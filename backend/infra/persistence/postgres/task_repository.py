"""PostgreSQL persistence for document- and collection-scoped tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.source import TaskRecord, TaskStageRecord
from infra.persistence.postgres.models.task import Task, TaskStage
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import Document


class PostgresTaskRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def add_task(self, record: TaskRecord) -> TaskRecord:
        async with self.session_factory.begin() as session:
            session.add(_task_row(record))
        return record

    async def get_or_create_collection_task(
        self,
        record: TaskRecord,
    ) -> tuple[TaskRecord, bool]:
        if record.document_id is not None:
            raise ValueError("collection task must not identify one document")
        async with self.session_factory.begin() as session:
            collection = await session.scalar(
                select(Collection)
                .where(Collection.collection_id == record.collection_id)
                .with_for_update()
            )
            if collection is None:
                raise FileNotFoundError(
                    f"collection not found: {record.collection_id}"
                )
            active = await session.scalar(
                select(Task)
                .where(
                    Task.collection_id == record.collection_id,
                    Task.document_id.is_(None),
                    Task.task_type == record.task_type,
                    Task.status.in_(("queued", "running")),
                )
                .order_by(Task.updated_at.desc(), Task.task_id.desc())
                .limit(1)
            )
            if active is not None:
                return _task_record(active), False
            session.add(_task_row(record))
            return record, True

    async def get_or_create_document_task(
        self,
        record: TaskRecord,
    ) -> tuple[TaskRecord, bool]:
        if record.document_id is None or record.input_fingerprint is None:
            raise ValueError("document task requires document and input fingerprint")
        async with self.session_factory.begin() as session:
            document = await session.scalar(
                select(Document)
                .where(
                    Document.collection_id == record.collection_id,
                    Document.document_id == record.document_id,
                )
                .with_for_update()
            )
            if document is None:
                raise FileNotFoundError(
                    f"document not found: {record.collection_id}/{record.document_id}"
                )
            active = await session.scalar(
                select(Task)
                .where(
                    Task.document_id == record.document_id,
                    Task.task_type == record.task_type,
                    Task.status.in_(("queued", "running")),
                )
                .order_by(Task.updated_at.desc(), Task.task_id.desc())
                .limit(1)
            )
            if active is not None:
                return _task_record(active), False
            completed = await session.scalar(
                select(Task)
                .where(
                    Task.document_id == record.document_id,
                    Task.task_type == record.task_type,
                    Task.input_fingerprint == record.input_fingerprint,
                    Task.status.in_(("completed", "partial_success")),
                )
                .order_by(Task.updated_at.desc(), Task.task_id.desc())
                .limit(1)
            )
            if completed is not None:
                return _task_record(completed), False
            session.add(_task_row(record))
            return record, True

    async def read_task(self, task_id: str) -> TaskRecord | None:
        async with self.session_factory() as session:
            row = await session.get(Task, task_id)
            return _task_record(row) if row is not None else None

    async def list_tasks(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[TaskRecord, ...]:
        statement = select(Task)
        if collection_id is not None:
            statement = statement.where(Task.collection_id == collection_id)
        if status is not None:
            statement = statement.where(Task.status == status)
        statement = statement.order_by(Task.updated_at.desc(), Task.task_id.desc())
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_task_record(row) for row in rows)

    async def update_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[TaskStageRecord, ...] | None = None,
    ) -> bool:
        async with self.session_factory.begin() as session:
            row = await session.get(Task, record.task_id)
            if row is None:
                return False
            _update_task_row(row, record)
            if stages is not None:
                for stage in stages:
                    if stage.task_id != record.task_id:
                        raise ValueError(f"stage task mismatch: {stage.stage_id}")
                    stored = await session.get(TaskStage, stage.stage_id)
                    if stored is None:
                        session.add(_stage_row(stage))
                    else:
                        _update_stage_row(stored, stage)
            return True

    async def list_stages(self, task_id: str) -> tuple[TaskStageRecord, ...]:
        statement = (
            select(TaskStage)
            .where(TaskStage.task_id == task_id)
            .order_by(TaskStage.stage_order, TaskStage.stage_id)
        )
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_stage_record(row) for row in rows)


def _task_row(record: TaskRecord) -> Task:
    return Task(
        task_id=record.task_id,
        collection_id=record.collection_id,
        document_id=record.document_id,
        task_type=record.task_type,
        mode=record.mode,
        input_fingerprint=record.input_fingerprint,
        status=record.status,
        current_stage=record.current_stage,
        progress_percent=record.progress_percent,
        progress_detail=(
            dict(record.progress_detail) if record.progress_detail is not None else None
        ),
        errors=list(record.errors),
        warnings=list(record.warnings),
        details=dict(record.details),
        created_at=_datetime(record.created_at),
        updated_at=_datetime(record.updated_at),
        started_at=_optional_datetime(record.started_at),
        finished_at=_optional_datetime(record.finished_at),
    )


def _update_task_row(row: Task, record: TaskRecord) -> None:
    row.collection_id = record.collection_id
    row.document_id = record.document_id
    row.task_type = record.task_type
    row.mode = record.mode
    row.input_fingerprint = record.input_fingerprint
    row.status = record.status
    row.current_stage = record.current_stage
    row.progress_percent = record.progress_percent
    row.progress_detail = (
        dict(record.progress_detail) if record.progress_detail is not None else None
    )
    row.errors = list(record.errors)
    row.warnings = list(record.warnings)
    row.details = dict(record.details)
    row.updated_at = _datetime(record.updated_at)
    row.started_at = _optional_datetime(record.started_at)
    row.finished_at = _optional_datetime(record.finished_at)


def _task_record(row: Task) -> TaskRecord:
    return TaskRecord(
        task_id=row.task_id,
        collection_id=row.collection_id,
        document_id=row.document_id,
        task_type=row.task_type,
        mode=row.mode,
        input_fingerprint=row.input_fingerprint,
        status=row.status,
        current_stage=row.current_stage,
        progress_percent=row.progress_percent,
        progress_detail=(
            dict(row.progress_detail) if row.progress_detail is not None else None
        ),
        errors=tuple(row.errors or ()),
        warnings=tuple(row.warnings or ()),
        details=dict(row.details or {}),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        started_at=_optional_iso(row.started_at),
        finished_at=_optional_iso(row.finished_at),
    )


def _stage_row(record: TaskStageRecord) -> TaskStage:
    node = record.node
    return TaskStage(
        stage_id=record.stage_id,
        task_id=record.task_id,
        stage_kind=node.name,
        stage_order=record.stage_order,
        status=node.status.value,
        started_at=_optional_datetime(node.started_at),
        finished_at=_optional_datetime(node.finished_at),
        errors=list(node.errors),
        warnings=list(node.warnings),
        dependencies=list(node.dependencies),
        stats=node.stats.to_record(),
        output_summary=dict(node.output_summary),
    )


def _update_stage_row(row: TaskStage, record: TaskStageRecord) -> None:
    node = record.node
    row.stage_order = record.stage_order
    row.status = node.status.value
    row.started_at = _optional_datetime(node.started_at)
    row.finished_at = _optional_datetime(node.finished_at)
    row.errors = list(node.errors)
    row.warnings = list(node.warnings)
    row.dependencies = list(node.dependencies)
    row.stats = node.stats.to_record()
    row.output_summary = dict(node.output_summary)


def _stage_record(row: TaskStage) -> TaskStageRecord:
    from domain.pipeline import PipelineNodeRun

    return TaskStageRecord(
        stage_id=row.stage_id,
        task_id=row.task_id,
        stage_order=row.stage_order,
        node=PipelineNodeRun.from_record(
            {
                "name": row.stage_kind,
                "status": row.status,
                "dependencies": list(row.dependencies or ()),
                "errors": list(row.errors or ()),
                "warnings": list(row.warnings or ()),
                "stats": dict(row.stats or {}),
                "output_summary": dict(row.output_summary or {}),
                "started_at": _optional_iso(row.started_at),
                "finished_at": _optional_iso(row.finished_at),
            }
        ),
    )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        parsed = datetime.fromisoformat(
            f"{text[:-1]}+00:00" if text.endswith("Z") else text
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_datetime(value: Any) -> datetime | None:
    return _datetime(value) if value is not None else None


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


def _optional_iso(value: datetime | None) -> str | None:
    return _iso(value) if value is not None else None


__all__ = ["PostgresTaskRepository"]
