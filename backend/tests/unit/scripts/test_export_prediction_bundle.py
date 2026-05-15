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


def test_export_prediction_bundle_projects_objective_uncertainties(tmp_path):
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
            "evidence_unit_id": "oeu-unresolved-1",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "resolution_status": "unresolved",
            "confidence": 0.3,
        }
    ]
    records_by_artifact["objective_logic_chains"] = [
        {
            "logic_chain_id": "olc-1",
            "objective_id": "obj-1",
            "document_id": "paper-1",
            "chain_payload": {
                "cross_paper": {
                    "gaps": [
                        "comparison_units_missing",
                    ]
                }
            },
        }
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=["baseline_references"],
        fact_source="objective_first",
    )

    assert bundle["uncertainties"] == [
        {
            "paper_id": "paper-1",
            "issue_id": "objective-unit-unresolved-oeu-unresolved-1",
            "description": (
                "Objective evidence unit oeu-unresolved-1 has "
                "resolution_status=unresolved."
            ),
            "impact": (
                "The related sample, condition, measurement, or comparison "
                "context may be incomplete."
            ),
            "source": {"artifact": "objective_evidence_units", "row": 1},
        },
        {
            "paper_id": "paper-1",
            "issue_id": "objective-logic-gap-olc-1-comparison_units_missing",
            "description": (
                "Objective logic chain olc-1 reports gap "
                "comparison_units_missing."
            ),
            "impact": "The assembled research chain is incomplete for objective obj-1.",
            "source": {"artifact": "objective_logic_chains", "row": 1},
        },
        {
            "paper_id": "",
            "issue_id": "missing-artifact-baseline_references",
            "description": "Repository artifact baseline_references is missing.",
            "impact": (
                "The related evidence family cannot be evaluated from this "
                "prediction bundle."
            ),
            "source": {"artifact": "metadata.missing_artifacts", "row": None},
        },
    ]


def test_export_prediction_bundle_projects_objective_measurement_pairs(tmp_path):
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
            "evidence_unit_id": "measure-1",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {"sample_number": 1},
            "value_payload": {"value": 200.0, "source_value_text": "200"},
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
            "evidence_unit_id": "measure-2",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {"sample_number": 2},
            "value_payload": {"value": 220.0, "source_value_text": "220"},
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
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert len(bundle["comparisons"]) == 2
    assert bundle["comparisons"][0] == {
        "paper_id": "paper-1",
        "comparison_id": "objective-measurement-pair-measure-1-measure-2",
        "current_sample_id": "obj-sample-paper-1-sample-1",
        "baseline_reference": "obj-sample-paper-1-sample-2",
        "baseline_sample_ids": ["obj-sample-paper-1-sample-2"],
        "comparison_type": "objective_measurement_pair",
        "comparison_axis": "sample_context",
        "comparison_metric": "yield strength",
        "metric_name": "yield strength",
        "current_value": 200.0,
        "baseline_value": 220.0,
        "unit": "MPa",
        "change_direction": "decrease",
        "direction": "decrease",
        "result_summary": "Sample 1 vs Sample 2 for yield strength",
        "comparability_status": "projected",
        "comparability_warnings": [],
        "evidence_ids": ["objective-source:table:table-1"],
        "anchor_ids": ["objective-source:table:table-1"],
        "relation_payload": {
            "current_evidence_unit_id": "measure-1",
            "baseline_evidence_unit_id": "measure-2",
            "projection_source": "objective_measurement_pair",
        },
        "source": {"artifact": "objective_evidence_units", "row": 1},
    }


def test_export_prediction_bundle_limits_condition_matrix_pairs(tmp_path):
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
            "evidence_unit_id": f"measure-{sample_number}",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {
                "Condition number": condition_number,
                "Sample number": sample_number,
            },
            "value_payload": {
                "value": 200 + sample_number,
                "source_value_text": str(200 + sample_number),
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
        }
        for condition_number, sample_numbers in ((1, (1, 2, 3)), (2, (4, 5, 6)))
        for sample_number in sample_numbers
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert len(bundle["comparisons"]) == 18
    comparison_pairs = {
        (
            comparison["current_sample_id"].rsplit("-", 1)[-1],
            comparison["baseline_reference"].rsplit("-", 1)[-1],
        )
        for comparison in bundle["comparisons"]
    }
    assert ("1", "4") in comparison_pairs
    assert ("4", "1") in comparison_pairs
    assert ("1", "5") not in comparison_pairs
    assert ("5", "1") not in comparison_pairs


