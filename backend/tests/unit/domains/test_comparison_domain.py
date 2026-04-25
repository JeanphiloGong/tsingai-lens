from __future__ import annotations

from domain.core.comparison import (
    COMPARABLE_RESULT_NORMALIZATION_VERSION,
    COLLECTION_COMPARISON_POLICY_FAMILY,
    COLLECTION_COMPARISON_POLICY_VERSION,
    COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
    CollectionComparableResult,
    ComparableResult,
    ComparisonAssessment,
    ComparisonAxis,
    ComparisonRowRecord,
    ContextBinding,
    EvidenceTrace,
    NormalizedComparisonContext,
    ResultValue,
    build_collection_assessment_input_fingerprint,
    build_comparable_result_id,
    evaluate_collection_reassessment_reasons,
    evaluate_comparison_assessment,
)
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


def _build_comparable_result(
    *,
    comparable_result_id: str = "cres-1",
    variant_id: str | None = "var-1",
    baseline_id: str | None = "base-1",
    baseline_reference: str | None = "untreated baseline",
    test_condition_id: str | None = "tc-1",
    traceability_status: str = TRACEABILITY_STATUS_DIRECT,
    property_normalized: str = "strength",
    result_type: str = "scalar",
    result_summary: str = "97 MPa",
    numeric_value: float | None = 97.0,
    structure_feature_ids: tuple[str, ...] = ("feat-1",),
    characterization_observation_ids: tuple[str, ...] = ("obs-1",),
) -> ComparableResult:
    return ComparableResult(
        comparable_result_id=comparable_result_id,
        source_result_id="res-1",
        source_document_id="doc-1",
        binding=ContextBinding(
            variant_id=variant_id,
            baseline_id=baseline_id,
            test_condition_id=test_condition_id,
        ),
        normalized_context=NormalizedComparisonContext(
            material_system_normalized="epoxy",
            process_normalized="80 C, 2 h",
            baseline_normalized=baseline_reference or "unspecified baseline",
            test_condition_normalized="tensile",
        ),
        axis=ComparisonAxis(
            axis_name="loading",
            axis_value="parallel",
            axis_unit=None,
        ),
        value=ResultValue(
            property_normalized=property_normalized,
            result_type=result_type,
            numeric_value=numeric_value,
            unit="MPa",
            summary=result_summary,
        ),
        evidence=EvidenceTrace(
            direct_anchor_ids=("anchor-1",),
            contextual_anchor_ids=("anchor-2",),
            evidence_ids=("ev-1",),
            structure_feature_ids=structure_feature_ids,
            characterization_observation_ids=characterization_observation_ids,
            traceability_status=traceability_status,
        ),
        variant_label="epoxy composite",
        baseline_reference=baseline_reference,
        result_source_type="text",
        epistemic_status="normalized_from_evidence",
        normalization_version=COMPARABLE_RESULT_NORMALIZATION_VERSION,
    )


def test_evaluate_comparison_assessment_returns_comparable_for_complete_scalar_result() -> None:
    assessment = evaluate_comparison_assessment(_build_comparable_result())

    assert assessment.comparability_status == COMPARABILITY_STATUS_COMPARABLE
    assert assessment.requires_expert_review is False
    assert assessment.assessment_epistemic_status == EPISTEMIC_NORMALIZED_FROM_EVIDENCE
    assert "variant_linked" in assessment.comparability_basis


def test_evaluate_comparison_assessment_handles_limited_and_missing_cases() -> None:
    limited = evaluate_comparison_assessment(
        _build_comparable_result(traceability_status=TRACEABILITY_STATUS_PARTIAL)
    )
    missing = evaluate_comparison_assessment(
        _build_comparable_result(
            variant_id=None,
            baseline_id=None,
            baseline_reference=None,
            test_condition_id=None,
            traceability_status=TRACEABILITY_STATUS_MISSING,
            result_type="trend",
            result_summary="Trend reported",
            numeric_value=None,
            structure_feature_ids=(),
            characterization_observation_ids=(),
        )
    )

    assert limited.comparability_status == COMPARABILITY_STATUS_LIMITED
    assert limited.assessment_epistemic_status == EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE
    assert "direct_traceability" in limited.missing_critical_context
    assert missing.comparability_status == COMPARABILITY_STATUS_INSUFFICIENT
    assert missing.requires_expert_review is True
    assert missing.assessment_epistemic_status == EPISTEMIC_UNRESOLVED


