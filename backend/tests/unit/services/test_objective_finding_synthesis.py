from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)


class _Extractor:
    def __init__(self, responses: list[dict | Exception | None]) -> None:
        self.responses = list(responses)
        self.payloads: list[dict] = []

    def judge_result_set(self, payload: dict) -> SimpleNamespace:
        self.payloads.append(payload)
        response = self.responses.pop(0) if self.responses else None
        if isinstance(response, Exception):
            raise response
        if response is None:
            findings: list[dict] = []
        else:
            findings = [dict(response)]
        return SimpleNamespace(model_dump=lambda: {"findings": findings})


def _objective(**overrides) -> ResearchObjective:
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "question": "How do laser power and scan speed affect relative density?",
        "material_scope": ["316L stainless steel"],
        "variables": ["laser power", "scan speed"],
        "outcomes": ["relative density"],
        "confidence": 0.9,
        "confirmation_status": "confirmed",
        "active_analysis_version": 1,
    }
    payload.update(overrides)
    return ResearchObjective.from_mapping(payload)


def _analysis(**overrides) -> ObjectiveAnalysis:
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "analysis_version": 1,
        "source_build_id": "build-1",
        "pipeline_version": "objective-analysis.v2",
        "model_name": "test-model",
        "prompt_versions": {},
        "status": "running",
        "phase": "finding_synthesis",
    }
    payload.update(overrides)
    return ObjectiveAnalysis(**payload)


def _contribution(document_id: str, **overrides) -> PaperContribution:
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "analysis_version": 1,
        "document_id": document_id,
        "analysis_status": "analyzed",
        "relevance": "high",
        "paper_role": "primary_experiment",
        "contribution_summary": "Direct parameter comparison.",
        "material_match": ["316L stainless steel"],
        "changed_variables": ["laser power", "scan speed"],
        "measured_property_scope": ["relative density"],
        "test_environment_scope": [],
        "warnings": [],
        "confidence": 0.9,
    }
    payload.update(overrides)
    return PaperContribution.from_mapping(payload)


def _evidence(
    evidence_id: str,
    document_id: str,
    *,
    role: str = "direct_result",
    outcome: str | None = "relative density",
    factors: tuple[str, ...] = ("laser power", "scan speed"),
    direction: str = "increase",
    comparison: dict | None | object = ...,
    attribution_scope: str | None = None,
    confidence: float = 0.9,
    material: str = "316L",
    **overrides,
) -> ObjectiveEvidence:
    is_result = role in {"direct_result", "contradictory_result"}
    variables = [
        {
            "name": factor,
            "baseline_value": f"baseline {factor}",
            "target_value": f"target {factor}",
        }
        for factor in factors
    ]
    if comparison is ...:
        comparison = (
            {
                "baseline_label": "condition A",
                "target_label": "condition B",
                "axis_names": list(factors),
                "comparable": True,
                "incomparability_reasons": [],
            }
            if is_result
            else None
        )
    if attribution_scope is None:
        attribution_scope = (
            "isolated_effect"
            if is_result and len(factors) == 1 and comparison is not None
            else "joint_effect"
            if is_result and len(factors) > 1 and comparison is not None
            else "not_attributable"
        )
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-density",
        "analysis_version": 1,
        "evidence_id": evidence_id,
        "document_id": document_id,
        "source_kind": "text_window",
        "source_ref": f"block-{evidence_id}",
        "source_excerpt": (
            "Laser power and scan speed changed while relative density increased."
        ),
        "page_numbers": [4],
        "related_source_refs": [],
        "evidence_role": role,
        "selection_status": "extracted",
        "selection_reason": "Direct objective result.",
        "changed_variables": variables if is_result else [],
        "comparison": comparison,
        "reported_result": (
            {
                "outcome": outcome,
                "value": 99.2,
                "unit": "%",
                "direction": direction,
                "result_text": f"{outcome} changed under the reported comparison.",
            }
            if is_result and outcome
            else None
        ),
        "attribution_scope": attribution_scope,
        "scientific_context": {
            "material": [{"name": "alloy", "value": material}],
            "sample": [{"name": "state", "value": "as-built"}],
            "process": [{"name": "process", "value": "LPBF"}],
            "test": [],
        },
        "anchor_ids": [f"anchor-{evidence_id}"],
        "resolution_status": "resolved",
        "confidence": confidence,
    }
    payload.update(overrides)
    return ObjectiveEvidence.from_mapping(payload)


def _candidate(**overrides) -> dict:
    payload = {
        "assertion_strength": "associative",
        "context_evidence_ids": [],
        "mechanisms": [],
    }
    payload.update(overrides)
    return payload


def _heterogeneous_candidate(**overrides) -> dict:
    return _candidate(**overrides)


def test_synthesis_builds_one_atomic_single_paper_finding() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.factors == ("laser power", "scan speed")
    assert finding.outcome == "relative density"
    assert finding.attribution_scope == "joint_effect"
    assert finding.synthesis_status == "insufficient_confirmation"
    assert finding.certainty == 0.5
    assert finding.direct_document_count == 1
    assert finding.paper_contributions[0].supporting_evidence_ids == ("ev-1",)
    assert extractor.payloads[0]["result_set"]["outcome"] == "relative density"
    assert "synthesis_status" not in extractor.payloads[0]


def test_synthesis_publishes_only_deterministic_analysis_limitations() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [_candidate(limitations=["The model inferred an uncited limitation."])]
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    )[0]

    assert finding.limitations == (
        "The reported comparison changes the complete factor set; "
        "individual-factor effects are not identifiable.",
        "Cross-paper confirmation is absent for this atomic result.",
    )


