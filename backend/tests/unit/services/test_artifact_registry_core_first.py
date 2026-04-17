from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from application.workspace.artifact_registry_service import ArtifactRegistryService


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

    assert payload["graph_generated"] is False
    assert payload["graph_ready"] is False


def test_artifact_registry_marks_graph_ready_from_core_inputs_without_legacy_graph_outputs(
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
                "row_id": "cmp-1",
                "collection_id": "col_demo",
                "source_document_id": "paper-1",
                "supporting_evidence_ids": ["ev-1"],
                "material_system_normalized": "oxide cathode",
                "process_normalized": "700 C",
                "property_normalized": "conductivity",
                "baseline_normalized": "as-prepared",
                "test_condition_normalized": "EIS",
                "comparability_status": "comparable",
                "comparability_warnings": [],
            }
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)

    payload = artifact_registry.build_registry("col_demo", output_dir)

    assert payload["graph_generated"] is True
    assert payload["graph_ready"] is True
    assert (output_dir / "entities.parquet").exists() is False
    assert (output_dir / "relationships.parquet").exists() is False
