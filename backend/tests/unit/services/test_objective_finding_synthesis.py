from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from application.core.finding_synthesis_service import FindingSynthesisService
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

    def synthesize_findings(self, payload: dict) -> SimpleNamespace:
        self.payloads.append(payload)
        response = self.responses.pop(0) if self.responses else None
        if isinstance(response, Exception):
            raise response
        if response is None:
            findings: list[dict] = []
        else:
            candidate = dict(response)
            candidate.setdefault(
                "result_set_id", payload["result_set"]["result_set_id"]
            )
            findings = [candidate]
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
        "statement": (
            "Laser power and scan speed were jointly associated with an increase "
            "in relative density."
        ),
        "direction": "increase",
        "assertion_strength": "associative",
        "condition_boundary_evidence_ids": [],
        "context_evidence_ids": [],
        "mechanisms": [],
        "limitations": [],
    }
    payload.update(overrides)
    return payload


def _heterogeneous_candidate(**overrides) -> dict:
    overrides.setdefault(
        "statement",
        (
            "Laser power and scan speed showed heterogeneous relative density "
            "responses across the reported conditions, with an increase and an "
            "opposing decrease."
        ),
    )
    return _candidate(**overrides)


def test_synthesis_builds_one_atomic_single_paper_finding() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=_Extractor([]))

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
    service = FindingSynthesisService(structured_extractor=_Extractor([]))

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


def test_synthesis_derives_cross_paper_agreement() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=_Extractor([]))
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


def test_synthesis_normalizes_scientific_unit_typography_for_display() -> None:
    service = FindingSynthesisService(structured_extractor=_Extractor([]))

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

    assert result_set["factors"] == ["Energy density (J/mm3)"]
    assert result_set["result_evidence"][0]["changed_variables"] == [
        {
            "name": "Energy density (J/mm3)",
            "baseline_value": 70,
            "target_value": 150,
            "unit": "J/mm3",
        }
    ]


def test_synthesis_does_not_use_complete_context_as_a_grouping_key() -> None:
    service = FindingSynthesisService(structured_extractor=_Extractor([]))
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

    assert len(result_sets) == 1
    assert len(result_sets[0]["result_evidence"]) == 2


def test_synthesis_keeps_context_inside_one_comparison_interval() -> None:
    extractor = _Extractor(
        [
            _heterogeneous_candidate(
                statement=(
                    "Scan strategy rotation angle showed heterogeneous yield strength "
                    "responses across the reported conditions, with an increase and "
                    "an opposing decrease."
                ),
            ),
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)
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

    assert len(findings) == 1
    assert len(extractor.payloads) == 1
    assert findings[0].direction == "increase"
    assert findings[0].contradicting_evidence_ids == ("alpha-45",)
    assert findings[0].scientific_context.to_record()["process"] == [
        {"name": "build orientation alpha angle", "value": 0, "unit": None},
        {"name": "build orientation beta angle", "value": 0, "unit": None},
    ]


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
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=extractor)

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
                    "scan strategy rotation angle",
                    "build orientation angle",
                    "layer thickness",
                ),
                outcome="yield strength",
            ),
        ),
    )

    assert len(findings) == 1
    assert findings[0].factors == (
        "build orientation angle",
        "layer thickness",
        "scan strategy rotation angle",
    )
    assert findings[0].attribution_scope == "joint_effect"