def test_synthesis_accepts_concrete_defect_measurement_for_defect_structure() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Volumetric energy density was associated with a decrease in "
                    "maximum defect diameter."
                ),
                direction="decrease",
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question=(
                "How does volumetric energy density affect defect structure?"
            ),
            variables=["volumetric energy density"],
            outcomes=["defect structure"],
        ),
        analysis=_analysis(),
        contributions=(
            _contribution(
                "paper-1",
                changed_variables=["volumetric energy density"],
                measured_property_scope=["defect structure"],
            ),
        ),
        evidence_records=(
            _evidence(
                "ev-defect-diameter",
                "paper-1",
                outcome="maximum defect diameter",
                factors=("volumetric energy density",),
                direction="decrease",
                source_excerpt=(
                    "The maximum defect diameters decreased from 76 um at low VED "
                    "to 50 um at high VED."
                ),
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].factors == ("volumetric energy density",)
    assert findings[0].outcome == "maximum defect diameter"


def test_synthesis_keeps_relative_density_out_of_defect_structure() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    result_sets = service._result_sets(
        _objective(
            variables=["volumetric energy density"],
            outcomes=["defect structure"],
        ),
        (
            _evidence(
                "ev-relative-density",
                "paper-1",
                outcome="relative density",
                factors=("volumetric energy density",),
            ),
        ),
    )

    assert result_sets == ()


def test_synthesis_accepts_relative_density_for_densification_outcome() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    result_sets = service._result_sets(
        _objective(
            variables=["energy density"],
            outcomes=["densification"],
        ),
        (
            _evidence(
                "ev-relative-density",
                "paper-1",
                outcome="relative density",
                factors=("energy density",),
            ),
        ),
    )

    assert len(result_sets) == 1
    assert result_sets[0]["outcome"] == "relative density"


def test_synthesis_canonicalizes_unit_qualified_axes_across_papers() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    result_sets = service._result_sets(
        _objective(variables=["laser power"], outcomes=["relative density"]),
        (
            _evidence(
                "paper-1-power",
                "paper-1",
                factors=("laser power",),
            ),
            _evidence(
                "paper-2-power",
                "paper-2",
                factors=("Laser power (W)",),
            ),
        ),
    )

    assert len(result_sets) == 1
    assert result_sets[0]["factors"] == ["laser power"]
    assert {
        item["document_id"] for item in result_sets[0]["result_evidence"]
    } == {"paper-1", "paper-2"}


def test_synthesis_excludes_unknown_direction_from_directional_result_sets() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    result_sets = service._result_sets(
        _objective(variables=["laser power"], outcomes=["relative density"]),
        (
            _evidence(
                "unknown-direction",
                "paper-1",
                factors=("laser power",),
                direction="unknown",
            ),
        ),
    )

    assert result_sets == ()


def test_synthesis_prompt_balances_representatives_across_documents() -> None:
    extractor = _Extractor([None])
    service = FindingSynthesisService(assertion_judge=extractor)
    heavy_evidence = tuple(
        _evidence(
            f"heavy-{position}",
            "paper-heavy",
            factors=("laser power",),
            confidence=0.99 - position / 1000,
            changed_variables=[
                {
                    "name": "laser power",
                    "baseline_value": position,
                    "target_value": position + 1,
                    "unit": "W",
                }
            ],
        )
        for position in range(50)
    )
    sparse_evidence = _evidence(
        "sparse-1",
        "paper-sparse",
        factors=("Laser power (W)",),
        confidence=0.8,
        changed_variables=[
            {
                "name": "Laser power (W)",
                "baseline_value": 150,
                "target_value": 200,
                "unit": "W",
            }
        ],
    )

    service.synthesize(
        collection_id="col-1",
        objective=_objective(variables=["laser power"]),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-heavy"),
            _contribution("paper-sparse"),
        ),
        evidence_records=(*heavy_evidence, sparse_evidence),
    )

    prompt_result_set = extractor.payloads[0]["result_set"]
    assert prompt_result_set["total_evidence_count"] == 51
    assert len(prompt_result_set["result_evidence"]) <= 16
    assert {
        item["document_id"]
        for item in prompt_result_set["result_evidence"][:2]
    } == {"paper-heavy", "paper-sparse"}
    assert {
        item["document_id"]: item["direction_counts"]
        for item in prompt_result_set["document_evidence_summaries"]
    } == {
        "paper-heavy": {"increase": 50},
        "paper-sparse": {"increase": 1},
    }
    full_result_set = service._result_sets(
        _objective(variables=["laser power"]),
        (*heavy_evidence, sparse_evidence),
    )[0]
    assert len(full_result_set["result_evidence"]) == 51


def test_synthesis_derives_cross_paper_agreement() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence("ev-2", "paper-2", confidence=0.84),
        ),
    )[0]

    assert finding.synthesis_status == "agreement"
    assert finding.certainty == 0.84
    assert finding.support_scope == "cross_paper"


def test_synthesis_groups_comparison_intervals_as_one_condition_series() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    evidence = tuple(
        _evidence(
            evidence_id,
            "paper-1",
            factors=("scan strategy rotation angle",),
            outcome="yield strength",
            direction=direction,
            changed_variables=[
                {
                    "name": "scan strategy rotation angle",
                    "baseline_value": baseline,
                    "target_value": target,
                    "unit": "degree",
                }
            ],
        )
        for evidence_id, baseline, target, direction in (
            ("angle-0-30", 0, 30, "decrease"),
            ("angle-0-45", 0, 45, "increase"),
            ("angle-30-45", 30, 45, "increase"),
        )
    )

    result_sets = service._result_sets(
        _objective(
            variables=["scan strategy rotation angle"],
            outcomes=["yield strength"],
        ),
        evidence,
    )

    assert len(result_sets) == 1
    assert [len(item["result_evidence"]) for item in result_sets] == [3]


def test_synthesis_separates_reference_treatment_from_treatment_comparisons(
) -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        variables=["post-processing condition"],
        outcomes=["ultimate tensile strength"],
        material_scope=["Ti-6Al-4V"],
    )

    def uts_comparison(
        evidence_id: str,
        document_id: str,
        baseline: str,
        target: str,
        direction: str,
    ) -> ObjectiveEvidence:
        return _evidence(
            evidence_id,
            document_id,
            factors=("post-processing condition",),
            outcome="ultimate tensile strength",
            direction=direction,
            material="Ti-6Al-4V",
            changed_variables=[
                {
                    "name": "post-processing condition",
                    "baseline_value": baseline,
                    "target_value": target,
                }
            ],
            scientific_context={
                "material": [{"name": "material", "value": "Ti-6Al-4V"}],
                "sample": [{"name": "build orientation", "value": "vertical"}],
                "process": [
                    {
                        "name": "manufacturing process",
                        "value": "laser powder bed fusion",
                    }
                ],
                "test": [],
            },
        )

    result_sets = service._result_sets(
        objective,
        (
            uts_comparison(
                "2020-af-to-hip",
                "paper-2020",
                "as-fabricated",
                "HIP + polishing",
                "decrease",
            ),
            uts_comparison(
                "2024-ab-to-800-sc",
                "paper-2024",
                "AB",
                "800 SC",
                "decrease",
            ),
            uts_comparison(
                "2024-800-fc-to-920-rq",
                "paper-2024",
                "800 FC",
                "920 RQ",
                "increase",
            ),
        ),
    )

    evidence_ids_by_interval = {
        result_set["comparison_interval"]: {
            item["evidence_id"] for item in result_set["result_evidence"]
        }
        for result_set in result_sets
    }
    assert evidence_ids_by_interval == {
        "reference_to_treatment": {
            "2020-af-to-hip",
            "2024-ab-to-800-sc",
        },
        "treatment_to_treatment": {"2024-800-fc-to-920-rq"},
    }


