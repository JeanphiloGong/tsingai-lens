from __future__ import annotations
from application.source import workspace_service

import json
from types import SimpleNamespace

import pytest
from infra.persistence import database
from tests.support.postgres import seed_workspace

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.source import (
    reference_extraction_service as source_reference_extraction_service,
)
from application.source import reference_workflow_service
from controllers.source import reference_routes as references_controller
from document.domain.source import SourceBlock, SourceDocument, assemble_source_documents
from exceptions import ResourceConflictException, ResourceNotFoundException
from document.repositories.source_repository import SourceRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _store_source_documents(repository, workspace_id, documents) -> None:
    for document in documents:
        await seed_workspace(
            database.AsyncSessionLocal,
            workspace_id,
            document_ids=(document.document_id,),
        )
        await repository.replace_document(workspace_id, document)


@pytest.fixture()
def source_reference_services(monkeypatch, tmp_path, *, postgres_session_factory):
    repository = SourceRepository()
    reference_workflow_service.SourceRepo = repository
    workflow_service = reference_workflow_service
    reference_workflow_service.workspace_service = workspace_service
    references_controller.reference_workflow_service = workflow_service
    request = SimpleNamespace(
        state=SimpleNamespace(current_user={"user_id": "local-user"})
    )
    return workspace_service, repository, request


async def test_source_reference_routes_build_and_read_refs(
    source_reference_services,
    *,
    workspace_files,
):
    workspace_service, repository, request = source_reference_services
    workspace = await workspace_service.create_workspace("Refs Workspace")
    workspace_id = workspace.workspace.workspace_id
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
        workspace_id,
        artifacts,
    )
    await repository.replace_document_references(
        "doc-1",
        source_reference_extraction_service.extract_source_references(artifacts),
    )
    summary = references_controller.SourceReferenceSummaryResponse.model_validate(
        json.loads(
            (
                await references_controller.build_workspace_references(
                    workspace_id=workspace_id,
                    user_id=request.state.current_user["user_id"],
                )
            ).body
        )["data"]
    )
    payload = references_controller.SourceReferenceSetResponse.model_validate(
        json.loads(
            (
                await references_controller.get_workspace_references(
                    workspace_id=workspace_id,
                    user_id=request.state.current_user["user_id"],
                )
            ).body
        )["data"]
    )

    assert summary.workspace_id == workspace_id
    assert summary.entry_count == 1
    assert summary.candidate_count == 1
    assert payload.entry_count == 1
    assert payload.entries[0].reference_id == "ref-doc-1-0001"
    assert payload.mentions[0].reference_id == "ref-doc-1-0001"
    assert payload.candidates[0].status == "metadata_only"


async def test_source_reference_build_route_returns_409_when_source_is_not_ready(
    source_reference_services,
    *,
    workspace_files,
):
    workspace_service, _repository, request = source_reference_services
    workspace = await workspace_service.create_workspace("Pending Refs Workspace")

    with pytest.raises(ResourceConflictException) as exc_info:
        references_controller.SourceReferenceSummaryResponse.model_validate(
            json.loads(
                (
                    await references_controller.build_workspace_references(
                        workspace_id=workspace.workspace.workspace_id,
                        user_id=request.state.current_user["user_id"],
                    )
                ).body
            )["data"]
        )

    exc = exc_info.value
    assert exc.code == 200204
    assert exc.data["code"] == "source_artifacts_not_ready"
    assert exc.data["workspace_id"] == workspace.workspace.workspace_id


async def test_source_reference_route_returns_404_for_missing_workspace(
    source_reference_services,
):
    _workspace_service, _repository, request = source_reference_services
    with pytest.raises(ResourceNotFoundException) as exc_info:
        references_controller.SourceReferenceSetResponse.model_validate(
            json.loads(
                (
                    await references_controller.get_workspace_references(
                        workspace_id="col_missing",
                        user_id=request.state.current_user["user_id"],
                    )
                ).body
            )["data"]
        )

    assert exc_info.value.code == 200201
