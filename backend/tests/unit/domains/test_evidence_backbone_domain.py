from __future__ import annotations

from domain.core.evidence_backbone import (
    CORE_NEUTRAL_DOMAIN_PROFILE,
    CharacterizationObservation,
    EvidenceAnchor,
    MeasurementResult,
    SampleVariant,
    TestCondition,
)
from domain.shared.enums import (
    EPISTEMIC_DIRECTLY_OBSERVED,
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    TRACEABILITY_STATUS_DIRECT,
)


def test_evidence_anchor_normalizes_nested_locator_payloads() -> None:
    anchor = EvidenceAnchor.from_mapping(
        {
            "anchor_id": "anchor-1",
            "document_id": "doc-1",
            "locator_type": "char_range",
            "locator_confidence": "high",
            "source_type": "text",
            "section_id": "sec-1",
            "char_range": {"start": 12, "end": 24},
            "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
            "page": 2,
            "quote": "quoted text",
            "deep_link": "/collections/c/documents/d",
            "snippet_id": "tu-1",
        }
    )

    assert anchor.char_range == {"start": 12, "end": 24}
    assert anchor.bbox == {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0}
    assert anchor.to_record()["page"] == 2


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
            "structure_feature_ids": ["feat-1", "feat-2"],
            "source_anchor_ids": ["anchor-1"],
            "confidence": 0.823,
            "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
        }
    )
    condition = TestCondition.from_mapping(
        {
            "test_condition_id": "tc-1",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "property_type": "strength",
            "template_type": "tensile_mechanics",
            "scope_level": "measurement",
            "condition_payload": {"method": "tensile", "temperatures_c": [25.0]},
            "missing_fields": ["method"],
            "evidence_anchor_ids": ["anchor-1"],
            "confidence": 0.718,
            "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
        }
    )

    assert variant.domain_profile == CORE_NEUTRAL_DOMAIN_PROFILE
    assert variant.structure_feature_ids == ("feat-1", "feat-2")
    assert variant.confidence == 0.82
    assert condition.domain_profile == CORE_NEUTRAL_DOMAIN_PROFILE
    assert condition.condition_completeness == "unresolved"
    assert condition.confidence == 0.72


def test_characterization_and_measurement_results_round_trip_records() -> None:
    observation = CharacterizationObservation.from_mapping(
        {
            "observation_id": "obs-1",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "characterization_type": "sem",
            "observation_text": "SEM showed dense grains.",
            "observed_value": 12.0,
            "observed_unit": "um",
            "condition_context": {"process": {"temperatures_c": [80.0]}},
            "evidence_anchor_ids": ["anchor-1", "anchor-2"],
            "confidence": 0.841,
            "epistemic_status": EPISTEMIC_DIRECTLY_OBSERVED,
        }
    )
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
            "structure_feature_ids": ["feat-1"],
            "characterization_observation_ids": ["obs-1"],
            "evidence_anchor_ids": ["anchor-1"],
            "traceability_status": TRACEABILITY_STATUS_DIRECT,
            "result_source_type": "text",
            "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
        }
    )

    assert observation.to_record()["evidence_anchor_ids"] == ["anchor-1", "anchor-2"]
    assert observation.confidence == 0.84
    assert result.to_record()["value_payload"]["value"] == 97.0
    assert result.traceability_status == TRACEABILITY_STATUS_DIRECT
