from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    PreparedDocumentInput,
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
        "document_inputs": (
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        "pipeline_version": "objective-analysis.v2",
        "model_name": "test-model",
        "prompt_versions": {},
        "status": "running",
        "phase": "finding_synthesis",
        "total_document_count": 1,
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
            "test": [{"name": "method", "value": "measurement"}],
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


def test_synthesis_keeps_source_result_that_is_not_yet_attributable() -> None:
    """A reported result must remain reviewable when same-paper context is open."""

    extractor = _Extractor([])
    service = FindingSynthesisService(assertion_judge=extractor)
    evidence = _evidence(
        "ev-unattributed",
        "paper-1",
        attribution_scope="not_attributable",
        comparison=None,
        selection_reason=(
            "Source-backed result retained. Research context remains open; "
            "missing same-paper fields: comparison, process, test."
        ),
        resolution_status="partial",
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    assert findings[0].attribution_scope == "descriptive_only"
    assert findings[0].supporting_evidence_ids == ("ev-unattributed",)


def test_synthesis_does_not_cross_compare_paper_with_incomplete_source_coverage() -> None:
    extractor = _Extractor([_candidate(), _candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    with capture_analysis_diagnostics() as diagnostics:
        findings = service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(
                document_inputs=(
                    PreparedDocumentInput(
                        document_id="paper-1",
                        preparation_fingerprint="fingerprint-paper-1",
                    ),
                    PreparedDocumentInput(
                        document_id="paper-2",
                        preparation_fingerprint="fingerprint-paper-2",
                    ),
                ),
                total_document_count=2,
            ),
            contributions=(
                _contribution(
                    "paper-1",
                    evidence_disposition="coverage_incomplete",
                    routed_source_count=2,
                    extracted_source_count=1,
                    comparable_evidence_count=1,
                    failed_source_count=0,
                    uninspected_source_count=1,
                    evidence_disposition_reason="1 relevant Source was not inspected.",
                ),
                _contribution("paper-2"),
            ),
            evidence_records=(
                _evidence("ev-1", "paper-1"),
                _evidence("ev-2", "paper-2"),
            ),
        )

    assert len(findings) == 2
    assert all(finding.direct_document_count == 1 for finding in findings)
    assert all(
        finding.synthesis_status == "insufficient_confirmation"
        for finding in findings
    )
    assert {
        evidence_id
        for finding in findings
        for contribution in finding.paper_contributions
        for evidence_id in contribution.supporting_evidence_ids
    } == {"ev-1", "ev-2"}
    assert all(finding.support_scope == "paper" for finding in findings)
    incomplete_finding = next(
        finding
        for finding in findings
        if finding.supporting_evidence_ids == ("ev-1",)
    )
    assert any(
        "not inspected" in limitation.casefold()
        for limitation in incomplete_finding.limitations
    )
    assert diagnostics.records == (
        {
            "trace_type": "objective_finding_coverage_gate",
            "collection_id": "col-1",
            "objective_id": "obj-density",
            "analysis_version": 1,
            "excluded_document_ids": ["paper-1"],
            "uninspected_source_count": 1,
            "eligible_result_evidence_count": 2,
            "excluded_result_evidence_count": 1,
            "paper_scoped_result_set_count": 1,
            "disposition": "paper_scoped_until_coverage_complete",
        },
    )


def test_synthesis_keeps_source_result_when_material_scope_is_unresolved() -> None:
    """An incomplete material match is a qualified paper result, not an empty run."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "ev-unresolved-material",
                "paper-1",
                scientific_context={
                    "material": [],
                    "sample": [{"name": "state", "value": "as-built"}],
                    "process": [{"name": "process", "value": "LPBF"}],
                    "test": [{"name": "method", "value": "tensile test"}],
                },
            ),
        ),
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.assertion_strength == "descriptive"
    assert finding.synthesis_status == "insufficient_confirmation"
    assert finding.supporting_evidence_ids == ("ev-unresolved-material",)
    assert "associated" in finding.statement
    assert any(
        "Material scope is not confirmed" in limitation
        for limitation in finding.limitations
    )


def test_synthesis_downgrades_result_with_open_process_context_to_association() -> None:
    """Missing fixed process context must not support an isolated Finding."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does laser power affect relative density?",
        variables=["laser power"],
        outcomes=["relative density"],
    )
    evidence = _evidence(
        "ev-open-process",
        "paper-1",
        factors=("laser power",),
        outcome="relative density",
        scientific_context={
            "material": [{"name": "material", "value": "316L"}],
            "sample": [{"name": "state", "value": "as-built"}],
            "process": [],
            "test": [{"name": "method", "value": "density measurement"}],
        },
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    assert findings[0].support_scope == "paper"
    assert findings[0].attribution_scope == "association_only"
    assert findings[0].assertion_strength == "descriptive"
    assert any(
        "process" in limitation.casefold()
        for limitation in findings[0].limitations
    )


def test_synthesis_keeps_qualitative_source_result_when_factor_is_in_source_text() -> None:
    """A grounded qualitative statement must not disappear without numeric endpoints."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    evidence = _evidence(
        "ev-lcf-qualitative",
        "paper-1",
        factors=("volumetric energy density",),
        comparison=None,
        attribution_scope="descriptive_only",
        outcome="low cycle fatigue strength",
        source_excerpt=(
            "The difference diminished in low cycle fatigue regimes for medium "
            "and high VED structures, where fatigue strength was enhanced."
        ),
        reported_result={
            "outcome": "low cycle fatigue strength",
            "value": None,
            "unit": None,
            "direction": "improve",
            "result_text": (
                "medium and high VED structures enhanced low cycle fatigue strength"
            ),
        },
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does volumetric energy density affect low cycle fatigue strength?",
            variables=["volumetric energy density"],
            outcomes=["low cycle fatigue strength"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    assert findings[0].factors == ("volumetric energy density",)
    assert findings[0].assertion_strength == "descriptive"
    assert findings[0].attribution_scope == "descriptive_only"
    assert findings[0].supporting_evidence_ids == ("ev-lcf-qualitative",)
    assert "low cycle fatigue strength" in findings[0].statement
    assert "associated" not in findings[0].statement
    assert findings[0].statement.startswith("The Source reported")


def test_synthesis_keeps_source_result_when_variable_endpoints_are_unstructured() -> None:
    """A source-local variable mention must survive missing structured endpoints."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    evidence = _evidence(
        "ev-unstructured-variable",
        "paper-1",
        factors=(),
        changed_variables=[],
        comparison=None,
        attribution_scope="descriptive_only",
        source_excerpt=(
            "At higher laser power, the melt pool was more stable and porosity "
            "was reduced."
        ),
        reported_result={
            "outcome": "porosity",
            "value": None,
            "unit": None,
            "direction": "decrease",
            "result_text": "Porosity was reduced at higher laser power.",
        },
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does laser power affect porosity?",
            variables=["laser power"],
            outcomes=["porosity"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    assert findings[0].factors == ("laser power",)
    assert findings[0].attribution_scope == "descriptive_only"
    assert findings[0].assertion_strength == "descriptive"
    assert findings[0].supporting_evidence_ids == ("ev-unstructured-variable",)


def test_synthesis_does_not_qualify_out_of_scope_result_as_finding() -> None:
    """A source result for another outcome must remain outside this Objective."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(outcomes=["porosity"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(
            _evidence(
                "ev-relative-density",
                "paper-1",
                outcome="relative density",
            ),
        ),
    )

    assert findings == ()


def test_synthesis_keeps_backend_result_when_judge_returns_empty_candidate() -> None:
    """A judge abstention must not erase a source-backed result set."""

    extractor = _Extractor([None])
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    )

    assert len(findings) == 1
    assert findings[0].assertion_strength == "descriptive"
    assert findings[0].supporting_evidence_ids == ("ev-1",)


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
    assert finding.certainty == 0.75
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
                "test": [{"name": "method", "value": "tensile test"}],
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


def test_synthesis_calibrates_reference_treatment_finding_to_paper_support(
) -> None:
    service = FindingSynthesisService(
        assertion_judge=_Extractor([_candidate(assertion_strength="causal")])
    )
    objective = _objective(
        variables=["post-processing condition"],
        outcomes=["ultimate tensile strength"],
        material_scope=["Ti-6Al-4V"],
    )

    def comparison(
        evidence_id: str,
        document_id: str,
        baseline: str,
        target: str,
        baseline_uts: float,
        target_uts: float,
    ) -> ObjectiveEvidence:
        return _evidence(
            evidence_id,
            document_id,
            factors=("post-processing condition",),
            outcome="ultimate tensile strength",
            direction="decrease",
            material="Ti-6Al-4V",
            source_kind="table",
            selection_reason=(
                "Deterministic comparison of rows from the same result table."
            ),
            related_source_refs=[
                {"row_index": 1, "col_index": 2},
                {"row_index": 2, "col_index": 2},
            ],
            changed_variables=[
                {
                    "name": "post-processing condition",
                    "baseline_value": baseline,
                    "target_value": target,
                }
            ],
            reported_result={
                "outcome": "ultimate tensile strength",
                "baseline_value": baseline_uts,
                "target_value": target_uts,
                "value": target_uts,
                "unit": "MPa",
                "direction": "decrease",
                "result_text": (
                    f"UTS changed from {baseline_uts} to {target_uts} MPa."
                ),
            },
            attribution_scope="association_only",
            confidence=0.92,
            scientific_context={
                "material": [{"name": "material", "value": "Ti-6Al-4V"}],
                "sample": [
                    {"name": "build orientation", "value": "vertical"}
                ],
                "process": [
                    {
                        "name": "manufacturing process",
                        "value": "laser powder bed fusion",
                    }
                ],
                "test": [{"name": "method", "value": "tensile test"}],
            },
        )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-2020"), _contribution("paper-2024")),
        evidence_records=(
            comparison(
                "2020-af-to-hip",
                "paper-2020",
                "as-fabricated",
                "HIP + polishing",
                1006.7,
                936.0,
            ),
            comparison(
                "2024-ab-to-800-sc",
                "paper-2024",
                "AB",
                "800 SC",
                1294.2,
                1082.43,
            ),
        ),
    )

    assert len(findings) == 2
    assert all(
        finding.statement == (
            "For Ti-6Al-4V at vertical build orientation, relative to "
            "as-built/as-fabricated reference conditions, the evaluated "
            "post-processing conditions were associated with lower ultimate "
            "tensile strength."
        )
        for finding in findings
    )
    assert all(finding.synthesis_status == "insufficient_confirmation" for finding in findings)
    assert all(finding.assertion_strength == "descriptive" for finding in findings)
    assert all(finding.attribution_scope == "association_only" for finding in findings)
    assert all(finding.certainty == 0.5 for finding in findings)


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


def test_synthesis_preserves_source_reported_qualitative_observation() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    evidence = _evidence(
        "preheating-dislocation-result",
        "paper-1",
        outcome="microstructure",
        factors=("build platform preheating",),
        direction="decrease",
        changed_variables=[
            {
                "name": "build platform preheating",
                "baseline_value": "without preheating",
                "target_value": "preheating to 150 C",
            }
        ],
        reported_result={
            "outcome": "microstructure",
            "value": None,
            "baseline_value": None,
            "target_value": None,
            "unit": None,
            "direction": "decrease",
            "result_text": (
                "Dislocation density decreased, and the microstructure became "
                "similar to the annealed condition."
            ),
        },
    )

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does build platform preheating affect microstructure?",
            variables=("build platform preheating",),
            outcomes=("microstructure",),
        ),
        analysis=_analysis(),
        contributions=(
            _contribution(
                "paper-1",
                changed_variables=["build platform preheating"],
                measured_property_scope=["microstructure"],
            ),
        ),
        evidence_records=(evidence,),
    )[0]

    assert finding.statement.startswith(
        "For build platform preheating (baseline: without preheating; target: "
        "preheating to 150 C), the Source reported this microstructure observation:"
    )
    assert "Dislocation density decreased" in finding.statement
    assert "microstructure became similar to the annealed condition" in finding.statement
    assert "decrease in microstructure" not in finding.statement


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
    common = {
        "material": [{"name": "alloy", "value": "316L"}],
        "sample": [],
        "test": [{"name": "method", "value": "tensile test"}],
    }

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
                "test": [{"name": "method", "value": "tensile test"}],
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
        "test": [{"name": "method", "value": "tensile test"}],
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
        "material": [{"name": "alloy", "value": "316L"}],
        "sample": [],
        "test": [{"name": "method", "value": "tensile test"}],
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


def test_synthesis_keeps_qualified_result_separate_from_comparable_result() -> None:
    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
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
    )

    assert len(findings) == 2
    assert findings[0].supporting_evidence_ids == ("comparison-1",)
    assert findings[1].supporting_evidence_ids == ("measurement-1",)
    assert findings[1].attribution_scope == "association_only"
    assert [
        item["evidence_id"]
        for item in extractor.payloads[0]["result_set"]["result_evidence"]
    ] == ["comparison-1"]


def test_synthesis_keeps_same_source_scalar_rows_as_evidence_not_findings() -> None:
    """A table row remains Evidence once its Source yields a relationship series."""

    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    shared = {
        "source_kind": "table",
        "source_ref": "condition-table",
        "source_excerpt": "Energy input 70 J/mm3; relative density 95.4%.",
    }
    comparison = _evidence(
        "comparison-1",
        "paper-1",
        factors=("energy input",),
        changed_variables=[
            {
                "name": "energy input",
                "baseline_value": 70,
                "target_value": 100,
                "unit": "J/mm3",
            }
        ],
        **shared,
    )
    scalar_row = _evidence(
        "measurement-1",
        "paper-1",
        factors=("energy input",),
        direction="unknown",
        comparison=None,
        attribution_scope="descriptive_only",
        reported_result={
            "outcome": "relative density",
            "value": 95.4,
            "unit": "%",
            "direction": "unknown",
            "result_text": "relative density = 95.4%",
        },
        **shared,
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(
            question="How does energy input affect relative density?",
            variables=["energy input"],
        ),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(comparison, scalar_row),
    )

    assert len(findings) == 1
    assert findings[0].supporting_evidence_ids == ("comparison-1",)
    assert len(extractor.payloads) == 1


def test_incomplete_coverage_keeps_series_finding_without_scalar_noise() -> None:
    """An unread supplemental Source must not replace a valid series with unknowns."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does scan rotation affect yield strength?",
        variables=["scan rotation"],
        outcomes=["yield strength"],
    )
    shared = {
        "source_kind": "table",
        "source_ref": "result-table",
        "source_excerpt": "scan rotation: 0 to 30 deg; yield strength: 334.2 to 342.5 MPa",
    }
    comparison = _evidence(
        "comparison-0-30",
        "paper-1",
        outcome="yield strength",
        factors=("scan rotation",),
        changed_variables=[
            {
                "name": "scan rotation",
                "baseline_value": 0,
                "target_value": 30,
                "unit": "deg",
            }
        ],
        reported_result={
            "outcome": "yield strength",
            "value": 342.5,
            "baseline_value": 334.2,
            "target_value": 342.5,
            "unit": "MPa",
            "direction": "increase",
            "result_text": "Yield strength increased from 334.2 to 342.5 MPa.",
            "result_kind": "measured",
        },
        **shared,
    )
    scalar_rows = tuple(
        _evidence(
            f"measurement-{index}",
            "paper-1",
            outcome="yield strength",
            factors=("scan rotation",),
            direction="unknown",
            comparison=None,
            attribution_scope="descriptive_only",
            changed_variables=[
                {
                    "name": "scan rotation",
                    "baseline_value": None,
                    "target_value": None,
                }
            ],
            reported_result={
                "outcome": "yield strength",
                "value": value,
                "unit": "MPa",
                "direction": "unknown",
                "result_text": f"Yield strength = {value} MPa.",
                "result_kind": "measured",
            },
            **shared,
        )
        for index, value in enumerate((334.2, 342.5), start=1)
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(
            _contribution(
                "paper-1",
                evidence_disposition="coverage_incomplete",
                routed_source_count=2,
                extracted_source_count=1,
                comparable_evidence_count=1,
                failed_source_count=0,
                uninspected_source_count=1,
                evidence_disposition_reason="One supplemental Source was not inspected.",
            ),
        ),
        evidence_records=(comparison, *scalar_rows),
    )

    assert len(findings) == 1
    assert findings[0].supporting_evidence_ids == ("comparison-0-30",)
    assert "direction was not determined" not in findings[0].statement


def test_qualified_results_group_same_source_comparators_as_one_series() -> None:
    """Source-local endpoint rows are Evidence details in one paper result series."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does laser power affect relative density?",
        variables=["laser power"],
    )
    first = _evidence(
        "same-source-low-high",
        "paper-1",
        factors=("laser power",),
        comparison={
            "baseline_label": "low laser power",
            "target_label": "high laser power",
            "axis_names": ["laser power"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        attribution_scope="association_only",
        source_ref="results-1",
        source_excerpt="Relative density increased from low laser power to high laser power.",
    )
    second = _evidence(
        "same-source-medium-high",
        "paper-1",
        factors=("laser power",),
        comparison={
            "baseline_label": "medium laser power",
            "target_label": "very high laser power",
            "axis_names": ["laser power"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        attribution_scope="association_only",
        source_ref="results-1",
        source_excerpt="Relative density increased from medium laser power to very high laser power.",
    )

    result_sets = service._qualified_result_sets(objective, (first, second))

    assert len(result_sets) == 1
    assert {
        item["evidence_id"] for item in result_sets[0]["result_evidence"]
    } == {"same-source-low-high", "same-source-medium-high"}


def test_qualified_results_group_one_paper_relation_across_source_fragments() -> None:
    """A paper-level relationship remains one result when prose and tables repeat it."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does porosity affect elongation?",
        variables=["porosity"],
        outcomes=["elongation"],
    )
    evidence = tuple(
        _evidence(
            evidence_id,
            "paper-1",
            factors=("porosity",),
            direction="increase",
            comparison=None,
            attribution_scope="association_only",
            source_ref=source_ref,
            source_excerpt=source_excerpt,
            changed_variables=[
                {
                    "name": "porosity",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": "%",
                }
            ],
            reported_result={
                "outcome": "elongation",
                "value": None,
                "unit": "%",
                "direction": "increase",
                "result_text": result_text,
                "result_kind": "observed",
            },
        )
        for evidence_id, source_ref, source_excerpt, result_text in (
            (
                "porosity-prose",
                "results-porosity",
                "Lower porosity was associated with higher elongation.",
                "elongation increased as porosity decreased.",
            ),
            (
                "porosity-table",
                "table-mechanics",
                "The table compares samples with different porosity levels.",
                "higher elongation was observed in the lower-porosity samples.",
            ),
        )
    )

    result_sets = service._qualified_result_sets(objective, evidence)

    assert len(result_sets) == 1
    assert {
        item["evidence_id"] for item in result_sets[0]["result_evidence"]
    } == {"porosity-prose", "porosity-table"}


def test_synthesis_groups_pairwise_rows_as_one_experiment_series() -> None:
    """A condition table yields one series conclusion, not one Finding per row pair."""

    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    objective = _objective(
        question=(
            "How do energy input, travel speed, and path strategy affect "
            "relative density?"
        ),
        variables=["energy input", "travel speed", "path strategy"],
        outcomes=["relative density"],
    )
    shared = {
        "source_kind": "table",
        "source_ref": "condition-table",
        "selection_reason": "Deterministic comparison of rows from the same result table.",
    }
    evidence_records = (
        _evidence(
            "series-low-middle",
            "paper-1",
            factors=("energy input", "travel speed"),
            direction="increase",
            attribution_scope="joint_effect",
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "path strategy", "value": "alternating"},
                    {"name": "process", "value": "powder bed fusion"},
                ],
                "test": [{"name": "method", "value": "image analysis"}],
            },
            changed_variables=[
                {
                    "name": "energy input",
                    "baseline_value": 40,
                    "target_value": 60,
                    "unit": "J/mm3",
                },
                {
                    "name": "travel speed",
                    "baseline_value": 1200,
                    "target_value": 900,
                    "unit": "mm/s",
                },
            ],
            **shared,
        ),
        _evidence(
            "series-middle-high",
            "paper-1",
            factors=("energy input", "path strategy"),
            direction="decrease",
            attribution_scope="joint_effect",
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "travel speed", "value": 900, "unit": "mm/s"},
                    {"name": "process", "value": "powder bed fusion"},
                ],
                "test": [{"name": "method", "value": "image analysis"}],
            },
            changed_variables=[
                {
                    "name": "energy input",
                    "baseline_value": 60,
                    "target_value": 80,
                    "unit": "J/mm3",
                },
                {
                    "name": "path strategy",
                    "baseline_value": "alternating",
                    "target_value": "island",
                },
            ],
            **shared,
        ),
        _evidence(
            "series-low-high",
            "paper-1",
            factors=("travel speed", "path strategy"),
            direction="no_change",
            attribution_scope="joint_effect",
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "energy input", "value": 60, "unit": "J/mm3"},
                    {"name": "process", "value": "powder bed fusion"},
                ],
                "test": [{"name": "method", "value": "image analysis"}],
            },
            changed_variables=[
                {
                    "name": "travel speed",
                    "baseline_value": 1200,
                    "target_value": 900,
                    "unit": "mm/s",
                },
                {
                    "name": "path strategy",
                    "baseline_value": "alternating",
                    "target_value": "island",
                },
            ],
            **shared,
        ),
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=evidence_records,
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.factors == ("energy input", "path strategy", "travel speed")
    assert set(finding.supporting_evidence_ids) | set(
        finding.contradicting_evidence_ids
    ) == {"series-low-middle", "series-middle-high", "series-low-high"}
    assert finding.attribution_scope == "joint_effect"
    assert "opposing directions" in finding.statement
    assert {
        item.name for item in finding.scientific_context.process
    }.isdisjoint({"energy input", "path strategy", "travel speed"})
    assert any(
        "individual-factor effects are not identifiable" in limitation
        for limitation in finding.limitations
    )
    assert len(extractor.payloads) == 1
    assert extractor.payloads[0]["result_set"]["total_evidence_count"] == 3


