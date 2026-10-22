from __future__ import annotations

from application.chat import ChatModelContext

import asyncio
import logging
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI
import pytest
from pydantic import BaseModel, ConfigDict

from application.chat import ToolSpec
from application.chat.model import (
    AGENT_MISSION,
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


@pytest.mark.parametrize("arguments", [None, "", "{}"])
async def test_stream_distinguishes_missing_arguments_from_explicit_empty_object(arguments):
    client, _ = _client([_stream_chunk(tool_calls=[SimpleNamespace(
        index=0, type="function", function=SimpleNamespace(name="inspect", arguments=arguments),
    )])])
    model = OpenAIChatModel(client=client, model="test-model")
    kwargs = dict(context=ChatModelContext((_message(),)), tool_specs=(), text_delta_callback=lambda _: None)
    if arguments == "{}":
        turn = await model.respond(**kwargs)
        assert turn.tool_calls[0].arguments == {}
    else:
        with pytest.raises(ModelResponseError) as error:
            await model.respond(**kwargs)
        assert error.value.reason == "stream_tool_arguments_missing"
        assert error.value.retryable and not error.value.partial_content


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("effort", [None, "", " none ", "low"])
async def test_chat_forwards_the_configured_reasoning_effort(monkeypatch, stream, effort):
    if effort is None:
        monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("LLM_REASONING_EFFORT", effort)
    client, completions = _client(
        [_stream_chunk(content="The plan is ready for review.")]
        if stream else _completion(content="The plan is ready for review.")
    )
    model = OpenAIChatModel(client=client, model="test-model")
    await model.respond(context=ChatModelContext((_message(),)), tool_specs=(),
                        text_delta_callback=(lambda text: None) if stream else None)
    if effort and effort.strip():
        assert completions.calls[0]["reasoning_effort"] == effort.strip()
    else:
        assert "reasoning_effort" not in completions.calls[0]


@pytest.mark.parametrize("stream", [False, True])
async def test_context_compaction_uses_json_without_executable_tools(stream):
    from application.chat.model import RESEARCH_COMPACTION_SYSTEM_PROMPT

    client, completions = _client([_stream_chunk(content='{"checks": []}')] if stream
                                  else _completion(content='{"checks": []}'))
    context = ChatModelContext((_message(),), compacting=True)
    await OpenAIChatModel(client=client, model="test-model").respond(
        context=context, tool_specs=(), text_delta_callback=(lambda _: None) if stream else None,
    )
    request = completions.calls[0]
    assert request["messages"][0]["content"] == RESEARCH_COMPACTION_SYSTEM_PROMPT
    assert request["response_format"] == {"type": "json_object"}
    assert "tools" not in request
    assert "你好" in str(request["messages"])


async def test_context_compaction_rejects_executable_tools():
    client, completions = _client(_completion(content="Unused"))
    with pytest.raises(ValueError, match="cannot expose"):
        await OpenAIChatModel(client=client).respond(
            context=ChatModelContext((), compacting=True),
            tool_specs=(ToolSpec(name="write", description="Write", risk=ToolRisk.WRITE, input_model=_NoArguments),),
        )
    assert completions.calls == []


def test_research_agent_prompt_keeps_default_answers_researcher_facing() -> None:
    prompt = " ".join(RESEARCH_AGENT_SYSTEM_PROMPT.split())

    assert RESEARCH_AGENT_PROMPT_VERSION == "research-agent-v16.8"
    for section in (
        "AGENT MISSION",
        "FOUR-LAYER RESPONSIBILITY MODEL",
        "RESEARCH UNDERSTANDING LOOP",
        "COLLABORATION AND CONTINUITY",
        "INPUT AND RESEARCH INFORMATION",
        "TOOL DECISION PATH",
        "SCIENTIFIC READING AND COMPARISON",
        "LIMITATIONS AND RECOVERY",
        "DRAFTS AND SAVED RECORDS",
        "RESEARCHER-FACING OUTPUT",
        "BOUNDARY EXAMPLES",
    ):
        assert section in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Match the user's language" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "research question" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "research conclusion" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "supporting source" in prompt
    assert "never restart the greeting or capability introduction" in prompt.lower()
    assert "Use onboarding only for greetings or identity/capability questions" in prompt
    assert "registered tool catalog and loaded parameter schemas define available actions" in prompt
    assert "Search matches, snippets and headings locate content but are not complete reads" in prompt
    assert "propose the actual structured PaperExperiment draft" in prompt
    assert "Use only canonical identities and versions" in prompt
    assert "insufficient map" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "inspect the outline or available body" in prompt.lower()
    assert "Paper Map is optional scope/navigation information" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Raw text or your prose does not create those records" in prompt
    assert "exact eligible selections" not in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Conversation intent does not create a grant" in prompt
    assert "no action is saved before a successful write result" in prompt
    assert "Technical completion is not scientific support" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Never expose hidden chain-of-thought" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Question candidate creation, confirmation and analysis start are distinct actions" in prompt
    assert "Saving a paper experiment never creates or requests a Finding by implication" in prompt
    assert "complete only the experiment path" in prompt
    assert "do not wait for a fixed user keyword" in prompt
    assert "backend permission mode, tool risk and prerequisite validation remain authoritative" in prompt
    assert "create_paper_experiment_revision" not in RESEARCH_AGENT_SYSTEM_PROMPT


def test_prompt_uses_the_research_decision_mission_and_four_layer_model() -> None:
    prompt = " ".join(RESEARCH_AGENT_SYSTEM_PROMPT.split())
    normalized = prompt.casefold()

    assert AGENT_MISSION.startswith("AGENT MISSION")
    assert "form a testable research judgment around the researcher's research decision" in prompt
    assert "relevant scientific knowledge, user materials, paper originals and available tools" in prompt
    assert "reduce key uncertainty" in prompt
    assert "adjust the research question, hypotheses, reading strategy, calculations and comparisons" in normalized
    assert "Research question layer" in prompt
    assert "Research understanding layer" in prompt
    assert "Traceable fact layer" in prompt
    assert "Runtime control layer" in prompt
    assert "runtime observations never become scientific evidence" in normalized
    assert "through traceable cross-paper comparison" not in AGENT_MISSION


def test_prompt_defines_paper_experiment_maturity_and_formal_lifecycle() -> None:
    prompt = " ".join(RESEARCH_AGENT_SYSTEM_PROMPT.split())

    assert "only records experiments actually reported by the paper" in prompt
    assert "Do not create a PaperExperiment merely to create an object" in prompt
    assert "When complete Source reads make a reusable paper-local" in prompt
    assert "complete Source -> PaperExperiment draft -> researcher review -> PaperExperiment revision" in prompt
    assert "later Objective analysis creates selections and cross-paper comparisons" in prompt
    assert "Future validation experiments are proposals, not PaperExperiment records" in prompt
    assert "propose the actual structured PaperExperiment draft" in prompt


def test_prompt_splits_multi_outcome_interest_before_scope_screening() -> None:
    prompt = " ".join(RESEARCH_AGENT_SYSTEM_PROMPT.split())
    assert (
        "one question per outcome"
        in prompt
    )
    assert "split it into one focused question per outcome before scope screening" in prompt
    assert "Preserve the shared intervention" in prompt
    assert "materials and explicit constraints" in prompt
    assert "an outcome is not a variable" in prompt
    assert "changing an outcome does not replace the intervention" in prompt


def test_prompt_separates_product_questions_from_collection_reads() -> None:
    prompt = " ".join(RESEARCH_AGENT_SYSTEM_PROMPT.split())
    assert "Lens purpose/capability questions directly when no collection fact is needed" in prompt
    assert "This system" in prompt
    assert "Lens unless the user asks about its papers" in prompt
    assert "get_collection_context when context is unknown" in prompt
    assert "literal filename/title query is not semantic relevance search" in prompt
    assert "Search matches, snippets and headings locate content" in prompt
    assert "Adding or deferring a paper changes only that paper" in prompt
    assert "one highest-information clarification question" in prompt


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


async def test_missing_provider_message_is_reported_as_invalid_response_shape(caplog) -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason="stop",
            provider_payload="private-provider-content",
        )],
        model="test-model",
        usage=None,
    )
    client, _ = _client(response)

    caplog.set_level(logging.WARNING, logger="infra.llm.chat_model")
    with pytest.raises(ModelResponseError) as caught:
        await OpenAIChatModel(client=client, model="test-model").respond(
            context=ChatModelContext((_message(),)), tool_specs=(),
        )

    assert caught.value.reason == "invalid_response_shape"
    assert "missing_field=message" in caplog.text
    assert "choice_fields=finish_reason,provider_payload" in caplog.text
    assert "message_attribute_present=False message_is_none=True" in caplog.text
    assert "response_fields=choices,model,usage" in caplog.text
    assert "message=research model returned an invalid response shape" in caplog.text
    assert "private-provider-content" not in caplog.text


