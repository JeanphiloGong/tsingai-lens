from __future__ import annotations

from hashlib import sha256
from dataclasses import replace
import json

import pytest

from application.chat import AgentContext, CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat import capability_policy
from application.chat.capabilities import CreateEvidenceDraftCapability
from application.chat.capabilities.document_sources import (
    InspectDocumentSourcesArguments,
    InspectDocumentSourcesCapability,
    InspectTableCapability,
    ReadSourceCapability,
    SearchSourcesCapability,
)
from domain.chat import ChatToolCall, ChatToolResult, ToolCallStatus, ToolRisk
from application.chat.capabilities.contracts import CapabilityExecutionContext
from tests.unit.application.test_chat_p002_source_fixture import _P002CollectionService, _P002SourceRepository
from tests.unit.application.test_research_agent_runner import _Model


@pytest.fixture
def anyio_backend():
    return "asyncio"


DOCUMENT = "doc_ef59d1f3a006"
METHODS = "blk_doc_ef59d1f3a006_23"
TABLE = "tbl_doc_ef59d1f3a006_2_table_2"


def _call(name, **arguments):
    return ModelTurn(tool_calls=(ModelToolCall(name=name, arguments=arguments),))


@pytest.mark.anyio
async def test_document_outline_survives_empty_search_and_supports_section_reading():
    repository = _P002SourceRepository()
    capability = InspectDocumentSourcesCapability(
        collection_service=_P002CollectionService(), source_artifact_repository=repository,
    )
    context = CapabilityExecutionContext("session-p002", "researcher-1", "collection-p002", "outline")
    overview = await capability.execute(context, InspectDocumentSourcesArguments(
        document_id=DOCUMENT, query="a phrase that is not in this paper", limit=1,
    ))
    assert overview.data["match_total"] == 0
    methods = next(block for block in repository.document.blocks if block.block_id == METHODS)
    heading = " ".join(str(methods.heading_path).split())
    assert heading in {item["heading_path"] for item in overview.data["document_outline"]}
    first = await capability.execute(context, InspectDocumentSourcesArguments(
        document_id=DOCUMENT, heading_path=heading, limit=1,
    ))
    assert first.data["sources"]
    assert all(" ".join(str(item["heading_path"]).split()) == heading for item in first.data["sources"])
    progress = capability_policy._section_reading_progress({"inspect_document_sources": [overview.data, first.data, first.data]})
    section = next(item for item in progress[0]["sections"] if item["heading_path"] == heading)
    assert section["completely_read_passages"] == sum(not item["content_truncated"] for item in first.data["sources"])
    assert section["available_passages"] >= len(first.data["sources"])
    if first.data["next_offset"] is not None:
        second = await capability.execute(context, InspectDocumentSourcesArguments(
            document_id=DOCUMENT, heading_path=heading, limit=1, offset=first.data["next_offset"],
        ))
        assert second.data["sources"][0]["source_ref"] != first.data["sources"][0]["source_ref"]


def test_comparison_progress_keeps_paper_without_outline_after_exact_results_read():
    results = {
        "search_sources": [{"document_ids": ["eli", "hp-lpbf", "lpbf"], "matches": []}],
        "inspect_document_sources": [{
            "document": {"document_id": document_id},
            "prepared_source_pages": [1], "outline_truncated": False,
            "document_outline": [{"heading_path": "Abstract", "pages": [1], "source_count": 1}],
        } for document_id in ("eli", "lpbf")],
        "read_source": [{
            "document_id": "hp-lpbf", "source_kind": "text_window", "source_ref": "results-109",
            "source_digest": "hp-results", "heading_path": "Results", "page": 10,
            "content_truncated": False,
        }],
    }
    progress = {item["document_id"]: item for item in capability_policy._section_reading_progress(results)}

    assert set(progress) == {"eli", "hp-lpbf", "lpbf"}
    assert progress["hp-lpbf"]["outline_status"] == "not_inspected"
    assert progress["hp-lpbf"]["prepared_source_pages"] is None
    assert progress["hp-lpbf"]["sections"] is None
    assert progress["hp-lpbf"]["completely_read_passages"] == 1
    assert progress["eli"]["prepared_source_pages"] == [1]

    results["inspect_document_sources"].append({
        "document": {"document_id": "hp-lpbf"}, "prepared_source_pages": list(range(1, 14)),
        "outline_truncated": False,
        "document_outline": [
            {"heading_path": "Materials and methods", "pages": [2, 3, 4], "source_count": 18},
            {"heading_path": "Results", "pages": [10], "source_count": 4},
        ],
    })
    progress = {item["document_id"]: item for item in capability_policy._section_reading_progress(results)}
    assert progress["hp-lpbf"]["outline_status"] == "inspected"
    assert progress["hp-lpbf"]["prepared_source_pages"] == list(range(1, 14))
    assert progress["hp-lpbf"]["sections"][0]["available_passages"] == 18
    assert progress["hp-lpbf"]["sections"][0]["completely_read_passages"] == 0
    assert progress["hp-lpbf"]["sections"][1]["completely_read_passages"] == 1


