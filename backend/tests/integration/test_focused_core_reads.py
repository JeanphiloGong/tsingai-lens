from __future__ import annotations

from unittest.mock import Mock

from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
)
from application.core.workspace_overview_service import WorkspaceService
from domain.core import DocumentProfile, EvidenceAnchor
from domain.core.paper_fact import PaperFactSet
from domain.source import SourceArtifactSet
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository


COLLECTION_ID = "col-focused"


def _paper_repository() -> MemoryPaperFactRepository:
    repository = MemoryPaperFactRepository()
    repository.replace_document_profiles(
        COLLECTION_ID,
        "build_test",
        (
            DocumentProfile.from_mapping(
                {
                    "document_id": "doc-1",
                    "collection_id": COLLECTION_ID,
                    "title": "Focused read paper",
                    "doc_type": "experimental",
                }
            ),
        ),
    )
    repository.replace_paper_facts(
        COLLECTION_ID,
        "build_test",
        PaperFactSet(
            paper_facts_ready=True,
            evidence_anchors=(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-1",
                        "document_id": "doc-1",
                        "locator_type": "text",
                        "source_type": "text",
                        "quote": "A focused result.",
                    }
                ),
            ),
        ),
    )
    return repository


def test_workspace_reads_each_collection_fact_family_once():
    paper_repository = _paper_repository()
    comparison_repository = MemoryComparisonRepository()
    paper_repository.read = Mock(wraps=paper_repository.read)
    comparison_repository.read = Mock(wraps=comparison_repository.read)
    source_repository = Mock()
    source_repository.read_collection_artifacts.return_value = SourceArtifactSet()
    collection_service = Mock()
    collection_service.get_collection.return_value = {
        "collection_id": COLLECTION_ID,
        "updated_at": "2026-07-20T00:00:00Z",
    }
    collection_service.list_files.return_value = [{"filename": "paper.pdf"}]
    task_service = Mock()
    task_service.list_tasks.return_value = []
    document_profile_service = Mock()
    document_profile_service.get_document_summary.return_value = {
        "total_documents": 1,
        "by_doc_type": {"experimental": 1},
        "warnings": [],
    }
    service = WorkspaceService(
        collection_service=collection_service,
        task_service=task_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_repository,
        comparison_repository=comparison_repository,
        document_profile_service=document_profile_service,
    )

    payload = service.get_workspace_overview(COLLECTION_ID)

    assert payload["artifacts"]["evidence_cards_ready"] is True
    paper_repository.read.assert_called_once_with(COLLECTION_ID)
    comparison_repository.read.assert_called_once_with(COLLECTION_ID)


def test_research_view_reads_paper_facts_once_without_objective_fallback():
    paper_repository = _paper_repository()
    paper_repository.read = Mock(wraps=paper_repository.read)
    comparison_service = Mock()
    comparison_service.read_comparison_projection.side_effect = RuntimeError
    collection_service = Mock()
    collection_service.get_collection.return_value = {
        "collection_id": COLLECTION_ID,
        "paper_count": 1,
    }
    collection_service.list_files.return_value = [{"filename": "paper.pdf"}]
    service = ResearchViewAggregationService(
        collection_service=collection_service,
        paper_fact_repository=paper_repository,
        comparison_service=comparison_service,
    )

    try:
        service.get_collection_research_view(COLLECTION_ID)
    except RuntimeError:
        pass

    paper_repository.read.assert_called_once_with(COLLECTION_ID)
