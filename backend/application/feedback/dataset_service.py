"""Application operations for maintained feedback datasets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from application.repositories.feedback_case_repository import FeedbackCaseRepository
from application.repositories.feedback_dataset_repository import (
    FeedbackDatasetRepository,
)
from application.repositories.feedback_dataset_sample_repository import (
    CollectedDatasetSample,
    FeedbackDatasetSampleRepository,
)
from domain.feedback.analysis_job import AnalysisJob
from domain.feedback.dataset_sample import (
    DATASET_SAMPLE_BUILD_JOB_TYPE,
    DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
    DatasetSample,
    build_job_payload,
    sample_build_idempotency_key,
    source_digest_for_case,
)
from application.source.collection_service import CollectionService
from domain.feedback.dataset import Dataset


class FeedbackDatasetError(ValueError):
    """A user-correctable dataset request."""


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
        if task_type != "sft":
            raise FeedbackDatasetError("dataset_task_type_not_available")
        cleaned_name = name.strip()
        if not cleaned_name:
            raise FeedbackDatasetError("dataset_name_required")
        _validate_public_spec(construction_spec)
        now = datetime.now(timezone.utc)
        dataset = Dataset(
            dataset_id=f"fdset_{uuid4().hex[:32]}",
            collection_id=collection_id,
            name=cleaned_name,
            task_type="sft",
            construction_spec=construction_spec,
            spec_version=1,
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        return await self.repository.create(dataset)

    async def list_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Dataset, ...]:
        await self.collection_service.get_collection_for_user(collection_id, user_id)
        if limit < 1 or limit > 200 or offset < 0:
            raise FeedbackDatasetError("pagination_invalid")
        return await self.repository.list_for_collection(
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )

    async def read_for_user(self, *, user_id: str, dataset_id: str) -> Dataset:
        dataset = await self.repository.read(dataset_id)
        if dataset is None:
            raise FileNotFoundError(f"dataset not found: {dataset_id}")
        await self.collection_service.get_collection_for_user(
            dataset.collection_id,
            user_id,
        )
        return dataset

    async def collect_cases_for_user(
        self,
        *,
        user_id: str,
        dataset_id: str,
        source_case_ids: tuple[str, ...],
    ) -> DatasetCollectionResult:
        """Freeze selected cases and enqueue one build job per new sample."""

        dataset = await self.read_for_user(user_id=user_id, dataset_id=dataset_id)
        if dataset.task_type != "sft":
            raise FeedbackDatasetError("dataset_task_type_not_available")
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
    "FeedbackDatasetError",
    "FeedbackDatasetService",
]
