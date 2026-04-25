from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from domain.core.comparison import (
    COMPARABLE_RESULT_NORMALIZATION_VERSION,
    COLLECTION_COMPARISON_POLICY_FAMILY,
    COLLECTION_COMPARISON_POLICY_VERSION,
    COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
    ComparableResult,
    build_collection_assessment_input_fingerprint,
    evaluate_comparison_assessment,
)


PBF_DOCUMENT_ID = "paper-1"
PBF_S2_VARIANT_ID = "var-s2"
PBF_S3_VARIANT_ID = "var-s3"
PBF_BASELINE_ID = "base-s2"
PBF_BASELINE_LABEL = "S2 optimized VED without HIP"
PBF_YIELD_25_RESULT_ID = "res-s3-ys-25"
PBF_YIELD_200_RESULT_ID = "res-s3-ys-200"
PBF_ELONGATION_RESULT_ID = "res-s3-el-25"
PBF_YIELD_25_COMPARABLE_ID = "cres-s3-ys-25"
PBF_YIELD_200_COMPARABLE_ID = "cres-s3-ys-200"
PBF_ELONGATION_COMPARABLE_ID = "cres-s3-el-25"
PBF_YIELD_SERIES_KEY = "yield_strength:test_temperature_c"


def write_pbf_acceptance_artifacts(
    output_dir: Path,
    *,
    collection_id: str,
    include_strain_rate: bool = True,
) -> None:
    """Write the Slice 5 single-paper PBF evidence-chain fixture."""

    sample_variants = pbf_acceptance_sample_variants(collection_id)
    test_conditions = pbf_acceptance_test_conditions(
        collection_id,
        include_strain_rate=include_strain_rate,
    )
    baseline_references = pbf_acceptance_baseline_references(collection_id)
    measurement_results = pbf_acceptance_measurement_results(collection_id)
    characterization = pbf_acceptance_characterization_observations(collection_id)
    structure_features = pbf_acceptance_structure_features(collection_id)
    comparable_results, scoped_results = pbf_acceptance_comparison_records(
        collection_id,
        sample_variants=sample_variants,
        test_conditions=test_conditions,
        baseline_references=baseline_references,
        measurement_results=measurement_results,
    )

    pd.DataFrame(sample_variants).to_parquet(
        output_dir / "sample_variants.parquet",
        index=False,
    )
    pd.DataFrame(test_conditions).to_parquet(
        output_dir / "test_conditions.parquet",
        index=False,
    )
    pd.DataFrame(baseline_references).to_parquet(
        output_dir / "baseline_references.parquet",
        index=False,
    )
    pd.DataFrame(measurement_results).to_parquet(
        output_dir / "measurement_results.parquet",
        index=False,
    )
    pd.DataFrame(characterization).to_parquet(
        output_dir / "characterization_observations.parquet",
        index=False,
    )
    pd.DataFrame(structure_features).to_parquet(
        output_dir / "structure_features.parquet",
        index=False,
    )
    pd.DataFrame(comparable_results).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(scoped_results).to_parquet(
        output_dir / "collection_comparable_results.parquet",
        index=False,
    )


def pbf_acceptance_assessment_context(
    *,
    collection_id: str = "col-pbf-acceptance",
    include_strain_rate: bool = True,
) -> dict[str, Any]:
    test_conditions = pbf_acceptance_test_conditions(
        collection_id,
        include_strain_rate=include_strain_rate,
    )
    return {
        "variant": _row_by_id(
            pbf_acceptance_sample_variants(collection_id),
            "variant_id",
            PBF_S3_VARIANT_ID,
        ),
        "test_condition": _row_by_id(test_conditions, "test_condition_id", "tc-25"),
        "baseline": _row_by_id(
            pbf_acceptance_baseline_references(collection_id),
            "baseline_id",
            PBF_BASELINE_ID,
        ),
        "measurement_result": _row_by_id(
            pbf_acceptance_measurement_results(collection_id),
            "result_id",
            PBF_YIELD_25_RESULT_ID,
        ),
    }


