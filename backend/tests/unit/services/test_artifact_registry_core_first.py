from __future__ import annotations

from application.source.artifact_registry_service import ArtifactRegistryService
from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    CoreFactSet,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
)
from domain.source import SourceArtifactSet
from infra.persistence.sqlite import SqliteCoreFactRepository, SqliteSourceArtifactRepository


def test_artifact_registry_ignores_absent_legacy_graph_outputs(tmp_path):
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")

    payload = artifact_registry.build_registry("col_demo", tmp_path / "output")

    assert payload["comparable_results_generated"] is False
    assert payload["comparable_results_ready"] is False
    assert payload["collection_comparable_results_generated"] is False
    assert payload["collection_comparable_results_ready"] is False
    assert payload["graph_generated"] is False
    assert payload["graph_ready"] is False
    assert payload["figures_generated"] is False
    assert payload["figures_ready"] is False


def test_artifact_registry_marks_core_readiness_from_repositories(tmp_path):
    collection_id = "col_demo"
    db_path = tmp_path / "lens.sqlite"
    source_repository = SqliteSourceArtifactRepository(db_path)
    core_repository = SqliteCoreFactRepository(db_path)
    source_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Core Paper",
                    "text": "Conductivity increased after annealing.",
                }
            ],
            figures=[
                {
                    "figure_id": "fig-1",
                    "document_id": "paper-1",
                    "figure_order": 1,
                    "caption_text": "Microstructure",
                }
            ],
        ),
    )
    core_repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            paper_facts_ready=True,
            comparison_artifacts_ready=True,
            document_profiles=(
                DocumentProfile.from_mapping(
                    {
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "title": "Core Paper",
                        "source_filename": "paper.txt",
                        "doc_type": "experimental",
                        "confidence": 0.91,
                    }
                ),
            ),
            evidence_anchors=(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-1",
                        "document_id": "paper-1",
                        "locator_type": "text",
                        "locator_confidence": "direct",
                        "source_type": "text",
                        "quote": "Conductivity increased after annealing.",
                    }
                ),
            ),
            measurement_results=(
                MeasurementResult.from_mapping(
                    {
                        "result_id": "res-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "property_normalized": "conductivity",
                        "result_type": "scalar",
                        "value_payload": {"value": 12.0},
                        "unit": "mS/cm",
                        "evidence_anchor_ids": ["anchor-1"],
                        "traceability_status": "direct",
                    }
                ),
            ),
            comparable_results=(
                ComparableResult.from_mapping(
                    {
                        "comparable_result_id": "cres-1",
                        "source_result_id": "res-1",
                        "source_document_id": "paper-1",
                        "normalized_context": {
                            "material_system_normalized": "oxide cathode",
                            "process_normalized": "700 C",
                            "baseline_normalized": "as-prepared",
                            "test_condition_normalized": "EIS",
                        },
                        "value": {
                            "property_normalized": "conductivity",
                            "result_type": "scalar",
                            "numeric_value": 12.0,
                            "unit": "mS/cm",
                            "summary": "12 mS/cm",
                        },
                    }
                ),
            ),
            collection_comparable_results=(
                CollectionComparableResult.from_mapping(
                    {
                        "collection_id": collection_id,
                        "comparable_result_id": "cres-1",
                        "assessment": {
                            "comparability_status": "comparable",
                            "requires_expert_review": False,
                        },
                        "included": True,
                        "sort_order": 0,
                    }
                ),
            ),
        ),
    )
    artifact_registry = ArtifactRegistryService(
        tmp_path / "collections",
        source_artifact_repository=source_repository,
        core_fact_repository=core_repository,
    )

    payload = artifact_registry.build_registry(collection_id, tmp_path / "output")

    assert payload["document_profiles_ready"] is True
    assert payload["evidence_cards_generated"] is True
    assert payload["evidence_cards_ready"] is True
    assert payload["comparable_results_ready"] is True
    assert payload["collection_comparable_results_ready"] is True
    assert payload["graph_generated"] is True
    assert payload["graph_ready"] is True
    assert payload["figures_generated"] is True
    assert payload["figures_ready"] is True