def test_result_table_keeps_independently_varied_axes_as_separate_series() -> None:
    """One table must not turn separate controlled factors into a joint effect."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question=(
            "How do build orientation alpha, build orientation beta, and scan "
            "strategy rotation angle affect yield strength?"
        ),
        variables=[
            "build orientation",
            "scan strategy rotation angle",
        ],
        outcomes=["yield strength"],
    )
    shared = {
        "source_kind": "table",
        "source_ref": "yield-strength-table",
        "outcome": "yield strength",
    }
    evidence_records = (
        _evidence(
            "alpha-0-45",
            "paper-1",
            factors=("build orientation alpha angle",),
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "build orientation beta angle", "value": 22.5},
                    {"name": "scan strategy rotation angle", "value": 0},
                ],
                "test": [{"name": "method", "value": "tensile testing"}],
            },
            **shared,
        ),
        _evidence(
            "beta-0-22.5",
            "paper-1",
            factors=("build orientation beta angle",),
            direction="decrease",
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "build orientation alpha angle", "value": 0},
                    {"name": "scan strategy rotation angle", "value": 0},
                ],
                "test": [{"name": "method", "value": "tensile testing"}],
            },
            **shared,
        ),
        _evidence(
            "theta-0-30",
            "paper-1",
            factors=("scan strategy rotation angle",),
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "build orientation alpha angle", "value": 0},
                    {"name": "build orientation beta angle", "value": 0},
                ],
                "test": [{"name": "method", "value": "tensile testing"}],
            },
            **shared,
        ),
        _evidence(
            "theta-30-45",
            "paper-1",
            factors=("scan strategy rotation angle",),
            changed_variables=[
                {
                    "name": "scan strategy rotation angle",
                    "baseline_value": 30,
                    "target_value": 45,
                    "unit": "degree",
                }
            ],
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "build orientation alpha angle", "value": 0},
                    {"name": "build orientation beta angle", "value": 0},
                ],
                "test": [{"name": "method", "value": "tensile testing"}],
            },
            **shared,
        ),
    )

    result_sets = service._result_sets(objective, evidence_records)

    assert {tuple(item["factors"]) for item in result_sets} == {
        ("build orientation alpha angle",),
        ("build orientation beta angle",),
        ("scan strategy rotation angle",),
    }
    assert not any(len(item["factors"]) > 1 for item in result_sets)
    theta_set = next(
        item
        for item in result_sets
        if item["factors"] == ["scan strategy rotation angle"]
    )
    assert {
        item["evidence_id"] for item in theta_set["result_evidence"]
    } == {"theta-0-30", "theta-30-45"}


def test_complete_specific_comparison_supersedes_broad_qualitative_finding() -> None:
    """A precise table result carries the Finding; the broad repeat stays Evidence."""

    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)
    objective = _objective(
        question="How does build orientation affect yield strength?",
        variables=["build orientation"],
        outcomes=["yield strength"],
    )
    shared_context = {
        "material": [{"name": "alloy", "value": "316L"}],
        "sample": [{"name": "state", "value": "as-built"}],
        "process": [{"name": "process", "value": "LPBF"}],
        "test": [{"name": "method", "value": "tensile testing"}],
    }
    comparison = _evidence(
        "alpha-comparison",
        "paper-1",
        factors=("build orientation alpha angle",),
        outcome="yield strength",
        changed_variables=[
            {
                "name": "build orientation alpha angle",
                "baseline_value": 0,
                "target_value": 45,
                "unit": "degree",
            }
        ],
        source_kind="table",
        source_ref="yield-strength-table",
        scientific_context=shared_context,
    )
    broad_repeat = _evidence(
        "broad-conclusion",
        "paper-1",
        factors=("build orientation",),
        outcome="yield strength",
        comparison=None,
        attribution_scope="association_only",
        confidence=0.4,
        resolution_status="partial",
        changed_variables=[
            {
                "name": "build orientation",
                "baseline_value": None,
                "target_value": None,
            }
        ],
        source_kind="text_window",
        source_ref="conclusion-block",
        source_excerpt="Build orientation was associated with yield strength.",
        scientific_context={
            **shared_context,
            "process": [{"name": "technique", "value": "L-PBF"}],
        },
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(comparison, broad_repeat),
    )

    assert len(findings) == 1
    assert findings[0].factors == ("build orientation alpha angle",)
    assert findings[0].supporting_evidence_ids == ("alpha-comparison",)
    assert len(extractor.payloads) == 1


def test_experiment_series_keeps_distinct_non_objective_test_contexts_separate() -> None:
    """One Source can still contain separate experiments under different test context."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(variables=["energy input"])
    evidence_records = tuple(
        _evidence(
            f"temperature-{temperature}",
            "paper-1",
            factors=("energy input",),
            source_kind="table",
            source_ref="condition-table",
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [{"name": "process", "value": "powder bed fusion"}],
                "test": [
                    {"name": "temperature", "value": temperature, "unit": "C"}
                ],
            },
        )
        for temperature in (20, 200)
    )

    result_sets = service._result_sets(objective, evidence_records)

    assert len(result_sets) == 2
    assert [len(item["result_evidence"]) for item in result_sets] == [1, 1]


