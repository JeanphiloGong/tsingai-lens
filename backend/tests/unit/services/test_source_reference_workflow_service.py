from __future__ import annotations

import pytest
from application.source import (
    reference_extraction_service as source_reference_extraction_service,
)
from application.source import reference_workflow_service
from domain.source import SourceBlock, SourceDocument, assemble_source_documents
from exceptions import ResourceConflictException, ResourceNotFoundException
from infra.persistence import database
from repositories.source_artifact_repository import SourceArtifactRepository
from tests.support.postgres import seed_collection

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _store_source_documents(repository, collection_id, documents) -> None:
    for document in documents:
        await seed_collection(
            database.AsyncSessionLocal,
            collection_id,
            document_ids=(document.document_id,),
        )
        await repository.replace_document(collection_id, document)


async def test_source_reference_workflow_builds_and_persists_refs(
    tmp_path, *, postgres_session_factory
):
    repository = SourceArtifactRepository()
    artifacts = assemble_source_documents(
        documents=(
            SourceDocument(
                document_id="doc-1",
                document_order=0,
                title="Paper",
                text="Prior work [1] matters.\nReferences\n[1] Smith A. Paper. Journal. 2024.",
            ),
        ),
        blocks=(
            SourceBlock(
                block_id="blk-body",
                document_id="doc-1",
                block_type="paragraph",
                text="Prior work [1] matters.",
                block_order=1,
            ),
            SourceBlock(
                block_id="blk-ref-heading",
                document_id="doc-1",
                block_type="heading",
                text="References",
                block_order=2,
            ),
            SourceBlock(
                block_id="blk-ref",
                document_id="doc-1",
                block_type="paragraph",
                text="[1] Smith A. Paper. Journal. 2024.",
                block_order=3,
            ),
        ),
    )
    await _store_source_documents(repository, "col_refs", artifacts)
    await repository.replace_document_references(
        "doc-1",
        source_reference_extraction_service.extract_source_references(artifacts),
    )
    reference_workflow_service.SourceArtifactRepo = repository
    service = reference_workflow_service

    result = await service.get_collection_references("col_refs", user_id="user-1")

    assert result.to_summary() == {
        "collection_id": "col_refs",
        "entry_count": 1,
        "mention_count": 1,
        "resolution_count": 0,
        "candidate_count": 1,
    }
    restored = await service.read_collection_references("col_refs", user_id="user-1")
    assert restored.references.entries[0].reference_id == "ref-doc-1-0001"
    assert restored.references.mentions[0].reference_id == "ref-doc-1-0001"
    assert restored.references.candidates[0].mention_count == 1


async def test_source_reference_workflow_requires_source_artifacts(
    tmp_path, *, postgres_session_factory
):
    repository = SourceArtifactRepository()
    reference_workflow_service.SourceArtifactRepo = repository
    service = reference_workflow_service

    await seed_collection(database.AsyncSessionLocal, "empty_collection")
    with pytest.raises(ResourceConflictException) as rejected:
        await service.get_collection_references("empty_collection", user_id="user-1")
    assert rejected.value.data["code"] == "source_artifacts_not_ready"


async def test_source_reference_workflow_rejects_missing_and_foreign_collections(
    postgres_session_factory,
):
    await seed_collection(database.AsyncSessionLocal, "foreign_collection")
    for collection_id in ("missing_collection", "foreign_collection"):
        with pytest.raises(ResourceNotFoundException):
            await reference_workflow_service.get_collection_references(
                collection_id,
                user_id="other-user",
            )
