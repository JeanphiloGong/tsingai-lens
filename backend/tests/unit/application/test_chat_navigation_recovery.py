import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat import CapabilityRegistry, ResearchAgentRunner
from application.chat.capability_policy import stage_instruction
from application.chat.capabilities import collection_context
from application.chat.capabilities.collection_context import (
    BrowseCollectionPapersCapability,
    BrowseCollectionPapersToolRequest,
)
from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.context_builder import ChatContextBuilder
from application.chat.model import ResearchWorkingNotesModelOutput
from domain.chat import ChatMessage, ChatMessageRole, ChatResourceRef, ChatToolResult


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_browsing_ledger_does_not_regress_after_revisiting_an_earlier_page():
    pages = [
        {"query": None, "paper_total": 100, "offset": offset,
         "next_offset": offset + count if offset + count < 100 else None,
         "papers": [{"document_id": f"doc-{i}", "title": f"IN718 paper {i}"}
                    for i in range(offset, offset + count)]}
        for offset, count in ((0, 84), (84, 12), (96, 4), (84, 12))
    ]
    text = stage_instruction(
        ("browse_collection_papers",), [],
        successful_results={"browse_collection_papers": pages},
    )
    assert text is not None
    payload = json.loads(text[text.index("{"):])
    ledger = payload["paper_browsing"][0]
    assert ledger["covered_ranges"] == [[0, 100]]
    assert ledger["next_unread_offset"] is None
    assert ledger["seen_document_count"] == 100
    assert any(paper["document_id"] == "doc-99" for paper in ledger["papers"])


def test_partial_title_search_does_not_complete_a_different_catalog():
    pages = [
        {"query": None, "catalog_digest": "old", "paper_total": 100, "offset": 0,
         "papers": [{"document_id": f"old-{i}"} for i in range(100)]},
        {"query": "IN718", "catalog_digest": "new", "paper_total": 1, "offset": 0,
         "papers": [{"document_id": "in718"}]},
        {"query": None, "catalog_digest": "new", "paper_total": 100, "offset": 24,
         "papers": [{"document_id": f"new-{i}"} for i in range(24, 36)]},
    ]
    text = stage_instruction(
        ("browse_collection_papers",), [],
        successful_results={"browse_collection_papers": pages},
    )
    payload = json.loads(text[text.index("{"):])
    assert payload["paper_browsing"][-1]["next_unread_offset"] == 0
    assert payload["paper_browsing"][-1]["covered_ranges"] == [[24, 36]]


def test_repeated_successful_action_is_visible_before_the_next_model_decision():
    from domain.chat import ChatToolCall, ToolRisk

    calls = [ChatToolCall.requested(
        tool_call_id=f"browse-{i}", session_id="chat", assistant_message_id=f"a-{i}",
        position=0, name="browse_collection_papers", arguments={"offset": 84}, risk=ToolRisk.READ,
    ).start("2026-11-01T00:00:00+00:00").succeed("2026-11-01T00:00:01+00:00")
             for i in range(2)]
    text = stage_instruction(("browse_collection_papers",), calls, successful_results={})
    payload = json.loads(text[text.index("{"):])
    assert payload["repeated_action"]["arguments"] == {"offset": 84}
    assert payload["repeated_action"]["previous_successful_count"] == 1


def test_collection_search_records_candidates_without_claiming_exact_reads():
    text = stage_instruction(("inspect_document_sources",), [], successful_results={
        "search_sources": [{"document_ids": None, "matches": [
            {"document_id": "paper-A", "source_ref": "methods"},
            {"document_id": "paper-A", "source_ref": "results"},
            {"document_id": "paper-B", "source_ref": "results"},
        ]}],
    })
    ledger = json.loads(text[text.index("{"):])["reading_ledger"]
    assert [item["document_id"] for item in ledger] == ["paper-A", "paper-B"]
    assert all(item["completely_read_passages"] == 0 for item in ledger)
    assert all(item["outline_status"] == "not_inspected" for item in ledger)


def test_reworded_plan_explanation_points_to_research_instead_of_another_plan_update():
    from domain.chat import ChatToolCall, ToolRisk

    call = ChatToolCall.requested(tool_call_id="plan", session_id="chat", assistant_message_id="a",
                                  name="update_execution_plan", arguments={}, risk=ToolRisk.READ)
    plan = {"steps": [{"step_id": "read", "status": "in_progress", "action": "Read conditions"}],
            "status": "in_progress"}
    text = stage_instruction(("read_source",), [call], successful_results={
        "update_execution_plan": [{**plan, "explanation": "Read the paper."},
                                  {**plan, "explanation": "I will inspect the paper next."}],
    })
    assert "unchanged_plan" in json.loads(text[text.index("{"):])


def test_fallback_replaces_old_next_actions_after_new_observations():
    runner = ResearchAgentRunner(model=object(), capabilities=CapabilityRegistry(()))
    active = ChatMessage.user(
        message_id="user", session_id="chat", content="Continue the IN718 comparison.",
        created_at="2026-11-01T00:00:00+00:00",
    )
    previous = ResearchWorkingNotesModelOutput(
        scope=active.content, checks=[], next_actions=["Continue browsing from offset 24."],
    )
    result = ChatToolResult(
        tool_call_id="last-page", status="succeeded",
        data={"paper_total": 100, "offset": 96, "next_offset": None,
              "papers": [{"document_id": "doc-99", "title": "IN718 tensile results"}]},
    )
    message = ChatMessage(
        message_id="result", session_id="chat", role=ChatMessageRole.TOOL,
        content=json.dumps(asdict(result)), tool_call_id=result.tool_call_id,
        tool_result=result, created_at=active.created_at,
    )
    notes = runner._fallback_working_notes(
        active, [message], max_tokens=2000, working_summary=previous.model_dump_json(),
    )
    assert "Continue browsing from offset 24." not in notes.next_actions
    assert any("ledger" in action for action in notes.next_actions)


