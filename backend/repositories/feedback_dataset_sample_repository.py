"""PostgreSQL repository for feedback dataset sample."""

from __future__ import annotations

from copy import deepcopy

from domain.feedback.sample_revision import (
    SftRevisionContent, PreferenceRevisionContent, EvaluationRevisionContent,
    SFT_SCHEMA_VERSION, PREFERENCE_SCHEMA_VERSION, EVALUATION_SCHEMA_VERSION,
)

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.persistence.database import AsyncSessionLocal

from domain.feedback.dataset_sample import (
    DatasetSample,
    SampleAction,
    _is_sha256,
    ensure_action_allowed,
)
from domain.feedback.sample_revision import SampleRevision, content_digest_for
from domain.feedback.feedback_case import FeedbackCase
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.feedback import AnalysisJobRow, FeedbackCaseRow
from infra.persistence.postgres.models.feedback_dataset import (
    FeedbackDatasetRow,
    FeedbackDatasetSampleRow,
    FeedbackSampleActionRow,
    FeedbackSampleRevisionRow,
)
from repositories.analysis_job_repository import (
    DATASET_SAMPLE_BUILD_JOB_TYPE,
    DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
    AnalysisJob,
)
from repositories.feedback_dataset_repository import ensure_system_datasets


def sample_action_digest(
    *, action: SampleAction, expected_revision_id: str | None, reason: str | None
) -> str:
    payload = {
        "action": action,
        "expected_revision_id": expected_revision_id,
        "reason": (reason or "").strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def source_digest_for_case(case: FeedbackCase | FeedbackCaseRow) -> str:
    """Hash sample source content, excluding workflow status and timestamps."""
    canonical = {
        "case_id": case.case_id,
        "collection_id": case.collection_id,
        "session_id": case.session_id,
        "anchor_message_id": case.anchor_message_id,
        "source_signal_ids": list(case.source_signal_ids),
        "analysis_result_ids": list(case.analysis_result_ids),
        "signal_analysis_result_ids": list(case.signal_analysis_result_ids),
        "tool_failure_analysis_result_ids": list(case.tool_failure_analysis_result_ids),
        "context_snapshot": case.context_snapshot,
        "annotation_digest": case.annotation_digest,
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def sample_build_idempotency_key(
    *,
    sample_id: str,
    generation: int,
    spec_version: int,
    source_digest: str,
) -> str:
    if generation < 1 or spec_version < 1 or not _is_sha256(source_digest):
        raise ValueError("invalid sample build identity")
    return ":".join(
        (
            DATASET_SAMPLE_BUILD_JOB_TYPE,
            sample_id,
            str(generation),
            str(spec_version),
            source_digest,
        )
    )



@dataclass(frozen=True)
class CollectedDatasetSample:
    sample: DatasetSample
    job: AnalysisJob | None


@dataclass(frozen=True)
class ConfirmedDatasetMember:
    sample: DatasetSample
    revision: SampleRevision


class DatasetSampleRevisionConflict(ValueError):
    """The sample changed after the caller read its current revision."""


class DatasetSampleActionConflict(ValueError):
    """An action key or the sample generation changed."""


BuildCompletionKind = Literal["candidate", "needs_input", "failed"]


class FeedbackDatasetSampleRepository:
    backend_name = "postgresql"

    async def backfill_existing_cases(self) -> int:
        """Initialize historical workbenches once at Worker startup, in bounded batches."""
        cursor = ""
        while True:
            async with AsyncSessionLocal() as db, db.begin():
                collections = list(await db.scalars(
                    select(Collection).where(Collection.collection_id > cursor)
                    .order_by(Collection.collection_id).limit(200)
                ))
                for collection in collections:
                    await ensure_system_datasets(
                        db, collection_id=collection.collection_id,
                        owner_user_id=collection.owner_user_id, now=datetime.now(timezone.utc),
                    )
                if collections:
                    cursor = collections[-1].collection_id
            if len(collections) < 200:
                break

        cursor = ""
        processed = 0
        while True:
            async with AsyncSessionLocal() as db, db.begin():
                cases = list(await db.scalars(
                    select(FeedbackCaseRow).where(
                        FeedbackCaseRow.case_id > cursor, FeedbackCaseRow.status != "withdrawn",
                    ).order_by(FeedbackCaseRow.case_id).limit(200).with_for_update()
                ))
                for case in cases:
                    await enqueue_case_samples(db, case, now=datetime.now(timezone.utc))
                processed += len(cases)
                if cases:
                    cursor = cases[-1].case_id
            if len(cases) < 200:
                return processed

    async def collect(
        self,
        *,
        samples: tuple[DatasetSample, ...],
        jobs: tuple[AnalysisJob, ...],
    ) -> tuple[CollectedDatasetSample, ...]:
        if len(samples) != len(jobs):
            raise ValueError("sample and job collections must have equal length")
        collected: list[CollectedDatasetSample] = []
        async with AsyncSessionLocal() as db, db.begin():
            cases = {
                case.case_id: case
                for case in await db.scalars(
                    select(FeedbackCaseRow)
                    .where(FeedbackCaseRow.case_id.in_(tuple(sample.source_case_id for sample in samples)))
                    .order_by(FeedbackCaseRow.case_id)
                    .with_for_update()
                )
            }
            for sample, job in zip(samples, jobs, strict=True):
                case = cases.get(sample.source_case_id)
                if (
                    case is None or case.status == "withdrawn"
                    or source_digest_for_case(case) != sample.source_digest
                ):
                    raise DatasetSampleRevisionConflict("sample_source_stale")
                collected.append(await _collect_sample(db, sample, job))
        return tuple(collected)

    async def read_sample(
        self, *, dataset_id: str, sample_id: str
    ) -> DatasetSample | None:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(FeedbackDatasetSampleRow).where(
                    FeedbackDatasetSampleRow.dataset_id == dataset_id,
                    FeedbackDatasetSampleRow.sample_id == sample_id,
                )
            )
            return (
                DatasetSample(
                    sample_id=row.sample_id,
                    dataset_id=row.dataset_id,
                    source_case_id=row.source_case_id,
                    status=row.status,
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
                if row is not None
                else None
            )

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
        statement = select(FeedbackDatasetSampleRow).join(FeedbackCaseRow).where(
            FeedbackDatasetSampleRow.dataset_id == dataset_id,
            FeedbackCaseRow.status != "withdrawn",
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
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(statement)
            return tuple(
                DatasetSample(
                    sample_id=row.sample_id,
                    dataset_id=row.dataset_id,
                    source_case_id=row.source_case_id,
                    status=row.status,
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
                for row in rows
            )

    async def read_revision(self, revision_id: str) -> SampleRevision | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(FeedbackSampleRevisionRow, revision_id)
            if row is None:
                return None
            content_value = row.content
            if content_value["schema_version"] == SFT_SCHEMA_VERSION:
                content = SftRevisionContent(
                    schema_version=content_value["schema_version"],
                    messages=tuple(content_value["messages"]),
                    context=tuple(content_value["context"]),
                    evidence=tuple(content_value["evidence"]),
                    target=content_value["target"],
                )
            elif content_value["schema_version"] == PREFERENCE_SCHEMA_VERSION:
                content = PreferenceRevisionContent(
                    schema_version=content_value["schema_version"],
                    messages=tuple(content_value["messages"]),
                    context=tuple(content_value["context"]),
                    evidence=tuple(content_value["evidence"]),
                    response_a=content_value["response_a"],
                    response_b=content_value["response_b"],
                    suggested_preference=content_value["suggested_preference"],
                    rationale=content_value["rationale"],
                    human_preference=content_value["human_preference"],
                )
            elif content_value["schema_version"] == EVALUATION_SCHEMA_VERSION:
                content = EvaluationRevisionContent(
                    schema_version=content_value["schema_version"],
                    messages=tuple(content_value["messages"]),
                    context=tuple(content_value["context"]),
                    evidence=tuple(content_value["evidence"]),
                    reference=content_value["reference"],
                    criteria=tuple(content_value["criteria"]),
                    evaluation_mode=content_value["evaluation_mode"],
                )
            else:
                raise ValueError("unsupported sample revision schema")
            return SampleRevision(
                revision_id=row.revision_id,
                sample_id=row.sample_id,
                revision_no=row.revision_no,
                author_kind=row.author_kind,
                content=content,
                content_digest=row.content_digest,
                input_digest=row.input_digest,
                construction_spec_version=row.construction_spec_version,
                provenance=row.provenance,
                created_at=_iso(row.created_at),
                created_by=row.created_by,
                job_id=row.job_id,
            )

    async def count_samples(self, *, dataset_id: str, status: str | None = None) -> int:
        from sqlalchemy import func

        statement = select(func.count()).select_from(FeedbackDatasetSampleRow).where(
            FeedbackDatasetSampleRow.dataset_id == dataset_id
        ).join(FeedbackCaseRow).where(FeedbackCaseRow.status != "withdrawn")
        if status is not None:
            statement = statement.where(FeedbackDatasetSampleRow.status == status)
        async with AsyncSessionLocal() as db:
            return int((await db.scalar(statement)) or 0)

    async def read_confirmed_members(
        self, *, dataset_id: str, sample_ids: tuple[str, ...] | None = None
    ) -> tuple[ConfirmedDatasetMember, ...]:
        statement = (
            select(FeedbackDatasetSampleRow, FeedbackSampleRevisionRow, FeedbackCaseRow)
            .join(
                FeedbackSampleRevisionRow,
                FeedbackDatasetSampleRow.confirmed_revision_id
                == FeedbackSampleRevisionRow.revision_id,
            )
            .join(
                FeedbackCaseRow,
                FeedbackCaseRow.case_id == FeedbackDatasetSampleRow.source_case_id,
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
        if sample_ids is not None:
            statement = statement.where(FeedbackDatasetSampleRow.sample_id.in_(sample_ids))
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(statement)).all()
            members: list[ConfirmedDatasetMember] = []
            for sample, revision, case in rows:
                if case.status == "withdrawn":
                    # A withdrawn source invalidates only this sample.  Do
                    # not make one stale row break the whole workbench or
                    # prevent other confirmed samples from being exported.
                    continue
                if source_digest_for_case(case) != sample.source_digest:
                    raise DatasetSampleRevisionConflict("sample_source_stale")
                content_value = revision.content
                if content_value["schema_version"] == SFT_SCHEMA_VERSION:
                    content = SftRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        target=content_value["target"],
                    )
                elif content_value["schema_version"] == PREFERENCE_SCHEMA_VERSION:
                    content = PreferenceRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        response_a=content_value["response_a"],
                        response_b=content_value["response_b"],
                        suggested_preference=content_value["suggested_preference"],
                        rationale=content_value["rationale"],
                        human_preference=content_value["human_preference"],
                    )
                elif content_value["schema_version"] == EVALUATION_SCHEMA_VERSION:
                    content = EvaluationRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        reference=content_value["reference"],
                        criteria=tuple(content_value["criteria"]),
                        evaluation_mode=content_value["evaluation_mode"],
                    )
                else:
                    raise ValueError("unsupported sample revision schema")
                members.append(
                    ConfirmedDatasetMember(
                        sample=DatasetSample(
                            sample_id=sample.sample_id,
                            dataset_id=sample.dataset_id,
                            source_case_id=sample.source_case_id,
                            status=sample.status,
                            current_revision_id=sample.current_revision_id,
                            confirmed_revision_id=sample.confirmed_revision_id,
                            generation=sample.generation,
                            source_digest=sample.source_digest,
                            active_job_id=sample.active_job_id,
                            missing_reasons=tuple(sample.missing_reasons or ()),
                            created_at=_iso(sample.created_at),
                            updated_at=_iso(sample.updated_at),
                            confirmed_by=sample.confirmed_by,
                            confirmed_at=(
                                _iso(sample.confirmed_at)
                                if sample.confirmed_at
                                else None
                            ),
                        ),
                        revision=SampleRevision(
                            revision_id=revision.revision_id,
                            sample_id=revision.sample_id,
                            revision_no=revision.revision_no,
                            author_kind=revision.author_kind,
                            content=content,
                            content_digest=revision.content_digest,
                            input_digest=revision.input_digest,
                            construction_spec_version=revision.construction_spec_version,
                            provenance=revision.provenance,
                            created_at=_iso(revision.created_at),
                            created_by=revision.created_by,
                            job_id=revision.job_id,
                        ),
                    )
                )
            return tuple(members)

    async def append_human_revision(
        self,
        *,
        sample_id: str,
        expected_revision_id: str | None,
        expected_generation: int | None = None,
        expected_source_digest: str,
        revision: SampleRevision,
        updated_at: str,
    ) -> DatasetSample:
        if revision.author_kind != "human" or revision.sample_id != sample_id:
            raise ValueError("human revision identity is invalid")
        if revision.content_digest != content_digest_for(revision.content):
            raise ValueError("revision content digest does not match content")
        timestamp = _datetime(updated_at)
        async with AsyncSessionLocal() as db, db.begin():
            row, case = await _lock_sample_source(db, sample_id)
            if row.current_revision_id != expected_revision_id:
                raise DatasetSampleRevisionConflict("sample_revision_stale")
            if expected_generation is not None and row.generation != expected_generation:
                raise DatasetSampleRevisionConflict("sample_revision_stale")
            if row.status not in {"needs_input", "needs_confirmation", "confirmed"}:
                raise DatasetSampleRevisionConflict("sample_not_editable")
            if case is None or case.status == "withdrawn":
                raise DatasetSampleRevisionConflict("sample_source_stale")
            if source_digest_for_case(case) != expected_source_digest:
                raise DatasetSampleRevisionConflict("sample_source_stale")
            if expected_revision_id is None and expected_generation is None:
                raise ValueError("sample_generation_required")
            content_value = revision.content
            if isinstance(content_value, SftRevisionContent):
                content_payload = {
                    "schema_version": content_value.schema_version,
                    "messages": [dict(item) for item in content_value.messages],
                    "context": [dict(item) for item in content_value.context],
                    "evidence": [dict(item) for item in content_value.evidence],
                    "target": content_value.target,
                }
            elif isinstance(content_value, PreferenceRevisionContent):
                content_payload = {
                    "schema_version": content_value.schema_version,
                    "messages": [dict(item) for item in content_value.messages],
                    "context": [dict(item) for item in content_value.context],
                    "evidence": [dict(item) for item in content_value.evidence],
                    "response_a": content_value.response_a,
                    "response_b": content_value.response_b,
                    "suggested_preference": content_value.suggested_preference,
                    "rationale": content_value.rationale,
                    "human_preference": content_value.human_preference,
                }
            else:
                content_payload = {
                    "schema_version": content_value.schema_version,
                    "messages": [dict(item) for item in content_value.messages],
                    "context": [dict(item) for item in content_value.context],
                    "evidence": [dict(item) for item in content_value.evidence],
                    "reference": content_value.reference,
                    "criteria": list(content_value.criteria),
                    "evaluation_mode": content_value.evaluation_mode,
                }
            db.add(
                FeedbackSampleRevisionRow(
                    revision_id=revision.revision_id,
                    sample_id=revision.sample_id,
                    revision_no=revision.revision_no,
                    author_kind=revision.author_kind,
                    content=content_payload,
                    content_digest=revision.content_digest,
                    input_digest=revision.input_digest,
                    construction_spec_version=revision.construction_spec_version,
                    provenance=deepcopy(revision.provenance),
                    created_by=revision.created_by,
                    job_id=revision.job_id,
                    created_at=_datetime(revision.created_at),
                )
            )
            await db.flush()
            row.current_revision_id = revision.revision_id
            row.confirmed_revision_id = None
            row.confirmed_by = None
            row.confirmed_at = None
            row.status = "needs_confirmation"
            row.missing_reasons = []
            row.updated_at = timestamp
            await db.flush()
            return DatasetSample(
                sample_id=row.sample_id,
                dataset_id=row.dataset_id,
                source_case_id=row.source_case_id,
                status=row.status,
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

    async def confirm_revision(
        self,
        *,
        sample_id: str,
        expected_revision_id: str,
        expected_source_digest: str,
        confirmed_by: str,
        confirmed_at: str,
    ) -> DatasetSample:
        timestamp = _datetime(confirmed_at)
        async with AsyncSessionLocal() as db, db.begin():
            row, case = await _lock_sample_source(db, sample_id)
            if (
                case is None or case.status == "withdrawn"
                or source_digest_for_case(case) != expected_source_digest
            ):
                raise DatasetSampleRevisionConflict("sample_source_stale")
            if row.confirmed_revision_id == expected_revision_id and row.status == "confirmed":
                return DatasetSample(
                    sample_id=row.sample_id,
                    dataset_id=row.dataset_id,
                    source_case_id=row.source_case_id,
                    status=row.status,
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
            if row.current_revision_id != expected_revision_id:
                raise DatasetSampleRevisionConflict("sample_revision_stale")
            if row.status != "needs_confirmation":
                raise ValueError("sample_not_confirmable")
            revision = await db.get(FeedbackSampleRevisionRow, expected_revision_id)
            if revision is None or revision.sample_id != sample_id:
                raise ValueError("sample_revision_missing")
            if revision.input_digest != expected_source_digest:
                raise DatasetSampleRevisionConflict("sample_source_stale")
            row.confirmed_revision_id = expected_revision_id
            row.confirmed_by = confirmed_by
            row.confirmed_at = timestamp
            row.status = "confirmed"
            row.updated_at = timestamp
            await db.flush()
            return DatasetSample(
                sample_id=row.sample_id,
                dataset_id=row.dataset_id,
                source_case_id=row.source_case_id,
                status=row.status,
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
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.scalar(
                select(FeedbackDatasetSampleRow)
                .where(
                    FeedbackDatasetSampleRow.dataset_id == dataset_id,
                    FeedbackDatasetSampleRow.sample_id == sample_id,
                )
                .with_for_update()
            )
            if row is None:
                raise FileNotFoundError("dataset sample not found")
            previous_action = await db.scalar(
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
                result_sample = previous_action.result_sample
                return DatasetSample(
                    **{**result_sample, "missing_reasons": tuple(result_sample["missing_reasons"])}
                )
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
                db.add(
                    AnalysisJobRow(
                        job_id=job.job_id,
                        job_type=job.job_type,
                        payload_version=job.payload_version,
                        payload=dict(job.payload),
                        status=job.status,
                        available_at=_datetime(job.available_at),
                        started_at=(
                            _datetime(job.started_at) if job.started_at else None
                        ),
                        finished_at=(
                            _datetime(job.finished_at) if job.finished_at else None
                        ),
                        result_id=job.result_id,
                        error_code=job.error_code,
                        idempotency_key=job.idempotency_key,
                        created_at=_datetime(job.created_at),
                        updated_at=_datetime(job.updated_at),
                        worker_id=job.worker_id,
                        lease_expires_at=(
                            _datetime(job.lease_expires_at)
                            if job.lease_expires_at
                            else None
                        ),
                        heartbeat_at=(
                            _datetime(job.heartbeat_at) if job.heartbeat_at else None
                        ),
                        lease_version=job.lease_version,
                    )
                )
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
                    await db.get(FeedbackSampleRevisionRow, row.current_revision_id)
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
            await db.flush()
            result = DatasetSample(
                sample_id=row.sample_id,
                dataset_id=row.dataset_id,
                source_case_id=row.source_case_id,
                status=row.status,
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
            db.add(
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
                    result_sample={
                        "sample_id": result.sample_id,
                        "dataset_id": result.dataset_id,
                        "source_case_id": result.source_case_id,
                        "status": result.status,
                        "current_revision_id": result.current_revision_id,
                        "confirmed_revision_id": result.confirmed_revision_id,
                        "generation": result.generation,
                        "source_digest": result.source_digest,
                        "active_job_id": result.active_job_id,
                        "missing_reasons": list(result.missing_reasons),
                        "created_at": result.created_at,
                        "updated_at": result.updated_at,
                        "confirmed_by": result.confirmed_by,
                        "confirmed_at": result.confirmed_at,
                    },
                    created_at=timestamp,
                )
            )
            await db.flush()
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
        async with AsyncSessionLocal() as db, db.begin():
            identity = await db.get(FeedbackDatasetSampleRow, sample_id)
            if identity is None:
                raise FileNotFoundError("sample build identity not found")
            # Keep source -> job -> sample ordering compatible with case writes and claims.
            case = await db.get(FeedbackCaseRow, identity.source_case_id, with_for_update=True)
            job_row = await db.get(AnalysisJobRow, job.job_id, with_for_update=True)
            if job_row is None:
                raise FileNotFoundError("sample build identity not found")
            if job_row.status in {"succeeded", "failed", "cancelled"}:
                if job_row.lease_version != job.lease_version:
                    return None
            elif not _lease_matches(job_row, job, timestamp):
                return None
            row = await db.scalar(
                select(FeedbackDatasetSampleRow)
                .where(FeedbackDatasetSampleRow.sample_id == sample_id)
                .with_for_update()
                .execution_options(populate_existing=True)
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
                return DatasetSample(
                    sample_id=row.sample_id,
                    dataset_id=row.dataset_id,
                    source_case_id=row.source_case_id,
                    status=row.status,
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
            if job_row.status != "running" or row.status not in {"pending", "building"}:
                raise ValueError("sample build is not running")

            if (
                case is None or case.status == "withdrawn"
                or source_digest_for_case(case) != row.source_digest
            ):
                row.status = "needs_input"
                row.active_job_id = None
                row.confirmed_revision_id = None
                row.confirmed_by = None
                row.confirmed_at = None
                row.missing_reasons = ["source_changed_since_collection"]
                row.updated_at = timestamp
                _finish_job(job_row, status="succeeded", finished_at=timestamp, result_id=sample_id, error_code=None)
                await db.flush()
                return DatasetSample(
                    sample_id=row.sample_id,
                    dataset_id=row.dataset_id,
                    source_case_id=row.source_case_id,
                    status=row.status,
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

            if outcome == "candidate":
                assert revision is not None
                if revision.sample_id != sample_id:
                    raise ValueError("revision does not belong to sample")
                if revision.content_digest != content_digest_for(revision.content):
                    raise ValueError("revision content digest does not match content")
                if revision.input_digest != row.source_digest:
                    raise DatasetSampleRevisionConflict("sample_source_stale")
                content_value = revision.content
                if isinstance(content_value, SftRevisionContent):
                    content_payload = {
                        "schema_version": content_value.schema_version,
                        "messages": [dict(item) for item in content_value.messages],
                        "context": [dict(item) for item in content_value.context],
                        "evidence": [dict(item) for item in content_value.evidence],
                        "target": content_value.target,
                    }
                elif isinstance(content_value, PreferenceRevisionContent):
                    content_payload = {
                        "schema_version": content_value.schema_version,
                        "messages": [dict(item) for item in content_value.messages],
                        "context": [dict(item) for item in content_value.context],
                        "evidence": [dict(item) for item in content_value.evidence],
                        "response_a": content_value.response_a,
                        "response_b": content_value.response_b,
                        "suggested_preference": content_value.suggested_preference,
                        "rationale": content_value.rationale,
                        "human_preference": content_value.human_preference,
                    }
                else:
                    content_payload = {
                        "schema_version": content_value.schema_version,
                        "messages": [dict(item) for item in content_value.messages],
                        "context": [dict(item) for item in content_value.context],
                        "evidence": [dict(item) for item in content_value.evidence],
                        "reference": content_value.reference,
                        "criteria": list(content_value.criteria),
                        "evaluation_mode": content_value.evaluation_mode,
                    }
                db.add(
                    FeedbackSampleRevisionRow(
                        revision_id=revision.revision_id,
                        sample_id=revision.sample_id,
                        revision_no=revision.revision_no,
                        author_kind=revision.author_kind,
                        content=content_payload,
                        content_digest=revision.content_digest,
                        input_digest=revision.input_digest,
                        construction_spec_version=revision.construction_spec_version,
                        provenance=deepcopy(revision.provenance),
                        created_by=revision.created_by,
                        job_id=revision.job_id,
                        created_at=_datetime(revision.created_at),
                    )
                )
                await db.flush()
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
            await db.flush()
            return DatasetSample(
                sample_id=row.sample_id,
                dataset_id=row.dataset_id,
                source_case_id=row.source_case_id,
                status=row.status,
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


async def _lock_sample_source(
    db: AsyncSession, sample_id: str,
) -> tuple[FeedbackDatasetSampleRow, FeedbackCaseRow | None]:
    identity = await db.get(FeedbackDatasetSampleRow, sample_id)
    if identity is None:
        raise FileNotFoundError("dataset sample not found")
    case = await db.get(FeedbackCaseRow, identity.source_case_id, with_for_update=True)
    sample = await db.scalar(
        select(FeedbackDatasetSampleRow)
        .where(FeedbackDatasetSampleRow.sample_id == sample_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if sample is None:
        raise FileNotFoundError("dataset sample not found")
    return sample, case


async def enqueue_case_samples(db: AsyncSession, case: FeedbackCaseRow, *, now: datetime) -> None:
    """Persist all three sample queues in the same transaction as the case."""
    if case.status == "withdrawn":
        return
    collection = await db.get(Collection, case.collection_id)
    if collection is None:
        raise FileNotFoundError("feedback case collection not found")
    datasets = await ensure_system_datasets(
        db, collection_id=case.collection_id, owner_user_id=collection.owner_user_id, now=now,
    )
    # Existing explicitly collected samples also need invalidation when their source changes.
    additional = await db.scalars(select(FeedbackDatasetRow).where(
        FeedbackDatasetRow.collection_id == case.collection_id,
        FeedbackDatasetRow.dataset_id.not_in(tuple(dataset.dataset_id for dataset in datasets)),
        select(FeedbackDatasetSampleRow.sample_id).where(
            FeedbackDatasetSampleRow.dataset_id == FeedbackDatasetRow.dataset_id,
            FeedbackDatasetSampleRow.source_case_id == case.case_id,
        ).exists(),
    ).order_by(FeedbackDatasetRow.dataset_id))
    datasets = (*datasets, *additional)
    source_digest = source_digest_for_case(case)
    for dataset in datasets:
        sample_id = f"sample_{uuid4().hex[:32]}"
        job_id = f"job_{uuid4().hex[:32]}"
        sample = DatasetSample.pending(
            sample_id=sample_id,
            dataset_id=dataset.dataset_id,
            source_case_id=case.case_id,
            source_digest=source_digest,
            active_job_id=job_id,
            now=now.isoformat(),
        )
        job = AnalysisJob(
            job_id=job_id,
            job_type=DATASET_SAMPLE_BUILD_JOB_TYPE,
            payload_version=DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
            payload={
                "dataset_id": dataset.dataset_id,
                "sample_id": sample_id,
                "generation": 1,
                "spec_version": dataset.spec_version,
                "source_digest": source_digest,
            },
            status="pending",
            idempotency_key=sample_build_idempotency_key(
                sample_id=sample_id, generation=1, spec_version=dataset.spec_version, source_digest=source_digest,
            ),
            available_at=now.isoformat(),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        await _collect_sample(db, sample, job)


async def _collect_sample(db: AsyncSession, sample: DatasetSample, job: AnalysisJob) -> CollectedDatasetSample:
    existing = await db.scalar(
        select(FeedbackDatasetSampleRow).where(
            FeedbackDatasetSampleRow.dataset_id == sample.dataset_id,
            FeedbackDatasetSampleRow.source_case_id == sample.source_case_id,
        ).with_for_update()
    )
    if existing is not None:
        if existing.source_digest == sample.source_digest or existing.status == "discarded":
            return CollectedDatasetSample(
                DatasetSample(
                    sample_id=existing.sample_id,
                    dataset_id=existing.dataset_id,
                    source_case_id=existing.source_case_id,
                    status=existing.status,
                    current_revision_id=existing.current_revision_id,
                    confirmed_revision_id=existing.confirmed_revision_id,
                    generation=existing.generation,
                    source_digest=existing.source_digest,
                    active_job_id=existing.active_job_id,
                    missing_reasons=tuple(existing.missing_reasons or ()),
                    created_at=_iso(existing.created_at),
                    updated_at=_iso(existing.updated_at),
                    confirmed_by=existing.confirmed_by,
                    confirmed_at=(
                        _iso(existing.confirmed_at) if existing.confirmed_at else None
                    ),
                ),
                None,
            )
        existing.generation += 1
        existing.source_digest = sample.source_digest
        existing.confirmed_revision_id = None
        existing.confirmed_by = None
        existing.confirmed_at = None
        existing.updated_at = _datetime(sample.updated_at)
        revision = (
            await db.get(FeedbackSampleRevisionRow, existing.current_revision_id)
            if existing.current_revision_id else None
        )
        if revision is not None and revision.author_kind == "human":
            existing.status = "needs_input"
            existing.active_job_id = None
            existing.missing_reasons = ["source_changed_since_collection"]
            await db.flush()
            return CollectedDatasetSample(
                DatasetSample(
                    sample_id=existing.sample_id,
                    dataset_id=existing.dataset_id,
                    source_case_id=existing.source_case_id,
                    status=existing.status,
                    current_revision_id=existing.current_revision_id,
                    confirmed_revision_id=existing.confirmed_revision_id,
                    generation=existing.generation,
                    source_digest=existing.source_digest,
                    active_job_id=existing.active_job_id,
                    missing_reasons=tuple(existing.missing_reasons or ()),
                    created_at=_iso(existing.created_at),
                    updated_at=_iso(existing.updated_at),
                    confirmed_by=existing.confirmed_by,
                    confirmed_at=(
                        _iso(existing.confirmed_at) if existing.confirmed_at else None
                    ),
                ),
                None,
            )
        job = replace(
            job,
            payload={**job.payload, "sample_id": existing.sample_id, "generation": existing.generation},
            idempotency_key=sample_build_idempotency_key(
                sample_id=existing.sample_id, generation=existing.generation,
                spec_version=job.payload["spec_version"], source_digest=sample.source_digest,
            ),
        )
        db.add(
            AnalysisJobRow(
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
                lease_expires_at=(
                    _datetime(job.lease_expires_at) if job.lease_expires_at else None
                ),
                heartbeat_at=_datetime(job.heartbeat_at) if job.heartbeat_at else None,
                lease_version=job.lease_version,
            )
        )
        await db.flush()
        existing.status = "pending"
        existing.active_job_id = job.job_id
        existing.missing_reasons = []
        await db.flush()
        return CollectedDatasetSample(
            DatasetSample(
                sample_id=existing.sample_id,
                dataset_id=existing.dataset_id,
                source_case_id=existing.source_case_id,
                status=existing.status,
                current_revision_id=existing.current_revision_id,
                confirmed_revision_id=existing.confirmed_revision_id,
                generation=existing.generation,
                source_digest=existing.source_digest,
                active_job_id=existing.active_job_id,
                missing_reasons=tuple(existing.missing_reasons or ()),
                created_at=_iso(existing.created_at),
                updated_at=_iso(existing.updated_at),
                confirmed_by=existing.confirmed_by,
                confirmed_at=(
                    _iso(existing.confirmed_at) if existing.confirmed_at else None
                ),
            ),
            job,
        )

    db.add(
        AnalysisJobRow(
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
            lease_expires_at=(
                _datetime(job.lease_expires_at) if job.lease_expires_at else None
            ),
            heartbeat_at=_datetime(job.heartbeat_at) if job.heartbeat_at else None,
            lease_version=job.lease_version,
        )
    )
    await db.flush()
    row = FeedbackDatasetSampleRow(
        sample_id=sample.sample_id, dataset_id=sample.dataset_id, source_case_id=sample.source_case_id,
        status="pending", generation=sample.generation, source_digest=sample.source_digest,
        active_job_id=job.job_id, missing_reasons=[],
        created_at=_datetime(sample.created_at), updated_at=_datetime(sample.updated_at),
    )
    db.add(row)
    await db.flush()
    return CollectedDatasetSample(
        DatasetSample(
            sample_id=row.sample_id,
            dataset_id=row.dataset_id,
            source_case_id=row.source_case_id,
            status=row.status,
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
        ),
        job,
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


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.isoformat()


__all__ = ['BuildCompletionKind', 'CollectedDatasetSample', 'ConfirmedDatasetMember', 'DatasetSampleRevisionConflict', 'DatasetSampleActionConflict', 'FeedbackDatasetSampleRepository']
