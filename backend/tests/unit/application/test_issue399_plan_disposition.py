import pytest
from application.chat import (
    CapabilityRegistry,
    ModelTurn,
    ModelToolCall,
    ResearchAgentRunner,
)
from application.chat.agent_runner import AgentCompletionReason
from tests.unit.application.test_research_agent_runner import _Model, _context


@pytest.fixture
def anyio_backend():
    return "asyncio"


def plan(status="in_progress"):
    return ModelTurn(
        tool_calls=(
            ModelToolCall(
                "update_execution_plan",
                {
                    "steps": [
                        {
                            "step_id": "conditions",
                            "action": "Check tensile orientation",
                            "status": (
                                "completed"
                                if status == "completed"
                                else (
                                    "blocked"
                                    if status != "in_progress"
                                    else "in_progress"
                                )
                            ),
                        }
                    ],
                    "status": status,
                    "explanation": "Orientation must be checked or explicitly reported as unknown.",
                },
            ),
        )
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "disposition", ["completed", "waiting_for_clarification", "scientific_refusal"]
)
async def test_narrative_cannot_close_active_plan_before_model_disposition(disposition):
    model = _Model(
        plan(),
        ModelTurn(content="Next I will inspect the conditions."),
        plan(disposition),
        ModelTurn(content="Supported result or focused clarification."),
        discover=("update_execution_plan",),
    )
    deltas = []
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry(())
    ).run_turn(
        context=_context(),
        previous_messages=(),
        user_message="Compare the paper conditions",
        text_delta_callback=deltas.append,
    )
    assert result.error_code is None
    assert result.execution_plan["model_status"] == disposition
    assert not any("Next I will" in m.content for m in result.messages)
    assert "Next I will" not in "".join(deltas)
    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER


@pytest.mark.anyio
async def test_repeated_narrative_stops_with_explicit_stalled_plan():
    model = _Model(
        plan(),
        ModelTurn(content="I will read next."),
        ModelTurn(content="I will read later."),
        ModelTurn(
            content="Conditions remain unchecked. Continue the unfinished review."
        ),
        discover=("update_execution_plan",),
    )
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry(())
    ).run_turn(
        context=_context(), previous_messages=(), user_message="Compare conditions"
    )
    assert result.error_code is None
    assert result.completion_reason is AgentCompletionReason.NO_PROGRESS
    assert result.execution_plan["status"] == "stalled"
    assert result.execution_plan["model_status"] == "in_progress"
    assert result.warnings
