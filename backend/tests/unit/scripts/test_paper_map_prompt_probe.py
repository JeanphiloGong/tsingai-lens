from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.core.objectives.discovery.study_window import (
    StructuredPaperMapRelationship,
    StructuredPaperMapStudy,
)


def _load_probe_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_dir = backend_root / "scripts" / "benchmarks"
    script_path = script_dir / "paper_map_prompt_probe.py"
    sys.path.insert(0, str(script_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "paper_map_prompt_probe",
            script_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(script_dir))


def test_compact_prompt_uses_short_lineage_and_schema_shaped_boundaries() -> None:
    probe = _load_probe_module()
    scenario = probe.default_scenarios()[0]

    variant = probe.build_prompt_variants(scenario.payload)["compact_json_object"]

    assert '"label":"S1"' in variant.user_prompt
    assert "source-unit-complete-1" not in variant.user_prompt
    assert "JSON schema:" not in variant.user_prompt
    assert '"studies"' in variant.user_prompt
    assert "JOINT FACTORS" in variant.user_prompt
    assert "BROAD OUTCOME" in variant.user_prompt
    assert "CITED BACKGROUND" in variant.user_prompt


def test_prompt_audit_separates_message_tokens_from_provider_schema() -> None:
    probe = _load_probe_module()
    scenario = probe.default_scenarios()[0]

    variants = probe.build_prompt_variants(scenario.payload)
    audit = probe.audit_prompt_variants(variants, model="zai-org/glm-5.2")

    current = audit["current_json_schema"]
    current_parse = audit["current_provider_parse"]
    compact_json = audit["compact_json_object"]
    compact_parse = audit["compact_provider_parse"]
    assert current["schema_delivery"] == "message"
    assert current_parse["schema_delivery"] == "provider_response_format"
    assert compact_json["schema_delivery"] == "compact_output_contract"
    assert compact_parse["schema_delivery"] == "provider_response_format"
    assert current["message_tokens_estimate"] > compact_json["message_tokens_estimate"]
    assert current["message_tokens_estimate"] > compact_parse["message_tokens_estimate"]
    assert current_parse["message_tokens_estimate"] < current["message_tokens_estimate"]
    assert current_parse["provider_schema_tokens_estimate"] > 0
    assert compact_parse["provider_schema_chars"] > 0
    assert compact_parse["provider_schema_tokens_estimate"] > 0
    expected_reduction = round(
        (
            current_parse["message_tokens_estimate"]
            - compact_parse["message_tokens_estimate"]
        )
        / current_parse["message_tokens_estimate"]
        * 100,
        2,
    )
    assert (
        compact_parse["message_token_reduction_vs_current_provider_parse_percent"]
        == expected_reduction
    )


def test_scientific_evaluator_accepts_joint_factor_scope() -> None:
    probe = _load_probe_module()
    scenario = next(
        item
        for item in probe.default_scenarios()
        if item.scenario_id == "joint_factors"
    )
    parsed = probe.StructuredExperimentalPaperMap.model_validate(
        {
            "doc_role": "experimental",
            "studies": [
                {
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["Ti-6Al-4V"],
                    "process_context": ["LPBF"],
                    "relationships": [
                        {
                            "factor_assertions": [
                                {
                                    "label": "laser power",
                                    "role": "varied",
                                    "source_labels": ["S1"],
                                },
                                {
                                    "label": "scan speed",
                                    "role": "varied",
                                    "source_labels": ["S1"],
                                },
                            ],
                            "outcome": "porosity",
                            "source_labels": ["S1"],
                            "confidence": 0.9,
                        },
                        {
                            "factor_assertions": [
                                {
                                    "label": "laser power",
                                    "role": "varied",
                                    "source_labels": ["S1"],
                                },
                                {
                                    "label": "scan speed",
                                    "role": "varied",
                                    "source_labels": ["S1"],
                                },
                            ],
                            "outcome": "tensile strength",
                            "source_labels": ["S1"],
                            "confidence": 0.9,
                        },
                    ],
                }
            ],
        }
    )

    evaluation = probe.evaluate_scenario_output(scenario, parsed)

    assert evaluation["passed"] is True
    assert evaluation["checks"]["joint_factor_set_preserved"] is True
    assert evaluation["checks"]["expected_outcomes_present"] is True


def test_scientific_evaluator_rejects_broad_outcome_as_complete_relationship() -> None:
    probe = _load_probe_module()
    scenario = next(
        item
        for item in probe.default_scenarios()
        if item.scenario_id == "broad_outcome"
    )
    relationship = StructuredPaperMapRelationship.model_construct(
        factor_assertions=[
            SimpleNamespace(
                label="heat treatment",
                role="varied",
                source_labels=["S1"],
            )
        ],
        outcome="microstructure",
        source_labels=["S1"],
        confidence=0.8,
    )
    study = StructuredPaperMapStudy.model_construct(
        design_type="experimental",
        claim_scope="current_work",
        relationships=[relationship],
    )
    parsed = probe.StructuredExperimentalPaperMap.model_construct(
        studies=[study],
        unresolved_signals=[],
        output_saturated=False,
    )

    evaluation = probe.evaluate_scenario_output(scenario, parsed)

    assert evaluation["passed"] is False
    assert evaluation["checks"]["broad_outcome_not_promoted"] is False


def test_scientific_evaluator_rejects_cited_work_as_current_work() -> None:
    probe = _load_probe_module()
    scenario = next(
        item
        for item in probe.default_scenarios()
        if item.scenario_id == "cited_background"
    )
    parsed = probe.StructuredExperimentalPaperMap.model_validate(
        {
            "doc_role": "experimental",
            "studies": [
                {
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "factor_assertions": [
                                {
                                    "label": "build plate temperature",
                                    "role": "varied",
                                    "source_labels": ["S1"],
                                }
                            ],
                            "outcome": "residual stress",
                            "source_labels": ["S1"],
                        }
                    ],
                }
            ],
        }
    )

    evaluation = probe.evaluate_scenario_output(scenario, parsed)

    assert evaluation["passed"] is False
    assert evaluation["checks"]["no_cited_current_work"] is False