def pbf_acceptance_sample_variants(collection_id: str) -> list[dict[str, Any]]:
    return [
        {
            "variant_id": PBF_S2_VARIANT_ID,
            "document_id": PBF_DOCUMENT_ID,
            "collection_id": collection_id,
            "domain_profile": "pbf_metal",
            "variant_label": PBF_BASELINE_LABEL,
            "host_material_system": {
                "family": "titanium alloy",
                "composition": "Ti-6Al-4V",
            },
            "composition": "Ti-6Al-4V",
            "variable_axis_type": "post_treatment",
            "variable_value": "optimized VED without HIP",
            "process_context": _pbf_process_context(post_treatment_summary="no HIP"),
            "profile_payload": {},
            "structure_feature_ids": [],
            "source_anchor_ids": ["anchor-s2-process"],
            "confidence": 0.9,
            "epistemic_status": "normalized_from_evidence",
        },
        {
            "variant_id": PBF_S3_VARIANT_ID,
            "document_id": PBF_DOCUMENT_ID,
            "collection_id": collection_id,
            "domain_profile": "pbf_metal",
            "variant_label": "S3 optimized VED + HIP",
            "host_material_system": {
                "family": "titanium alloy",
                "composition": "Ti-6Al-4V",
            },
            "composition": "Ti-6Al-4V",
            "variable_axis_type": "post_treatment",
            "variable_value": "optimized VED + HIP",
            "process_context": _pbf_process_context(post_treatment_summary="HIP"),
            "profile_payload": {},
            "structure_feature_ids": ["sf-porosity", "sf-residual-stress"],
            "source_anchor_ids": ["anchor-s3-process"],
            "confidence": 0.9,
            "epistemic_status": "normalized_from_evidence",
        },
    ]


def pbf_acceptance_test_conditions(
    collection_id: str,
    *,
    include_strain_rate: bool = True,
) -> list[dict[str, Any]]:
    return [
        _test_condition_row(
            collection_id=collection_id,
            test_condition_id="tc-25",
            temperature_c=25.0,
            include_strain_rate=include_strain_rate,
        ),
        _test_condition_row(
            collection_id=collection_id,
            test_condition_id="tc-200",
            temperature_c=200.0,
            include_strain_rate=include_strain_rate,
        ),
    ]


def pbf_acceptance_baseline_references(collection_id: str) -> list[dict[str, Any]]:
    return [
        {
            "baseline_id": PBF_BASELINE_ID,
            "document_id": PBF_DOCUMENT_ID,
            "collection_id": collection_id,
            "domain_profile": "pbf_metal",
            "variant_id": PBF_S2_VARIANT_ID,
            "baseline_type": "same_paper_control",
            "baseline_label": PBF_BASELINE_LABEL,
            "baseline_scope": "current_paper",
            "evidence_anchor_ids": ["anchor-baseline-s2"],
            "confidence": 0.9,
            "epistemic_status": "normalized_from_evidence",
        }
    ]


def pbf_acceptance_measurement_results(collection_id: str) -> list[dict[str, Any]]:
    return [
        _measurement_result_row(
            collection_id=collection_id,
            result_id=PBF_YIELD_25_RESULT_ID,
            property_normalized="yield_strength",
            value=940.0,
            source_value_text="940",
            unit="MPa",
            test_condition_id="tc-25",
            anchor_id="anchor-ys-25",
        ),
        _measurement_result_row(
            collection_id=collection_id,
            result_id=PBF_YIELD_200_RESULT_ID,
            property_normalized="yield_strength",
            value=820.0,
            source_value_text="820",
            unit="MPa",
            test_condition_id="tc-200",
            anchor_id="anchor-ys-200",
        ),
        _measurement_result_row(
            collection_id=collection_id,
            result_id=PBF_ELONGATION_RESULT_ID,
            property_normalized="elongation",
            value=15.0,
            source_value_text="15",
            unit="%",
            test_condition_id="tc-25",
            anchor_id="anchor-el-25",
        ),
    ]