def test_evaluate_comparison_assessment_detects_not_comparable_without_baseline_and_condition() -> None:
    assessment = evaluate_comparison_assessment(
        _build_comparable_result(
            baseline_id=None,
            baseline_reference=None,
            test_condition_id=None,
            traceability_status=TRACEABILITY_STATUS_PARTIAL,
        )
    )

    assert assessment.comparability_status == COMPARABILITY_STATUS_NOT_COMPARABLE
    assert "baseline_reference" in assessment.missing_critical_context
    assert "test_condition" in assessment.missing_critical_context


def test_evaluate_comparison_assessment_applies_pbf_tensile_missingness() -> None:
    context = {
        "variant": {
            "domain_profile": "pbf_metal",
            "process_context": {
                "laser_power_w": 280,
                "scan_speed_mm_s": 1200,
                "layer_thickness_um": 30,
                "hatch_spacing_um": 100,
                "energy_density_j_mm3": 78,
                "energy_density_origin": "reported",
                "build_orientation": "vertical",
                "post_treatment_summary": "HIP",
            },
        },
        "test_condition": {
            "condition_payload": {
                "test_method": "tensile",
                "test_temperature_c": 25,
                "strain_rate_s-1": 0.001,
                "loading_direction": "vertical",
                "sample_orientation": "vertical",
            }
        },
        "measurement_result": {
            "value_payload": {
                "value": 940,
                "value_origin": "reported",
            }
        },
    }

    complete = evaluate_comparison_assessment(
        _build_comparable_result(property_normalized="yield_strength"),
        assessment_context=context,
    )
    missing_strain_rate = evaluate_comparison_assessment(
        _build_comparable_result(property_normalized="yield_strength"),
        assessment_context={
            **context,
            "test_condition": {
                "condition_payload": {
                    "test_method": "tensile",
                    "test_temperature_c": 25,
                    "loading_direction": "vertical",
                    "sample_orientation": "vertical",
                }
            },
        },
    )

    assert complete.comparability_status == COMPARABILITY_STATUS_COMPARABLE
    assert "pbf_context_detected" in complete.comparability_basis
    assert "strain_rate_reported" in complete.comparability_basis
    assert missing_strain_rate.comparability_status == COMPARABILITY_STATUS_LIMITED
    assert "strain_rate_s-1" in missing_strain_rate.missing_critical_context
    assert any(
        "missing strain rate" in warning
        for warning in missing_strain_rate.comparability_warnings
    )


def test_evaluate_comparison_assessment_flags_energy_density_provenance() -> None:
    base_context = {
        "variant": {
            "domain_profile": "pbf_metal",
            "process_context": {
                "laser_power_w": 280,
                "scan_speed_mm_s": 1200,
                "layer_thickness_um": 30,
                "hatch_spacing_um": 100,
                "energy_density_j_mm3": 78,
                "build_orientation": "vertical",
            },
        },
        "test_condition": {
            "condition_payload": {
                "test_method": "tensile",
                "test_temperature_c": 25,
                "strain_rate_s-1": 0.001,
                "loading_direction": "vertical",
                "sample_orientation": "vertical",
            }
        },
    }

    derived = evaluate_comparison_assessment(
        _build_comparable_result(property_normalized="yield_strength"),
        assessment_context={
            **base_context,
            "variant": {
                **base_context["variant"],
                "process_context": {
                    **base_context["variant"]["process_context"],
                    "energy_density_origin": "derived",
                },
            },
        },
    )
    estimated = evaluate_comparison_assessment(
        _build_comparable_result(property_normalized="yield_strength"),
        assessment_context={
            **base_context,
            "variant": {
                **base_context["variant"],
                "process_context": {
                    **base_context["variant"]["process_context"],
                    "energy_density_origin": "estimated",
                },
            },
        },
    )

    assert derived.comparability_status == COMPARABILITY_STATUS_COMPARABLE
    assert derived.requires_expert_review is False
    assert "energy_density_origin:derived" in derived.comparability_basis
    assert any("Energy density was derived" in warning for warning in derived.comparability_warnings)
    assert estimated.comparability_status == COMPARABILITY_STATUS_LIMITED
    assert estimated.requires_expert_review is True
    assert "energy_density_estimated" in estimated.missing_critical_context


