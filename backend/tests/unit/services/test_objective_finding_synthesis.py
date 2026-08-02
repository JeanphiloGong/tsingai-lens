from __future__ import annotations

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
        response = self.responses.pop(0)
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
        "supporting_evidence_ids": ["ev-1"],
        "contradicting_evidence_ids": [],
        "condition_boundary_evidence_ids": [],
        "context_evidence_ids": [],
        "mechanisms": [],
        "limitations": [],
    }
    payload.update(overrides)
    return payload


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


def test_synthesis_derives_cross_paper_agreement() -> None:
    extractor = _Extractor(
        [_candidate(supporting_evidence_ids=["ev-1", "ev-2"])]
    )
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


def test_synthesis_splits_distinct_outcomes_into_distinct_findings() -> None:
    extractor = _Extractor(
        [
            _candidate(
                statement=(
                    "Laser power and scan speed were jointly associated with a "
                    "decrease in elongation."
                ),
                direction="decrease",
                supporting_evidence_ids=["elongation-1"],
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
    extractor = _Extractor([_candidate(supporting_evidence_ids=["ev-1"])])
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


def test_synthesis_keeps_every_eligible_result_in_one_atomic_set() -> None:
    extractor = _Extractor(
        [
            _candidate(
                supporting_evidence_ids=["comparison-1", "measurement-1"]
            )
        ]
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


def test_synthesis_rejects_omitted_result_evidence() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor(
            [_candidate(supporting_evidence_ids=["ev-1"])]
        )
    )
    evidence = (
        _evidence("ev-1", "paper-1"),
        _evidence("conflict-1", "paper-2", role="contradictory_result"),
    )
    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=evidence,
    )
    assert findings == ()


def test_synthesis_rejects_duplicate_result_assignment_without_silent_dedup() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor(
            [_candidate(supporting_evidence_ids=["ev-1", "ev-1"])]
        )
    )

    assert service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    ) == ()


def test_synthesis_assigns_support_and_contradiction_by_direction_not_role() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor(
            [
                _candidate(
                    supporting_evidence_ids=["conflict-1"],
                    contradicting_evidence_ids=["ev-1"],
                    direction="decrease",
                    statement=(
                        "Laser power and scan speed were jointly associated with a "
                        "decrease in relative density."
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


def test_synthesis_rejects_same_direction_as_contradiction() -> None:
    service = FindingSynthesisService(
        structured_extractor=_Extractor(
            [
                _candidate(
                    supporting_evidence_ids=["ev-1"],
                    contradicting_evidence_ids=["same-direction"],
                )
            ]
        )
    )

    assert service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"), _contribution("paper-2")),
        evidence_records=(
            _evidence("ev-1", "paper-1"),
            _evidence("same-direction", "paper-2", role="contradictory_result"),
        ),
    ) == ()


def test_synthesis_does_not_drop_results_after_the_first_48() -> None:
    evidence_ids = [f"evidence-{index}" for index in range(49)]
    extractor = _Extractor(
        [_candidate(supporting_evidence_ids=evidence_ids)]
    )
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


def test_synthesis_derives_conflict_and_preserves_both_papers() -> None:
    extractor = _Extractor(
        [
            _candidate(
                supporting_evidence_ids=["ev-1"],
                contradicting_evidence_ids=["conflict-1"],
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
    assert finding.contradicting_evidence_ids == ("conflict-1",)
    assert finding.contributing_document_ids == ("paper-1", "paper-2")


def test_synthesis_requires_cited_boundary_for_condition_dependence() -> None:
    context = _evidence(
        "condition-2",
        "paper-2",
        role="condition_context",
        factors=(),
        outcome=None,
    )
    extractor = _Extractor(
        [
            _candidate(
                supporting_evidence_ids=["ev-1"],
                contradicting_evidence_ids=["conflict-1"],
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

    assert finding.synthesis_status == "condition_dependent"
    assert finding.condition_boundary_evidence_ids == (
        "conflict-1",
        "condition-2",
    )


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
                context_evidence_ids=["mechanism-1"],
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


def test_synthesis_rejects_parse_valid_mechanism_with_wrong_evidence_role() -> None:
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

    assert service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"), condition),
    ) == ()


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
