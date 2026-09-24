from __future__ import annotations

from application.feedback.source_coverage import (
    ChatCoverageAudit,
    build_evidence_coverage,
)
from application.repositories.chat_repository import ChatModelCall
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSourceContext,
    ChatToolRequest,
    ChatToolResult,
)


def _trajectory(
    *,
    result_status: str = "succeeded",
    result_data: dict | None = None,
    result_error: str | None = None,
    model_status: str = "provider_succeeded",
    tool_request_message_id: str = "answer-1",
    answer_message_id: str = "answer-1",
) -> tuple[tuple[ChatMessage, ...], ChatMessage, ChatModelCall]:
    question = ChatMessage.user(
        message_id="question-1",
        session_id="session-1",
        content="Read the exact Source.",
        created_at="2026-09-25T00:00:00+00:00",
    )
    request = ChatToolRequest(
        tool_call_id="tool-1",
        name="read_source",
        arguments={
            "document_id": "document-1",
            "source_kind": "text_window",
            "source_ref": "source-1",
        },
        position=0,
    )
    tool_request = ChatMessage.assistant_tool_calls(
        message_id=tool_request_message_id,
        session_id="session-1",
        content="",
        tool_calls=(request,),
        created_at="2026-09-25T00:00:01+00:00",
    )
    data = result_data or {
        "document_id": "document-1",
        "document_title": "Paper 1",
        "source_kind": "text_window",
        "source_ref": "source-1",
        "source_digest": "a" * 64,
        "content": "The exact passage.",
        "content_truncated": False,
        "complete_source": True,
    }
    result = ChatToolResult(
        tool_call_id="tool-1",
        status=result_status,
        data=data,
        error_code=result_error,
        error_message="The Source read failed." if result_error else None,
    )
    result_message = ChatMessage.from_tool_result(
        message_id="tool-result-1",
        session_id="session-1",
        result=result,
        created_at="2026-09-25T00:00:02+00:00",
    )
    answer = ChatMessage.assistant(
        message_id=answer_message_id,
        session_id="session-1",
        content="The answer.",
        created_at="2026-09-25T00:00:03+00:00",
    )
    model_call = ChatModelCall(
        call_id="model-call-1",
        session_id="session-1",
        trigger_message_id="question-1",
        response_message_id=answer_message_id,
        purpose="decision",
        model="audit-model",
        request={},
        request_digest="b" * 64,
        started_at="2026-09-25T00:00:00+00:00",
        status=model_status,
        finished_at="2026-09-25T00:00:03+00:00",
        provider_confirmed=model_status == "provider_succeeded",
    )
    return (question, tool_request, result_message, answer), answer, model_call


def test_complete_source_requires_matching_model_and_tool_audit() -> None:
    messages, answer, model_call = _trajectory()

    coverage = build_evidence_coverage(
        messages,
        answer,
        audit=ChatCoverageAudit(model_calls=(model_call,), tool_calls={}),
    )

    assert coverage.coverage_status == "complete"
    assert len(coverage.inspected_sources) == 1
    assert coverage.inspected_sources[0]["source_ref"] == "source-1"
    assert coverage.inspected_sources[0]["audit_basis"] == "successful_source_tool_result"
    assert coverage.claim_support == ()
    assert coverage.omitted_candidates == ()


def test_complete_source_uses_the_final_response_boundary_when_ids_are_distinct() -> None:
    messages, answer, model_call = _trajectory(
        tool_request_message_id="tool-request-response-1",
        answer_message_id="final-response-1",
    )

    coverage = build_evidence_coverage(
        messages,
        answer,
        audit=ChatCoverageAudit(model_calls=(model_call,), tool_calls={}),
    )

    assert coverage.coverage_status == "complete"
    assert coverage.inspected_sources[0]["source_ref"] == "source-1"


def test_same_response_id_keeps_tool_results_before_legacy_answer_boundary() -> None:
    messages, answer, model_call = _trajectory()

    coverage = build_evidence_coverage(
        messages,
        answer,
        audit=ChatCoverageAudit(model_calls=(model_call,), tool_calls={}),
    )

    assert coverage.coverage_status == "complete"
    assert coverage.inspected_sources[0]["source_ref"] == "source-1"