def test_load_scenarios_reads_real_payloads_with_structural_expectations(
    tmp_path: Path,
) -> None:
    probe = _load_probe_module()
    scenario_path = tmp_path / "real-paper-map-scenarios.json"
    scenario_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario_id": "historical-unknown-5",
                        "description": "A production window that saturated.",
                        "payload": {
                            "title": "Wire hybrid additive manufacture",
                            "document_profile": {"doc_type": "experimental"},
                            "window_id": "unknown-5",
                            "window_role": "unknown",
                            "source_units": [
                                {
                                    "source_unit_id": "source-unit-000025",
                                    "source_kind": "block",
                                    "source_ref": "block-25",
                                    "section_path": "Methods",
                                    "content": "Wire position was varied.",
                                }
                            ],
                        },
                        "expectation": {
                            "kind": "structural",
                            "allow_output_saturated": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    scenarios = probe.load_scenarios(scenario_path)

    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "historical-unknown-5"
    assert scenarios[0].payload["source_units"][0]["source_unit_id"] == (
        "source-unit-000025"
    )
    assert scenarios[0].expectation == {
        "kind": "structural",
        "allow_output_saturated": True,
    }


def test_structural_evaluator_accepts_schema_valid_saturated_stress_output() -> None:
    probe = _load_probe_module()
    scenario = probe.ProbeScenario(
        scenario_id="historical-stress",
        description="Dense historical production window.",
        payload={
            "source_units": [
                {"source_unit_id": "source-unit-1"},
                {"source_unit_id": "source-unit-2"},
            ]
        },
        expectation={"kind": "structural", "allow_output_saturated": True},
    )
    parsed = probe.StructuredExperimentalPaperMap.model_validate(
        {
            "doc_role": "experimental",
            "studies": [],
            "unresolved_signals": [
                    {
                        "signal_type": "variable",
                        "label": "wire position",
                        "variable_role": "uncertain",
                        "source_labels": ["S2"],
                }
            ],
            "output_saturated": True,
        }
    )

    evaluation = probe.evaluate_scenario_output(scenario, parsed)

    assert evaluation["passed"] is True
    assert evaluation["checks"]["source_labels_allowed"] is True
    assert "not_output_saturated" not in evaluation["checks"]


def test_structural_evaluator_requires_unsaturated_current_window() -> None:
    probe = _load_probe_module()
    scenario = probe.ProbeScenario(
        scenario_id="current-overview",
        description="Current lightweight overview window.",
        payload={"source_units": [{"source_unit_id": "source-unit-1"}]},
        expectation={"kind": "structural"},
    )
    parsed = probe.StructuredExperimentalPaperMap.model_validate(
        {
            "doc_role": "experimental",
            "studies": [],
            "unresolved_signals": [],
            "output_saturated": True,
        }
    )

    evaluation = probe.evaluate_scenario_output(scenario, parsed)

    assert evaluation["passed"] is False
    assert evaluation["checks"]["not_output_saturated"] is False


def test_scientific_evaluator_requires_each_explicit_configuration_relationship() -> (
    None
):
    probe = _load_probe_module()
    scenario = probe.ProbeScenario(
        scenario_id="current-conclusion",
        description="The conclusion explicitly links configuration to two outcomes.",
        payload={"source_units": [{"source_unit_id": "source-unit-1"}]},
        expectation={
            "kind": "required_relationships",
            "relationships": [
                {
                    "factor_contains": ["configuration"],
                    "outcome_contains": ["stability"],
                },
                {
                    "factor_contains": ["configuration"],
                    "outcome_contains": ["bead appearance"],
                },
            ],
        },
    )
    parsed = probe.StructuredExperimentalPaperMap.model_validate(
        {
            "doc_role": "experimental",
            "studies": [],
            "unresolved_signals": [
                {
                    "signal_type": "outcome",
                    "label": "deposition stability and bead appearance",
                    "variable_role": "not_applicable",
                    "source_labels": ["S1"],
                }
            ],
        }
    )

    evaluation = probe.evaluate_scenario_output(scenario, parsed)

    assert evaluation["passed"] is False
    assert evaluation["checks"]["required_relationship_1"] is False
    assert evaluation["checks"]["required_relationship_2"] is False


def test_scientific_evaluator_rejects_mechanisms_and_invented_study_splits() -> None:
    probe = _load_probe_module()
    scenario = probe.ProbeScenario(
        scenario_id="current-conclusion",
        description="One paper-owned conclusion with a causal explanation.",
        payload={"source_units": [{"source_unit_id": "source-unit-1"}]},
        expectation={
            "kind": "required_relationships",
            "relationships": [
                {
                    "factor_contains": ["heat source"],
                    "outcome_contains": ["deposition rate"],
                }
            ],
            "max_studies": 1,
            "forbidden_outcome_contains": ["energy distribution"],
        },
    )
    parsed = probe.StructuredExperimentalPaperMap.model_validate(
        {
            "doc_role": "experimental",
            "studies": [
                {
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "factor_assertions": [
                                {
                                    "label": "heat source type",
                                    "role": "compared",
                                    "source_labels": ["S1"],
                                }
                            ],
                            "outcome": "deposition rate",
                            "source_labels": ["S1"],
                        }
                    ],
                },
                {
                    "experiment_label": "invented mechanism study",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "factor_assertions": [
                                {
                                    "label": "heat source type",
                                    "role": "compared",
                                    "source_labels": ["S1"],
                                }
                            ],
                            "outcome": "energy distribution",
                            "source_labels": ["S1"],
                        }
                    ],
                },
            ],
        }
    )

    evaluation = probe.evaluate_scenario_output(scenario, parsed)

    assert evaluation["passed"] is False
    assert evaluation["checks"]["required_relationship_1"] is True
    assert evaluation["checks"]["study_count_within_limit"] is False
    assert evaluation["checks"]["forbidden_outcomes_absent"] is False


