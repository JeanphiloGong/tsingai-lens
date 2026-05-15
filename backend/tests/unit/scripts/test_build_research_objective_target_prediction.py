from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_projection_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "build_research_objective_target_prediction.py"
    )
    spec = importlib.util.spec_from_file_location(
        "build_research_objective_target_prediction",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_target_prediction_projects_bundle_scope_and_contributions() -> None:
    projection = _load_projection_module()

    prediction = projection.build_target_prediction_from_bundle(_prediction_bundle())

    assert prediction["evidence_scope"] == {
        "paper_count": 1,
        "sample_count": 2,
        "test_condition_count": 1,
        "measurement_count": 2,
        "comparison_count": 1,
        "observation_count": 1,
        "uncertainty_count": 1,
    }
    assert prediction["paper_contributions"] == [
        {
            "paper_id": "P001",
            "role": "prediction_bundle_paper",
            "summary": (
                "P001: Energy input study. Goal: Study energy input. "
                "Variables: energy density. Properties: density; strength. "
                "Samples: 2. Measurements: density, yield strength."
            ),
        }
    ]


def test_build_target_prediction_preserves_comparisons_and_limits() -> None:
    projection = _load_projection_module()

    prediction = projection.build_target_prediction_from_bundle(_prediction_bundle())

    assert prediction["controlled_comparisons"] == [
        {
            "paper_id": "P001",
            "comparison_id": "C001",
            "summary": (
                "P001 C001: S002 vs S001 for density. "
                "99 % vs 95 %. Direction: improved. "
                "Notes: Higher density sample performs better."
            ),
        }
    ]
    assert prediction["mechanism_chains"] == [
        {
            "paper_id": "P001",
            "observation_id": "O001",
            "path": (
                "SEM observes pores: fewer pores. "
                "Interpretation: Energy input reduces pores."
            ),
        }
    ]
    assert prediction["limitations"] == [
        "P001 U001: density method limitation. Impact: avoid over-comparison."
    ]


def test_build_target_prediction_aligns_paper_ids_to_target_contributions() -> None:
    projection = _load_projection_module()
    bundle = _prediction_bundle()
    bundle["papers"][0]["paper_id"] = "doc-energy"
    for family in ("samples", "measurement_results"):
        for row in bundle[family]:
            row["paper_id"] = "doc-energy"

    prediction = projection.build_target_prediction_from_bundle(
        bundle,
        target={
            "required_paper_contributions": [
                {
                    "paper_id": "P777",
                    "required_terms": ["energy density", "yield strength"],
                }
            ]
        },
    )

    assert prediction["paper_contributions"] == [
        {
            "paper_id": "P777",
            "role": "prediction_bundle_paper",
            "summary": (
                "P777: Energy input study. Goal: Study energy input. "
                "Variables: energy density. Properties: density; strength. "
                "Samples: 2. Measurements: density, yield strength."
            ),
            "source_paper_id": "doc-energy",
        }
    ]


def test_build_target_prediction_exposes_measurement_summaries() -> None:
    projection = _load_projection_module()
    bundle = _prediction_bundle()

    prediction = projection.build_target_prediction_from_bundle(bundle)

    assert prediction["measurement_results"] == [
        {
            "paper_id": "P001",
            "result_id": "R001",
            "sample_id": "S001",
            "metric_name": "density",
            "value": "95%",
            "summary": "P001 R001: S001 density = 95%.",
        },
        {
            "paper_id": "P001",
            "result_id": "R002",
            "sample_id": "S002",
            "metric_name": "yield strength",
            "value": "450 MPa",
            "summary": "P001 R002: S002 yield strength = 450 MPa.",
        },
    ]


def test_build_target_prediction_adds_measurement_value_aliases() -> None:
    projection = _load_projection_module()
    bundle = _prediction_bundle()
    bundle["measurement_results"] = [
        {
            "paper_id": "P001",
            "result_id": "R003",
            "sample_id": "S003",
            "metric_name": "total elongation [%]",
            "value_or_trend": "48.3 +/- 3.2",
            "unit": "",
        },
        {
            "paper_id": "P001",
            "result_id": "R004",
            "sample_id": "S004",
            "metric_name": "passive film resistance",
            "value_or_trend": "1.90x10 5 ohm cm 2",
            "unit": "",
        },
    ]

    prediction = projection.build_target_prediction_from_bundle(bundle)

    assert prediction["measurement_results"] == [
        {
            "paper_id": "P001",
            "result_id": "R003",
            "sample_id": "S003",
            "metric_name": "total elongation [%]",
            "value": "48.3 +/- 3.2",
            "summary": (
                "P001 R003: S003 total elongation [%] = 48.3 +/- 3.2. "
                "Aliases: 48.3%."
            ),
            "value_aliases": ["48.3%"],
        },
        {
            "paper_id": "P001",
            "result_id": "R004",
            "sample_id": "S004",
            "metric_name": "passive film resistance",
            "value": "1.90x10 5 ohm cm 2",
            "summary": (
                "P001 R004: S004 passive film resistance = "
                "1.90x10 5 ohm cm 2. Aliases: 1.90e5 ohm cm2."
            ),
            "value_aliases": ["1.90e5 ohm cm2"],
        },
    ]


def test_build_research_objective_target_prediction_writes_prediction_and_report(
    tmp_path: Path,
) -> None:
    projection = _load_projection_module()
    backend_root = Path(__file__).resolve().parents[3]
    target_path = (
        backend_root
        / "tests"
        / "fixtures"
        / "research_objective_targets"
        / "lpbf_slm_316l_collection_target.json"
    )
    bundle_path = tmp_path / "bundle.json"
    prediction_path = tmp_path / "target_prediction.json"
    report_path = tmp_path / "target_report.json"
    bundle_path.write_text(json.dumps(_prediction_bundle()), encoding="utf-8")

    result = projection.build_research_objective_target_prediction(
        prediction_bundle_path=bundle_path,
        output_path=prediction_path,
        target_path=target_path,
        report_path=report_path,
    )

    assert result == prediction_path
    assert json.loads(prediction_path.read_text(encoding="utf-8"))[
        "evidence_scope"
    ]["paper_count"] == 1
    assert json.loads(report_path.read_text(encoding="utf-8"))["quality_gate"][
        "status"
    ] == "fail"


def _prediction_bundle() -> dict:
    return {
        "papers": [
            {
                "paper_id": "P001",
                "title": "Energy input study",
                "research_goal": "Study energy input",
                "main_variables": "energy density",
                "target_properties": "density; strength",
            }
        ],
        "samples": [
            {"paper_id": "P001", "sample_id": "S001"},
            {"paper_id": "P001", "sample_id": "S002"},
        ],
        "test_conditions": [
            {"paper_id": "P001", "test_condition_id": "T001"},
        ],
        "measurement_results": [
            {
                "paper_id": "P001",
                "result_id": "R001",
                "sample_id": "S001",
                "metric_name": "density",
                "value_or_trend": "95",
                "unit": "%",
            },
            {
                "paper_id": "P001",
                "result_id": "R002",
                "sample_id": "S002",
                "metric_name": "yield strength",
                "value_or_trend": "450",
                "unit": "MPa",
            },
        ],
        "comparisons": [
            {
                "paper_id": "P001",
                "comparison_id": "C001",
                "current_sample_id": "S002",
                "baseline_reference": "S001",
                "metric_name": "density",
                "current_value": "99",
                "baseline_value": "95",
                "unit": "%",
                "direction": "improved",
                "notes": "Higher density sample performs better.",
            }
        ],
        "observations": [
            {
                "paper_id": "P001",
                "observation_id": "O001",
                "characterization_method": "SEM",
                "observed_object": "pores",
                "value_or_description": "fewer pores",
                "author_interpretation": "Energy input reduces pores.",
            }
        ],
        "uncertainties": [
            {
                "paper_id": "P001",
                "issue_id": "U001",
                "description": "density method limitation",
                "impact": "avoid over-comparison",
            }
        ],
        "evidence": [
            {
                "paper_id": "P001",
                "evidence_id": "E001",
                "figure_or_table": "Table 1",
                "section": "Results",
                "supports": "density",
            }
        ],
    }
