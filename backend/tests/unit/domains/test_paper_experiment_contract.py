from __future__ import annotations

from dataclasses import replace

import pytest

from domain.core.paper_experiment import (
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    ExperimentalVariant,
    PaperExperimentRevision,
    SourceReference,
)


def _experiment() -> PaperExperimentRevision:
    return PaperExperimentRevision(
        experiment_id="exp-1",
        document_id="doc-1",
        experiment_version=1,
        source_fingerprint="prep-1",
        label="Preheat tensile series",
        scope_description="A, B, and C under one tensile method",
        design_type="parallel",
        identity_status="identified",
        binding_status="bound",
        variants=tuple(
            ExperimentalVariant(key, label)
            for key, label in (("A", "NP"), ("B", "P150"), ("C", "P200"))
        ),
        test_conditions=(ExperimentTestCondition("tensile-1", "tensile"),),
        measurements=tuple(
            ExperimentMeasurementResult(
                measurement_key=key,
                outcome=outcome,
                variant_key=variant,
                test_key="tensile-1",
                value=value,
                unit=unit,
                binding_status="direct",
            )
            for key, outcome, variant, value, unit in (
                ("a-elongation", "elongation", "A", 72, "%"),
                ("b-elongation", "elongation", "B", 82, "%"),
                ("c-elongation", "elongation", "C", 85, "%"),
                ("a-strength", "yield_strength", "A", 500, "MPa"),
            )
        ),
    )


def _comparison(*, outcome="elongation", target="b-elongation"):
    return ExperimentComparison(
        comparison_key="a-to-b",
        baseline_variant_key="A",
        target_variant_key="B",
        outcome=outcome,
        baseline_measurement_keys=("a-elongation",),
        target_measurement_keys=(target,),
    )


def test_revision_preserves_multi_variant_multi_outcome_table() -> None:
    experiment = _experiment()
    assert [item.variant_key for item in experiment.variants] == ["A", "B", "C"]
    assert {item.outcome for item in experiment.measurements} == {
        "elongation",
        "yield_strength",
    }


def test_measurement_cannot_reference_variant_outside_revision() -> None:
    experiment = _experiment()
    with pytest.raises(ValueError, match="variant outside"):
        replace(
            experiment,
            measurements=(
                replace(experiment.measurements[0], variant_key="missing"),
                *experiment.measurements[1:],
            ),
        )


def test_duplicate_variant_keys_are_rejected() -> None:
    experiment = _experiment()
    with pytest.raises(ValueError, match="variant keys must be unique"):
        replace(
            experiment,
            variants=(*experiment.variants, ExperimentalVariant("A", "duplicate")),
        )


def test_comparison_must_use_same_outcome_measurements() -> None:
    with pytest.raises(ValueError, match="share the comparison outcome"):
        replace(_experiment(), comparisons=(_comparison(target="a-strength"),))


def test_comparison_accepts_unit_annotation_difference_in_outcome_labels() -> None:
    experiment = _experiment()
    revision = replace(
        experiment,
        measurements=(
            replace(experiment.measurements[0], outcome="elongation (%)"),
            *experiment.measurements[1:],
        ),
        comparisons=(_comparison(),),
    )
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
    measurement_outcome, comparison_outcome
) -> None:
    experiment = _experiment()
    revision = replace(
        experiment,
        measurements=(
            replace(experiment.measurements[0], outcome=measurement_outcome),
            replace(experiment.measurements[1], outcome=measurement_outcome),
            *experiment.measurements[2:],
        ),
        comparisons=(_comparison(outcome=comparison_outcome),),
    )
    assert revision.comparisons[0].outcome == comparison_outcome


def test_non_unit_qualifier_is_not_dropped_from_outcome_label() -> None:
    experiment = _experiment()
    with pytest.raises(ValueError, match="share the comparison outcome"):
        replace(
            experiment,
            measurements=(
                replace(experiment.measurements[0], outcome="strength (tensile)"),
                replace(experiment.measurements[1], outcome="strength (tensile)"),
                *experiment.measurements[2:],
            ),
            comparisons=(_comparison(outcome="strength"),),
        )


@pytest.mark.parametrize(
    ("measurement_outcome", "comparison_outcome"),
    [("tensile strength", "strength"), ("test temperature", "temperature")],
)
def test_comparison_rejects_different_outcomes_with_shared_tokens(
    measurement_outcome, comparison_outcome
) -> None:
    experiment = _experiment()
    with pytest.raises(ValueError, match="share the comparison outcome"):
        replace(
            experiment,
            measurements=(
                replace(experiment.measurements[0], outcome=measurement_outcome),
                *experiment.measurements[1:],
            ),
            comparisons=(_comparison(outcome=comparison_outcome),),
        )


def test_reported_result_can_preserve_non_numeric_text_and_unresolved_issue() -> None:
    experiment = _experiment()
    experiment = replace(
        experiment,
        measurements=(
            *experiment.measurements,
            ExperimentMeasurementResult(
                measurement_key="b-text",
                outcome="fracture_mode",
                variant_key="B",
                test_key="tensile-1",
                result_text="ductile-looking fracture",
            ),
        ),
        unresolved_issues=(
            {
                "target_ref": "measurements/b-text",
                "description": "test temperature unknown",
            },
        ),
    )
    assert experiment.measurements[-1].value is None
    assert experiment.measurements[-1].result_text == "ductile-looking fracture"
    assert experiment.unresolved_issues[0]["target_ref"] == "measurements/b-text"


def test_broad_variant_and_test_metadata_remain_auditable() -> None:
    experiment = _experiment()
    source = SourceReference(
        document_id="doc-1",
        source_fingerprint="prep-1",
        source_kind="section",
        source_ref="methods-1",
        quote="Mechanical tests were reported for as-SLM samples.",
    )
    variant = replace(
        experiment.variants[0],
        variant_label="as-SLM",
        identity_specificity="partial",
        missing_dimensions=("laser power", "scan speed"),
        identity_evidence=("methods-1",),
        source_refs=(source,),
    )
    test = replace(
        experiment.test_conditions[0],
        test_type="mechanical test",
        protocol_specificity="partial",
        test_identity_status="category",
        protocol_completeness="partial",
        missing_parameters=("standard", "strain rate"),
        method="mechanical test",
        outcome_scope=("elongation", "yield_strength"),
        protocol_evidence=("methods-1",),
        source_refs=(source,),
        binding_source_refs=(source,),
    )
    revision = replace(
        experiment,
        variants=(variant, *experiment.variants[1:]),
        test_conditions=(test,),
    )
    assert revision.variants[0].identity_specificity == "partial"
    assert variant.missing_dimensions == ("laser power", "scan speed")
    assert variant.identity_evidence == ("methods-1",)
    assert test.protocol_specificity == "partial"
    assert test.test_identity_status == "category"
    assert test.protocol_completeness == "partial"
    assert test.missing_parameters == ("standard", "strain rate")
    assert test.outcome_scope == ("elongation", "yield_strength")
    assert test.protocol_evidence == ("methods-1",)
    assert test.binding_source_refs == (source,)


def test_missing_specificity_defaults_to_unknown_instead_of_claiming_exact() -> None:
    experiment = _experiment()
    assert experiment.variants[0].identity_specificity == "unknown"
    assert experiment.test_conditions[0].protocol_specificity == "unknown"
    assert experiment.test_conditions[0].protocol_completeness == "unknown"
