from dataclasses import replace

import pytest

from application.chat import (
    AgentCompletionReason, AgentRunLimits, CapabilityRegistry, ModelToolCall,
    ModelTurn, ResearchAgentRunner,
)
from application.chat.agent_runner import _RunProgress
from application.chat.capability_policy import _section_reading_progress
from domain.chat import ChatResourceRef, ChatToolCall, ChatToolResult, ToolResultStatus, ToolRisk
from tests.unit.application.test_research_agent_runner import (
    _Capability, _Model, _QuestionArguments, _context,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_discovery_reordering_is_not_new_progress():
    progress = _RunProgress(AgentRunLimits())
    for order, expected in ((["read_source", "inspect_table"], True),
                            (["inspect_table", "read_source"], False),
                            (["read_source"], False),
                            (["read_source", "search_sources"], True)):
        call = ChatToolCall.requested(
            tool_call_id="discovery", session_id="chat", assistant_message_id="assistant",
            name="discover_research_tools", arguments={"tool_names": order}, risk=ToolRisk.READ,
        )
        data = {"loaded_tool_names": order,
                "tools": [{"name": name} for name in order]}
        result = ChatToolResult(call.tool_call_id, ToolResultStatus.SUCCEEDED, data=data)
        assert progress.observe(call, result) is expected
        assert result.data["loaded_tool_names"] == order


def test_discovery_catalog_contains_only_definitions_not_already_exposed():
    from application.chat.capability_policy import select_tool_specs
    from domain.chat import ChatMessage, ChatMessageRole

    core = _Capability("read_source", ToolRisk.READ)
    core.spec = replace(core.spec, initially_available=True)
    extra = _Capability("query_published_findings", ToolRisk.READ)
    registry = CapabilityRegistry((core, extra))
    specs = select_tool_specs(registry, [], [])
    catalog = next(spec for spec in specs if spec.name == "discover_research_tools")
    assert "- read_source [" not in catalog.description
    assert "- query_published_findings [" in catalog.description
    assert set(catalog.input_model.model_fields) == {"tool_names"}
    observed = ChatMessage(
        "loaded", "chat", ChatMessageRole.TOOL, "", "2026-11-01", tool_call_id="discovery",
        tool_result=ChatToolResult("discovery", ToolResultStatus.SUCCEEDED,
                                  data={"loaded_tool_names": [extra.spec.name]}),
    )
    from domain.chat import ChatToolRequest
    request = ChatMessage.assistant_tool_calls(
        message_id="request", session_id="chat", content="", created_at="2026-11-01",
        tool_calls=(ChatToolRequest("discovery", "discover_research_tools", {"tool_names": [extra.spec.name]}, 0),),
    )
    user = ChatMessage.user(message_id="u", session_id="chat", content="Review a Finding.", created_at="2026-11-01")
    selected = select_tool_specs(registry, [user, request, observed], [])
    assert {spec.name for spec in selected} == {core.spec.name, extra.spec.name, "update_execution_plan"}


def test_rephrasing_a_plan_is_saved_without_counting_as_progress():
    from domain.chat import ChatMessage

    progress = _RunProgress(AgentRunLimits())
    user = ChatMessage.user(message_id="u", session_id="chat", content="Compare elongation.", created_at="2026-11-01")
    data = {"steps": [{"step_id": "read", "action": "Read relevant experiments", "status": "in_progress"}],
            "status": "in_progress", "explanation": "Check the reported conditions."}
    result = ChatToolResult("plan", ToolResultStatus.SUCCEEDED, data=data)
    assert progress.accept_plan_update(result, request=user)
    progress.plan_update_available = True
    changed = {**data, "steps": [{**data["steps"][0], "action": "Inspect relevant paper experiments"}]}
    assert not progress.accept_plan_update(replace(result, data=changed), request=user)
    assert progress.execution_plan.steps[0]["action"] == changed["steps"][0]["action"]
    completed = {**changed, "steps": [{**changed["steps"][0], "status": "completed"}], "status": "completed"}
    assert progress.accept_plan_update(replace(result, data=completed), request=user)


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


@pytest.mark.anyio
async def test_terminal_plan_transition_gets_a_normal_answer_after_repeated_reads():
    reader = _Capability("read_source", ToolRisk.READ, _QuestionArguments)
    step = {"step_id": "read", "action": "Check reported conditions", "status": "in_progress"}
    plan = {"steps": [step], "status": "in_progress", "explanation": "Read the experiment."}
    done = {"steps": [{**step, "status": "completed"}], "status": "completed",
            "explanation": "Existing observations answer the bounded question."}
    answer = "The inspected experiment leaves tensile orientation unknown."
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("update_execution_plan", plan),)),
        *(ModelTurn(tool_calls=(ModelToolCall("read_source", {"question": "paper"}),)) for _ in range(3)),
        ModelTurn(tool_calls=(ModelToolCall("update_execution_plan", done),)),
        ModelTurn(content=answer), discover=("update_execution_plan", "read_source"),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((reader,))).run_turn(
        context=_context(), previous_messages=(), user_message="Check the experiment's tensile orientation.",
    )
    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER
    assert result.messages[-1].content == answer
    assert result.execution_plan["status"] == "completed"


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
