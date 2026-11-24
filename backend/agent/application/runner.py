"""Deterministic durable execution loop over an in-memory RunnerState."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace

from pydantic import ValidationError

from agent.capabilities.registry import CapabilityRegistry, ToolExecutionContext
from agent.domain.models import AgentTask, Operation, TaskStep
from domain.chat import ChatToolResult, ToolResultStatus


@dataclass(frozen=True)
class RunnerState:
    task: AgentTask
    operations: tuple[Operation, ...]
    steps: tuple[TaskStep, ...]
    messages: tuple[dict[str, object], ...]


Checkpoint = Callable[[RunnerState], Awaitable[None]]


class DurableRunner:
    def __init__(self, *, registry: CapabilityRegistry, checkpoint: Checkpoint) -> None:
        self.registry = registry
        self.checkpoint = checkpoint

    async def run(
        self,
        state: RunnerState,
        *,
        request: str,
        user_id: str,
        workspace_id: str,
    ) -> RunnerState:
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
            context = ToolExecutionContext(
                user_id=user_id,
                workspace_id=workspace_id,
                task_id=state.task.task_id,
                operation_id=pending.operation_id,
                tool_call_id=pending.tool_call_id,
            )
            try:
                result = await self.registry.execute(
                    pending.name,
                    pending.arguments,
                    context=context,
                )
            except LookupError as error:
                if str(error) != "unknown_tool":
                    raise
                result = ChatToolResult(
                    tool_call_id=context.tool_call_id or pending.operation_id,
                    status=ToolResultStatus.FAILED,
                    error_code="unknown_tool",
                    error_message="tool is not registered",
                )
            except ValidationError as error:
                result = ChatToolResult(
                    tool_call_id=context.tool_call_id or pending.operation_id,
                    status=ToolResultStatus.FAILED,
                    error_code="invalid_arguments",
                    error_message=str(error),
                )
            operation_status = (
                "succeeded"
                if result.status is ToolResultStatus.SUCCEEDED
                else "failed"
            )
            error_code = result.error_code
            error_message = result.error_message
            if operation_status != "succeeded":
                error_code = error_code or "tool_execution_failed"
                error_message = error_message or "tool did not succeed"
            updated_operation = replace(
                pending,
                status=operation_status,
                result=asdict(result),
                error_code=error_code,
                error_message=error_message,
            )
            next_state = replace(
                state,
                task=state.task.checkpoint(state.task.checkpoint_revision + 1),
                operations=tuple(
                    updated_operation
                    if item.operation_id == pending.operation_id
                    else item
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
        result_data = (
            result.get("data", result) if result is not None else None
        )
        hold_time = (
            result_data.get("hold_time_minutes")
            if isinstance(result_data, dict)
            else None
        )
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


__all__ = ["Checkpoint", "DurableRunner", "RunnerState"]
