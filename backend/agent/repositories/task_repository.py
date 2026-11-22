"""Persistence operations for Agent Task acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from infra.persistence.postgres.models.chat import AgentTaskORM
from sqlalchemy.ext.asyncio import AsyncSession


class TaskRepository:
    async def insert_accepted_task(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        conversation_id: str,
        trigger_message_id: str,
        request_digest: str,
    ) -> None:
        now = datetime.now(UTC)
        db.add(
            AgentTaskORM(
                task_id=task_id,
                session_id=conversation_id,
                trigger_kind="user_message",
                trigger_message_id=trigger_message_id,
                request_id=str(uuid4()),
                request_digest=request_digest,
                status="accepted",
                checkpoint_revision=0,
                checkpoint={},
                started_at=now,
                updated_at=now,
            )
        )


__all__ = ["TaskRepository"]
