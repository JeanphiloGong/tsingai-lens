from __future__ import annotations

from typing import Mapping

import pytest
from domain.core import (
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
    ObjectiveEvidence,
    PaperContribution,
)
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    FINDING_ASSERTION_STRENGTHS,
    FINDING_ORIGINS,
    FINDING_SYNTHESIS_STATUSES,
    PAPER_CONTRIBUTION_STATUSES,
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
)
from domain.core.finding import _certainty as finding_certainty
from domain.core.finding import _choice
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _datetime_or_none as finding_datetime_or_none
from domain.core.finding import _non_negative_int as finding_non_negative_int
from domain.core.finding import _positive_int as finding_positive_int
from domain.core.finding import _stable_id as finding_stable_id
from domain.core.finding import _strings as finding_strings
from domain.core.finding import _text as finding_text
from domain.core.research_objective import (
    PAPER_RELEVANCE_VALUES,
    PAPER_ROLE_VALUES,
    ObjectiveEvidence,
    PaperContribution,
)
from domain.core.scientific_fact import (
    SCIENTIFIC_CONTEXT_SCOPES,
    SCIENTIFIC_RESULT_DIRECTIONS,
    ScientificAttribute,
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)
from domain.core.scientific_fact import _choice as scientific_choice
from domain.core.scientific_fact import _scientific_scalar as scientific_scalar
from domain.core.scientific_fact import _terms as scientific_terms
from domain.core.scientific_fact import _text as scientific_text


def _evidence(
    evidence_id: str,
    document_id: str,
    *,
    analysis_version: int = 1,
    role: str = "direct_result",
    factors: tuple[str, ...] = ("preheating",),
    attribution_scope: str = "isolated_effect",
    confidence: float = 0.9,
    material: str = "316L",
    direction: str = "increase",
) -> ObjectiveEvidence:
    result_role = role in {"direct_result", "contradictory_result"}
    return ObjectiveEvidence(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=analysis_version,
        evidence_id=evidence_id,
        document_id=document_id,
        source_kind="text_window",
        source_ref=f"{document_id}-block-1",
        source_excerpt="Preheating was associated with higher ductility.",
        page_numbers=(),
        related_source_refs=(),
        evidence_role=role,
        selection_status="extracted",
        selection_reason=None,
        changed_variables=(
            tuple(
                ScientificVariable(factor, f"baseline {factor}", f"target {factor}")
                for factor in factors
            )
            if result_role
            else ()
        ),
        comparison=(
            ScientificComparison("baseline", "target", factors, True)
            if result_role
            else None
        ),
        reported_result=(
            ScientificResult(
                "ductility",
                None,
                None,
                direction,
                "Preheating was associated with higher ductility.",
            )
            if result_role
            else None
        ),
        attribution_scope=attribution_scope if result_role else "not_attributable",
        scientific_context=ScientificContext(
            material=(ScientificAttribute("alloy", material),),
            test=(ScientificAttribute("temperature", 25, "C"),),
        ),
        resolution_status="resolved",
        failure_reason=None,
        confidence=confidence,
    )


def _contribution(
    document_id: str,
    *,
    analysis_status: str = "analyzed",
) -> PaperContribution:
    return PaperContribution(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_id=finding_text(document_id) or "",
        analysis_status=finding_choice(
            analysis_status, PAPER_CONTRIBUTION_STATUSES, "pending"
        ),
        relevance=finding_choice(
            "high" if analysis_status == "analyzed" else "irrelevant",
            PAPER_RELEVANCE_VALUES,
            "uncertain",
        ),
        paper_role=finding_choice(
            "primary_experiment" if analysis_status == "analyzed" else "irrelevant",
            PAPER_ROLE_VALUES,
            "uncertain",
        ),
        contribution_summary="Direct preheating experiment.",
        material_match=(),
        changed_variables=(),
        measured_property_scope=(),
        test_environment_scope=(),
        exclusion_reason=finding_text(
            None if analysis_status == "analyzed" else "No relevant experiment."
        ),
        warnings=(),
        confidence=0.9,
    )


