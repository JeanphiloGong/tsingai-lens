from __future__ import annotations

import pandas as pd

from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.core.workspace_overview_service import WorkspaceService
from tests.support.collection_service import build_test_collection_service
from application.source.task_service import TaskService
from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    CoreFactSet,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    ObjectiveEvidenceUnit,
)
from domain.source import SourceArtifactSet
from infra.source.runtime.source_evidence import build_blocks


def _write_source_artifacts(
    profile_service: DocumentProfileService,
    collection_id: str,
    documents: pd.DataFrame,
    text_units: pd.DataFrame,
) -> None:
    profile_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=documents.to_dict(orient="records"),
            text_units=text_units.to_dict(orient="records"),
            blocks=build_blocks(documents, text_units).to_dict(orient="records"),
        ),
    )


def test_workspace_service_builds_collection_overview(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    workspace_service = WorkspaceService(collection_service, task_service)

    collection = collection_service.create_collection("Composite Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(collection_id, "paper.txt", b"Experimental Section\nMix and anneal.")

    task_service.create_task(collection_id, "build")
    task_service.update_task(
        task_service.list_tasks(collection_id=collection_id, limit=1)[0]["task_id"],
        status="running",
        current_stage="source_artifacts_started",
        progress_percent=35,
    )
    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["collection"]["collection_id"] == collection_id
    assert overview["file_count"] == 1
    assert overview["status_summary"] == "processing"
    assert overview["latest_task"]["current_stage"] == "source_artifacts_started"
    assert overview["capabilities"]["can_view_graph"] is False
    assert overview["capabilities"]["can_view_results"] is False
    assert overview["capabilities"]["can_view_comparable_results"] is False


def test_workspace_service_includes_document_summary_and_links(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    profile_service = DocumentProfileService(collection_service)
    workspace_service = WorkspaceService(
        collection_service,
        task_service,
        document_profile_service=profile_service,
    )
    collection = collection_service.create_collection("Profiled Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nPowders were mixed and annealed.",
    )
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Profiled Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    _write_source_artifacts(profile_service, collection_id, documents, text_units)
    profile_service.build_document_profiles(collection_id)

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["status_summary"] == "document_profiled"
    assert overview["workflow"]["documents"]["status"] == "ready"
    assert overview["workflow"]["results"]["status"] == "not_started"
    assert overview["artifacts"]["document_profiles_generated"] is True
    assert overview["artifacts"]["document_profiles_ready"] is True
    assert overview["artifacts"]["evidence_cards_generated"] is False
    assert overview["artifacts"]["blocks_generated"] is True
    assert overview["artifacts"]["blocks_ready"] is True
    assert overview["document_summary"]["total_documents"] == 1
    assert overview["document_summary"]["by_doc_type"]["experimental"] == 1
    assert overview["links"]["documents"] == f"/api/v1/collections/{collection_id}/documents/profiles"
    assert overview["links"]["results"] == f"/api/v1/collections/{collection_id}/results"
    assert overview["capabilities"]["can_view_results"] is False
    assert overview["capabilities"]["can_view_comparable_results"] is False


def test_workspace_service_marks_comparisons_ready_from_core_repository(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    workspace_service = WorkspaceService(collection_service, task_service)
    collection = collection_service.create_collection("Semantic Graph Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nConductivity increased after annealing.",
    )
    workspace_service.core_fact_repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            paper_facts_ready=True,
            comparison_artifacts_ready=True,
            document_profiles=(
                DocumentProfile.from_mapping(
                    {
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "title": "Semantic Graph Paper",
                        "source_filename": "paper.txt",
                        "doc_type": "experimental",
                        "confidence": 0.9,
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
    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["status_summary"] == "ready"
    assert overview["workflow"]["results"]["status"] == "ready"
    assert overview["workflow"]["comparisons"]["status"] == "ready"
    assert overview["artifacts"]["comparison_rows_generated"] is True
    assert overview["artifacts"]["comparison_rows_ready"] is False
    assert overview["artifacts"]["graph_generated"] is True
    assert overview["artifacts"]["graph_ready"] is True
    assert overview["capabilities"]["can_view_graph"] is True
    assert overview["capabilities"]["can_view_results"] is True
    assert overview["capabilities"]["can_view_comparable_results"] is True


def test_workspace_service_marks_objective_units_as_research_view_ready(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    workspace_service = WorkspaceService(collection_service, task_service)
    collection = collection_service.create_collection("Objective Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nLPBF 316L corrosion current density was reported.",
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
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-1"}
                ],
                "resolution_status": "resolved",
            }
        ),
    )
    workspace_service.core_fact_repository.replace_collection_document_profiles(
        collection_id,
        document_profiles,
    )
    workspace_service.core_fact_repository.replace_collection_research_objectives(
        collection_id,
        paper_skims=(),
        research_objectives=(),
        objective_contexts=(),
        objective_paper_frames=(),
        objective_evidence_routes=(),
        objective_evidence_units=objective_evidence_units,
        objective_logic_chains=(),
    )

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["status_summary"] == "graph_ready"
    assert overview["workflow"]["evidence"]["status"] == "ready"
    assert overview["workflow"]["comparisons"]["status"] == "not_started"
    assert overview["artifacts"]["evidence_cards_generated"] is True
    assert overview["artifacts"]["evidence_cards_ready"] is True
    assert overview["artifacts"]["sample_variants_generated"] is False
    assert overview["artifacts"]["measurement_results_generated"] is False
    assert overview["artifacts"]["graph_generated"] is True
    assert overview["artifacts"]["graph_ready"] is True
    assert overview["capabilities"]["can_view_graph"] is True
    assert overview["capabilities"]["can_view_research_view"] is True
    assert overview["capabilities"]["can_view_results"] is False
