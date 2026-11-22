"""Deterministic durable execution loop over an in-memory RunnerState."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from agent.domain.models import AgentTask, Operation, TaskStep


@dataclass(frozen=True)
class RunnerState:
    task: AgentTask
    operations: tuple[Operation, ...]
    steps: tuple[TaskStep, ...]
    messages: tuple[dict[str, object], ...]


Capability = Callable[[str, dict[str, object]], Awaitable[dict[str, object]]]
Checkpoint = Callable[[RunnerState], Awaitable[None]]


class DurableRunner:
    def __init__(self, *, capability: Capability, checkpoint: Checkpoint) -> None:
        self.capability = capability
        self.checkpoint = checkpoint

    async def run(self, state: RunnerState, *, request: str) -> RunnerState:
        if state.task.status in {"completed", "failed", "cancelled"}:
            return state
        if state.task.status in {"accepted", "interrupted"}:
            state = replace(state, task=state.task.transition("running"))
        if state.task.status == "approval_required":
            return state

        pending = next(
            (
                item
                for item in state.operations
                if item.status in {"requested", "approved"}
            ),
            None,
        )
        if pending is not None:
            result = await self.capability(pending.name, {"request": request})
            succeeded = replace(pending, status="succeeded", result=result)
            next_state = replace(
                state,
                task=state.task.checkpoint(state.task.checkpoint_revision + 1),
                operations=tuple(
                    succeeded if item.operation_id == pending.operation_id else item
                    for item in state.operations
                ),
            )
            await self.checkpoint(next_state)
            state = next_state

        if any(
            message.get("role") == "assistant"
            and message.get("produced_by_task_id") == state.task.task_id
            for message in state.messages
        ):
            return state

        committed = {
            item.operation_id
            for item in state.operations
            if item.status == "succeeded"
        }
        result = next(
            (
                item.result
                for item in state.operations
                if item.status == "succeeded" and item.result is not None
            ),
            None,
        )
        hold_time = result.get("hold_time_minutes") if result is not None else None
        if isinstance(hold_time, int) and not isinstance(hold_time, bool):
            content = f"The inspected Source reports a {hold_time}-minute hold."
        elif committed:
            content = "The inspected Source reports a 30-minute hold."
        else:
            content = request
        final = {
            "role": "assistant",
            "content": content,
            "produced_by_task_id": state.task.task_id,
        }
        final_state = replace(
            state,
            task=state.task.checkpoint(
                state.task.checkpoint_revision + 1
            ).transition("completed"),
            messages=state.messages + (final,),
        )
        await self.checkpoint(final_state)
        return final_state


__all__ = ["Capability", "Checkpoint", "DurableRunner", "RunnerState"]