@pytest.mark.parametrize("outline_failed", [False, True])
def test_reading_progress_keeps_earlier_search_scope_and_distinguishes_failed_outline(outline_failed):
    calls = [ChatToolCall.requested(
        tool_call_id="search", session_id="s", assistant_message_id="a", position=0,
        name="search_sources", arguments={"document_ids": ["eli", "hp-lpbf"]}, risk=ToolRisk.READ,
    )]
    if outline_failed:
        calls.append(replace(ChatToolCall.requested(
            tool_call_id="outline", session_id="s", assistant_message_id="b", position=0,
            name="inspect_document_sources", arguments={"document_id": "hp-lpbf"}, risk=ToolRisk.READ,
        ), status=ToolCallStatus.FAILED, error_code="source_document_not_found",
           finished_at="2026-09-15T00:00:00+00:00"))
    results = {
        "browse_collection_papers": [{"papers": [{"document_id": "unselected-paper"}]}],
        "search_sources": [{"document_ids": ["eli"], "matches": []}],
    }
    instruction = capability_policy.stage_instruction(("inspect_document_sources",), calls, successful_results=results)
    assert instruction is not None
    progress = {item["document_id"]: item for item in json.loads(instruction.rsplit("\n", 1)[1])}
    assert set(progress) == {"eli", "hp-lpbf"}
    assert progress["hp-lpbf"]["outline_status"] == ("inspection_failed" if outline_failed else "not_inspected")
    assert progress["hp-lpbf"]["prepared_source_pages"] is None
    assert progress["hp-lpbf"]["outline_truncated"] is None


@pytest.mark.parametrize("name,arguments", [
    ("search_sources", {"document_ids": None}),
    ("search_sources", {"document_ids": "hp-lpbf"}),
    ("search_sources", {"document_ids": [None, {"document_id": "hp-lpbf"}]}),
    ("inspect_document_sources", {"document_id": {"id": "hp-lpbf"}}),
])
def test_reading_progress_tolerates_invalid_document_arguments_during_repair(name, arguments):
    call = ChatToolCall.requested(
        tool_call_id="invalid", session_id="s", assistant_message_id="a", position=0,
        name=name, arguments=arguments, risk=ToolRisk.READ,
    )
    results = {"search_sources": [{"document_ids": ["eli"], "matches": []}]}
    progress = capability_policy._section_reading_progress(results, calls=[call])
    assert [item["document_id"] for item in progress] == ["eli"]


def test_requested_section_keeps_continuation_when_only_its_heading_was_returned():
    heading = "2. Materials and methods"
    overview = {
        "document": {"document_id": "hp-lpbf"}, "heading_path": heading,
        "document_outline": [{"heading_path": heading, "pages": [2, 3], "source_count": 3}],
        "offset": 0, "next_offset": 1, "match_total": 3,
        "sources": [{
            "source_kind": "text_window", "source_ref": "heading", "block_type": "heading",
            "heading_path": heading, "source_digest": "title-digest",
            "content": heading, "content_truncated": False,
        }],
    }
    results = {"inspect_document_sources": [overview]}
    progress = capability_policy._section_reading_progress(results)[0]
    assert progress["sections"][0]["completely_read_heading_passages"] == 1
    assert progress["pending_section_reads"] == [{
        "arguments": {"document_id": "hp-lpbf", "heading_path": heading, "offset": 1},
        "last_batch_block_types": ["heading"],
    }]

    results["inspect_document_sources"].append({
        **overview, "offset": 1, "next_offset": None,
        "sources": [{
            "source_kind": "text_window", "source_ref": ref, "block_type": "paragraph",
            "heading_path": heading, "source_digest": f"{ref}-digest",
            "content": text, "content_truncated": False,
        } for ref, text in (("treatment", "Annealed at 850 C for two hours."),
                            ("measurement", "Three specimens per state; room-temperature tensile tests."))],
    })
    progress = capability_policy._section_reading_progress(results)[0]
    assert progress["sections"][0]["completely_read_passages"] == 3
    assert progress["sections"][0]["completely_read_heading_passages"] == 1
    assert progress["pending_section_reads"] == []


