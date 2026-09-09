import pytest

from application.chat import AgentContext, CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat.capabilities import ProposeResearchPlanCapability
from tests.unit.application.test_chat_research_plan_capability import (
    _CollectionService, _FindingFeedbackService, _Model, _plan_arguments,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("missing_control", [False, True])
@pytest.mark.parametrize("initial_schema_error", [False, True])
async def test_plan_can_correct_unlinked_evidence_before_returning_a_draft(missing_control, initial_schema_error):
    proposal = ProposeResearchPlanCapability(
        collection_service=_CollectionService(), finding_feedback_service=_FindingFeedbackService()
    )
    invalid = _plan_arguments()
    invalid["evidence_ids"].append("evidence-from-another-finding")
    malformed = _plan_arguments()
    del malformed["controls"]
    correction = (ModelTurn(tool_calls=(ModelToolCall("propose_research_plan", malformed),)),) if missing_control else ()
    model = _Model(
        *((ModelTurn(tool_calls=(ModelToolCall("propose_research_plan", malformed),)),) if initial_schema_error else ()),
        ModelTurn(tool_calls=(ModelToolCall("propose_research_plan", invalid),)),
        ModelTurn(content="I will correct the Evidence selection before returning the plan."),
        *correction,
        ModelTurn(tool_calls=(ModelToolCall("propose_research_plan", _plan_arguments()),)),
        ModelTurn(content="The provisional plan now cites only the selected finding's evidence."),
        expected_tools={"propose_research_plan"},
    )
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((proposal,)))
    result = await runner.run_turn(
        context=AgentContext(session_id="chat-1", user_id="user-1", collection_id="col-1"),
        previous_messages=(), user_message="Draft a research plan with at most four samples per group; do not save.",
    )
    assert result.status.value == "completed"
    assert len(result.tool_results) == 3 + int(missing_control) + int(initial_schema_error)
    assert result.tool_results[1 + int(initial_schema_error)].data["draft_status"] == "abstained"
    if missing_control:
        assert result.tool_results[-2].error_code == "invalid_tool_arguments"
        assert "controls (missing)" in result.tool_results[-2].error_message
    assert result.tool_results[-1].data["draft_id"]
    assert result.tool_results[-1].data["structured_plan"]