async def test_missing_stream_delta_is_reported_as_invalid_stream(caplog) -> None:
    response = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")], usage=None)]
    client, _ = _client(response)

    caplog.set_level(logging.WARNING, logger="infra.llm.chat_model")
    with pytest.raises(ModelResponseError) as caught:
        await OpenAIChatModel(client=client, model="test-model").respond(
            context=ChatModelContext((_message(),)), tool_specs=(),
            text_delta_callback=lambda _text: None,
        )

    assert caught.value.reason == "invalid_stream"
    assert "missing_field=delta" in caplog.text
    assert "choice_fields=finish_reason" in caplog.text


@pytest.mark.parametrize("required", [False, True])
async def test_required_research_action_sets_provider_tool_choice(required):
    client, completions = _client(_completion(tool_calls=[SimpleNamespace(
        type="function", function=SimpleNamespace(name="read_source", arguments="{}"),
    )]))
    await OpenAIChatModel(client=client, model="test-model").respond(
        context=ChatModelContext((_message(),), require_tool_call=required),
        tool_specs=(ToolSpec(name="read_source", description="Read a Source.", risk=ToolRisk.READ, input_model=_NoArguments),),
    )
    assert completions.calls[0]["tool_choice"] == ("required" if required else "auto")


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


@pytest.mark.parametrize("compacting", [False, True])
async def test_total_context_guard_includes_prompts_and_compaction_input(compacting):
    from dataclasses import replace
    client, completions = _client(_completion(content="unreachable"))
    context = ChatModelContext(
        (replace(_message(), content="Ti-6Al-4V elongation " * 2000),),
        max_context_tokens=2000, compacting=compacting,
    )
    with pytest.raises(ModelResponseError) as caught:
        await OpenAIChatModel(client=client, model="test-model").respond(
            context=context, tool_specs=(), max_output_tokens=512,
        )
    assert caught.value.reason == "context_window_exceeded"
    assert completions.calls == []


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


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("code", ["context_length_exceeded", "context_window_exceeded"])
async def test_provider_context_rejection_is_normalized_and_audited(streaming, nested, code):
    outcomes = []

    class Observer:
        async def start(self, record):
            return "model-call-1"

        async def finish(self, call_id, outcome):
            outcomes.append(outcome)

    detail = {"code": code, "message": "private prompt/provider details", "type": "invalid_request_error"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        400, json={"error": detail} if nested else detail,
    ))) as http_client:
        async with AsyncOpenAI(api_key="test", base_url="https://provider.invalid/v1", http_client=http_client) as client:
            model = OpenAIChatModel(client=client)
            with pytest.raises(ModelResponseError) as caught:
                await model.respond(
                    context=ChatModelContext((_message(),), model_call_observer=Observer()),
                    tool_specs=(), text_delta_callback=(lambda _: None) if streaming else None,
                )
    assert caught.value.reason == "context_window_exceeded"
    assert not caught.value.retryable
    assert not caught.value.partial_content
    assert "private" not in str(caught.value)
    assert outcomes[-1].error_code == "context_window_exceeded"


@pytest.mark.parametrize("status,code", [(400, "invalid_request_error"), (401, "context_length_exceeded"),
                                        (429, "rate_limit_exceeded"), (500, "server_error")])
async def test_other_provider_errors_are_not_context_rejections(status, code):
    from openai import APIStatusError

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        status, json={"error": {"code": code, "message": "context window exceeded"}},
    ))) as http_client:
        async with AsyncOpenAI(api_key="test", base_url="https://provider.invalid/v1", http_client=http_client) as client:
            with pytest.raises(APIStatusError):
                await OpenAIChatModel(client=client).respond(context=ChatModelContext((_message(),)), tool_specs=())
