from __future__ import annotations

from dataclasses import replace

import pytest

from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolRisk,
)


def test_chat_session_round_trips_immutable_owner_and_collection() -> None:
    session = ChatSession.create(
        session_id="chat-1",
        user_id="user-1",
        collection_id="col-1",
        created_at="2026-08-19T00:00:00+00:00",
    )

    assert ChatSession.from_mapping(session.to_record()) == session
    with pytest.raises(ValueError, match="session identity cannot be reassigned"):
        session.update(
            user_id="user-2",
            collection_id="col-1",
            updated_at="2026-08-19T00:01:00+00:00",
        )


def test_tool_call_digest_is_stable_and_write_waits_for_approval() -> None:
    first = ChatToolCall.requested(
        tool_call_id="call-1",
        session_id="chat-1",
        assistant_message_id="msg-2",
        name="create_objective_candidate",
        arguments={"question": "How does energy input affect ductility?", "rank": 1},
        risk=ToolRisk.WRITE,
    )
    reordered = ChatToolCall.requested(
        tool_call_id="call-2",
        session_id="chat-1",
        assistant_message_id="msg-3",
        name="create_objective_candidate",
        arguments={"rank": 1, "question": "How does energy input affect ductility?"},
        risk=ToolRisk.WRITE,
    )

    assert first.arguments_digest == reordered.arguments_digest
    assert first.require_approval().status is ToolCallStatus.APPROVAL_REQUIRED


def test_write_tool_approval_binds_user_and_exact_argument_digest() -> None:
    pending = ChatToolCall.requested(
        tool_call_id="call-1",
        session_id="chat-1",
        assistant_message_id="msg-2",
        name="create_objective_candidate",
        arguments={"question": "How does energy input affect ductility?"},
        risk=ToolRisk.WRITE,
    ).require_approval()

    approved = pending.approve(
        user_id="user-1",
        arguments_digest=pending.arguments_digest,
        decided_at="2026-08-19T00:01:00+00:00",
    )

    assert approved.status is ToolCallStatus.APPROVED
    assert approved.decision_user_id == "user-1"
    assert approved.decision_arguments_digest == pending.arguments_digest
    assert approved.start("2026-08-19T00:02:00+00:00").status is ToolCallStatus.RUNNING

    with pytest.raises(ValueError, match="arguments digest"):
        pending.approve(
            user_id="user-1",
            arguments_digest="changed-arguments",
            decided_at="2026-08-19T00:01:00+00:00",
        )


def test_rejected_write_tool_records_the_deciding_user() -> None:
    pending = ChatToolCall.requested(
        tool_call_id="call-1",
        session_id="chat-1",
        assistant_message_id="msg-2",
        name="create_objective_candidate",
        arguments={"question": "How does energy input affect ductility?"},
        risk=ToolRisk.WRITE,
    ).require_approval()

    rejected = pending.reject(
        user_id="user-1",
        arguments_digest=pending.arguments_digest,
        decided_at="2026-08-19T00:01:00+00:00",
    )

    assert rejected.status is ToolCallStatus.REJECTED
    assert rejected.error_code == "user_rejected"
    assert rejected.decision_user_id == "user-1"


def test_tool_call_rejects_invalid_state_transition() -> None:
    requested = ChatToolCall.requested(
        tool_call_id="call-1",
        session_id="chat-1",
        assistant_message_id="msg-2",
        name="get_collection_context",
        arguments={},
        risk=ToolRisk.READ,
    )

    with pytest.raises(ValueError, match="requested -> succeeded"):
        replace(requested, status=ToolCallStatus.SUCCEEDED)


def test_tool_result_failure_requires_public_error_code() -> None:
    with pytest.raises(ValueError, match="failed tool result requires error_code"):
        ChatToolResult(
            tool_call_id="call-1",
            status="failed",
        )


def test_queued_tool_result_requires_a_traceable_resource() -> None:
    with pytest.raises(ValueError, match="queued tool result requires a resource"):
        ChatToolResult(
            tool_call_id="call-1",
            status="queued",
        )

    queued = ChatToolResult(
        tool_call_id="call-1",
        status="queued",
        resource_refs=(
            ChatResourceRef(
                resource_type="objective_analysis",
                resource_id="objective-1:1",
            ),
        ),
    )

    assert ChatToolResult.from_mapping(queued.to_record()) == queued


def test_tool_result_and_message_copy_mutable_input() -> None:
    payload = {"items": ["paper-1"]}
    result = ChatToolResult(
        tool_call_id="call-1",
        status="succeeded",
        data=payload,
        resource_refs=(
            ChatResourceRef(
                resource_type="document",
                resource_id="paper-1",
            ),
        ),
    )
    message = ChatMessage.from_tool_result(
        message_id="msg-3",
        session_id="chat-1",
        result=result,
        created_at="2026-08-19T00:00:00+00:00",
    )
    payload["items"].append("paper-2")

    assert result.data == {"items": ["paper-1"]}
    assert message.tool_result == result
    assert message.tool_call_id == "call-1"


def test_resource_reference_requires_stable_identity() -> None:
    with pytest.raises(ValueError, match="resource_type"):
        ChatResourceRef(resource_type=" ", resource_id="paper-1")
    with pytest.raises(ValueError, match="resource_id"):
        ChatResourceRef(resource_type="document", resource_id=" ")