def _finding(**overrides) -> Finding:
    values = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "finding_id": "finding-1",
        "statement": "Preheating was associated with higher ductility in paper 1.",
        "factors": ("preheating",),
        "outcome": "ductility",
        "direction": "increase",
        "assertion_strength": "associative",
        "attribution_scope": _choice(
            "isolated_effect",
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        "synthesis_status": "insufficient_confirmation",
        "certainty": 0.5,
        "display_rank": 0,
        "mechanisms": (),
        "scientific_context": ScientificContext(
            material=(ScientificAttribute(name="alloy", value="316L"),),
            test=(ScientificAttribute(name="temperature", value=25, unit="C"),),
        ),
        "limitations": ("Cross-paper confirmation is absent.",),
        "paper_contributions": (
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
            ),
        ),
    }
    values.update(overrides)
    return Finding(**values)


def test_finding_round_trips_one_atomic_outcome_without_legacy_fields() -> None:
    finding = _finding()
    record = finding.to_record()

    assert finding.key == ("collection-1", "objective-1", 1, "finding-1")
    assert record["factors"] == ["preheating"]
    assert record["outcome"] == "ductility"
    assert finding.support_scope == "paper"
    assert finding.direct_document_count == 1
    for removed in (
        "finding_level",
        "variables",
        "mediators",
        "outcomes",
        "scope_summary",
        "evidence_strength",
        "generalization_status",
        "paper_count",
        "confidence",
        "relations",
        "context",
        "derivation",
    ):
        assert removed not in record


