from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def probe():
    scripts = Path(__file__).resolve().parents[3] / "scripts" / "benchmarks"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "objective_question_probe", scripts / "objective_question_probe.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts))


@pytest.fixture
def scenario():
    return {
        "scenario_id": "joint-versus-single",
        "interest": None,
        "expectation": {
            "private_reviewer_note": "DO_NOT_SEND_TO_MODEL",
            "shared_question_documents": ["paper-c"],
        },
        "papers": [
            {
                "document_id": "paper-c",
                "title": "Joint settings",
                "map_origin": "synthetic_boundary_case",
                "paper_map": {
                    "document_id": "paper-c",
                    "doc_role": "experimental",
                    "studies": [
                        {
                            "design_type": "experimental",
                            "claim_scope": "current_work",
                            "material_scope": ["Ti-6Al-4V"],
                            "process_context": ["LPBF"],
                            "relationships": [
                                {
                                    "varied_factors": ["laser power", "scan speed"],
                                    "outcome": "porosity",
                                    "confidence": 0.8,
                                    "source_refs": [
                                        {
                                            "source_kind": "block",
                                            "source_ref": "c-abstract",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                "excerpts": [
                    {
                        "source_ref": "c-abstract",
                        "text": "We jointly varied laser power and scan speed and measured porosity.",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def output():
    return {
        "proposals": [
            {
                "question": "How do laser power and scan speed affect porosity?",
                "material_scope": ["Ti-6Al-4V"],
                "variables": ["laser power", "scan speed"],
                "outcome": "porosity",
                "constraints": ["LPBF"],
                "reason": "A joint intervention warrants checking.",
                "papers": [
                    {
                        "document_id": "paper-c",
                        "source_refs": ["c-abstract"],
                        "role": "inspect",
                        "reason": "Reports the joint scope.",
                        "limitation": "No isolated effect has been established.",
                    }
                ],
            }
        ],
        "abstention_reason": None,
    }


def run(probe, scenario, payload, *, finish_reason="stop"):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            model="test-model",
            usage=None,
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(
                        content=(
                            payload if isinstance(payload, str) else json.dumps(payload)
                        )
                    ),
                )
            ],
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    runtime = SimpleNamespace(
        model="test-model",
        max_completion_tokens=8192,
        reasoning_effort=None,
        timeout_s=30,
    )
    return probe.run_proposal(scenario, runtime, client), requests


def test_core_probe_preserves_reading_scope_original_sources_and_joint_factors(
    probe, scenario, output
):
    before = probe.payload_hash(scenario)
    result, requests = run(probe, scenario, output)
    assert result["status"] == "completed"
    assert result["audit"]["reference_errors"] == []
    assert result["audit"]["shared_question_coverage"] is True
    candidate = result["candidates"][0]
    assert candidate["objective"]["seed_document_ids"] == ["paper-c"]
    assert candidate["objective"]["confirmation_status"] == "candidate"
    paper = candidate["papers"][0]
    assert paper["excerpts"] == scenario["papers"][0]["excerpts"]
    assert paper["paper_map"]["studies"][0]["relationships"][0]["varied_factors"] == [
        "laser power",
        "scan speed",
    ]
    assert probe.payload_hash(scenario) == before
    assert len(requests) == 1
    assert "draft_tool" not in result


def test_core_prompt_keeps_source_context_without_hidden_expectations(
    probe, scenario, output
):
    result, requests = run(probe, scenario, output)
    messages = json.dumps(requests[0]["messages"])
    assert "DO_NOT_SEND_TO_MODEL" not in messages
    assert "jointly varied laser power and scan speed" in messages
    assert '"research_interest": null' in requests[0]["messages"][1]["content"]
    assert result["trace"]["prompt_version"] == "objective_question_formation.v2"


def test_relevance_is_not_rechecked_with_the_agent_exact_factor_matcher(
    probe, scenario, output
):
    output["proposals"][0]["variables"] = ["processing conditions"]
    result, _ = run(probe, scenario, output)
    assert result["status"] == "completed"
    assert result["candidates"][0]["objective"]["seed_document_ids"] == ["paper-c"]


def test_loader_rejects_source_links_outside_the_supplied_paper(
    probe, scenario, tmp_path
):
    scenario["papers"][0]["excerpts"][0]["source_ref"] = "unrelated-source"
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"scenarios": [scenario]}))
    with pytest.raises(ValueError, match="unavailable excerpt"):
        probe.load_scenarios(path)


@pytest.mark.parametrize("failure", ["reference", "length", "json"])
def test_invalid_model_response_is_not_a_successful_scientific_abstention(
    probe, scenario, output, failure
):
    if failure == "reference":
        output["proposals"][0]["papers"][0]["source_refs"] = ["unseen"]
    result, requests = run(
        probe,
        scenario,
        "bad json" if failure == "json" else output,
        finish_reason="length" if failure == "length" else "stop",
    )
    assert result["status"] == "technical_failure"
    assert "candidates" not in result
    assert "abstention_reason" not in result
    assert result["trace"]["trace_status"] == "failed"
    assert len(requests) == 1


def test_valid_abstention_is_recorded_separately(probe, scenario):
    result, _ = run(
        probe, scenario, {"proposals": [], "abstention_reason": "No relevant scope."}
    )
    assert result["status"] == "completed"
    assert result["candidates"] == []
    assert result["abstention_reason"]


@pytest.mark.parametrize("abstain", [True, False])
def test_unsupported_interest_audit_separates_schema_success_from_scope_success(
    probe, scenario, output, abstain
):
    scenario["interest"] = "How does laser power affect corrosion current density?"
    scenario["expectation"]["abstain"] = True
    if abstain:
        output = {
            "proposals": [],
            "abstention_reason": "The supplied paper reports porosity, not corrosion.",
        }
    result, requests = run(probe, scenario, output)
    assert result["status"] == "completed"
    assert result["audit"]["reference_errors"] == []
    assert result["audit"]["expected_abstention"] is abstain
    assert "requires_review" in result["audit"]["scientific_acceptance"]
    input_payload, _ = json.JSONDecoder().raw_decode(
        requests[0]["messages"][1]["content"]
    )
    assert input_payload["research_interest"] == scenario["interest"]
