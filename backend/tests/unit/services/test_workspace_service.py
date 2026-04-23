from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from application.core.workspace_overview_service import WorkspaceService
from domain.core.comparison import ComparableResult, build_collection_assessment_input_fingerprint
from infra.source.runtime.source_evidence import build_blocks, build_table_cells, build_table_rows


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _current_scope_metadata(comparable_result: dict) -> dict[str, object]:
    comparable_record = ComparableResult.from_mapping(comparable_result)
    return {
        "policy_family": "default_collection_comparison_policy",
        "policy_version": "comparison_policy_v1",
        "comparable_result_normalization_version": comparable_record.normalization_version,
        "assessment_input_fingerprint": build_collection_assessment_input_fingerprint(
            comparable_record
        ),
        "reassessment_triggers": [
            "policy_family_changed",
            "policy_version_changed",
            "comparable_result_normalization_version_changed",
            "assessment_input_fingerprint_changed",
        ],
    }


def _write_source_artifacts(
    output_dir: Path,
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> None:
    build_blocks(documents, text_units).to_parquet(output_dir / "blocks.parquet", index=False)
    pd.DataFrame(columns=["figure_id"]).to_parquet(output_dir / "figures.parquet", index=False)
    build_table_rows(documents, text_units).to_parquet(output_dir / "table_rows.parquet", index=False)
    build_table_cells(documents, text_units).to_parquet(output_dir / "table_cells.parquet", index=False)


def test_workspace_service_builds_collection_overview(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    workspace_service = WorkspaceService(collection_service, task_service, artifact_registry)

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
    artifact_registry.upsert(collection_id, collection_service.get_paths(collection_id).output_dir)

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["collection"]["collection_id"] == collection_id
    assert overview["file_count"] == 1
    assert overview["status_summary"] == "processing"
    assert overview["latest_task"]["current_stage"] == "source_artifacts_started"
    assert overview["capabilities"]["can_view_graph"] is False
    assert overview["capabilities"]["can_view_results"] is False
    assert overview["capabilities"]["can_view_comparable_results"] is False
    assert overview["capabilities"]["can_generate_sop"] is False


def test_workspace_service_includes_document_summary_and_links(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    workspace_service = WorkspaceService(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Profiled Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nPowders were mixed and annealed.",
    )

    output_dir = collection_service.get_paths(collection_id).output_dir
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
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)
    DocumentProfileService(collection_service, artifact_registry).build_document_profiles(
        collection_id,
        output_dir,
    )

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["status_summary"] == "document_profiled"
    assert overview["workflow"]["documents"]["status"] == "ready"
    assert overview["workflow"]["results"]["status"] == "not_started"
    assert overview["workflow"]["protocol"]["status"] == "not_started"
    assert overview["artifacts"]["document_profiles_generated"] is True
    assert overview["artifacts"]["document_profiles_ready"] is True
    assert overview["artifacts"]["evidence_anchors_generated"] is False
    assert overview["artifacts"]["evidence_anchors_ready"] is False
    assert overview["artifacts"]["method_facts_generated"] is False
    assert overview["artifacts"]["method_facts_ready"] is False
    assert overview["artifacts"]["evidence_cards_generated"] is False
    assert overview["artifacts"]["evidence_cards_ready"] is False
    assert overview["artifacts"]["characterization_observations_generated"] is False
    assert overview["artifacts"]["characterization_observations_ready"] is False
    assert overview["artifacts"]["structure_features_generated"] is False
    assert overview["artifacts"]["structure_features_ready"] is False
    assert overview["artifacts"]["test_conditions_generated"] is False
    assert overview["artifacts"]["test_conditions_ready"] is False
    assert overview["artifacts"]["baseline_references_generated"] is False
    assert overview["artifacts"]["baseline_references_ready"] is False
    assert overview["artifacts"]["sample_variants_generated"] is False
    assert overview["artifacts"]["sample_variants_ready"] is False
    assert overview["artifacts"]["measurement_results_generated"] is False
    assert overview["artifacts"]["measurement_results_ready"] is False
    assert overview["artifacts"]["comparable_results_generated"] is False
    assert overview["artifacts"]["comparable_results_ready"] is False
    assert overview["artifacts"]["collection_comparable_results_generated"] is False
    assert overview["artifacts"]["collection_comparable_results_ready"] is False
    assert overview["artifacts"]["collection_comparable_results_stale"] is False
    assert overview["artifacts"]["comparison_rows_generated"] is False
    assert overview["artifacts"]["comparison_rows_ready"] is False
    assert overview["artifacts"]["comparison_rows_stale"] is False
    assert overview["artifacts"]["graph_stale"] is False
    assert overview["artifacts"]["blocks_generated"] is True
    assert overview["artifacts"]["blocks_ready"] is True
    assert overview["artifacts"]["figures_generated"] is True
    assert overview["artifacts"]["figures_ready"] is False
    assert overview["artifacts"]["table_rows_generated"] is True
    assert overview["artifacts"]["table_rows_ready"] is False
    assert overview["artifacts"]["table_cells_generated"] is True
    assert overview["artifacts"]["table_cells_ready"] is False
    assert overview["artifacts"]["protocol_steps_generated"] is False
    assert "graphml_generated" not in overview["artifacts"]
    assert overview["document_summary"]["total_documents"] == 1
    assert overview["document_summary"]["by_doc_type"]["experimental"] == 1
    assert overview["links"]["documents"] == f"/api/v1/collections/{collection_id}/documents/profiles"
    assert overview["links"]["results"] == f"/api/v1/collections/{collection_id}/results"
    assert overview["links"]["documents_profiles"] == f"/api/v1/collections/{collection_id}/documents/profiles"
    assert overview["links"]["comparisons"] == f"/api/v1/collections/{collection_id}/comparisons"
    assert overview["links"]["comparable_results"] == (
        f"/api/v1/comparable-results?collection_id={collection_id}"
    )
    assert overview["capabilities"]["can_view_results"] is False
    assert overview["capabilities"]["can_view_comparable_results"] is False


def test_workspace_service_marks_comparisons_ready_from_semantic_artifacts_without_row_cache(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    workspace_service = WorkspaceService(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Semantic Graph Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nConductivity increased after annealing.",
    )

    output_dir = collection_service.get_paths(collection_id).output_dir
    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Semantic Graph Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.9,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Conductivity increased after annealing.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "oxide cathode"},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.82,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "comparable_result_id": "cres-1",
                "source_result_id": "res-1",
                "source_document_id": "paper-1",
                "binding": {
                    "variant_id": None,
                    "baseline_id": None,
                    "test_condition_id": None,
                },
                "normalized_context": {
                    "material_system_normalized": "oxide cathode",
                    "process_normalized": "700 C",
                    "baseline_normalized": "as-prepared",
                    "test_condition_normalized": "EIS",
                },
                "axis": {
                    "axis_name": None,
                    "axis_value": None,
                    "axis_unit": None,
                },
                "value": {
                    "property_normalized": "conductivity",
                    "result_type": "scalar",
                    "numeric_value": 12.0,
                    "unit": "mS/cm",
                    "summary": "12 mS/cm",
                },
                "evidence": {
                    "direct_anchor_ids": ["anchor-1"],
                    "contextual_anchor_ids": [],
                    "evidence_ids": ["ev-1"],
                    "structure_feature_ids": [],
                    "characterization_observation_ids": [],
                    "traceability_status": "direct",
                },
                "variant_label": None,
                "baseline_reference": "as-prepared",
                "result_source_type": "text",
                "epistemic_status": "normalized_from_evidence",
                "normalization_version": "comparable_result_v1",
            }
        ]
    ).to_parquet(output_dir / "comparable_results.parquet", index=False)
    current_scope_record = {
        "collection_id": collection_id,
        "comparable_result_id": "cres-1",
        "assessment": {
            "missing_critical_context": [],
            "comparability_basis": ["baseline_resolved"],
            "comparability_warnings": [],
            "comparability_status": "comparable",
            "requires_expert_review": False,
            "assessment_epistemic_status": "normalized_from_evidence",
        },
        "epistemic_status": "normalized_from_evidence",
        "included": True,
        "sort_order": 0,
        **_current_scope_metadata(
            {
                "comparable_result_id": "cres-1",
                "source_result_id": "res-1",
                "source_document_id": "paper-1",
                "binding": {
                    "variant_id": None,
                    "baseline_id": None,
                    "test_condition_id": None,
                },
                "normalized_context": {
                    "material_system_normalized": "oxide cathode",
                    "process_normalized": "700 C",
                    "baseline_normalized": "as-prepared",
                    "test_condition_normalized": "EIS",
                },
                "axis": {
                    "axis_name": None,
                    "axis_value": None,
                    "axis_unit": None,
                },
                "value": {
                    "property_normalized": "conductivity",
                    "result_type": "scalar",
                    "numeric_value": 12.0,
                    "unit": "mS/cm",
                    "summary": "12 mS/cm",
                },
                "evidence": {
                    "direct_anchor_ids": ["anchor-1"],
                    "contextual_anchor_ids": [],
                    "evidence_ids": ["ev-1"],
                    "structure_feature_ids": [],
                    "characterization_observation_ids": [],
                    "traceability_status": "direct",
                },
                "variant_label": None,
                "baseline_reference": "as-prepared",
                "result_source_type": "text",
                "epistemic_status": "normalized_from_evidence",
                "normalization_version": "comparable_result_v1",
            }
        ),
    }
    pd.DataFrame([current_scope_record]).to_parquet(
        output_dir / "collection_comparable_results.parquet",
        index=False,
    )
    artifact_registry.upsert(collection_id, output_dir)

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["status_summary"] == "ready"
    assert overview["workflow"]["results"]["status"] == "ready"
    assert overview["workflow"]["comparisons"]["status"] == "ready"
    assert overview["artifacts"]["comparison_rows_generated"] is False
    assert overview["artifacts"]["comparison_rows_ready"] is False
    assert overview["artifacts"]["collection_comparable_results_stale"] is False
    assert overview["artifacts"]["comparison_rows_stale"] is False
    assert overview["artifacts"]["graph_generated"] is True
    assert overview["artifacts"]["graph_ready"] is True
    assert overview["artifacts"]["graph_stale"] is False
    assert overview["capabilities"]["can_view_graph"] is True
    assert overview["capabilities"]["can_view_results"] is True
    assert overview["capabilities"]["can_view_comparable_results"] is True
    assert overview["capabilities"]["can_download_graphml"] is True