def test_experiment_backed_finding_keeps_selection_and_optional_group_refs() -> None:
    finding = Finding(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=2,
        finding_id="finding-experiment-1",
        statement="The reported outcome changes under the selected condition.",
        factors=("preheating",),
        outcome="elongation",
        direction="mixed",
        assertion_strength="descriptive",
        attribution_scope=finding_choice(
            "descriptive_only",
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        synthesis_status="single_study",
        certainty=0.4,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=("The selected record has no cross-paper confirmation.",),
        paper_contributions=(),
        selection_ids=("selection-1",),
    )

    record = finding.to_record()
    restored = Finding(
        collection_id=finding_text(record.get("collection_id")) or "",
        objective_id=finding_text(record.get("objective_id")) or "",
        analysis_version=finding_positive_int(record.get("analysis_version")),
        finding_id=finding_text(record.get("finding_id"))
        or finding_stable_id(
            "finding",
            record.get("objective_id"),
            record.get("analysis_version"),
            finding_strings(record.get("factors")),
            finding_text(record.get("outcome")) or "",
            record.get("supporting_evidence_ids"),
        ),
        statement=finding_text(record.get("statement")) or "",
        factors=finding_strings(record.get("factors")),
        outcome=finding_text(record.get("outcome")) or "",
        direction=finding_choice(
            record.get("direction"), SCIENTIFIC_RESULT_DIRECTIONS, "unknown"
        ),
        assertion_strength=finding_choice(
            record.get("assertion_strength"), FINDING_ASSERTION_STRENGTHS, "descriptive"
        ),
        attribution_scope=finding_choice(
            record.get("attribution_scope"),
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        synthesis_status=finding_choice(
            record.get("synthesis_status"),
            FINDING_SYNTHESIS_STATUSES,
            "insufficient_confirmation",
        ),
        certainty=finding_certainty(record.get("certainty")),
        display_rank=finding_non_negative_int(record.get("display_rank")),
        mechanisms=tuple(
            (
                FindingMechanismRelation(
                    source_term=finding_text(item.get("source_term")) or "",
                    relation_type=finding_text(item.get("relation_type")) or "",
                    target_term=finding_text(item.get("target_term")) or "",
                    direction=finding_text(item.get("direction")),
                    assertion_strength=finding_choice(
                        item.get("assertion_strength"),
                        FINDING_ASSERTION_STRENGTHS,
                        "descriptive",
                    ),
                    supporting_evidence_ids=finding_strings(
                        item.get("supporting_evidence_ids")
                    ),
                )
                for item in tuple(
                    (
                        dict(item)
                        for item in (
                            record.get("mechanisms")
                            if isinstance(record.get("mechanisms"), (list, tuple))
                            else ()
                        )
                        if isinstance(item, Mapping)
                    )
                )
            )
        ),
        scientific_context=ScientificContext(
            material=tuple(
                (
                    ScientificAttribute(
                        name=scientific_text(attribute.get("name")) or "",
                        value=(
                            scientific_scalar(attribute.get("value"))
                            if scientific_scalar(attribute.get("value")) is not None
                            else ""
                        ),
                        unit=scientific_text(attribute.get("unit")),
                        context_scope=scientific_choice(
                            attribute.get("context_scope"),
                            SCIENTIFIC_CONTEXT_SCOPES,
                            "unknown",
                        ),
                        applies_to_outcomes=scientific_terms(
                            attribute.get("applies_to_outcomes")
                        ),
                    )
                    for attribute in (
                        (
                            dict(record.get("scientific_context"))
                            if isinstance(record.get("scientific_context"), Mapping)
                            else {}
                        ).get("material")
                        if isinstance(
                            (
                                dict(record.get("scientific_context"))
                                if isinstance(record.get("scientific_context"), Mapping)
                                else {}
                            ).get("material"),
                            (list, tuple),
                        )
                        else ()
                    )
                    if isinstance(attribute, Mapping)
                )
            ),
            sample=tuple(
                (
                    ScientificAttribute(
                        name=scientific_text(attribute.get("name")) or "",
                        value=(
                            scientific_scalar(attribute.get("value"))
                            if scientific_scalar(attribute.get("value")) is not None
                            else ""
                        ),
                        unit=scientific_text(attribute.get("unit")),
                        context_scope=scientific_choice(
                            attribute.get("context_scope"),
                            SCIENTIFIC_CONTEXT_SCOPES,
                            "unknown",
                        ),
                        applies_to_outcomes=scientific_terms(
                            attribute.get("applies_to_outcomes")
                        ),
                    )
                    for attribute in (
                        (
                            dict(record.get("scientific_context"))
                            if isinstance(record.get("scientific_context"), Mapping)
                            else {}
                        ).get("sample")
                        if isinstance(
                            (
                                dict(record.get("scientific_context"))
                                if isinstance(record.get("scientific_context"), Mapping)
                                else {}
                            ).get("sample"),
                            (list, tuple),
                        )
                        else ()
                    )
                    if isinstance(attribute, Mapping)
                )
            ),
            process=tuple(
                (
                    ScientificAttribute(
                        name=scientific_text(attribute.get("name")) or "",
                        value=(
                            scientific_scalar(attribute.get("value"))
                            if scientific_scalar(attribute.get("value")) is not None
                            else ""
                        ),
                        unit=scientific_text(attribute.get("unit")),
                        context_scope=scientific_choice(
                            attribute.get("context_scope"),
                            SCIENTIFIC_CONTEXT_SCOPES,
                            "unknown",
                        ),
                        applies_to_outcomes=scientific_terms(
                            attribute.get("applies_to_outcomes")
                        ),
                    )
                    for attribute in (
                        (
                            dict(record.get("scientific_context"))
                            if isinstance(record.get("scientific_context"), Mapping)
                            else {}
                        ).get("process")
                        if isinstance(
                            (
                                dict(record.get("scientific_context"))
                                if isinstance(record.get("scientific_context"), Mapping)
                                else {}
                            ).get("process"),
                            (list, tuple),
                        )
                        else ()
                    )
                    if isinstance(attribute, Mapping)
                )
            ),
            test=tuple(
                (
                    ScientificAttribute(
                        name=scientific_text(attribute.get("name")) or "",
                        value=(
                            scientific_scalar(attribute.get("value"))
                            if scientific_scalar(attribute.get("value")) is not None
                            else ""
                        ),
                        unit=scientific_text(attribute.get("unit")),
                        context_scope=scientific_choice(
                            attribute.get("context_scope"),
                            SCIENTIFIC_CONTEXT_SCOPES,
                            "unknown",
                        ),
                        applies_to_outcomes=scientific_terms(
                            attribute.get("applies_to_outcomes")
                        ),
                    )
                    for attribute in (
                        (
                            dict(record.get("scientific_context"))
                            if isinstance(record.get("scientific_context"), Mapping)
                            else {}
                        ).get("test")
                        if isinstance(
                            (
                                dict(record.get("scientific_context"))
                                if isinstance(record.get("scientific_context"), Mapping)
                                else {}
                            ).get("test"),
                            (list, tuple),
                        )
                        else ()
                    )
                    if isinstance(attribute, Mapping)
                )
            ),
        ),
        limitations=finding_strings(record.get("limitations")),
        paper_contributions=tuple(
            (
                FindingPaperContribution(
                    document_id=finding_text(item.get("document_id")) or "",
                    analysis_status=finding_choice(
                        item.get("analysis_status"),
                        PAPER_CONTRIBUTION_STATUSES,
                        "pending",
                    ),
                    supporting_evidence_ids=finding_strings(
                        item.get("supporting_evidence_ids")
                    ),
                    contradicting_evidence_ids=finding_strings(
                        item.get("contradicting_evidence_ids")
                    ),
                    context_evidence_ids=finding_strings(
                        item.get("context_evidence_ids")
                    ),
                    condition_boundary_evidence_ids=finding_strings(
                        item.get("condition_boundary_evidence_ids")
                    ),
                )
                for item in tuple(
                    (
                        dict(item)
                        for item in (
                            record.get("paper_contributions")
                            if isinstance(
                                record.get("paper_contributions"), (list, tuple)
                            )
                            else ()
                        )
                        if isinstance(item, Mapping)
                    )
                )
            )
        ),
        origin=finding_choice(
            record.get("origin"), FINDING_ORIGINS, "system_generated"
        ),
        source_analysis_version=finding_positive_int(
            record.get("source_analysis_version")
        )
        or None,
        parent_finding_id=finding_text(record.get("parent_finding_id")),
        created_by_user_id=finding_text(record.get("created_by_user_id")),
        created_by_tool_call_id=finding_text(record.get("created_by_tool_call_id")),
        created_at=finding_datetime_or_none(record.get("created_at")),
        warnings=finding_strings(record.get("warnings")),
        selection_ids=finding_strings(record.get("selection_ids")),
        comparison_group_ids=finding_strings(record.get("comparison_group_ids")),
    )

    assert restored.selection_ids == ("selection-1",)
    assert restored.comparison_group_ids == ()
    assert restored.support_scope == "paper"


def test_finding_validates_direct_evidence_and_complete_paper_coverage() -> None:
    finding = _finding(
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
            ),
            FindingPaperContribution(document_id="paper-2", analysis_status="excluded"),
        )
    )

    finding.validate_sources(
        (_evidence("evidence-1", "paper-1"),),
        (_contribution("paper-1"), _contribution("paper-2", analysis_status="excluded")),
    )

    with pytest.raises(ValueError, match="paper coverage"):
        finding.validate_sources(
            (_evidence("evidence-1", "paper-1"),),
            (_contribution("paper-1"),),
        )


