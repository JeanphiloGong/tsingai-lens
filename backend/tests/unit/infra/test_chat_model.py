from __future__ import annotations

from application.chat import ChatModelContext

from types import SimpleNamespace
import asyncio

import httpx
from openai import AsyncOpenAI
import pytest
from pydantic import BaseModel, ConfigDict

from application.chat import ToolSpec
from application.chat.model import (
    ModelUsage,
    ModelResponseError,
    ModelTurn,
    RESEARCH_AGENT_PROMPT_VERSION,
    RESEARCH_AGENT_SYSTEM_PROMPT,
)
from domain.chat import ChatMessage, ChatResourceRef, ChatSourceContext, ToolRisk
from infra.llm.chat_model import OpenAIChatModel


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def close(self):
        self.closed = True


class _Completions:
    def __init__(self, response) -> None:  # noqa: ANN001
        self.response = response
        self.calls: list[dict] = []
        self.stream = None

    async def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            self.stream = _Stream(self.response)
            return self.stream
        return self.response


def _client(response):  # noqa: ANN001, ANN202
    completions = _Completions(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions), options={})
    def with_options(**kwargs):
        client.options.update(kwargs)
        return client
    client.with_options = with_options
    return client, completions


def _completion(*, content: str | None = None, tool_calls: list | None = None,
                finish_reason: str = "stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        model="test-model",
        usage=None,
    )


def _stream_chunk(
    *,
    content: str | None = None,
    tool_calls: list | None = None,
    usage=None,  # noqa: ANN001
    finish_reason=None,
):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)]
        if content is not None or tool_calls or finish_reason else [],
        model="test-model",
        usage=usage,
    )


def _message() -> ChatMessage:
    return ChatMessage.user(
        message_id="msg-1",
        session_id="chat-1",
        content="你好",
        created_at="2026-08-19T00:00:00+00:00",
    )


def test_research_agent_prompt_keeps_default_answers_researcher_facing() -> None:
    prompt = " ".join(RESEARCH_AGENT_SYSTEM_PROMPT.split())

    assert RESEARCH_AGENT_PROMPT_VERSION == "research-agent-v14.0"
    assert "Match the user's language" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "research question" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "research conclusion" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "supporting source" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Never expose registered tool names" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "never restart the greeting or capability introduction" in prompt
    assert "Use onboarding only for an actual greeting" in prompt
    assert "A paper survey and a Source search are navigation steps" in prompt
    assert "complete, untruncated canonical content and its digest" in prompt
    assert "the actual transient plan draft before answering" in prompt
    assert "Never describe an unmentioned value as researcher-specified" in prompt
    assert "insufficient map" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "inspect that paper's Sources" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "it is not verified Evidence" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "inspect the exact complete Finding" in prompt
    assert "does not create a new Finding" in prompt
    assert "Never reconstruct a complete Finding from a summary" in prompt
    assert "record or correct Evidence" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "exact complete Source" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "`read_source`" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "create_evidence_version" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Evidence draft" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Finding draft" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Source-to-Evidence write" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "analysis authored by you" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "publish_agent_objective_analysis" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "publishes no Finding" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "derive_objective" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "propose_research_plan" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "create_research_plan" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "technical extraction failure" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Never expose hidden chain-of-thought" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "candidate creation" in RESEARCH_AGENT_SYSTEM_PROMPT.lower()
    assert "confirm_objective" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert (
        "candidate creation, objective confirmation, and analysis start"
        in RESEARCH_AGENT_SYSTEM_PROMPT.lower()
    )


def test_prompt_splits_multi_outcome_interest_before_scope_screening() -> None:
    prompt = " ".join(RESEARCH_AGENT_SYSTEM_PROMPT.split())
    assert (
        "split it into separate focused questions before scope screening"
        in prompt
    )
    assert "one intervention question and exactly one outcome" in prompt
    assert "Outcomes never belong in the variables list" in prompt
    assert "preview each focused question separately" in prompt
    assert "Preserve every material explicitly named" in prompt
    assert "do not leave scientific scope only" in prompt
    assert "uncertainty, not grounds to exclude a same-material paper" in prompt