def test_export_prediction_bundle_skips_uncontrolled_large_pair_groups(tmp_path):
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
            "evidence_unit_id": f"measure-{sample_number}",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {"sample_number": sample_number},
            "value_payload": {
                "value": 200 + sample_number,
                "source_value_text": str(200 + sample_number),
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
        }
        for sample_number in range(1, 7)
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert bundle["comparisons"] == []


def test_export_prediction_bundle_pairs_numbered_treatment_series(tmp_path):
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
            "evidence_unit_id": f"measure-{sample_number}",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "tensile strength",
            "sample_context": {
                "Specimens": specimen,
                "sample_number": sample_number,
            },
            "value_payload": {
                "value": value,
                "source_value_text": str(value),
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
        }
        for sample_number, specimen, value in (
            (11, "as-SLM (120/100)", 593.0),
            (12, "HT-SLM (120/100)", 570.2),
            (13, "HIP-SLM (120/100)", 573.9),
            (17, "as-SLM (120/200)", 251.8),
            (18, "HT-SLM (120/200)", 497.0),
            (19, "HIP-SLM (120/200)", 506.5),
        )
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    comparison_index = {
        (
            comparison["current_sample_id"].rsplit("-", 1)[-1],
            comparison["baseline_reference"].rsplit("-", 1)[-1],
            comparison["current_value"],
            comparison["baseline_value"],
        )
        for comparison in bundle["comparisons"]
    }

    assert ("12", "11", 570.2, 593.0) in comparison_index
    assert ("13", "11", 573.9, 593.0) in comparison_index
    assert ("18", "17", 497.0, 251.8) in comparison_index
    assert ("19", "17", 506.5, 251.8) in comparison_index
    assert ("17", "11", 251.8, 593.0) not in comparison_index
    assert len(bundle["comparisons"]) == 4


def test_export_prediction_bundle_uses_main_value_from_uncertainty_first_text(
    tmp_path,
):
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
            "evidence_unit_id": evidence_unit_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {
                "Specimens": specimen,
                "sample_number": sample_number,
            },
            "value_payload": {
                "value": extracted_value,
                "source_value_text": source_value_text,
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
        }
        for evidence_unit_id, sample_number, specimen, extracted_value, source_value_text in (
            (
                "measure-11",
                11,
                "as-SLM (120/100)",
                10.2,
                "( 10.2) 464.8 ( +/- 5.8)",
            ),
            (
                "measure-12",
                12,
                "HT-SLM (120/100)",
                570.2,
                "570.2 ( +/- 9.1)",
            ),
            (
                "measure-13",
                13,
                "HIP-SLM (120/100)",
                2.1,
                "( +/- 2.1) 180.5",
            ),
        )
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    measurement_values = {
        measurement["result_id"]: measurement["value_payload"]["value"]
        for measurement in bundle["measurement_results"]
    }
    comparison_index = {
        (
            comparison["current_sample_id"].rsplit("-", 1)[-1],
            comparison["baseline_reference"].rsplit("-", 1)[-1],
            comparison["current_value"],
            comparison["baseline_value"],
        )
        for comparison in bundle["comparisons"]
    }

    assert measurement_values["measure-11"] == 464.8
    assert measurement_values["measure-12"] == 570.2
    assert measurement_values["measure-13"] == 180.5
    assert ("12", "11", 570.2, 464.8) in comparison_index
    assert ("13", "11", 180.5, 464.8) in comparison_index


