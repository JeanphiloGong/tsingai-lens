"""Verify real PostgreSQL snapshot/audit binding through authenticated HTTP."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import httpx
from openai import AsyncOpenAI
import pytest
from sqlalchemy import update

from controllers.model_connection_routes import model_connection_router as model_router
from repositories.chat_repository import ChatRepository
from infra.persistence.postgres.models.model_connection import ModelConnectionORM
from tests.integration.persistence.test_chat_branches import branch_app  # noqa: F401

pytestmark = pytest.mark.anyio


async def test_sync_sse_audit_and_reconnect_read_the_persisted_binding(branch_app, monkeypatch):
    fixture = branch_app
    factory = fixture.factory
    now = datetime.now(timezone.utc)
    async with factory.begin() as database:
        database.add(ModelConnectionORM(
            connection_id="lab-a", display_name="Lab A", model="model-a",
            base_url="https://lab-a.example.invalid/v1", api_key_ref="env:LENS_MODEL_KEY_LAB_A",
            enabled=True, created_at=now, updated_at=now,
        ))
    token = "synthetic-binding-test-value"
    monkeypatch.setenv("LENS_MODEL_KEY_LAB_A", token)
    requests = []
    clients = []

    async def provider(request):
        requests.append(request)
        payload = json.loads(request.content)
        message = {"role": "assistant", "content": "Match the tensile test conditions before comparing."}
        if payload.get("stream"):
            chunk = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "model-a",
                     "choices": [{"index": 0, "delta": message, "finish_reason": "stop"}]}
            return httpx.Response(200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
                                  headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 1, "model": "model-a",
                                        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]})

    def build_client(**kwargs):
        client = AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
        clients.append(client)
        return client

    monkeypatch.setattr("infra.llm.chat_model.AsyncOpenAI", build_client)
    fixture.client._transport.app.include_router(model_router, prefix="/api/v1")
    sessions = []
    for headers in ({}, {"Accept": "text/event-stream"}):
        created = await fixture.client.post("/api/v1/chat-sessions", json={"collection_id": "collection"})
        session_id = created.json()["data"]["session_id"]
        sessions.append(session_id)
        response = await fixture.client.post(f"/api/v1/chat-sessions/{session_id}/messages", headers=headers,
            json={"message": "Which conditions should I match? Explain without tools.", "model_connection_id": "lab-a"})
        assert response.status_code == 200, response.text
        if headers:
            assert 'event: turn' in response.text
            assert 'event: error' not in response.text
        else:
            assert response.json()["code"] == 200, response.text
    fresh = ChatRepository()
    for session_id in sessions:
        snapshot = await fresh.read_response_snapshot(session_id)
        calls = await fresh.read_model_calls(session_id)
        assert snapshot.status == "completed"
        assert snapshot.model_connection_id == "lab-a"
        assert calls and all(call.model_connection_id == "lab-a" for call in calls)
        response = await fixture.client.get(f"/api/v1/chat-sessions/{session_id}/events", params={"response_id": snapshot.response_id})
        assert response.status_code == 200
        assert len(await fresh.read_model_calls(session_id)) == len(calls)
        assert token not in str(snapshot) + str(calls) + response.text
    assert len(requests) == 2 and all(client.is_closed() for client in clients)
    async with factory.begin() as database:
        await database.execute(update(ModelConnectionORM).values(enabled=False))
    directory = await fixture.client.get("/api/v1/model-connections")
    assert directory.json()["code"] == 200 and directory.json()["data"] == {"items": []}
    refused = await fixture.client.post(f"/api/v1/chat-sessions/{sessions[0]}/messages",
        json={"message": "Another question", "model_connection_id": "lab-a"})
    assert refused.status_code == 200 and refused.json()["code"] == 200204 and len(requests) == 2


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_other_worker_recovers_saved_decision_through_http(branch_app, decision, monkeypatch):
    from application.chat import CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
    from application.chat.session_service import ChatSessionService
    from infra.llm import chat_model as provider_module
    from infra.llm.chat_model import OpenAIChatModel
    from tests.unit.application.test_chat_model_connections import ClosableModel
    from tests.unit.application.test_chat_session_service import _WriteCapability

    fixture = branch_app
    fixture.client._transport.app.include_router(model_router, prefix="/api/v1")
    now = datetime.now(timezone.utc)
    async with fixture.factory.begin() as database:
        database.add(ModelConnectionORM(
            connection_id="lab-a", display_name="Lab A", model="model-a",
            base_url="https://lab-a.example.invalid/v1", api_key_ref="env:LENS_MODEL_KEY_LAB_A",
            enabled=True, created_at=now, updated_at=now,
        ))
    selected = []
    clients = []

    def build_model(*, model, **options):
        turns = ([ModelTurn(tool_calls=(ModelToolCall(
            "create_objective_candidate", {"question": "Compare LPBF evidence"},
        ),))] if not selected else [ModelTurn(content="Preserve the original research context.")])
        selected.append(model)
        client = ClosableModel(*turns)
        clients.append(client)
        return client

    first = fixture.service
    monkeypatch.setattr(provider_module, "OpenAIChatModel", build_model)
    monkeypatch.setenv("LENS_MODEL_KEY_LAB_A", "synthetic-test-value")
    session = await first.create_session(collection_id="collection", user_id=fixture.owner)
    turn = await first.send_message(session.session_id, fixture.owner,
        message="Save the research objective.", model_connection_id="lab-a")
    pending = turn["pending_approval"]
    assert pending is not None
    async with fixture.factory.begin() as database:
        await database.execute(update(ModelConnectionORM).values(enabled=False))
        database.add(ModelConnectionORM(
            connection_id="lab-b", display_name="Lab B", model="model-b",
            base_url="https://lab-a.example.invalid/v1", api_key_ref=None,
            enabled=True, created_at=now, updated_at=now,
        ))
    directory = (await fixture.client.get("/api/v1/model-connections")).json()
    assert [item["connection_id"] for item in directory["data"]["items"]] == ["lab-b"]
    write = _WriteCapability()
    second = ChatSessionService(
        runner=ResearchAgentRunner(model=first.runner.model, capabilities=CapabilityRegistry((write,))),
    )
    monkeypatch.setattr("application.chat.session_service.ChatService", second)
    monkeypatch.setattr(provider_module, "OpenAIChatModel", OpenAIChatModel)
    monkeypatch.delenv("LENS_MODEL_KEY_LAB_A", raising=False)
    path = f"/api/v1/chat-sessions/{session.session_id}"
    body = {"arguments_digest": pending.arguments_digest, "decision": decision}
    response = await fixture.client.post(f"{path}/tool-calls/{pending.tool_call_id}/decision", json=body)
    assert response.status_code == 200 and response.json()["code"] == 200205
    assert response.json()["data"]["code"] == "model_connection_key_unavailable"
    saved = await fixture.repository.read_tool_call(pending.tool_call_id)
    assert saved.status.value == decision and write.executed == []
    trajectory = (await fixture.client.get(f"{path}/messages")).json()["data"]
    assert trajectory["pending_approval"] is None and not trajectory["running"]
    assert trajectory["retryable_decision"]["tool_call_id"] == pending.tool_call_id
    assert trajectory["retryable_decision"]["status"] == decision
    assert selected == ["model-a"]  # GET observation did not construct a client or execute.

    # A third instance sees only durable state, as it would after a reload/restart.
    third = ChatSessionService(
        runner=ResearchAgentRunner(model=first.runner.model, capabilities=CapabilityRegistry((write,))),
    )
    monkeypatch.setattr("application.chat.session_service.ChatService", third)
    monkeypatch.setattr(provider_module, "OpenAIChatModel", build_model)
    monkeypatch.setenv("LENS_MODEL_KEY_LAB_A", "synthetic-restored-key")
    response = await fixture.client.post(f"{path}/tool-calls/{pending.tool_call_id}/decision", json=body)
    assert response.status_code == 200 and response.json()["data"]["status"] == "completed", response.text
    snapshot = await fixture.repository.read_response_snapshot(session.session_id)
    assert snapshot.model_connection_id == "lab-a"
    assert selected == ["model-a", "model-a"] and all(model.closed for model in clients)
    assert len(write.executed) == (1 if decision == "approved" else 0)
    messages = await fixture.repository.read_messages(session.session_id)
    assert sum(item.tool_result is not None and item.tool_result.tool_call_id == pending.tool_call_id
               for item in messages) == 1
    trajectory = (await fixture.client.get(f"{path}/messages")).json()["data"]
    assert trajectory["retryable_decision"] is None and trajectory["response"]["status"] == "completed"
    response_id = snapshot.response_id
    repeated = await fixture.client.post(f"{path}/tool-calls/{pending.tool_call_id}/decision", json=body)
    assert repeated.status_code == 200 and repeated.json()["code"] == 200
    assert (await fixture.repository.read_response_snapshot(session.session_id)).response_id == response_id
    assert selected == ["model-a", "model-a"] and len(write.executed) == (1 if decision == "approved" else 0)
