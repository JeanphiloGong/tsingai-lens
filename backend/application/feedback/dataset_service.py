"""Application operations for maintained feedback datasets."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, cast
from uuid import uuid4

from application.repositories.analysis_job_repository import AnalysisJob
from application.repositories.feedback_case_repository import FeedbackCaseRepository
from application.repositories.feedback_dataset_repository import (
    FeedbackDatasetRepository,
    StoredDataset,
)
from application.repositories.feedback_dataset_sample_repository import (
    DATASET_SAMPLE_BUILD_JOB_TYPE,
    DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
    CollectedDatasetSample,
    DatasetSampleActionConflict,
    DatasetSampleRevisionConflict,
    FeedbackDatasetSampleRepository,
    build_job_payload,
    sample_action_digest,
    sample_build_idempotency_key,
    source_digest_for_case,
)
from application.source.collection_service import CollectionService
from domain.feedback.dataset import DATASET_TASK_TYPES, Dataset, DatasetTaskType
from domain.feedback.dataset_sample import DatasetSample, SampleAction
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.sample_revision import (
    SampleRevision,
    content_digest_for,
    parse_revision_content,
    sanitize_revision_content_mapping,
)


class FeedbackDatasetError(ValueError):
    """A user-correctable dataset request."""


class FeedbackDatasetConflict(FeedbackDatasetError):
    """A mutable sample changed after the caller read it."""


@dataclass(frozen=True)
class DatasetSampleListResult:
    items: tuple[DatasetSample, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class DatasetSampleDetail:
    dataset: Dataset
    sample: DatasetSample
    current_revision: SampleRevision | None
    confirmed_revision: SampleRevision | None
    source_case: FeedbackCase


class DatasetCollectionResult:
    """The durable result of explicitly collecting source cases."""

    def __init__(self, *, operation_id: str, items: tuple[CollectedDatasetSample, ...]) -> None:
        self.operation_id = operation_id
        self.items = items

    @property
    def created_count(self) -> int:
        return sum(item.job is not None for item in self.items)

    @property
    def existing_count(self) -> int:
        return len(self.items) - self.created_count


_FORBIDDEN_SPEC_KEYS = frozenset({"api_key", "token", "password", "secret", "credential"})


class FeedbackDatasetService:
    def __init__(
        self,
        *,
        repository: FeedbackDatasetRepository,
        collection_service: CollectionService,
        sample_repository: FeedbackDatasetSampleRepository | None = None,
        case_repository: FeedbackCaseRepository | None = None,
    ) -> None:
        self.repository = repository
        self.collection_service = collection_service
        self.sample_repository = sample_repository
        self.case_repository = case_repository

    async def create_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        name: str,
        task_type: str,
        construction_spec: dict[str, Any],
    ) -> Dataset:
        await self.collection_service.get_collection_for_user(collection_id, user_id)
        if task_type not in DATASET_TASK_TYPES:
            raise FeedbackDatasetError("dataset_task_type_not_available")
        cleaned_name = name.strip()
        if not cleaned_name:
            raise FeedbackDatasetError("dataset_name_required")
        if len(cleaned_name) > 120:
            raise FeedbackDatasetError("dataset_name_too_long")
        if not user_id or not collection_id:
            raise FeedbackDatasetError("dataset_identity_required")
        _validate_public_spec(construction_spec)
        dataset = Dataset(
            dataset_id=f"fdset_{uuid4().hex[:32]}",
            collection_id=collection_id,
            name=cleaned_name,
            task_type=cast(DatasetTaskType, task_type),
            construction_spec=deepcopy(construction_spec),
            spec_version=1,
            created_by=user_id,
        )
        return await self.repository.create(dataset)

    async def read_for_user(self, *, user_id: str, dataset_id: str) -> Dataset:
        dataset = await self.repository.read(dataset_id)
        if dataset is None:
            raise FileNotFoundError(f"dataset not found: {dataset_id}")
        await self.collection_service.get_collection_for_user(
            dataset.collection_id,
            user_id,
        )
        return dataset

    async def read_record_for_user(
        self, *, user_id: str, dataset_id: str
    ) -> StoredDataset:
        record = await self.repository.read_record(dataset_id)
        if record is None:
            raise FileNotFoundError(f"dataset not found: {dataset_id}")
        await self.collection_service.get_collection_for_user(
            record.dataset.collection_id, user_id
        )
        return record

    async def list_records_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[StoredDataset, ...]:
        if limit < 1 or limit > 200 or offset < 0:
            raise FeedbackDatasetError("pagination_invalid")
        await self.ensure_system_workbench_for_user(
            user_id=user_id,
            collection_id=collection_id,
            backfill_existing_cases=True,
        )
        return await self.repository.list_records_for_collection(
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )

    async def ensure_system_workbench_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        backfill_existing_cases: bool,
    ) -> tuple[Dataset, ...]:
        """Return the three fixed Collection workbenches and queue their cases.

        Dataset records are an internal persistence detail of the workbench;
        users choose a task type, never a Dataset definition.  The first page
        visit also backfills cases created before the automatic pipeline was
        enabled, so an empty task page cannot be caused by an old case.
        """

        collection = await self.collection_service.get_collection_for_user(
            collection_id, user_id
        )
        ensure = getattr(self.repository, "ensure_system_datasets", None)
        if not callable(ensure):
            return ()
        datasets = tuple(
            await ensure(
                collection_id=collection_id,
                owner_user_id=str(collection["owner_user_id"]),
            )
        )
        if not backfill_existing_cases or self.sample_repository is None or self.case_repository is None:
            return datasets

        case_ids: list[str] = []
        offset = 0
        while True:
            batch = await self.case_repository.list_cases(
                collection_id=collection_id, limit=200, offset=offset
            )
            case_ids.extend(case.case_id for case in batch)
            if len(batch) < 200:
                break
            offset += len(batch)
        for dataset in datasets:
            for start in range(0, len(case_ids), 1000):
                if case_ids[start : start + 1000]:
                    await self.collect_cases_for_user(
                        user_id=user_id,
                        dataset_id=dataset.dataset_id,
                        source_case_ids=tuple(case_ids[start : start + 1000]),
                    )
        return datasets

    async def enqueue_case_samples(self, *, collection_id: str, case_id: str) -> None:
        """Queue one sample build for each fixed task type after case creation."""

        if self.sample_repository is None or self.case_repository is None:
            return
        collection = await self.collection_service.get_collection(collection_id)
        datasets = await self.ensure_system_workbench_for_user(
            user_id=str(collection["owner_user_id"]),
            collection_id=collection_id,
            backfill_existing_cases=False,
        )
        for dataset in datasets:
            await self.collect_cases_for_user(
                user_id=str(collection["owner_user_id"]),
                dataset_id=dataset.dataset_id,
                source_case_ids=(case_id,),
            )

    async def collect_cases_for_user(
        self,
        *,
        user_id: str,
        dataset_id: str,
        source_case_ids: tuple[str, ...],
    ) -> DatasetCollectionResult:
        """Freeze selected cases and enqueue one build job per new sample."""

        dataset = await self.read_for_user(user_id=user_id, dataset_id=dataset_id)
        if self.sample_repository is None or self.case_repository is None:
            raise FeedbackDatasetError("dataset_samples_unavailable")
        case_ids = tuple(dict.fromkeys(str(item).strip() for item in source_case_ids if str(item).strip()))
        if not case_ids:
            raise FeedbackDatasetError("source_case_ids_required")
        if len(case_ids) > 1000:
            raise FeedbackDatasetError("source_case_selection_too_large")

        now = datetime.now(timezone.utc).isoformat()
        samples: list[DatasetSample] = []
        jobs: list[AnalysisJob] = []
        for case_id in case_ids:
            case = await self.case_repository.read_case(case_id)
            if case is None or case.collection_id != dataset.collection_id:
                raise FileNotFoundError(f"feedback case not found: {case_id}")
            if case.status == "withdrawn":
                raise FeedbackDatasetError("source_case_withdrawn")
            source_digest = source_digest_for_case(case.to_record())
            sample_id = f"sample_{uuid4().hex[:32]}"
            generation = 1
            job_id = f"job_{uuid4().hex[:32]}"
            idempotency_key = sample_build_idempotency_key(
                sample_id=sample_id,
                generation=generation,
                spec_version=dataset.spec_version,
                source_digest=source_digest,
            )
            samples.append(
                DatasetSample.pending(
                    sample_id=sample_id,
                    dataset_id=dataset.dataset_id,
                    source_case_id=case_id,
                    source_digest=source_digest,
                    active_job_id=job_id,
                    now=now,
                )
            )
            jobs.append(
                AnalysisJob(
                    job_id=job_id,
                    job_type=DATASET_SAMPLE_BUILD_JOB_TYPE,
                    payload_version=DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
                    payload=build_job_payload(
                        dataset_id=dataset.dataset_id,
                        sample_id=sample_id,
                        generation=generation,
                        spec_version=dataset.spec_version,
                        source_digest=source_digest,
                    ),
                    status="pending",
                    idempotency_key=idempotency_key,
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        collected = await self.sample_repository.collect(
            samples=tuple(samples),
            jobs=tuple(jobs),
        )
        return DatasetCollectionResult(
            operation_id=f"collect_{uuid4().hex[:24]}",
            items=collected,
        )

    async def list_samples_for_user(
        self,
        *,
        user_id: str,
        dataset_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DatasetSampleListResult:
        dataset = await self.read_for_user(user_id=user_id, dataset_id=dataset_id)
        self._require_supported(dataset)
        repository = self._sample_repository()
        if limit < 1 or limit > 200 or offset < 0:
            raise FeedbackDatasetError("pagination_invalid")
        allowed_statuses = {
            "pending",
            "building",
            "needs_confirmation",
            "needs_input",
            "confirmed",
            "discarded",
            "build_failed",
        }
        if status is not None and status not in allowed_statuses:
            raise FeedbackDatasetError("sample_status_invalid")
        items = await repository.list_samples(
            dataset_id=dataset_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await repository.count_samples(dataset_id=dataset_id, status=status)
        return DatasetSampleListResult(items=items, total=total, limit=limit, offset=offset)

    async def read_sample_for_user(
        self, *, user_id: str, dataset_id: str, sample_id: str
    ) -> DatasetSampleDetail:
        dataset = await self.read_for_user(user_id=user_id, dataset_id=dataset_id)
        self._require_supported(dataset)
        repository = self._sample_repository()
        sample = await repository.read_sample(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise FileNotFoundError(f"dataset sample not found: {sample_id}")
        current_revision = await self._read_related_revision(
            repository, sample.current_revision_id, sample_id, "sample_current_revision_missing"
        )
        confirmed_revision = await self._read_related_revision(
            repository,
            sample.confirmed_revision_id,
            sample_id,
            "sample_confirmed_revision_missing",
        )
        case_repository = self._case_repository()
        source_case = await case_repository.read_case(sample.source_case_id)
        if source_case is None or source_case.collection_id != dataset.collection_id:
            raise FeedbackDatasetError("sample_source_case_missing")
        return DatasetSampleDetail(
            dataset=dataset,
            sample=sample,
            current_revision=current_revision,
            confirmed_revision=confirmed_revision,
            source_case=source_case,
        )

    async def update_sample(
        self,
        *,
        user_id: str,
        dataset_id: str,
        sample_id: str,
        expected_revision_id: str | None,
        content: dict[str, Any],
        expected_generation: int | None = None,
    ) -> DatasetSample:
        dataset = await self.read_for_user(user_id=user_id, dataset_id=dataset_id)
        self._require_supported(dataset)
        repository = self._sample_repository()
        sample = await repository.read_sample(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise FileNotFoundError(f"dataset sample not found: {sample_id}")
        if sample.current_revision_id != expected_revision_id:
            raise FeedbackDatasetConflict("sample_revision_stale")
        if expected_generation is not None and sample.generation != expected_generation:
            raise FeedbackDatasetConflict("sample_revision_stale")
        if sample.status not in {"needs_input", "needs_confirmation", "confirmed"}:
            raise FeedbackDatasetError("sample_not_editable")
        if expected_revision_id is None and expected_generation is None:
            raise FeedbackDatasetError("sample_generation_required")
        current = await repository.read_revision(expected_revision_id) if expected_revision_id else None
        if expected_revision_id and (current is None or current.sample_id != sample_id):
            raise FeedbackDatasetError("sample_current_revision_missing")
        try:
            parsed = parse_revision_content(sanitize_revision_content_mapping(content))
        except ValueError as exc:
            raise FeedbackDatasetError(str(exc)) from exc
        if parsed.schema_version != _schema_for_task(dataset.task_type):
            raise FeedbackDatasetError("sample_content_task_type_mismatch")
        case = await self._case_repository().read_case(sample.source_case_id)
        if case is None or case.collection_id != dataset.collection_id:
            raise FeedbackDatasetError("sample_source_case_missing")
        if case.status == "withdrawn":
            raise FeedbackDatasetError("sample_source_case_withdrawn")
        if source_digest_for_case(case.to_record()) != sample.source_digest:
            raise FeedbackDatasetConflict("sample_source_stale")
        snapshot = case.context_snapshot
        prior_provenance = current.provenance if current else {}
        source_records = [
            *prior_provenance.get("evidence_records", []),
            *snapshot.get("inspected_sources", []),
            *snapshot.get("requested_scope", []),
        ]
        # Bind edited excerpts to exact known text, never retain an old source
        # identity for replacement text supplied by the annotator.
        evidence_records = []
        for item in parsed.evidence:
            original = next((record for record in source_records if isinstance(record, Mapping)
                and str(record.get("document_title") or record.get("title") or "").strip() == item["document_title"]
                and str(record.get("quote") or record.get("text") or record.get("content") or "").strip() == item["text"]), None)
            evidence_records.append({
                **(dict(original) if original else {}),
                "document_title": item["document_title"], "quote": item["text"],
                "audit_basis": "human_selected_case_evidence" if original else "human_supplied_excerpt",
                "annotated_by": user_id,
            })
        provenance = {
            **prior_provenance,
            "collection_id": dataset.collection_id, "source_case_id": case.case_id,
            "session_id": case.session_id, "anchor_message_id": case.anchor_message_id,
            "corrected_message_id": snapshot.get("corrected_message_id"),
            "evidence_records": evidence_records,
            "source_refs": list(dict.fromkeys(str(item.get("source_ref") or item.get("table_ref"))
                for item in evidence_records if item.get("source_ref") or item.get("table_ref"))),
            "edited_from_revision_id": current.revision_id if current else None,
            "edited_by": user_id,
        }
        now = datetime.now(timezone.utc).isoformat()
        revision = SampleRevision(
            revision_id=f"revision_{uuid4().hex[:32]}",
            sample_id=sample_id,
            revision_no=current.revision_no + 1 if current else 1,
            author_kind="human",
            content=parsed,
            content_digest=content_digest_for(parsed),
            input_digest=sample.source_digest,
            construction_spec_version=dataset.spec_version,
            provenance=provenance,
            created_at=now,
            created_by=user_id,
            job_id=None,
        )
        try:
            return await repository.append_human_revision(
                sample_id=sample_id,
                expected_revision_id=expected_revision_id,
                expected_generation=sample.generation,
                expected_source_digest=sample.source_digest,
                revision=revision,
                updated_at=now,
            )
        except DatasetSampleRevisionConflict as exc:
            raise FeedbackDatasetConflict(str(exc)) from exc

    async def confirm_sample(
        self,
        *,
        user_id: str,
        dataset_id: str,
        sample_id: str,
        expected_revision_id: str,
    ) -> DatasetSample:
        dataset = await self.read_for_user(user_id=user_id, dataset_id=dataset_id)
        self._require_supported(dataset)
        repository = self._sample_repository()
        sample = await repository.read_sample(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise FileNotFoundError(f"dataset sample not found: {sample_id}")
        if sample.current_revision_id != expected_revision_id:
            raise FeedbackDatasetConflict("sample_revision_stale")
        revision = await repository.read_revision(expected_revision_id)
        if revision is None or revision.sample_id != sample_id:
            raise FeedbackDatasetError("sample_current_revision_missing")
        if revision.content.schema_version != _schema_for_task(dataset.task_type):
            raise FeedbackDatasetError("sample_content_invalid")
        case = await self._case_repository().read_case(sample.source_case_id)
        if case is None or case.collection_id != dataset.collection_id:
            raise FeedbackDatasetError("sample_source_case_missing")
        if case.status == "withdrawn":
            raise FeedbackDatasetError("sample_source_case_withdrawn")
        if source_digest_for_case(case.to_record()) != sample.source_digest:
            raise FeedbackDatasetConflict("sample_source_stale")
        now = datetime.now(timezone.utc).isoformat()
        try:
            return await repository.confirm_revision(
                sample_id=sample_id,
                expected_revision_id=expected_revision_id,
                expected_source_digest=sample.source_digest,
                confirmed_by=user_id,
                confirmed_at=now,
            )
        except DatasetSampleRevisionConflict as exc:
            raise FeedbackDatasetConflict(str(exc)) from exc

    async def apply_sample_action_for_user(
        self,
        *,
        user_id: str,
        dataset_id: str,
        sample_id: str,
        action: SampleAction,
        expected_revision_id: str | None,
        reason: str | None,
        idempotency_key: str,
    ) -> DatasetSample:
        dataset = await self.read_for_user(user_id=user_id, dataset_id=dataset_id)
        self._require_supported(dataset)
        repository = self._sample_repository()
        sample = await repository.read_sample(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise FileNotFoundError(f"dataset sample not found: {sample_id}")
        if action not in {"rebuild", "retry", "discard", "restore"}:
            raise FeedbackDatasetError("sample_action_invalid")
        cleaned_reason = (reason or "").strip() or None
        if action == "rebuild" and not cleaned_reason:
            raise FeedbackDatasetError("sample_rebuild_reason_required")
        if cleaned_reason and len(cleaned_reason) > 2000:
            raise FeedbackDatasetError("sample_action_reason_too_long")
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise FeedbackDatasetError("sample_action_key_invalid")

        now = datetime.now(timezone.utc).isoformat()
        source_digest: str | None = None
        if action in {"rebuild", "retry", "restore"}:
            case = await self._case_repository().read_case(sample.source_case_id)
            if case is None or case.collection_id != dataset.collection_id:
                raise FeedbackDatasetError("sample_source_case_missing")
            if case.status == "withdrawn":
                raise FeedbackDatasetError("sample_source_case_withdrawn")
            source_digest = source_digest_for_case(case.to_record())

        job: AnalysisJob | None = None
        if action in {"rebuild", "retry"}:
            assert source_digest is not None
            generation = sample.generation + 1
            payload = build_job_payload(
                dataset_id=dataset_id,
                sample_id=sample_id,
                generation=generation,
                spec_version=dataset.spec_version,
                source_digest=source_digest,
            )
            if cleaned_reason:
                payload["review_note"] = cleaned_reason
            job = AnalysisJob(
                job_id=f"job_{uuid4().hex[:32]}",
                job_type=DATASET_SAMPLE_BUILD_JOB_TYPE,
                payload_version=DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
                payload=payload,
                status="pending",
                idempotency_key=sample_build_idempotency_key(
                    sample_id=sample_id,
                    generation=generation,
                    spec_version=dataset.spec_version,
                    source_digest=source_digest,
                ),
                available_at=now,
                created_at=now,
                updated_at=now,
            )
        try:
            return await repository.apply_action(
                dataset_id=dataset_id,
                sample_id=sample_id,
                expected_revision_id=expected_revision_id,
                expected_generation=sample.generation,
                action=action,
                reason=cleaned_reason,
                actor_id=user_id,
                idempotency_key=idempotency_key,
                request_digest=sample_action_digest(
                    action=action,
                    expected_revision_id=expected_revision_id,
                    reason=cleaned_reason,
                ),
                source_digest=source_digest,
                job=job,
                now=now,
            )
        except DatasetSampleActionConflict as exc:
            raise FeedbackDatasetConflict(str(exc)) from exc
        except ValueError as exc:
            raise FeedbackDatasetError(str(exc)) from exc

    async def _read_related_revision(
        self,
        repository: FeedbackDatasetSampleRepository,
        revision_id: str | None,
        sample_id: str,
        missing_code: str,
    ) -> SampleRevision | None:
        if not revision_id:
            return None
        revision = await repository.read_revision(revision_id)
        if revision is None or revision.sample_id != sample_id:
            raise FeedbackDatasetError(missing_code)
        return revision

    def _sample_repository(self) -> FeedbackDatasetSampleRepository:
        if self.sample_repository is None:
            raise FeedbackDatasetError("dataset_samples_unavailable")
        return self.sample_repository

    def _case_repository(self) -> FeedbackCaseRepository:
        if self.case_repository is None:
            raise FeedbackDatasetError("dataset_samples_unavailable")
        return self.case_repository

    @staticmethod
    def _require_supported(dataset: Dataset) -> None:
        if dataset.task_type not in DATASET_TASK_TYPES:
            raise FeedbackDatasetError("dataset_task_type_not_available")


def _schema_for_task(task_type: DatasetTaskType) -> str:
    return {
        "sft": "literature-sft.v1",
        "preference": "literature-preference.v1",
        "evaluation": "literature-evaluation.v1",
    }[task_type]


def _validate_public_spec(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise FeedbackDatasetError("construction_spec_invalid")

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).lower() in _FORBIDDEN_SPEC_KEYS:
                    raise FeedbackDatasetError("construction_spec_contains_credential")
                walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)


__all__ = [
    "DatasetCollectionResult",
    "DatasetSampleDetail",
    "DatasetSampleListResult",
    "FeedbackDatasetConflict",
    "FeedbackDatasetError",
    "FeedbackDatasetService",
]