def test_qualified_results_group_same_paper_descriptive_measurements() -> None:
    """A result table is one paper-level observation set, not one Finding per row."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does build platform temperature condition affect elongation?",
        variables=["build platform temperature condition"],
        outcomes=["elongation"],
    )
    first = _evidence(
        "table-row-1",
        "paper-1",
        factors=(),
        outcome="elongation",
        direction="unknown",
        comparison=None,
        attribution_scope="descriptive_only",
        source_ref="table-2",
        source_excerpt=(
            "Build platform temperature condition: Non-preheated; elongation 72%."
        ),
        reported_result={
            "outcome": "elongation",
            "value": 72,
            "unit": "%",
            "direction": "unknown",
            "result_text": "elongation = 72%",
        },
    )
    second = _evidence(
        "table-row-2",
        "paper-1",
        factors=(),
        outcome="elongation",
        direction="unknown",
        comparison=None,
        attribution_scope="descriptive_only",
        source_ref="table-2",
        source_excerpt=(
            "Build platform temperature condition: Preheated; elongation 82%."
        ),
        reported_result={
            "outcome": "elongation",
            "value": 82,
            "unit": "%",
            "direction": "unknown",
            "result_text": "elongation = 82%",
        },
    )

    result_sets = service._qualified_result_sets(objective, (first, second))

    assert len(result_sets) == 1
    assert [
        item["evidence_id"] for item in result_sets[0]["result_evidence"]
    ] == ["table-row-1", "table-row-2"]


def test_qualified_results_merge_same_paper_partial_context_without_crossing_conflict() -> None:
    """Methods context and a Source-local result form one paper result set."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does laser power affect relative density?",
        variables=["laser power"],
        outcomes=["relative density"],
    )
    complete = _evidence(
        "methods-and-results",
        "paper-1",
        factors=("laser power",),
        scientific_context={
            "material": [{"name": "alloy", "value": "316L"}],
            "sample": [{"name": "state", "value": "as-built"}],
            "process": [{"name": "process", "value": "LPBF"}],
            "test": [{"name": "method", "value": "density measurement"}],
        },
    )
    result_only = _evidence(
        "table-result",
        "paper-1",
        factors=("laser power",),
        scientific_context={
            "material": [{"name": "alloy", "value": "316L"}],
            "sample": [],
            "process": [{"name": "process", "value": "LPBF"}],
            "test": [],
        },
    )

    result_sets = service._qualified_result_sets(objective, (complete, result_only))

    assert len(result_sets) == 1
    assert {
        item["evidence_id"] for item in result_sets[0]["result_evidence"]
    } == {"methods-and-results", "table-result"}