def test_finding_accepts_experiment_series_factor_subsets_with_exact_union() -> None:
    """Row-pair Evidence may cover subsets of one source-grounded series scope."""

    support = _evidence(
        "evidence-1",
        "paper-1",
        factors=("energy input", "travel speed"),
        attribution_scope="joint_effect",
    )
    contradiction = _evidence(
        "evidence-2",
        "paper-1",
        factors=("travel speed", "path strategy"),
        attribution_scope="joint_effect",
        direction="decrease",
    )
    finding = _finding(
        factors=("energy input", "path strategy", "travel speed"),
        attribution_scope="joint_effect",
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
                contradicting_evidence_ids=("evidence-2",),
            ),
        ),
    )

    finding.validate_sources(
        (support, contradiction),
        (_contribution("paper-1"),),
    )


def test_finding_accepts_semantically_equivalent_series_factor_labels() -> None:
    """Source header units and ordinary word forms do not create a new axis."""

    support = _evidence(
        "evidence-1",
        "paper-1",
        factors=("Hatch space (mm)", "scanning speed"),
        attribution_scope="joint_effect",
    )
    finding = _finding(
        factors=("hatch spacing", "scanning speed"),
        attribution_scope="joint_effect",
    )

    finding.validate_sources((support,), (_contribution("paper-1"),))