def test_synthesis_generates_uniform_no_change_statement_from_evidence() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    evidence = tuple(
        _evidence(
            evidence_id,
            "paper-1",
            direction="no_change",
            changed_variables=[
                {
                    "name": "laser power",
                    "baseline_value": baseline,
                    "target_value": target,
                    "unit": "W",
                },
                {
                    "name": "scan speed",
                    "baseline_value": 100,
                    "target_value": 200,
                    "unit": "mm/s",
                },
            ],
        )
        for evidence_id, baseline, target in (
            ("uniform-100-120", 100, 120),
            ("uniform-120-140", 120, 140),
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=evidence,
    )[0]

    assert len(extractor.payloads) == 1
    assert finding.direction == "no_change"
    assert finding.statement == (
        "Joint changes in laser power and scan speed were associated with no "
        "reported change in relative density."
    )


def test_synthesis_generates_categorical_changed_finding_from_evidence() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    evidence = _evidence(
        "phase-change",
        "paper-1",
        outcome="phase composition",
        factors=("heat treatment",),
        direction="changed",
        reported_result={
            "outcome": "phase composition",
            "value": "alpha+beta",
            "baseline_value": "alpha-prime",
            "target_value": "alpha+beta",
            "unit": None,
            "direction": "changed",
            "result_text": "Phase composition changed from alpha-prime to alpha+beta.",
        },
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            variables=("heat treatment",),
            outcomes=("phase composition",),
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )[0]

    assert finding.direction == "changed"
    assert finding.statement == (
        "Changes in heat treatment were associated with a qualitative change "
        "in phase composition."
    )
    assert extractor.payloads[0]["result_set"]["primary_direction"] == "changed"


def test_synthesis_accepts_source_supported_uniform_mixed_condition_series() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    evidence = tuple(
        _evidence(
            evidence_id,
            "paper-1",
            direction="mixed",
            changed_variables=[
                {
                    "name": "laser power",
                    "baseline_value": baseline,
                    "target_value": target,
                    "unit": "W",
                },
                {
                    "name": "scan speed",
                    "baseline_value": 100,
                    "target_value": 200,
                    "unit": "mm/s",
                },
            ],
        )
        for evidence_id, baseline, target in (
            ("mixed-100-120", 100, 120),
            ("mixed-120-140", 120, 140),
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=evidence,
    )[0]

    assert len(extractor.payloads) == 1
    assert finding.direction == "mixed"
    assert finding.statement == (
        "Joint changes in laser power and scan speed were associated with a "
        "source-reported mixed change in relative density."
    )


def test_synthesis_ignores_model_owned_statement_and_direction_fields() -> None:
    model_candidate = _candidate(
        statement=(
            "Across the reported condition series, laser power and scan speed "
            "showed conflicting responses in relative density."
        ),
        direction="increase",
    )
    extractor = _Extractor([model_candidate])
    service = FindingSynthesisService(assertion_judge=extractor)
    evidence = tuple(
        _evidence(
            evidence_id,
            "paper-1",
            direction="no_change",
            changed_variables=[
                {
                    "name": "laser power",
                    "baseline_value": baseline,
                    "target_value": target,
                    "unit": "W",
                },
                {
                    "name": "scan speed",
                    "baseline_value": 100,
                    "target_value": 200,
                    "unit": "mm/s",
                },
            ],
        )
        for evidence_id, baseline, target in (
            ("uniform-100-120", 100, 120),
            ("uniform-120-140", 120, 140),
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=evidence,
    )[0]

    assert len(extractor.payloads) == 1
    assert finding.direction == "no_change"
    assert "no reported change" in finding.statement
    assert "conflict" not in finding.statement.casefold()


def test_synthesis_uses_backend_direction_and_statement_for_no_change() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Laser power and scan speed increased relative density across "
                    "the reported comparisons."
                ),
                direction="increase",
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "no-change-result",
                "paper-1",
                direction="no_change",
            ),
        ),
    )[0]

    assert len(extractor.payloads) == 1
    assert finding.direction == "no_change"
    assert "no reported change" in finding.statement
    assert "increas" not in finding.statement.casefold()


def test_synthesis_does_not_read_mixed_powder_as_result_heterogeneity() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "For mixed powder batches, the effects of laser power and scan "
                    "speed increased relative density."
                ),
                direction="increase",
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("increase-result", "paper-1"),),
    )[0]

    assert len(extractor.payloads) == 1
    assert finding.direction == "increase"
    assert "increase" in finding.statement


def test_synthesis_splits_non_opposing_directions_without_dropping_evidence() -> None:
    class BackendDirectionExtractor:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def judge_result_set(self, payload: dict) -> SimpleNamespace:
            self.payloads.append(payload)
            return SimpleNamespace(
                model_dump=lambda: {"findings": [_candidate()]},
            )

    extractor = BackendDirectionExtractor()
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-increase"),
            _contribution("paper-mixed"),
        ),
        evidence_records=(
            _evidence("increase-result", "paper-increase", direction="increase"),
            _evidence("mixed-result", "paper-mixed", direction="mixed"),
        ),
    )

    assert {finding.direction for finding in findings} == {"increase", "mixed"}
    assert {
        evidence_id
        for finding in findings
        for evidence_id in finding.supporting_evidence_ids
    } == {"increase-result", "mixed-result"}
    assert all(not finding.contradicting_evidence_ids for finding in findings)
    assert {
        payload["result_set"]["primary_direction"] for payload in extractor.payloads
    } == {"increase", "mixed"}


def test_synthesis_normalizes_scientific_unit_typography_for_display() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    result_set = service._result_sets(
        _objective(variables=["energy density"]),
        (
            _evidence(
                "density-result",
                "paper-1",
                factors=("Energy density (J/mm 3 )",),
                changed_variables=[
                    {
                        "name": "Energy density (J/mm 3 )",
                        "baseline_value": 70,
                        "target_value": 150,
                        "unit": "J/ mm 3",
                    }
                ],
            ),
        ),
    )[0]

    assert result_set["factors"] == ["energy density"]
    assert result_set["result_evidence"][0]["changed_variables"] == [
        {
            "name": "Energy density (J/mm3)",
            "baseline_value": 70,
            "target_value": 150,
            "unit": "J/mm3",
        }
    ]


def test_synthesis_splits_cross_paper_results_at_process_context_boundary() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    common = {"material": [], "sample": [], "test": []}

    result_sets = service._result_sets(
        _objective(
            variables=["scan strategy rotation angle"],
            outcomes=["yield strength"],
        ),
        (
            _evidence(
                "paper-1-result",
                "paper-1",
                factors=("scan strategy rotation angle",),
                outcome="yield strength",
                scientific_context={
                    **common,
                    "process": [{"name": "build orientation", "value": 0}],
                },
            ),
            _evidence(
                "paper-2-result",
                "paper-2",
                factors=("scan strategy rotation angle",),
                outcome="yield strength",
                scientific_context={
                    **common,
                    "process": [{"name": "build orientation", "value": 90}],
                },
            ),
        ),
    )

    assert len(result_sets) == 2
    assert [len(item["result_evidence"]) for item in result_sets] == [1, 1]
    assert len({item["result_set_id"] for item in result_sets}) == 2


def test_synthesis_matches_cross_paper_stratum_when_one_paper_has_two_orientations(
) -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    def evidence(
        evidence_id: str,
        document_id: str,
        orientation: str,
    ) -> ObjectiveEvidence:
        return _evidence(
            evidence_id,
            document_id,
            factors=("post-processing condition",),
            outcome="ultimate tensile strength",
            direction="decrease",
            material="Ti-6Al-4V",
            scientific_context={
                "material": [{"name": "material", "value": "Ti-6Al-4V"}],
                "sample": [
                    {"name": "build orientation", "value": orientation}
                ],
                "process": [
                    {
                        "name": "manufacturing process",
                        "value": "laser powder bed fusion",
                    }
                ],
                "test": [],
            },
        )

    result_sets = service._result_sets(
        _objective(
            material_scope=["Ti-6Al-4V"],
            variables=["post-processing condition"],
            outcomes=["ultimate tensile strength"],
        ),
        (
            evidence("paper-2020-vertical", "paper-2020", "vertical"),
            evidence("paper-2020-horizontal", "paper-2020", "horizontal"),
            evidence("paper-2024-vertical", "paper-2024", "vertical"),
        ),
    )

    assert len(result_sets) == 2
    assert {
        tuple(
            sorted(
                item["document_id"]
                for item in result_set["result_evidence"]
            )
        )
        for result_set in result_sets
    } == {("paper-2020",), ("paper-2020", "paper-2024")}