def test_export_prediction_bundle_ignores_uncertainty_only_pair_candidates(tmp_path):
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
            "evidence_unit_id": f"measure-{sample_label.lower()}",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "TE [%]",
            "sample_context": {"Printed > 316L": sample_label},
            "value_payload": {
                "value": value,
                "source_value_text": f"{value} +/- 1.1",
            },
            "unit": None,
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 7,
                }
            ],
            "resolution_status": "resolved",
        }
        for sample_label, value in (
            ("L-VED", 33.2),
            ("M-VED", 37.3),
            ("H-VED", 48.3),
            ("Wrought 316L", 54.0),
        )
    ]
    records_by_artifact["objective_evidence_units"].append(
        {
            "evidence_unit_id": "measure-l-uncertainty",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "total elongation",
            "sample_context": {"Printed > 316L": "L-VED"},
            "value_payload": {
                "value": 1.1,
                "source_value_text": "+/- 1.1",
            },
            "unit": "%",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 7,
                }
            ],
            "resolution_status": "resolved",
        }
    )

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert len(bundle["comparisons"]) == 12
    assert {
        comparison["current_value"]
        for comparison in bundle["comparisons"]
    } == {33.2, 37.3, 48.3, 54.0}


def test_export_prediction_bundle_projects_structural_context_pairs(tmp_path):
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
            "evidence_unit_id": f"density-{sample_label.lower()}",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "material density",
            "sample_context": {
                "sample_id": sample_label,
                "grain_size_eq_diameter": grain_size,
                "melt_pool_width": melt_pool_width,
            },
            "process_context": {"volumetric_energy_density": sample_label},
            "value_payload": {
                "value": density,
                "source_value_text": str(density),
            },
            "unit": "%",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-structure",
                    "page": 5,
                }
            ],
            "resolution_status": "resolved",
        }
        for sample_label, density, grain_size, melt_pool_width in (
            ("L-VED", 91.9, 81, 148),
            ("M-VED", 98.92, 108, 166),
            ("H-VED", 99.6, 115, 190),
        )
    ]
    records_by_artifact["objective_evidence_units"].append(
        {
            "evidence_unit_id": "defect-map",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "defect size",
            "sample_context": {"defect_structure": "complex defects"},
            "value_payload": {
                "maximum_defect_diameter": {
                    "H-VED": 50,
                    "L-VED": 76,
                    "M-VED": 54,
                }
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-defects",
                    "page": 5,
                }
            ],
            "resolution_status": "resolved",
        }
    )

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    comparison_index = {
        (
            comparison["comparison_metric"],
            comparison["current_sample_id"].rsplit("-", 2)[-2],
            comparison["baseline_reference"].rsplit("-", 2)[-2],
            comparison["current_value"],
            comparison["baseline_value"],
        )
        for comparison in bundle["comparisons"]
    }

    assert (
        "equivalent_grain_diameter",
        "h",
        "l",
        115.0,
        81.0,
    ) in comparison_index
    assert ("melt_pool_width", "h", "l", 190.0, 148.0) in comparison_index
    assert (
        "maximum_defect_diameter",
        "h",
        "l",
        50.0,
        76.0,
    ) in comparison_index
    assert (
        "maximum_defect_diameter",
        "h",
        "m",
        50.0,
        54.0,
    ) in comparison_index


def test_export_prediction_bundle_projects_characterization_value_map_pairs(tmp_path):
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
            "evidence_unit_id": "defect-map",
            "document_id": "paper-1",
            "unit_kind": "characterization",
            "property_normalized": "defect size",
            "sample_context": {"defect_structure": "complex defects"},
            "value_payload": {
                "maximum_defect_diameter": {
                    "H-VED": "50 μm",
                    "L-VED": "76 μm",
                    "M-VED": "54 μm",
                }
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-defects",
                    "page": 5,
                }
            ],
            "resolution_status": "resolved",
        }
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    comparison_index = {
        (
            comparison["comparison_metric"],
            comparison["current_sample_id"].rsplit("-", 2)[-2],
            comparison["baseline_reference"].rsplit("-", 2)[-2],
            comparison["current_value"],
            comparison["baseline_value"],
        )
        for comparison in bundle["comparisons"]
    }

    assert (
        "maximum_defect_diameter",
        "h",
        "l",
        50.0,
        76.0,
    ) in comparison_index
    assert (
        "maximum_defect_diameter",
        "h",
        "m",
        50.0,
        54.0,
    ) in comparison_index


