from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from application.core.workspace_overview_service import WorkspaceService
from domain.core import ObjectiveFactSet
from tests.support.objective_repository import MemoryObjectiveRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _service(
    *,
    source_documents: tuple[object, ...] = (),
    objective_facts: ObjectiveFactSet | None = None,
) -> WorkspaceService:
    source_repository = Mock()
    source_repository.read_collection_documents = AsyncMock(
        return_value=source_documents
    )
    objective_repository = MemoryObjectiveRepository()
    if objective_facts is not None:
        await objective_repository.replace("col_test", "build_test", objective_facts)
    return WorkspaceService(
        collection_service=Mock(),
        task_service=Mock(),
        source_artifact_repository=source_repository,
        objective_repository=objective_repository,
        document_profile_service=Mock(),
    )


async def test_workspace_artifacts_only_report_the_maintained_build_outputs():
    service = await _service(
        source_documents=(object(),),
        objective_facts=ObjectiveFactSet(research_objectives_ready=True),
    )

    artifacts = await service._build_artifacts(
        "col_test",
        {"updated_at": "2026-08-20T00:00:00Z"},
        {"total_documents": 1},
    )

    assert artifacts == {
        "source_documents_ready": True,
        "document_profiles_ready": True,
        "objective_candidates_ready": True,
        "updated_at": "2026-08-20T00:00:00Z",
    }


async def test_workspace_marks_zero_candidate_objective_discovery_as_completed():
    service = await _service(
        source_documents=(object(),),
        objective_facts=ObjectiveFactSet(research_objectives_ready=True),
    )
    artifacts = await service._build_artifacts(
        "col_test",
        {"updated_at": "2026-08-20T00:00:00Z"},
        {"total_documents": 1},
    )

    workflow = service._build_workflow(
        file_count=1,
        latest_task=None,
        artifacts=artifacts,
        document_summary={"total_documents": 1},
    )

    assert workflow == {
        "documents": {
            "status": "ready",
            "detail": "Document profiles are available.",
        },
        "objectives": {
            "status": "ready",
            "detail": "Objective candidate discovery is complete.",
        },
    }


async def test_workspace_does_not_report_retired_graph_or_result_capabilities():
    service = await _service()

    capabilities = service._build_capabilities(
        {
            "source_documents_ready": True,
            "document_profiles_ready": True,
            "objective_candidates_ready": True,
        }
    )

    assert capabilities == {
        "can_view_documents": True,
        "can_view_objectives": True,
        "can_view_comparisons": True,
    }