def test_comparison_row_record_normalizes_lists_and_defaults() -> None:
    row = ComparisonRowRecord.from_mapping(
        {
            "row_id": "cmp-1",
            "collection_id": "col-1",
            "comparable_result_id": "cres-1",
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

    assert row.comparable_result_id == "cres-1"
    assert row.supporting_evidence_ids == ("ev-1",)
    assert row.requires_expert_review is False
    assert row.to_record()["value"] == 97.0


def test_comparable_result_id_is_stable_for_identical_semantic_payloads() -> None:
    first = build_comparable_result_id(
        source_document_id="doc-1",
        property_normalized="strength",
        result_type="scalar",
        value_payload={"value": 97.0, "statement": "97 MPa"},
        unit="MPa",
        result_source_type="text",
        traceability_status=TRACEABILITY_STATUS_DIRECT,
        variant_payload={"variant_label": "epoxy composite", "variable_axis": None},
        baseline_payload={"baseline_label": "untreated baseline"},
        test_condition_payload={"condition_normalized": "tensile"},
    )
    second = build_comparable_result_id(
        source_document_id="doc-1",
        property_normalized="strength",
        result_type="scalar",
        value_payload={"statement": "97 MPa", "value": 97.0},
        unit="MPa",
        result_source_type="text",
        traceability_status=TRACEABILITY_STATUS_DIRECT,
        variant_payload={"variable_axis": None, "variant_label": "epoxy composite"},
        baseline_payload={"baseline_label": "untreated baseline"},
        test_condition_payload={"condition_normalized": "tensile"},
    )

    assert first == second
    assert first.startswith("cres_")


def test_comparable_result_round_trips_through_record_payload() -> None:
    comparable_result = _build_comparable_result(
        structure_feature_ids=("feat-1", "feat-2"),
        characterization_observation_ids=("obs-1", "obs-2"),
    )

    restored = ComparableResult.from_mapping(comparable_result.to_record())

    assert restored == comparable_result


def test_collection_comparable_result_round_trips_through_record_payload() -> None:
    comparable_result = _build_comparable_result()
    assessment = evaluate_comparison_assessment(comparable_result)
    scoped_result = CollectionComparableResult(
        collection_id="col-1",
        comparable_result_id=comparable_result.comparable_result_id,
        assessment=assessment,
        epistemic_status=assessment.assessment_epistemic_status,
        included=True,
        sort_order=3,
        policy_family=COLLECTION_COMPARISON_POLICY_FAMILY,
        policy_version=COLLECTION_COMPARISON_POLICY_VERSION,
        comparable_result_normalization_version=comparable_result.normalization_version,
        assessment_input_fingerprint=build_collection_assessment_input_fingerprint(
            comparable_result
        ),
        reassessment_triggers=(
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
        ),
    )

    restored = CollectionComparableResult.from_mapping(scoped_result.to_record())

    assert restored == scoped_result


def test_comparison_assessment_round_trips_through_record_payload() -> None:
    assessment = ComparisonAssessment(
        missing_critical_context=("baseline_reference",),
        comparability_basis=("variant_linked",),
        comparability_warnings=("Baseline reference is missing or unresolved.",),
        comparability_status=COMPARABILITY_STATUS_LIMITED,
        requires_expert_review=True,
        assessment_epistemic_status=EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE,
    )

    restored = ComparisonAssessment.from_mapping(assessment.to_record())

    assert restored == assessment


def test_evaluate_collection_reassessment_reasons_detects_policy_and_input_drift() -> None:
    comparable_result = _build_comparable_result()
    assessment = evaluate_comparison_assessment(comparable_result)
    scoped_result = CollectionComparableResult(
        collection_id="col-1",
        comparable_result_id=comparable_result.comparable_result_id,
        assessment=assessment,
        epistemic_status=assessment.assessment_epistemic_status,
        included=True,
        sort_order=0,
        policy_family=COLLECTION_COMPARISON_POLICY_FAMILY,
        policy_version=COLLECTION_COMPARISON_POLICY_VERSION,
        comparable_result_normalization_version=comparable_result.normalization_version,
        assessment_input_fingerprint="cafp_outdated",
        reassessment_triggers=(
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
        ),
    )

    reasons = evaluate_collection_reassessment_reasons(
        scoped_result,
        comparable_result,
        policy_family="alternate_policy_family",
        policy_version="comparison_policy_v2",
    )

    assert reasons == (
        COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
        COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
        COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
    )


def test_evaluate_collection_reassessment_reasons_returns_empty_when_scope_record_is_current() -> None:
    comparable_result = _build_comparable_result()
    assessment = evaluate_comparison_assessment(comparable_result)
    scoped_result = CollectionComparableResult(
        collection_id="col-1",
        comparable_result_id=comparable_result.comparable_result_id,
        assessment=assessment,
        epistemic_status=assessment.assessment_epistemic_status,
        included=True,
        sort_order=0,
        policy_family=COLLECTION_COMPARISON_POLICY_FAMILY,
        policy_version=COLLECTION_COMPARISON_POLICY_VERSION,
        comparable_result_normalization_version=comparable_result.normalization_version,
        assessment_input_fingerprint=build_collection_assessment_input_fingerprint(
            comparable_result
        ),
        reassessment_triggers=(
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
        ),
    )

    reasons = evaluate_collection_reassessment_reasons(
        scoped_result,
        comparable_result,
    )

    assert reasons == ()
