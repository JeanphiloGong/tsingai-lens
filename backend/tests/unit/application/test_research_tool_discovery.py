from __future__ import annotations

import pytest

from application.chat import CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat.capability_policy import select_tool_specs
from domain.chat import ChatMessage, ToolRisk
from tests.unit.application.test_research_agent_runner import _Capability, _Model, _context


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_initial_catalog_defers_read_parameters_even_without_intent_keywords():
    registry = CapabilityRegistry((_Capability("search_sources", ToolRisk.READ),))
    message = ChatMessage.user(message_id="u", session_id="chat-1", content="What did the authors measure?", created_at="2026-09-09T00:00:00Z")
    specs = select_tool_specs(registry, [message], [])
    assert [spec.name for spec in specs] == ["discover_research_tools"]
    assert "search_sources" in specs[0].description
    assert "SearchSourcesArguments" not in str(specs[0].model_schema())


@pytest.mark.anyio
async def test_discovered_read_runs_and_does_not_carry_into_next_request():
    search = _Capability("search_sources", ToolRisk.READ, result_data={"matches": []})
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="discover_research_tools", arguments={"tool_names": ["search_sources"]}),)),
        ModelTurn(tool_calls=(ModelToolCall(name="search_sources", arguments={}),)),
        ModelTurn(content="No matching Source was located; the measurement remains unverified."),
        ModelTurn(content="Hello."),
    )
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((search,)))
    first = await runner.run_turn(context=_context(), previous_messages=(), user_message="What did the authors measure?")
    assert first.status == "completed"
    assert search.executed_arguments == [{}]
    assert [call.name for call in first.tool_calls] == ["discover_research_tools", "search_sources"]
    await runner.run_turn(context=_context(), previous_messages=first.messages, user_message="Hello")
    assert "search_sources" not in model.tool_spec_names[-1]


@pytest.mark.anyio
async def test_catalog_cannot_load_a_write():
    writer = _Capability("create_evidence_version", ToolRisk.WRITE)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="discover_research_tools", arguments={"tool_names": ["create_evidence_version"]}),)),
        ModelTurn(content="No Evidence was saved."),
    )
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((_Capability("search_sources", ToolRisk.READ), writer)))
    result = await runner.run_turn(context=_context(), previous_messages=(), user_message="Read the measurements.")
    assert writer.executed_arguments == []
    assert result.pending_approval is None
    assert result.tool_results[0].status == "failed"


def test_explicit_no_tools_disables_catalog():
    registry = CapabilityRegistry((_Capability("search_sources", ToolRisk.READ),))
    message = ChatMessage.user(message_id="u", session_id="chat-1", content="Explain LPBF, do not search.", created_at="2026-09-09T00:00:00Z")
    assert select_tool_specs(registry, [message], []) == ()


@pytest.mark.parametrize("request_text", [
    "Do not publish analysis; inspect it first.",
    "Review this finding, do not save any changes.",
    "Do not save evidence; check the source first.",
    "Revise the saved plan as a draft, do not save changes.",
    "Do not save a new version of this finding; review it first.",
    "复核这个 Finding，不要保存任何修改。",
    "不要发布分析，先检查。",
    "先不要保存证据，读取原文。",
    "Review the start analysis action; do not save any changes.",
    "Inspect the confirm objective action, do not save anything.",
])
def test_no_write_request_excludes_all_persistence_tools(request_text):
    from application.chat.intent_policy import WRITE_CAPABILITIES

    registry = CapabilityRegistry((
        _Capability("read_source", ToolRisk.READ),
        *(_Capability(name, ToolRisk.WRITE) for name in sorted(WRITE_CAPABILITIES)),
    ))
    message = ChatMessage.user(message_id="u", session_id="chat-1", content=request_text, created_at="2026-09-09T00:00:00Z")
    assert not {spec.name for spec in select_tool_specs(registry, [message], [])}.intersection(WRITE_CAPABILITIES)


@pytest.mark.anyio
async def test_no_save_plan_draft_does_not_reenable_writes_after_discovery():
    create = _Capability("create_research_plan", ToolRisk.WRITE)
    revise = _Capability("revise_research_plan", ToolRisk.WRITE)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="inspect_research_plans"),)),
        ModelTurn(tool_calls=(ModelToolCall(name="propose_research_plan"),)),
        ModelTurn(content="The revised plan is ready for review and has not been saved."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        _Capability("inspect_research_plans", ToolRisk.READ, result_data={"objective_id": "o", "plans": [{"plan_id": "p"}]}),
        _Capability("propose_research_plan", ToolRisk.DRAFT, result_data={"draft_status": "ready"}),
        create, revise,
    ))).run_turn(context=_context(), previous_messages=(), user_message="Revise the saved plan as a draft, do not save changes.")
    assert result.status == "completed"
    assert result.pending_approval is None
    assert create.executed_arguments == revise.executed_arguments == []
    assert all(not {"create_research_plan", "revise_research_plan"}.intersection(names) for names in model.all_tool_spec_names)