def test_prompt_separates_product_questions_from_collection_reads() -> None:
    assert "application's purpose" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "without calling a tool" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "current collection's contents" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "browse the visible paper" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "screening only" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "researcher may add" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "one highest-information clarification question" in RESEARCH_AGENT_SYSTEM_PROMPT


def test_openai_chat_model_uses_the_global_model_setting(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "global-model")
    monkeypatch.setenv("RESEARCH_AGENT_LLM_MODEL", "retired-agent-model")
    client, _completions = _client(_completion(content="ok"))

    model = OpenAIChatModel(client=client)

    assert model.model == "global-model"


async def test_openai_chat_model_returns_an_ordinary_answer_without_tools() -> None:
    client, completions = _client(_completion(content="你好，我可以帮助分析文献。"))
    model = OpenAIChatModel(client=client, model="test-model")

    turn = await model.respond(context=ChatModelContext((_message(),)), tool_specs=())

    assert turn.content == "你好，我可以帮助分析文献。"
    assert turn.tool_calls == ()
    request = completions.calls[0]
    assert request["messages"][0]["role"] == "system"
    assert request["messages"][1] == {"role": "user", "content": "你好"}
    assert "tools" not in request


@pytest.mark.parametrize("stream", [False, True])
async def test_provider_usage_includes_usage_only_stream_chunk(stream: bool) -> None:
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150)
    response = _completion(content="Done")
    response.usage = usage
    client, _ = _client(
        [_stream_chunk(content="Done"), _stream_chunk(usage=usage)] if stream else response
    )

    turn = await OpenAIChatModel(client=client, model="test-model").respond(
        context=ChatModelContext((_message(),)), tool_specs=(),
        text_delta_callback=(lambda _text: None) if stream else None,
    )

    assert turn.usage == ModelUsage(120, 30, 150)


@pytest.mark.parametrize("stream", [False, True])
async def test_model_request_enforces_output_timeout_and_no_hidden_retries(stream: bool) -> None:
    client, completions = _client([_stream_chunk(content="Done")] if stream else _completion(content="Done"))
    await OpenAIChatModel(client=client, model="test-model").respond(
        context=ChatModelContext((_message(),)), tool_specs=(),
        timeout_seconds=4.5, max_output_tokens=500,
        text_delta_callback=(lambda _: None) if stream else None,
    )

    assert completions.calls[0]["max_completion_tokens"] == 500
    assert completions.calls[0]["timeout"] == 4.5
    assert client.options["max_retries"] == 0
    if stream:
        assert completions.stream.closed


@pytest.mark.parametrize("stream", [False, True])
async def test_length_limited_answer_is_not_a_complete_model_turn(stream: bool) -> None:
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150)
    response = _completion(content="Paper A reports", finish_reason="length")
    response.usage = usage
    client, completions = _client(
        [_stream_chunk(content="Paper A reports"), _stream_chunk(finish_reason="length"),
         _stream_chunk(usage=usage)] if stream else response
    )
    with pytest.raises(ModelResponseError) as error:
        await OpenAIChatModel(client=client, model="test-model").respond(
            context=ChatModelContext((_message(),)), tool_specs=(),
            text_delta_callback=(lambda _: None) if stream else None,
        )
    assert error.value.reason == "output_token_limit"
    assert not error.value.retryable
    assert error.value.usage == ModelUsage(120, 30, 150)
    if stream:
        assert completions.stream.closed


