from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from application.source.artifact_registry_service import ArtifactRegistryService


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def test_artifact_registry_ignores_legacy_graph_outputs_for_core_readiness(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([{"id": "ent-1", "title": "oxide cathode"}]).to_parquet(
        output_dir / "entities.parquet",
        index=False,
    )
    pd.DataFrame([{"source": "ent-1", "target": "ent-2", "weight": 1.0}]).to_parquet(
        output_dir / "relationships.parquet",
        index=False,
    )

    payload = artifact_registry.build_registry("col_demo", output_dir)

    assert payload["comparable_results_generated"] is False
    assert payload["comparable_results_ready"] is False
    assert payload["collection_comparable_results_generated"] is False
    assert payload["collection_comparable_results_ready"] is False
    assert payload["graph_generated"] is False
    assert payload["graph_ready"] is False
    assert payload["figures_generated"] is False
    assert payload["figures_ready"] is False


def test_artifact_registry_marks_graph_ready_from_semantic_inputs_without_row_cache(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": "col_demo",
                "title": "Core Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": "col_demo",
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
                    "variant_id": "var-1",
                    "baseline_id": "base-1",
                    "test_condition_id": "tc-1",
                },
                "normalized_context": {
                    "material_system_normalized": "oxide cathode",
                    "process_normalized": "700 C",
                    "baseline_normalized": "as-prepared",
                    "test_condition_normalized": "EIS",
                },
                "axis": {
                    "axis_name": "anneal_temp",
                    "axis_value": 700,
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
                "variant_label": "A1",
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
                "collection_id": "col_demo",
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
            }
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    payload = artifact_registry.build_registry("col_demo", output_dir)

    assert payload["comparable_results_generated"] is True
    assert payload["comparable_results_ready"] is True
    assert payload["collection_comparable_results_generated"] is True
    assert payload["collection_comparable_results_ready"] is True
    assert payload["comparison_rows_generated"] is False
    assert payload["comparison_rows_ready"] is False
    assert payload["graph_generated"] is True
    assert payload["graph_ready"] is True
    assert (output_dir / "comparison_rows.parquet").exists() is False
    assert (output_dir / "entities.parquet").exists() is False
    assert (output_dir / "relationships.parquet").exists() is False


def test_artifact_registry_marks_figures_ready_from_source_figure_artifact(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "figure_id": "fig-1",
                "document_id": "paper-1",
                "figure_order": 1,
                "figure_label": "Figure 1",
                "caption_text": "Figure 1 SEM image.",
                "caption_block_id": "blk-paper-1-1",
                "page": 1,
                "bbox": "{\"b\": 4.0, \"coord_origin\": \"BOTTOMLEFT\", \"l\": 1.0, \"r\": 3.0, \"t\": 2.0}",
                "heading_path": "Characterization",
                "image_path": "image_assets/fig-1.png",
                "image_mime_type": "image/png",
                "image_width": 20,
                "image_height": 10,
                "asset_sha256": "sha",
                "metadata": {"asset_source": "docling_crop"},
            }
        ]
    ).to_parquet(output_dir / "figures.parquet", index=False)

    payload = artifact_registry.build_registry("col_demo", output_dir)

    assert payload["figures_generated"] is True
    assert payload["figures_ready"] is True