def test_qualified_results_do_not_bind_ambiguous_context_free_source() -> None:
    """A context-free Source must not be assigned to two known conditions."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does heat treatment affect relative density?",
        variables=["heat treatment"],
        outcomes=["relative density"],
    )
    contexts = {
        "as-built-result": "as-built",
        "annealed-result": "annealed",
    }
    evidence = tuple(
        _evidence(
            evidence_id,
            "paper-1",
            factors=("heat treatment",),
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": state}] if state else [],
                "process": [{"name": "process", "value": "LPBF"}],
                "test": [{"name": "method", "value": "density measurement"}],
            },
        )
        for evidence_id, state in (*contexts.items(), ("context-free-result", None))
    )

    result_sets = service._qualified_result_sets(objective, evidence)

    assert len(result_sets) == 3
    assert {
        tuple(item["evidence_id"] for item in result_set["result_evidence"])
        for result_set in result_sets
    } == {
        ("as-built-result",),
        ("annealed-result",),
        ("context-free-result",),
    }


def test_qualified_result_keeps_joint_factors_outside_objective_scope() -> None:
    """A broad Objective must not erase co-varied factors from a paper result."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    evidence = _evidence(
        "joint-ved-result",
        "paper-1",
        factors=(
            "laser power",
            "scanning speed",
            "hatch spacing",
            "volumetric energy density",
        ),
        outcome="high cycle fatigue strength",
        attribution_scope="joint_effect",
        scientific_context={
            "material": [{"name": "material", "value": "316L stainless steel"}],
            "sample": [],
            "process": [{"name": "process", "value": "LPBF"}],
            "test": [{"name": "method", "value": "fatigue test"}],
        },
        comparison={
            "baseline_label": "low VED",
            "target_label": "high VED",
            "axis_names": [
                "laser power",
                "scanning speed",
                "hatch spacing",
                "volumetric energy density",
            ],
            "comparable": True,
            "incomparability_reasons": [],
        },
    )
    objective = _objective(
        question="How does volumetric energy density affect high cycle fatigue strength?",
        variables=["volumetric energy density"],
        outcomes=["high cycle fatigue strength"],
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    assert findings[0].factors == (
        "hatch spacing",
        "laser power",
        "scanning speed",
        "volumetric energy density",
    )
    assert findings[0].supporting_evidence_ids == ("joint-ved-result",)
    assert findings[0].attribution_scope == "joint_effect"


def test_synthesis_keeps_non_comparable_results_out_of_strict_finding() -> None:
    """A researcher must see incomplete observations without treating them as comparisons."""

    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-1"),
            _contribution("paper-2"),
        ),
        evidence_records=(
            _evidence("complete-comparison", "paper-1"),
            _evidence(
                "paper-1-association",
                "paper-1",
                comparison=None,
                attribution_scope="association_only",
            ),
            _evidence(
                "paper-2-association",
                "paper-2",
                comparison=None,
                attribution_scope="association_only",
            ),
        ),
    )

    strict_findings = [
        finding
        for finding in findings
        if finding.supporting_evidence_ids == ("complete-comparison",)
    ]
    qualified_findings = [
        finding
        for finding in findings
        if finding.supporting_evidence_ids
        and finding.supporting_evidence_ids != ("complete-comparison",)
    ]

    assert len(strict_findings) == 1
    assert {finding.supporting_evidence_ids[0] for finding in qualified_findings} == {
        "paper-1-association",
        "paper-2-association",
    }
    assert all(
        finding.attribution_scope == "association_only"
        for finding in qualified_findings
    )