@pytest.mark.parametrize(
    ("section", "attribute_name", "left_value", "right_value"),
    (
        ("sample", "sample state", "as-built", "annealed"),
        ("test", "test temperature", 25, 650),
    ),
)
def test_synthesis_splits_cross_paper_results_at_scientific_context_boundary(
    section: str,
    attribute_name: str,
    left_value: object,
    right_value: object,
) -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    base_context = {
        "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
        "sample": [],
        "process": [{"name": "process", "value": "LPBF"}],
        "test": [],
    }

    def context(value: object) -> dict:
        return {
            **base_context,
            section: [{"name": attribute_name, "value": value}],
        }

    result_sets = service._result_sets(
        _objective(
            material_scope=["Ti-6Al-4V"],
            variables=["heat treatment temperature"],
            outcomes=["elongation"],
        ),
        (
            _evidence(
                "paper-1-result",
                "paper-1",
                factors=("heat treatment temperature",),
                outcome="elongation",
                material="Ti-6Al-4V",
                scientific_context=context(left_value),
            ),
            _evidence(
                "paper-2-result",
                "paper-2",
                factors=("heat treatment temperature",),
                outcome="elongation",
                material="Ti-6Al-4V",
                scientific_context=context(right_value),
            ),
        ),
    )

    assert len(result_sets) == 2
    assert {
        tuple(item["document_id"] for item in result_set["result_evidence"])
        for result_set in result_sets
    } == {("paper-1",), ("paper-2",)}


def test_synthesis_does_not_use_missing_context_to_bridge_known_states() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    def evidence(
        evidence_id: str,
        document_id: str,
        sample_state: str | None,
    ) -> ObjectiveEvidence:
        return _evidence(
            evidence_id,
            document_id,
            factors=("heat treatment temperature",),
            outcome="elongation",
            material="Ti-6Al-4V",
            scientific_context={
                "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
                "sample": (
                    [{"name": "sample state", "value": sample_state}]
                    if sample_state is not None
                    else []
                ),
                "process": [{"name": "process", "value": "LPBF"}],
                "test": [{"name": "test temperature", "value": 25, "unit": "C"}],
            },
        )

    result_sets = service._result_sets(
        _objective(
            material_scope=["Ti-6Al-4V"],
            variables=["heat treatment temperature"],
            outcomes=["elongation"],
        ),
        (
            evidence("as-built-result", "paper-as-built", "as-built"),
            evidence("annealed-result", "paper-annealed", "annealed"),
            evidence("unknown-state-result", "paper-unknown", None),
        ),
    )

    assert len(result_sets) == 3
    assert all(len(item["result_evidence"]) == 1 for item in result_sets)


def test_synthesis_does_not_claim_cross_paper_support_with_missing_fixed_context(
) -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    shared = {
        "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
        "process": [{"name": "process", "value": "LPBF"}],
        "test": [{"name": "test temperature", "value": 25, "unit": "C"}],
    }

    result_sets = service._result_sets(
        _objective(
            material_scope=["Ti-6Al-4V"],
            variables=["heat treatment temperature"],
            outcomes=["elongation"],
        ),
        (
            _evidence(
                "known-state-result",
                "paper-known",
                factors=("heat treatment temperature",),
                outcome="elongation",
                scientific_context={
                    **shared,
                    "sample": [{"name": "sample state", "value": "as-built"}],
                },
            ),
            _evidence(
                "unknown-state-result",
                "paper-unknown",
                factors=("heat treatment temperature",),
                outcome="elongation",
                scientific_context={**shared, "sample": []},
            ),
        ),
    )

    assert len(result_sets) == 2
    assert all(len(item["result_evidence"]) == 1 for item in result_sets)


def test_synthesis_normalizes_fixed_context_field_names_across_papers() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    contexts = (
        {
            "material": [{"name": "material", "value": "Ti-6Al-4V"}],
            "sample": [{"name": "state", "value": "as-built"}],
            "process": [{"name": "manufacturing process", "value": "LPBF"}],
            "test": [
                {"name": "testing temperature", "value": 25, "unit": "C"}
            ],
        },
        {
            "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
            "sample": [{"name": "sample state", "value": "as-built"}],
            "process": [{"name": "process", "value": "LPBF"}],
            "test": [{"name": "test temperature", "value": 25, "unit": "C"}],
        },
    )

    result_sets = service._result_sets(
        _objective(
            material_scope=["Ti-6Al-4V"],
            variables=["heat treatment temperature"],
            outcomes=["elongation"],
        ),
        tuple(
            _evidence(
                f"paper-{position}-result",
                f"paper-{position}",
                factors=("heat treatment temperature",),
                outcome="elongation",
                scientific_context=context,
            )
            for position, context in enumerate(contexts, start=1)
        ),
    )

    assert len(result_sets) == 1
    assert len(result_sets[0]["result_evidence"]) == 2


def test_synthesis_excludes_changed_axis_from_fixed_context_boundary() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    result_sets = service._result_sets(
        _objective(
            material_scope=["Ti-6Al-4V"],
            variables=["heat treatment temperature"],
            outcomes=["elongation"],
        ),
        tuple(
            _evidence(
                f"paper-{temperature}-result",
                f"paper-{temperature}",
                factors=("heat treatment temperature",),
                outcome="elongation",
                scientific_context={
                    "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
                    "sample": [{"name": "sample state", "value": "as-built"}],
                    "process": [
                        {"name": "process", "value": "LPBF"},
                        {
                            "name": "heat treatment temperature",
                            "value": temperature,
                            "unit": "C",
                        },
                    ],
                    "test": [
                        {"name": "test temperature", "value": 25, "unit": "C"}
                    ],
                },
            )
            for temperature in (800, 900)
        ),
    )

    assert len(result_sets) == 1
    assert len(result_sets[0]["result_evidence"]) == 2


