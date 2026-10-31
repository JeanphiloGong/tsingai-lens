"""PostgreSQL repository for experiment plan."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.goal import (
    ExperimentPlanRecord,
)
from exceptions import ResourceConflictException
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import ChatMessageRow, ChatSessionRow
from infra.persistence.postgres.models.objective_workspace import (
    ObjectiveExperimentPlan,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class ExperimentPlanRepository:
    backend_name = "postgresql"

    async def upsert_plan(self, plan: ExperimentPlanRecord) -> ExperimentPlanRecord:
        if plan.parent_plan_id is not None:
            raise ValueError("use append_plan_revision for a successor revision")
        async with AsyncSessionLocal() as db, db.begin():
            await _validate_source_message(db, plan)
            row = await db.get(ObjectiveExperimentPlan, plan.plan_id)
            if row is not None:
                existing = ExperimentPlanRecord(
                    plan_id=row.plan_id,
                    collection_id=row.collection_id,
                    objective_id=row.objective_id,
                    title=row.title,
                    content=row.content,
                    status=row.status,
                    source_message_id=row.source_message_id,
                    source_links=tuple(row.source_links),
                    metadata=row.metadata_json,
                    plan_version=row.plan_version,
                    parent_plan_id=row.parent_plan_id,
                    structured_plan=row.structured_plan,
                    created_by=row.created_by,
                    updated_by=row.updated_by,
                    created_at=_isoformat(row.created_at),
                    updated_at=_isoformat(row.updated_at),
                )
                if existing == plan:
                    return existing
                raise ResourceConflictException(
                    "experiment plan revisions are immutable",
                    data={
                        "code": "experiment_plan_revision_immutable",
                        "plan_id": plan.plan_id,
                        "plan_version": plan.plan_version,
                    },
                )
            row = ObjectiveExperimentPlan(
                plan_id=plan.plan_id,
                collection_id=plan.collection_id,
                objective_id=plan.objective_id,
                title=plan.title,
                content=plan.content,
                status=plan.status,
                source_message_id=plan.source_message_id,
                source_links=list(plan.source_links),
                metadata_json=plan.metadata,
                plan_version=plan.plan_version,
                parent_plan_id=plan.parent_plan_id,
                structured_plan=plan.structured_plan,
                created_by=plan.created_by,
                updated_by=plan.updated_by,
                created_at=_datetime(plan.created_at),
                updated_at=_datetime(plan.updated_at),
            )
            db.add(row)
            await db.flush()
            return ExperimentPlanRecord(
                plan_id=row.plan_id,
                collection_id=row.collection_id,
                objective_id=row.objective_id,
                title=row.title,
                content=row.content,
                status=row.status,
                source_message_id=row.source_message_id,
                source_links=tuple(row.source_links),
                metadata=row.metadata_json,
                plan_version=row.plan_version,
                parent_plan_id=row.parent_plan_id,
                structured_plan=row.structured_plan,
                created_by=row.created_by,
                updated_by=row.updated_by,
                created_at=_isoformat(row.created_at),
                updated_at=_isoformat(row.updated_at),
            )

    async def append_plan_revision(
        self, plan: ExperimentPlanRecord
    ) -> ExperimentPlanRecord:
        parent_plan_id = plan.parent_plan_id
        if parent_plan_id is None:
            raise ValueError("successor revision requires parent_plan_id")
        async with AsyncSessionLocal() as db, db.begin():
            parent_row = await db.scalar(
                select(ObjectiveExperimentPlan)
                .where(ObjectiveExperimentPlan.plan_id == parent_plan_id)
                .with_for_update()
            )
            if parent_row is None:
                raise ValueError("experiment plan parent revision was not found")
            _validate_successor(parent_row, plan)
            if await db.get(ObjectiveExperimentPlan, plan.plan_id) is not None:
                raise ResourceConflictException(
                    "experiment plan revision identity already exists",
                    data={
                        "code": "experiment_plan_revision_identity_conflict",
                        "plan_id": plan.plan_id,
                        "plan_version": plan.plan_version,
                        "parent_plan_id": parent_plan_id,
                    },
                )
            existing_child = await db.scalar(
                select(ObjectiveExperimentPlan.plan_id).where(
                    ObjectiveExperimentPlan.parent_plan_id == parent_row.plan_id
                )
            )
            if existing_child is not None:
                raise ResourceConflictException(
                    "experiment plan revision has already been superseded",
                    data={
                        "code": "experiment_plan_revision_superseded",
                        "plan_id": plan.plan_id,
                        "parent_plan_id": parent_plan_id,
                    },
                )
            await _validate_source_message(db, plan)
            row = ObjectiveExperimentPlan(
                plan_id=plan.plan_id,
                collection_id=plan.collection_id,
                objective_id=plan.objective_id,
                title=plan.title,
                content=plan.content,
                status=plan.status,
                source_message_id=plan.source_message_id,
                source_links=list(plan.source_links),
                metadata_json=plan.metadata,
                plan_version=plan.plan_version,
                parent_plan_id=plan.parent_plan_id,
                structured_plan=plan.structured_plan,
                created_by=plan.created_by,
                updated_by=plan.updated_by,
                created_at=_datetime(plan.created_at),
                updated_at=_datetime(plan.updated_at),
            )
            db.add(row)
            try:
                await db.flush()
            except IntegrityError as exc:
                if _constraint_name(exc) == (
                    "uq_objective_experiment_plans_parent_plan_id"
                ):
                    raise ResourceConflictException(
                        "experiment plan revision has already been superseded",
                        data={
                            "code": "experiment_plan_revision_superseded",
                            "plan_id": plan.plan_id,
                            "parent_plan_id": parent_plan_id,
                        },
                    ) from exc
                raise
            return ExperimentPlanRecord(
                plan_id=row.plan_id,
                collection_id=row.collection_id,
                objective_id=row.objective_id,
                title=row.title,
                content=row.content,
                status=row.status,
                source_message_id=row.source_message_id,
                source_links=tuple(row.source_links),
                metadata=row.metadata_json,
                plan_version=row.plan_version,
                parent_plan_id=row.parent_plan_id,
                structured_plan=row.structured_plan,
                created_by=row.created_by,
                updated_by=row.updated_by,
                created_at=_isoformat(row.created_at),
                updated_at=_isoformat(row.updated_at),
            )

    async def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ObjectiveExperimentPlan).where(
                    ObjectiveExperimentPlan.plan_id == plan_id,
                    ObjectiveExperimentPlan.collection_id == collection_id,
                    ObjectiveExperimentPlan.objective_id == objective_id,
                )
            )
            if row is None:
                return None
            return ExperimentPlanRecord(
                plan_id=row.plan_id,
                collection_id=row.collection_id,
                objective_id=row.objective_id,
                title=row.title,
                content=row.content,
                status=row.status,
                source_message_id=row.source_message_id,
                source_links=tuple(row.source_links),
                metadata=row.metadata_json,
                plan_version=row.plan_version,
                parent_plan_id=row.parent_plan_id,
                structured_plan=row.structured_plan,
                created_by=row.created_by,
                updated_by=row.updated_by,
                created_at=_isoformat(row.created_at),
                updated_at=_isoformat(row.updated_at),
            )

    async def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
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
            records = tuple(
                ExperimentPlanRecord(
                    plan_id=row.plan_id,
                    collection_id=row.collection_id,
                    objective_id=row.objective_id,
                    title=row.title,
                    content=row.content,
                    status=row.status,
                    source_message_id=row.source_message_id,
                    source_links=tuple(row.source_links),
                    metadata=row.metadata_json,
                    plan_version=row.plan_version,
                    parent_plan_id=row.parent_plan_id,
                    structured_plan=row.structured_plan,
                    created_by=row.created_by,
                    updated_by=row.updated_by,
                    created_at=_isoformat(row.created_at),
                    updated_at=_isoformat(row.updated_at),
                )
                for row in rows
            )
            superseded_ids = {
                record.parent_plan_id
                for record in records
                if record.parent_plan_id is not None
            }
            return tuple(
                record for record in records if record.plan_id not in superseded_ids
            )


async def _validate_source_message(
    db: AsyncSession,
    plan: ExperimentPlanRecord,
) -> None:
    if plan.source_message_id is None:
        return
    message = await db.get(ChatMessageRow, plan.source_message_id)
    chat = (
        await db.get(ChatSessionRow, message.session_id)
        if message is not None
        else None
    )
    if message is None or chat is None or chat.collection_id != plan.collection_id:
        raise ValueError("historical source message must belong to the plan collection")


def _validate_successor(
    parent: ObjectiveExperimentPlan,
    successor: ExperimentPlanRecord,
) -> None:
    if (
        successor.parent_plan_id != parent.plan_id
        or successor.collection_id != parent.collection_id
        or successor.objective_id != parent.objective_id
        or successor.plan_version != parent.plan_version + 1
        or successor.created_by != parent.created_by
        or successor.created_at != _isoformat(parent.created_at)
    ):
        raise ValueError("experiment plan revision does not continue its parent")


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return str(value) if value else None


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


__all__ = ["ExperimentPlanRepository"]


ExperimentPlanRepo = ExperimentPlanRepository()
