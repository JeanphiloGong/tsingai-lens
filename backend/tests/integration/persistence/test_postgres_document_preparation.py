from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from application.pipeline import pipeline_run_service
from application.source import collection_service, document_preparation_service
from controllers.schemas.source.pipeline_run import PipelineRunResponse
from domain.core import DocumentProfile, PaperResearchMap
from infra.persistence import database


from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)
from repositories.collection_repository import (
    CollectionRepository,
)
from repositories.document_profile_repository import (
    DocumentProfileRepository,
)
from repositories.paper_map_repository import PaperMapRepository
from repositories.pipeline_run_repository import (
    PipelineRunRepository,
)
from repositories.source_artifact_repository import SourceArtifactRepository
from sqlalchemy import select
from tests.integration.persistence.test_postgres_source_artifacts import (
    COLLECTION_ID,
    _source,
)
from tests.support.postgres import seed_collection

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio


def _profile(document_id: str, title: str) -> DocumentProfile:
    return DocumentProfile(
        document_id=document_id,
        title=title,
        doc_type="experimental",
        profile_warnings=(),
        confidence=0.9,
    )


def _paper_map(document_id: str, limitation: str = "") -> PaperResearchMap:
    return PaperResearchMap(
        document_id=document_id,
        doc_role="primary_experiment",
        studies=(),
        evidence_density="medium",
        confidence=0.8,
        warnings=(),
        map_status="insufficient_map" if limitation else "sufficient",
        map_limitations=tuple([limitation] if limitation else []),
        input_fingerprint=f"input-{document_id}-{limitation or 'complete'}",
        map_version="paper-map.v1",
        generated_at="2026-09-08T09:00:00+00:00",
    )


async def test_profiles_and_paper_maps_are_current_per_document(
    source_repository,
) -> None:
    profiles = DocumentProfileRepository()
    paper_maps = PaperMapRepository()
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
    async with database.AsyncSessionLocal() as session:
        stored_map = await session.scalar(
            select(DocumentPreparationRow).where(
                DocumentPreparationRow.document_id == "doc_a"
            )
        )
    assert (
        stored_map.paper_map_payload["input_fingerprint"]
        == revised_map.input_fingerprint
    )
    assert stored_map.paper_map_payload["map_version"] == revised_map.map_version
    assert stored_map.paper_map_payload["generated_at"] is not None
    assert stored_map.paper_map_payload["document_id"] == revised_map.document_id


async def test_profile_replacement_does_not_relabel_current_source(
    source_repository,
) -> None:
    profiles = DocumentProfileRepository()
    source = _source("doc_a", title="Current source")
    await seed_collection(
        database.AsyncSessionLocal, COLLECTION_ID, document_ids=(source.document_id,)
    )
    await source_repository.replace_document(COLLECTION_ID, source)
    async with database.AsyncSessionLocal() as session:
        row = await session.get(DocumentPreparationRow, "doc_a")
        current_fingerprint = row.source_fingerprint
    stale_profile = replace(
        _profile("doc_a", "Previous profile"), source_fingerprint="old-source"
    )
    await profiles.replace(COLLECTION_ID, stale_profile)
    collection_repository = CollectionRepository()
    collection = await collection_repository.read_collection(COLLECTION_ID)
    document = collection.documents[0]
    await collection_repository.update_document(
        replace(document, document=replace(document.document, status="processing"))
    )
    async with database.AsyncSessionLocal() as session:
        row = await session.get(DocumentPreparationRow, "doc_a")
        assert row.source_fingerprint == current_fingerprint
        assert row.profile_json["source_fingerprint"] == "old-source"
    assert await profiles.read(COLLECTION_ID, "doc_a") == stale_profile
    unknown_profile = _profile("doc_a", "Unversioned profile")
    await profiles.replace(COLLECTION_ID, unknown_profile)
    assert await profiles.read(COLLECTION_ID, "doc_a") == unknown_profile


async def test_profile_only_preparation_is_not_a_source(source_repository) -> None:
    profiles = DocumentProfileRepository()
    await profiles.replace(COLLECTION_ID, _profile("doc_a", "Imported profile"))
    assert await source_repository.read_document(COLLECTION_ID, "doc_a") is None
    assert await source_repository.read_collection_documents(COLLECTION_ID) == ()


async def test_paper_map_requires_a_profile_in_the_shared_row(
    source_repository,
) -> None:
    await source_repository.replace_document(
        COLLECTION_ID, _source("doc_a", title="Source only")
    )
    paper_maps = PaperMapRepository()
    with pytest.raises(FileNotFoundError, match="document profile not found"):
        await paper_maps.replace(COLLECTION_ID, _paper_map("doc_a"))


async def test_postgres_restart_recovery_is_retryable_and_api_readable(
    document_preparation_runtime,
    source_repository, tmp_path, *, postgres_session_factory
) -> None:
    collection_service.CollectionRepo = CollectionRepository()
    await collection_service.update_document_preparation(
        COLLECTION_ID,
        "doc_a",
        status="processing",
    )
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    run, created = await pipeline_run_service.get_or_create_document_run(
        collection_id=COLLECTION_ID,
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="restart-input",
    )
    assert created is True
    await pipeline_run_service.update_run(run["run_id"], status="running")
    document_preparation_service.collection_service = collection_service
    document_preparation_service.pipeline_run_service = pipeline_run_service
    document_preparation_service.SourceArtifactRepo = SourceArtifactRepository()
    document_preparation_service.document_profile_service = object()
    document_preparation_runtime._semaphore = asyncio.Semaphore(1)
    service = document_preparation_runtime

    recovered = await service.recover_interrupted_runs()

    recovered_run = await pipeline_run_service.get_run(
        run["run_id"], user_id="user_source"
    )
    assert recovered == 1
    assert recovered_run["status"] == "failed"
    assert recovered_run["current_node"] == "interrupted"
    assert PipelineRunResponse(**recovered_run).status == "failed"
    assert (
        await collection_service.get_document(COLLECTION_ID, "doc_a")
    ).document.status == ("stored")

    retry, retry_created = await pipeline_run_service.get_or_create_document_run(
        collection_id=COLLECTION_ID,
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="restart-input",
    )
    assert retry_created is True
    assert retry["run_id"] != run["run_id"]