def test_synthesis_splits_same_paper_results_at_fixed_context_boundary() -> None:
    extractor = _Extractor(
        [
            _candidate(),
            _candidate(),
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)
    common = {
        "material": [],
        "sample": [],
        "test": [],
    }

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does scan strategy rotation angle affect yield strength?",
            variables=["scan strategy rotation angle"],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "alpha-0",
                "paper-1",
                factors=("scan strategy rotation angle",),
                outcome="yield strength",
                scientific_context={
                    **common,
                    "process": [
                        {
                            "name": "build orientation alpha angle",
                            "value": 0,
                        },
                        {
                            "name": "build orientation beta angle",
                            "value": 0,
                        },
                    ],
                },
            ),
            _evidence(
                "alpha-45",
                "paper-1",
                factors=("scan strategy rotation angle",),
                outcome="yield strength",
                direction="decrease",
                scientific_context={
                    **common,
                    "process": [
                        {
                            "name": "build orientation alpha angle",
                            "value": 45,
                        },
                        {
                            "name": "build orientation beta angle",
                            "value": 22.5,
                        },
                    ],
                },
            ),
        ),
    )

    assert len(findings) == 2
    assert len(extractor.payloads) == 2
    assert {finding.direction for finding in findings} == {"increase", "decrease"}
    assert all(not finding.contradicting_evidence_ids for finding in findings)
    assert {
        tuple(
            (item["name"], item["value"])
            for item in finding.scientific_context.to_record()["process"]
        )
        for finding in findings
    } == {
        (
            ("build orientation alpha angle", 0),
            ("build orientation beta angle", 0),
        ),
        (
            ("build orientation alpha angle", 45),
            ("build orientation beta angle", 22.5),
        ),
    }


def test_synthesis_splits_distinct_outcomes_into_distinct_findings() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Laser power and scan speed were jointly associated with a "
                    "decrease in elongation."
                ),
                direction="decrease",
            ),
            _candidate(),
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(outcomes=["relative density", "elongation"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "elongation-1",
                "paper-1",
                outcome="elongation",
                direction="decrease",
            ),
        ),
    )

    assert [finding.outcome for finding in findings] == [
        "elongation",
        "relative density",
    ]
    assert all(len(payload["result_set"].get("outcome", "")) > 0 for payload in extractor.payloads)


def test_synthesis_groups_only_exact_factor_tuples() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "off-axis",
                "paper-2",
                factors=("volumetric energy density",),
                attribution_scope="isolated_effect",
            ),
        ),
    )

    assert len(findings) == 1
    assert len(extractor.payloads) == 1
    assert extractor.payloads[0]["result_set"]["factors"] == [
        "laser power",
        "scan speed",
    ]
    assert findings[0].paper_contributions[1].supporting_evidence_ids == ()


def test_synthesis_keeps_coupled_factors_outside_the_objective_axis() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Scan strategy rotation angle, build orientation angle, and layer "
                    "thickness were jointly associated with increased yield strength."
                )
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question=(
                "How do scan strategy rotation angles and build orientation angles "
                "affect yield strength?"
            ),
            variables=[
                "scan strategy rotation angles",
                "build orientation angles",
            ],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(
            _contribution(
                "paper-1",
                changed_variables=[
                    "scan strategy rotation angle",
                    "build orientation angle",
                    "layer thickness",
                ],
                measured_property_scope=["yield strength"],
            ),
        ),
        evidence_records=(
            _evidence(
                "ev-1",
                "paper-1",
                factors=(
                    "scan strategy rotation angles",
                    "build orientation angles",
                    "layer thickness",
                ),
                outcome="yield strength",
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].factors == (
        "build orientation angles",
        "layer thickness",
        "scan strategy rotation angles",
    )
    assert findings[0].attribution_scope == "joint_effect"


def test_synthesis_keeps_every_eligible_result_in_one_atomic_set() -> None:
    extractor = _Extractor(
        [_candidate()]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "measurement-1",
                "paper-1",
                comparison=None,
                attribution_scope="association_only",
            ),
            _evidence("comparison-1", "paper-1"),
        ),
    )[0]

    assert finding.supporting_evidence_ids == ("comparison-1", "measurement-1")
    assert [
        item["evidence_id"]
        for item in extractor.payloads[0]["result_set"]["result_evidence"]
    ] == ["comparison-1", "measurement-1"]


def test_synthesis_does_not_copy_model_numeric_endpoints_into_statement() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Increasing scan strategy rotation angle from 0 to 45 degrees "
                    "increased yield strength from 334.2 to 365.6 MPa."
                )
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)
    evidence_records = (
        _evidence(
            "scan-group-1",
            "paper-1",
            factors=("scan strategy rotation angle",),
            outcome="yield strength",
            source_excerpt=(
                "theta 0: yield strength 334.2 MPa; "
                "theta 45: yield strength 351.9 MPa."
            ),
        ),
        _evidence(
            "scan-group-2",
            "paper-1",
            factors=("scan strategy rotation angle",),
            outcome="yield strength",
            source_excerpt=(
                "theta 0: yield strength 363.1 MPa; "
                "theta 45: yield strength 365.6 MPa."
            ),
        ),
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does scan strategy rotation angle affect yield strength?",
            variables=["scan strategy rotation angle"],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=evidence_records,
    )[0]

    assert finding.factors == ("scan strategy rotation angle",)
    assert finding.outcome == "yield strength"
    assert not any(character.isdigit() for character in finding.statement)


def test_synthesis_generates_non_numeric_statement_for_multi_interval_series() -> None:
    extractor = _Extractor(
        [
            _heterogeneous_candidate(
                statement=(
                    "Across the reported condition series, laser power and scan "
                    "speed from 70 to 150 showed heterogeneous relative density "
                    "responses, with an increase and an opposing decrease."
                ),
            ),
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence("series-70-100", "paper-1"),
            _evidence(
                "series-100-150",
                "paper-1",
                direction="decrease",
                changed_variables=[
                    {
                        "name": "laser power",
                        "baseline_value": 100,
                        "target_value": 150,
                    },
                    {
                        "name": "scan speed",
                        "baseline_value": 900,
                        "target_value": 800,
                    },
                ],
            ),
        ),
    )[0]

    assert len(extractor.payloads) == 1
    assert "opposing directions" in finding.statement
    assert not any(character.isdigit() for character in finding.statement)


def test_synthesis_does_not_publish_number_absent_from_structured_evidence() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [
                _candidate(
                    statement=(
                        "A 45 degree scan strategy rotation angle increased yield "
                        "strength by 1.9 MPa."
                    )
                )
            ]
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does scan strategy rotation angle affect yield strength?",
            variables=["scan strategy rotation angle"],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "angle-result",
                "paper-1",
                factors=("scan strategy rotation angle",),
                outcome="yield strength",
                source_excerpt=(
                    "At a scan strategy rotation angle of 45 degrees, the measured "
                    "yield strength was 351.9 MPa."
                ),
            ),
        ),
    )[0]

    assert not any(character.isdigit() for character in finding.statement)
    assert "scan strategy rotation angle" in finding.statement
    assert "yield strength" in finding.statement


def test_synthesis_does_not_publish_number_from_unrelated_source_property() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [
                _candidate(
                    statement=(
                        "Laser power and scan speed were associated with a 1.9% "
                        "increase in relative density."
                    )
                )
            ]
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "density-result",
                "paper-1",
                source_excerpt=(
                    "Hardness changed by 1.9 HV while relative density reached 99.2%."
                ),
                reported_result={
                    "outcome": "relative density",
                    "value": 99.2,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Relative density reached 99.2%.",
                },
            ),
        ),
    )[0]

    assert not any(character.isdigit() for character in finding.statement)
    assert "relative density" in finding.statement