def test_synthesis_keeps_association_only_evidence_out_of_causal_finding() -> None:
    """Complete associative endpoints yield no causal claim, but can be synthesized."""

    extractor = _Extractor([_candidate()])
    service = FindingSynthesisService(assertion_judge=extractor)

    association_evidence = tuple(
        _evidence(
            f"association-{document_id}",
            document_id,
            attribution_scope="association_only",
        )
        for document_id in ("paper-1", "paper-2")
    )
    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-1"),
            _contribution("paper-2"),
        ),
        evidence_records=association_evidence,
    )

    assert len(findings) == 1
    assert findings[0].attribution_scope == "association_only"
    assert findings[0].assertion_strength == "associative"
    assert findings[0].synthesis_status == "agreement"
    assert service.is_comparable_result_evidence(
        _objective(), association_evidence[0]
    ) is False
    assert len(extractor.payloads) == 1


def test_synthesis_groups_grounded_associations_across_compatible_papers() -> None:
    """Compatible source associations yield a qualified cross-paper conclusion."""

    extractor = _Extractor([_candidate(assertion_strength="associative")])
    service = FindingSynthesisService(assertion_judge=extractor)
    association_evidence = tuple(
        _evidence(
            f"association-{document_id}",
            document_id,
            attribution_scope="association_only",
        )
        for document_id in ("paper-1", "paper-2")
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=tuple(
            _contribution(document_id)
            for document_id in ("paper-1", "paper-2")
        ),
        evidence_records=association_evidence,
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.attribution_scope == "association_only"
    assert finding.assertion_strength == "associative"
    assert finding.synthesis_status == "agreement"
    assert set(finding.supporting_evidence_ids) == {
        "association-paper-1",
        "association-paper-2",
    }
    assert len(extractor.payloads) == 1


def test_synthesis_ignores_narrative_context_noise_when_grouping_associations() -> None:
    """Paper-specific descriptions must not split identical test conditions."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    evidence_records = tuple(
        _evidence(
            f"association-{document_id}",
            document_id,
            attribution_scope="association_only",
            scientific_context={
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [{"name": "process", "value": "LPBF"}],
                "test": [
                    {"name": "method", "value": "X-ray computed tomography"},
                    {"name": "details", "value": f"Paper {document_id} summary."},
                    {"name": "methods", "value": f"Paper {document_id} methods."},
                ],
            },
        )
        for document_id in ("paper-1", "paper-2")
    )

    result_sets = service._result_sets(_objective(), evidence_records)

    assert len(result_sets) == 1
    assert {
        item["document_id"] for item in result_sets[0]["result_evidence"]
    } == {"paper-1", "paper-2"}


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


def test_synthesis_retains_unknown_direction_as_paper_scoped_result() -> None:
    """An explicit Source result without a direction remains reviewable."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    objective = _objective(
        question="How does laser power affect relative density?",
        variables=["laser power"],
    )
    evidence = _evidence(
        "unknown-paper-result",
        "paper-1",
        factors=("laser power",),
        direction="unknown",
        attribution_scope="descriptive_only",
    )

    qualified = service._qualified_result_sets(objective, (evidence,))

    assert len(qualified) == 1
    assert qualified[0]["primary_direction"] == "unknown"
    assert "direction" in qualified[0]["quality_note"].casefold()

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    assert findings[0].direction == "unknown"
    assert findings[0].assertion_strength == "descriptive"
    assert "direction" in findings[0].statement.casefold()


