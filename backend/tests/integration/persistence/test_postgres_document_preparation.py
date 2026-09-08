from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select

from application.source.collection_service import CollectionService
from application.source.document_preparation_service import (
    DocumentPreparationService,
)
from application.pipeline import PipelineRunService
from controllers.schemas.source.pipeline_run import PipelineRunResponse
from domain.core import DocumentProfile, PaperResearchMap
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
from infra.persistence.postgres.models.document_profile import DocumentProfileRow
from infra.persistence.postgres.pipeline_run_repository import (
    PostgresPipelineRunRepository,
)
from tests.integration.persistence.test_postgres_source_artifacts import COLLECTION_ID


pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

def _profile(document_id: str, title: str) -> DocumentProfile:
    return DocumentProfile.from_mapping(
        {
            "document_id": document_id,
            "title": title,
            "doc_type": "experimental",
            "profile_warnings": [],
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
            "input_fingerprint": f"input-{document_id}-{limitation or 'complete'}",
            "map_version": "paper-map.v1",
            "generated_at": "2026-09-08T09:00:00+00:00",
        }
    )


async def test_profiles_and_paper_maps_are_current_per_document(source_repository) -> None:
    profiles = PostgresDocumentProfileRepository(source_repository.session_factory)
    paper_maps = PostgresPaperMapRepository(source_repository.session_factory)
    first_profile = _profile("doc_a", "Paper A")
    second_profile = _profile("doc_b", "Paper B")
    first_map = _paper_map("doc_a")
    second_map = _paper_map("doc_b")

    await profiles.replace(COLLECTION_ID, first_profile)
    await profiles.replace(COLLECTION_ID, second_profile)
    await paper_maps.replace(COLLECTION_ID, first_map)
    await paper_maps.replace(COLLECTION_ID, second_map)

    revised_profile = replace(first_profile, title="Paper A reparsed")
    revised_map = _paper_map("doc_a", "methods_scope_missing")
    await profiles.replace(COLLECTION_ID, revised_profile)
    await paper_maps.replace(COLLECTION_ID, revised_map)

    assert await profiles.list_collection(COLLECTION_ID) == (
        revised_profile,
        second_profile,
    )
    assert await paper_maps.list_collection(COLLECTION_ID) == (
        revised_map,
        second_map,
    )
    async with source_repository.session_factory() as session:
        stored_map = await session.scalar(
            select(DocumentProfileRow).where(DocumentProfileRow.document_id == "doc_a")
        )
    assert stored_map.paper_map_payload["input_fingerprint"] == revised_map.input_fingerprint
    assert stored_map.paper_map_payload["map_version"] == revised_map.map_version
    assert stored_map.paper_map_payload["generated_at"] is not None
    assert stored_map.paper_map_payload["document_id"] == revised_map.document_id


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
    pipeline_run_service = PipelineRunService(
        PostgresPipelineRunRepository(source_repository.session_factory)
    )
    run, created = await pipeline_run_service.get_or_create_document_run(
        collection_id=COLLECTION_ID,
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="restart-input",
    )
    assert created is True
    await pipeline_run_service.update_run(run["run_id"], status="running")
    service = DocumentPreparationService(
        collection_service=collection_service,
        pipeline_run_service=pipeline_run_service,
        source_artifact_repository=MemorySourceArtifactRepository(),
        document_profile_service=object(),
        max_concurrency=1,
    )

    recovered = await service.recover_interrupted_runs()

    recovered_run = await pipeline_run_service.get_run(run["run_id"])
    assert recovered == 1
    assert recovered_run["status"] == "failed"
    assert recovered_run["current_node"] == "interrupted"
    assert PipelineRunResponse(**recovered_run).status == "failed"
    assert (await collection_service.get_document(COLLECTION_ID, "doc_a")).status == (
        "stored"
    )

    retry, retry_created = await pipeline_run_service.get_or_create_document_run(
        collection_id=COLLECTION_ID,
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="restart-input",
    )
    assert retry_created is True
    assert retry["run_id"] != run["run_id"]
