from __future__ import annotations

from application.core.workspace_overview_service import WorkspaceService
from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonFactSet,
    EvidenceAnchor,
)
from domain.core.paper_fact import PaperFactSet
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.source_artifact_repository import MemorySourceArtifactRepository


def _service(
    *,
    paper_repository: MemoryPaperFactRepository | None = None,
    comparison_repository: MemoryComparisonRepository | None = None,
) -> WorkspaceService:
    return WorkspaceService(
        collection_service=None,  # type: ignore[arg-type]
        task_service=None,  # type: ignore[arg-type]
        source_artifact_repository=MemorySourceArtifactRepository(),
        paper_fact_repository=paper_repository or MemoryPaperFactRepository(),
        comparison_repository=comparison_repository or MemoryComparisonRepository(),
        document_profile_service=None,  # type: ignore[arg-type]
    )


def test_workspace_artifacts_are_empty_before_paper_facts_exist():
    artifacts = _service()._build_artifacts(
        "col-empty",
        {"updated_at": "2026-07-20T00:00:00+00:00"},
    )

    assert artifacts["evidence_cards_ready"] is False
    assert artifacts["comparison_rows_ready"] is False
    assert artifacts["graph_ready"] is False


def test_workspace_readiness_comes_from_paper_facts_and_comparisons():
    collection_id = "col-ready"
    paper_repository = MemoryPaperFactRepository()
    paper_repository.replace_paper_facts(
        collection_id,
        "build_test",
        PaperFactSet(
            paper_facts_ready=True,
            evidence_anchors=(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-1",
                        "document_id": "paper-1",
                        "locator_type": "text",
                        "source_type": "text",
                        "quote": "A measured result.",
                    }
                ),
            ),
        ),
    )
    comparison_repository = MemoryComparisonRepository()
    comparison_repository.replace(
        collection_id,
        "build_test",
        ComparisonFactSet(
            comparison_artifacts_ready=True,
            comparable_results=(
                ComparableResult.from_mapping(
                    {
                        "comparable_result_id": "result-1",
                        "source_result_id": "measurement-1",
                        "source_document_id": "paper-1",
                    }
                ),
            ),
            collection_comparable_results=(
                CollectionComparableResult.from_mapping(
                    {
                        "collection_id": collection_id,
                        "comparable_result_id": "result-1",
                        "included": True,
                    }
                ),
            ),
        ),
    )

    artifacts = _service(
        paper_repository=paper_repository,
        comparison_repository=comparison_repository,
    )._build_artifacts(
        collection_id,
        {"updated_at": "2026-07-20T00:00:00+00:00"},
    )

    assert artifacts["evidence_cards_ready"] is True
    assert artifacts["comparison_rows_ready"] is True
    assert artifacts["graph_ready"] is False


def test_workspace_excluded_comparisons_are_not_ready():
    collection_id = "col-excluded"
    comparison_repository = MemoryComparisonRepository()
    comparison_repository.replace(
        collection_id,
        "build_test",
        ComparisonFactSet(
            comparison_artifacts_ready=True,
            comparable_results=(
                ComparableResult.from_mapping(
                    {
                        "comparable_result_id": "result-1",
                        "source_result_id": "measurement-1",
                        "source_document_id": "paper-1",
                    }
                ),
            ),
            collection_comparable_results=(
                CollectionComparableResult.from_mapping(
                    {
                        "collection_id": collection_id,
                        "comparable_result_id": "result-1",
                        "included": False,
                    }
                ),
            ),
        ),
    )

    artifacts = _service(
        comparison_repository=comparison_repository
    )._build_artifacts(
        collection_id,
        {"updated_at": "2026-07-20T00:00:00+00:00"},
    )

    assert artifacts["comparison_rows_generated"] is True
    assert artifacts["comparison_rows_ready"] is False