def test_reading_a_parent_heading_does_not_complete_its_unread_subsections():
    page = {
        "document": {"document_id": "paper"}, "heading_path": "Methods", "next_offset": 1,
        "document_outline": [
            {"heading_path": "Methods", "pages": [1], "source_count": 1},
            {"heading_path": "Methods > Powder", "pages": [1], "source_count": 1},
        ],
        "sources": [{"document_id": "paper", "heading_path": "Methods", "content": "Methods",
                     "source_kind": "text_window", "source_ref": "heading", "source_digest": "digest",
                     "block_type": "heading", "content_truncated": False}],
    }
    text = stage_instruction(
        ("inspect_document_sources",), [],
        successful_results={"inspect_document_sources": [page]},
    )
    ledger = json.loads(text[text.index("{"):])["reading_ledger"][0]
    assert ledger["pending_section_reads"][0]["arguments"]["offset"] == 1


def test_fallback_retains_attributed_body_after_a_long_document_outline():
    runner = ResearchAgentRunner(model=object(), capabilities=CapabilityRegistry(()))
    active = ChatMessage.user(
        message_id="user", session_id="chat", content="Compare the reported tensile results.",
        created_at="2026-11-01T00:00:00+00:00",
    )
    source = {"source_kind": "text_window", "source_ref": "results-1",
              "source_digest": "a" * 64, "page": 8, "heading_path": "Results",
              "content": "The as-built specimen had elongation of 17% under the reported test conditions.",
              "content_truncated": False}
    result = ChatToolResult(
        tool_call_id="read-results", status="succeeded",
        data={"document": {"document_id": "paper"}, "document_outline": ["metadata " * 1000],
              "sources": [{**source, "source_ref": "title", "block_type": "heading", "content": "Results"}, source]},
    )
    message = ChatMessage(
        message_id="result", session_id="chat", role=ChatMessageRole.TOOL,
        content=json.dumps(asdict(result)), tool_call_id=result.tool_call_id,
        tool_result=result, created_at=active.created_at,
    )
    notes = runner._fallback_working_notes(active, [message], max_tokens=2000)
    saved = notes.model_dump_json()
    assert source["content"] in saved
    for value in ("paper", "results-1", source["source_digest"]):
        assert value in saved
    assert any("result" in check.basis_message_ids for check in notes.checks)
    assert "untrusted" in saved


def test_source_model_message_keeps_body_and_citations_without_duplicate_metadata():
    source = {"source_kind": "text_window", "source_type": "text", "block_type": "paragraph",
              "source_ref": "block-1", "source_label": "S001", "source_digest": "a" * 64,
              "page": 3, "heading_path": "Results", "content": "Elongation was measured.",
              "content_truncated": False, "canonical_length": 24, "estimated_tokens": 7}
    href = "/collections/col/documents/doc?view=parsed-paper&source_ref=block-1&page=3"
    result = ChatToolResult(
        tool_call_id="read", status="succeeded",
        data={"document": {"document_id": "doc", "title": "IN718"}, "sources": [source],
              "source_label_to_ref": {"S001": "block-1"}, "next_offset": None},
        resource_refs=(ChatResourceRef("source", "doc:block-1", href),),
    )
    before = asdict(result)
    message = ChatMessage(
        message_id="result", session_id="chat", role=ChatMessageRole.TOOL,
        content=json.dumps(before), tool_call_id="read", tool_result=result,
        created_at="2026-11-01T00:00:00+00:00",
    )
    content = json.loads(ChatContextBuilder.model_message(message)["content"])
    projected = content["data"]["sources"][0]
    for key in ("content", "source_ref", "source_kind", "source_digest", "source_label",
                "page", "heading_path", "content_truncated"):
        assert projected[key] == source[key]
    assert projected["href"] == href
    assert "source_label_to_ref" not in content["data"]
    assert "resource_refs" not in content
    assert "estimated_tokens" not in projected
    assert asdict(result) == before


@pytest.mark.anyio
async def test_default_browse_fits_many_identities_and_keeps_exact_continuation(monkeypatch):
    records = tuple(SimpleNamespace(
        document=SimpleNamespace(document_id=f"doc-{i}", original_filename=f"IN718 {i}.pdf", status="ready"),
        stored_filename=f"IN718 {i}.pdf",
    ) for i in range(100))
    monkeypatch.setattr(collection_context.collection_service, "get_collection_for_user",
                        AsyncMock(return_value=SimpleNamespace(documents=records)))
    monkeypatch.setattr(collection_context.DocumentProfileRepo, "list_collection", AsyncMock(return_value=[]))
    monkeypatch.setattr(collection_context.PaperMapRepo, "list_collection", AsyncMock(return_value=[]))
    monkeypatch.setattr(collection_context.SourceArtifactRepo, "read_document", AsyncMock(
        return_value=SimpleNamespace(blocks=()),
    ))
    capability = BrowseCollectionPapersCapability()
    seen = []
    offset = 0
    pages = 0
    while True:
        pages += 1
        result = await capability.execute(
            CapabilityExecutionContext("chat", "user", "col", "browse", max_result_tokens=12000),
            BrowseCollectionPapersToolRequest(offset=offset),
        )
        message = ChatContextBuilder.tool_result_message(result)
        assert ChatContextBuilder.estimate_tokens(message) <= 12000
        seen.extend(paper["document_id"] for paper in result.data["papers"])
        next_offset = result.data["next_offset"]
        if next_offset is None:
            break
        assert next_offset > offset
        offset = next_offset
    assert seen == [f"doc-{i}" for i in range(100)]
    assert pages <= 3