def test_workspace_service_marks_stale_comparisons_as_limited(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    workspace_service = WorkspaceService(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Stale Semantic Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nConductivity increased after annealing.",
    )

    output_dir = collection_service.get_paths(collection_id).output_dir
    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Semantic Graph Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.9,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Conductivity increased after annealing.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "oxide cathode"},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.82,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "comparable_result_id": "cres-1",
                "source_result_id": "res-1",
                "source_document_id": "paper-1",
                "binding": {
                    "variant_id": None,
                    "baseline_id": None,
                    "test_condition_id": None,
                },
                "normalized_context": {
                    "material_system_normalized": "oxide cathode",
                    "process_normalized": "700 C",
                    "baseline_normalized": "as-prepared",
                    "test_condition_normalized": "EIS",
                },
                "axis": {
                    "axis_name": None,
                    "axis_value": None,
                    "axis_unit": None,
                },
                "value": {
                    "property_normalized": "conductivity",
                    "result_type": "scalar",
                    "numeric_value": 12.0,
                    "unit": "mS/cm",
                    "summary": "12 mS/cm",
                },
                "evidence": {
                    "direct_anchor_ids": ["anchor-1"],
                    "contextual_anchor_ids": [],
                    "evidence_ids": ["ev-1"],
                    "structure_feature_ids": [],
                    "characterization_observation_ids": [],
                    "traceability_status": "direct",
                },
                "variant_label": None,
                "baseline_reference": "as-prepared",
                "result_source_type": "text",
                "epistemic_status": "normalized_from_evidence",
                "normalization_version": "comparable_result_v1",
            }
        ]
    ).to_parquet(output_dir / "comparable_results.parquet", index=False)
    pd.DataFrame(
        [
            {
                "collection_id": collection_id,
                "comparable_result_id": "cres-1",
                "assessment": {
                    "missing_critical_context": [],
                    "comparability_basis": ["baseline_resolved"],
                    "comparability_warnings": [],
                    "comparability_status": "comparable",
                    "requires_expert_review": False,
                    "assessment_epistemic_status": "normalized_from_evidence",
                },
                "epistemic_status": "normalized_from_evidence",
                "included": True,
                "sort_order": 0,
                "policy_family": "default_collection_comparison_policy",
                "policy_version": "comparison_policy_v0",
                "comparable_result_normalization_version": "comparable_result_v1",
                "assessment_input_fingerprint": "cafp_outdated",
                "reassessment_triggers": [
                    "policy_family_changed",
                    "policy_version_changed",
                    "comparable_result_normalization_version_changed",
                    "assessment_input_fingerprint_changed",
                ],
            }
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    pd.DataFrame([{"row_id": "cmp-1"}]).to_parquet(
        output_dir / "comparison_rows.parquet",
        index=False,
    )
    artifact_registry.upsert(collection_id, output_dir)

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["status_summary"] == "comparison_pending"
    assert overview["workflow"]["results"]["status"] == "limited"
    assert overview["workflow"]["comparisons"]["status"] == "limited"
    assert "stale" in overview["workflow"]["comparisons"]["detail"].lower()
    assert overview["artifacts"]["collection_comparable_results_generated"] is True
    assert overview["artifacts"]["collection_comparable_results_ready"] is False
    assert overview["artifacts"]["collection_comparable_results_stale"] is True
    assert overview["artifacts"]["comparison_rows_generated"] is True
    assert overview["artifacts"]["comparison_rows_ready"] is False
    assert overview["artifacts"]["comparison_rows_stale"] is True
    assert overview["artifacts"]["graph_generated"] is True
    assert overview["artifacts"]["graph_ready"] is False
    assert overview["artifacts"]["graph_stale"] is True
    assert overview["capabilities"]["can_view_graph"] is False
    assert overview["capabilities"]["can_view_results"] is True
    assert overview["capabilities"]["can_view_comparable_results"] is True
    assert overview["capabilities"]["can_download_graphml"] is False
