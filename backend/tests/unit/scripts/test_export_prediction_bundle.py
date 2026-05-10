from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from domain.core import (
    BaselineReference,
    CharacterizationObservation,
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    CoreFactSet,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    SampleVariant,
    StructureFeature,
    TestCondition,
)
from domain.source import SourceArtifactSet
from infra.persistence.sqlite import SqliteCoreFactRepository, SqliteSourceArtifactRepository


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


def test_export_prediction_bundle_writes_gold_aligned_system_output(tmp_path):
    exporter = _load_exporter_module()
    backend_root = tmp_path / "backend"
    collection_id = "col-test"
    _write_system_artifacts(backend_root, collection_id)
    prediction_path = tmp_path / "generated" / "prediction_bundle.json"

    result_path = exporter.export_prediction_bundle(
        backend_root=backend_root,
        collection_id=collection_id,
        output_path=prediction_path,
    )

    assert result_path == prediction_path
    bundle = json.loads(prediction_path.read_text(encoding="utf-8"))
    assert bundle["metadata"]["schema_version"] == "prediction-bundle-v0.1"
    assert bundle["metadata"]["collection_id"] == collection_id
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
        "artifact": "comparison_rows",
        "row": 1,
    }


def test_export_prediction_bundle_allows_missing_artifacts(tmp_path):
    exporter = _load_exporter_module()
    backend_root = tmp_path / "backend"
    collection_id = "col-empty"
    prediction_path = tmp_path / "generated" / "prediction_bundle.json"

    exporter.export_prediction_bundle(
        backend_root=backend_root,
        collection_id=collection_id,
        output_path=prediction_path,
    )

    bundle = json.loads(prediction_path.read_text(encoding="utf-8"))
    assert bundle["papers"] == []
    assert bundle["samples"] == []
    assert bundle["metadata"]["artifact_rows"]["documents"] == 0
    assert "documents" in bundle["metadata"]["missing_artifacts"]


