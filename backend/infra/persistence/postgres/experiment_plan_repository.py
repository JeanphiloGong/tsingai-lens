"""PostgreSQL persistence for Objective-scoped experiment plans."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.goal import (
    ExperimentPlanRecord,
    ExperimentPlanRevisionConflictError,
)
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
        if plan.parent_plan_id is not None:
            raise ValueError("use append_plan_revision for a successor revision")
        async with self.session_factory.begin() as session:
            await _validate_source_message(session, plan)
            row = await session.get(ObjectiveExperimentPlan, plan.plan_id)
            if row is not None:
                existing = _plan_record(row)
                if existing == plan:
                    return existing
                raise ExperimentPlanRevisionConflictError(
                    "experiment plan revisions are immutable"
                )
            row = _new_plan_row(plan)
            session.add(row)
            await session.flush()
            return _plan_record(row)

    async def append_plan_revision(
        self, plan: ExperimentPlanRecord
    ) -> ExperimentPlanRecord:
        parent_plan_id = plan.parent_plan_id
        if parent_plan_id is None:
            raise ValueError("successor revision requires parent_plan_id")
        async with self.session_factory.begin() as session:
            parent_row = await session.scalar(
                select(ObjectiveExperimentPlan)
                .where(ObjectiveExperimentPlan.plan_id == parent_plan_id)
                .with_for_update()
            )
            if parent_row is None:
                raise ValueError("experiment plan parent revision was not found")
            parent = _plan_record(parent_row)
            _validate_successor(parent, plan)
            if await session.get(ObjectiveExperimentPlan, plan.plan_id) is not None:
                raise ExperimentPlanRevisionConflictError(
                    "experiment plan revision identity already exists"
                )
            existing_child = await session.scalar(
                select(ObjectiveExperimentPlan.plan_id).where(
                    ObjectiveExperimentPlan.parent_plan_id == parent.plan_id
                )
            )
            if existing_child is not None:
                raise ExperimentPlanRevisionConflictError(
                    "experiment plan revision has already been superseded"
                )
            await _validate_source_message(session, plan)
            row = _new_plan_row(plan)
            session.add(row)
            try:
                await session.flush()
            except IntegrityError as exc:
                if _constraint_name(exc) == (
                    "uq_objective_experiment_plans_parent_plan_id"
                ):
                    raise ExperimentPlanRevisionConflictError(
                        "experiment plan revision has already been superseded"
                    ) from exc
                raise
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
            records = tuple(_plan_record(row) for row in rows)
            superseded_ids = {
                record.parent_plan_id
                for record in records
                if record.parent_plan_id is not None
            }
            return tuple(
                record for record in records if record.plan_id not in superseded_ids
            )


def _new_plan_row(plan: ExperimentPlanRecord) -> ObjectiveExperimentPlan:
    return ObjectiveExperimentPlan(
        plan_id=plan.plan_id,
        collection_id=plan.collection_id,
        objective_id=plan.objective_id,
        title=plan.title,
        content=plan.content,
        status=plan.status,
        source_message_id=plan.source_message_id,
        source_links=[dict(item) for item in plan.source_links],
        metadata_json=dict(plan.metadata),
        plan_version=plan.plan_version,
        parent_plan_id=plan.parent_plan_id,
        structured_plan=(
            dict(plan.structured_plan) if plan.structured_plan is not None else None
        ),
        created_by=plan.created_by,
        updated_by=plan.updated_by,
        created_at=_datetime(plan.created_at),
        updated_at=_datetime(plan.updated_at),
    )


async def _validate_source_message(
    session: AsyncSession,
    plan: ExperimentPlanRecord,
) -> None:
    if plan.source_message_id is None:
        return
    message = await session.get(ChatMessageRow, plan.source_message_id)
    chat = (
        await session.get(ChatSessionRow, message.session_id)
        if message is not None
        else None
    )
    if message is None or chat is None or chat.collection_id != plan.collection_id:
        raise ValueError(
            "historical source message must belong to the plan collection"
        )


def _validate_successor(
    parent: ExperimentPlanRecord,
    successor: ExperimentPlanRecord,
) -> None:
    if (
        successor.parent_plan_id != parent.plan_id
        or successor.collection_id != parent.collection_id
        or successor.objective_id != parent.objective_id
        or successor.plan_version != parent.plan_version + 1
        or successor.created_by != parent.created_by
        or successor.created_at != parent.created_at
    ):
        raise ValueError("experiment plan revision does not continue its parent")


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return str(value) if value else None


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
            "plan_version": row.plan_version,
            "parent_plan_id": row.parent_plan_id,
            "structured_plan": (
                dict(row.structured_plan) if row.structured_plan is not None else None
            ),
            "created_by": row.created_by,
            "updated_by": row.updated_by,
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
