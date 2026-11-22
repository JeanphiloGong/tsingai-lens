import pytest

from agent.application.runner import DurableRunner, RunnerState
from agent.domain.models import AgentTask, Operation


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

    async def capability(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        return {"hold_time_minutes": 30}

    async def checkpoint(state: RunnerState) -> None:
        nonlocal committed, interrupt_after_checkpoint
        committed = state
        if interrupt_after_checkpoint:
            interrupt_after_checkpoint = False
            raise ExecutionInterrupted()

    initial = RunnerState(
        task=AgentTask("task-1", "conv-1", "msg-1", "running"),
        operations=(
            Operation("op-1", "task-1", "read_source", "a" * 64, "requested"),
        ),
        steps=(),
        messages=(),
    )
    runner = DurableRunner(capability=capability, checkpoint=checkpoint)
    with pytest.raises(ExecutionInterrupted):
        await runner.run(initial, request="inspect Source")
    assert attempts == 1
    assert committed is not None

    resumed = await runner.run(committed, request="inspect Source")
    assert resumed.task.status == "completed"
    assert attempts == 1
    assert len(
        [
            message
            for message in resumed.messages
            if message["role"] == "assistant"
        ]
    ) == 1
    assert resumed.operations[0].result == {"hold_time_minutes": 30}
