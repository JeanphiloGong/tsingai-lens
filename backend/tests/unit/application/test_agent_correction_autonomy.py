"""Acceptance probes against the actual Lens checkout after v2 edits."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.unit.application.test_research_agent_runner import _Capability, _FindingArguments, _Model, _context
from application.chat import AgentRunStatus, CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from domain.chat import ToolRisk

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_known_finding_outside_last_query_reaches_its_handler():
    query = _Capability("query_published_findings", ToolRisk.READ, result_data={
        "objectives": [{"objective_id": "objective-1", "findings": [{"finding_id": "finding-1"}]}],
    })
    inspect = _Capability("inspect_published_finding", ToolRisk.READ, _FindingArguments)
    known = {"objective_id": "objective-1", "finding_id": "finding-2"}
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("query_published_findings", {}),)),
        ModelTurn(tool_calls=(ModelToolCall("inspect_published_finding", known),)),
        ModelTurn(content="The requested Finding was inspected; no record was changed."),
        discover=("query_published_findings", "inspect_published_finding"),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((query, inspect))).run_turn(
        context=_context(), previous_messages=(), user_message="Check finding-2 from the earlier reference.",
    )
    assert inspect.executed_arguments == [known]
    assert result.status is AgentRunStatus.COMPLETED
    assert result.pending_approval is None


async def test_real_finding_handler_checks_collection_before_loading_records():
    from application.chat.capabilities.published_findings import InspectPublishedFindingCapability

    collection = SimpleNamespace(get_collection_for_user=AsyncMock(side_effect=PermissionError()))
    analysis = SimpleNamespace(get_finding=AsyncMock())
    handler = InspectPublishedFindingCapability(
        collection_service=collection, objective_analysis_service=analysis,
        finding_feedback_service=SimpleNamespace(),
    )
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("inspect_published_finding", {
            "objective_id": "objective-1", "finding_id": "finding-2",
        }),)),
        ModelTurn(content="The record could not be accessed. No change was made."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((handler,))).run_turn(
        context=_context(), previous_messages=(), user_message="Inspect finding-2; do not save.",
    )
    collection.get_collection_for_user.assert_awaited_once_with("col-1", "user-1")
    analysis.get_finding.assert_not_awaited()
    assert result.tool_results[-1].status == "failed"
    assert result.pending_approval is None


async def test_transient_draft_can_be_followed_by_reading():
    draft = _Capability("create_finding_draft", ToolRisk.DRAFT, result_data={
        "draft": {"draft_id": "draft-1"}, "persistence": "transient_chat_result",
    })
    read = _Capability("read_source", ToolRisk.READ)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("create_finding_draft", {}),)),
        ModelTurn(tool_calls=(ModelToolCall("read_source", {}),)),
        ModelTurn(content="I checked another passage after the draft. It is still unsaved."),
        discover=("create_finding_draft", "read_source"),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((draft, read))).run_turn(
        context=_context(), previous_messages=(), user_message="Draft a correction; do not save or publish.",
    )
    assert read.executed_arguments == [{}]
    assert result.status is AgentRunStatus.COMPLETED
    assert result.messages[-1].content == "I checked another passage after the draft. It is still unsaved."
    assert result.pending_approval is None
