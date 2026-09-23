from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.chat import ChatModelContext
from application.chat.model_calls import ModelCallInput, ModelCallOutcome
from domain.chat import ChatMessage
from infra.llm.chat_model import OpenAIChatModel


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Completions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="The answer", tool_calls=[]),
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
        return "model_call_test"

    async def finish(self, call_id: str, outcome: ModelCallOutcome) -> None:
        self.finished.append((call_id, outcome))


def _client(completions: _Completions):
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions), options={}
    )
    client.with_options = lambda **kwargs: client
    return client


def _message() -> ChatMessage:
    return ChatMessage.user(
        message_id="msg-question",
        session_id="chat-test",
        content="Compare the two papers.",
        created_at="2026-09-23T00:00:00+00:00",
    )


async def test_capture_is_the_same_json_sent_to_the_provider() -> None:
    completions = _Completions()
    observer = _Observer()
    context = ChatModelContext(
        (_message(),),
        active_user_message_id="msg-question",
        model_call_observer=observer,
        model_call_response_message_id="msg-answer",
        model_call_session_id="chat-test",
    )

    await OpenAIChatModel(client=_client(completions), model="test-model").respond(
        context=context, tool_specs=()
    )

    assert len(observer.started) == 1
    assert observer.started[0].request == completions.calls[0]
    assert observer.started[0].trigger_message_id == "msg-question"
    assert observer.started[0].response_message_id == "msg-answer"
    assert observer.finished[0][0] == "model_call_test"
    assert observer.finished[0][1].status == "provider_succeeded"


async def test_capture_failure_prevents_provider_submission() -> None:
    completions = _Completions()

    class FailingObserver(_Observer):
        async def start(self, call: ModelCallInput) -> str:
            raise RuntimeError("storage unavailable")

    context = ChatModelContext(
        (_message(),), model_call_observer=FailingObserver(), model_call_session_id="chat-test"
    )
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await OpenAIChatModel(client=_client(completions), model="test-model").respond(
            context=context, tool_specs=()
        )
    assert completions.calls == []