async def test_cancelled_openai_stream_closes_the_underlying_http_response() -> None:
    started = asyncio.Event()
    closed = asyncio.Event()

    class StalledBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b""  # pragma: no cover

        async def aclose(self):
            closed.set()

    transport = httpx.MockTransport(lambda _: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=StalledBody(),
    ))
    async with httpx.AsyncClient(transport=transport) as http:
        async with AsyncOpenAI(api_key="test-only", http_client=http) as client:
            model = OpenAIChatModel(client=client, model="test-model")
            task = asyncio.create_task(model.respond(
                context=ChatModelContext((_message(),)), tool_specs=(),
                text_delta_callback=lambda _: None,
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert closed.is_set()


async def test_rollover_is_a_separate_system_message_without_mutating_history() -> None:
    messages = (_message(),)
    context = ChatModelContext(messages, '{"entries":[{"source_ref":"methods-1"}]}')
    client, completions = _client(_completion(content="Re-read the Source."))

    await OpenAIChatModel(client=client, model="test-model").respond(context=context, tool_specs=())

    provider_messages = completions.calls[0]["messages"]
    assert [item["role"] for item in provider_messages] == ["system", "system", "user"]
    assert "deterministic lineage" in provider_messages[1]["content"]
    assert context.rollover_summary in provider_messages[1]["content"]
    assert context.messages == messages
    assert messages[0].content == "你好"


async def test_openai_chat_model_marks_selected_canonical_source_as_not_yet_evidence() -> None:
    client, completions = _client(_completion(content="This passage reports one measured result."))
    model = OpenAIChatModel(client=client, model="test-model")
    message = ChatMessage.user(
        message_id="msg-source",
        session_id="chat-1",
        content="What does this passage support?",
        created_at="2026-08-31T00:00:00+00:00",
        source_contexts=(
            ChatSourceContext(
                resource_ref=ChatResourceRef(
                    resource_type="source",
                    resource_id="doc-1:results",
                    href=(
                        "/collections/col-1/documents/doc-1"
                        "?view=parsed-paper&source_ref=results&page=3"
                    ),
                ),
                collection_id="col-1",
                document_id="doc-1",
                document_title="Paper A",
                source_kind="text_window",
                source_ref="results",
                page=3,
                quote="Conductivity improved to 12 mS/cm under EIS.",
                heading_path="Results",
            ),
        ),
    )

    await model.respond(context=ChatModelContext((message,)), tool_specs=())

    provider_content = completions.calls[0]["messages"][1]["content"]
    assert "USER-SELECTED SOURCE CONTEXT" in provider_content
    assert "not yet verified Evidence" in provider_content
    assert '"document_id":"doc-1"' in provider_content
    assert '"source_ref":"results"' in provider_content
    assert "Conductivity improved to 12 mS/cm under EIS." in provider_content
    assert provider_content.endswith("What does this passage support?")


async def test_openai_chat_model_parses_one_typed_tool_call() -> None:
    tool_call = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(
            name="get_collection_context",
            arguments='{"include_documents":true}',
        ),
    )
    client, completions = _client(_completion(tool_calls=[tool_call]))
    model = OpenAIChatModel(client=client, model="test-model")
    spec = ToolSpec(
        name="get_collection_context",
        description="Read bounded collection context.",
        risk=ToolRisk.READ,
        input_model=_NoArguments,
    )

    turn = await model.respond(context=ChatModelContext((_message(),)), tool_specs=(spec,))

    assert turn.tool_calls != ()
    assert turn.tool_calls[0].name == "get_collection_context"
    assert turn.tool_calls[0].arguments == {"include_documents": True}
    request = completions.calls[0]
    assert request["parallel_tool_calls"] is True
    assert request["tools"][0]["function"]["name"] == "get_collection_context"


async def test_openai_chat_model_streams_text_and_returns_the_complete_turn() -> None:
    client, completions = _client(
        iter(
            (
                _stream_chunk(content="这批"),
                _stream_chunk(content="论文"),
                _stream_chunk(usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=2,
                    total_tokens=12,
                )),
            )
        )
    )
    model = OpenAIChatModel(client=client, model="test-model")
    deltas: list[str] = []

    turn = await model.respond(
        context=ChatModelContext((_message(),)),
        tool_specs=(),
        text_delta_callback=deltas.append,
    )

    assert deltas == ["这批", "论文"]
    assert turn.content == "这批论文"
    assert turn.usage is not None
    assert turn.usage.total_tokens == 12
    request = completions.calls[0]
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}


async def test_openai_chat_model_reassembles_one_streamed_tool_call() -> None:
    first = SimpleNamespace(
        index=0,
        id="provider-call-0",
        type="function",
        function=SimpleNamespace(name="get_collection_context", arguments=""),
    )
    second = SimpleNamespace(
        index=0,
        id=None,
        type=None,
        function=SimpleNamespace(name=None, arguments="{}"),
    )
    client, _completions = _client(
        iter(
            (
                _stream_chunk(tool_calls=[first]),
                _stream_chunk(tool_calls=[second]),
            )
        )
    )
    model = OpenAIChatModel(client=client, model="test-model")

    turn = await model.respond(
        context=ChatModelContext((_message(),)),
        tool_specs=(),
        text_delta_callback=lambda _content: None,
    )

    assert turn.tool_calls != ()
    assert turn.tool_calls[0].name == "get_collection_context"
    assert turn.tool_calls[0].arguments == {}