def pbf_acceptance_characterization_observations(
    collection_id: str,
) -> list[dict[str, Any]]:
    return [
        {
            "observation_id": "obs-porosity",
            "document_id": PBF_DOCUMENT_ID,
            "collection_id": collection_id,
            "variant_id": PBF_S3_VARIANT_ID,
            "characterization_type": "porosity",
            "observation_text": "Porosity decreased to 0.1%.",
            "observed_value": 0.1,
            "observed_unit": "%",
            "condition_context": {"process": {}, "test": {}, "baseline": {}},
            "evidence_anchor_ids": ["anchor-porosity"],
            "confidence": 0.9,
            "epistemic_status": "normalized_from_evidence",
        },
        {
            "observation_id": "obs-residual-stress",
            "document_id": PBF_DOCUMENT_ID,
            "collection_id": collection_id,
            "variant_id": PBF_S3_VARIANT_ID,
            "characterization_type": "residual_stress",
            "observation_text": "Residual stress was lower after HIP.",
            "observed_value": None,
            "observed_unit": None,
            "condition_context": {"process": {}, "test": {}, "baseline": {}},
            "evidence_anchor_ids": ["anchor-residual-stress"],
            "confidence": 0.86,
            "epistemic_status": "normalized_from_evidence",
        },
    ]


def pbf_acceptance_structure_features(collection_id: str) -> list[dict[str, Any]]:
    return [
        {
            "feature_id": "sf-porosity",
            "document_id": PBF_DOCUMENT_ID,
            "collection_id": collection_id,
            "variant_id": PBF_S3_VARIANT_ID,
            "feature_type": "porosity",
            "feature_value": 0.1,
            "feature_unit": "%",
            "qualitative_descriptor": "Porosity 0.1%",
            "source_observation_ids": ["obs-porosity"],
            "confidence": 0.9,
            "epistemic_status": "normalized_from_evidence",
        },
        {
            "feature_id": "sf-residual-stress",
            "document_id": PBF_DOCUMENT_ID,
            "collection_id": collection_id,
            "variant_id": PBF_S3_VARIANT_ID,
            "feature_type": "residual_stress",
            "feature_value": None,
            "feature_unit": None,
            "qualitative_descriptor": "Residual stress lower after HIP",
            "source_observation_ids": ["obs-residual-stress"],
            "confidence": 0.86,
            "epistemic_status": "normalized_from_evidence",
        },
    ]


