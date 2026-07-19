from __future__ import annotations

from unittest.mock import Mock

from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.task_service import TaskService
from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    ObjectiveEvidenceUnit,
)
from domain.core.paper_fact import PaperFactSet
from domain.source import SourceArtifactSet
from infra.persistence.memory import MemoryBuildRepository
from infra.persistence.sqlite import (
    SqliteCoreFactRepository,
    SqliteSourceArtifactRepository,
)
from tests.support.paper_fact_repository import MemoryPaperFactRepository


def test_artifact_registry_ignores_absent_legacy_graph_outputs(tmp_path):
    source_repository = Mock()
    source_repository.read_collection_artifacts.return_value = SourceArtifactSet()
    paper_repository = MemoryPaperFactRepository()
    core_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    artifact_registry = ArtifactRegistryService(
        MemoryBuildRepository(),
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_repository,
        core_fact_repository=core_repository,
    )

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
    paper_repository = MemoryPaperFactRepository()
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
    structure_repository = Mock()
    structure_repository.read_collection_artifacts.return_value = (
        source_repository.read_collection_artifacts(collection_id)
    )
    paper_repository.replace_document_profiles(
        collection_id,
        "build_test",
        (
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
        ),
    )
    comparable_result = ComparableResult.from_mapping(
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
    )
    core_repository.replace_collection_comparison_artifacts(
        collection_id,
        (comparable_result,),
        (
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
        (),
    )
    artifact_registry = ArtifactRegistryService(
        MemoryBuildRepository(),
        source_artifact_repository=structure_repository,
        paper_fact_repository=paper_repository,
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


def test_artifact_registry_marks_objective_units_as_evidence_cards(tmp_path):
    collection_id = "col_demo"
    db_path = tmp_path / "lens.sqlite"
    source_repository = SqliteSourceArtifactRepository(db_path)
    core_repository = SqliteCoreFactRepository(db_path)
    paper_repository = MemoryPaperFactRepository()
    source_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Objective Paper",
                    "text": "LPBF 316L corrosion current density was reported.",
                }
            ],
        ),
    )
    structure_repository = Mock()
    structure_repository.read_collection_artifacts.return_value = (
        source_repository.read_collection_artifacts(collection_id)
    )
    document_profiles = (
        DocumentProfile.from_mapping(
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Objective Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "confidence": 0.9,
            }
        ),
    )
    objective_evidence_units = (
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": "oeu-1",
                "objective_id": "obj-corrosion",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {"name": "316L stainless steel"},
                "sample_context": {"sample": "as-built"},
                "process_context": {"process": "LPBF"},
                "test_condition": {"method": "polarization"},
                "property_normalized": "corrosion current density",
                "value_payload": {"value": 1.2},
                "unit": "uA/cm2",
                "source_refs": [{"source_kind": "table", "source_ref": "table-1"}],
                "resolution_status": "resolved",
            }
        ),
    )
    comparison_rows = (
        ComparisonRowRecord.from_mapping(
            {
                "row_id": "row-1",
                "collection_id": collection_id,
                "comparable_result_id": "objective:oeu-1",
                "source_document_id": "paper-1",
                "variant_label": "as-built",
                "result_type": "scalar",
                "result_summary": "1.2 uA/cm2",
                "supporting_evidence_ids": ["oeu-1"],
                "material_system_normalized": "316L stainless steel",
                "process_normalized": "LPBF",
                "property_normalized": "corrosion current density",
                "baseline_normalized": "unspecified baseline",
                "test_condition_normalized": "method: polarization",
                "comparability_status": "comparable",
                "value": 1.2,
                "unit": "uA/cm2",
            }
        ),
    )
    paper_repository.replace_document_profiles(
        collection_id,
        "build_test",
        document_profiles,
    )
    core_repository.replace_collection_research_objectives(
        collection_id,
        paper_skims=(),
        research_objectives=(),
        objective_contexts=(),
        objective_paper_frames=(),
        objective_evidence_routes=(),
        objective_evidence_units=objective_evidence_units,
        objective_logic_chains=(),
    )
    core_repository.replace_collection_comparison_artifacts(
        collection_id,
        comparable_results=(),
        collection_comparable_results=(),
        comparison_rows=comparison_rows,
    )
    artifact_registry = ArtifactRegistryService(
        MemoryBuildRepository(),
        source_artifact_repository=structure_repository,
        paper_fact_repository=paper_repository,
        core_fact_repository=core_repository,
    )

    payload = artifact_registry.build_registry(collection_id, tmp_path / "output")

    assert payload["evidence_cards_generated"] is True
    assert payload["evidence_cards_ready"] is True
    assert payload["evidence_anchors_generated"] is False
    assert payload["sample_variants_generated"] is False
    assert payload["measurement_results_generated"] is False
    assert payload["comparison_rows_generated"] is True
    assert payload["comparison_rows_ready"] is True
    assert payload["graph_generated"] is True
    assert payload["graph_ready"] is True


def test_artifact_registry_persists_version_rows_and_rebuilds_task_projection(
    tmp_path,
) -> None:
    collection_id = "col_versions"
    repository = MemoryBuildRepository()
    task_service = TaskService(repository)
    task = task_service.create_task(collection_id)
    task_service.update_task(
        task["task_id"],
        status="running",
        output_path=str(tmp_path / "output"),
        pipeline_nodes={
            "artifact_registry": {
                "status": "running",
                "started_at": "2026-07-19T10:00:00+00:00",
                "finished_at": None,
                "errors": [],
                "warnings": [],
                "skip_reason": None,
            }
        },
    )
    db_path = tmp_path / "lens.sqlite"
    source_repository = SqliteSourceArtifactRepository(db_path)
    core_repository = SqliteCoreFactRepository(db_path)
    paper_repository = MemoryPaperFactRepository()
    source_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Versioned Paper",
                    "text": "Traceable content.",
                }
            ]
        ),
    )
    structure_repository = Mock()
    structure_repository.read_collection_artifacts.return_value = (
        source_repository.read_collection_artifacts(collection_id)
    )
    registry = ArtifactRegistryService(
        repository,
        source_artifact_repository=structure_repository,
        paper_fact_repository=paper_repository,
        core_fact_repository=core_repository,
    )

    registered = registry.register(
        task["task_id"],
        collection_id,
        tmp_path / "output",
    )
    versions = repository.list_artifact_versions(task["task_id"])

    assert {version.artifact_kind for version in versions} == {
        "blocks",
        "documents",
        "figures",
        "table_cells",
        "table_rows",
    }
    assert all(version.details == {} for version in versions)
    assert registered["documents_generated"] is True
    assert registered["documents_ready"] is True
    assert registered["blocks_generated"] is True
    assert registered["blocks_ready"] is False
    assert registry.get_for_task(task["task_id"]) == registered
