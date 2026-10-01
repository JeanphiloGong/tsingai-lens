from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.chat.context_builder import ChatModelContext
from application.repositories.chat_repository import ModelCallInput, ModelCallOutcome
from domain.chat import ChatMessage
from infra.llm.chat_model import OpenAIChatModel

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
        self.started: list[ModelCallInput] = []
        self.finished: list[tuple[str, ModelCallOutcome]] = []

    async def start(self, call: ModelCallInput) -> str:
        self.started.append(call)
        return "call-1"

    async def finish(self, call_id: str, outcome: ModelCallOutcome) -> None:
        self.finished.append((call_id, outcome))


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
    assert observer.started[0].request == completions.calls[0]
    assert observer.started[0].purpose == "decision"
    assert observer.finished[0][1].status == "provider_succeeded"


async def test_audit_records_provider_failure_without_persisting_error_body() -> None:
    completions = _Completions(error=TimeoutError("secret provider body"))
    observer = _Observer()
    with pytest.raises(TimeoutError):
        await OpenAIChatModel(client=_client(completions), model="audit-model").respond(
            context=_context(observer), tool_specs=()
        )
    assert observer.finished[0][1].status == "provider_failed"
    assert observer.finished[0][1].error_code == "provider_timeout"
    assert "secret" not in str(observer.finished[0][1])
