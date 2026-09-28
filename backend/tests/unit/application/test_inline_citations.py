from __future__ import annotations

from domain.chat import ChatMessage, ChatResourceRef, ChatToolCall, ChatToolResult, ToolRisk

from application.chat.inline_citations import format_inline_citations, format_message_citations


def _call(call_id: str, name: str) -> ChatToolCall:
    return ChatToolCall.requested(
        tool_call_id=call_id,
        session_id="session-1",
        assistant_message_id="assistant-1",
        name=name,
        arguments={},
        risk=ToolRisk.READ,
    )


def _read_result(
    *,
    call_id: str = "call-1",
    source_ref: str = "tbl_doc_abc_table_3",
    complete: bool = True,
    href: str | None = "/collections/col-1/documents/doc-1?source_ref=tbl_doc_abc_table_3",
) -> ChatToolResult:
    return ChatToolResult(
        tool_call_id=call_id,
        status="succeeded",
        data={
            "document_id": "doc-1",
            "document_title": "P006.pdf",
            "source_kind": "table",
            "source_ref": source_ref,
            "page": 8,
            "caption": "Table 3. Yield strength",
            "complete_table": complete,
            "content_truncated": not complete,
            "table_markdown": "| value |",
        },
        resource_refs=(
            ChatResourceRef(
                resource_type="source",
                resource_id=f"doc-1:{source_ref}",
                href=href,
            ),
        ),
    )


def test_marker_becomes_a_readable_link_at_the_claim_location() -> None:
    result = _read_result()

    rendered = format_inline_citations(
        "The measured value increases. [[cite:tbl_doc_abc_table_3]]",
        calls=[_call("call-1", "inspect_table")],
        results=[result],
    )

    assert rendered == (
        "The measured value increases. "
        "[P006.pdf · Table 3 · p. 8](/collections/col-1/documents/doc-1?source_ref=tbl_doc_abc_table_3)"
    )
    assert "tbl_doc_abc_table_3" not in rendered.split("](", 1)[0]


def test_old_raw_locator_is_replaced_without_exposing_the_internal_id() -> None:
    result = _read_result()

    rendered = format_inline_citations(
        "（Source：`tbl_doc_abc_table_3`，第 8 页）",
        calls=[_call("call-1", "inspect_table")],
        results=[result],
    )

    assert "tbl_doc_abc_table_3" not in rendered.split("](", 1)[0]
    assert "P006.pdf · Table 3 · p. 8" in rendered


def test_truncated_source_is_not_rendered_as_supporting_link() -> None:
    result = _read_result(complete=False)

    rendered = format_inline_citations(
        "The preview [[cite:tbl_doc_abc_table_3]] is incomplete.",
        calls=[_call("call-1", "inspect_table")],
        results=[result],
    )

    assert "tbl_doc_abc_table_3" not in rendered
    assert "preview" in rendered
    assert "](/collections/" not in rendered


def test_ambiguous_short_marker_requires_a_document_qualified_reference() -> None:
    first = _read_result(call_id="call-1", source_ref="shared-table")
    second = _read_result(call_id="call-2", source_ref="shared-table")
    second = ChatToolResult(
        tool_call_id="call-2",
        status="succeeded",
        data={**second.data, "document_id": "doc-2", "document_title": "P007.pdf"},
        resource_refs=(
            ChatResourceRef(
                resource_type="source",
                resource_id="doc-2:shared-table",
                href="/collections/col-1/documents/doc-2?source_ref=shared-table",
            ),
        ),
    )

    ambiguous = format_inline_citations(
        "Unqualified [[cite:shared-table]].",
        calls=[_call("call-1", "read_source"), _call("call-2", "read_source")],
        results=[first, second],
    )
    qualified = format_inline_citations(
        "Qualified [[cite:doc-2/shared-table]].",
        calls=[_call("call-1", "read_source"), _call("call-2", "read_source")],
        results=[first, second],
    )

    assert ambiguous == "Unqualified ."
    assert "P007.pdf" in qualified
    assert "shared-table" not in qualified.split("](", 1)[0]


def test_search_match_is_readable_but_never_a_supporting_link() -> None:
    result = ChatToolResult(
        tool_call_id="call-search",
        status="succeeded",
        data={
            "matches": [
                {
                    "document_id": "doc-1",
                    "document_title": "P006.pdf",
                    "source_kind": "text_window",
                    "source_ref": "blk_doc_abc_9",
                    "page": 2,
                    "heading_path": "Results",
                    "content": "A navigation snippet",
                }
            ]
        },
        resource_refs=(
            ChatResourceRef(
                resource_type="source",
                resource_id="doc-1:blk_doc_abc_9",
                href="/collections/col-1/documents/doc-1?source_ref=blk_doc_abc_9",
            ),
        ),
    )

    rendered = format_inline_citations(
        "Candidate [[cite:blk_doc_abc_9]].",
        calls=[_call("call-search", "search_sources")],
        results=[result],
    )

    assert "blk_doc_abc_9" not in rendered
    assert "preview" in rendered
    assert "](/collections/" not in rendered


def test_table_ref_is_bound_when_the_capability_uses_its_canonical_field_name() -> None:
    result = ChatToolResult(
        tool_call_id="call-table",
        status="succeeded",
        data={
            "document_id": "doc-1",
            "document_title": "P006.pdf",
            "table_ref": "tbl_doc_abc_table_3",
            "source_kind": "table",
            "page": 8,
            "caption": "Table 3. Yield strength",
            "complete_table": True,
            "content_truncated": False,
            "table_markdown": "| value |",
        },
        resource_refs=(
            ChatResourceRef(
                resource_type="source",
                resource_id="doc-1:tbl_doc_abc_table_3",
                href="/collections/col-1/documents/doc-1?source_ref=tbl_doc_abc_table_3&page=8",
            ),
        ),
    )

    rendered = format_inline_citations(
        "The table reports the measured value. [[cite:tbl_doc_abc_table_3]]",
        calls=[_call("call-table", "inspect_table")],
        results=[result],
    )

    assert "P006.pdf · Table 3 · p. 8" in rendered
    assert "](/collections/col-1/documents/doc-1?source_ref=tbl_doc_abc_table_3&page=8)" in rendered


def test_unknown_internal_source_id_is_not_exposed() -> None:
    rendered = format_inline_citations(
        "The passage was identified as `blk_doc_unknown_83`.",
    )

    assert "blk_doc_unknown_83" not in rendered
    assert "supporting source" in rendered


def test_historical_assistant_message_is_projected_with_its_source_context() -> None:
    source = _read_result()
    request = ChatMessage.from_mapping({
        "message_id": "request-1",
        "session_id": "session-1",
        "role": "assistant",
        "content": "",
        "created_at": "2026-09-28T00:00:00Z",
        "tool_calls": [{
            "tool_call_id": "call-1", "name": "inspect_table", "arguments": {}, "position": 0,
        }],
    })
    assistant = ChatMessage.assistant(
        message_id="answer-1",
        session_id="session-1",
        content="The value is supported by `tbl_doc_abc_table_3`.",
        created_at="2026-09-28T00:00:00Z",
    )
    tool = ChatMessage.from_tool_result(
        message_id="tool-1",
        session_id="session-1",
        result=source,
        created_at="2026-09-28T00:00:00Z",
    )
    projected = format_message_citations((request, tool, assistant))[2].content

    assert "P006.pdf · Table 3 · p. 8" in projected
    assert "tbl_doc_abc_table_3" not in projected.split("](", 1)[0]