def test_export_prediction_bundle_projects_fatigue_limit_interpretation_pairs(
    tmp_path,
):
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
            "evidence_unit_id": "fatigue-limit-map",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "fatigue strength",
            "sample_context": {"sample_type": "H-VED"},
            "value_payload": {
                "fatigue_limit": {
                    "L-VED": "80 - 100 MPa",
                    "wrought_316L": "256 MPa",
                }
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-fatigue",
                    "page": 7,
                }
            ],
            "resolution_status": "resolved",
        }
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    def sample_key(sample_id: str) -> str:
        return sample_id.removeprefix("obj-sample-paper-1-")

    comparison_index = {
        (
            comparison["comparison_metric"],
            sample_key(comparison["current_sample_id"]),
            sample_key(comparison["baseline_reference"]),
            comparison["current_value"],
            comparison["baseline_value"],
        )
        for comparison in bundle["comparisons"]
    }

    assert ("fatigue_limit", "l-ved", "wrought-316l", 80.0, 256.0) in (
        comparison_index
    )
    assert ("fatigue_limit", "h-ved", "wrought-316l", 80.0, 256.0) in (
        comparison_index
    )


def test_export_prediction_bundle_projects_objective_interpretations(tmp_path):
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
            "evidence_unit_id": "interpret-1",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "fatigue strength",
            "value_payload": {
                "fatigue_limit": {
                    "printed": "80 - 100 MPa",
                    "wrought_316L": "256 MPa",
                }
            },
            "interpretation": {
                "fatigue_limit": {
                    "printed": "80 - 100 MPa",
                    "wrought_316L": "256 MPa",
                }
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                    "page": 7,
                }
            ],
            "resolution_status": "resolved",
        }
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-objective",
        source_output_dir=tmp_path / "output",
        records_by_artifact=records_by_artifact,
        missing_artifacts=[],
        fact_source="objective_first",
    )

    assert bundle["observations"] == [
        {
            "paper_id": "paper-1",
            "observation_id": "interpret-1",
            "sample_id": "",
            "sample_ids": [],
            "characterization_method": "fatigue strength",
            "observed_object": "fatigue strength",
            "value_or_description": {
                "fatigue_limit": {
                    "printed": "80 - 100 MPa",
                    "wrought_316L": "256 MPa",
                }
            },
            "unit": "",
            "author_interpretation": (
                '{"fatigue_limit": {"printed": "80 - 100 MPa", '
                '"wrought_316L": "256 MPa"}}'
            ),
            "condition_context": None,
            "evidence_ids": ["objective-source:text_window:block-1"],
            "confidence": None,
            "epistemic_status": "resolved",
            "source": {"artifact": "objective_evidence_units", "row": 1},
        }
    ]


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


def test_export_prediction_bundle_normalizes_objective_metric_aliases(tmp_path):
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
            "evidence_unit_id": "oeu-yield",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "\u0131 y",
            "sample_context": {"sample_number": 1},
            "value_payload": {"value": 448},
            "unit": "MPa",
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-ultimate",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "\u0131 u",
            "sample_context": {"sample_number": 1},
            "value_payload": {"value": 617},
            "unit": "MPa",
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-elongation",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "EL%",
            "sample_context": {"sample_number": 1},
            "value_payload": {"value": 72},
            "unit": "%",
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-compact-yield",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "YS > [MPa]",
            "sample_context": {"sample_number": 2},
            "value_payload": {"value": 437},
            "unit": None,
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-compact-ultimate",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "UTS > [MPa]",
            "sample_context": {"sample_number": 2},
            "value_payload": {"value": 560},
            "unit": None,
            "resolution_status": "resolved",
        },
        {
            "evidence_unit_id": "oeu-compact-elongation",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "TE [%]",
            "sample_context": {"sample_number": 2},
            "value_payload": {"value": 48.3},
            "unit": None,
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
        result["metric_name"]
        for result in bundle["measurement_results"]
    ] == [
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "yield strength",
        "ultimate tensile strength",
        "elongation",
    ]
    assert [
        result["unit"]
        for result in bundle["measurement_results"]
    ] == ["MPa", "MPa", "%", "MPa", "MPa", "%"]


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
