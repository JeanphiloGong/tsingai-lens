import pytest
from pydantic import BaseModel

from agent.application.runner import DurableRunner, RunnerState
from agent.capabilities import CapabilityRegistry, ToolExecutionContext, ToolSpec
from agent.domain.models import AgentTask, Operation
from domain.chat import ChatToolResult, ToolResultStatus


class ExecutionInterrupted(RuntimeError):
    pass


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_runner_reuses_committed_operation_after_checkpoint_interrupt():
    attempts = 0
    committed: RunnerState | None = None
    interrupt_after_checkpoint = True

    class ReadSourceArguments(BaseModel):
        source_ref: str

    async def read_source(
        context: ToolExecutionContext, arguments: BaseModel
    ) -> ChatToolResult:
        nonlocal attempts
        attempts += 1
        parsed = ReadSourceArguments.model_validate(arguments)
        assert context.user_id == "user-1"
        assert context.workspace_id == "workspace-1"
        assert parsed.source_ref == "methods"
        return ChatToolResult(
            tool_call_id=context.tool_call_id or "call-1",
            status=ToolResultStatus.SUCCEEDED,
            data={"hold_time_minutes": 30},
        )

    registry = CapabilityRegistry(
        (
            ToolSpec(
                name="read_source",
                description="Read one Source.",
                input_model=ReadSourceArguments,
                handler=read_source,
                source="document",
            ),
        )
    )

    async def checkpoint(state: RunnerState) -> None:
        nonlocal committed, interrupt_after_checkpoint
        committed = state
        if interrupt_after_checkpoint:
            interrupt_after_checkpoint = False
            raise ExecutionInterrupted()

    initial = RunnerState(
        task=AgentTask("task-1", "conv-1", "msg-1", "running"),
        operations=(
            Operation(
                "op-1",
                "task-1",
                "read_source",
                "a" * 64,
                "requested",
                arguments={"source_ref": "methods"},
                tool_call_id="call-1",
            ),
        ),
        steps=(),
        messages=(),
    )
    runner = DurableRunner(registry=registry, checkpoint=checkpoint)
    with pytest.raises(ExecutionInterrupted):
        await runner.run(
            initial,
            request="inspect Source",
            user_id="user-1",
            workspace_id="workspace-1",
        )
    assert attempts == 1
    assert committed is not None

    resumed = await runner.run(
        committed,
        request="inspect Source",
        user_id="user-1",
        workspace_id="workspace-1",
    )
    assert resumed.task.status == "completed"
    assert attempts == 1
    assert len(
        [
            message
            for message in resumed.messages
            if message["role"] == "assistant"
        ]
    ) == 1
    assert resumed.operations[0].result is not None
    assert resumed.operations[0].result["data"] == {"hold_time_minutes": 30}


@pytest.mark.anyio
async def test_runner_records_unknown_tool_without_calling_a_handler():
    calls = 0

    class EmptyArguments(BaseModel):
        pass

    async def unexpected_handler(
        _context: ToolExecutionContext, _arguments: BaseModel
    ) -> ChatToolResult:
        nonlocal calls
        calls += 1
        raise AssertionError("unknown tool reached a handler")

    registry = CapabilityRegistry(
        (
            ToolSpec(
                name="read_source",
                description="Read one Source.",
                input_model=EmptyArguments,
                handler=unexpected_handler,
                source="document",
            ),
        )
    )
    state = RunnerState(
        task=AgentTask("task-2", "conv-1", "msg-1", "running"),
        operations=(
            Operation("op-2", "task-2", "missing_tool", "b" * 64, "requested"),
        ),
        steps=(),
        messages=(),
    )
    saved: list[RunnerState] = []

    async def checkpoint(next_state: RunnerState) -> None:
        saved.append(next_state)

    result = await DurableRunner(registry=registry, checkpoint=checkpoint).run(
        state,
        request="inspect Source",
        user_id="user-1",
        workspace_id="workspace-1",
    )

    assert calls == 0
    assert saved[0].operations[0].status == "failed"
    assert saved[0].operations[0].error_code == "unknown_tool"
    assert result.task.status == "completed"
