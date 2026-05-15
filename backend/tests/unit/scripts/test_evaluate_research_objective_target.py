from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_evaluator_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "evaluate_research_objective_target.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evaluate_research_objective_target",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_target_reports_missing_required_keys() -> None:
    evaluator = _load_evaluator_module()

    assert evaluator.validate_target({}) == [
        "missing_target_key:target_id",
        "missing_target_key:objective",
        "missing_target_key:expected_evidence_scope",
        "missing_target_key:required_paper_contributions",
        "missing_target_key:required_claims",
        "missing_target_key:required_limitations",
        "missing_target_key:forbidden_overclaims",
        "objective_must_be_object",
        "expected_evidence_scope_must_be_object",
    ]


def test_evaluate_target_prediction_scores_structured_prediction() -> None:
    evaluator = _load_evaluator_module()

    report = evaluator.evaluate_target_prediction(
        target=_target(),
        prediction={
            "evidence_scope": {"paper_count": 1, "sample_count": 2},
            "paper_contributions": [
                {
                    "paper_id": "P001",
                    "summary": "Energy input changes porosity and strength.",
                }
            ],
            "controlled_comparisons": [
                {
                    "paper_id": "P001",
                    "claim": "Sample A reaches 99% density and 450 MPa strength.",
                }
            ],
            "mechanism_chains": [
                "energy input porosity strength",
            ],
            "limitations": [
                "Density method is not directly equivalent to micro-CT.",
            ],
        },
    )

    assert report["scores"] == {
        "evidence_scope_score": 1.0,
        "paper_contribution_score": 1.0,
        "required_claim_score": 1.0,
        "mechanism_chain_score": 1.0,
        "limitation_score": 1.0,
        "forbidden_overclaim_violations": 0,
    }
    assert report["quality_gate"]["status"] == "pass"


def test_evaluate_target_prediction_reports_missing_claims_and_overclaims() -> None:
    evaluator = _load_evaluator_module()

    report = evaluator.evaluate_target_prediction(
        target=_target(),
        prediction={
            "evidence_scope": {"paper_count": 0, "sample_count": 1},
            "paper_contributions": [
                {
                    "paper_id": "P001",
                    "summary": "Energy density is always better.",
                }
            ],
            "collection_conclusion": "Energy density is always better.",
        },
    )

    assert report["quality_gate"]["status"] == "fail"
    assert report["required_claims"]["failed_checks"] == [
        {
            "claim_id": "p001_density_strength",
            "status": "fail",
            "matched_values": [],
            "missing_values": ["99%", "450 MPa"],
            "required_value_count": 2,
        }
    ]
    assert report["forbidden_overclaims"]["violations"] == [
        {
            "overclaim_id": "always_better",
            "text": "Energy density is always better.",
        }
    ]


def test_evaluate_research_objective_target_writes_report(tmp_path: Path) -> None:
    evaluator = _load_evaluator_module()
    target_path = tmp_path / "target.json"
    prediction_path = tmp_path / "prediction.json"
    report_path = tmp_path / "report.json"
    target_path.write_text(json.dumps(_target()), encoding="utf-8")
    prediction_path.write_text(
        json.dumps(
            {
                "evidence_scope": {"paper_count": 1, "sample_count": 2},
                "paper_contributions": [
                    {
                        "paper_id": "P001",
                        "summary": "Energy input changes porosity and strength.",
                    }
                ],
                "controlled_comparisons": [
                    "Sample A reaches 99% density and 450 MPa strength."
                ],
                "mechanism_chains": ["energy input porosity strength"],
                "limitations": [
                    "Density method is not directly equivalent to micro-CT."
                ],
            }
        ),
        encoding="utf-8",
    )

    result_path = evaluator.evaluate_research_objective_target(
        target_path=target_path,
        prediction_path=prediction_path,
        output_path=report_path,
    )

    assert result_path == report_path
    assert json.loads(report_path.read_text(encoding="utf-8"))["target_id"] == (
        "test_target"
    )


def _target() -> dict:
    return {
        "target_id": "test_target",
        "objective": {"question": "How does energy input affect 316L?"},
        "expected_evidence_scope": {"paper_count": 1, "sample_count": 2},
        "required_paper_contributions": [
            {
                "paper_id": "P001",
                "required_terms": ["energy input", "porosity", "strength"],
            }
        ],
        "required_claims": [
            {
                "claim_id": "p001_density_strength",
                "text": "Sample A reaches 99% density and 450 MPa strength.",
                "required_papers": ["P001"],
                "required_numbers": ["99%", "450 MPa"],
            }
        ],
        "required_mechanism_chains": [
            {
                "chain_id": "energy_porosity_strength",
                "path": ["energy input", "porosity", "strength"],
            }
        ],
        "required_limitations": [
            {
                "limitation_id": "density_method",
                "paper_id": "P001",
                "text": "Density method is not directly equivalent to micro-CT.",
            }
        ],
        "forbidden_overclaims": [
            {
                "overclaim_id": "always_better",
                "text": "Energy density is always better.",
            }
        ],
    }