def test_successful_tool_result_without_matching_model_call_is_only_partial() -> None:
    messages, answer, _ = _trajectory()

    coverage = build_evidence_coverage(
        messages,
        answer,
        audit=ChatCoverageAudit(model_calls=(), tool_calls={}),
    )

    assert coverage.coverage_status == "partial"
    assert coverage.inspected_sources[0]["source_ref"] == "source-1"
    assert "no model call audit matched the answer" in coverage.gaps


def test_truncated_source_is_omitted_and_never_reported_as_inspected() -> None:
    messages, answer, model_call = _trajectory(
        result_data={
            "document_id": "document-1",
            "source_kind": "text_window",
            "source_ref": "source-1",
            "source_digest": "a" * 64,
            "content": "Only the first page.",
            "content_truncated": True,
            "complete_source": False,
            "next_offset": 20,
        }
    )

    coverage = build_evidence_coverage(
        messages,
        answer,
        audit=ChatCoverageAudit(model_calls=(model_call,), tool_calls={}),
    )

    assert coverage.coverage_status == "partial"
    assert coverage.inspected_sources == ()
    assert coverage.omitted_candidates[0]["reason"] == "source_read_incomplete"
    assert coverage.omitted_candidates[0]["source_ref"] == "source-1"


def test_failed_source_tool_is_failed_coverage_with_error_provenance() -> None:
    messages, answer, model_call = _trajectory(
        result_status="failed",
        result_data={
            "document_id": "document-1",
            "source_kind": "text_window",
            "source_ref": "source-1",
        },
        result_error="source_not_found",
    )

    coverage = build_evidence_coverage(
        messages,
        answer,
        audit=ChatCoverageAudit(model_calls=(model_call,), tool_calls={}),
    )

    assert coverage.coverage_status == "failed"
    assert coverage.inspected_sources == ()
    assert coverage.omitted_candidates[0]["reason"] == "source_read_failed"
    assert coverage.omitted_candidates[0]["error_code"] == "source_not_found"
    assert "source tool failed: source_not_found" in coverage.gaps


def test_selected_context_stays_requested_when_model_audit_is_missing() -> None:
    _, answer, _ = _trajectory()
    selected_source = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id="document-1:source-1",
        ),
        collection_id="collection-1",
        document_id="document-1",
        document_title="Paper 1",
        source_kind="text_window",
        source_ref="source-1",
        page=1,
        quote="A user-selected excerpt.",
        source_digest="a" * 64,
    )
    # Drop the tool trajectory while retaining the user's selected scope in a
    # separate legacy-style message.  Selection is not a model-read fact.
    selected = ChatMessage.user(
        message_id="question-selected",
        session_id="session-1",
        content="Read the selected Source.",
        created_at="2026-09-25T00:00:00+00:00",
        source_contexts=(selected_source,),
    )
    messages = (selected, answer)

    coverage = build_evidence_coverage(messages, answer, audit=ChatCoverageAudit())

    assert coverage.coverage_status == "partial"
    assert coverage.inspected_sources == ()
    assert coverage.requested_scope[0]["origin"] == "user_selected_context"
    assert coverage.omitted_candidates[0]["reason"] == "selected_context_not_verified"
    assert "model Source-read audit is unavailable" in coverage.gaps[0]


def test_durable_source_request_without_result_remains_unverified() -> None:
    messages, answer, model_call = _trajectory()
    request = messages[1].tool_calls[0]
    messages = (messages[0], messages[1], answer)

    coverage = build_evidence_coverage(
        messages,
        answer,
        audit=ChatCoverageAudit(model_calls=(model_call,), tool_calls={request.tool_call_id: object()}),
    )

    assert coverage.coverage_status == "unknown"
    assert coverage.inspected_sources == ()
    assert coverage.requested_scope[0]["source_ref"] == "source-1"
    assert coverage.omitted_candidates[0]["reason"] == "source_read_not_verified"
