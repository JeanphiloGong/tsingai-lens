from __future__ import annotations

from domain.core.evidence_backbone import (
    CORE_NEUTRAL_DOMAIN_PROFILE,
    MeasurementResult,
    SampleVariant,
    TestCondition as DomainTestCondition,
)
from domain.shared.enums import (
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    TRACEABILITY_STATUS_DIRECT,
)


def test_sample_variant_and_test_condition_apply_domain_defaults() -> None:
    variant = SampleVariant.from_mapping(
        {
            "variant_id": "var-1",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "variant_label": "Sample A",
            "host_material_system": {"family": "epoxy", "composition": "epoxy + sio2"},
            "process_context": {"temperatures_c": [80.0], "durations": ["2 h"]},
            "profile_payload": {"source_kind": "table_row"},
            "confidence": 0.823,
            "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
        }
    )
    condition = DomainTestCondition.from_mapping(
        {
            "test_condition_id": "tc-1",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "property_type": "strength",
            "template_type": "tensile_mechanics",
            "scope_level": "measurement",
            "condition_payload": {"method": "tensile", "temperatures_c": [25.0]},
            "missing_fields": ["method"],
            "confidence": 0.718,
            "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
        }
    )

    assert variant.domain_profile == CORE_NEUTRAL_DOMAIN_PROFILE
    assert variant.confidence == 0.82
    assert condition.domain_profile == CORE_NEUTRAL_DOMAIN_PROFILE
    assert condition.condition_completeness == "unresolved"
    assert condition.confidence == 0.72


def test_measurement_results_round_trip_records() -> None:
    result = MeasurementResult.from_mapping(
        {
            "result_id": "res-1",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "property_normalized": "strength",
            "result_type": "scalar",
            "value_payload": {"value": 97.0, "statement": "97 MPa"},
            "unit": "MPa",
            "test_condition_id": "tc-1",
            "baseline_id": "base-1",
            "traceability_status": TRACEABILITY_STATUS_DIRECT,
            "result_source_type": "text",
            "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
        }
    )

    assert result.to_record()["value_payload"]["value"] == 97.0
    assert result.traceability_status == TRACEABILITY_STATUS_DIRECT