def test_source_placeholder_remains_pending_after_section_pagination_finishes():
    source = {
        "source_kind": "text_window", "source_ref": "tensile-protocol", "source_digest": "protocol-digest",
        "heading_path": "Methods", "block_type": "paragraph", "content": "", "content_truncated": True,
    }
    results = {"inspect_document_sources": [{
        "document": {"document_id": "hp-lpbf"}, "heading_path": "Methods", "next_offset": None,
        "document_outline": [{"heading_path": "Methods", "pages": [3], "source_count": 1}],
        "sources": [source],
    }]}
    progress = capability_policy._section_reading_progress(results)[0]
    assert progress["pending_source_reads"] == [{
        "tool_name": "read_source",
        "arguments": {"document_id": "hp-lpbf", "source_kind": "text_window", "source_ref": "tensile-protocol"},
    }]
    results["read_source"] = [{**source, "document_id": "hp-lpbf", "content": "Three specimens per state.", "content_truncated": False}]
    assert capability_policy._section_reading_progress(results)[0]["pending_source_reads"] == []


@pytest.mark.anyio
async def test_section_read_preserves_body_space_when_paper_has_many_other_headings():
    repository = _P002SourceRepository()
    methods = next(block for block in repository.document.blocks if block.block_id == METHODS)
    repository.document = replace(repository.document, blocks=(
        methods, *(replace(methods, block_id=f"other-{index}", block_order=index + 100,
                           heading_path=f"Supplementary characterization protocol {index}", text="Other measurements.")
                   for index in range(30)),
    ), tables=(), figures=())
    capability = InspectDocumentSourcesCapability(collection_service=_P002CollectionService(), source_artifact_repository=repository)
    result = await capability.execute(CapabilityExecutionContext(
        "session-p002", "researcher-1", "collection-p002", "section", max_result_tokens=3200,
    ), capability.spec.input_model(document_id=DOCUMENT, heading_path=methods.heading_path))
    assert result.status.value == "succeeded"
    assert capability._result_tokens(result) <= 3200
    assert result.data["sources"][0]["source_ref"] == METHODS
    assert result.data["sources"][0]["content_truncated"] is False
    assert result.data["sources"][0]["content"] == methods.text.strip()
    assert any(item["heading_path"] == methods.heading_path for item in result.data["document_outline"])


def test_finding_review_checks_document_structure_even_after_an_abstract_search():
    results = {
        "discover_research_tools": [{"source_inspection_required": True}],
        "inspect_published_finding": [{"evidence": [{"document_id": "paper-a"}]}],
        "search_sources": [{"document_ids": ["paper-b"], "matches": [], "match_total": 0}],
    }
    assert capability_policy._pending_document_overviews(results) == ("paper-a", "paper-b")
    results["inspect_document_sources"] = [{"document": {"document_id": "paper-a"}, "document_outline": []}]
    assert capability_policy._pending_document_overviews(results) == ("paper-b",)
    assert capability_policy.required_tool_before_answer(("inspect_document_sources",), successful_results=results) == "inspect_document_sources"
    results["inspect_document_sources"].append({"document": {"document_id": "paper-b"}, "document_outline": []})
    assert capability_policy._pending_document_overviews(results) == ()


def test_complete_overview_passage_satisfies_evidence_free_paper_read_without_rereading():
    source = {"document_id": "paper-b", "source_kind": "text_window", "source_ref": "abstract-b",
              "source_digest": "digest-b", "content_truncated": False, "content": "Only an abstract is prepared."}
    results = {
        "discover_research_tools": [{"source_inspection_required": True}],
        "inspect_published_finding": [{"finding": {"paper_contributions": [{"document_id": "paper-b"}]}}],
        "inspect_document_sources": [{"document": {"document_id": "paper-b"},
                                      "sources": [source], "document_outline": []}],
    }
    assert capability_policy._pending_finding_sources(results) == ()


