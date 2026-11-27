"""Agent Task, Operation, Step, and checkpoint persistence."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import (
    AgentOperationORM,
    AgentTaskORM,
    AgentTaskStepORM,
    ChatModelCallORM,
)
from infra.persistence.postgres.models.workspace import WorkspaceORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class TaskNotFound(FileNotFoundError):
    """The Task is missing or outside the authenticated Conversation."""


class CheckpointConflict(ValueError):
    """Execution attempted to save from an obsolete checkpoint revision."""


class TaskBusyError(RuntimeError):
    """Another execution currently owns the Task execution lock."""


class OperationDecisionConflict(ValueError):
    """The operation cannot accept the requested decision."""


class TaskResumeConflict(ValueError):
    """The Task cannot be resumed from the supplied checkpoint."""


@dataclass(frozen=True)
class TaskExecutionContext:
    task_id: str
    conversation_id: str
    workspace_id: str
    trigger_message_id: str | None
    status: str
    checkpoint_revision: int
    checkpoint: dict[str, Any]
    model_connection_id: str | None
    messages: tuple[dict[str, Any], ...]


def _now() -> datetime:
    return datetime.now(UTC)


class TaskRepository:
    async def read_successful_results(
        self, *, task_id: str, user_id: str, names: tuple[str, ...]
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        async with AsyncSessionLocal() as db:
            task = await db.scalar(
                select(AgentTaskORM)
                .join(ConversationORM, ConversationORM.conversation_id == AgentTaskORM.session_id)
                .join(WorkspaceORM, WorkspaceORM.workspace_id == ConversationORM.workspace_id)
                .where(
                    AgentTaskORM.task_id == task_id,
                    ConversationORM.user_id == user_id,
                    ConversationORM.deleted_at.is_(None),
                    WorkspaceORM.owner_user_id == user_id,
                )
            )
            if task is None:
                raise TaskNotFound("task not found")
            path = select(MessageORM.message_id, MessageORM.parent_message_id).where(
                MessageORM.conversation_id == task.session_id,
                MessageORM.message_id == task.trigger_message_id,
            ).cte("selected_path", recursive=True)
            path = path.union(
                select(MessageORM.message_id, MessageORM.parent_message_id)
                .join(path, MessageORM.message_id == path.c.parent_message_id)
                .where(MessageORM.conversation_id == task.session_id)
            )
            rows = (await db.execute(
                select(AgentOperationORM.name, AgentOperationORM.result)
                .join(AgentTaskORM, AgentTaskORM.task_id == AgentOperationORM.task_id)
                .where(
                    AgentTaskORM.session_id == task.session_id,
                    (AgentTaskORM.task_id == task_id)
                    | AgentTaskORM.final_message_id.in_(select(path.c.message_id)),
                    AgentOperationORM.status == "succeeded",
                    AgentOperationORM.name.in_(names),
                    AgentOperationORM.result.is_not(None),
                )
                .order_by(AgentOperationORM.created_at, AgentOperationORM.operation_id)
            )).all()
            return tuple((name, result) for name, result in rows)

    async def start_model_call(
        self,
        *,
        task_id: str,
        conversation_id: str,
        call_id: str,
        trigger_message_id: str | None,
        response_message_id: str | None,
        model_connection_id: str,
        purpose: str,
        request: dict[str, Any],
        request_digest: str,
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            sequence = await db.scalar(
                select(func.coalesce(func.max(ChatModelCallORM.sequence) + 1, 0))
                .where(ChatModelCallORM.task_id == task_id)
            )
            db.add(ChatModelCallORM(
                call_id=call_id,
                task_id=task_id,
                session_id=conversation_id,
                sequence=sequence,
                trigger_message_id=trigger_message_id,
                response_message_id=response_message_id,
                model_connection_id=model_connection_id,
                purpose=purpose,
                model=str(request.get("model") or "unknown"),
                request=request,
                request_digest=request_digest,
                status="recorded",
                started_at=_now(),
            ))

    async def finish_model_call(
        self,
        *,
        task_id: str,
        call_id: str,
        status: str,
        finished_at: datetime,
        error_code: str | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(ChatModelCallORM, call_id, with_for_update=True)
            if row is None or row.task_id != task_id:
                raise TaskNotFound(f"model call not found: {call_id}")
            if row.finished_at is not None:
                if row.status != status:
                    raise ValueError("model call outcome cannot be reassigned")
                return
            row.status = status
            row.finished_at = finished_at
            row.error_code = error_code
            row.provider_confirmed = status == "provider_succeeded"
            row.prompt_tokens = prompt_tokens
            row.completion_tokens = completion_tokens
            row.total_tokens = total_tokens

    @asynccontextmanager
    async def execution_lock(self, task_id: str):
        """Hold one PostgreSQL advisory lock for the complete Task run."""

        async with AsyncSessionLocal() as db, db.begin():
            acquired = await db.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        func.hashtextextended(f"agent-task:{task_id}", 0)
                    )
                )
            )
            if not acquired:
                raise TaskBusyError("task execution is already in progress")
            # Keep this transaction and its advisory lock out of the pool while
            # capability execution is awaiting external work.
            connection = await db.connection()
            connection.sync_connection.detach()
            yield

    async def insert_accepted_task(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        conversation_id: str,
        trigger_message_id: str,
        model_connection_id: str | None = None,
    ) -> None:
        now = _now()
        db.add(
            AgentTaskORM(
                task_id=task_id,
                session_id=conversation_id,
                trigger_kind="user_message",
                trigger_message_id=trigger_message_id,
                status="accepted",
                checkpoint_revision=0,
                checkpoint={},
                model_connection_id=model_connection_id,
                started_at=now,
                updated_at=now,
            )
        )

    async def load_for_execution(
        self, *, task_id: str, user_id: str
    ) -> TaskExecutionContext:
        async with AsyncSessionLocal() as db, db.begin():
            row = (
                await db.execute(
                    select(AgentTaskORM, ConversationORM.workspace_id)
                    .join(
                        ConversationORM,
                        ConversationORM.conversation_id == AgentTaskORM.session_id,
                    )
                    .join(
                        WorkspaceORM,
                        WorkspaceORM.workspace_id == ConversationORM.workspace_id,
                    )
                    .where(
                        AgentTaskORM.task_id == task_id,
                        ConversationORM.user_id == user_id,
                        WorkspaceORM.owner_user_id == user_id,
                        ConversationORM.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise TaskNotFound("task not found")
            task, workspace_id = row
            history = []
            message_id = task.trigger_message_id
            while message_id is not None:
                message = await db.scalar(
                    select(MessageORM).where(
                        MessageORM.conversation_id == task.session_id,
                        MessageORM.message_id == message_id,
                    )
                )
                if message is None:
                    raise TaskNotFound("task message not found")
                if message.role in {"user", "assistant"} and message.content:
                    history.append({
                        "message_id": message.message_id,
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat(),
                        "source_contexts": message.source_contexts,
                    })
                message_id = message.parent_message_id
            return TaskExecutionContext(
                task_id=task.task_id,
                conversation_id=task.session_id,
                workspace_id=workspace_id,
                trigger_message_id=task.trigger_message_id,
                status=task.status,
                checkpoint_revision=task.checkpoint_revision,
                checkpoint=dict(task.checkpoint),
                model_connection_id=task.model_connection_id,
                messages=tuple(reversed(history)),
            )

    async def bind_model_connection(
        self, *, task_id: str, connection_id: str, display_name: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            task = await self._lock_task_for_checkpoint(db, task_id)
            task.model_connection_id = connection_id
            task.model_connection_name = display_name

    async def save_checkpoint(
        self,
        *,
        task_id: str,
        expected_revision: int,
        checkpoint: dict[str, Any],
        status: str,
    ) -> int:
        async with AsyncSessionLocal() as db, db.begin():
            task = await self._lock_task_for_checkpoint(db, task_id)
            self._require_revision(task, expected_revision)
            revision = expected_revision + 1
            task.checkpoint_revision = revision
            task.checkpoint = checkpoint
            task.status = status
            task.updated_at = _now()
            return revision

    async def record_model_failure(
        self, *, task_id: str, expected_revision: int, error_code: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            task = await self._lock_task_for_checkpoint(db, task_id)
            self._require_revision(task, expected_revision)
            task.checkpoint = {**task.checkpoint, "error_code": error_code}
            task.checkpoint_revision += 1
            task.status = "interrupted"
            task.updated_at = _now()

    async def read_task(
        self, *, conversation_id: str, task_id: str, user_id: str
    ) -> dict[str, object]:
        async with AsyncSessionLocal() as db:
            task = await db.scalar(
                select(AgentTaskORM)
                .join(
                    ConversationORM,
                    ConversationORM.conversation_id == AgentTaskORM.session_id,
                )
                .join(
                    WorkspaceORM,
                    WorkspaceORM.workspace_id == ConversationORM.workspace_id,
                )
                .where(
                    AgentTaskORM.session_id == conversation_id,
                    AgentTaskORM.task_id == task_id,
                    ConversationORM.user_id == user_id,
                    WorkspaceORM.owner_user_id == user_id,
                    ConversationORM.deleted_at.is_(None),
                )
            )
            if task is None:
                raise TaskNotFound("task not found")
            operation_id = await db.scalar(
                select(AgentOperationORM)
                .where(
                    AgentOperationORM.task_id == task_id,
                    AgentOperationORM.status == "approval_required",
                )
                .limit(1)
            )
            return {
                "task_id": task.task_id,
                "conversation_id": task.session_id,
                "trigger_message_id": task.trigger_message_id,
                "final_message_id": task.final_message_id,
                "status": task.status,
                "error_code": task.checkpoint.get("error_code"),
                "checkpoint_revision": task.checkpoint_revision,
                "active_operation_id": (
                    operation_id.operation_id if operation_id is not None else None
                ),
                "active_operation": (
                    {
                        "operation_id": operation_id.operation_id,
                        "task_id": operation_id.task_id,
                        "name": operation_id.name,
                        "arguments": operation_id.arguments,
                        "arguments_digest": operation_id.arguments_digest,
                        "decision_basis": operation_id.decision_basis,
                        "tool_call_id": operation_id.tool_call_id,
                        "assistant_message_id": operation_id.assistant_message_id,
                        "risk": operation_id.risk,
                        "status": operation_id.status,
                    }
                    if operation_id is not None
                    else None
                ),
                "started_at": task.started_at,
                "updated_at": task.updated_at,
            }

    async def list_tasks(
        self,
        *,
        conversation_id: str,
        user_id: str,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[dict[str, object], ...]:
        statement = (
            select(AgentTaskORM)
            .join(
                ConversationORM,
                ConversationORM.conversation_id == AgentTaskORM.session_id,
            )
            .join(
                WorkspaceORM,
                WorkspaceORM.workspace_id == ConversationORM.workspace_id,
            )
            .where(
                AgentTaskORM.session_id == conversation_id,
                ConversationORM.user_id == user_id,
                WorkspaceORM.owner_user_id == user_id,
                ConversationORM.deleted_at.is_(None),
            )
            .order_by(AgentTaskORM.updated_at.desc(), AgentTaskORM.task_id)
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            statement = statement.where(AgentTaskORM.status == status)
        async with AsyncSessionLocal() as db:
            tasks = (await db.scalars(statement)).all()
            operation_ids = (
                await db.execute(
                    select(AgentOperationORM.task_id, AgentOperationORM.operation_id)
                    .where(
                        AgentOperationORM.task_id.in_(
                            tuple(task.task_id for task in tasks)
                        ),
                        AgentOperationORM.status == "approval_required",
                    )
                )
            ).all()
        active_operations = {task_id: operation_id for task_id, operation_id in operation_ids}
        return tuple(
            self._task_payload(task, active_operations.get(task.task_id))
            for task in tasks
        )

    async def stop_task(
        self, *, conversation_id: str, task_id: str, user_id: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            conversation = await db.scalar(
                select(ConversationORM)
                .join(
                    WorkspaceORM,
                    WorkspaceORM.workspace_id == ConversationORM.workspace_id,
                )
                .where(
                    ConversationORM.conversation_id == conversation_id,
                    ConversationORM.user_id == user_id,
                    WorkspaceORM.owner_user_id == user_id,
                    ConversationORM.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if conversation is None:
                raise TaskNotFound("task not found")
            task = await db.scalar(
                select(AgentTaskORM)
                .where(
                    AgentTaskORM.session_id == conversation_id,
                    AgentTaskORM.task_id == task_id,
                    AgentTaskORM.status.in_(
                        ("accepted", "running", "approval_required")
                    ),
                )
                .with_for_update()
            )
            if task is None:
                raise TaskNotFound("task not found")
            task.status = "interrupted"
            task.checkpoint_revision += 1
            task.updated_at = _now()

    async def decide_operation(
        self,
        *,
        conversation_id: str,
        task_id: str,
        operation_id: str,
        user_id: str,
        decision: str,
        arguments_digest: str,
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            conversation = await db.scalar(
                select(ConversationORM)
                .join(
                    WorkspaceORM,
                    WorkspaceORM.workspace_id == ConversationORM.workspace_id,
                )
                .where(
                    ConversationORM.conversation_id == conversation_id,
                    ConversationORM.user_id == user_id,
                    WorkspaceORM.owner_user_id == user_id,
                    ConversationORM.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if conversation is None:
                raise TaskNotFound("task not found")
            task = await db.scalar(
                select(AgentTaskORM)
                .where(
                    AgentTaskORM.task_id == task_id,
                    AgentTaskORM.session_id == conversation_id,
                )
                .with_for_update()
            )
            if task is None:
                raise TaskNotFound("task not found")
            operation = await db.scalar(
                select(AgentOperationORM)
                .where(
                    AgentOperationORM.operation_id == operation_id,
                    AgentOperationORM.task_id == task_id,
                    AgentOperationORM.status == "approval_required",
                )
                .with_for_update()
            )
            if operation is None:
                raise TaskNotFound("operation not found")
            if operation.arguments_digest != arguments_digest:
                raise OperationDecisionConflict("operation arguments digest mismatch")
            if decision not in {"approved", "rejected"}:
                raise OperationDecisionConflict("invalid operation decision")
            now = _now()
            operation.status = decision
            operation.decision_user_id = user_id
            operation.decision_arguments_digest = arguments_digest
            operation.decided_at = now
            operation.updated_at = now
            checkpoint = dict(task.checkpoint or {})
            checkpoint_operations = list(checkpoint.get("operations", []))
            updated_operation = {
                "operation_id": operation.operation_id,
                "task_id": operation.task_id,
                "tool_call_id": operation.tool_call_id,
                "name": operation.name,
                "assistant_message_id": operation.assistant_message_id,
                "arguments": operation.arguments,
                "arguments_digest": operation.arguments_digest,
                "decision_basis": operation.decision_basis,
                "status": decision,
                "decision_arguments_digest": arguments_digest,
                "result": operation.result,
                "error_code": operation.error_code,
                "error_message": operation.error_message,
            }
            for index, item in enumerate(checkpoint_operations):
                if item.get("operation_id") == operation.operation_id:
                    checkpoint_operations[index] = {
                        **item,
                        **updated_operation,
                    }
                    break
            else:
                checkpoint_operations.append(updated_operation)
            checkpoint["operations"] = checkpoint_operations
            task.checkpoint = checkpoint
            task.checkpoint_revision += 1
            task.status = "running"
            task.updated_at = now

    async def resume_task(
        self,
        *,
        conversation_id: str,
        task_id: str,
        user_id: str,
        expected_checkpoint_revision: int,
    ) -> dict[str, object]:
        async with AsyncSessionLocal() as db, db.begin():
            conversation = await db.scalar(
                select(ConversationORM)
                .join(
                    WorkspaceORM,
                    WorkspaceORM.workspace_id == ConversationORM.workspace_id,
                )
                .where(
                    ConversationORM.conversation_id == conversation_id,
                    ConversationORM.user_id == user_id,
                    WorkspaceORM.owner_user_id == user_id,
                    ConversationORM.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if conversation is None:
                raise TaskNotFound("task not found")
            task = await db.scalar(
                select(AgentTaskORM)
                .where(
                    AgentTaskORM.session_id == conversation_id,
                    AgentTaskORM.task_id == task_id,
                )
                .with_for_update()
            )
            if task is None:
                raise TaskNotFound("task not found")
            if task.checkpoint_revision != expected_checkpoint_revision:
                raise CheckpointConflict("checkpoint revision is stale")
            if task.status not in {"interrupted", "accepted", "running"}:
                raise TaskResumeConflict("task is not resumable")
            task.status = "running"
            task.checkpoint_revision += 1
            task.updated_at = _now()
            return self._task_payload(task)

    @staticmethod
    def _task_payload(
        task: AgentTaskORM, active_operation_id: str | None = None
    ) -> dict[str, object]:
        return {
            "task_id": task.task_id,
            "conversation_id": task.session_id,
            "trigger_message_id": task.trigger_message_id,
            "final_message_id": task.final_message_id,
            "status": task.status,
            "error_code": task.checkpoint.get("error_code"),
            "checkpoint_revision": task.checkpoint_revision,
            "active_operation_id": active_operation_id,
            "active_operation": None,
            "started_at": task.started_at,
            "updated_at": task.updated_at,
        }

    async def write_checkpoint_bundle(
        self,
        *,
        task_id: str,
        expected_revision: int,
        message: dict[str, Any] | None,
        operation: dict[str, Any] | None,
        step: dict[str, Any],
        checkpoint: dict[str, Any],
        status: str,
    ) -> int:
        async with AsyncSessionLocal() as db, db.begin():
            task = await self._lock_task_for_checkpoint(db, task_id)
            self._require_revision(task, expected_revision)
            if message is not None:
                await self._insert_message(db, task, message)
                await db.flush()
            if operation is not None:
                await self._upsert_operation(db, task_id, operation)
            await self._upsert_step(db, task_id, step)

            revision = expected_revision + 1
            task.checkpoint_revision = revision
            task.checkpoint = checkpoint
            task.status = status
            task.updated_at = _now()
            if status in {"completed", "failed", "cancelled"}:
                task.finished_at = task.finished_at or _now()
            if message is not None:
                task.checkpoint_message_id = message["message_id"]
                if status == "completed":
                    task.final_message_id = message["message_id"]
            return revision

    async def _locked_task(self, db: AsyncSession, task_id: str) -> AgentTaskORM:
        task = await db.scalar(
            select(AgentTaskORM)
            .where(AgentTaskORM.task_id == task_id)
            .with_for_update()
        )
        if task is None:
            raise TaskNotFound("task not found")
        return task

    async def _lock_task_for_checkpoint(
        self, db: AsyncSession, task_id: str
    ) -> AgentTaskORM:
        conversation_id = await db.scalar(
            select(AgentTaskORM.session_id).where(AgentTaskORM.task_id == task_id)
        )
        if conversation_id is None:
            raise TaskNotFound("task not found")
        conversation = await db.scalar(
            select(ConversationORM)
            .where(ConversationORM.conversation_id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise TaskNotFound("task not found")
        if conversation.deleted_at is not None:
            raise CheckpointConflict("conversation was deleted")
        task = await self._locked_task(db, task_id)
        if task.status == "cancelled":
            raise CheckpointConflict("conversation was deleted")
        return task

    @staticmethod
    def _require_revision(task: AgentTaskORM, expected_revision: int) -> None:
        if task.checkpoint_revision != expected_revision:
            raise CheckpointConflict("checkpoint revision is stale")

    async def _insert_message(
        self, db: AsyncSession, task: AgentTaskORM, message: dict[str, Any]
    ) -> None:
        conversation_id = message.get("conversation_id", task.session_id)
        if conversation_id != task.session_id:
            raise ValueError("message conversation does not match Task")
        db.add(
            MessageORM(
                message_id=message["message_id"],
                conversation_id=conversation_id,
                parent_message_id=message.get("parent_message_id"),
                role=message["role"],
                content=message.get("content", ""),
                source_contexts=message.get("source_contexts", []),
                citations=message.get("citations", []),
                operation_id=message.get("operation_id"),
                produced_by_task_id=task.task_id,
                created_at=message.get("created_at", _now()),
            )
        )

    async def _upsert_operation(
        self, db: AsyncSession, task_id: str, operation: dict[str, Any]
    ) -> None:
        if operation.get("task_id", task_id) != task_id:
            raise ValueError("operation belongs to another Task")
        operation_id = operation["operation_id"]
        row = await db.scalar(
            select(AgentOperationORM)
            .where(AgentOperationORM.operation_id == operation_id)
            .with_for_update()
        )
        now = _now()
        if row is None:
            db.add(
                AgentOperationORM(
                    operation_id=operation_id,
                    task_id=task_id,
                    tool_call_id=operation.get("tool_call_id"),
                    assistant_message_id=operation.get("assistant_message_id"),
                    name=operation["name"],
                    arguments=operation.get("arguments", {}),
                    arguments_digest=operation["arguments_digest"],
                    decision_basis=operation.get("decision_basis", "registry"),
                    risk=operation.get("risk", "write" if operation["status"] == "approval_required" else "read"),
                    status=operation["status"],
                    idempotency_key=operation.get("idempotency_key"),
                    result=operation.get("result"),
                    error_code=operation.get("error_code"),
                    error_message=operation.get("error_message"),
                    decision_user_id=operation.get("decision_user_id"),
                    decision_arguments_digest=operation.get(
                        "decision_arguments_digest"
                    ),
                    decided_at=operation.get("decided_at"),
                    started_at=operation.get("started_at"),
                    finished_at=operation.get("finished_at"),
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        if row.task_id != task_id:
            raise ValueError("operation belongs to another Task")
        if row.arguments_digest != operation["arguments_digest"]:
            raise ValueError("operation arguments digest mismatch")
        row.status = operation["status"]
        row.decision_basis = operation.get("decision_basis", row.decision_basis)
        row.result = operation.get("result")
        row.error_code = operation.get("error_code")
        row.error_message = operation.get("error_message")
        row.updated_at = now

    async def _upsert_step(
        self, db: AsyncSession, task_id: str, step: dict[str, Any]
    ) -> None:
        sequence = step["sequence"]
        row = await db.scalar(
            select(AgentTaskStepORM)
            .where(
                AgentTaskStepORM.task_id == task_id,
                AgentTaskStepORM.sequence == sequence,
            )
            .with_for_update()
        )
        if row is None:
            db.add(
                AgentTaskStepORM(
                    step_id=step["step_id"],
                    task_id=task_id,
                    sequence=sequence,
                    name=step["name"],
                    status=step["status"],
                    checkpoint=step["checkpoint"],
                    started_at=step.get("started_at"),
                    finished_at=step.get("finished_at"),
                )
            )
            return
        if row.step_id != step["step_id"]:
            raise ValueError("checkpoint sequence belongs to another Step")
        row.status = step["status"]
        row.checkpoint = step["checkpoint"]
        row.finished_at = step.get("finished_at")


__all__ = [
    "CheckpointConflict",
    "TaskBusyError",
    "TaskExecutionContext",
    "TaskNotFound",
    "TaskRepository",
]