def test_finding_rejects_factor_not_covered_by_direct_evidence_union() -> None:
    support = _evidence(
        "evidence-1",
        "paper-1",
        factors=("energy input", "travel speed"),
        attribution_scope="joint_effect",
    )
    finding = _finding(
        factors=("atmosphere", "energy input", "travel speed"),
        attribution_scope="joint_effect",
    )

    with pytest.raises(ValueError, match="factors differ"):
        finding.validate_sources((support,), (_contribution("paper-1"),))


def test_finding_rejects_missing_and_cross_version_evidence() -> None:
    finding = _finding()
    contributions = (_contribution("paper-1"),)

    with pytest.raises(ValueError, match="missing evidence"):
        finding.validate_sources((), contributions)
    with pytest.raises(ValueError, match="cross-version"):
        finding.validate_sources(
            (_evidence("evidence-1", "paper-1", analysis_version=2),),
            contributions,
        )


def test_context_evidence_cannot_replace_direct_result() -> None:
    finding = _finding()

    with pytest.raises(ValueError, match="must have a result role"):
        finding.validate_sources(
            (_evidence("evidence-1", "paper-1", role="condition_context"),),
            (_contribution("paper-1"),),
        )


def test_cross_paper_agreement_is_derived_from_independent_direct_results() -> None:
    finding = _finding(
        synthesis_status="agreement",
        certainty=0.75,
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
            ),
            FindingPaperContribution(
                document_id="paper-2",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-2",),
            ),
        ),
    )
    evidence = (
        _evidence("evidence-1", "paper-1"),
        _evidence("evidence-2", "paper-2"),
    )

    finding.validate_sources(
        evidence,
        (_contribution("paper-1"), _contribution("paper-2")),
    )
    assert finding.support_scope == "cross_paper"
    assert finding.supporting_document_ids == ("paper-1", "paper-2")


def test_finding_rejects_declared_status_that_differs_from_paper_evidence() -> None:
    with pytest.raises(ValueError, match="synthesis status differs"):
        _finding(synthesis_status="agreement")


def test_joint_factor_finding_cannot_claim_isolated_or_causal_effect() -> None:
    paper = (
        FindingPaperContribution(
            document_id="paper-1",
            analysis_status="analyzed",
            supporting_evidence_ids=("evidence-1",),
        ),
    )
    with pytest.raises(ValueError, match="one factor"):
        _finding(
            factors=("laser power", "scan speed"),
            attribution_scope="isolated_effect",
            paper_contributions=paper,
        )
    with pytest.raises(ValueError, match="causal Finding requires"):
        _finding(
            factors=("laser power", "scan speed"),
            attribution_scope="joint_effect",
            assertion_strength="causal",
            paper_contributions=paper,
        )


