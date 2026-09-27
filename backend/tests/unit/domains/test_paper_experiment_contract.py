from __future__ import annotations

import pytest

from domain.core.paper_experiment import (
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    ExperimentalVariant,
    PaperExperimentRevision,
)


def _experiment_payload() -> dict:
    return {
        "experiment_id": "exp-1",
        "document_id": "doc-1",
        "experiment_version": 1,
        "source_fingerprint": "prep-1",
        "label": "Preheat tensile series",
        "scope_description": "A, B, and C under one tensile method",
        "design_type": "parallel",
        "identity_status": "identified",
        "binding_status": "bound",
        "variants": [
            {"variant_key": "A", "variant_label": "NP"},
            {"variant_key": "B", "variant_label": "P150"},
            {"variant_key": "C", "variant_label": "P200"},
        ],
        "test_conditions": [{"test_key": "tensile-1", "test_type": "tensile"}],
        "measurements": [
            {
                "measurement_key": "a-elongation",
                "outcome": "elongation",
                "variant_key": "A",
                "test_key": "tensile-1",
                "value": 72,
                "unit": "%",
                "binding_status": "direct",
            },
            {
                "measurement_key": "b-elongation",
                "outcome": "elongation",
                "variant_key": "B",
                "test_key": "tensile-1",
                "value": 82,
                "unit": "%",
                "binding_status": "direct",
            },
            {
                "measurement_key": "c-elongation",
                "outcome": "elongation",
                "variant_key": "C",
                "test_key": "tensile-1",
                "value": 85,
                "unit": "%",
                "binding_status": "direct",
            },
            {
                "measurement_key": "a-strength",
                "outcome": "yield_strength",
                "variant_key": "A",
                "test_key": "tensile-1",
                "value": 500,
                "unit": "MPa",
                "binding_status": "direct",
            },
        ],
    }


def test_revision_preserves_multi_variant_multi_outcome_table() -> None:
    experiment = PaperExperimentRevision.from_mapping(_experiment_payload())

    assert [item.variant_key for item in experiment.variants] == ["A", "B", "C"]
    assert {item.outcome for item in experiment.measurements} == {
        "elongation",
        "yield_strength",
    }
    restored = PaperExperimentRevision.from_mapping(experiment.to_record())
    assert restored.to_record() == experiment.to_record()


def test_measurement_cannot_reference_variant_outside_revision() -> None:
    payload = _experiment_payload()
    payload["measurements"][0]["variant_key"] = "missing"

    with pytest.raises(ValueError, match="variant outside"):
        PaperExperimentRevision.from_mapping(payload)


def test_duplicate_variant_keys_are_rejected() -> None:
    payload = _experiment_payload()
    payload["variants"].append({"variant_key": "A", "variant_label": "duplicate"})

    with pytest.raises(ValueError, match="variant keys must be unique"):
        PaperExperimentRevision.from_mapping(payload)


def test_comparison_must_use_same_outcome_measurements() -> None:
    payload = _experiment_payload()
    payload["comparisons"] = [
        {
            "comparison_key": "a-to-b",
            "baseline_variant_key": "A",
            "target_variant_key": "B",
            "outcome": "elongation",
            "baseline_measurement_keys": ["a-elongation"],
            "target_measurement_keys": ["a-strength"],
        }
    ]

    with pytest.raises(ValueError, match="share the comparison outcome"):
        PaperExperimentRevision.from_mapping(payload)


def test_comparison_accepts_unit_annotation_difference_in_outcome_labels() -> None:
    payload = _experiment_payload()
    payload["measurements"][0]["outcome"] = "elongation (%)"
    payload["comparisons"] = [
        {
            "comparison_key": "a-to-b",
            "baseline_variant_key": "A",
            "target_variant_key": "B",
            "outcome": "elongation",
            "baseline_measurement_keys": ["a-elongation"],
            "target_measurement_keys": ["b-elongation"],
        }
    ]

    revision = PaperExperimentRevision.from_mapping(payload)

    assert revision.comparisons[0].outcome == "elongation"


@pytest.mark.parametrize(
    ("measurement_outcome", "comparison_outcome"),
    [
        ("hardness (HV)", "hardness"),
        ("yield strength (MPa)", "yield strength"),
        ("energy density (J/mm3)", "energy density"),
    ],
)
def test_comparison_accepts_common_unit_annotations(
    measurement_outcome: str,
    comparison_outcome: str,
) -> None:
    payload = _experiment_payload()
    payload["measurements"][0]["outcome"] = measurement_outcome
    payload["measurements"][1]["outcome"] = measurement_outcome
    payload["comparisons"] = [
        {
            "comparison_key": "a-to-b",
            "baseline_variant_key": "A",
            "target_variant_key": "B",
            "outcome": comparison_outcome,
            "baseline_measurement_keys": ["a-elongation"],
            "target_measurement_keys": ["b-elongation"],
        }
    ]

    revision = PaperExperimentRevision.from_mapping(payload)

    assert revision.comparisons[0].outcome == comparison_outcome


