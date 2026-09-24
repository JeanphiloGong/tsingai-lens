from __future__ import annotations

from dataclasses import replace

from application.core.objectives.analysis.paper_experiment import (
    assemble_paper_experiment,
    assemble_paper_experiments,
)
from application.core.objectives.analysis.paper_experiment_revision_converter import (
    convert_paper_experiment,
    stable_experiment_id,
)
from domain.core.research_process import SourceObservation


def _observation(
    observation_id: str,
    *,
    objective_id: str = "objective-1",
    value: float,
    label: str,
    derived_from: tuple[str, ...] = (),
    comparison: dict | None = None,
) -> SourceObservation:
    return SourceObservation.from_mapping(
        {
            "observation_id": observation_id,
            "collection_id": "collection-1",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "observation_role": "direct_result",
            "source_excerpt": f"{label}: elongation {value}%",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "source_excerpt": f"{label}: elongation {value}%",
                }
            ],
            "confidence": 0.9,
            "status": "validated",
            "scientific_context": {
                "material": [{"name": "alloy", "value": "316L"}],
                "sample": [{"name": "group", "value": label}],
                "process": [{"name": "preheat", "value": label}],
                "test": [{"name": "method", "value": "tensile"}],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": value,
                "unit": "%",
                "direction": "unknown",
                "result_text": f"{label}: elongation {value}%",
            },
            "derived_from_observation_ids": list(derived_from),
            "comparison": comparison,
        }
    )


def test_conversion_preserves_multidimensional_records_and_reported_comparison() -> None:
    baseline = _observation("np", value=72, label="NP")
    target = _observation("p150", value=82, label="P150")
    contrast = _observation(
        "contrast",
        value=82,
        label="P150",
        derived_from=("np", "p150"),
        comparison={
            "baseline_label": "NP",
            "target_label": "P150",
            "axis_names": ["preheat"],
            "comparable": True,
        },
    )
    legacy = assemble_paper_experiment(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(baseline, target, contrast),
    )

    converted = convert_paper_experiment(
        legacy,
        source_fingerprint="prepared-v1",
    )
    revision = converted.revision

    assert revision.experiment_id == stable_experiment_id(legacy)
    assert revision.document_id == "paper-1"
    assert len(revision.variants) == 2
    assert len(revision.measurements) == 2
    assert len(revision.comparisons) == 1
    comparison = revision.comparisons[0]
    assert comparison.status == "ready"
    assert comparison.baseline_measurement_keys
    assert comparison.target_measurement_keys
    assert revision.reported_interpretations[0].statement.endswith("82%")
    assert revision.source_refs[0].source_fingerprint == "prepared-v1"


def test_conversion_expands_inline_reported_endpoints_into_comparison() -> None:
    inline = _observation(
        "inline",
        value=82,
        label="P150",
        comparison={
            "baseline_label": "NP",
            "target_label": "P150",
            "axis_names": ["preheat"],
            "comparable": True,
        },
    )
    inline = SourceObservation.from_mapping(
        {
            **inline.to_record(),
            "changed_variables": [
                {
                    "name": "preheat",
                    "baseline_value": 0,
                    "target_value": 150,
                    "unit": "C",
                }
            ],
            "attribution_scope": "isolated_effect",
            "reported_result": {
                **inline.reported_result.to_record(),
                "baseline_value": 72,
                "target_value": 82,
            },
        }
    )
    legacy = assemble_paper_experiment(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(inline,),
    )

    revision = convert_paper_experiment(
        legacy,
        source_fingerprint="prepared-v1",
    ).revision

    assert len(revision.measurements) == 2
    assert {item.value for item in revision.measurements} == {72, 82}
    assert len(revision.comparisons) == 1
    comparison = revision.comparisons[0]
    assert comparison.basis == "reported"
    assert comparison.status == "ready"
    assert comparison.direction == "increase"
    assert comparison.baseline_measurement_keys != comparison.target_measurement_keys


def test_identity_does_not_change_when_only_objective_context_changes() -> None:
    first = _observation("np", objective_id="objective-a", value=72, label="NP")
    second = _observation("p150", objective_id="objective-a", value=82, label="P150")
    first_experiment = assemble_paper_experiment(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(first, second),
    )
    other_first = replace(first, objective_id="objective-b")
    other_second = replace(second, objective_id="objective-b")
    other_experiment = assemble_paper_experiment(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(other_first, other_second),
    )

    assert stable_experiment_id(first_experiment) == stable_experiment_id(other_experiment)


def test_identity_distinguishes_explicit_result_series_from_one_source() -> None:
    built = _observation("built", value=72, label="as-built")
    fabricated = _observation("fabricated", value=82, label="as-fabricated")
    experiments = assemble_paper_experiments(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(built, fabricated),
    )

    assert len(experiments) == 2
    assert len({stable_experiment_id(item) for item in experiments}) == 2


def test_identity_does_not_change_when_same_series_gains_an_outcome() -> None:
    elongation = _observation("elongation", value=72, label="as-built")
    hardness = SourceObservation.from_mapping(
        {
            **elongation.to_record(),
            "observation_id": "hardness",
            "source_excerpt": "as-built: hardness 320 HV",
            "reported_result": {
                "outcome": "hardness",
                "value": 320,
                "unit": "HV",
                "direction": "unknown",
                "result_text": "as-built: hardness 320 HV",
            },
        }
    )
    initial = assemble_paper_experiment(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(elongation,),
    )
    enriched = assemble_paper_experiment(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(elongation, hardness),
    )

    assert stable_experiment_id(initial) == stable_experiment_id(enriched)


def test_conversion_keeps_missing_bindings_as_partial_revision() -> None:
    observation = _observation("one", value=72, label="unknown")
    experiment = assemble_paper_experiment(
        collection_id="collection-1",
        document_id="paper-1",
        source_facts=(observation,),
    )

    revision = convert_paper_experiment(
        experiment,
        source_fingerprint="prepared-v1",
    ).revision

    assert revision.binding_status in {"partial", "bound"}
    assert revision.measurements
    assert all(item.source_refs for item in revision.measurements)
