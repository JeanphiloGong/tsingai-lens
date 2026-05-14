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
    PairwiseComparisonRelation,
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
    assert bundle["metadata"]["artifact_rows"]["pairwise_comparison_relations"] == 1
    assert bundle["papers"][0]["paper_id"] == "paper-1"
    assert bundle["papers"][0]["title"] == "Prediction Paper"
    sample = next(row for row in bundle["samples"] if row["sample_id"] == "var-1")
    assert sample["evidence_ids"] == ["anchor-sample"]
    assert any(
        record["original_parameter_name"] == "laser_power_w"
        and record["sample_reference"] == "var-1"
        for record in bundle["process_parameters"]
    )
    assert bundle["test_conditions"][0]["test_temperature"] == "25"
    assert bundle["measurement_results"][0]["value_payload"]["value"] == 940
    assert bundle["measurement_results"][0]["evidence_ids"] == ["anchor-result"]
    assert bundle["comparisons"][0]["comparison_id"] == "rel-1"
    assert bundle["comparisons"][0]["current_sample_id"] == "var-1"
    assert bundle["comparisons"][0]["baseline_sample_ids"] == ["var-0"]
    assert bundle["comparisons"][0]["comparison_metric"] == "yield_strength"
    assert bundle["observations"][0]["sample_id"] == "var-1"
    assert bundle["evidence"][0]["quote_or_cell"] == "S1 YS 940 MPa"
    assert bundle["comparison_rows"][0]["source"] == {
        "artifact": "comparison_rows",
        "row": 1,
    }

    output_dir_prediction_path = tmp_path / "generated" / "prediction_from_output.json"
    collection_output_dir = backend_root / "data" / "collections" / collection_id / "output"
    collection_output_dir.mkdir(parents=True)
    exporter.export_prediction_bundle(
        backend_root=backend_root,
        source_output_dir=collection_output_dir,
        output_path=output_dir_prediction_path,
    )
    output_dir_bundle = json.loads(
        output_dir_prediction_path.read_text(encoding="utf-8")
    )
    assert output_dir_bundle["metadata"]["collection_id"] == collection_id
    assert output_dir_bundle["comparisons"][0]["comparison_id"] == "rel-1"

    run_root = tmp_path / "probe-run"
    run_collection_id = "col-run"
    run_output_dir = run_root / "collections" / run_collection_id / "output"
    run_output_dir.mkdir(parents=True)
    _write_system_artifacts_to_db(run_root / "lens.sqlite", run_collection_id)
    run_output_prediction_path = tmp_path / "generated" / "prediction_from_run.json"

    exporter.export_prediction_bundle(
        backend_root=backend_root,
        source_output_dir=run_output_dir,
        output_path=run_output_prediction_path,
    )

    run_output_bundle = json.loads(
        run_output_prediction_path.read_text(encoding="utf-8")
    )
    assert run_output_bundle["metadata"]["collection_id"] == run_collection_id
    assert run_output_bundle["measurement_results"][0]["result_id"] == "res-1"


def test_export_prediction_bundle_projects_objective_first_units(tmp_path):
    exporter = _load_exporter_module()
    records_by_artifact = {name: [] for name in exporter.ARTIFACT_NAMES}
    records_by_artifact["documents"] = [
        {
            "id": "paper-1",
            "title": "Objective Paper",
            "metadata": {"doi": "10.1000/objective"},
        }
    ]
    records_by_artifact["document_profiles"] = [
        {
            "document_id": "paper-1",
            "title": "Objective Paper",
            "doc_type": "experimental",
        }
    ]
    records_by_artifact["objective_evidence_units"] = [
        {
            "evidence_unit_id": "oeu-process-1",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "sample_context": {"sample_number": 1},
            "process_context": {"laser_power_w": 200},
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 3,
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-test-1",
            "document_id": "paper-1",
            "unit_kind": "test_condition",
            "property_normalized": "yield strength",
            "test_condition": {
                "test_method": "tensile test",
                "test_temperature_c": 25,
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                    "page": 2,
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.8,
        },
        {
            "evidence_unit_id": "oeu-measure-1",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {"sample_number": 1},
            "process_context": {"laser_power_w": 200},
            "value_payload": {"value": 940, "source_value_text": "940"},
            "unit": "MPa",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 3,
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        },
        {
            "evidence_unit_id": "oeu-comparison-1",
            "document_id": "paper-1",
            "unit_kind": "comparison",
            "property_normalized": "yield strength",
            "sample_context": {"sample_number": 1},
            "baseline_context": {
                "sample_context": {"sample_number": 0},
                "value": 880,
            },
            "value_payload": {
                "value": 940,
                "direction": "increase",
                "comparison_axis": "laser_power_w",
            },
            "unit": "MPa",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 3,
                }
            ],
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-characterization-1",
            "document_id": "paper-1",
            "unit_kind": "characterization",
            "property_normalized": "microstructure",
            "sample_context": {"sample_number": 1},
            "value_payload": {"summary": "fine grains"},
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-2",
                    "page": 5,
                }
            ],
            "resolution_status": "resolved",
        },
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert bundle["metadata"]["fact_source"] == "objective_first"
    assert bundle["metadata"]["artifact_rows"]["objective_evidence_units"] == 5
    assert bundle["papers"][0]["paper_id"] == "paper-1"
    assert bundle["samples"][0]["label_in_paper"] == "Sample 1"
    assert bundle["process_parameters"][0]["original_parameter_name"] == (
        "laser_power_w"
    )
    assert bundle["test_conditions"][0]["test_type"] == "yield strength"
    assert bundle["test_conditions"][0]["test_temperature"] == "25"
    assert bundle["measurement_results"][0]["result_id"] == "oeu-measure-1"
    assert bundle["measurement_results"][0]["value_or_trend"] == "940"
    assert bundle["measurement_results"][0]["sample_id"] == (
        "obj-sample-paper-1-sample-1"
    )
    assert bundle["comparisons"][0]["current_value"] == 940
    assert bundle["comparisons"][0]["baseline_value"] == 880
    assert bundle["comparisons"][0]["baseline_sample_ids"] == [
        "obj-sample-paper-1-sample-0"
    ]
    assert bundle["observations"][0]["value_or_description"] == "fine grains"
    assert {
        evidence["evidence_id"]
        for evidence in bundle["evidence"]
    } == {
        "objective-source:table:table-1",
        "objective-source:text_window:block-1",
        "objective-source:text_window:block-2",
    }
    assert bundle["objective_evidence_units"][0]["source"] == {
        "artifact": "objective_evidence_units",
        "row": 1,
    }