def test_synthesis_does_not_duplicate_weaker_statement_of_directional_paper_result() -> None:
    """One experiment remains one Finding while every Source stays auditable."""

    service = FindingSynthesisService(assertion_judge=_Extractor([_candidate()]))
    objective = _objective(
        question="How does build platform preheating affect elongation?",
        variables=["build platform preheating"],
        outcomes=["elongation"],
    )
    context = {
        "material": [{"name": "material", "value": "316L stainless steel"}],
        "sample": [],
        "process": [{"name": "manufacturing process", "value": "LPBF"}],
        "test": [{"name": "method", "value": "tensile testing"}],
    }
    directional = _evidence(
        "table-comparison",
        "paper-1",
        factors=("build platform preheating",),
        outcome="elongation",
        direction="increase",
        source_kind="table",
        source_ref="table-2",
        changed_variables=[
            {
                "name": "build platform preheating",
                "baseline_value": "Non-preheated",
                "target_value": "Preheated",
            }
        ],
        reported_result={
            "outcome": "elongation",
            "value": 82,
            "baseline_value": 72,
            "target_value": 82,
            "unit": "%",
            "direction": "increase",
            "result_text": "Elongation changed from 72% to 82%.",
        },
        scientific_context=context,
    )
    weaker = _evidence(
        "qualitative-repeat",
        "paper-1",
        factors=("build platform preheating",),
        outcome="elongation",
        direction="unknown",
        source_ref="results-ductility",
        changed_variables=[
            {
                "name": "build platform preheating",
                "baseline_value": "non-preheated",
                "target_value": "preheated to 150 C",
            }
        ],
        reported_result={
            "outcome": "elongation",
            "value": None,
            "unit": None,
            "direction": "unknown",
            "result_text": "P150 specimens possess higher ductility than NP ones.",
        },
        scientific_context=context,
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(directional, weaker),
    )

    assert len(findings) == 1
    assert findings[0].direction == "increase"
    assert findings[0].supporting_evidence_ids == ("table-comparison",)


