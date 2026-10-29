from __future__ import annotations

from domain.chat import ChatMessageRole, ToolResultStatus

import json

from dataclasses import asdict, replace

import pytest

from controllers.chat.schemas import ChatSourceContextPayload

from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ChatToolRequest,
    ChatToolResult,
    ToolCallStatus,
    ToolRisk,
)


def test_ordered_requests_preserve_order_and_reject_gaps_and_duplicates() -> None:
    first = ChatToolRequest("call-1", "read_source", {"document_id": "paper-1"}, 0)
    second = ChatToolRequest("call-2", "read_source", {"document_id": "paper-2"}, 1)
    message = ChatMessage.assistant_tool_calls(
        message_id="msg-1", session_id="chat-1", content="",
        created_at="2026-09-08T00:00:00+00:00", tool_calls=(first, second),
    )
    assert message.tool_calls == (first, second)
    for bad in (replace(second, position=2), replace(second, tool_call_id="call-1")):
        with pytest.raises(ValueError):
            replace(message, tool_calls=(first, bad))
    with pytest.raises(ValueError):
        replace(message, tool_call_id="call-1")


def test_prepared_assistant_text_keeps_its_original_format() -> None:
    content = "  strength-A / strength-a / 001\n    indented result\n"

    message = ChatMessage.assistant(
        message_id="message-A", session_id="chat-A", content=content,
        created_at="2026-10-29T00:00:00+00:00",
    )

    assert message.content == content


def test_approval_arguments_are_isolated_and_tampering_stops_execution() -> None:
    arguments = {"measurements": ["strength-A", "strength-a", "001"], "certainty": 0.735123}
    pending = ChatToolCall.requested(
        tool_call_id="call-A", session_id="chat-A", assistant_message_id="message-A",
        name="save_result", arguments=arguments, risk=ToolRisk.WRITE,
    ).require_approval()
    arguments["measurements"].append("outside-change")
    approved = pending.approve(
        user_id="researcher-A", arguments_digest=pending.arguments_digest,
        decided_at="2026-10-29T00:00:00+00:00",
    )

    assert approved.arguments["measurements"] == ["strength-A", "strength-a", "001"]
    assert approved.arguments["certainty"] == 0.735123
    approved.arguments["measurements"].append("tampered")
    with pytest.raises(ValueError, match="digest"):
        approved.start("2026-10-29T00:01:00+00:00")


def test_chat_session_preserves_immutable_owner_and_collection() -> None:
    session = ChatSession.create(
        session_id="chat-1",
        user_id="user-1",
        collection_id="col-1",
        created_at="2026-08-19T00:00:00+00:00",
    )

    assert session.user_id == "user-1"
    assert session.collection_id == "col-1"
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
            status=ToolResultStatus.FAILED,
        )


def test_queued_tool_result_requires_a_traceable_resource() -> None:
    with pytest.raises(ValueError, match="queued tool result requires a resource"):
        ChatToolResult(
            tool_call_id="call-1",
            status=ToolResultStatus.QUEUED,
        )

    queued = ChatToolResult(
        tool_call_id="call-1",
        status=ToolResultStatus.QUEUED,
        resource_refs=(
            ChatResourceRef(
                resource_type="objective_analysis",
                resource_id="objective-1:1",
            ),
        ),
    )

    assert queued.resource_refs[0].resource_id == "objective-1:1"


def test_tool_result_message_preserves_paired_scientific_result() -> None:
    payload = {"items": ["paper-1"]}
    result = ChatToolResult(
        tool_call_id="call-1",
        status=ToolResultStatus.SUCCEEDED,
        data=payload,
        resource_refs=(
            ChatResourceRef(
                resource_type="document",
                resource_id="paper-1",
            ),
        ),
    )
    message = ChatMessage(
        message_id="msg-3",
        session_id="chat-1",
        role=ChatMessageRole.TOOL,
        content=json.dumps(
            asdict(result),
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        created_at="2026-08-19T00:00:00+00:00",
        tool_call_id=result.tool_call_id,
        tool_result=result,
    )

    assert result.data == {"items": ["paper-1"]}
    assert message.tool_result == result
    assert message.tool_call_id == "call-1"




def test_user_message_preserves_traceable_source_context() -> None:
    source_context = ChatSourceContext(
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
        source_digest="a" * 64,
    )
    message = ChatMessage.user(
        message_id="msg-source",
        session_id="chat-1",
        content="Explain what this result means.",
        created_at="2026-08-31T00:00:00+00:00",
        source_contexts=(source_context,),
    )

    assert message.source_contexts == (source_context,)
    assert message.source_contexts[0].quote == "Conductivity improved to 12 mS/cm under EIS."


def test_source_context_request_rejects_an_invalid_source_digest() -> None:
    with pytest.raises(ValueError, match="source_digest"):
        ChatSourceContextPayload(
            resource_ref={"resource_type": "source", "resource_id": "doc-1:results"},
            collection_id="col-1",
            document_id="doc-1",
            document_title="Paper A",
            source_kind="text_window",
            source_ref="results",
            page=3,
            quote="Conductivity improved to 12 mS/cm under EIS.",
            source_digest="not-a-digest",
        )


def test_source_context_requires_a_matching_stable_source_reference() -> None:
    with pytest.raises(ValueError, match="resource identity"):
        ChatSourceContext(
            resource_ref=ChatResourceRef(
                resource_type="source",
                resource_id="doc-1:another-source",
            ),
            collection_id="col-1",
            document_id="doc-1",
            document_title="Paper A",
            source_kind="text_window",
            source_ref="results",
            page=3,
            quote="Conductivity improved to 12 mS/cm under EIS.",
            heading_path="Results",
        )