def test_compact_provider_prompt_teaches_explicit_configuration_relationships() -> None:
    probe = _load_probe_module()
    scenario = probe.default_scenarios()[0]

    variant = probe.build_prompt_variants(scenario.payload)["compact_provider_parse"]

    assert "EXPLICIT CONFIGURATION EFFECT" in variant.user_prompt
    assert "deposition stability" in variant.user_prompt
    assert "bead appearance" in variant.user_prompt
    assert "Do not demote an explicit link" in variant.user_prompt
    assert "OUTPUT SHAPE" in variant.user_prompt
    assert "JSON schema:" not in variant.user_prompt


def test_paper_map_study_accepts_six_relationships_but_rejects_seven() -> None:
    relationship = {
        "factor_assertions": [
            {
                "label": "process configuration",
                "role": "varied",
                "source_labels": ["S1"],
            }
        ],
        "outcome": "deposition rate",
        "source_labels": ["S1"],
    }
    six_relationships = [
        {**relationship, "outcome": f"outcome {position}"} for position in range(1, 7)
    ]

    parsed = StructuredPaperMapStudy.model_validate(
        {"relationships": six_relationships}
    )

    assert len(parsed.relationships) == 6
    with pytest.raises(ValidationError, match="at most 6 items"):
        StructuredPaperMapStudy.model_validate(
            {
                "relationships": [
                    *six_relationships,
                    {**relationship, "outcome": "outcome 7"},
                ]
            }
        )


