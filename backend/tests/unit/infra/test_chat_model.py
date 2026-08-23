from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from application.chat import ToolSpec
from application.chat.model import (
    ModelTurn,
    RESEARCH_AGENT_PROMPT_VERSION,
    RESEARCH_AGENT_SYSTEM_PROMPT,
)
from domain.chat import ChatMessage, ToolRisk
from infra.llm.chat_model import OpenAIChatModel


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Completions:
    def __init__(self, response) -> None:  # noqa: ANN001
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        return self.response


def _client(response):  # noqa: ANN001, ANN202
    completions = _Completions(response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def _completion(*, content: str | None = None, tool_calls: list | None = None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        model="test-model",
        usage=None,
    )


def _stream_chunk(
    *,
    content: str | None = None,
    tool_calls: list | None = None,
    usage=None,  # noqa: ANN001
):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta)] if content is not None or tool_calls else [],
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
    assert RESEARCH_AGENT_PROMPT_VERSION == "research-agent-v5"
    assert "Match the user's language" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "research question" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "research conclusion" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "supporting source" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "Never expose registered tool names" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "我是 TsingAI-Lens 科研研究智能体" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "形成研究目标" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "分析已有论文和证据" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "设计研究方案" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "验证研究判断" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "研究方案生成和验证闭环仍在开发中" in RESEARCH_AGENT_SYSTEM_PROMPT


def test_prompt_separates_product_questions_from_collection_reads() -> None:
    assert "application's purpose" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "without calling a tool" in RESEARCH_AGENT_SYSTEM_PROMPT
    assert "current collection's contents" in RESEARCH_AGENT_SYSTEM_PROMPT


def test_openai_chat_model_uses_the_global_model_setting(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "global-model")
    monkeypatch.setenv("RESEARCH_AGENT_LLM_MODEL", "retired-agent-model")
    client, _completions = _client(_completion(content="ok"))

    model = OpenAIChatModel(client=client)

    assert model.model == "global-model"


def test_openai_chat_model_returns_an_ordinary_answer_without_tools() -> None:
    client, completions = _client(_completion(content="你好，我可以帮助分析文献。"))
    model = OpenAIChatModel(client=client, model="test-model")

    turn = model.respond(messages=(_message(),), tool_specs=())

    assert turn.content == "你好，我可以帮助分析文献。"
    assert turn.tool_call is None
    request = completions.calls[0]
    assert request["messages"][0]["role"] == "system"
    assert request["messages"][1] == {"role": "user", "content": "你好"}
    assert "tools" not in request


def test_openai_chat_model_parses_one_typed_tool_call() -> None:
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

    turn = model.respond(messages=(_message(),), tool_specs=(spec,))

    assert turn.tool_call is not None
    assert turn.tool_call.name == "get_collection_context"
    assert turn.tool_call.arguments == {"include_documents": True}
    request = completions.calls[0]
    assert request["parallel_tool_calls"] is False
    assert request["tools"][0]["function"]["name"] == "get_collection_context"


def test_openai_chat_model_streams_text_and_returns_the_complete_turn() -> None:
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

    turn = model.respond(
        messages=(_message(),),
        tool_specs=(),
        text_delta_callback=deltas.append,
    )

    assert deltas == ["这批", "论文"]
    assert turn == ModelTurn(content="这批论文")
    request = completions.calls[0]
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}


def test_openai_chat_model_reassembles_one_streamed_tool_call() -> None:
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

    turn = model.respond(
        messages=(_message(),),
        tool_specs=(),
        text_delta_callback=lambda _content: None,
    )

    assert turn.tool_call is not None
    assert turn.tool_call.name == "get_collection_context"
    assert turn.tool_call.arguments == {}


def test_openai_chat_model_rejects_multiple_or_non_object_tool_arguments() -> None:
    first = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name="one", arguments="{}"),
    )
    second = SimpleNamespace(
        id="call-2",
        type="function",
        function=SimpleNamespace(name="two", arguments="{}"),
    )
    client, _completions = _client(_completion(tool_calls=[first, second]))
    model = OpenAIChatModel(client=client, model="test-model")

    with pytest.raises(ValueError, match="exactly one tool call"):
        model.respond(messages=(_message(),), tool_specs=())

    invalid = SimpleNamespace(
        id="call-3",
        type="function",
        function=SimpleNamespace(name="one", arguments="[]"),
    )
    client, _completions = _client(_completion(tool_calls=[invalid]))
    model = OpenAIChatModel(client=client, model="test-model")

    with pytest.raises(ValueError, match="JSON object"):
        model.respond(messages=(_message(),), tool_specs=())
