"""PostgreSQL persistence for task and collection-build lineage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from domain.source import (
    ArtifactVersionRecord,
    BuildStageRecord,
    CollectionBuildRecord,
    TaskRecord,
)
from infra.persistence.postgres.models.build import (
    ArtifactVersion,
    BuildStage,
    CollectionActiveBuild,
    CollectionBuild,
    Task,
)
from infra.persistence.postgres.models.collection import Collection


class PostgresBuildRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def add_task(
        self,
        record: TaskRecord,
        *,
        build_id: str,
    ) -> CollectionBuildRecord:
        with self.session_factory.begin() as session:
            collection = session.scalar(
                select(Collection)
                .where(Collection.collection_id == record.collection_id)
                .with_for_update()
            )
            current_number = session.scalar(
                select(func.max(CollectionBuild.build_number)).where(
                    CollectionBuild.collection_id == record.collection_id
                )
            )
            build_number = int(current_number or 0) + 1
            session.add(_task_row(record))
            session.flush()
            build = CollectionBuild(
                build_id=str(build_id),
                task_id=record.task_id,
                collection_id=record.collection_id,
                build_number=build_number,
                status="queued",
                created_at=_datetime(record.created_at),
                started_at=None,
                finished_at=None,
            )
            session.add(build)
            if collection is None:
                session.flush()
            result = _build_record(build)
        return result

    def read_task(self, task_id: str) -> TaskRecord | None:
        with self.session_factory() as session:
            row = session.get(Task, task_id)
            return _task_record(row) if row is not None else None

    def list_tasks(
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
        if offset > 0:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        with self.session_factory() as session:
            return tuple(_task_record(row) for row in session.scalars(statement))

    def update_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[BuildStageRecord, ...] | None = None,
    ) -> bool:
        with self.session_factory.begin() as session:
            task = session.get(Task, record.task_id)
            if task is None:
                return False
            _update_task_row(task, record)
            build = session.scalar(
                select(CollectionBuild).where(CollectionBuild.task_id == record.task_id)
            )
            if build is None:
                raise RuntimeError(f"build not found for task: {record.task_id}")
            if record.status == "running" and build.status == "queued":
                build.status = "building"
                build.started_at = _optional_datetime(record.started_at) or _datetime(
                    record.updated_at
                )
            if stages is not None:
                for stage_record in stages:
                    if stage_record.build_id != build.build_id:
                        raise ValueError(
                            f"stage build mismatch: {stage_record.stage_id}"
                        )
                    stage = session.get(BuildStage, stage_record.stage_id)
                    if stage is None:
                        session.add(_stage_row(stage_record))
                    else:
                        _update_stage_row(stage, stage_record)
            return True

    def read_build(self, task_id: str) -> CollectionBuildRecord | None:
        with self.session_factory() as session:
            build = session.scalar(
                select(CollectionBuild).where(CollectionBuild.task_id == task_id)
            )
            return _build_record(build) if build is not None else None

    def list_stages(self, task_id: str) -> tuple[BuildStageRecord, ...]:
        statement = (
            select(BuildStage)
            .join(CollectionBuild, CollectionBuild.build_id == BuildStage.build_id)
            .where(CollectionBuild.task_id == task_id)
            .order_by(BuildStage.stage_order, BuildStage.stage_id)
        )
        with self.session_factory() as session:
            return tuple(_stage_record(row) for row in session.scalars(statement))

    def add_artifact_versions(
        self,
        task_id: str,
        records: tuple[ArtifactVersionRecord, ...],
    ) -> None:
        with self.session_factory.begin() as session:
            build = session.scalar(
                select(CollectionBuild).where(CollectionBuild.task_id == task_id)
            )
            if build is None:
                raise FileNotFoundError(f"build not found for task: {task_id}")
            stage_ids = {record.build_stage_id for record in records}
            owned_stage_ids = set(
                session.scalars(
                    select(BuildStage.stage_id).where(
                        BuildStage.build_id == build.build_id,
                        BuildStage.stage_id.in_(stage_ids),
                    )
                )
            )
            if owned_stage_ids != stage_ids:
                raise ValueError(f"artifact stage does not belong to task: {task_id}")
            session.add_all(_artifact_row(record) for record in records)

    def list_artifact_versions(
        self,
        task_id: str,
    ) -> tuple[ArtifactVersionRecord, ...]:
        statement = (
            select(ArtifactVersion)
            .join(BuildStage, BuildStage.stage_id == ArtifactVersion.build_stage_id)
            .join(CollectionBuild, CollectionBuild.build_id == BuildStage.build_id)
            .where(CollectionBuild.task_id == task_id)
            .order_by(
                ArtifactVersion.artifact_kind, ArtifactVersion.artifact_version_id
            )
        )
        with self.session_factory() as session:
            return tuple(_artifact_record(row) for row in session.scalars(statement))

    def finish_build(
        self,
        record: TaskRecord,
        *,
        build_status: str,
        activate: bool,
    ) -> CollectionBuildRecord:
        with self.session_factory.begin() as session:
            task = session.get(Task, record.task_id)
            if task is None:
                raise FileNotFoundError(f"task not found: {record.task_id}")
            _update_task_row(task, record)
            build = session.scalar(
                select(CollectionBuild)
                .where(CollectionBuild.task_id == record.task_id)
                .with_for_update()
            )
            if build is None:
                raise RuntimeError(f"build not found for task: {record.task_id}")
            build.status = str(build_status)
            build.started_at = build.started_at or _optional_datetime(record.started_at)
            build.finished_at = _optional_datetime(record.finished_at)
            if activate:
                if build_status != "succeeded":
                    raise ValueError("only succeeded builds can become active")
                self._activate_if_newer(session, build)
            result = _build_record(build)
        return result

    def read_active_build(
        self,
        collection_id: str,
    ) -> CollectionBuildRecord | None:
        statement = (
            select(CollectionBuild)
            .join(
                CollectionActiveBuild,
                CollectionActiveBuild.build_id == CollectionBuild.build_id,
            )
            .where(CollectionActiveBuild.collection_id == collection_id)
        )
        with self.session_factory() as session:
            build = session.scalar(statement)
            return _build_record(build) if build is not None else None

    @staticmethod
    def _activate_if_newer(session: Session, build: CollectionBuild) -> None:
        collection = session.scalar(
            select(Collection)
            .where(Collection.collection_id == build.collection_id)
            .with_for_update()
        )
        if collection is None:
            raise RuntimeError(f"collection not found: {build.collection_id}")
        active = session.get(CollectionActiveBuild, build.collection_id)
        if active is None:
            session.add(
                CollectionActiveBuild(
                    collection_id=build.collection_id,
                    build_id=build.build_id,
                )
            )
            return
        current = session.get(CollectionBuild, active.build_id)
        if current is None or current.build_number < build.build_number:
            active.build_id = build.build_id


def _task_row(record: TaskRecord) -> Task:
    return Task(
        task_id=record.task_id,
        collection_id=record.collection_id,
        task_type=record.task_type,
        status=record.status,
        current_stage=record.current_stage,
        progress_percent=record.progress_percent,
        progress_detail=(
            dict(record.progress_detail) if record.progress_detail is not None else None
        ),
        output_path=record.output_path,
        errors=list(record.errors),
        warnings=list(record.warnings),
        details=dict(record.details),
        created_at=_datetime(record.created_at),
        updated_at=_datetime(record.updated_at),
        started_at=_optional_datetime(record.started_at),
        finished_at=_optional_datetime(record.finished_at),
    )


def _update_task_row(row: Task, record: TaskRecord) -> None:
    row.task_type = record.task_type
    row.status = record.status
    row.current_stage = record.current_stage
    row.progress_percent = record.progress_percent
    row.progress_detail = (
        dict(record.progress_detail) if record.progress_detail is not None else None
    )
    row.output_path = record.output_path
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
        task_type=row.task_type,
        status=row.status,
        current_stage=row.current_stage,
        progress_percent=row.progress_percent,
        progress_detail=(
            dict(row.progress_detail) if row.progress_detail is not None else None
        ),
        output_path=row.output_path,
        errors=tuple(row.errors),
        warnings=tuple(row.warnings),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        started_at=_optional_iso(row.started_at),
        finished_at=_optional_iso(row.finished_at),
        details=dict(row.details),
    )


def _build_record(row: CollectionBuild) -> CollectionBuildRecord:
    return CollectionBuildRecord(
        build_id=row.build_id,
        task_id=row.task_id,
        collection_id=row.collection_id,
        build_number=row.build_number,
        status=row.status,
        created_at=_iso(row.created_at),
        started_at=_optional_iso(row.started_at),
        finished_at=_optional_iso(row.finished_at),
    )


def _stage_row(record: BuildStageRecord) -> BuildStage:
    return BuildStage(
        stage_id=record.stage_id,
        build_id=record.build_id,
        stage_kind=record.stage_kind,
        stage_version=record.stage_version,
        stage_order=record.stage_order,
        status=record.status,
        started_at=_optional_datetime(record.started_at),
        finished_at=_optional_datetime(record.finished_at),
        errors=list(record.errors),
        warnings=list(record.warnings),
        skip_reason=record.skip_reason,
    )


def _update_stage_row(row: BuildStage, record: BuildStageRecord) -> None:
    row.status = record.status
    row.started_at = _optional_datetime(record.started_at)
    row.finished_at = _optional_datetime(record.finished_at)
    row.errors = list(record.errors)
    row.warnings = list(record.warnings)
    row.skip_reason = record.skip_reason


def _stage_record(row: BuildStage) -> BuildStageRecord:
    return BuildStageRecord(
        stage_id=row.stage_id,
        build_id=row.build_id,
        stage_kind=row.stage_kind,
        stage_version=row.stage_version,
        stage_order=row.stage_order,
        status=row.status,
        started_at=_optional_iso(row.started_at),
        finished_at=_optional_iso(row.finished_at),
        errors=tuple(row.errors),
        warnings=tuple(row.warnings),
        skip_reason=row.skip_reason,
    )


def _artifact_row(record: ArtifactVersionRecord) -> ArtifactVersion:
    return ArtifactVersion(
        artifact_version_id=record.artifact_version_id,
        build_stage_id=record.build_stage_id,
        artifact_kind=record.artifact_kind,
        schema_version=record.schema_version,
        content_version=record.content_version,
        status=record.status,
        object_id=record.object_id,
        details=dict(record.details),
        created_at=_datetime(record.created_at),
    )


def _artifact_record(row: ArtifactVersion) -> ArtifactVersionRecord:
    return ArtifactVersionRecord(
        artifact_version_id=row.artifact_version_id,
        build_stage_id=row.build_stage_id,
        artifact_kind=row.artifact_kind,
        schema_version=row.schema_version,
        content_version=row.content_version,
        status=row.status,
        object_id=row.object_id,
        details=dict(row.details),
        created_at=_iso(row.created_at),
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
    return None if value is None else _datetime(value)


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


def _optional_iso(value: datetime | None) -> str | None:
    return _iso(value) if value is not None else None


__all__ = ["PostgresBuildRepository"]