def test_live_case_preserves_provider_metadata_when_validation_fails() -> None:
    probe = _load_probe_module()
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"unresolved_signals":[{"signal_type":"variable",'
                        '"label":"wire position","source_labels":'
                        '["S1","S2","S3","S4","S5"]}]}'
                    )
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=123,
            completion_tokens=7,
            total_tokens=130,
        ),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: response)
        )
    )
    scenario = probe.default_scenarios()[0]
    variant = probe.build_prompt_variants(scenario.payload)["compact_json_object"]

    record, _ = probe._run_live_case(
        client,
        scenario=scenario,
        variant=variant,
        model="fake-model",
        run=1,
        temperature=0.0,
        max_completion_tokens=2048,
        enable_thinking=False,
        reasoning_effort=None,
    )

    assert record["validated"] is False
    assert record["error_type"] == "ValidationError"
    assert record["finish_reason"] == "stop"
    assert record["usage"] == {
        "prompt_tokens": 123,
        "completion_tokens": 7,
        "total_tokens": 130,
    }


def test_live_provider_case_matches_production_reasoning_controls() -> None:
    probe = _load_probe_module()
    calls: list[dict[str, object]] = []
    parsed = probe.StructuredExperimentalPaperMap.model_validate(
        {
            "doc_role": "experimental",
            "studies": [],
            "unresolved_signals": [],
        }
    )

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=parsed, content=""),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    client = SimpleNamespace(
        beta=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
        )
    )
    scenario = probe.default_scenarios()[0]
    variant = probe.build_prompt_variants(scenario.payload)["current_provider_parse"]

    record, _ = probe._run_live_case(
        client,
        scenario=scenario,
        variant=variant,
        model="fake-model",
        run=1,
        temperature=0.0,
        max_completion_tokens=2048,
        enable_thinking=False,
        reasoning_effort="none",
    )

    assert record["validated"] is True
    assert calls[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert calls[0]["reasoning_effort"] == "none"


def test_probe_runtime_reads_reasoning_effort_from_env_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    probe = _load_probe_module()
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_REASONING_EFFORT=none\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        backend_root=tmp_path,
        env_file=env_file,
        base_url="https://example.invalid/v1",
        model="fake-model",
        api_key="test-key",
        temperature=0.0,
        max_completion_tokens=2048,
        timeout_s=30.0,
        reasoning_effort=None,
    )

    runtime = probe.resolve_runtime(args)

    assert runtime.reasoning_effort == "none"
