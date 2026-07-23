from __future__ import annotations

from unittest.mock import Mock

from application.source.artifact_registry_service import ArtifactRegistryService
from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonFactSet,
    DocumentProfile,
    EvidenceAnchor,
)
from domain.core.paper_fact import PaperFactSet
from domain.source import SourceArtifactSet
from infra.persistence.memory import MemoryBuildRepository
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository


def _registry(
    *,
    source_artifacts: SourceArtifactSet = SourceArtifactSet(),
    paper_repository: MemoryPaperFactRepository | None = None,
    comparison_repository: MemoryComparisonRepository | None = None,
) -> ArtifactRegistryService:
    source_repository = Mock()
    source_repository.read_collection_artifacts.return_value = source_artifacts
    return ArtifactRegistryService(
        MemoryBuildRepository(),
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_repository or MemoryPaperFactRepository(),
        comparison_repository=comparison_repository or MemoryComparisonRepository(),
    )


def test_artifact_registry_marks_absent_core_artifacts_not_ready(tmp_path):
    payload = _registry().build_registry("col_demo", tmp_path / "output")

    assert payload["evidence_cards_ready"] is False
    assert payload["comparable_results_ready"] is False
    assert payload["collection_comparable_results_ready"] is False
    assert payload["graph_ready"] is False
    assert payload["figures_ready"] is False


def test_artifact_registry_reads_paper_facts_and_comparisons_directly(tmp_path):
    collection_id = "col_demo"
    paper_repository = MemoryPaperFactRepository()
    paper_repository.replace_document_profiles(
        collection_id,
        "build_test",
        (
            DocumentProfile.from_mapping(
                {
                    "document_id": "paper-1",
                    "collection_id": collection_id,
                    "title": "Core Paper",
                    "doc_type": "experimental",
                }
            ),
        ),
    )
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
                        "quote": "Conductivity increased after annealing.",
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
                        "comparable_result_id": "cres-1",
                        "source_result_id": "result-1",
                        "source_document_id": "paper-1",
                    }
                ),
            ),
            collection_comparable_results=(
                CollectionComparableResult.from_mapping(
                    {
                        "collection_id": collection_id,
                        "comparable_result_id": "cres-1",
                        "assessment": {"comparability_status": "comparable"},
                        "included": True,
                    }
                ),
            ),
        ),
    )
    source_artifacts = SourceArtifactSet.from_records(
        documents=[{"id": "paper-1", "title": "Core Paper", "text": "Text"}],
        figures=[
            {
                "figure_id": "fig-1",
                "document_id": "paper-1",
                "figure_order": 1,
                "caption_text": "Microstructure",
            }
        ],
    )

    payload = _registry(
        source_artifacts=source_artifacts,
        paper_repository=paper_repository,
        comparison_repository=comparison_repository,
    ).build_registry(collection_id, tmp_path / "output")

    assert payload["document_profiles_ready"] is True
    assert payload["evidence_cards_generated"] is True
    assert payload["evidence_cards_ready"] is True
    assert payload["comparison_rows_ready"] is True
    assert payload["graph_ready"] is True
    assert payload["figures_ready"] is True


def test_artifact_registry_keeps_excluded_comparison_rows_not_ready(tmp_path):
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
                        "comparable_result_id": "cres-excluded",
                        "source_result_id": "result-1",
                        "source_document_id": "paper-1",
                    }
                ),
            ),
            collection_comparable_results=(
                CollectionComparableResult.from_mapping(
                    {
                        "collection_id": collection_id,
                        "comparable_result_id": "cres-excluded",
                        "included": False,
                    }
                ),
            ),
        ),
    )

    payload = _registry(
        comparison_repository=comparison_repository
    ).build_registry(collection_id, tmp_path / "output")

    assert payload["comparison_rows_generated"] is True
    assert payload["comparison_rows_ready"] is False