def test_synthesis_derives_all_same_direction_results_as_support() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor([_candidate()])
    )
    evidence = (
        _evidence("ev-1", "paper-1"),
        _evidence("ev-2", "paper-2"),
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=evidence,
    )[0]

    assert finding.supporting_evidence_ids == ("ev-1", "ev-2")
    assert finding.synthesis_status == "agreement"


def test_synthesis_derives_opposing_result_as_contradiction() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor([_heterogeneous_candidate()])
    )
    evidence = (
        _evidence("ev-1", "paper-1"),
        _evidence(
            "conflict-1",
            "paper-2",
            role="contradictory_result",
            direction="decrease",
        ),
    )
    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=evidence,
    )[0]
    assert finding.supporting_evidence_ids == ("ev-1",)
    assert finding.contradicting_evidence_ids == ("conflict-1",)
    assert finding.synthesis_status == "conflict"


def test_synthesis_derives_within_paper_opposition_statement_and_limitation() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence("increase-1", "paper-1"),
            _evidence("increase-2", "paper-1"),
            _evidence("decrease-1", "paper-1", direction="decrease"),
        ),
    )[0]

    assert len(extractor.payloads) == 1
    assert "opposing directions" in finding.statement
    assert (
        "Within-paper condition comparisons report opposing directions."
        in finding.limitations
    )


def test_synthesis_ignores_unknown_direction_instead_of_treating_it_as_opposition() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor([_candidate()])
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence("unknown-1", "paper-2", direction="unknown"),
        ),
    )[0]

    assert finding.supporting_evidence_ids == ("ev-1",)
    assert finding.contradicting_evidence_ids == ()
    assert finding.direct_document_count == 1


def test_synthesis_assigns_support_and_contradiction_by_direction_not_role() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [
                _candidate(
                    direction="decrease",
                    statement=(
                        "Laser power and scan speed showed heterogeneous relative "
                        "density responses across the reported conditions, with a "
                        "decrease and an opposing increase."
                    ),
                )
            ]
        )
    )
    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1", role="contradictory_result"),
            _evidence(
                "conflict-1",
                "paper-2",
                role="direct_result",
                direction="decrease",
            ),
        ),
    )[0]

    assert finding.direction == "increase"
    assert finding.supporting_evidence_ids == ("ev-1",)
    assert finding.contradicting_evidence_ids == ("conflict-1",)
    assert finding.synthesis_status == "conflict"


def test_synthesis_primary_direction_counts_documents_before_rows() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    repeated_single_paper = tuple(
        _evidence(f"increase-{index}", "paper-heavy", direction="increase")
        for index in range(10)
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-heavy"),
            _contribution("paper-2"),
            _contribution("paper-3"),
        ),
        evidence_records=(
            *repeated_single_paper,
            _evidence("decrease-2", "paper-2", direction="decrease"),
            _evidence("decrease-3", "paper-3", direction="decrease"),
        ),
    )[0]

    assert finding.direction == "decrease"
    assert finding.supporting_evidence_ids == ("decrease-2", "decrease-3")
    assert set(finding.contradicting_evidence_ids) == {
        item.evidence_id for item in repeated_single_paper
    }
    assert finding.direct_document_count == 3


def test_synthesis_does_not_drop_results_after_the_first_48() -> None:
    evidence_ids = [f"evidence-{index}" for index in range(49)]
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    contributions = tuple(
        _contribution(f"paper-{index}") for index in range(49)
    )
    evidence = tuple(
        _evidence(evidence_id, f"paper-{index}")
        for index, evidence_id in enumerate(evidence_ids)
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=contributions,
        evidence_records=evidence,
    )[0]

    result_set_payload = extractor.payloads[0]["result_set"]
    assert len(result_set_payload["result_evidence"]) == 16
    assert result_set_payload["total_evidence_count"] == 49
    assert len(result_set_payload["document_evidence_summaries"]) == 49
    assert finding.direct_document_count == 49


def test_synthesis_compacts_large_condition_series_without_dropping_results() -> None:
    evidence_ids = [f"condition-series-{index}" for index in range(49)]
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    contributions = tuple(
        _contribution(f"paper-{'x' * 96}-{index}") for index in range(49)
    )
    long_result_text = "relative density changed across this comparison " * 30
    evidence = tuple(
        _evidence(
            evidence_id,
            contributions[index].document_id,
            source_excerpt="source evidence " * 200,
            changed_variables=[
                {
                    "name": "laser power",
                    "baseline_value": index,
                    "target_value": index + 1,
                },
                {
                    "name": "scan speed",
                    "baseline_value": 1000 - index,
                    "target_value": 999 - index,
                },
            ],
            reported_result={
                "outcome": "relative density",
                "value": 95 + index / 100,
                "unit": "%",
                "direction": "increase",
                "result_text": long_result_text,
            },
        )
        for index, evidence_id in enumerate(evidence_ids)
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=contributions,
        evidence_records=evidence,
    )[0]

    payload = extractor.payloads[0]
    result_evidence = payload["result_set"]["result_evidence"]
    assert len(result_evidence) == 16
    assert {item["evidence_id"] for item in result_evidence} <= set(evidence_ids)
    assert all(
        set(item)
        == {
            "evidence_id",
            "document_id",
            "changed_variables",
            "reported_result",
            "attribution_scope",
        }
        for item in result_evidence
    )
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) < 45_000
    assert payload["result_set"]["total_evidence_count"] == len(evidence_ids)
    assert len(payload["result_set"]["document_evidence_summaries"]) == len(
        evidence_ids
    )
    assert finding.direct_document_count == 49


def test_synthesis_bounds_prompt_excerpts_and_context_without_dropping_results() -> None:
    result_ids = [f"result-{index}" for index in range(12)]
    context_ids = [f"context-{index}" for index in range(12)]
    extractor = _Extractor(
        [
            _candidate(
                context_evidence_ids=[
                    "context-0",
                    "context-1",
                    "context-10",
                    "context-11",
                    "context-2",
                    "context-3",
                    "context-4",
                    "context-5",
                ],
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)
    contributions = tuple(
        _contribution(f"paper-{index}") for index in range(12)
    )
    long_excerpt = "source evidence " * 200
    results = tuple(
        _evidence(
            evidence_id,
            f"paper-{index}",
            source_excerpt=long_excerpt,
        )
        for index, evidence_id in enumerate(result_ids)
    )
    contexts = tuple(
        _evidence(
            evidence_id,
            f"paper-{index}",
            role="condition_context",
            factors=(),
            outcome=None,
            source_excerpt=long_excerpt,
        )
        for index, evidence_id in enumerate(context_ids)
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=contributions,
        evidence_records=(*results, *contexts),
    )[0]

    payload = extractor.payloads[0]
    assert len(payload["result_set"]["result_evidence"]) == 12
    assert len(payload["context_evidence"]) == 8
    assert all(
        "source_excerpt" not in item
        for item in payload["result_set"]["result_evidence"]
    )
    assert all(
        len(item["source_excerpt"]) <= 320
        for item in payload["context_evidence"]
    )
    assert finding.direct_document_count == 12


def test_synthesis_derives_conflict_and_preserves_both_papers() -> None:
    extractor = _Extractor(
        [_heterogeneous_candidate()]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "conflict-1",
                "paper-2",
                role="contradictory_result",
                direction="decrease",
            ),
        ),
    )[0]

    assert finding.synthesis_status == "conflict"
    assert finding.contradicting_evidence_ids == ("conflict-1",)
    assert finding.contributing_document_ids == ("paper-1", "paper-2")


