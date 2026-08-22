"""PostgreSQL persistence for Objective-scoped experiment plans."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.goal import ExperimentPlanRecord
from infra.persistence.postgres.models.chat import ChatMessageRow, ChatSessionRow
from infra.persistence.postgres.models.objective_workspace import (
    ObjectiveExperimentPlan,
)


class PostgresExperimentPlanRepository:
    backend_name = "postgresql"

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    async def upsert_plan(
        self, plan: ExperimentPlanRecord
    ) -> ExperimentPlanRecord:
        async with self.session_factory.begin() as session:
            if plan.source_message_id is not None:
                message = await session.get(
                    ChatMessageRow, plan.source_message_id
                )
                chat = (
                    await session.get(ChatSessionRow, message.session_id)
                    if message is not None
                    else None
                )
                if (
                    message is None
                    or chat is None
                    or chat.collection_id != plan.collection_id
                ):
                    raise ValueError(
                        "historical source message must belong to the plan collection"
                    )
            row = await session.get(ObjectiveExperimentPlan, plan.plan_id)
            if row is not None and (
                row.collection_id != plan.collection_id
                or row.objective_id != plan.objective_id
            ):
                raise ValueError("experiment plan identity cannot be reassigned")
            if row is None:
                row = ObjectiveExperimentPlan(
                    plan_id=plan.plan_id,
                    collection_id=plan.collection_id,
                    objective_id=plan.objective_id,
                    title=plan.title,
                    content=plan.content,
                    status=plan.status,
                    source_message_id=plan.source_message_id,
                    source_links=[dict(item) for item in plan.source_links],
                    metadata_json=dict(plan.metadata),
                    created_by=plan.created_by,
                    created_at=_datetime(plan.created_at),
                    updated_at=_datetime(plan.updated_at),
                )
                session.add(row)
            row.title = plan.title
            row.content = plan.content
            row.status = plan.status
            row.source_message_id = plan.source_message_id
            row.source_links = [dict(item) for item in plan.source_links]
            row.metadata_json = dict(plan.metadata)
            row.created_by = plan.created_by
            row.updated_at = _datetime(plan.updated_at)
            await session.flush()
            return _plan_record(row)

    async def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(ObjectiveExperimentPlan).where(
                    ObjectiveExperimentPlan.plan_id == plan_id,
                    ObjectiveExperimentPlan.collection_id == collection_id,
                    ObjectiveExperimentPlan.objective_id == objective_id,
                )
            )
            return _plan_record(row) if row is not None else None

    async def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(ObjectiveExperimentPlan)
                .where(
                    ObjectiveExperimentPlan.collection_id == collection_id,
                    ObjectiveExperimentPlan.objective_id == objective_id,
                )
                .order_by(
                    ObjectiveExperimentPlan.updated_at.desc(),
                    ObjectiveExperimentPlan.created_at.desc(),
                    ObjectiveExperimentPlan.plan_id,
                )
            )
            return tuple(_plan_record(row) for row in rows)


def _plan_record(row: ObjectiveExperimentPlan) -> ExperimentPlanRecord:
    return ExperimentPlanRecord.from_mapping(
        {
            "plan_id": row.plan_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "title": row.title,
            "content": row.content,
            "status": row.status,
            "source_message_id": row.source_message_id,
            "source_links": [dict(item) for item in row.source_links],
            "metadata": dict(row.metadata_json),
            "created_by": row.created_by,
            "created_at": _isoformat(row.created_at),
            "updated_at": _isoformat(row.updated_at),
        }
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


__all__ = ["PostgresExperimentPlanRepository"]
