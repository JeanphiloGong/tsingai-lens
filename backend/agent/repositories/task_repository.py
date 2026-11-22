"""Agent Task, Operation, Step, and checkpoint persistence."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import (
    AgentOperationORM,
    AgentTaskORM,
    AgentTaskStepORM,
)
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class TaskNotFound(FileNotFoundError):
    """The Task is missing or outside the authenticated Conversation."""


class CheckpointConflict(ValueError):
    """Execution attempted to save from an obsolete checkpoint revision."""


class TaskBusyError(RuntimeError):
    """Another execution currently owns the Task execution lock."""


@dataclass(frozen=True)
class TaskExecutionContext:
    task_id: str
    conversation_id: str
    trigger_message_id: str | None
    status: str
    checkpoint_revision: int
    checkpoint: dict[str, Any]


def _now() -> datetime:
    return datetime.now(UTC)


def _legacy_request_digest(task_id: str, conversation_id: str) -> str:
    """Fill pre-V2 storage columns without exposing them as Task identity."""

    return sha256(f"{conversation_id}:{task_id}".encode("utf-8")).hexdigest()


class TaskRepository:
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
        request_digest: str | None = None,
    ) -> None:
        now = _now()
        db.add(
            AgentTaskORM(
                task_id=task_id,
                session_id=conversation_id,
                trigger_kind="user_message",
                trigger_message_id=trigger_message_id,
                request_id=str(uuid4()),
                request_digest=request_digest
                or _legacy_request_digest(task_id, conversation_id),
                status="accepted",
                checkpoint_revision=0,
                checkpoint={},
                started_at=now,
                updated_at=now,
            )
        )

    async def load_for_execution(
        self, *, task_id: str, user_id: str
    ) -> TaskExecutionContext:
        async with AsyncSessionLocal() as db, db.begin():
            task = await db.scalar(
                select(AgentTaskORM)
                .join(
                    ConversationORM,
                    ConversationORM.conversation_id == AgentTaskORM.session_id,
                )
                .where(
                    AgentTaskORM.task_id == task_id,
                    ConversationORM.user_id == user_id,
                )
                .with_for_update()
            )
            if task is None:
                raise TaskNotFound("task not found")
            return TaskExecutionContext(
                task_id=task.task_id,
                conversation_id=task.session_id,
                trigger_message_id=task.trigger_message_id,
                status=task.status,
                checkpoint_revision=task.checkpoint_revision,
                checkpoint=dict(task.checkpoint),
            )

    async def save_checkpoint(
        self,
        *,
        task_id: str,
        expected_revision: int,
        checkpoint: dict[str, Any],
        status: str,
    ) -> int:
        async with AsyncSessionLocal() as db, db.begin():
            task = await self._locked_task(db, task_id)
            self._require_revision(task, expected_revision)
            revision = expected_revision + 1
            task.checkpoint_revision = revision
            task.checkpoint = checkpoint
            task.status = status
            task.updated_at = _now()
            return revision

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
                .where(
                    AgentTaskORM.session_id == conversation_id,
                    AgentTaskORM.task_id == task_id,
                    ConversationORM.user_id == user_id,
                )
            )
            if task is None:
                raise TaskNotFound("task not found")
            operation_id = await db.scalar(
                select(AgentOperationORM.operation_id)
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
                "checkpoint_revision": task.checkpoint_revision,
                "active_operation_id": operation_id,
            }

    async def stop_task(
        self, *, conversation_id: str, task_id: str, user_id: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            task = await db.scalar(
                select(AgentTaskORM)
                .join(
                    ConversationORM,
                    ConversationORM.conversation_id == AgentTaskORM.session_id,
                )
                .where(
                    AgentTaskORM.session_id == conversation_id,
                    AgentTaskORM.task_id == task_id,
                    ConversationORM.user_id == user_id,
                    AgentTaskORM.status.in_(
                        ("accepted", "running", "approval_required")
                    ),
                )
                .with_for_update()
            )
            if task is None:
                raise TaskNotFound("task not found")
            task.status = "interrupted"
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
            operation = await db.scalar(
                select(AgentOperationORM)
                .join(
                    AgentTaskORM,
                    AgentTaskORM.task_id == AgentOperationORM.task_id,
                )
                .join(
                    ConversationORM,
                    ConversationORM.conversation_id == AgentTaskORM.session_id,
                )
                .where(
                    AgentOperationORM.operation_id == operation_id,
                    AgentOperationORM.task_id == task_id,
                    AgentOperationORM.status == "approval_required",
                    AgentTaskORM.session_id == conversation_id,
                    ConversationORM.user_id == user_id,
                )
                .with_for_update()
            )
            if operation is None:
                raise TaskNotFound("operation not found")
            if operation.arguments_digest != arguments_digest:
                raise ValueError("operation arguments digest mismatch")
            if decision not in {"approved", "rejected"}:
                raise ValueError("invalid operation decision")
            now = _now()
            operation.status = decision
            operation.decision_user_id = user_id
            operation.decision_arguments_digest = arguments_digest
            operation.decided_at = now
            operation.updated_at = now

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
            task = await self._locked_task(db, task_id)
            self._require_revision(task, expected_revision)
            if message is not None:
                await self._insert_message(db, task, message)
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
        position = message.get("position")
        if position is None:
            position = await db.scalar(
                select(func.coalesce(func.max(MessageORM.position) + 1, 0)).where(
                    MessageORM.conversation_id == task.session_id
                )
            )
        db.add(
            MessageORM(
                message_id=message["message_id"],
                conversation_id=conversation_id,
                position=position,
                parent_message_id=message.get("parent_message_id"),
                role=message["role"],
                content=message.get("content", ""),
                source_contexts=message.get("source_contexts", []),
                tool_call_id=message.get("tool_call_id"),
                operation_id=message.get("operation_id"),
                tool_requests=message.get("tool_requests", []),
                tool_result=message.get("tool_result"),
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
                    risk=operation.get("risk", "read"),
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
