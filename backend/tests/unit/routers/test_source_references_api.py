from __future__ import annotations
from application.source import collection_service

import json
from types import SimpleNamespace

import pytest
from infra.persistence import database
from tests.support.postgres import seed_collection

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.source import (
    reference_extraction_service as source_reference_extraction_service,
)
from application.source import reference_workflow_service
from controllers.source import reference_routes as references_controller
from domain.source import SourceBlock, SourceDocument, assemble_source_documents
from exceptions import ResourceConflictException, ResourceNotFoundException
from repositories.source_artifact_repository import SourceArtifactRepository

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


@pytest.fixture()
def source_reference_services(monkeypatch, tmp_path, *, postgres_session_factory):
    repository = SourceArtifactRepository()
    reference_workflow_service.SourceArtifactRepo = repository
    workflow_service = reference_workflow_service
    reference_workflow_service.collection_service = collection_service
    references_controller.reference_workflow_service = workflow_service
    request = SimpleNamespace(
        state=SimpleNamespace(current_user={"user_id": "local-user"})
    )
    return collection_service, repository, request


async def test_source_reference_routes_build_and_read_refs(
    source_reference_services,
    *,
    collection_workspace,
):
    collection_service, repository, request = source_reference_services
    collection = await collection_service.create_collection("Refs Collection", workspace=collection_workspace)
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
        source_reference_extraction_service.extract_source_references(artifacts),
    )
    summary = references_controller.SourceReferenceSummaryResponse.model_validate(
        json.loads(
            (
                await references_controller.build_collection_references(
                    collection_id=collection_id,
                    user_id=request.state.current_user["user_id"],
                )
            ).body
        )["data"]
    )
    payload = references_controller.SourceReferenceSetResponse.model_validate(
        json.loads(
            (
                await references_controller.get_collection_references(
                    collection_id=collection_id,
                    user_id=request.state.current_user["user_id"],
                )
            ).body
        )["data"]
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
    *,
    collection_workspace,
):
    collection_service, _repository, request = source_reference_services
    collection = await collection_service.create_collection("Pending Refs Collection", workspace=collection_workspace)

    with pytest.raises(ResourceConflictException) as exc_info:
        references_controller.SourceReferenceSummaryResponse.model_validate(
            json.loads(
                (
                    await references_controller.build_collection_references(
                        collection_id=collection["collection_id"],
                        user_id=request.state.current_user["user_id"],
                    )
                ).body
            )["data"]
        )

    exc = exc_info.value
    assert exc.code == 200204
    assert exc.data["code"] == "source_artifacts_not_ready"
    assert exc.data["collection_id"] == collection["collection_id"]


async def test_source_reference_route_returns_404_for_missing_collection(
    source_reference_services,
):
    _collection_service, _repository, request = source_reference_services
    with pytest.raises(ResourceNotFoundException) as exc_info:
        references_controller.SourceReferenceSetResponse.model_validate(
            json.loads(
                (
                    await references_controller.get_collection_references(
                        collection_id="col_missing",
                        user_id=request.state.current_user["user_id"],
                    )
                ).body
            )["data"]
        )

    assert exc_info.value.code == 200201