def test_synthesis_does_not_treat_cited_context_as_a_condition_boundary() -> None:
    context = _evidence(
        "condition-2",
        "paper-2",
        role="condition_context",
        factors=(),
        outcome=None,
    )
    extractor = _Extractor(
        [
            _heterogeneous_candidate(
                context_evidence_ids=["condition-2"],
                condition_boundary_evidence_ids=["conflict-1", "condition-2"],
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "conflict-1",
                "paper-2",
                role="contradictory_result",
                direction="decrease",
            ),
            context,
        ),
    )[0]

    assert finding.synthesis_status == "conflict"
    assert finding.condition_boundary_evidence_ids == ()


def test_synthesis_direct_result_cannot_be_a_condition_boundary() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [
                _heterogeneous_candidate(
                    condition_boundary_evidence_ids=["conflict-1"]
                )
            ]
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "conflict-1",
                "paper-2",
                role="contradictory_result",
                direction="decrease",
            ),
        ),
    )[0]

    assert finding.synthesis_status == "conflict"
    assert finding.condition_boundary_evidence_ids == ()


def test_synthesis_splits_opposing_papers_at_explicit_condition_boundary(
) -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor([_candidate(), _candidate()])
    )
    shared = {"material": [], "sample": [], "test": []}

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence(
                "support-1",
                "paper-1",
                scientific_context={
                    **shared,
                    "process": [{"name": "build orientation", "value": 0}],
                },
            ),
            _evidence(
                "conflict-1",
                "paper-2",
                role="contradictory_result",
                direction="decrease",
                scientific_context={
                    **shared,
                    "process": [{"name": "build orientation", "value": 90}],
                },
            ),
        ),
    )

    assert len(findings) == 2
    assert {finding.direction for finding in findings} == {"increase", "decrease"}
    assert {finding.synthesis_status for finding in findings} == {
        "insufficient_confirmation"
    }
    assert {
        finding.supporting_evidence_ids for finding in findings
    } == {("support-1",), ("conflict-1",)}
    assert all(not finding.contradicting_evidence_ids for finding in findings)
    assert all(not finding.condition_boundary_evidence_ids for finding in findings)


def test_synthesis_keeps_changed_axis_boundary_inside_one_comparable_finding(
) -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor([_heterogeneous_candidate()])
    )

    def result(
        evidence_id: str,
        document_id: str,
        temperature: int,
        direction: str,
    ) -> ObjectiveEvidence:
        return _evidence(
            evidence_id,
            document_id,
            factors=("heat treatment temperature",),
            outcome="elongation",
            direction=direction,
            scientific_context={
                "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
                "sample": [{"name": "sample state", "value": "as-built"}],
                "process": [
                    {"name": "process", "value": "LPBF"},
                    {
                        "name": "heat treatment temperature",
                        "value": temperature,
                        "unit": "C",
                    },
                ],
                "test": [
                    {"name": "test method", "value": "tensile test"},
                    {"name": "test temperature", "value": 25, "unit": "C"},
                ],
            },
        )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            material_scope=["Ti-6Al-4V"],
            variables=["heat treatment temperature"],
            outcomes=["elongation"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            result("lower-range", "paper-1", 800, "increase"),
            result("higher-range", "paper-2", 900, "decrease"),
        ),
    )[0]

    assert finding.synthesis_status == "condition_dependent"
    assert finding.supporting_evidence_ids == ("lower-range",)
    assert finding.contradicting_evidence_ids == ("higher-range",)
    assert set(finding.condition_boundary_evidence_ids) == {
        "lower-range",
        "higher-range",
    }


def test_synthesis_does_not_link_model_boundary_context_implicitly() -> None:
    context = _evidence(
        "condition-2",
        "paper-2",
        role="condition_context",
        factors=(),
        outcome=None,
    )
    extractor = _Extractor(
        [
            _heterogeneous_candidate(
                condition_boundary_evidence_ids=["condition-2"],
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "conflict-1",
                "paper-2",
                role="contradictory_result",
                direction="decrease",
            ),
            context,
        ),
    )[0]

    assert finding.synthesis_status == "conflict"
    assert finding.context_evidence_ids == ()
    assert finding.condition_boundary_evidence_ids == ()


def test_synthesis_drops_boundary_labels_that_are_not_evidence_ids() -> None:
    extractor = _Extractor(
        [
            _heterogeneous_candidate(
                condition_boundary_evidence_ids=["Fixed scan speed"],
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence(
                "conflict-1",
                "paper-2",
                role="contradictory_result",
                direction="decrease",
            ),
        ),
    )[0]

    assert finding.synthesis_status == "conflict"
    assert finding.condition_boundary_evidence_ids == ()


def test_synthesis_binds_mechanism_only_from_selected_context() -> None:
    mechanism = _evidence(
        "mechanism-1",
        "paper-1",
        role="mechanism_context",
        factors=(),
        outcome=None,
    )
    extractor = _Extractor(
        [
            _candidate(
                mechanisms=[
                    {
                        "source_term": "laser power and scan speed",
                        "relation_type": "changes",
                        "target_term": "melt-pool stability",
                        "assertion_strength": "associative",
                        "supporting_evidence_ids": ["mechanism-1"],
                    }
                ],
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"), mechanism),
    )[0]

    assert finding.mechanisms[0].target_term == "melt-pool stability"
    assert finding.context_evidence_ids == ("mechanism-1",)


def test_synthesis_drops_mechanism_with_wrong_evidence_role() -> None:
    condition = _evidence(
        "condition-1",
        "paper-1",
        role="condition_context",
        factors=(),
        outcome=None,
    )
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [
                _candidate(
                    context_evidence_ids=["condition-1"],
                    mechanisms=[
                        {
                            "source_term": "laser power",
                            "relation_type": "changes",
                            "target_term": "melt-pool stability",
                            "assertion_strength": "associative",
                            "supporting_evidence_ids": ["condition-1"],
                        }
                    ],
                )
            ]
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"), condition),
    )[0]

    assert finding.mechanisms == ()
    assert finding.context_evidence_ids == ("condition-1",)


def test_synthesis_keeps_every_candidate_paper_binding() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    excluded = _contribution(
        "paper-2",
        analysis_status="excluded",
        relevance="irrelevant",
        paper_role="irrelevant",
        exclusion_reason="No objective result.",
    )
    failed = _contribution(
        "paper-3",
        analysis_status="failed",
        relevance="uncertain",
        paper_role="uncertain",
        warnings=["Extraction failed."],
    )
    analyzed_without_result = _contribution("paper-4")

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-1"),
            excluded,
            failed,
            analyzed_without_result,
        ),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    )[0]

    assert [item.document_id for item in finding.paper_contributions] == [
        "paper-1",
        "paper-2",
        "paper-3",
        "paper-4",
    ]
    assert finding.paper_contributions[1].analysis_status == "excluded"
    assert finding.paper_contributions[2].analysis_status == "failed"
    assert finding.paper_contributions[3].analysis_status == "analyzed"
    assert finding.paper_contributions[3].has_direct_evidence is False
    assert extractor.payloads[0]["paper_contributions"][1][
        "analysis_status"
    ] == "excluded"


