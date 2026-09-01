from __future__ import annotations

from dataclasses import replace

import pytest

from application.source.collection_service import CollectionService
from application.source.document_preparation_service import (
    DocumentPreparationService,
)
from application.source.task_service import TaskService
from controllers.schemas.source.task import TaskResponse
from domain.core import DocumentProfile, PaperResearchMap
from domain.source import TaskRecord
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.memory import (
    MemoryPaperMapRepository,
    MemorySourceArtifactRepository,
)
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from infra.persistence.postgres.document_profile_repository import (
    PostgresDocumentProfileRepository,
)
from infra.persistence.postgres.paper_map_repository import PostgresPaperMapRepository
from infra.persistence.postgres.task_repository import PostgresTaskRepository
from tests.integration.persistence.test_postgres_source_artifacts import COLLECTION_ID


pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

NOW = "2026-08-27T10:00:00+00:00"


def _profile(document_id: str, title: str) -> DocumentProfile:
    return DocumentProfile.from_mapping(
        {
            "document_id": document_id,
            "collection_id": COLLECTION_ID,
            "title": title,
            "source_filename": f"{document_id}.pdf",
            "doc_type": "experimental",
            "parsing_warnings": [],
            "confidence": 0.9,
        }
    )


def _paper_map(document_id: str, limitation: str = "") -> PaperResearchMap:
    return PaperResearchMap.from_mapping(
        {
            "document_id": document_id,
            "doc_role": "primary_experiment",
            "studies": [],
            "evidence_density": "medium",
            "confidence": 0.8,
            "warnings": [],
            "map_status": "insufficient_map" if limitation else "sufficient",
            "map_limitations": [limitation] if limitation else [],
        }
    )


def _task(task_id: str, fingerprint: str) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        collection_id=COLLECTION_ID,
        document_id="doc_a",
        task_type="document_preparation",
        mode="standard",
        input_fingerprint=fingerprint,
        status="queued",
        current_stage="queued",
        progress_percent=0,
        progress_detail=None,
        output_path=None,
        errors=(),
        warnings=(),
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        finished_at=None,
    )


def _collection_task(task_id: str, fingerprint: str) -> TaskRecord:
    return replace(
        _task(task_id, fingerprint),
        document_id=None,
        task_type="objective_discovery",
        details={"document_ids": ["doc_a", "doc_b"]},
    )


async def test_profiles_and_paper_maps_are_current_per_document(source_repository) -> None:
    profiles = PostgresDocumentProfileRepository(source_repository.session_factory)
    paper_maps = PostgresPaperMapRepository(source_repository.session_factory)
    first_profile = _profile("doc_a", "Paper A")
    second_profile = _profile("doc_b", "Paper B")
    first_map = _paper_map("doc_a")
    second_map = _paper_map("doc_b")

    await profiles.replace(first_profile)
    await profiles.replace(second_profile)
    await paper_maps.replace(COLLECTION_ID, first_map)
    await paper_maps.replace(COLLECTION_ID, second_map)

    revised_profile = replace(first_profile, title="Paper A reparsed")
    revised_map = _paper_map("doc_a", "methods_scope_missing")
    await profiles.replace(revised_profile)
    await paper_maps.replace(COLLECTION_ID, revised_map)

    assert await profiles.list_collection(COLLECTION_ID) == (
        revised_profile,
        second_profile,
    )
    assert await paper_maps.list_collection(COLLECTION_ID) == (
        revised_map,
        second_map,
    )


async def test_document_task_reuses_active_and_matching_completed_work(
    source_repository,
) -> None:
    tasks = PostgresTaskRepository(source_repository.session_factory)
    first = _task("task-first", "fingerprint-a")
    stored, created = await tasks.get_or_create_document_task(first)
    assert (stored, created) == (first, True)

    active_request = _task("task-active-request", "fingerprint-b")
    reused_active, created = await tasks.get_or_create_document_task(active_request)
    assert (reused_active, created) == (first, False)

    completed = replace(
        first,
        status="completed",
        current_stage="completed",
        progress_percent=100,
        updated_at="2026-08-27T10:01:00+00:00",
        started_at=NOW,
        finished_at="2026-08-27T10:01:00+00:00",
    )
    assert await tasks.update_task(completed) is True

    matching_request = _task("task-matching-request", "fingerprint-a")
    reused_completed, created = await tasks.get_or_create_document_task(
        matching_request
    )
    assert (reused_completed, created) == (completed, False)

    changed_request = _task("task-changed-request", "fingerprint-b")
    created_task, created = await tasks.get_or_create_document_task(changed_request)
    assert (created_task, created) == (changed_request, True)


async def test_collection_task_reuses_only_active_discovery_work(
    source_repository,
) -> None:
    tasks = PostgresTaskRepository(source_repository.session_factory)
    first = _collection_task("task-discovery-first", "scope-a")
    stored, created = await tasks.get_or_create_collection_task(first)
    assert (stored, created) == (first, True)

    active_request = _collection_task("task-discovery-duplicate", "scope-b")
    reused_active, created = await tasks.get_or_create_collection_task(
        active_request
    )
    assert (reused_active, created) == (first, False)

    completed = replace(
        first,
        status="completed",
        current_stage="objectives_ready",
        progress_percent=100,
        updated_at="2026-08-27T10:01:00+00:00",
        started_at=NOW,
        finished_at="2026-08-27T10:01:00+00:00",
    )
    assert await tasks.update_task(completed) is True

    retry = _collection_task("task-discovery-retry", "scope-b")
    created_task, created = await tasks.get_or_create_collection_task(retry)
    assert (created_task, created) == (retry, True)


async def test_postgres_restart_recovery_is_retryable_and_api_readable(
    source_repository,
    tmp_path,
) -> None:
    collection_service = CollectionService(
        PostgresCollectionRepository(source_repository.session_factory),
        FileCollectionWorkspace(tmp_path / "collections"),
    )
    await collection_service.update_document_preparation(
        COLLECTION_ID,
        "doc_a",
        status="processing",
    )
    task_service = TaskService(
        PostgresTaskRepository(source_repository.session_factory)
    )
    task, created = await task_service.get_or_create_document_task(
        collection_id=COLLECTION_ID,
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="restart-input",
    )
    assert created is True
    await task_service.update_task(task["task_id"], status="running")
    service = DocumentPreparationService(
        collection_service=collection_service,
        task_service=task_service,
        source_artifact_repository=MemorySourceArtifactRepository(),
        document_profile_service=object(),
        max_concurrency=1,
    )

    recovered = await service.recover_interrupted_tasks()

    recovered_task = await task_service.get_task(task["task_id"])
    assert recovered == 1
    assert recovered_task["status"] == "failed"
    assert recovered_task["current_stage"] == "interrupted"
    assert TaskResponse(**recovered_task).status == "failed"
    assert (await collection_service.get_document(COLLECTION_ID, "doc_a")).status == (
        "stored"
    )

    retry, retry_created = await task_service.get_or_create_document_task(
        collection_id=COLLECTION_ID,
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="restart-input",
    )
    assert retry_created is True
    assert retry["task_id"] != task["task_id"]
