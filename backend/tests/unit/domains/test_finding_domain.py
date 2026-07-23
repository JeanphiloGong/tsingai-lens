from __future__ import annotations

import pytest

from domain.core import (
    Finding,
    FindingContext,
    FindingDerivation,
    FindingRelation,
    ObjectiveEvidence,
)


def _evidence(
    evidence_id: str,
    document_id: str,
    *,
    analysis_version: int = 1,
    role: str = "direct_result",
    isolated: bool = True,
) -> ObjectiveEvidence:
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
            "evidence_kind": "measurement",
            "property_normalized": "ductility",
            "value_payload": {"direction": "increase"},
            "join_keys": {"isolated_variable": "preheating"} if isolated else {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


def _paper_finding(**overrides) -> Finding:
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "finding_id": "finding-1",
        "finding_level": "paper",
        "statement": "Preheating was associated with higher ductility in paper 1.",
        "variables": ["preheating"],
        "mediators": ["microstructure"],
        "outcomes": ["ductility"],
        "direction": "increase",
        "scope_summary": "LPBF 316L under the reported tensile test.",
        "evidence_strength": "moderate",
        "generalization_status": "paper_level_only",
        "paper_count": 1,
        "confidence": 0.8,
        "display_rank": 0,
        "relations": [
            {
                "source_term": "preheating",
                "relation_type": "associated_with",
                "target_term": "ductility",
                "direction": "increase",
                "assertion_strength": "associative",
                "supporting_evidence_ids": ["evidence-1"],
            }
        ],
        "context": {
            "material_system": {"alloy": "316L"},
            "limitations": ["single paper"],
            "supporting_evidence_ids": ["evidence-1"],
        },
        "derivation": {
            "synthesis_mode": "paper",
            "comparison_status": "insufficient_confirmation",
            "contributing_document_ids": ["paper-1"],
            "supporting_evidence_ids": ["evidence-1"],
            "rationale": "One direct result supports a paper-level finding.",
        },
    }
    payload.update(overrides)
    return Finding.from_mapping(payload)


def test_finding_round_trips_without_claim_or_logic_chain_identity() -> None:
    finding = _paper_finding()
    record = finding.to_record()

    assert finding.key == ("collection-1", "objective-1", 1, "finding-1")
    assert record["statement"].startswith("Preheating")
    assert "claim_id" not in record
    assert "logic_chain_id" not in record
    assert "context_id" not in record["context"]
    assert "relation_id" not in record["relations"][0]


def test_paper_finding_validates_direct_result_evidence() -> None:
    finding = _paper_finding()

    finding.validate_evidence((_evidence("evidence-1", "paper-1"),))


def test_finding_rejects_missing_and_cross_version_evidence() -> None:
    finding = _paper_finding()

    with pytest.raises(ValueError, match="missing evidence"):
        finding.validate_evidence(())
    with pytest.raises(ValueError, match="cross-version"):
        finding.validate_evidence(
            (_evidence("evidence-1", "paper-1", analysis_version=2),)
        )


def test_condition_context_cannot_replace_direct_result() -> None:
    finding = _paper_finding()
    context = _evidence(
        "evidence-1",
        "paper-1",
        role="condition_context",
    )

    with pytest.raises(ValueError, match="direct result"):
        finding.validate_evidence((context,))


def test_cross_paper_finding_requires_two_direct_documents() -> None:
    finding = _paper_finding(
        finding_level="cross_paper",
        generalization_status="cross_paper_agreement",
        paper_count=2,
        derivation={
            "synthesis_mode": "cross_paper",
            "comparison_status": "agreement",
            "contributing_document_ids": ["paper-1", "paper-2"],
            "supporting_evidence_ids": ["evidence-1", "evidence-2"],
            "rationale": "Two papers report comparable direct results.",
        },
        relations=[
            {
                "source_term": "preheating",
                "relation_type": "associated_with",
                "target_term": "ductility",
                "assertion_strength": "associative",
                "supporting_evidence_ids": ["evidence-1", "evidence-2"],
            }
        ],
        context={"supporting_evidence_ids": ["evidence-1", "evidence-2"]},
    )

    finding.validate_evidence(
        (
            _evidence("evidence-1", "paper-1"),
            _evidence("evidence-2", "paper-2"),
        )
    )

    with pytest.raises(ValueError, match="missing evidence"):
        finding.validate_evidence((_evidence("evidence-1", "paper-1"),))


def test_cross_paper_finding_constructor_rejects_single_paper() -> None:
    with pytest.raises(ValueError, match="at least two papers"):
        _paper_finding(
            finding_level="cross_paper",
            generalization_status="cross_paper_agreement",
            derivation={
                "synthesis_mode": "cross_paper",
                "comparison_status": "agreement",
                "contributing_document_ids": ["paper-1"],
                "supporting_evidence_ids": ["evidence-1"],
                "rationale": "Insufficient direct confirmation.",
            },
        )


def test_causal_relation_requires_isolated_variable_evidence() -> None:
    finding = _paper_finding(
        relations=[
            {
                "source_term": "preheating",
                "relation_type": "increases",
                "target_term": "ductility",
                "assertion_strength": "causal",
                "supporting_evidence_ids": ["evidence-1"],
            }
        ]
    )

    with pytest.raises(ValueError, match="lacks isolated-variable"):
        finding.validate_evidence(
            (_evidence("evidence-1", "paper-1", isolated=False),)
        )

    finding.validate_evidence((_evidence("evidence-1", "paper-1"),))


def test_finding_subordinates_have_no_independent_business_ids() -> None:
    relation = FindingRelation.from_mapping(
        {
            "source_term": "porosity",
            "relation_type": "associated_with",
            "target_term": "pitting potential",
            "assertion_strength": "associative",
            "supporting_evidence_ids": ["evidence-1"],
        }
    )
    context = FindingContext.from_mapping(
        {
            "material_system": {"alloy": "316L"},
            "supporting_evidence_ids": ["evidence-1"],
        }
    )
    derivation = FindingDerivation.from_mapping(
        {
            "synthesis_mode": "paper",
            "comparison_status": "insufficient_confirmation",
            "contributing_document_ids": ["paper-1"],
            "supporting_evidence_ids": ["evidence-1"],
            "rationale": "One paper reports the result.",
        }
    )

    assert "relation_id" not in relation.to_record()
    assert "context_id" not in context.to_record()
    assert "derivation_id" not in derivation.to_record()
