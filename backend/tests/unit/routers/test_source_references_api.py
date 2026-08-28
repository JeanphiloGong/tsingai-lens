from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from tests.support.collection_service import build_test_collection_service
from application.source.reference_workflow_service import (
    SourceReferenceWorkflowService,
)
from application.source.reference_extraction_service import (
    SourceReferenceExtractionService,
)
from controllers.source import references as references_controller
from domain.source import SourceBlock, SourceDocument, assemble_source_documents
from infra.persistence.memory import MemorySourceArtifactRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _store_source_documents(repository, collection_id, documents) -> None:
    for document in documents:
        await repository.replace_document(collection_id, document)


@pytest.fixture()
def source_reference_services(monkeypatch, tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    repository = MemorySourceArtifactRepository()
    workflow_service = SourceReferenceWorkflowService(
        source_artifact_repository=repository,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                collection_service=collection_service,
                reference_workflow_service=workflow_service,
            ),
        )
    )
    return collection_service, repository, request


async def test_source_reference_routes_build_and_read_refs(source_reference_services):
    collection_service, repository, request = source_reference_services
    collection = await collection_service.create_collection("Refs Collection")
    collection_id = collection["collection_id"]
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
    await _store_source_documents(
        repository,
        collection_id,
        artifacts,
    )
    await repository.replace_document_references(
        "doc-1",
        SourceReferenceExtractionService().extract(artifacts),
    )
    summary = await references_controller.build_collection_references(
        collection_id,
        request,
    )
    payload = await references_controller.get_collection_references(
        collection_id,
        request,
    )

    assert summary.collection_id == collection_id
    assert summary.entry_count == 1
    assert summary.candidate_count == 1
    assert payload.entry_count == 1
    assert payload.entries[0].reference_id == "ref-doc-1-0001"
    assert payload.mentions[0].reference_id == "ref-doc-1-0001"
    assert payload.candidates[0].status == "metadata_only"


async def test_source_reference_build_route_returns_409_when_source_is_not_ready(
    source_reference_services,
):
    collection_service, _repository, request = source_reference_services
    collection = await collection_service.create_collection("Pending Refs Collection")

    with pytest.raises(HTTPException) as exc_info:
        await references_controller.build_collection_references(
                collection["collection_id"],
                request,
            )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "source_artifacts_not_ready"
    assert exc.detail["collection_id"] == collection["collection_id"]


async def test_source_reference_route_returns_404_for_missing_collection(
    source_reference_services,
):
    _collection_service, _repository, request = source_reference_services
    with pytest.raises(HTTPException) as exc_info:
        await references_controller.get_collection_references(
            "col_missing",
            request,
        )

    assert exc_info.value.status_code == 404
