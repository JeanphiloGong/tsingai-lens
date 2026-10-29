from __future__ import annotations

from domain.chat import ChatMessageRole, ToolResultStatus

from dataclasses import asdict

from domain.chat import ChatToolRequest

import json
from hashlib import sha256

import httpx
import pytest
from openai import AsyncOpenAI

from application.auth.session_service import SESSION_COOKIE_NAME, AuthSessionService
from application.chat import CapabilityRegistry, ChatContextBuilder, ResearchAgentRunner
from application.chat.session_service import RepositoryModelCallObserver
from domain.chat import ChatMessage, ChatToolCall, ChatToolResult, ToolRisk
from infra.llm.chat_model import OpenAIChatModel
from repositories.auth_repository import AuthRepository
from tests.integration.persistence.test_chat_branches import NOW, branch_app  # noqa: F401
from tests.integration.persistence.test_chat_response_recovery import _server

pytestmark = pytest.mark.anyio


async def test_http_context_recovery_persists_trajectory_budget_and_provider_reason(branch_app):
    """Exercise real HTTP, SDK parsing and PostgreSQL with an offline provider."""
    fixture = branch_app
    session = await fixture.service.create_session(collection_id="collection", user_id=fixture.owner)
    history = [ChatMessage.user(message_id="prior-request", session_id=session.session_id,
                                content="Read the paper results before comparing elongation.", created_at=NOW)]
    calls, results = [], []
    for index in range(10):
        call = ChatToolCall.requested(
            tool_call_id=f"prior-read-{index}", session_id=session.session_id,
            assistant_message_id=f"prior-call-{index}", name="read_source",
            arguments={"document_id": "paper", "source_kind": "text_window", "source_ref": f"results-{index}"},
            risk=ToolRisk.READ,
        ).start(NOW).succeed(NOW)
        content = "Synthetic prior paper result; material state and tensile orientation constrain comparison. " * 900
        result = ChatToolResult(tool_call_id=call.tool_call_id, status=ToolResultStatus.SUCCEEDED, data={
            **call.arguments, "content": content, "source_digest": sha256(content.encode()).hexdigest(),
            "content_truncated": False,
        })
        history.extend(
            (
                ChatMessage.assistant_tool_calls(
                    message_id=call.assistant_message_id,
                    session_id=session.session_id,
                    content="",
                    tool_calls=(
                        ChatToolRequest(
                            tool_call_id=call.tool_call_id,
                            name=call.name,
                            arguments=call.arguments,
                            position=call.position,
                            decision_user_id=call.decision_user_id,
                            decision_arguments_digest=call.decision_arguments_digest,
                            decided_at=call.decided_at,
                            decision_basis=call.decision_basis,
                            authorization_revision=call.authorization_revision,
                        ),
                    ),
                    created_at=NOW,
                ),
                ChatMessage(
                    message_id=f"prior-result-{index}",
                    session_id=session.session_id,
                    role=ChatMessageRole.TOOL,
                    content=json.dumps(
                        asdict(result),
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
                    created_at=NOW,
                    tool_call_id=result.tool_call_id,
                    tool_result=result,
                ),
            )
        )
        calls.append(call)
        results.append(result)
    await fixture.repository.save_trajectory(chat_session=session, messages=tuple(history),
                                             tool_calls=tuple(calls), tool_results=tuple(results))
    requests = []
    answer = "The available records do not establish a comparable elongation ranking."

    def provider(request):
        payload = json.loads(request.content)
        if payload.get("response_format"):
            content = '{"scope":"Match material and tensile conditions.","checks":[],"next_actions":[]}'
        else:
            requests.append(payload)
            if len(requests) == 1:
                return httpx.Response(400, json={"error": {"code": "context_length_exceeded", "message": "input too long"}})
            content = answer
        if payload.get("stream"):
            chunk = {"id": "offline-completion", "object": "chat.completion.chunk", "created": 0,
                     "model": "offline-test", "choices": [{"index": 0, "finish_reason": "stop",
                     "delta": {"content": content}}],
                     "usage": {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140}}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={
            "id": "offline-completion", "object": "chat.completion", "created": 0, "model": "offline-test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
        })

    auth = AuthSessionService(AuthRepository())
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as provider_http:
        async with AsyncOpenAI(api_key="offline-test", base_url="https://provider.invalid/v1", http_client=provider_http) as client:
            fixture.service.runner = ResearchAgentRunner(model=OpenAIChatModel(client=client, model="offline-test"),
                                                         capabilities=CapabilityRegistry(()))
            fixture.service.model_call_observer = RepositoryModelCallObserver(fixture.repository)
            async with _server(fixture.service, auth) as url:
                async with httpx.AsyncClient(base_url=url, cookies={SESSION_COOKIE_NAME: fixture.cookies[0]}, timeout=15) as browser:
                    path = f"/api/v1/chat-sessions/{session.session_id}"
                    response = await browser.post(f"{path}/messages", json={"message": "Compare the evidence already read; do not use tools."})
                    assert response.status_code == 200, response.text
                    assert response.json()["status"] == "completed"
                    restored = (await browser.get(f"{path}/messages")).json()
    assert len(requests) == 2
    sizes = [ChatContextBuilder.estimate_tokens(payload["messages"]) for payload in requests]
    assert sizes[1] < sizes[0]
    snapshot = await fixture.repository.read_response_snapshot(session.session_id)
    assert snapshot.status == "completed"
    assert snapshot.progress["context_recovery_attempts"] >= 1
    assert snapshot.progress["retry_count"] == snapshot.progress["context_recovery_attempts"]
    saved = await fixture.repository.read_messages(session.session_id)
    assert saved[:len(history)] == tuple(history)
    assert saved[-1].content == answer
    assert restored["items"][-1]["content"] == answer
    audits = await fixture.repository.read_model_calls(session_id=session.session_id)
    assert any(call.error_code == "context_window_exceeded" and call.status == "provider_failed" for call in audits)
    assert any(call.purpose == "decision" and call.status == "provider_succeeded" for call in audits)