def test_non_unit_qualifier_is_not_dropped_from_outcome_label() -> None:
    payload = _experiment_payload()
    payload["measurements"][0]["outcome"] = "strength (tensile)"
    payload["measurements"][1]["outcome"] = "strength (tensile)"
    payload["comparisons"] = [
        {
            "comparison_key": "a-to-b",
            "baseline_variant_key": "A",
            "target_variant_key": "B",
            "outcome": "strength",
            "baseline_measurement_keys": ["a-elongation"],
            "target_measurement_keys": ["b-elongation"],
        }
    ]

    with pytest.raises(ValueError, match="share the comparison outcome"):
        PaperExperimentRevision.from_mapping(payload)


@pytest.mark.parametrize(
    ("measurement_outcome", "comparison_outcome"),
    [("tensile strength", "strength"), ("test temperature", "temperature")],
)
def test_comparison_rejects_different_outcomes_with_shared_tokens(
    measurement_outcome: str,
    comparison_outcome: str,
) -> None:
    payload = _experiment_payload()
    payload["measurements"][0]["outcome"] = measurement_outcome
    payload["comparisons"] = [
        {
            "comparison_key": "a-to-b",
            "baseline_variant_key": "A",
            "target_variant_key": "B",
            "outcome": comparison_outcome,
            "baseline_measurement_keys": ["a-elongation"],
            "target_measurement_keys": ["b-elongation"],
        }
    ]

    with pytest.raises(ValueError, match="share the comparison outcome"):
        PaperExperimentRevision.from_mapping(payload)


def test_reported_result_can_preserve_non_numeric_text_and_unresolved_issue() -> None:
    payload = _experiment_payload()
    payload["measurements"].append(
        {
            "measurement_key": "b-text",
            "outcome": "fracture_mode",
            "variant_key": "B",
            "test_key": "tensile-1",
            "result_text": "ductile-looking fracture",
        }
    )
    payload["unresolved_issues"] = [
        {"target_ref": "measurements/b-text", "description": "test temperature unknown"}
    ]

    experiment = PaperExperimentRevision.from_mapping(payload)

    assert experiment.measurements[-1].value is None
    assert experiment.measurements[-1].result_text == "ductile-looking fracture"
    assert experiment.unresolved_issues[0]["target_ref"] == "measurements/b-text"


def test_broad_variant_and_test_metadata_survive_domain_round_trip() -> None:
    """Broad source labels remain auditable without becoming exact bindings."""

    source = {
        "document_id": "doc-1",
        "source_fingerprint": "prep-1",
        "source_kind": "section",
        "source_ref": "methods-1",
        "quote": "Mechanical tests were reported for as-SLM samples.",
    }
    payload = _experiment_payload()
    payload["variants"][0].update(
        {
            "variant_label": "as-SLM",
            "identity_specificity": "partial",
            "missing_dimensions": ["laser power", "scan speed"],
            "identity_evidence": ["methods-1"],
            "source_refs": [source],
        }
    )
    payload["test_conditions"][0].update(
        {
            "test_type": "mechanical test",
            "protocol_specificity": "partial",
            "test_identity_status": "category",
            "protocol_completeness": "partial",
            "missing_parameters": ["standard", "strain rate"],
            "method": "mechanical test",
            "standard": None,
            "outcome_scope": ["elongation", "yield_strength"],
            "protocol_evidence": ["methods-1"],
            "source_refs": [source],
            "binding_source_refs": [source],
        }
    )

    experiment = PaperExperimentRevision.from_mapping(payload)
    variant = experiment.variants[0]
    test = experiment.test_conditions[0]

    assert variant.identity_specificity == "partial"
    assert variant.missing_dimensions == ("laser power", "scan speed")
    assert variant.identity_evidence == ("methods-1",)
    assert test.protocol_specificity == "partial"
    assert test.test_identity_status == "category"
    assert test.protocol_completeness == "partial"
    assert test.missing_parameters == ("standard", "strain rate")
    assert test.outcome_scope == ("elongation", "yield_strength")
    assert test.protocol_evidence == ("methods-1",)
    assert len(test.binding_source_refs) == 1

    restored = PaperExperimentRevision.from_mapping(experiment.to_record())
    assert restored.to_record() == experiment.to_record()


def test_missing_specificity_defaults_to_unknown_instead_of_claiming_exact() -> None:
    payload = _experiment_payload()

    experiment = PaperExperimentRevision.from_mapping(payload)

    assert experiment.variants[0].identity_specificity == "unknown"
    assert experiment.test_conditions[0].protocol_specificity == "unknown"
    assert experiment.test_conditions[0].protocol_completeness == "unknown"
