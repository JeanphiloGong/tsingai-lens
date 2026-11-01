from dataclasses import replace
import json

import pytest

from application.chat import (
    AgentCompletionReason, AgentRunLimits, CapabilityRegistry, ModelToolCall,
    ModelTurn, ResearchAgentRunner,
)
from application.chat.agent_runner import _RunProgress
from application.chat.capability_policy import _section_reading_progress
from domain.chat import ChatResourceRef, ToolRisk
from tests.unit.application.test_research_agent_runner import (
    _Capability, _Model, _QuestionArguments, _context,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_collection_search_candidates_enter_ledger_without_becoming_exact_reads():
    from application.chat.capability_policy import stage_instruction

    instruction = stage_instruction(("inspect_document_sources",), [], successful_results={
        "search_sources": [{"document_ids": None, "matches": [
            {"document_id": "paper-A", "source_ref": "methods"},
            {"document_id": "paper-A", "source_ref": "results"},
            {"document_id": "paper-B", "source_ref": "results"},
        ]}],
    })
    ledger = json.loads(instruction[instruction.index("{"):])["reading_ledger"]
    assert [item["document_id"] for item in ledger] == ["paper-A", "paper-B"]
    assert all(item["completely_read_passages"] == 0 for item in ledger)
    assert all(item["outline_status"] == "not_inspected" for item in ledger)


def test_section_read_keeps_the_full_outline_and_unread_results():
    methods = {"heading_path": "Methods", "pages": [2], "source_count": 3}
    results = {"heading_path": "Results", "pages": [3, 4], "source_count": 5}
    pages = [
        {"document": {"document_id": "paper"}, "heading_path": None,
         "document_outline": [methods, results], "outline_truncated": False,
         "prepared_source_pages": [1, 2, 3, 4], "sources": []},
        {"document": {"document_id": "paper"}, "heading_path": "Methods",
         "document_outline": [methods], "outline_truncated": True,
         "prepared_source_pages": [1, 2, 3, 4], "sources": []},
    ]
    ledger = _section_reading_progress({"inspect_document_sources": pages})[0]
    assert ledger["outline_truncated"] is False
    assert [section["heading_path"] for section in ledger["sections"]] == ["Methods", "Results"]
    assert ledger["sections"][1]["completely_read_passages"] == 0


def test_changed_source_version_replaces_the_known_outline():
    pages = [
        {"document": {"document_id": "paper"}, "source_version": "old",
         "document_outline": [{"heading_path": "Old results", "pages": [3], "source_count": 5}],
         "sources": []},
        {"document": {"document_id": "paper"}, "source_version": "new", "heading_path": "New methods",
         "document_outline": [{"heading_path": "New methods", "pages": [2], "source_count": 1}],
         "sources": []},
    ]
    ledger = _section_reading_progress({"inspect_document_sources": pages})[0]
    assert [section["heading_path"] for section in ledger["sections"]] == ["New methods"]


@pytest.mark.anyio
async def test_stalled_research_can_execute_a_new_read_after_specific_feedback():
    class Reader(_Capability):
        async def execute(self, context, arguments):
            result = await super().execute(context, arguments)
            return replace(result, data={"content": "Measured conditions for " + arguments.question},
                           resource_refs=(ChatResourceRef("source", arguments.question),))

    read = Reader("read_source", ToolRisk.READ, _QuestionArguments)
    plan = {"steps": [{"step_id": "read", "action": "Compare both papers", "status": "in_progress"}],
            "status": "in_progress", "explanation": "Read the conditions before comparing."}
    completed = {**plan, "steps": [{**plan["steps"][0], "status": "completed"}], "status": "completed"}
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("update_execution_plan", plan),)),
        *(ModelTurn(tool_calls=(ModelToolCall("read_source", {"question": "paper-1"}),)) for _ in range(3)),
        ModelTurn(tool_calls=(ModelToolCall("read_source", {"question": "paper-2"}),)),
        ModelTurn(tool_calls=(ModelToolCall("update_execution_plan", completed),)),
        ModelTurn(content="Both papers' conditions were inspected."),
        discover=("read_source", "update_execution_plan"),
    )
    events = []
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,)), limits=AgentRunLimits(max_elapsed_seconds=None),
    ).run_turn(context=_context(), previous_messages=(), user_message="Compare the two papers.",
               progress_callback=events.append)
    assert read.executed_arguments[-1] == {"question": "paper-2"}
    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER
    assert any(event["phase"] == "no_progress_recovery" for event in events)
    correction = next(context for context in model.contexts
                      if any("[STALLED EXECUTION: CORRECTION]" in message.content for message in context))
    assert any("read_source" in message.content for message in correction
               if "[STALLED EXECUTION: CORRECTION]" in message.content)


def test_stall_correction_does_not_override_the_tool_budget():
    progress = _RunProgress(AgentRunLimits(max_tool_calls=2))
    progress.executed_tool_calls = 2
    progress.consecutive_no_progress = 2
    assert progress.stop_before_model(allow_no_progress_recovery=True) is AgentCompletionReason.RESOURCE_BUDGET


@pytest.mark.anyio
async def test_active_research_step_does_not_receive_a_plan_update_reminder_after_each_read():
    reader = _Capability("read_source", ToolRisk.READ, _QuestionArguments)
    step = {"step_id": "read", "action": "Compare paper conditions", "status": "in_progress"}
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("update_execution_plan", {
            "steps": [step], "status": "in_progress", "explanation": "Read both papers.",
        }),)),
        ModelTurn(tool_calls=(ModelToolCall("read_source", {"question": "paper-1"}),)),
        ModelTurn(tool_calls=(ModelToolCall("read_source", {"question": "paper-2"}),)),
        ModelTurn(tool_calls=(ModelToolCall("update_execution_plan", {
            "steps": [{**step, "status": "completed"}], "status": "completed",
            "explanation": "Both papers inspected.",
        }),)),
        ModelTurn(content="The reported conditions differ."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((reader,))).run_turn(
        context=_context(), previous_messages=(), user_message="Compare both papers.",
    )
    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER
    assert len(reader.executed_arguments) == 2
    assert not any("The current execution plan is still in progress." in message.content
                   for context in model.contexts for message in context)


def test_core_reader_specs_are_available_without_discovery_but_writes_are_not():
    from application.chat.capability_policy import select_tool_specs
    from application.chat.capabilities.document_sources import SearchSourcesCapability,InspectDocumentSourcesCapability,ReadSourceCapability,InspectTableCapability
    from application.chat.capabilities.collection_context import BrowseCollectionPapersCapability
    readers=(SearchSourcesCapability(),InspectDocumentSourcesCapability(),ReadSourceCapability(),InspectTableCapability(),BrowseCollectionPapersCapability())
    registry=CapabilityRegistry((*readers,_Capability('save',ToolRisk.WRITE)))
    names={spec.name for spec in select_tool_specs(registry,[],[],permission_mode='read_only')}
    assert {reader.spec.name for reader in readers}<=names
    assert 'update_execution_plan' in names and 'save' not in names
    assert select_tool_specs(registry,[],[],permission_mode='none')==()