def test_finding_review_requires_a_source_check_for_evidence_free_contributions():
    source = {
        "document_id": "paper-b", "source_kind": "text_window",
        "source_ref": "abstract-1", "source_digest": "digest-b",
        "content_truncated": True,
    }
    results = {
        "discover_research_tools": [{"source_inspection_required": True}],
        "inspect_published_finding": [{
            "finding": {"paper_contributions": [{"document_id": "paper-a"}, {"document_id": "paper-b"}]},
            "evidence": [{"document_id": "paper-a", "source_kind": "text_window", "source_ref": "results-1"}],
        }],
        "inspect_document_sources": [{"document": {"document_id": "paper-b"}, "sources": [source], "document_outline": []}],
        "read_source": [{
            "document_id": "paper-a", "source_kind": "text_window", "source_ref": "results-1",
            "source_digest": "digest-a", "content_truncated": False,
        }],
    }
    assert capability_policy._pending_finding_sources(results) == (("paper-b", "text_window", "abstract-1"),)
    results["discover_research_tools"] = [{"source_inspection_required": False}]
    results.pop("inspect_document_sources")
    assert capability_policy._pending_document_overviews(results) == ()


@pytest.mark.anyio
@pytest.mark.parametrize("parallel_searches", [False, True])
@pytest.mark.parametrize("read_table", [False, True])
async def test_p002_methods_read_does_not_verify_a_new_table_search(parallel_searches, read_table):
    dependencies = dict(collection_service=_P002CollectionService(), source_artifact_repository=_P002SourceRepository())
    methods_search = _call("search_sources", document_ids=[DOCUMENT], query="NP P150", source_types=["text"])
    table_search = _call("search_sources", document_ids=[DOCUMENT], query="elongation", source_types=["table"])
    methods_read = _call("read_source", document_id=DOCUMENT, source_kind="text_window", source_ref=METHODS)
    turns = (
        [ModelTurn(tool_calls=(*methods_search.tool_calls, *table_search.tool_calls)), methods_read]
        if parallel_searches else [methods_search, methods_read, table_search]
    )
    if read_table:
        turns.append(_call("inspect_table", document_id=DOCUMENT, table_ref=TABLE))
    turns.extend([ModelTurn(content="Both the group definitions and elongation values were verified.")] * 2)
    result = await ResearchAgentRunner(
        model=_Model(*turns),
        capabilities=CapabilityRegistry((ReadSourceCapability(**dependencies), SearchSourcesCapability(**dependencies), InspectTableCapability(**dependencies))),
    ).run_turn(context=AgentContext("session-p002", "researcher-1", "collection-p002"), previous_messages=(), user_message="Inspect the P002 group definitions and measured elongation.")
    if read_table:
        assert result.status == "completed"
        assert result.tool_results[-1].data["complete_table"] is True
    else:
        assert result.error_code == "required_research_action_not_completed"


@pytest.mark.anyio
@pytest.mark.parametrize("next_query", ["P150 NP", "unmatched-measurement"])
@pytest.mark.parametrize("reader", ["read_source", "inspect_document_sources"])
async def test_p002_new_navigation_can_reuse_the_same_source_or_report_no_matches(next_query, reader):
    dependencies = dict(collection_service=_P002CollectionService(), source_artifact_repository=_P002SourceRepository())
    read_arguments = (
        dict(document_id=DOCUMENT, source_kind="text_window", source_ref=METHODS)
        if reader == "read_source" else dict(document_id=DOCUMENT, query="NP P150", source_types=["text"])
    )
    result = await ResearchAgentRunner(
        model=_Model(
            _call(reader, **read_arguments),
            _call("search_sources", document_ids=[DOCUMENT], query=next_query, source_types=["text"]),
            ModelTurn(content="The group definitions are available; no additional measurements have been verified."),
        ),
        capabilities=CapabilityRegistry((ReadSourceCapability(**dependencies), InspectDocumentSourcesCapability(**dependencies), SearchSourcesCapability(**dependencies))),
    ).run_turn(context=AgentContext("session-p002", "researcher-1", "collection-p002"), previous_messages=(), user_message="Inspect the P002 group definitions.")
    assert result.status == "completed"
    assert result.tool_calls[-1].name == "search_sources"