def test_synthesis_statement_keeps_complete_joint_factor_set() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement="Laser power was associated with relative density."
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    )[0]

    assert finding.factors == ("laser power", "scan speed")
    assert "laser power and scan speed" in finding.statement


def test_synthesis_statement_does_not_add_unbound_objective_factor() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Scan strategy rotation angles and build orientation angles "
                    "were associated with yield strength."
                ),
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            variables=[
                "scan strategy rotation angles",
                "build orientation angles",
            ],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "ev-1",
                "paper-1",
                factors=("Scan strategy",),
                outcome="yield strength",
            ),
        ),
    )[0]

    assert finding.factors == ("Scan strategy",)
    assert "build orientation" not in finding.statement.casefold()


def test_synthesis_statement_keeps_broad_source_factor_without_specializing_it() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Scan strategy rotation angles were associated with yield "
                    "strength."
                ),
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            variables=["scan strategy rotation angles"],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "ev-1",
                "paper-1",
                factors=("Scan strategy",),
                outcome="yield strength",
            ),
        ),
    )[0]

    assert finding.factors == ("Scan strategy",)
    assert "Scan strategy" in finding.statement
    assert "rotation angles" not in finding.statement


def test_synthesis_accepts_experimental_outcome_without_repeating_qualifier() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement="Laser power increased yield strength.",
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            variables=["laser power"],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "ev-1",
                "paper-1",
                factors=("laser power",),
                outcome="yield strength experiment",
            ),
        ),
    )[0]

    assert finding.outcome == "yield strength experiment"


def test_synthesis_preserves_prediction_qualifier_in_backend_statement() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement="Laser power increased yield strength.",
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            variables=["laser power"],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "ev-1",
                "paper-1",
                factors=("laser power",),
                outcome="yield strength prediction",
            ),
        ),
    )[0]

    assert finding.outcome == "yield strength prediction"
    assert "yield strength prediction" in finding.statement


def test_synthesis_rejects_causal_joint_factor_candidate() -> None:
    extractor = _Extractor([_candidate(assertion_strength="causal")])
    service = FindingSynthesisService(assertion_judge=extractor)

    assert (
        service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(),
            contributions=(_contribution("paper-1"),),
            evidence_records=(_evidence("ev-1", "paper-1"),),
        )
        == ()
    )


def test_synthesis_rejects_causal_descriptive_candidate() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement="Laser power was associated with relative density.",
                assertion_strength="causal",
            )
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    evidence = _evidence(
        "ev-1",
        "paper-1",
        factors=("laser power",),
        comparison=None,
        attribution_scope="descriptive_only",
    )
    assert (
        service.synthesize(
            collection_id="col-1",
            objective=_objective(variables=["laser power"]),
            analysis=_analysis(),
            contributions=(_contribution("paper-1"),),
            evidence_records=(evidence,),
        )
        == ()
    )


def test_synthesis_downgrades_non_deterministic_isolated_result_to_associative() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [
                _candidate(
                    statement="Laser power increased relative density.",
                    assertion_strength="causal",
                )
            ]
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(variables=["laser power"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence("ev-1", "paper-1", factors=("laser power",)),
        ),
    )[0]

    assert finding.attribution_scope == "isolated_effect"
    assert finding.assertion_strength == "associative"


def test_synthesis_keeps_causal_strength_for_deterministic_controlled_table_pair() -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor(
            [
                _candidate(
                    statement="Laser power increased relative density.",
                    assertion_strength="causal",
                )
            ]
        )
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(variables=["laser power"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "ev-1",
                "paper-1",
                factors=("laser power",),
                source_kind="table",
                selection_reason=(
                    "Deterministic comparison of rows from the same result table."
                ),
                related_source_refs=[
                    {"row_index": 1, "col_index": 2},
                    {"row_index": 2, "col_index": 2},
                ],
            ),
        ),
    )[0]

    assert finding.assertion_strength == "causal"


def test_synthesis_excludes_unattributable_and_context_only_evidence() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    incomparable = _evidence(
        "incomparable-1",
        "paper-1",
        attribution_scope="not_attributable",
        comparison={
            "baseline_label": "as-built",
            "target_label": "HIP",
            "axis_names": ["laser power", "scan speed"],
            "comparable": False,
            "incomparability_reasons": ["sample state differs"],
        },
    )

    assert (
        service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(),
            contributions=(_contribution("paper-1"),),
            evidence_records=(incomparable,),
        )
        == ()
    )
    assert extractor.payloads == []


def test_synthesis_continues_after_one_result_set_provider_failure() -> None:
    extractor = _Extractor(
        [
            ValueError("invalid JSON"),
            _candidate(
                statement=(
                    "Laser power and scan speed were jointly associated with an "
                    "increase in relative density."
                ),
            ),
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)
    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(outcomes=["elongation", "relative density"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "elongation-1",
                "paper-1",
                outcome="elongation",
                direction="decrease",
            ),
            _evidence("ev-1", "paper-1"),
        ),
    )

    assert len(extractor.payloads) == 2
    assert [finding.outcome for finding in findings] == ["relative density"]


def test_synthesis_repairs_unavailable_context_reference_once() -> None:
    extractor = _Extractor(
        [
            _candidate(
                assertion_strength="descriptive",
                context_evidence_ids=["missing-context"],
            ),
            _candidate(
                assertion_strength="descriptive",
            ),
        ]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does energy density affect densification?",
            variables=["energy density"],
            outcomes=["densification"],
        ),
        analysis=_analysis(),
        contributions=(
            _contribution(
                "paper-1",
                changed_variables=["energy density"],
                measured_property_scope=["densification"],
            ),
        ),
        evidence_records=(
            _evidence(
                "ev-density",
                "paper-1",
                factors=("energy density",),
                outcome="densification",
                direction="increase",
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].direction == "increase"
    assert len(extractor.payloads) == 2
    repair = extractor.payloads[1]["candidate_rejection"]
    assert repair["reason"] == "candidate references unavailable context Evidence"
    assert repair["previous_candidate"] == {
        "assertion_strength": "descriptive",
        "context_evidence_ids": ["missing-context"],
        "mechanisms": [],
    }


def test_synthesis_stops_after_one_semantic_repair(caplog) -> None:
    rejected = _candidate(
        context_evidence_ids=["missing-context"],
    )
    extractor = _Extractor([rejected, rejected])
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    )

    assert findings == ()
    assert len(extractor.payloads) == 2
    assert "semantic_repair_attempted=True" in caplog.text


def test_synthesis_rejects_cross_version_children_and_orphan_evidence() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    with pytest.raises(ValueError, match="another objective version"):
        service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(),
            contributions=(_contribution("paper-1", analysis_version=2),),
            evidence_records=(),
        )
    with pytest.raises(ValueError, match="lacks a PaperContribution"):
        service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(),
            contributions=(_contribution("paper-1"),),
            evidence_records=(_evidence("ev-1", "paper-2"),),
        )
