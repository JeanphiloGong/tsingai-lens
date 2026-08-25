from __future__ import annotations

from domain.chat import ChatMessage, ChatToolResult

from application.chat import ChatContextBuilder


def _user(message_id: str, content: str) -> ChatMessage:
    return ChatMessage.user(
        message_id=message_id,
        session_id="chat-1",
        content=content,
        created_at="2026-08-19T00:00:00+00:00",
    )


def _assistant(message_id: str, content: str) -> ChatMessage:
    return ChatMessage.assistant(
        message_id=message_id,
        session_id="chat-1",
        content=content,
        created_at="2026-08-19T00:00:00+00:00",
    )


def _tool_pair() -> tuple[ChatMessage, ChatMessage]:
    call = ChatMessage.assistant_tool_call(
        message_id="msg-call",
        session_id="chat-1",
        content="",
        tool_call_id="call-1",
        tool_name="get_collection_context",
        tool_arguments={},
        created_at="2026-08-19T00:00:00+00:00",
    )
    result = ChatMessage.from_tool_result(
        message_id="msg-result",
        session_id="chat-1",
        result=ChatToolResult(
            tool_call_id="call-1",
            status="succeeded",
            data={"collection_id": "col-1"},
        ),
        created_at="2026-08-19T00:00:00+00:00",
    )
    return call, result


def test_context_builder_keeps_tool_call_and_result_as_one_protocol_unit() -> None:
    call, result = _tool_pair()
    messages = (
        _user("msg-old-user", "old question"),
        _assistant("msg-old-answer", "old answer"),
        call,
        result,
    )

    selected = ChatContextBuilder(max_messages=2, max_chars=2_000).for_model(
        messages
    )

    assert selected == (call, result)


def test_context_builder_returns_a_bounded_recent_suffix() -> None:
    call, result = _tool_pair()
    latest = _user("msg-latest", "new question")
    messages = (
        _user("msg-old-user", "x" * 900),
        _assistant("msg-old-answer", "y" * 900),
        call,
        result,
        latest,
    )

    selected = ChatContextBuilder(max_messages=3, max_chars=1_000).for_model(messages)

    assert selected[-1] == latest
    assert selected == (call, result, latest)
    assert len(selected) <= 3
    assert sum(len(item.content) for item in selected) <= 1_000
    assert not (
        selected and selected[0].role.value == "tool"
    )


def test_context_builder_budgets_tool_result_once_for_model_wire_content() -> None:
    user = _user("msg-user", "split energy input effects into focused questions")
    call = ChatMessage.assistant_tool_call(
        message_id="msg-scope-call",
        session_id="chat-1",
        content="I will preview the relevant paper scope.",
        tool_call_id="call-scope",
        tool_name="preview_research_scope",
        tool_arguments={"question": "How does energy input affect ductility?"},
        created_at="2026-08-19T00:00:00+00:00",
    )
    result = ChatMessage.from_tool_result(
        message_id="msg-scope-result",
        session_id="chat-1",
        result=ChatToolResult(
            tool_call_id="call-scope",
            status="succeeded",
            data={"scope_records": ["x" * 4000]},
        ),
        created_at="2026-08-19T00:00:00+00:00",
    )

    selected = ChatContextBuilder(max_messages=3, max_chars=5_000).for_model(
        (user, call, result)
    )

    assert selected == (user, call, result)
