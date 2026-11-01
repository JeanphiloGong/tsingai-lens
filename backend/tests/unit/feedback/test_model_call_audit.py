from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace

import httpx
from openai import APIStatusError, AsyncOpenAI
import pytest

from application.chat.context_builder import ChatModelContext
from application.chat.model import ModelResponseError
from application.chat.session_service import RepositoryModelCallObserver
from domain.chat import ChatMessage, ChatSession
from infra.llm.chat_model import OpenAIChatModel
from repositories.chat_repository import ChatRepository
from tests.support.postgres import seed_collection

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Completions:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls: list[dict] = []
        self.error = error

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="answer", tool_calls=[]),
                finish_reason="stop",
            )],
            usage=None,
        )


class _Observer:
    def __init__(self) -> None:
        self.started: list[dict] = []
        self.finished: list[tuple[str, dict]] = []

    async def start(
        self, *, session_id, trigger_message_id, response_message_id, purpose, request
    ) -> str:
        self.started.append({
            "session_id": session_id,
            "trigger_message_id": trigger_message_id,
            "response_message_id": response_message_id,
            "purpose": purpose,
            "request": request,
        })
        return "call-1"

    async def finish(
        self, call_id, *, status, finished_at, error_code=None,
        prompt_tokens=None, completion_tokens=None, total_tokens=None,
    ) -> None:
        self.finished.append((call_id, {
            "status": status,
            "finished_at": finished_at,
            "error_code": error_code,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }))


def _client(completions: _Completions):
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions), options={})
    client.with_options = lambda **kwargs: client
    return client


def _context(observer: _Observer) -> ChatModelContext:
    message = ChatMessage.user(
        message_id="question-1",
        session_id="session-1",
        content="Compare A and B.",
        created_at="2026-09-24T00:00:00+00:00",
    )
    return ChatModelContext(
        (message,),
        active_user_message_id="question-1",
        model_call_observer=observer,
        model_call_session_id="session-1",
        model_call_response_message_id="answer-1",
    )


async def test_audit_snapshot_is_identical_to_provider_request() -> None:
    completions = _Completions()
    observer = _Observer()
    await OpenAIChatModel(client=_client(completions), model="audit-model").respond(
        context=_context(observer), tool_specs=()
    )
    assert observer.started[0]["request"] == completions.calls[0]
    assert observer.started[0]["purpose"] == "decision"
    assert observer.finished[0][1]["status"] == "provider_succeeded"


async def test_audit_records_provider_failure_without_persisting_error_body() -> None:
    completions = _Completions(error=APIStatusError(
        "secret provider body",
        response=httpx.Response(408, request=httpx.Request("POST", "https://provider.invalid")),
        body={"error": {"message": "secret provider body"}},
    ))
    observer = _Observer()
    with pytest.raises(ModelResponseError) as failure:
        await OpenAIChatModel(client=_client(completions), model="audit-model").respond(
            context=_context(observer), tool_specs=()
        )
    assert failure.value.reason == "provider_timeout"
    assert observer.finished[0][1]["status"] == "provider_failed"
    assert observer.finished[0][1]["error_code"] == "provider_timeout"
    assert "secret" not in str(observer.finished[0][1])


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "status,error_code",
    [
        ("provider_succeeded", None),
        ("provider_failed", "http_status"),
        ("response_invalid", "empty_response"),
        ("cancelled", "request_cancelled"),
    ],
)
async def test_sdk_audit_persists_outcome_and_keeps_completed_call_immutable(
    postgres_session_factory, streaming, status, error_code,
) -> None:
    await seed_collection(postgres_session_factory, "audit-collection")
    repository = ChatRepository()
    observer = RepositoryModelCallObserver()
    context = _context(observer)
    await repository.add_session(ChatSession.create(
        session_id="session-1", user_id="user-1", collection_id="audit-collection",
        created_at=context.messages[0].created_at,
    ))
    requests = []
    usage = {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    key = "synthetic-audit-test-key"

    async def provider(request):
        requests.append(json.loads(request.content))
        # The exact call is already durable before dispatch to the provider.
        recorded, = await repository.read_model_calls("session-1")
        assert recorded.status == "recorded" and recorded.finished_at is None
        assert recorded.request == {**requests[-1], "timeout": model.request_timeout}
        if status == "cancelled":
            raise asyncio.CancelledError
        if status == "provider_failed":
            return httpx.Response(500, json={"error": {"message": "private provider body"}})
        content = "" if status == "response_invalid" else "Compare the test conditions first."
        message = {"role": "assistant", "content": content}
        payload = {
            "id": "audit-completion", "created": 0, "model": "audit-model",
            "object": "chat.completion.chunk" if streaming else "chat.completion",
            "choices": [{
                "index": 0, "finish_reason": "stop",
                "delta" if streaming else "message": message,
            }],
            "usage": usage,
        }
        if streaming:
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"},
                text=f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http_client:
        async with AsyncOpenAI(
            api_key=key, base_url="https://provider.invalid/v1", http_client=http_client,
        ) as client:
            model = OpenAIChatModel(client=client, model="audit-model")
            if error_code is None:
                result = await model.respond(
                    context=context, tool_specs=(),
                    text_delta_callback=(lambda _: None) if streaming else None,
                )
                assert result.content == "Compare the test conditions first."
            else:
                error_type = asyncio.CancelledError if status == "cancelled" else ModelResponseError
                with pytest.raises(error_type):
                    await model.respond(
                        context=context, tool_specs=(),
                        text_delta_callback=(lambda _: None) if streaming else None,
                    )

    saved, = await ChatRepository().read_model_calls("session-1")
    assert len(requests) == 1
    assert saved.trigger_message_id == "question-1"
    assert saved.response_message_id == "answer-1"
    assert saved.purpose == "decision" and saved.model == "audit-model"
    assert saved.status == status and saved.error_code == error_code
    assert saved.provider_confirmed is (status == "provider_succeeded")
    assert saved.finished_at is not None
    expected_tokens = (12, 3, 15) if status in {"provider_succeeded", "response_invalid"} else (None, None, None)
    assert (saved.prompt_tokens, saved.completion_tokens, saved.total_tokens) == expected_tokens
    assert saved.request_digest == sha256(json.dumps(
        saved.request, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert key not in str(saved) and "private provider body" not in str(saved)

    # Retrying completion cannot replace the recorded time, usage or outcome.
    await observer.finish(
        saved.call_id, status=status, finished_at=datetime.now(timezone.utc).isoformat(),
        error_code="replacement", prompt_tokens=99, completion_tokens=99, total_tokens=198,
    )
    assert await repository.read_model_call("session-1", saved.call_id) == saved
    with pytest.raises(ValueError, match="outcome cannot be reassigned"):
        await observer.finish(
            saved.call_id,
            status="provider_failed" if status == "provider_succeeded" else "provider_succeeded",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    assert await repository.read_model_calls("session-1") == (saved,)