async def test_openai_chat_model_serializes_provider_multiple_tool_calls() -> None:
    first = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name="preview_research_scope", arguments='{"outcomes":["ductility"]}'),
    )
    second = SimpleNamespace(
        id="call-2",
        type="function",
        function=SimpleNamespace(name="preview_research_scope", arguments='{"outcomes":["strength"]}'),
    )
    client, _completions = _client(_completion(tool_calls=[first, second]))
    model = OpenAIChatModel(client=client, model="test-model")

    turn = await model.respond(context=ChatModelContext((_message(),)), tool_specs=())

    assert turn.tool_calls != ()
    assert turn.tool_calls[0].name == "preview_research_scope"
    assert turn.tool_calls[0].arguments == {"outcomes": ["ductility"]}
    assert len(turn.tool_calls) == 2
    assert turn.tool_calls[1].arguments == {"outcomes": ["strength"]}


async def test_openai_chat_model_serializes_streamed_provider_multiple_tool_calls() -> None:
    first = SimpleNamespace(
        index=0,
        id="call-1",
        type="function",
        function=SimpleNamespace(
            name="preview_research_scope",
            arguments='{"outcomes":["ductility"]}',
        ),
    )
    second = SimpleNamespace(
        index=1,
        id="call-2",
        type="function",
        function=SimpleNamespace(
            name="preview_research_scope",
            arguments='{"outcomes":["strength"]}',
        ),
    )
    client, _completions = _client(
        iter((_stream_chunk(tool_calls=[first, second]),))
    )
    model = OpenAIChatModel(client=client, model="test-model")

    turn = await model.respond(
        context=ChatModelContext((_message(),)),
        tool_specs=(),
        text_delta_callback=lambda _content: None,
    )

    assert turn.tool_calls != ()
    assert turn.tool_calls[0].name == "preview_research_scope"
    assert turn.tool_calls[0].arguments == {"outcomes": ["ductility"]}
    assert len(turn.tool_calls) == 2
    assert turn.tool_calls[1].arguments == {"outcomes": ["strength"]}


async def test_openai_chat_model_rejects_non_object_tool_arguments() -> None:

    invalid = SimpleNamespace(
        id="call-3",
        type="function",
        function=SimpleNamespace(name="one", arguments="[]"),
    )
    client, _completions = _client(_completion(tool_calls=[invalid]))
    model = OpenAIChatModel(client=client, model="test-model")

    with pytest.raises(ModelResponseError, match="invalid tool arguments") as exc_info:
        await model.respond(context=ChatModelContext((_message(),)), tool_specs=())

    assert exc_info.value.reason == "invalid_tool_arguments"


async def test_openai_chat_model_marks_empty_stream_as_invalid_response() -> None:
    client, _completions = _client(
        iter((_stream_chunk(usage=SimpleNamespace(total_tokens=0)),))
    )
    model = OpenAIChatModel(client=client, model="test-model")

    with pytest.raises(ModelResponseError) as exc_info:
        await model.respond(
            context=ChatModelContext((_message(),)),
            tool_specs=(),
            text_delta_callback=lambda _content: None,
        )

    assert exc_info.value.reason == "empty_response"
    assert exc_info.value.partial_content is False


async def test_openai_chat_model_marks_stream_iterator_value_error_as_invalid_response() -> None:
    class BrokenStream:
        def __iter__(self):
            raise ValueError("invalid provider stream")
            yield  # pragma: no cover

    client, _completions = _client(BrokenStream())
    model = OpenAIChatModel(client=client, model="test-model")

    with pytest.raises(ModelResponseError) as exc_info:
        await model.respond(
            context=ChatModelContext((_message(),)),
            tool_specs=(),
            text_delta_callback=lambda _content: None,
        )

    assert exc_info.value.reason == "invalid_stream"
    assert exc_info.value.partial_content is False
    assert _completions.stream.closed
