"""PostgreSQL persistence for task dataset samples and build revisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.feedback_dataset_sample_repository import (
    CollectedDatasetSample,
    ConfirmedDatasetMember,
    DatasetSampleActionConflict,
    DatasetSampleRevisionConflict,
)
from domain.feedback.analysis_job import AnalysisJob
from domain.feedback.dataset_sample import DatasetSample, SampleAction, ensure_action_allowed
from domain.feedback.sample_revision import SampleRevision, parse_revision_content
from infra.persistence.postgres.models.feedback import AnalysisJobRow
from infra.persistence.postgres.models.feedback_dataset import (
    FeedbackSampleActionRow,
    FeedbackDatasetSampleRow,
    FeedbackSampleRevisionRow,
)


class PostgresFeedbackDatasetSampleRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def collect(
        self,
        *,
        samples: tuple[DatasetSample, ...],
        jobs: tuple[AnalysisJob, ...],
    ) -> tuple[CollectedDatasetSample, ...]:
        if len(samples) != len(jobs):
            raise ValueError("sample and job collections must have equal length")
        collected: list[CollectedDatasetSample] = []
        async with self.session_factory.begin() as session:
            for sample, job in zip(samples, jobs, strict=True):
                existing = await session.scalar(
                    select(FeedbackDatasetSampleRow)
                    .where(
                        FeedbackDatasetSampleRow.dataset_id == sample.dataset_id,
                        FeedbackDatasetSampleRow.source_case_id == sample.source_case_id,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    # Collection is idempotent.  A later source-case change
                    # must go through an explicit rebuild so a human revision
                    # is never replaced by a second collect click.
                    collected.append(CollectedDatasetSample(_sample(existing), None))
                    continue

                row = FeedbackDatasetSampleRow(
                    sample_id=sample.sample_id,
                    dataset_id=sample.dataset_id,
                    source_case_id=sample.source_case_id,
                    status=sample.status,
                    current_revision_id=sample.current_revision_id,
                    confirmed_revision_id=sample.confirmed_revision_id,
                    generation=sample.generation,
                    source_digest=sample.source_digest,
                    active_job_id=sample.active_job_id,
                    missing_reasons=list(sample.missing_reasons),
                    created_at=_datetime(sample.created_at),
                    updated_at=_datetime(sample.updated_at),
                    confirmed_by=sample.confirmed_by,
                    confirmed_at=_datetime(sample.confirmed_at) if sample.confirmed_at else None,
                )
                job_row = _job_row(job)
                session.add(row)
                session.add(job_row)
                try:
                    await session.flush()
                except IntegrityError:
                    # A concurrent collector may have inserted this exact
                    # dataset/source pair.  The outer transaction is not
                    # reusable after a flush failure, so surface the error;
                    # callers can retry the idempotent collect operation.
                    raise
                collected.append(CollectedDatasetSample(sample, job))
        return tuple(collected)

    async def read_sample(
        self, *, dataset_id: str, sample_id: str
    ) -> DatasetSample | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(FeedbackDatasetSampleRow).where(
                    FeedbackDatasetSampleRow.dataset_id == dataset_id,
                    FeedbackDatasetSampleRow.sample_id == sample_id,
                )
            )
            return _sample(row) if row is not None else None

    async def list_samples(
        self,
        *,
        dataset_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[DatasetSample, ...]:
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        statement = select(FeedbackDatasetSampleRow).where(
            FeedbackDatasetSampleRow.dataset_id == dataset_id
        )
        if status is not None:
            statement = statement.where(FeedbackDatasetSampleRow.status == status)
        statement = statement.order_by(
            FeedbackDatasetSampleRow.created_at,
            FeedbackDatasetSampleRow.sample_id,
        )
        if limit is not None:
            statement = statement.offset(offset).limit(limit)
        else:
            statement = statement.offset(offset)
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_sample(row) for row in rows)

    async def read_revision(self, revision_id: str) -> SampleRevision | None:
        async with self.session_factory() as session:
            row = await session.get(FeedbackSampleRevisionRow, revision_id)
            return _revision(row) if row is not None else None

    async def count_samples(self, *, dataset_id: str, status: str | None = None) -> int:
        from sqlalchemy import func

        statement = select(func.count()).select_from(FeedbackDatasetSampleRow).where(
            FeedbackDatasetSampleRow.dataset_id == dataset_id
        )
        if status is not None:
            statement = statement.where(FeedbackDatasetSampleRow.status == status)
        async with self.session_factory() as session:
            return int((await session.scalar(statement)) or 0)

    async def read_confirmed_members(
        self, *, dataset_id: str
    ) -> tuple[ConfirmedDatasetMember, ...]:
        statement = (
            select(FeedbackDatasetSampleRow, FeedbackSampleRevisionRow)
            .join(
                FeedbackSampleRevisionRow,
                FeedbackDatasetSampleRow.confirmed_revision_id
                == FeedbackSampleRevisionRow.revision_id,
            )
            .where(
                FeedbackDatasetSampleRow.dataset_id == dataset_id,
                FeedbackDatasetSampleRow.status == "confirmed",
                FeedbackDatasetSampleRow.current_revision_id
                == FeedbackDatasetSampleRow.confirmed_revision_id,
            )
            .order_by(
                FeedbackDatasetSampleRow.created_at,
                FeedbackDatasetSampleRow.sample_id,
            )
        )
        async with self.session_factory() as session:
            rows = (await session.execute(statement)).all()
            return tuple(
                ConfirmedDatasetMember(sample=_sample(sample), revision=_revision(revision))
                for sample, revision in rows
            )

    async def append_human_revision(
        self,
        *,
        sample_id: str,
        expected_revision_id: str | None,
        expected_generation: int | None = None,
        revision: SampleRevision,
        updated_at: str,
    ) -> DatasetSample:
        if revision.author_kind != "human" or revision.sample_id != sample_id:
            raise ValueError("human revision identity is invalid")
        timestamp = _datetime(updated_at)
        async with self.session_factory.begin() as session:
            row = await session.scalar(
                select(FeedbackDatasetSampleRow)
                .where(FeedbackDatasetSampleRow.sample_id == sample_id)
                .with_for_update()
            )
            if row is None:
                raise FileNotFoundError("dataset sample not found")
            if row.current_revision_id != expected_revision_id:
                raise DatasetSampleRevisionConflict("sample_revision_stale")
            if expected_generation is not None and row.generation != expected_generation:
                raise DatasetSampleRevisionConflict("sample_revision_stale")
            if row.status not in {"needs_input", "needs_confirmation", "confirmed"}:
                raise DatasetSampleRevisionConflict("sample_not_editable")
            if expected_revision_id is None and expected_generation is None:
                raise ValueError("sample_generation_required")
            session.add(_revision_row(revision))
            await session.flush()
            row.current_revision_id = revision.revision_id
            row.confirmed_revision_id = None
            row.confirmed_by = None
            row.confirmed_at = None
            row.status = "needs_confirmation"
            row.missing_reasons = []
            row.updated_at = timestamp
            await session.flush()
            return _sample(row)

    async def confirm_revision(
        self,
        *,
        sample_id: str,
        expected_revision_id: str,
        confirmed_by: str,
        confirmed_at: str,
    ) -> DatasetSample:
        timestamp = _datetime(confirmed_at)
        async with self.session_factory.begin() as session:
            row = await session.scalar(
                select(FeedbackDatasetSampleRow)
                .where(FeedbackDatasetSampleRow.sample_id == sample_id)
                .with_for_update()
            )
            if row is None:
                raise FileNotFoundError("dataset sample not found")
            if row.confirmed_revision_id == expected_revision_id and row.status == "confirmed":
                return _sample(row)
            if row.current_revision_id != expected_revision_id:
                raise DatasetSampleRevisionConflict("sample_revision_stale")
            if row.status != "needs_confirmation":
                raise ValueError("sample_not_confirmable")
            revision = await session.get(FeedbackSampleRevisionRow, expected_revision_id)
            if revision is None or revision.sample_id != sample_id:
                raise ValueError("sample_revision_missing")
            row.confirmed_revision_id = expected_revision_id
            row.confirmed_by = confirmed_by
            row.confirmed_at = timestamp
            row.status = "confirmed"
            row.updated_at = timestamp
            await session.flush()
            return _sample(row)

    async def apply_action(
        self,
        *,
        dataset_id: str,
        sample_id: str,
        expected_revision_id: str | None,
        expected_generation: int,
        action: SampleAction,
        reason: str | None,
        actor_id: str,
        idempotency_key: str,
        request_digest: str,
        source_digest: str | None,
        job: AnalysisJob | None,
        now: str,
    ) -> DatasetSample:
        timestamp = _datetime(now)
        async with self.session_factory.begin() as session:
            row = await session.scalar(
                select(FeedbackDatasetSampleRow)
                .where(
                    FeedbackDatasetSampleRow.dataset_id == dataset_id,
                    FeedbackDatasetSampleRow.sample_id == sample_id,
                )
                .with_for_update()
            )
            if row is None:
                raise FileNotFoundError("dataset sample not found")
            previous_action = await session.scalar(
                select(FeedbackSampleActionRow).where(
                    FeedbackSampleActionRow.sample_id == sample_id,
                    FeedbackSampleActionRow.idempotency_key == idempotency_key,
                )
            )
            if previous_action is not None:
                if (
                    previous_action.request_digest != request_digest
                    or previous_action.actor_id != actor_id
                ):
                    raise DatasetSampleActionConflict("sample_action_identity_conflict")
                return DatasetSample(**previous_action.result_sample)
            if row.generation != expected_generation or row.current_revision_id != expected_revision_id:
                raise DatasetSampleActionConflict("sample_revision_stale")
            ensure_action_allowed(row.status, action)
            previous_status = row.status
            generation = row.generation + 1
            if action in {"rebuild", "retry"}:
                if job is None or source_digest is None:
                    raise ValueError("sample build action requires a job and source digest")
                if (
                    job.status != "pending"
                    or job.payload.get("sample_id") != sample_id
                    or job.payload.get("generation") != generation
                    or job.payload.get("source_digest") != source_digest
                ):
                    raise ValueError("sample build action job identity is invalid")
                session.add(_job_row(job))
                row.status = "pending"
                row.active_job_id = job.job_id
                row.source_digest = source_digest
                row.missing_reasons = []
            elif action == "discard":
                if job is not None:
                    raise ValueError("discard cannot create a job")
                row.status = "discarded"
                row.active_job_id = None
            else:
                if job is not None or source_digest is None:
                    raise ValueError("restore requires current source identity and no job")
                current = (
                    await session.get(FeedbackSampleRevisionRow, row.current_revision_id)
                    if row.current_revision_id else None
                )
                has_current_content = (
                    current is not None
                    and current.sample_id == sample_id
                    and current.input_digest == source_digest
                )
                row.status = "needs_confirmation" if has_current_content else "needs_input"
                row.active_job_id = None
                row.source_digest = source_digest
                row.missing_reasons = [] if has_current_content else ["source_changed_or_incomplete"]
            row.generation = generation
            row.confirmed_revision_id = None
            row.confirmed_by = None
            row.confirmed_at = None
            row.updated_at = timestamp
            await session.flush()
            result = _sample(row)
            session.add(
                FeedbackSampleActionRow(
                    action_id=f"action_{uuid4().hex[:32]}",
                    sample_id=sample_id,
                    actor_id=actor_id,
                    action=action,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    expected_revision_id=expected_revision_id,
                    previous_status=previous_status,
                    next_status=row.status,
                    generation=generation,
                    reason=reason,
                    job_id=job.job_id if job else None,
                    result_sample=result.to_record(),
                    created_at=timestamp,
                )
            )
            await session.flush()
            return result

    async def complete_build(
        self,
        *,
        job: AnalysisJob,
        sample_id: str,
        generation: int,
        revision: SampleRevision | None,
        outcome: str,
        missing_reasons: tuple[str, ...] = (),
        error_code: str | None = None,
        finished_at: str,
    ) -> DatasetSample | None:
        if outcome not in {"candidate", "needs_input", "failed"}:
            raise ValueError("invalid sample build outcome")
        if outcome == "candidate" and revision is None:
            raise ValueError("candidate build requires a revision")
        if outcome != "candidate" and revision is not None:
            raise ValueError("non-candidate build cannot persist a revision")
        timestamp = _datetime(finished_at)
        async with self.session_factory.begin() as session:
            job_row = await session.get(AnalysisJobRow, job.job_id, with_for_update=True)
            if job_row is None:
                raise FileNotFoundError("sample build identity not found")
            if job_row.status in {"succeeded", "failed", "cancelled"}:
                if job_row.lease_version != job.lease_version:
                    return None
            elif not _lease_matches(job_row, job, timestamp):
                return None
            row = await session.scalar(
                select(FeedbackDatasetSampleRow)
                .where(FeedbackDatasetSampleRow.sample_id == sample_id)
                .with_for_update()
            )
            if row is None:
                raise FileNotFoundError("sample build identity not found")
            if (
                row.generation != generation
                or row.active_job_id != job.job_id
                or row.source_digest != job.payload.get("source_digest")
            ):
                if job_row.status == "running":
                    _finish_job(
                        job_row,
                        status="cancelled",
                        finished_at=timestamp,
                        result_id=None,
                        error_code="sample_build_superseded",
                    )
                return None
            if job_row.status in {"succeeded", "failed", "cancelled"}:
                return _sample(row)
            if job_row.status != "running" or row.status not in {"pending", "building"}:
                raise ValueError("sample build is not running")

            if outcome == "candidate":
                assert revision is not None
                if revision.sample_id != sample_id:
                    raise ValueError("revision does not belong to sample")
                session.add(_revision_row(revision))
                await session.flush()
                row.current_revision_id = revision.revision_id
                row.status = "needs_confirmation"
                row.active_job_id = None
                row.confirmed_revision_id = None
                row.confirmed_by = None
                row.confirmed_at = None
                row.missing_reasons = []
                _finish_job(
                    job_row,
                    status="succeeded",
                    finished_at=timestamp,
                    result_id=revision.revision_id,
                    error_code=None,
                )
            elif outcome == "needs_input":
                row.status = "needs_input"
                row.active_job_id = None
                row.confirmed_revision_id = None
                row.confirmed_by = None
                row.confirmed_at = None
                row.missing_reasons = list(
                    dict.fromkeys(item.strip() for item in missing_reasons if item.strip())
                )
                _finish_job(
                    job_row,
                    status="succeeded",
                    finished_at=timestamp,
                    result_id=sample_id,
                    error_code=None,
                )
            else:
                row.status = "build_failed"
                row.active_job_id = None
                row.confirmed_revision_id = None
                row.confirmed_by = None
                row.confirmed_at = None
                row.missing_reasons = [error_code or "sample_build_failed"]
                _finish_job(
                    job_row,
                    status="failed",
                    finished_at=timestamp,
                    result_id=None,
                    error_code=error_code or "sample_build_failed",
                )
            row.updated_at = timestamp
            await session.flush()
            return _sample(row)


def _job_row(job: AnalysisJob) -> AnalysisJobRow:
    return AnalysisJobRow(
        job_id=job.job_id,
        job_type=job.job_type,
        payload_version=job.payload_version,
        payload=dict(job.payload),
        status=job.status,
        available_at=_datetime(job.available_at),
        started_at=_datetime(job.started_at) if job.started_at else None,
        finished_at=_datetime(job.finished_at) if job.finished_at else None,
        result_id=job.result_id,
        error_code=job.error_code,
        idempotency_key=job.idempotency_key,
        created_at=_datetime(job.created_at),
        updated_at=_datetime(job.updated_at),
        worker_id=job.worker_id,
        lease_expires_at=_datetime(job.lease_expires_at) if job.lease_expires_at else None,
        heartbeat_at=_datetime(job.heartbeat_at) if job.heartbeat_at else None,
        lease_version=job.lease_version,
    )


def _finish_job(
    row: AnalysisJobRow,
    *,
    status: str,
    finished_at: datetime,
    result_id: str | None,
    error_code: str | None,
) -> None:
    row.status = status
    row.finished_at = finished_at
    row.updated_at = finished_at
    row.result_id = result_id
    row.error_code = error_code
    _clear_lease(row)


def _clear_lease(row: AnalysisJobRow) -> None:
    row.worker_id = None
    row.lease_expires_at = None
    row.heartbeat_at = None


def _lease_matches(row: AnalysisJobRow, job: AnalysisJob, timestamp: datetime) -> bool:
    return bool(job.worker_id) and (
        row.status == "running"
        and row.worker_id == job.worker_id
        and row.lease_version == job.lease_version
        and row.lease_expires_at is not None
        and row.lease_expires_at > timestamp
    )


def _sample(row: FeedbackDatasetSampleRow) -> DatasetSample:
    return DatasetSample(
        sample_id=row.sample_id,
        dataset_id=row.dataset_id,
        source_case_id=row.source_case_id,
        status=row.status,  # type: ignore[arg-type]
        current_revision_id=row.current_revision_id,
        confirmed_revision_id=row.confirmed_revision_id,
        generation=row.generation,
        source_digest=row.source_digest,
        active_job_id=row.active_job_id,
        missing_reasons=tuple(row.missing_reasons or ()),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        confirmed_by=row.confirmed_by,
        confirmed_at=_iso(row.confirmed_at) if row.confirmed_at else None,
    )


def _revision(row: FeedbackSampleRevisionRow) -> SampleRevision:
    return SampleRevision(
        revision_id=row.revision_id,
        sample_id=row.sample_id,
        revision_no=row.revision_no,
        author_kind=row.author_kind,  # type: ignore[arg-type]
        content=parse_revision_content(row.content),
        content_digest=row.content_digest,
        input_digest=row.input_digest,
        construction_spec_version=row.construction_spec_version,
        provenance=dict(row.provenance or {}),
        created_at=_iso(row.created_at),
        created_by=row.created_by,
        job_id=row.job_id,
    )


def _revision_row(revision: SampleRevision) -> FeedbackSampleRevisionRow:
    return FeedbackSampleRevisionRow(
        revision_id=revision.revision_id,
        sample_id=revision.sample_id,
        revision_no=revision.revision_no,
        author_kind=revision.author_kind,
        content=revision.content.to_record(),
        content_digest=revision.content_digest,
        input_digest=revision.input_digest,
        construction_spec_version=revision.construction_spec_version,
        provenance=dict(revision.provenance),
        created_by=revision.created_by,
        job_id=revision.job_id,
        created_at=_datetime(revision.created_at),
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.isoformat()


__all__ = ["PostgresFeedbackDatasetSampleRepository"]