def _write_system_artifacts(backend_root: Path, collection_id: str) -> None:
    db_path = backend_root / "data" / "lens.sqlite"
    SqliteSourceArtifactRepository(db_path).replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Prediction Paper",
                    "text": "S1 YS 940 MPa",
                    "metadata": {"doi": "10.1000/test"},
                }
            ],
        ),
    )
    SqliteCoreFactRepository(db_path).replace_collection_facts(
        collection_id,
        CoreFactSet(
            document_profiles=(
                DocumentProfile.from_mapping(
                    {
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "title": "Prediction Paper",
                        "source_filename": "paper.pdf",
                        "doc_type": "experimental",
                        "protocol_extractable": "yes",
                        "protocol_extractability_signals": [],
                        "parsing_warnings": [],
                        "confidence": 0.9,
                    }
                ),
            ),
            evidence_anchors=(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-result",
                        "document_id": "paper-1",
                        "locator_type": "table_row",
                        "locator_confidence": "direct",
                        "source_type": "table",
                        "section_id": "Results",
                        "page": 3,
                        "quote": "S1 YS 940 MPa",
                        "figure_or_table": "Table 1",
                    }
                ),
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-sample",
                        "document_id": "paper-1",
                        "locator_type": "text",
                        "locator_confidence": "direct",
                        "source_type": "text",
                        "quote": "S1 was printed by LPBF.",
                    }
                ),
            ),
            method_facts=(
                MethodFact.from_mapping(
                    {
                        "method_id": "method-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "domain_profile": "materials",
                        "method_role": "process",
                        "method_name": "LPBF",
                        "method_payload": {"laser_power_w": 200},
                        "evidence_anchor_ids": ["anchor-sample"],
                        "confidence": 0.9,
                    }
                ),
            ),
            sample_variants=(
                SampleVariant.from_mapping(
                    {
                        "variant_id": "var-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "domain_profile": "materials",
                        "variant_label": "S1",
                        "host_material_system": {"normalized": "Ti-6Al-4V"},
                        "composition": "Ti-6Al-4V",
                        "variable_axis_type": "post_treatment",
                        "variable_value": "as-built",
                        "process_context": {"laser_power_w": 200},
                        "profile_payload": {},
                        "structure_feature_ids": ["sf-1"],
                        "source_anchor_ids": ["anchor-sample"],
                        "confidence": 0.8,
                    }
                ),
            ),
            test_conditions=(
                TestCondition.from_mapping(
                    {
                        "test_condition_id": "tc-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "domain_profile": "materials",
                        "property_type": "yield_strength",
                        "template_type": "mechanical",
                        "scope_level": "variant",
                        "condition_payload": {"test_temperature_c": 25},
                        "condition_completeness": "complete",
                        "missing_fields": [],
                        "evidence_anchor_ids": ["anchor-result"],
                        "confidence": 0.8,
                    }
                ),
            ),
            baseline_references=(
                BaselineReference.from_mapping(
                    {
                        "baseline_id": "base-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "domain_profile": "materials",
                        "variant_id": "var-1",
                        "baseline_type": "control",
                        "baseline_label": "control",
                        "baseline_scope": "same_paper",
                        "evidence_anchor_ids": ["anchor-result"],
                        "confidence": 0.8,
                    }
                ),
            ),
            measurement_results=(
                MeasurementResult.from_mapping(
                    {
                        "result_id": "res-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "domain_profile": "materials",
                        "variant_id": "var-1",
                        "property_normalized": "yield_strength",
                        "result_type": "scalar",
                        "claim_scope": "variant",
                        "value_payload": {"value": 940},
                        "unit": "MPa",
                        "test_condition_id": "tc-1",
                        "baseline_id": "base-1",
                        "structure_feature_ids": ["sf-1"],
                        "characterization_observation_ids": ["obs-1"],
                        "evidence_anchor_ids": ["anchor-result"],
                        "traceability_status": "direct",
                        "result_source_type": "table",
                    }
                ),
            ),
            characterization_observations=(
                CharacterizationObservation.from_mapping(
                    {
                        "observation_id": "obs-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "variant_id": "var-1",
                        "characterization_type": "microstructure",
                        "observation_text": "fine grains",
                        "observed_value": {"text": "fine grains"},
                        "observed_unit": None,
                        "condition_context": {},
                        "evidence_anchor_ids": ["anchor-result"],
                        "confidence": 0.7,
                    }
                ),
            ),
            structure_features=(
                StructureFeature.from_mapping(
                    {
                        "feature_id": "sf-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "variant_id": "var-1",
                        "feature_type": "grain",
                        "feature_value": {"text": "fine"},
                        "source_observation_ids": ["obs-1"],
                        "confidence": 0.7,
                    }
                ),
            ),
            comparable_results=(
                ComparableResult.from_mapping(
                    {
                        "comparable_result_id": "cres-1",
                        "source_result_id": "res-1",
                        "source_document_id": "paper-1",
                        "binding": {
                            "variant_id": "var-1",
                            "test_condition_id": "tc-1",
                            "baseline_id": "base-1",
                        },
                        "normalized_context": {
                            "material_system_normalized": "Ti-6Al-4V",
                            "process_normalized": "LPBF",
                            "property_normalized": "yield_strength",
                            "baseline_normalized": "control",
                            "test_condition_normalized": "tensile",
                        },
                        "axis": {"variable_axis": "post_treatment"},
                        "value": {
                            "property_normalized": "yield_strength",
                            "result_type": "scalar",
                            "result_summary": "YS 940 MPa",
                            "value": 940,
                            "unit": "MPa",
                        },
                        "evidence": {
                            "supporting_evidence_ids": ["ev-res-1"],
                            "supporting_anchor_ids": ["anchor-result"],
                        },
                        "variant_label": "S1",
                        "baseline_reference": "control",
                        "result_source_type": "table",
                    }
                ),
            ),
            collection_comparable_results=(
                CollectionComparableResult.from_mapping(
                    {
                        "collection_id": collection_id,
                        "comparable_result_id": "cres-1",
                        "assessment": {"status": "comparable"},
                        "included": True,
                        "sort_order": 0,
                    }
                ),
            ),
            comparison_rows=(
                ComparisonRowRecord.from_mapping(
                    {
                        "row_id": "row-1",
                        "collection_id": collection_id,
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
                        "supporting_evidence_ids": ["ev-res-1"],
                        "supporting_anchor_ids": ["anchor-result"],
                        "characterization_observation_ids": ["obs-1"],
                        "structure_feature_ids": ["sf-1"],
                        "material_system_normalized": "Ti-6Al-4V",
                        "process_normalized": "LPBF",
                        "property_normalized": "yield_strength",
                        "baseline_normalized": "control",
                        "test_condition_normalized": "tensile",
                        "comparability_status": "comparable",
                        "comparability_warnings": [],
                        "comparability_basis": {},
                        "requires_expert_review": False,
                        "assessment_epistemic_status": "normalized_from_evidence",
                        "missing_critical_context": [],
                        "value": 940,
                        "unit": "MPa",
                    }
                ),
            ),
        ),
    )