def test_approved_write_is_not_reexposed_before_discovery():
    registry = CapabilityRegistry((
        _Capability("get_collection_context", ToolRisk.READ),
        _Capability("create_objective_candidate", ToolRisk.WRITE),
    ))
    message = ChatMessage.user(message_id="u", session_id="chat-1", content="Save this research objective candidate.", created_at="2026-09-09T00:00:00Z")
    specs = select_tool_specs(registry, [message], [], inherited_completed_writes={"create_objective_candidate"})
    assert "create_objective_candidate" not in {spec.name for spec in specs}


def test_discovery_name_cannot_be_shadowed_by_registered_handler():
    with pytest.raises(ValueError, match="reserved"):
        CapabilityRegistry((_Capability("discover_research_tools", ToolRisk.WRITE),))


@pytest.mark.anyio
async def test_provider_error_during_finalization_does_not_log_details(caplog):
    from application.chat import AgentRunLimits

    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="discover_research_tools", arguments={"tool_names": ["search_sources"]}),)),
        RuntimeError("provider-secret-do-not-log"),
    )
    result = await ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((_Capability("search_sources", ToolRisk.READ),)),
        limits=AgentRunLimits(max_tool_calls=1),
    ).run_turn(context=_context(), previous_messages=(), user_message="Inspect the measured values.")
    assert result.error_code == "final_answer_unavailable"
    assert "provider-secret-do-not-log" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


@pytest.mark.anyio
async def test_reading_a_plan_section_keeps_selected_source_tools():
    inspect = _Capability("inspect_document_sources", ToolRisk.READ)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="inspect_document_sources"),)),
        ModelTurn(content="The paper's plan section was inspected."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        inspect,
        _Capability("get_collection_context", ToolRisk.READ),
        _Capability("assess_objective_quality", ToolRisk.READ),
        _Capability("query_published_findings", ToolRisk.READ),
        _Capability("propose_research_plan", ToolRisk.DRAFT),
    ))).run_turn(context=_context(), previous_messages=(), user_message="Read the plan section in P002")
    assert result.status == "completed"
    assert inspect.executed_arguments == [{}]
    assert [call.name for call in result.tool_calls] == ["discover_research_tools", "inspect_document_sources"]


@pytest.mark.anyio
async def test_real_p002_source_read_can_recover_from_a_stale_reference():
    from application.chat import AgentContext
    from application.chat.capabilities.document_sources import ReadSourceCapability, InspectDocumentSourcesCapability
    from tests.unit.application.test_chat_p002_source_fixture import _P002CollectionService, _P002SourceRepository

    dependencies = dict(collection_service=_P002CollectionService(), source_artifact_repository=_P002SourceRepository())
    arguments = {"document_id": "doc_ef59d1f3a006", "source_kind": "text_window", "source_ref": "blk_doc_ef59d1f3a006_23"}
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="read_source", arguments={**arguments, "source_ref": "stale-id"}),)),
        ModelTurn(tool_calls=(ModelToolCall(name="inspect_document_sources", arguments={"document_id": arguments["document_id"], "query": "NP P150"}),)),
        ModelTurn(tool_calls=(ModelToolCall(name="read_source", arguments=arguments),)),
        ModelTurn(content="NP means no build-platform preheating; P150 means preheating to 150 C."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        ReadSourceCapability(**dependencies), InspectDocumentSourcesCapability(**dependencies),
    ))).run_turn(context=AgentContext("session-p002", "researcher-1", "collection-p002"), previous_messages=(), user_message="Inspect the P002 group definitions")
    assert result.status == "completed"
    assert result.tool_results[1].error_code == "source_not_found"
    assert [call.name for call in result.tool_calls] == [
        "discover_research_tools", "read_source", "discover_research_tools",
        "inspect_document_sources", "read_source",
    ]
    assert all(item.status == "succeeded" for item in result.tool_results[2:])
    assert result.tool_results[-1].data["source_ref"] == arguments["source_ref"]
    assert result.tool_results[-1].data["content_truncated"] is False
    assert "designated by NP and P150" in result.tool_results[-1].data["content"]
    assert model.all_tool_spec_names[0] == ("discover_research_tools",)