def test_synthesis_keeps_unknown_result_for_distinct_numeric_treatment_level() -> None:
    service = FindingSynthesisService(assertion_judge=_Extractor([_candidate()]))
    objective = _objective(
        question="How does build platform preheating affect elongation?",
        variables=["build platform preheating"],
        outcomes=["elongation"],
    )
    directional = _evidence(
        "preheat-150",
        "paper-1",
        factors=("build platform preheating",),
        outcome="elongation",
        direction="increase",
        changed_variables=[
            {
                "name": "build platform preheating",
                "baseline_value": "without preheating",
                "target_value": "150 C",
            }
        ],
    )
    unresolved = _evidence(
        "preheat-200",
        "paper-1",
        factors=("build platform preheating",),
        outcome="elongation",
        direction="unknown",
        changed_variables=[
            {
                "name": "build platform preheating",
                "baseline_value": "without preheating",
                "target_value": "200 C",
            }
        ],
    )

    findings = service.synthesize(
        collection_id="col-1",
        objective=objective,
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(directional, unresolved),
    )

    assert len(findings) == 2
    assert {finding.direction for finding in findings} == {"increase", "unknown"}


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
    shared = {
        "material": [{"name": "alloy", "value": "316L"}],
        "sample": [],
        "test": [{"name": "method", "value": "tensile test"}],
    }

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


