from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


def _load_exporter_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "export_prediction_bundle.py"
    )
    spec = importlib.util.spec_from_file_location(
        "export_prediction_bundle",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_export_prediction_bundle_writes_gold_aligned_system_output(tmp_path, monkeypatch):
    exporter = _load_exporter_module()
    output_dir = tmp_path / "collection-output"
    output_dir.mkdir()
    frames = _write_system_artifact_placeholders(output_dir)
    monkeypatch.setattr(
        exporter.pd,
        "read_parquet",
        lambda path: frames[Path(path).stem].copy(),
    )
    prediction_path = tmp_path / "generated" / "prediction_bundle.json"

    result_path = exporter.export_prediction_bundle(
        source_output_dir=output_dir,
        output_path=prediction_path,
    )

    assert result_path == prediction_path
    bundle = json.loads(prediction_path.read_text(encoding="utf-8"))
    assert bundle["metadata"]["schema_version"] == "prediction-bundle-v0.1"
    assert bundle["metadata"]["collection_id"] == "col-test"
    assert bundle["metadata"]["artifact_rows"]["measurement_results"] == 1
    assert bundle["papers"][0]["paper_id"] == "paper-1"
    assert bundle["papers"][0]["title"] == "Prediction Paper"
    assert bundle["samples"][0]["sample_id"] == "var-1"
    assert bundle["samples"][0]["evidence_ids"] == ["anchor-sample"]
    assert any(
        record["original_parameter_name"] == "laser_power_w"
        and record["sample_reference"] == "var-1"
        for record in bundle["process_parameters"]
    )
    assert bundle["test_conditions"][0]["test_temperature"] == "25"
    assert bundle["measurement_results"][0]["value_payload"]["value"] == 940
    assert bundle["measurement_results"][0]["evidence_ids"] == ["anchor-result"]
    assert bundle["comparisons"][0]["comparison_id"] == "row-1"
    assert bundle["comparisons"][0]["comparison_metric"] == "yield_strength"
    assert bundle["observations"][0]["sample_id"] == "var-1"
    assert bundle["evidence"][0]["quote_or_cell"] == "S1 YS 940 MPa"
    assert bundle["comparison_rows"][0]["source"] == {
        "artifact": "comparison_rows.parquet",
        "row": 1,
    }


def test_export_prediction_bundle_allows_missing_artifacts(tmp_path):
    exporter = _load_exporter_module()
    output_dir = tmp_path / "collection-output"
    output_dir.mkdir()
    prediction_path = tmp_path / "generated" / "prediction_bundle.json"

    exporter.export_prediction_bundle(
        source_output_dir=output_dir,
        output_path=prediction_path,
    )

    bundle = json.loads(prediction_path.read_text(encoding="utf-8"))
    assert bundle["papers"] == []
    assert bundle["samples"] == []
    assert bundle["metadata"]["artifact_rows"]["documents"] == 0
    assert "documents.parquet" in bundle["metadata"]["missing_artifacts"]


def _write_system_artifact_placeholders(output_dir: Path) -> dict[str, pd.DataFrame]:
    frames = {
        "documents": pd.DataFrame(
            [
                {
                    "id": "paper-1",
                    "title": "Prediction Paper",
                    "text": "S1 YS 940 MPa",
                    "doi": "10.1000/test",
                }
            ]
        ),
        "document_profiles": pd.DataFrame(
            [
                {
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "title": "Prediction Paper",
                    "source_filename": "paper.pdf",
                    "doc_type": "experimental",
                    "protocol_extractable": "yes",
                    "protocol_extractability_signals": [],
                    "parsing_warnings": [],
                    "confidence": 0.9,
                }
            ]
        ),
        "evidence_anchors": pd.DataFrame(
            [
                {
                    "anchor_id": "anchor-result",
                    "document_id": "paper-1",
                    "locator_type": "table_row",
                    "locator_confidence": "direct",
                    "source_type": "table",
                    "section_id": "Results",
                    "char_range": None,
                    "bbox": None,
                    "page": 3,
                    "quote": "S1 YS 940 MPa",
                    "deep_link": None,
                    "block_id": None,
                    "snippet_id": None,
                    "figure_or_table": "Table 1",
                    "quote_span": None,
                }
            ]
        ),
        "method_facts": pd.DataFrame(
            [
                {
                    "method_id": "mf-1",
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "domain_profile": "pbf_metal",
                    "method_role": "process",
                    "method_name": "LPBF",
                    "method_payload": '{"scan_speed_mm_s": 1200}',
                    "evidence_anchor_ids": '["anchor-method"]',
                    "confidence": 0.8,
                    "epistemic_status": "normalized_from_evidence",
                }
            ]
        ),
        "sample_variants": pd.DataFrame(
            [
                {
                    "variant_id": "var-1",
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "domain_profile": "pbf_metal",
                    "variant_label": "S1",
                    "host_material_system": '{"composition": "Ti-6Al-4V"}',
                    "composition": "Ti-6Al-4V",
                    "variable_axis_type": "post_treatment",
                    "variable_value": "as-built",
                    "process_context": (
                        '{"laser_power_w": 280, '
                        '"build_orientation": "vertical"}'
                    ),
                    "profile_payload": "{}",
                    "structure_feature_ids": '["sf-1"]',
                    "source_anchor_ids": '["anchor-sample"]',
                    "confidence": 0.91,
                    "epistemic_status": "normalized_from_evidence",
                }
            ]
        ),
        "test_conditions": pd.DataFrame(
            [
                {
                    "test_condition_id": "tc-1",
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "domain_profile": "pbf_metal",
                    "property_type": "yield_strength",
                    "template_type": "tensile_mechanics",
                    "scope_level": "result",
                    "condition_payload": (
                        '{"test_temperature_c": 25, '
                        '"strain_rate_s-1": "1e-3"}'
                    ),
                    "condition_completeness": "partial",
                    "missing_fields": '["surface_condition"]',
                    "evidence_anchor_ids": '["anchor-condition"]',
                    "confidence": 0.87,
                    "epistemic_status": "normalized_from_evidence",
                }
            ]
        ),
        "baseline_references": pd.DataFrame(
            [
                {
                    "baseline_id": "base-1",
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "domain_profile": "pbf_metal",
                    "variant_id": "var-0",
                    "baseline_type": "same_paper_control",
                    "baseline_label": "control",
                    "baseline_scope": "current_paper",
                    "evidence_anchor_ids": '["anchor-baseline"]',
                    "confidence": 0.82,
                    "epistemic_status": "normalized_from_evidence",
                }
            ]
        ),
        "measurement_results": pd.DataFrame(
            [
                {
                    "result_id": "res-1",
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "domain_profile": "pbf_metal",
                    "variant_id": "var-1",
                    "property_normalized": "yield_strength",
                    "result_type": "scalar",
                    "claim_scope": "current_work",
                    "value_payload": '{"value": 940, "source_value_text": "940"}',
                    "unit": "MPa",
                    "test_condition_id": "tc-1",
                    "baseline_id": "base-1",
                    "structure_feature_ids": '["sf-1"]',
                    "characterization_observation_ids": '["obs-1"]',
                    "evidence_anchor_ids": '["anchor-result"]',
                    "traceability_status": "direct",
                    "result_source_type": "table",
                    "epistemic_status": "normalized_from_evidence",
                }
            ]
        ),
        "characterization_observations": pd.DataFrame(
            [
                {
                    "observation_id": "obs-1",
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "variant_id": "var-1",
                    "characterization_type": "porosity",
                    "observation_text": "low porosity",
                    "observed_value": None,
                    "observed_unit": None,
                    "condition_context": "{}",
                    "evidence_anchor_ids": '["anchor-observation"]',
                    "confidence": 0.8,
                    "epistemic_status": "normalized_from_evidence",
                }
            ]
        ),
        "structure_features": pd.DataFrame(
            [
                {
                    "feature_id": "sf-1",
                    "document_id": "paper-1",
                    "collection_id": "col-test",
                    "variant_id": "var-1",
                    "feature_type": "porosity",
                    "feature_value": None,
                    "feature_unit": None,
                    "qualitative_descriptor": "low porosity",
                    "source_observation_ids": '["obs-1"]',
                    "confidence": 0.8,
                    "epistemic_status": "normalized_from_evidence",
                }
            ]
        ),
        "comparable_results": pd.DataFrame(
            [
                {
                    "comparable_result_id": "cres-1",
                    "source_result_id": "res-1",
                    "source_document_id": "paper-1",
                    "binding": "{}",
                    "normalized_context": "{}",
                    "axis": "{}",
                    "value": '{"numeric_value": 940}',
                    "evidence": "{}",
                    "variant_label": "S1",
                    "baseline_reference": "control",
                    "result_source_type": "table",
                    "epistemic_status": "normalized_from_evidence",
                    "normalization_version": "test",
                }
            ]
        ),
        "collection_comparable_results": pd.DataFrame(
            [
                {
                    "collection_id": "col-test",
                    "comparable_result_id": "cres-1",
                    "assessment": "{}",
                    "epistemic_status": "normalized_from_evidence",
                    "included": True,
                    "sort_order": 0,
                    "policy_family": "test",
                    "policy_version": "test",
                    "comparable_result_normalization_version": "test",
                    "assessment_input_fingerprint": "fingerprint",
                    "reassessment_triggers": "[]",
                }
            ]
        ),
        "comparison_rows": pd.DataFrame(
            [
                {
                    "row_id": "row-1",
                    "collection_id": "col-test",
                    "comparable_result_id": "cres-1",
                    "source_document_id": "paper-1",
                    "variant_id": "var-1",
                    "variant_label": "S1",
                    "variable_axis": "post_treatment",
                    "variable_value": "as-built",
                    "baseline_reference": "control",
                    "result_source_type": "table",
                    "result_type": "scalar",
                    "result_summary": "YS 940 MPa",
                    "supporting_evidence_ids": '["ev-res-1"]',
                    "supporting_anchor_ids": '["anchor-result"]',
                    "characterization_observation_ids": '["obs-1"]',
                    "structure_feature_ids": '["sf-1"]',
                    "material_system_normalized": "Ti-6Al-4V",
                    "process_normalized": "LPBF",
                    "property_normalized": "yield_strength",
                    "baseline_normalized": "control",
                    "test_condition_normalized": "tensile",
                    "comparability_status": "comparable",
                    "comparability_warnings": "[]",
                    "comparability_basis": "{}",
                    "requires_expert_review": False,
                    "assessment_epistemic_status": "normalized_from_evidence",
                    "missing_critical_context": "[]",
                    "value": 940,
                    "unit": "MPa",
                }
            ]
        ),
    }
    for name in frames:
        (output_dir / f"{name}.parquet").write_text("", encoding="utf-8")
    return frames
