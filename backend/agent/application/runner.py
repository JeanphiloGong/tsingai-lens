"""Run model turns and persist each operation before advancing the Task."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from uuid import uuid4

from pydantic import ValidationError

from agent.tools.registry import CapabilityRegistry, ToolExecutionContext
from agent.domain.models import AgentTask, Operation, TaskStep, digest_arguments
from agent.application.model import ModelTurn
from domain.chat import ChatToolResult, ToolResultStatus


@dataclass(frozen=True)
class RunnerState:
    task: AgentTask
    operations: tuple[Operation, ...]
    steps: tuple[TaskStep, ...]
    messages: tuple[dict[str, object], ...]


Checkpoint = Callable[[RunnerState], Awaitable[None]]
Respond = Callable[[tuple[Operation, ...]], Awaitable[ModelTurn]]


class DurableRunner:
    def __init__(self, *, registry: CapabilityRegistry, checkpoint: Checkpoint, respond: Respond) -> None:
        self.registry = registry
        self.checkpoint = checkpoint
        self.respond = respond

    async def run(
        self, state: RunnerState, *, user_id: str, workspace_id: str
    ) -> RunnerState:
        if state.task.status in {"completed", "failed", "cancelled", "approval_required"}:
            return state
        if state.task.status in {"accepted", "interrupted"}:
            state = await self._save(state, status="running")

        while True:
            pending = next(
                (item for item in state.operations if item.status in {
                    "requested", "approved", "running", "needs_reconciliation", "approval_required",
                }),
                None,
            )
            if pending is not None:
                if pending.status in {"running", "needs_reconciliation"}:
                    return await self._save(
                        state, status="interrupted",
                        operation=replace(pending, status="needs_reconciliation"),
                    )
                if pending.status == "approval_required":
                    return await self._save(state, status="approval_required")
                pending = replace(pending, status="running")
                state = await self._save(state, operation=pending)
                result = await self._execute(pending, state.task, user_id, workspace_id)
                state = await self._save(
                    state,
                    operation=replace(
                        pending,
                        status="failed" if result.status is ToolResultStatus.FAILED else "succeeded",
                        result=asdict(result),
                        error_code=result.error_code,
                        error_message=result.error_message,
                    ),
                )
                continue

            if len(state.operations) >= 24:
                return await self._save(state, status="failed")
            turn = await self.respond(state.operations)
            if not turn.tool_calls:
                return await self._save(
                    state,
                    status="completed",
                    message={
                        "role": "assistant",
                        "content": turn.content,
                        "citations": [asdict(item) for item in turn.citations],
                        "produced_by_task_id": state.task.task_id,
                    },
                )
            # Persist every requested operation before running any of them.
            for call in turn.tool_calls:
                operation_id = f"op_{uuid4().hex}"
                arguments = dict(call.arguments)
                spec = self.registry.get(call.name)
                requires_approval = spec is not None and spec.requires_approval
                state = await self._save(
                    state,
                    status="approval_required" if requires_approval else state.task.status,
                    message={"role": "assistant", "content": turn.content, "message_id": f"msg_{uuid4().hex}"},
                    operation=Operation(
                        operation_id, state.task.task_id, call.name, digest_arguments(arguments),
                        "approval_required" if requires_approval else "requested",
                        arguments=arguments,
                        tool_call_id=f"call_{uuid4().hex}",
                    ),
                )
                if requires_approval:
                    return state

    async def _save(
        self, state: RunnerState, *, status=None, operation: Operation | None = None,
        message: dict[str, object] | None = None,
    ) -> RunnerState:
        task = state.task.checkpoint(state.task.checkpoint_revision + 1)
        if status is not None and status != task.status:
            task = task.transition(status)
        operations = state.operations
        if operation is not None:
            if message is not None:
                operation = replace(operation, assistant_message_id=str(message["message_id"]))
            if any(item.operation_id == operation.operation_id for item in operations):
                operations = tuple(
                    operation if item.operation_id == operation.operation_id else item
                    for item in operations
                )
            else:
                operations += (operation,)
        next_state = replace(
            state, task=task, operations=operations,
            messages=state.messages + (message,) if message is not None else state.messages,
        )
        await self.checkpoint(next_state)
        return next_state

    async def _execute(
        self, operation: Operation, task: AgentTask, user_id: str, workspace_id: str
    ) -> ChatToolResult:
        context = ToolExecutionContext(
            user_id=user_id, workspace_id=workspace_id, task_id=task.task_id,
            operation_id=operation.operation_id,
            tool_call_id=operation.tool_call_id or operation.operation_id,
        )
        spec = self.registry.get(operation.name)
        if spec is None:
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                error_code="unknown_tool", error_message="Tool is not registered.",
            )
        try:
            arguments = spec.input_model.model_validate(operation.arguments)
        except ValidationError as exc:
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                error_code="invalid_arguments", error_message=exc.title,
            )
        return await spec.handler(context, arguments)


__all__ = ["Checkpoint", "DurableRunner", "RunnerState"]