def test_export_prediction_bundle_prefers_objective_sample_number(tmp_path):
    exporter = _load_exporter_module()
    records_by_artifact = {name: [] for name in exporter.ARTIFACT_NAMES}
    records_by_artifact["documents"] = [
        {
            "id": "paper-1",
            "title": "Objective Paper",
        }
    ]
    records_by_artifact["objective_evidence_units"] = [
        {
            "evidence_unit_id": "oeu-measure-1",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "density",
            "sample_context": {
                "label": "135 W-750 mm·s -1",
                "sample_number": 1,
            },
            "value_payload": {"value": 99.26, "source_value_text": "99.26"},
            "unit": "%",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 3,
                }
            ],
            "resolution_status": "resolved",
        },
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert bundle["samples"][0]["label_in_paper"] == "Sample 1"
    assert bundle["samples"][0]["sample_description"] == "135 W-750 mm·s -1"
    assert bundle["measurement_results"][0]["sample_id"] == (
        "obj-sample-paper-1-sample-1"
    )


def test_export_prediction_bundle_infers_objective_sample_labels(tmp_path):
    exporter = _load_exporter_module()
    records_by_artifact = {name: [] for name in exporter.ARTIFACT_NAMES}
    records_by_artifact["documents"] = [
        {
            "id": "paper-1",
            "title": "Objective Paper",
        }
    ]
    records_by_artifact["objective_evidence_units"] = [
        {
            "evidence_unit_id": "oeu-density-l",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "material density",
            "sample_context": {"ID": "L-VED"},
            "value_payload": {"value": 91.9},
            "unit": "%",
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-density-m",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "material density",
            "sample_context": {"Printed": "M-VED"},
            "value_payload": {"value": 98.92},
            "unit": "%",
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-density-h",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "material density",
            "sample_context": {"sample_type": "H-VED structure"},
            "value_payload": {"value": 99.6},
            "unit": "%",
            "resolution_status": "resolved",
        },
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert [
        sample["label_in_paper"]
        for sample in bundle["samples"]
    ] == ["L-VED", "M-VED", "H-VED"]
    assert [
        result["sample_id"]
        for result in bundle["measurement_results"]
    ] == [
        "obj-sample-paper-1-l-ved",
        "obj-sample-paper-1-m-ved",
        "obj-sample-paper-1-h-ved",
    ]


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
    _write_system_artifacts_to_db(db_path, collection_id)


def _write_system_artifacts_to_db(db_path: Path, collection_id: str) -> None:
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
                        "variant_id": "var-0",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "domain_profile": "materials",
                        "variant_label": "S0",
                        "host_material_system": {"normalized": "Ti-6Al-4V"},
                        "composition": "Ti-6Al-4V",
                        "variable_axis_type": "post_treatment",
                        "variable_value": "baseline",
                        "process_context": {"laser_power_w": 180},
                        "profile_payload": {},
                        "structure_feature_ids": [],
                        "source_anchor_ids": ["anchor-sample"],
                        "confidence": 0.8,
                    }
                ),
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
            pairwise_comparison_relations=(
                PairwiseComparisonRelation.from_mapping(
                    {
                        "relation_id": "rel-1",
                        "collection_id": collection_id,
                        "document_id": "paper-1",
                        "current_variant_id": "var-1",
                        "reference_variant_id": "var-0",
                        "comparison_axis": "laser_power_w",
                        "property_normalized": "yield_strength",
                        "current_result_id": "res-1",
                        "reference_result_id": "res-0",
                        "current_value": 940,
                        "reference_value": 880,
                        "unit": "MPa",
                        "direction": "increase",
                        "evidence_anchor_ids": ["anchor-result"],
                        "relation_payload": {
                            "current_variant_label": "S1",
                            "reference_variant_label": "S0",
                        },
                        "confidence": 0.8,
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
