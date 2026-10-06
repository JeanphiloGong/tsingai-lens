from __future__ import annotations

import json
import logging

import pytest
from pydantic import BaseModel

from application.chat import (
    AgentContext,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
    ToolSpec,
)
from application.chat.agent_runner import AgentRunLimits, _RunProgress
from domain.chat import ToolRisk


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("ending", ["model_answer", "approval_required", "model_unavailable"])
async def test_cycle_trace_records_the_actual_terminal_outcome(ending, caplog) -> None:
    write_capability_name = "create_objective_candidate"

    class Arguments(BaseModel):
        document_id: str

    class Capability:
        spec = ToolSpec(
            name=write_capability_name,
            description="Test approval",
            risk=ToolRisk.WRITE,
            input_model=Arguments,
        )

        async def execute(self, context, arguments):
            pytest.fail("A traced approval must not execute the write")

    class Model:
        async def respond(self, *, context, tool_specs, timeout_seconds=180.0, max_output_tokens=16_384):
            if ending == "model_unavailable":
                raise RuntimeError("private-provider-detail")
            if ending == "approval_required":
                assert [spec.name for spec in tool_specs if spec.name != "discover_research_tools"] == [
                    write_capability_name
                ]
                return ModelTurn(
                    tool_calls=(
                        ModelToolCall(
                            name=write_capability_name,
                            arguments={"document_id": "private-request-argument"},
                        ),
                    )
                )
            return ModelTurn(content="A bounded answer.")

    with caplog.at_level(logging.INFO, logger="application.chat.agent_runner"):
        await ResearchAgentRunner(model=Model(), capabilities=CapabilityRegistry((Capability(),))).run_turn(
            context=AgentContext(session_id="chat-1", user_id="user-1", collection_id="col-1"),
            previous_messages=(), user_message="Save this research objective.",
        )

    entries = [json.loads(record.getMessage().removeprefix("Research Agent cycle "))
               for record in caplog.records if record.getMessage().startswith("Research Agent cycle ")]
    assert entries[-1]["termination_reason"] == ending
    assert entries[-1]["final_answer_present"] is (ending == "model_answer")
    assert entries[-1]["executed_tool_count"] == 0
    assert "private-provider-detail" not in caplog.text
    assert "private-request-argument" not in caplog.text


def test_progress_trace_reports_cumulative_requested_actions_without_dead_plan_state() -> None:
    events: list[dict[str, object]] = []
    progress = _RunProgress(AgentRunLimits(), progress_callback=events.append)
    context = AgentContext(session_id="chat-1", user_id="user-1", collection_id="col-1")

    progress.requested_tool_calls += 2
    progress.trace(context, phase="tools")
    progress.executed_tool_calls = 1
    progress.requested_tool_calls += 1
    progress.trace(context, phase="tools")

    assert [event["requested_tool_count"] for event in events] == [2, 3]
    assert [event["executed_tool_count"] for event in events] == [0, 1]
    assert all("research_plan" not in event for event in events)
