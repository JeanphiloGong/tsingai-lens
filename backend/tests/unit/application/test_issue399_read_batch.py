import json

from application.chat import (
    CapabilityRegistry,
    ModelTurn,
    ModelToolCall,
    ResearchAgentRunner,
    AgentRunLimits,
)
from application.chat.agent_runner import _RunProgress
from domain.chat import ToolRisk
from tests.unit.application.test_research_agent_runner import _Capability, _context


def test_large_batch_keeps_room_for_source_bodies():
    capability = _Capability("read_source", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=None, capabilities=CapabilityRegistry((capability,))
    )
    progress = _RunProgress(AgentRunLimits(), read_batch_tokens=8192)
    progress.start_response()
    messages = []
    requests = runner._requested_calls(
        _context(),
        messages,
        ModelTurn(
            tool_calls=tuple(
                ModelToolCall("read_source", {"document_id": f"paper-{i}"})
                for i in range(8)
            )
        ),
        allowed_names={"read_source"},
        progress=progress,
    )
    assert len(requests) == 2
    assert len(messages[-1].tool_calls) == 2
    assert progress.deferred_read_calls == 6

    pending = json.loads(messages[-1].content.split("arguments:\n", 1)[1])
    assert [item["arguments"]["document_id"] for item in pending] == [
        f"paper-{i}" for i in range(2, 8)
    ]
    seen = [call.arguments["document_id"] for call, _ in requests]
    while pending:
        progress.start_response()
        requests = runner._requested_calls(
            _context(),
            messages,
            ModelTurn(
                tool_calls=tuple(
                    ModelToolCall(item["name"], item["arguments"]) for item in pending
                )
            ),
            allowed_names={"read_source"},
            progress=progress,
        )
        seen.extend(call.arguments["document_id"] for call, _ in requests)
        pending = (
            json.loads(messages[-1].content.split("arguments:\n", 1)[1])
            if "arguments:\n" in messages[-1].content
            else []
        )
    assert seen == [f"paper-{i}" for i in range(8)]
