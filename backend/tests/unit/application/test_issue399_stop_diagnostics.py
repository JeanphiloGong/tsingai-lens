"""Distinguish runtime stops from scientific absence and measure actual reads."""

import pytest

from application.chat import (
    AgentCompletionReason,
    AgentRunLimits,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
)
from application.chat.agent_runner import _RunProgress
from domain.chat import ChatToolCall, ChatToolResult, ToolResultStatus, ToolRisk
from tests.unit.application.test_research_agent_runner import _Capability, _Model, _context


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("field,value,reason", [
    ("restored_elapsed_seconds", 300, "resource_budget"),
    ("executed_tool_calls", 96, "resource_budget"),
    ("model_tokens", 1_000_000, "resource_budget"),
    ("model_cycles", 64, "emergency_ceiling"),
    ("consecutive_no_progress", 2, "no_progress"),
])
def test_runtime_stop_has_a_specific_reason(field, value, reason):
    progress = _RunProgress(AgentRunLimits())
    setattr(progress, field, value)
    assert progress.stop_before_model().value == reason


@pytest.mark.anyio
async def test_reading_volume_and_stop_reason_reach_snapshot():
    read = _Capability("test_source", ToolRisk.READ, result_data={
        "sources": [{"content": "Methods passage", "content_truncated": False}],
    })
    events = []
    result = await ResearchAgentRunner(
        model=_Model(
            ModelTurn(tool_calls=(ModelToolCall("test_source", {}),)),
            ModelTurn(content="Partial review; next check remains."),
        ),
        capabilities=CapabilityRegistry((read,)),
        limits=AgentRunLimits(max_tool_calls=2),
    ).run_turn(
        context=_context(), previous_messages=(), user_message="Review the paper",
        progress_callback=events.append,
    )
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert events[-1]["source_content_chars"] == len("Methods passage")
    assert events[-1]["source_batch_count"] == 1
    assert events[-1]["empty_source_batch_count"] == 0
    assert events[-1]["remaining_seconds"] >= 0
    assert events[-1]["termination_reason"] == "resource_budget"


def test_read_diagnostics_count_transfers_not_unique_evidence():
    progress = _RunProgress(AgentRunLimits(max_elapsed_seconds=None))
    call = ChatToolCall.requested(
        tool_call_id="read", session_id="chat-1", assistant_message_id="assistant-1",
        name="read_source", arguments={}, risk=ToolRisk.READ,
    )
    for data in ({"content": "abc"}, {"content": "abc"}, {"sources": [{"content": ""}]}):
        progress.observe(call, ChatToolResult(
            tool_call_id="read", status=ToolResultStatus.SUCCEEDED, data=data,
        ))
    progress.observe(call, ChatToolResult(
        tool_call_id="read", status=ToolResultStatus.SUCCEEDED, data={"sources": []},
    ))
    progress.observe(call, ChatToolResult(
        tool_call_id="read", status=ToolResultStatus.FAILED,
        error_code="source_missing", error_message="Unavailable", data={"content": "ignored"},
    ))
    assert progress.source_content_chars == 6
    assert progress.source_batch_count == 3
    assert progress.empty_source_batch_count == 1
    events = []
    progress.progress_callback = events.append
    progress.trace(_context(), phase="test")
    assert events[-1]["remaining_seconds"] is None
    assert "abc" not in str(events[-1])
