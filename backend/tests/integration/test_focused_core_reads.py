from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from application.core.workspace_overview_service import WorkspaceService
from domain.source import assemble_source_documents
from tests.support.objective_repository import MemoryObjectiveRepository


COLLECTION_ID = "col-focused"
pytestmark = pytest.mark.anyio


async def test_workspace_reads_only_maintained_collection_readiness():
    source_repository = Mock()
    source_repository.read_collection_documents = AsyncMock(return_value=(
        assemble_source_documents()
    ))
    collection_service = Mock()
    collection_service.get_collection = AsyncMock(
        return_value={
            "collection_id": COLLECTION_ID,
            "updated_at": "2026-07-20T00:00:00Z",
        }
    )
    collection_service.list_files = AsyncMock(
        return_value=[{"filename": "paper.pdf"}]
    )
    task_service = Mock()
    task_service.list_tasks = AsyncMock(return_value=[])
    document_profile_service = Mock()
    document_profile_service.get_document_summary = AsyncMock(
        return_value={
            "total_documents": 1,
            "by_doc_type": {"experimental": 1},
            "warnings": [],
        }
    )
    service = WorkspaceService(
        collection_service=collection_service,
        task_service=task_service,
        source_artifact_repository=source_repository,
        objective_repository=MemoryObjectiveRepository(),
        document_profile_service=document_profile_service,
    )

    payload = await service.get_workspace_overview(COLLECTION_ID)

    assert payload["artifacts"] == {
        "source_documents_ready": False,
        "document_profiles_ready": True,
        "objective_candidates_ready": False,
        "updated_at": "2026-07-20T00:00:00Z",
    }