@pytest.mark.anyio
@pytest.mark.parametrize("user_id,document_id,error_code", [
    ("researcher-1", "outside-collection", "document_sources_not_ready"),
    ("another-user", "doc_ef59d1f3a006", "capability_execution_failed"),
])
async def test_discovery_does_not_bypass_source_ownership(user_id, document_id, error_code):
    from application.chat import AgentContext
    from application.chat.capabilities.document_sources import ReadSourceCapability
    from tests.unit.application.test_chat_p002_source_fixture import _P002CollectionService, _P002SourceRepository

    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="read_source", arguments={"document_id": document_id, "source_kind": "text_window", "source_ref": "blk_doc_ef59d1f3a006_23"}),)),
        ModelTurn(content="The requested source could not be read."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        ReadSourceCapability(collection_service=_P002CollectionService(), source_artifact_repository=_P002SourceRepository()),
    ))).run_turn(context=AgentContext("session-p002", user_id, "collection-p002"), previous_messages=(), user_message="Inspect the P002 group definitions")
    assert result.status == "completed"
    assert result.tool_results[-1].error_code == error_code
    assert not result.tool_results[-1].resource_refs


@pytest.mark.anyio
@pytest.mark.parametrize("inspection", [
    {"objective_id": "other-objective", "plans": []},
    {"objective_id": "objective-1", "plans": [{"plan_id": "another-plan"}]},
])
async def test_plan_revision_rejects_a_parent_that_was_not_inspected(inspection):
    from application.chat.capabilities.research_planning import ReviseResearchPlanArguments
    from tests.unit.application.test_chat_research_plan_capability import _plan_arguments, _source_snapshots

    revision = _Capability("revise_research_plan", ToolRisk.WRITE, ReviseResearchPlanArguments)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="inspect_research_plans"),)),
        ModelTurn(tool_calls=(ModelToolCall(name="revise_research_plan", arguments={
            **_plan_arguments(), "parent_plan_id": "unread-plan", "source_snapshots": _source_snapshots(),
        }),)),
        ModelTurn(content="I need to read that saved plan before revising it."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        _Capability("inspect_research_plans", ToolRisk.READ, result_data=inspection), revision,
    ))).run_turn(context=_context(), previous_messages=(), user_message="Revise the saved plan")
    assert result.pending_approval is None
    assert revision.executed_arguments == []
    assert result.tool_results[-1].error_code == "research_plan_not_inspected"


@pytest.mark.anyio
async def test_automatically_loaded_exact_reader_stays_available_in_the_turn():
    source = {"document_id": "paper-1", "source_kind": "text_window", "source_ref": "methods"}
    search = _Capability("search_sources", ToolRisk.READ, result_data={"matches": [source]})
    read = _Capability("read_source", ToolRisk.READ, result_data={**source, "content_truncated": False, "source_digest": "a" * 64})
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="search_sources"),)),
        ModelTurn(tool_calls=(ModelToolCall(name="read_source"),)),
        ModelTurn(content="The experiment groups were verified from the complete Methods source."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((search, read))).run_turn(
        context=_context(), previous_messages=(), user_message="Inspect the P002 group definitions",
    )
    assert result.status == "completed"
    assert "read_source" in model.all_tool_spec_names[-1]


@pytest.mark.anyio
async def test_successful_navigation_after_a_failed_read_requires_the_new_source():
    from application.chat import AgentContext
    from application.chat.capabilities.document_sources import ReadSourceCapability, SearchSourcesCapability
    from tests.unit.application.test_chat_p002_source_fixture import _P002CollectionService, _P002SourceRepository

    dependencies = dict(collection_service=_P002CollectionService(), source_artifact_repository=_P002SourceRepository())
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="read_source", arguments={
            "document_id": "doc_ef59d1f3a006", "source_kind": "text_window", "source_ref": "stale-id",
        }),)),
        ModelTurn(tool_calls=(ModelToolCall(name="search_sources", arguments={
            "document_ids": ["doc_ef59d1f3a006"], "query": "NP P150",
        }),)),
        ModelTurn(content="The group definitions are verified."),
        ModelTurn(content="The group definitions are verified."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        ReadSourceCapability(**dependencies), SearchSourcesCapability(**dependencies),
    ))).run_turn(context=AgentContext("session-p002", "researcher-1", "collection-p002"), previous_messages=(), user_message="Inspect the P002 group definitions")
    assert result.tool_calls[-1].name == "search_sources"
    assert result.tool_calls[-1].status == "succeeded"
    assert result.tool_results[-1].data["matches"]
    assert result.error_code == "required_research_action_not_completed"
    assert model.all_tool_spec_names[-1] == ("read_source",)