def test_synthesis_bounds_causal_joint_factor_candidate_to_associative() -> None:
    extractor = _Extractor([_candidate(assertion_strength="causal")])
    service = FindingSynthesisService(assertion_judge=extractor)

    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(_evidence("ev-1", "paper-1"),),
    )[0]

    assert finding.attribution_scope == "joint_effect"
    assert finding.assertion_strength == "associative"


def test_synthesis_bounds_causal_descriptive_candidate_to_descriptive() -> None:
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
    finding = service.synthesize(
        collection_id="col-1",
        objective=_objective(variables=["laser power"]),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(evidence,),
    )[0]

    assert finding.attribution_scope == "descriptive_only"
    assert finding.assertion_strength == "descriptive"


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


def test_synthesis_retains_unattributable_result_as_descriptive_finding() -> None:
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

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(),
        analysis=_analysis(),
        contributions=(_contribution("paper-1"),),
        evidence_records=(incomparable,),
    )

    assert len(findings) == 1
    assert findings[0].attribution_scope == "descriptive_only"
    assert findings[0].assertion_strength == "descriptive"
    assert findings[0].supporting_evidence_ids == ("incomparable-1",)
    assert any(
        "complete comparable condition pair" in item.casefold()
        for item in findings[0].limitations
    )
    assert extractor.payloads == []


def test_synthesis_does_not_turn_unresolved_inspection_into_finding() -> None:
    """An inspected Source with no extracted fact remains an audit record only."""

    service = FindingSynthesisService(assertion_judge=_Extractor([]))
    inspection = _evidence(
        "inspection-only",
        "paper-1",
        role="condition_context",
        comparison=None,
        outcome=None,
        factors=(),
        selection_status="candidate",
        selection_reason=(
            "Source was inspected for same-paper context but no source-grounded "
            "context was extracted."
        ),
        resolution_status="unresolved",
        reported_result=None,
    )

    assert (
        service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(),
            contributions=(_contribution("paper-1"),),
            evidence_records=(inspection,),
        )
        == ()
    )


def test_synthesis_fails_atomically_after_one_result_set_provider_failure() -> None:
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
    with pytest.raises(
        RuntimeError,
        match="Finding synthesis failed for result set",
    ):
        service.synthesize(
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

    assert len(extractor.payloads) == 1


def test_synthesis_recovers_backend_result_set_after_empty_model_response(caplog) -> None:
    extractor = _Extractor(
        [RuntimeError("structured extraction returned empty response content")]
    )
    service = FindingSynthesisService(assertion_judge=extractor)

    findings = service.synthesize(
        collection_id="col-1",
        objective=_objective(variables=["laser power"]),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-1", changed_variables=["laser power"]),
        ),
        evidence_records=(
            _evidence("ev-1", "paper-1", factors=("laser power",)),
        ),
    )

    assert len(findings) == 1
    assert findings[0].factors == ("laser power",)
    assert findings[0].outcome == "relative density"
    assert findings[0].direction == "increase"
    assert findings[0].assertion_strength == "descriptive"
    assert findings[0].context_evidence_ids == ()
    assert findings[0].mechanisms == ()
    assert "conservative recovery" in caplog.text


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


def test_synthesis_fails_after_one_unsuccessful_semantic_repair(caplog) -> None:
    rejected = _candidate(
        context_evidence_ids=["missing-context"],
    )
    extractor = _Extractor([rejected, rejected])
    service = FindingSynthesisService(assertion_judge=extractor)

    with pytest.raises(
        RuntimeError,
        match="Finding synthesis remained invalid after repair",
    ):
        service.synthesize(
            collection_id="col-1",
            objective=_objective(),
            analysis=_analysis(),
            contributions=(_contribution("paper-1"),),
            evidence_records=(_evidence("ev-1", "paper-1"),),
        )

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
