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
from domain.chat import ToolRisk


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("ending", ["model_answer", "approval_required", "model_unavailable"])
async def test_cycle_trace_records_the_actual_terminal_outcome(ending, caplog) -> None:
    class Arguments(BaseModel):
        document_id: str

    class Capability:
        spec = ToolSpec(name="test_write", description="Test approval", risk=ToolRisk.WRITE,
                        input_model=Arguments)

        async def execute(self, context, arguments):
            pytest.fail("A traced approval must not execute the write")

    class Model:
        def respond(self, *, context, tool_specs):
            if ending == "model_unavailable":
                raise RuntimeError("private-provider-detail")
            if ending == "approval_required":
                return ModelTurn(tool_calls=(ModelToolCall(name="test_write", arguments={
                    "document_id": "private-request-argument",
                }),))
            return ModelTurn(content="A bounded answer.")

    with caplog.at_level(logging.INFO, logger="application.chat.agent_runner"):
        await ResearchAgentRunner(model=Model(), capabilities=CapabilityRegistry((Capability(),))).run_turn(
            context=AgentContext(session_id="chat-1", user_id="user-1", collection_id="col-1"),
            previous_messages=(), user_message="Review the request.",
        )

    entries = [json.loads(record.getMessage().removeprefix("Research Agent cycle "))
               for record in caplog.records if record.getMessage().startswith("Research Agent cycle ")]
    assert entries[-1]["termination_reason"] == ending
    assert entries[-1]["final_answer_present"] is (ending == "model_answer")
    assert entries[-1]["executed_tool_count"] == 0
    assert "private-provider-detail" not in caplog.text
    assert "private-request-argument" not in caplog.text
