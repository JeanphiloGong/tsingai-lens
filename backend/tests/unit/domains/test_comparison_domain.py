from __future__ import annotations

from domain.core.comparison import ComparisonRow, evaluate_comparison_assessment
from domain.shared.enums import (
    COMPARABILITY_STATUS_COMPARABLE,
    COMPARABILITY_STATUS_INSUFFICIENT,
    COMPARABILITY_STATUS_LIMITED,
    COMPARABILITY_STATUS_NOT_COMPARABLE,
    EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE,
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    EPISTEMIC_UNRESOLVED,
    TRACEABILITY_STATUS_DIRECT,
    TRACEABILITY_STATUS_MISSING,
    TRACEABILITY_STATUS_PARTIAL,
)


def test_evaluate_comparison_assessment_returns_comparable_for_complete_scalar_result() -> None:
    assessment = evaluate_comparison_assessment(
        variant_id="var-1",
        baseline_reference="untreated baseline",
        test_condition_id="tc-1",
        traceability_status=TRACEABILITY_STATUS_DIRECT,
        result_type="scalar",
        result_summary="97 MPa",
        numeric_value=97.0,
        structure_feature_ids=["feat-1"],
        characterization_observation_ids=["obs-1"],
    )

    assert assessment.comparability_status == COMPARABILITY_STATUS_COMPARABLE
    assert assessment.requires_expert_review is False
    assert assessment.assessment_epistemic_status == EPISTEMIC_NORMALIZED_FROM_EVIDENCE
    assert "variant_linked" in assessment.comparability_basis


def test_evaluate_comparison_assessment_handles_limited_and_missing_cases() -> None:
    limited = evaluate_comparison_assessment(
        variant_id="var-1",
        baseline_reference="baseline",
        test_condition_id="tc-1",
        traceability_status=TRACEABILITY_STATUS_PARTIAL,
        result_type="scalar",
        result_summary="97 MPa",
        numeric_value=97.0,
        structure_feature_ids=[],
        characterization_observation_ids=[],
    )
    missing = evaluate_comparison_assessment(
        variant_id=None,
        baseline_reference=None,
        test_condition_id=None,
        traceability_status=TRACEABILITY_STATUS_MISSING,
        result_type="trend",
        result_summary="Trend reported",
        numeric_value=None,
        structure_feature_ids=[],
        characterization_observation_ids=[],
    )

    assert limited.comparability_status == COMPARABILITY_STATUS_LIMITED
    assert limited.assessment_epistemic_status == EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE
    assert "direct_traceability" in limited.missing_critical_context
    assert missing.comparability_status == COMPARABILITY_STATUS_INSUFFICIENT
    assert missing.requires_expert_review is True
    assert missing.assessment_epistemic_status == EPISTEMIC_UNRESOLVED


def test_evaluate_comparison_assessment_detects_not_comparable_without_baseline_and_condition() -> None:
    assessment = evaluate_comparison_assessment(
        variant_id="var-1",
        baseline_reference=None,
        test_condition_id=None,
        traceability_status=TRACEABILITY_STATUS_PARTIAL,
        result_type="scalar",
        result_summary="97 MPa",
        numeric_value=97.0,
        structure_feature_ids=[],
        characterization_observation_ids=[],
    )

    assert assessment.comparability_status == COMPARABILITY_STATUS_NOT_COMPARABLE
    assert "baseline_reference" in assessment.missing_critical_context
    assert "test_condition" in assessment.missing_critical_context


def test_comparison_row_normalizes_lists_and_defaults() -> None:
    row = ComparisonRow.from_mapping(
        {
            "row_id": "cmp-1",
            "collection_id": "col-1",
            "source_document_id": "doc-1",
            "result_type": "scalar",
            "result_summary": "97 MPa",
            "supporting_evidence_ids": ["ev-1"],
            "supporting_anchor_ids": ["anchor-1"],
            "characterization_observation_ids": ["obs-1"],
            "structure_feature_ids": ["feat-1"],
            "material_system_normalized": "epoxy",
            "process_normalized": "80 C, 2 h",
            "property_normalized": "strength",
            "baseline_normalized": "untreated baseline",
            "test_condition_normalized": "tensile",
            "comparability_status": COMPARABILITY_STATUS_COMPARABLE,
            "comparability_warnings": [],
            "comparability_basis": ["variant_linked"],
            "requires_expert_review": 0,
            "assessment_epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
            "missing_critical_context": [],
            "value": 97,
            "unit": "MPa",
        }
    )

    assert row.supporting_evidence_ids == ("ev-1",)
    assert row.requires_expert_review is False
    assert row.to_record()["value"] == 97.0
