"""A model response can outlive the old request and finalization deadlines."""

import asyncio

import httpx
from openai import AsyncOpenAI
import pytest

from application.chat import AgentRunLimits, CapabilityRegistry, ModelTurn, ResearchAgentRunner
from application.chat.agent_runner import _RunProgress
import application.chat.agent_runner as runtime
from application.chat.context_builder import ChatModelContext
from domain.chat import ChatMessage
from infra.llm.chat_model import OpenAIChatModel


@pytest.fixture
def anyio_backend():
    return "asyncio"


def context():
    return ChatModelContext((ChatMessage.user(
        message_id="request", session_id="research", content="Summarize the reported experiments.",
        created_at="2026-11-02T00:00:00Z",
    ),))


@pytest.mark.anyio
@pytest.mark.parametrize("finalizing", [False, True])
async def test_default_model_wait_has_no_elapsed_deadline(monkeypatch, finalizing):
    now = [runtime.monotonic()]
    monkeypatch.setattr(runtime, "monotonic", lambda: now[0])

    class Model:
        async def respond(self, *, text_delta_callback, **options):
            assert options["timeout_seconds"] is None
            text_delta_callback("Reported ")
            now[0] += 181
            await asyncio.sleep(0)
            text_delta_callback("evidence.")
            now[0] += 181
            return ModelTurn(content="Reported evidence.")

    limits = AgentRunLimits()
    runner = ResearchAgentRunner(model=Model(), capabilities=CapabilityRegistry(()), limits=limits)
    chunks = []
    result = await runner._respond(context(), (), _RunProgress(limits), chunks.append, finalizing=finalizing)
    assert result.content == "".join(chunks) == "Reported evidence."


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True])
async def test_default_sdk_request_has_no_hidden_network_timeout(monkeypatch, streaming):
    # This shared setting still belongs to Core/feedback clients, not Chat.
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "180")
    requests = []

    async def respond(request):
        requests.append(request)
        if streaming:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
                'data: {"id":"reply","object":"chat.completion.chunk","model":"test-model",'
                '"choices":[{"index":0,"delta":{"content":"Evidence."},"finish_reason":null}]}\n\n'
                'data: {"id":"reply","object":"chat.completion.chunk","model":"test-model",'
                '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
                'data: [DONE]\n\n'
            ))
        return httpx.Response(200, json={
            "id": "reply", "object": "chat.completion", "model": "test-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Evidence."},
                         "finish_reason": "stop"}],
        })

    async with AsyncOpenAI(api_key="synthetic", base_url="https://model.invalid/v1",
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
        model = OpenAIChatModel(client=client, model="test-model")
        result = await model.respond(context=context(), tool_specs=(),
                                     text_delta_callback=(lambda _: None) if streaming else None)
    assert result.content == "Evidence."
    assert requests[0].extensions["timeout"] == {
        "connect": None, "read": None, "write": None, "pool": None,
    }
