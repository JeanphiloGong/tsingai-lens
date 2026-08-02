from __future__ import annotations

import pytest

from domain.core import (
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
    ObjectiveEvidence,
    PaperContribution,
)


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
    variables = [
        {
            "name": factor,
            "baseline_value": f"baseline {factor}",
            "target_value": f"target {factor}",
        }
        for factor in factors
    ]
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": analysis_version,
            "evidence_id": evidence_id,
            "document_id": document_id,
            "source_kind": "text_window",
            "source_ref": f"{document_id}-block-1",
            "source_excerpt": "Preheating was associated with higher ductility.",
            "evidence_role": role,
            "selection_status": "extracted",
            "changed_variables": variables if result_role else [],
            "comparison": (
                {
                    "baseline_label": "baseline",
                    "target_label": "target",
                    "axis_names": list(factors),
                    "comparable": True,
                }
                if result_role
                else None
            ),
            "reported_result": (
                {
                    "outcome": "ductility",
                    "value": None,
                    "unit": None,
                    "direction": direction,
                    "result_text": "Preheating was associated with higher ductility.",
                }
                if result_role
                else None
            ),
            "attribution_scope": attribution_scope if result_role else "not_attributable",
            "scientific_context": {
                "material": [{"name": "alloy", "value": material}],
                "test": [{"name": "temperature", "value": 25, "unit": "C"}],
            },
            "resolution_status": "resolved",
            "confidence": confidence,
        }
    )


def _contribution(
    document_id: str,
    *,
    analysis_status: str = "analyzed",
) -> PaperContribution:
    return PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "document_id": document_id,
            "analysis_status": analysis_status,
            "relevance": "high" if analysis_status == "analyzed" else "irrelevant",
            "paper_role": (
                "primary_experiment" if analysis_status == "analyzed" else "irrelevant"
            ),
            "contribution_summary": "Direct preheating experiment.",
            "exclusion_reason": (
                None if analysis_status == "analyzed" else "No relevant experiment."
            ),
            "confidence": 0.9,
        }
    )


def _finding(**overrides) -> Finding:
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "finding_id": "finding-1",
        "statement": "Preheating was associated with higher ductility in paper 1.",
        "factors": ["preheating"],
        "outcome": "ductility",
        "direction": "increase",
        "assertion_strength": "associative",
        "attribution_scope": "isolated_effect",
        "synthesis_status": "insufficient_confirmation",
        "certainty": 0.5,
        "display_rank": 0,
        "mechanisms": [],
        "scientific_context": {
            "material": [{"name": "alloy", "value": "316L"}],
            "test": [{"name": "temperature", "value": 25, "unit": "C"}],
        },
        "limitations": ["Cross-paper confirmation is absent."],
        "paper_contributions": [
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-1"],
            }
        ],
    }
    payload.update(overrides)
    return Finding.from_mapping(payload)


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


def test_finding_validates_direct_evidence_and_complete_paper_coverage() -> None:
    finding = _finding(
        paper_contributions=[
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-1"],
            },
            {"document_id": "paper-2", "analysis_status": "excluded"},
        ]
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
        certainty=0.9,
        paper_contributions=[
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-1"],
            },
            {
                "document_id": "paper-2",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-2"],
            },
        ],
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
    paper = [
        {
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "supporting_evidence_ids": ["evidence-1"],
        }
    ]
    with pytest.raises(ValueError, match="one factor"):
        _finding(
            factors=["laser power", "scan speed"],
            attribution_scope="isolated_effect",
            paper_contributions=paper,
        )
    with pytest.raises(ValueError, match="causal Finding requires"):
        _finding(
            factors=["laser power", "scan speed"],
            attribution_scope="joint_effect",
            assertion_strength="causal",
            paper_contributions=paper,
        )


def test_finding_mechanism_remains_subordinate_and_requires_mechanism_evidence() -> None:
    finding = _finding(
        mechanisms=[
            {
                "source_term": "preheating",
                "relation_type": "changes",
                "target_term": "dislocation structure",
                "assertion_strength": "associative",
                "supporting_evidence_ids": ["mechanism-1"],
            }
        ],
        paper_contributions=[
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-1"],
                "context_evidence_ids": ["mechanism-1"],
            }
        ],
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
            mechanisms=[
                {
                    "source_term": "preheating",
                    "relation_type": "changes",
                    "target_term": "dislocation structure",
                    "assertion_strength": "associative",
                    "supporting_evidence_ids": ["mechanism-1"],
                }
            ]
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
        certainty=0.9,
        paper_contributions=[
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-1"],
            },
            {
                "document_id": "paper-2",
                "analysis_status": "analyzed",
                "contradicting_evidence_ids": ["evidence-2"],
            },
        ],
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


def test_certainty_is_evidence_derived_and_single_paper_capped() -> None:
    evidence = (_evidence("evidence-1", "paper-1", confidence=0.93),)

    assert Finding.certainty_for("insufficient_confirmation", evidence) == 0.5
    assert Finding.certainty_for("agreement", evidence) == 0.93


def test_finding_subordinates_have_no_independent_business_ids() -> None:
    mechanism = FindingMechanismRelation.from_mapping(
        {
            "source_term": "porosity",
            "relation_type": "affects",
            "target_term": "passive film stability",
            "assertion_strength": "associative",
            "supporting_evidence_ids": ["mechanism-1"],
        }
    )
    paper = FindingPaperContribution.from_mapping(
        {
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "supporting_evidence_ids": ["evidence-1"],
        }
    )

    assert "relation_id" not in mechanism.to_record()
    assert "contribution_id" not in paper.to_record()