@pytest.mark.anyio
async def test_p002_source_pages_do_not_combine_across_user_requests():
    dependencies = dict(collection_service=_P002CollectionService(), source_artifact_repository=_P002SourceRepository())
    model = _Model(
        _call("read_source", document_id=DOCUMENT, source_kind="text_window", source_ref=METHODS, limit=200),
        ModelTurn(content="Only the first part has been read."),
        _call("read_source", document_id=DOCUMENT, source_kind="text_window", source_ref=METHODS, offset=200),
        ModelTurn(content="Only the last part has been read in this request."),
    )
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        ReadSourceCapability(**dependencies), InspectDocumentSourcesCapability(**dependencies),
    )))
    context = AgentContext("session-p002", "researcher-1", "collection-p002")
    model.discover = ("read_source", "inspect_document_sources")
    first = await runner.run_turn(context=context, previous_messages=(), user_message="Read the beginning of the P002 group definitions.")
    model.discover = ("read_source", "inspect_document_sources")
    second = await runner.run_turn(context=context, previous_messages=first.messages, user_message="Read the remainder of those definitions.")
    assert first.status == second.status == "completed"
    assert not capability_policy.has_successful_exact_source_read(capability_policy.active_successful_results_by_name(second.messages))


@pytest.mark.anyio
@pytest.mark.parametrize("page_offsets,expected", [([0, 200], "succeeded"), ([200], "failed"), ([0, 201], "failed")])
async def test_p002_paginated_methods_can_support_an_evidence_draft(page_offsets, expected):
    repository = _P002SourceRepository()
    dependencies = dict(collection_service=_P002CollectionService(), source_artifact_repository=repository)
    content = next(block.text for block in repository.document.blocks if block.block_id == METHODS)
    assert 200 < len(content) < 12000
    turns = [
        _call("read_source", document_id=DOCUMENT, source_kind="text_window", source_ref=METHODS, offset=offset, limit=200 if offset == 0 else 12000)
        for offset in page_offsets
    ]
    turns.append(_call(
        "create_evidence_draft", draft_id="draft-p002-method", objective_id="objective-p002-elongation",
        source_analysis_version=1, document_id=DOCUMENT, source_kind="text_window", source_ref=METHODS,
        source_excerpt=content, source_digest=sha256(content.encode()).hexdigest(),
        evidence_role="condition_context", attribution_scope="descriptive_only",
    ))
    turns.append(ModelTurn(content="The inspected group definitions are ready for review; no Evidence was saved."))
    result = await ResearchAgentRunner(
        model=_Model(*turns, discover=("read_source", "create_evidence_draft")),
        capabilities=CapabilityRegistry((ReadSourceCapability(**dependencies), CreateEvidenceDraftCapability(**dependencies))),
    ).run_turn(context=AgentContext("session-p002", "researcher-1", "collection-p002"), previous_messages=(), user_message="Read the P002 group definitions and draft Evidence without saving.")
    draft = next(item for call, item in zip(result.tool_calls, result.tool_results) if call.name == "create_evidence_draft")
    assert draft.status == expected
    assert draft.error_code == (None if expected == "succeeded" else "source_read_incomplete")
    assert result.pending_approval is None


def _page(offset, content, **overrides):
    return {
        "document_id": DOCUMENT, "source_kind": "text_window", "source_ref": METHODS,
        "source_digest": "digest-v1", "canonical_length": 12600,
        "content_offset": offset, "content": content, "content_truncated": True,
        "complete_source": False, **overrides,
    }


@pytest.mark.parametrize("second_page,complete", [
    (_page(12000, "b" * 600), True),
    (_page(11900, "b" * 700), True),
    (_page(12001, "b" * 599), False),
    (_page(12000, "b" * 600, source_digest="digest-v2"), False),
    (_page(12000, "b" * 600, document_id="other-paper"), False),
    (_page(12000, "b" * 600, source_kind="figure"), False),
    (_page(12000, "b" * 600, source_ref="other-section"), False),
    (_page(12000, "b" * 600, canonical_length=12601), False),
])
def test_paginated_source_proof_requires_contiguous_same_version_coverage(second_page, complete):
    results = {"read_source": [second_page, _page(0, "a" * 12000)]}
    assert capability_policy.has_successful_exact_source_read(results) is complete


def test_search_for_a_new_source_version_cannot_reuse_an_old_complete_read():
    source = {"document_id": DOCUMENT, "source_kind": "text_window", "source_ref": METHODS}
    results = {
        "read_source": [{**source, "source_digest": "old", "content_truncated": False}],
        "search_sources": [{"matches": [{**source, "source_digest": "new"}]}],
    }
    assert capability_policy.required_tool_before_answer(("read_source",), successful_results=results) == "read_source"