def pbf_acceptance_comparison_records(
    collection_id: str,
    *,
    sample_variants: list[dict[str, Any]] | None = None,
    test_conditions: list[dict[str, Any]] | None = None,
    baseline_references: list[dict[str, Any]] | None = None,
    measurement_results: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sample_variants = sample_variants or pbf_acceptance_sample_variants(collection_id)
    test_conditions = test_conditions or pbf_acceptance_test_conditions(collection_id)
    baseline_references = baseline_references or pbf_acceptance_baseline_references(
        collection_id
    )
    measurement_results = measurement_results or pbf_acceptance_measurement_results(
        collection_id
    )
    comparable_results = [
        _comparable_result_record(
            comparable_result_id=PBF_YIELD_25_COMPARABLE_ID,
            source_result_id=PBF_YIELD_25_RESULT_ID,
            property_normalized="yield_strength",
            numeric_value=940.0,
            unit="MPa",
            summary="YS 940 MPa at 25 C",
            test_condition_id="tc-25",
            evidence_id="ev-ys-25",
        ),
        _comparable_result_record(
            comparable_result_id=PBF_YIELD_200_COMPARABLE_ID,
            source_result_id=PBF_YIELD_200_RESULT_ID,
            property_normalized="yield_strength",
            numeric_value=820.0,
            unit="MPa",
            summary="YS 820 MPa at 200 C",
            test_condition_id="tc-200",
            evidence_id="ev-ys-200",
        ),
        _comparable_result_record(
            comparable_result_id=PBF_ELONGATION_COMPARABLE_ID,
            source_result_id=PBF_ELONGATION_RESULT_ID,
            property_normalized="elongation",
            numeric_value=15.0,
            unit="%",
            summary="EL 15% at 25 C",
            test_condition_id="tc-25",
            evidence_id="ev-el-25",
        ),
    ]
    scoped_results = [
        _scoped_result_record(
            collection_id=collection_id,
            comparable_result=comparable_result,
            sort_order=sort_order,
            assessment_context=_assessment_context_for_record(
                comparable_result,
                sample_variants=sample_variants,
                test_conditions=test_conditions,
                baseline_references=baseline_references,
                measurement_results=measurement_results,
            ),
        )
        for sort_order, comparable_result in enumerate(comparable_results)
    ]
    return comparable_results, scoped_results


def _pbf_process_context(*, post_treatment_summary: str) -> dict[str, Any]:
    return {
        "laser_power_w": 280,
        "scan_speed_mm_s": 1200,
        "hatch_spacing_um": 100,
        "layer_thickness_um": 30,
        "energy_density_j_mm3": 78,
        "energy_density_origin": "reported",
        "build_orientation": "vertical",
        "post_treatment_summary": post_treatment_summary,
    }


def _test_condition_row(
    *,
    collection_id: str,
    test_condition_id: str,
    temperature_c: float,
    include_strain_rate: bool,
) -> dict[str, Any]:
    condition_payload: dict[str, Any] = {
        "test_method": "tensile",
        "test_temperature_c": temperature_c,
        "loading_direction": "vertical",
        "sample_orientation": "vertical",
    }
    if include_strain_rate:
        condition_payload["strain_rate_s-1"] = 0.001
    return {
        "test_condition_id": test_condition_id,
        "document_id": PBF_DOCUMENT_ID,
        "collection_id": collection_id,
        "domain_profile": "pbf_metal",
        "property_type": "yield_strength",
        "template_type": "tensile_mechanics",
        "scope_level": "result",
        "condition_payload": condition_payload,
        "condition_completeness": "complete" if include_strain_rate else "partial",
        "missing_fields": [] if include_strain_rate else ["strain_rate_s-1"],
        "evidence_anchor_ids": [f"anchor-test-{int(temperature_c)}"],
        "confidence": 0.9,
        "epistemic_status": "normalized_from_evidence",
    }


def _measurement_result_row(
    *,
    collection_id: str,
    result_id: str,
    property_normalized: str,
    value: float,
    source_value_text: str,
    unit: str,
    test_condition_id: str,
    anchor_id: str,
) -> dict[str, Any]:
    return {
        "result_id": result_id,
        "document_id": PBF_DOCUMENT_ID,
        "collection_id": collection_id,
        "domain_profile": "pbf_metal",
        "variant_id": PBF_S3_VARIANT_ID,
        "property_normalized": property_normalized,
        "result_type": "scalar",
        "claim_scope": "current_work",
        "value_payload": {
            "value": value,
            "source_value_text": source_value_text,
            "source_unit_text": unit,
            "value_origin": "reported",
        },
        "unit": unit,
        "test_condition_id": test_condition_id,
        "baseline_id": PBF_BASELINE_ID,
        "structure_feature_ids": ["sf-porosity", "sf-residual-stress"],
        "characterization_observation_ids": ["obs-porosity", "obs-residual-stress"],
        "evidence_anchor_ids": [anchor_id],
        "traceability_status": "direct",
        "result_source_type": "table",
        "epistemic_status": "normalized_from_evidence",
    }


def _comparable_result_record(
    *,
    comparable_result_id: str,
    source_result_id: str,
    property_normalized: str,
    numeric_value: float,
    unit: str,
    summary: str,
    test_condition_id: str,
    evidence_id: str,
) -> dict[str, Any]:
    return {
        "comparable_result_id": comparable_result_id,
        "source_result_id": source_result_id,
        "source_document_id": PBF_DOCUMENT_ID,
        "binding": {
            "variant_id": PBF_S3_VARIANT_ID,
            "baseline_id": PBF_BASELINE_ID,
            "test_condition_id": test_condition_id,
        },
        "normalized_context": {
            "material_system_normalized": "Ti-6Al-4V",
            "process_normalized": (
                "P=280 W, v=1200 mm/s, h=100 um, t=30 um, "
                "VED=78 J/mm3, VED_origin=reported, build=vertical, HIP"
            ),
            "baseline_normalized": PBF_BASELINE_LABEL,
            "test_condition_normalized": "tensile",
        },
        "axis": {
            "axis_name": None,
            "axis_value": None,
            "axis_unit": None,
        },
        "value": {
            "property_normalized": property_normalized,
            "result_type": "scalar",
            "numeric_value": numeric_value,
            "unit": unit,
            "summary": summary,
            "statistic_type": None,
            "uncertainty": None,
        },
        "evidence": {
            "direct_anchor_ids": [f"anchor-{comparable_result_id}"],
            "contextual_anchor_ids": ["anchor-s3-process", "anchor-baseline-s2"],
            "evidence_ids": [evidence_id],
            "structure_feature_ids": ["sf-porosity", "sf-residual-stress"],
            "characterization_observation_ids": [
                "obs-porosity",
                "obs-residual-stress",
            ],
            "traceability_status": "direct",
        },
        "variant_label": "S3 optimized VED + HIP",
        "baseline_reference": PBF_BASELINE_LABEL,
        "result_source_type": "table",
        "epistemic_status": "normalized_from_evidence",
        "normalization_version": COMPARABLE_RESULT_NORMALIZATION_VERSION,
    }


def _scoped_result_record(
    *,
    collection_id: str,
    comparable_result: dict[str, Any],
    sort_order: int,
    assessment_context: dict[str, Any],
) -> dict[str, Any]:
    record = ComparableResult.from_mapping(comparable_result)
    assessment = evaluate_comparison_assessment(
        record,
        assessment_context=assessment_context,
    )
    return {
        "collection_id": collection_id,
        "comparable_result_id": comparable_result["comparable_result_id"],
        "assessment": {
            "missing_critical_context": list(assessment.missing_critical_context),
            "comparability_basis": list(assessment.comparability_basis),
            "comparability_warnings": list(assessment.comparability_warnings),
            "comparability_status": assessment.comparability_status,
            "requires_expert_review": assessment.requires_expert_review,
            "assessment_epistemic_status": assessment.assessment_epistemic_status,
        },
        "epistemic_status": "normalized_from_evidence",
        "included": True,
        "sort_order": sort_order,
        "policy_family": COLLECTION_COMPARISON_POLICY_FAMILY,
        "policy_version": COLLECTION_COMPARISON_POLICY_VERSION,
        "comparable_result_normalization_version": COMPARABLE_RESULT_NORMALIZATION_VERSION,
        "assessment_input_fingerprint": build_collection_assessment_input_fingerprint(
            record
        ),
        "reassessment_triggers": [
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
        ],
    }


def _assessment_context_for_record(
    comparable_result: dict[str, Any],
    *,
    sample_variants: list[dict[str, Any]],
    test_conditions: list[dict[str, Any]],
    baseline_references: list[dict[str, Any]],
    measurement_results: list[dict[str, Any]],
) -> dict[str, Any]:
    binding = comparable_result["binding"]
    return {
        "variant": _row_by_id(sample_variants, "variant_id", binding["variant_id"]),
        "test_condition": _row_by_id(
            test_conditions,
            "test_condition_id",
            binding["test_condition_id"],
        ),
        "baseline": _row_by_id(
            baseline_references,
            "baseline_id",
            binding["baseline_id"],
        ),
        "measurement_result": _row_by_id(
            measurement_results,
            "result_id",
            comparable_result["source_result_id"],
        ),
    }


def _row_by_id(
    rows: list[dict[str, Any]],
    key: str,
    value: str,
) -> dict[str, Any]:
    return next(row for row in rows if row[key] == value)