def test_synthesis_keeps_every_eligible_result_in_one_atomic_set() -> None:
    extractor = _Extractor(
        [_candidate()]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

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


def test_synthesis_rejects_statement_mixing_numeric_evidence_endpoints() -> None:
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
    service = FindingSynthesisService(structured_extractor=extractor)
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

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does scan strategy rotation angle affect yield strength?",
            variables=["scan strategy rotation angle"],
            outcomes=["yield strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=evidence_records,
    )

    assert findings == ()


def test_synthesis_rejects_numeric_endpoint_for_multi_interval_series() -> None:
    extractor = _Extractor(
        [
            _heterogeneous_candidate(
                statement=(
                    "Across the reported condition series, laser power and scan "
                    "speed from 70 to 150 showed heterogeneous relative density "
                    "responses, with an increase and an opposing decrease."
                ),
            ),
            None,
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
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
    )

    assert findings == ()
    assert extractor.payloads[1]["candidate_rejection"]["reason"] == (
        "condition-series statement contains a numeric endpoint"
    )


def test_synthesis_rejects_statement_number_absent_from_bound_evidence() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor(
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
    )

    assert findings == ()


def test_synthesis_rejects_statement_number_from_unrelated_source_property() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor(
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

    findings = service.synthesize(
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
    )

    assert findings == ()


def test_synthesis_derives_all_same_direction_results_as_support() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor([_candidate()])
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
        structured_extractor=_Extractor([_heterogeneous_candidate()])
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


def test_synthesis_requires_within_paper_heterogeneity_in_statement_and_limitations(
) -> None:
    extractor = _Extractor(
        [
            _candidate(),
            _candidate(
                statement=(
                    "Across the reported conditions, joint changes in laser power "
                    "and scan speed showed heterogeneous relative density responses: "
                    "increases were accompanied by an opposing decrease."
                )
            ),
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

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

    assert len(extractor.payloads) == 2
    assert "opposing directions" in extractor.payloads[1]["candidate_rejection"][
        "reason"
    ]
    assert "heterogeneous" in finding.statement
    assert (
        "Within-paper condition comparisons report opposing directions."
        in finding.limitations
    )


def test_synthesis_rejects_result_direction_that_is_not_an_explicit_opposition() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor([_candidate()])
    )

    assert service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence("unknown-1", "paper-2", direction="unknown"),
        ),
    ) == ()


def test_synthesis_assigns_support_and_contradiction_by_direction_not_role() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor(
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

    assert finding.direction == "decrease"
    assert finding.supporting_evidence_ids == ("conflict-1",)
    assert finding.contradicting_evidence_ids == ("ev-1",)
    assert finding.synthesis_status == "conflict"


def test_synthesis_does_not_drop_results_after_the_first_48() -> None:
    evidence_ids = [f"evidence-{index}" for index in range(49)]
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)
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

    assert len(extractor.payloads[0]["result_set"]["result_evidence"]) == 49
    assert finding.direct_document_count == 49


def test_synthesis_compacts_large_condition_series_without_dropping_results() -> None:
    evidence_ids = [f"condition-series-{index}" for index in range(49)]
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(structured_extractor=extractor)
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
    assert len(result_evidence) == len(evidence_ids)
    assert {item["evidence_id"] for item in result_evidence} == set(evidence_ids)
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
    service = FindingSynthesisService(structured_extractor=extractor)
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
        len(item["source_excerpt"]) <= 320
        for item in (
            *payload["result_set"]["result_evidence"],
            *payload["context_evidence"],
        )
    )
    assert finding.direct_document_count == 12


def test_synthesis_derives_conflict_and_preserves_both_papers() -> None:
    extractor = _Extractor(
        [_heterogeneous_candidate()]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=extractor)

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
        structured_extractor=_Extractor(
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


def test_synthesis_derives_condition_boundary_from_opposing_papers_with_disjoint_context(
) -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor([_heterogeneous_candidate()])
    )
    shared = {"material": [], "sample": [], "test": []}

    finding = service.synthesize(
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
    )[0]

    assert finding.synthesis_status == "condition_dependent"
    assert set(finding.condition_boundary_evidence_ids) == {
        "support-1",
        "conflict-1",
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
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=extractor)

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
        structured_extractor=_Extractor(
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
    service = FindingSynthesisService(structured_extractor=extractor)
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


def test_synthesis_rejects_statement_that_drops_one_joint_factor() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement="Laser power was associated with relative density."
            )
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

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


def test_synthesis_rejects_statement_that_adds_an_unbound_objective_factor() -> None:
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
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
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
    )

    assert findings == ()


def test_synthesis_rejects_statement_that_specializes_a_broad_factor() -> None:
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
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
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
    )

    assert findings == ()


def test_synthesis_accepts_experimental_outcome_without_repeating_qualifier() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement="Laser power increased yield strength.",
            )
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

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


def test_synthesis_requires_prediction_qualifier_in_statement() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement="Laser power increased yield strength.",
            )
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

    findings = service.synthesize(
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
    )

    assert findings == ()


def test_synthesis_rejects_causal_joint_factor_candidate() -> None:
    extractor = _Extractor([_candidate(assertion_strength="causal")])
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=extractor)

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
        structured_extractor=_Extractor(
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
        structured_extractor=_Extractor(
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
    service = FindingSynthesisService(structured_extractor=extractor)
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
    service = FindingSynthesisService(structured_extractor=extractor)
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


def test_synthesis_repairs_semantically_rejected_production_candidate_once() -> None:
    extractor = _Extractor(
        [
            _candidate(
                result_set_id="model-invented-result-set",
                statement=(
                    "energy density: low -> high results in low densification "
                    "levels, higher porosity"
                ),
                direction="decrease",
                assertion_strength="descriptive",
            ),
            _candidate(
                statement=(
                    "Energy density showed an increase in densification under "
                    "the reported comparison."
                ),
                direction="increase",
                assertion_strength="descriptive",
            ),
        ]
    )
    service = FindingSynthesisService(structured_extractor=extractor)

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
    assert repair["reason"] == (
        "candidate direction decrease has no supporting result Evidence"
    )
    assert repair["previous_candidate"]["result_set_id"].startswith("result_set_")
    assert repair["previous_candidate"]["result_set_id"] != (
        "model-invented-result-set"
    )


def test_synthesis_stops_after_one_semantic_repair(caplog) -> None:
    rejected = _candidate(
        statement="Laser power was associated with relative density.",
    )
    extractor = _Extractor([rejected, rejected])
    service = FindingSynthesisService(structured_extractor=extractor)

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
    service = FindingSynthesisService(structured_extractor=_Extractor([]))

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