def test_evidence_for_a_new_source_version_requires_reading_that_version():
    from application.chat.capabilities import CreateEvidenceDraftArguments
    from tests.unit.application.test_research_agent_runner import _Capability
    from domain.chat import ChatMessage, ChatMessageRole, ChatToolRequest

    source = {"document_id": DOCUMENT, "source_kind": "text_window", "source_ref": METHODS}
    read_result = ChatToolResult(tool_call_id="read", status="succeeded", data={
        **source, "source_digest": "a" * 64, "content_truncated": False,
    })
    messages = [
        ChatMessage.user(message_id="u", session_id="s", content="Draft Evidence from these methods.", created_at="2026-09-09T00:00:00Z"),
        ChatMessage(message_id="a", session_id="s", role=ChatMessageRole.ASSISTANT, content="", created_at="2026-09-09T00:00:00Z", tool_calls=(ChatToolRequest(tool_call_id="read", name="read_source", arguments={}, position=0),)),
        ChatMessage(message_id="t", session_id="s", role=ChatMessageRole.TOOL, content="", created_at="2026-09-09T00:00:00Z", tool_call_id="read", tool_result=read_result),
    ]
    handler = _Capability("create_evidence_draft", ToolRisk.DRAFT, CreateEvidenceDraftArguments)
    call = ChatToolCall.requested(tool_call_id="draft", session_id="s", assistant_message_id="a2", position=0,
        name="create_evidence_draft", risk=ToolRisk.DRAFT, arguments={
            **source, "draft_id": "draft", "objective_id": "objective", "source_analysis_version": 1,
            "source_excerpt": "Changed source text", "source_digest": "b" * 64,
            "evidence_role": "condition_context", "attribution_scope": "descriptive_only",
        })
    error, _ = capability_policy.validate_batch(CapabilityRegistry((handler,)), [(call, handler)], messages)
    assert error is not None and error[0] == "source_read_incomplete"


@pytest.mark.anyio
async def test_reading_only_last_table_row_is_not_a_complete_read():
    from tests.unit.application.test_chat_p002_source_fixture import _context

    table = InspectTableCapability(collection_service=_P002CollectionService(), source_artifact_repository=_P002SourceRepository())
    result = await table.execute(_context("tail"), table.spec.input_model(document_id=DOCUMENT, table_ref=TABLE, row_offset=1))
    assert result.data["complete_table"] is False
    assert result.data["content_truncated"] is False
    assert not capability_policy.has_successful_exact_source_read({"inspect_table": [result.data]})


@pytest.mark.anyio
async def test_complete_same_version_table_windows_count_as_read():
    from tests.unit.application.test_chat_p002_source_fixture import _context

    repository = _P002SourceRepository()
    source = repository.document.tables[0]
    repository.document = replace(repository.document, tables=(replace(
        source, header_row_count=0, column_headers=("Condition", "Result"),
        table_matrix=(("NP", "a" * 7000), ("P150", "b" * 7000)),
    ),))
    table = InspectTableCapability(collection_service=_P002CollectionService(), source_artifact_repository=repository)
    first = await table.execute(_context("first"), table.spec.input_model(document_id=DOCUMENT, table_ref=source.table_id, row_limit=1))
    last = await table.execute(_context("last"), table.spec.input_model(document_id=DOCUMENT, table_ref=source.table_id, row_offset=first.data["next_row_offset"]))
    assert first.data["complete_table"] is last.data["complete_table"] is False
    assert first.data["returned_row_count"] == last.data["returned_row_count"] == 1
    assert capability_policy.has_successful_exact_source_read({"inspect_table": [last.data, first.data]})
    assert not capability_policy.has_successful_exact_source_read({"inspect_table": [first.data, {**last.data, "source_digest": "another-version"}]})
    assert not capability_policy.has_successful_exact_source_read({"inspect_table": [first.data, {**last.data, "returned_row_count": 0}]})


@pytest.mark.parametrize("complete", [False, True])
def test_reading_ledger_uses_complete_source_coverage(complete):
    pages = [_page(0, "a" * 12000)]
    if complete:
        pages.append(_page(12000, "b" * 600))
    calls = [ChatToolCall.requested(
        tool_call_id=f"read-{i}", session_id="s", assistant_message_id=f"a-{i}", position=0,
        name="read_source", arguments={"document_id": DOCUMENT}, risk=ToolRisk.READ,
    ) for i in range(len(pages))]
    results = [ChatToolResult(tool_call_id=call.tool_call_id, status="succeeded", data=page) for call, page in zip(calls, pages)]
    ledger = ResearchAgentRunner._reading_ledger(calls, results)
    assert f"Exact paper Sources read ({int(complete)}):" in ledger