def test_finding_mechanism_remains_subordinate_and_requires_mechanism_evidence() -> None:
    finding = _finding(
        mechanisms=(
            FindingMechanismRelation(
                source_term="preheating",
                relation_type="changes",
                target_term="dislocation structure",
                direction=None,
                assertion_strength="associative",
                supporting_evidence_ids=("mechanism-1",),
            ),
        ),
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
                context_evidence_ids=("mechanism-1",),
            ),
        ),
    )

    finding.validate_sources(
        (
            _evidence("evidence-1", "paper-1"),
            _evidence("mechanism-1", "paper-1", role="mechanism_context"),
        ),
        (_contribution("paper-1"),),
    )
    assert finding.factors == ("preheating",)
    assert finding.outcome == "ductility"

    with pytest.raises(ValueError, match="lacks mechanism evidence"):
        finding.validate_sources(
            (
                _evidence("evidence-1", "paper-1"),
                _evidence("mechanism-1", "paper-1", role="condition_context"),
            ),
            (_contribution("paper-1"),),
        )


def test_finding_requires_mechanism_evidence_in_paper_context_binding() -> None:
    with pytest.raises(ValueError, match="must bind as paper context"):
        _finding(
            mechanisms=(
                FindingMechanismRelation(
                    source_term="preheating",
                    relation_type="changes",
                    target_term="dislocation structure",
                    direction=None,
                    assertion_strength="associative",
                    supporting_evidence_ids=("mechanism-1",),
                ),
            )
        )


def test_finding_rejects_support_or_contradiction_with_wrong_direction() -> None:
    contributions = (_contribution("paper-1"), _contribution("paper-2"))
    support = _evidence("evidence-1", "paper-1")
    same_direction = _evidence(
        "evidence-2",
        "paper-2",
        role="contradictory_result",
    )
    finding = _finding(
        synthesis_status="conflict",
        certainty=0.6,
        paper_contributions=(
            FindingPaperContribution(
                document_id="paper-1",
                analysis_status="analyzed",
                supporting_evidence_ids=("evidence-1",),
            ),
            FindingPaperContribution(
                document_id="paper-2",
                analysis_status="analyzed",
                contradicting_evidence_ids=("evidence-2",),
            ),
        ),
    )

    with pytest.raises(ValueError, match="does not oppose"):
        finding.validate_sources((support, same_direction), contributions)

    opposite = _evidence(
        "evidence-2",
        "paper-2",
        role="direct_result",
        direction="decrease",
    )
    finding.validate_sources((support, opposite), contributions)


def test_common_scientific_context_keeps_only_exact_shared_attributes() -> None:
    common = Finding.common_scientific_context_for(
        (
            _evidence("evidence-1", "paper-1", material="316L"),
            _evidence("evidence-2", "paper-2", material="316L"),
        )
    )
    different = Finding.common_scientific_context_for(
        (
            _evidence("evidence-1", "paper-1", material="316L"),
            _evidence("evidence-2", "paper-2", material="304L"),
        )
    )

    assert common.material[0].value == "316L"
    assert different.material == ()
    assert len(different.test) == 1


def test_certainty_is_capped_by_independent_document_support() -> None:
    one_paper = (_evidence("evidence-1", "paper-1", confidence=0.93),)
    two_papers = (
        *one_paper,
        _evidence("evidence-2", "paper-2", confidence=0.91),
    )
    three_papers = (
        *two_papers,
        _evidence("evidence-3", "paper-3", confidence=0.9),
    )

    assert Finding.certainty_for("insufficient_confirmation", one_paper) == 0.5
    assert Finding.certainty_for("agreement", one_paper) == 0.5
    assert Finding.certainty_for("agreement", two_papers) == 0.75
    assert Finding.certainty_for("agreement", three_papers) == 0.85
    assert Finding.certainty_for("conflict", three_papers) == 0.6
    assert Finding.certainty_for("condition_dependent", three_papers) == 0.7


def test_finding_subordinates_have_no_independent_business_ids() -> None:
    mechanism = FindingMechanismRelation(
        source_term="preheating",
        relation_type="changes",
        target_term="dislocation structure",
        direction=None,
        assertion_strength="associative",
        supporting_evidence_ids=("mechanism-1",),
    )
    paper = FindingPaperContribution(
        document_id="paper-1",
        analysis_status="analyzed",
        supporting_evidence_ids=("evidence-1",),
    )
    assert not hasattr(mechanism, "relation_id")
    assert not hasattr(paper, "contribution_id")
