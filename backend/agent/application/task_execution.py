"""Direct Task execution and checkpoint rehydration."""

from __future__ import annotations

from dataclasses import asdict, replace

from agent.application.runner import DurableRunner, RunnerState
from agent.domain.models import AgentTask, Operation, TaskStep
from agent.repositories.task_repository import TaskRepository


class TaskExecution:
    def __init__(self, repository: TaskRepository, runner: DurableRunner) -> None:
        self.repository = repository
        self.runner = runner

    async def run_task(self, *, task_id: str, user_id: str, request: str) -> str:
        async with self.repository.execution_lock(task_id):
            context = await self.repository.load_for_execution(
                task_id=task_id, user_id=user_id
            )
            task = AgentTask(
                context.task_id,
                context.conversation_id,
                context.trigger_message_id,
                context.status,
                context.checkpoint_revision,
            )
            checkpoint = context.checkpoint
            state = RunnerState(
                task=task,
                operations=tuple(
                    Operation(**item) for item in checkpoint.get("operations", [])
                ),
                steps=tuple(TaskStep(**item) for item in checkpoint.get("steps", [])),
                messages=tuple(checkpoint.get("messages", [])),
            )
            expected_revision = state.task.checkpoint_revision
            previous_state = state

            async def save(next_state: RunnerState) -> None:
                nonlocal expected_revision, previous_state
                previous_operations = {
                    item.operation_id: item for item in previous_state.operations
                }
                operation = next(
                    (
                        item
                        for item in next_state.operations
                        if previous_operations.get(item.operation_id) != item
                    ),
                    None,
                )
                message = (
                    next_state.messages[-1]
                    if len(next_state.messages) > len(previous_state.messages)
                    else None
                )
                if message is not None:
                    message = {
                        "message_id": f"msg_{task_id}_{len(next_state.messages)}",
                        "conversation_id": context.conversation_id,
                        "parent_message_id": context.trigger_message_id,
                        "role": message["role"],
                        "content": message["content"],
                    }
                step = {
                    "step_id": f"step_{task_id}_{expected_revision}",
                    "task_id": task_id,
                    "sequence": expected_revision,
                    "name": "research_turn",
                    "status": "completed",
                    "checkpoint": {
                        "operation_count": len(next_state.operations),
                    },
                }
                steps = list(previous_state.steps)
                for item in next_state.steps:
                    steps = [
                        existing
                        for existing in steps
                        if existing.sequence != item.sequence
                    ]
                    steps.append(item)
                steps.append(TaskStep(**step))
                await self.repository.write_checkpoint_bundle(
                    task_id=task_id,
                    expected_revision=expected_revision,
                    message=message,
                    operation=asdict(operation) if operation is not None else None,
                    step=step,
                    checkpoint={
                        "operations": [
                            asdict(item) for item in next_state.operations
                        ],
                        "steps": [asdict(item) for item in steps],
                        "messages": list(next_state.messages),
                    },
                    status=next_state.task.status,
                )
                expected_revision += 1
                previous_state = replace(next_state, steps=tuple(steps))

            runner = DurableRunner(
                capability=self.runner.capability,
                checkpoint=save,
            )
            final = await runner.run(state, request=request)
            return final.task.status


__all__ = ["TaskExecution"]
