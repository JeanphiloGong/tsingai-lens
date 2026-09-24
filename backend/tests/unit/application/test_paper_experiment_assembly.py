from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.paper_experiment import (
    _bind_unambiguous_document_context,
    assemble_paper_experiment,
    assemble_paper_experiments,
    reconstruct_paper_experiments,
)
from application.core.objectives.analysis.source_extraction import (
    EvidenceExtractionsModelOutput,
    SourceObservation,
    SourceReadAudit,
    _extract_source_round,
    _failed_source_read,
)
from domain.core import ResearchObjective, ScientificAttribute
from domain.source import SourceTable


def test_assembly_keeps_source_result_and_marks_missing_conditions_incomplete() -> None:
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "ev-1",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "evidence_role": "direct_result",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-2",
                    "source_excerpt": "Elongation: 82%",
                }
            ],
            "reported_result": {
                "outcome": "elongation",
                "value": 82,
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation was 82%.",
            },
            "scientific_context": {},
            "confidence": 0.9,
        }
    )

    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(draft,),
    )

    assert experiment.status == "incomplete"
    assert experiment.has_measurements
    assert not experiment.has_bound_measurements
    assert "Test conditions remain unresolved" in experiment.uncertainties[0]
    assert experiment.source_observations[0].status == "unvalidated"


def _observation(identifier: str, **fields) -> SourceObservation:
    return SourceObservation.from_mapping(
        {
            "observation_id": identifier,
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "observation_role": "direct_result",
            "source_excerpt": "NP: elongation 72%; P150: elongation 82%.",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-2",
                    "source_excerpt": "NP: elongation 72%; P150: elongation 82%.",
                }
            ],
            "confidence": 0.9,
            "status": "validated",
            "reported_result": {
                "outcome": "elongation",
                "value": 82,
                "unit": "%",
                "direction": "unknown",
                "result_text": "P150: elongation 82%.",
            },
            **fields,
        }
    )


@pytest.mark.parametrize(
    "status", ["unvalidated", "validated", "uncertain", "rejected"]
)
def test_assembly_preserves_observation_validation_and_lineage(status: str) -> None:
    observation = _observation("obs-p150", status=status, resolution_status="partial")
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(observation,),
    )
    assert experiment.source_observations == (observation,)


def test_assembly_does_not_bind_hardness_conditions_to_tensile_result() -> None:
    tensile = _observation("obs-tensile", status="uncertain")
    hardness = _observation(
        "obs-hardness",
        reported_result=None,
        observation_role="condition_context",
        scientific_context={
            "sample": [{"name": "sample", "value": "B"}],
            "test": [
                {
                    "name": "hardness load",
                    "value": 10,
                    "unit": "N",
                    "applies_to_outcomes": ["hardness"],
                }
            ],
        },
    )
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(tensile, hardness),
    )
    assert experiment.status == "incomplete"


def test_different_outcomes_from_one_source_share_the_parent_experiment() -> None:
    elongation = _observation("obs-elongation")
    hardness = replace(
        elongation,
        observation_id="obs-hardness",
        reported_result=replace(
            elongation.reported_result,
            outcome="hardness",
            value=320,
            unit="HV",
            result_text="Hardness was 320 HV.",
        ),
    )

    experiments = assemble_paper_experiments(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(elongation, hardness),
    )

    assert len(experiments) == 1
    assert {item.property_normalized for item in experiments[0].measurements} == {
        "elongation",
        "hardness",
    }


def test_different_tables_and_tests_share_the_parent_experiment() -> None:
    first = _p002_result("obs-a", "A", 72)
    second_context = _p002_result("context-b", "B", 82).scientific_context
    second = replace(
        _p002_result("obs-b", "B", 82),
        source_ref="table-3",
        source_refs=(
            {
                "source_kind": "table",
                "source_ref": "table-3",
                "source_excerpt": "B: elongation 82%",
            },
        ),
        scientific_context=replace(
            second_context,
            test=(replace(second_context.test[0], value=0.1),),
        ),
    )

    experiments = assemble_paper_experiments(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(first, second),
    )

    assert len(experiments) == 1
    assert {item.value_payload["value"] for item in experiments[0].measurements} == {
        72,
        82,
    }


def test_conflicting_values_from_different_sources_are_retained() -> None:
    first = _p002_result("obs-first", "NP", 72)
    second = replace(
        _p002_result("obs-second", "NP", 75),
        source_kind="text_window",
        source_ref="results-text",
        source_refs=(
            {
                "source_kind": "text_window",
                "source_ref": "results-text",
                "source_excerpt": "NP elongation was 75%.",
            },
        ),
    )

    experiments = assemble_paper_experiments(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(first, second),
    )

    assert len(experiments) == 1
    experiment = experiments[0]
    assert [item.value_payload["value"] for item in experiment.measurements] == [72, 75]
    assert {item.result_id for item in experiment.measurements} == {
        "obs-first",
        "obs-second",
    }
    assert {item.source_ref for item in experiment.source_observations} == {
        "table-2",
        "results-text",
    }


def test_derived_comparison_is_not_another_measured_result() -> None:
    baseline = _observation("obs-np")
    target = _observation("obs-p150")
    contrast = SourceObservation.from_mapping(
        {
            **target.to_record(),
            "observation_id": "cmp-np-p150",
            "derived_from_observation_ids": [
                baseline.observation_id,
                target.observation_id,
            ],
        }
    )
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(baseline, target, contrast),
    )
    assert {item.result_id for item in experiment.measurements} == {
        "obs-np",
        "obs-p150",
    }


def _group_context(
    identifier: str,
    sample: str,
    *,
    method: str | None = "Archimedes method",
    applies_to_outcomes: list[str] | None = None,
    source_ref: str | None = None,
) -> SourceObservation:
    source_ref = source_ref or f"methods-{sample}"
    test = (
        [
            {
                "name": "density measurement method",
                "value": method,
                "context_scope": "experimental",
                "applies_to_outcomes": applies_to_outcomes or ["relative density"],
            }
        ]
        if method is not None
        else []
    )
    return SourceObservation.from_mapping(
        {
            "observation_id": identifier,
            "collection_id": "col-1",
            "objective_id": "obj-density",
            "document_id": "doc-density",
            "source_kind": "text_window",
            "source_ref": source_ref,
            "observation_role": "condition_context",
            "source_excerpt": f"Group {sample} was tested.",
            "scientific_context": {
                "sample": [{"name": "sample", "value": sample}],
                "test": test,
            },
            "source_refs": [
                {"source_kind": "text_window", "source_ref": source_ref}
            ],
            "confidence": 0.9,
        }
    )


def _density_result() -> SourceObservation:
    return SourceObservation.from_mapping(
        {
            "observation_id": "density-result",
            "collection_id": "col-1",
            "objective_id": "obj-density",
            "document_id": "doc-density",
            "source_kind": "table",
            "source_ref": "table-density",
            "observation_role": "direct_result",
            "source_excerpt": "Relative density was 99.1%.",
            "reported_result": {
                "outcome": "relative density",
                "value": 99.1,
                "unit": "%",
                "direction": "unknown",
                "result_text": "Relative density was 99.1%.",
            },
            "source_refs": [
                {"source_kind": "table", "source_ref": "table-density"}
            ],
            "confidence": 0.9,
        }
    )


def test_consistent_group_test_context_binds_to_result_with_provenance() -> None:
    bound = _bind_unambiguous_document_context(
        (
            _group_context("context-a", "A"),
            _group_context("context-b", "B"),
            _density_result(),
        )
    )

    result = next(item for item in bound if item.observation_id == "density-result")
    assert [item.to_record() for item in result.scientific_context.test] == [
        {
            "name": "density measurement method",
            "value": "Archimedes method",
            "unit": None,
            "context_scope": "experimental",
            "applies_to_outcomes": ["relative density"],
        }
    ]
    refs = {
        ref["source_ref"]: set(ref.get("supports", ()))
        for ref in result.source_refs
    }
    assert refs["methods-A"] >= {"scientific_context.test"}
    assert refs["methods-B"] >= {"scientific_context.test"}


@pytest.mark.parametrize(
    "contexts",
    [
        (
            _group_context("context-a", "A", method="Archimedes method"),
            _group_context("context-b", "B", method="helium pycnometry"),
        ),
        (
            _group_context("context-a", "A"),
            _group_context("context-b", "B", method=None),
        ),
        (
            _group_context(
                "context-a", "A", applies_to_outcomes=["relative density"]
            ),
            _group_context("context-b", "B", applies_to_outcomes=["hardness"]),
        ),
    ],
    ids=["conflicting-values", "missing-group-context", "conflicting-outcomes"],
)
def test_inconsistent_group_test_context_stays_unresolved(
    contexts: tuple[SourceObservation, SourceObservation],
) -> None:
    bound = _bind_unambiguous_document_context((*contexts, _density_result()))

    result = next(item for item in bound if item.observation_id == "density-result")
    assert result.scientific_context.test == ()
    assert all(
        ref["source_ref"] not in {"methods-A", "methods-B"}
        for ref in result.source_refs
    )


def _p002_result(identifier: str, sample: str, value: float) -> SourceObservation:
    return _observation(
        identifier,
        reported_result={
            "outcome": "elongation",
            "value": value,
            "unit": "%",
            "direction": "unknown",
            "result_text": f"{sample}: {value}%",
        },
        scientific_context={
            "material": [{"name": "alloy", "value": "316L"}],
            "sample": [{"name": "sample", "value": sample}],
            "process": [{"name": "manufacturing process", "value": "LPBF"}],
            "test": [
                {
                    "name": "strain rate",
                    "value": 0.001,
                    "unit": "s^-1",
                    "applies_to_outcomes": ["elongation"],
                }
            ],
        },
    )


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "question": "How does platform preheating affect elongation?",
            "variables": ["platform preheating"],
            "outcomes": ["elongation"],
            "material_scope": ["316L"],
        }
    )


def test_p002_measurements_bind_to_their_own_specimens_and_tests() -> None:
    np = _p002_result("obs-np", "NP", 72)
    p150 = _p002_result("obs-p150", "P150", 82)
    experiments = assemble_paper_experiments(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(np, p150),
    )
    assert len(experiments) == 1
    experiment = experiments[0]
    assert experiment.has_bound_measurements
    variants = {item.variant_id: item for item in experiment.sample_variants}
    tests = {item.test_condition_id: item for item in experiment.test_conditions}
    assert [
        variants[item.variant_id].variant_label for item in experiment.measurements
    ] == ["NP", "P150"]
    assert [
        tests[item.test_condition_id].property_type for item in experiment.measurements
    ] == ["elongation", "elongation"]
    # Binding does not imply that all test conditions were reported.
    assert all(
        item.condition_completeness == "partial" for item in experiment.test_conditions
    )


def test_reported_sample_state_becomes_the_measurement_variant() -> None:
    observation = _observation(
        "obs-as-built",
        reported_result={
            "outcome": "porosity",
            "value": 0.8,
            "baseline_value": 2.4,
            "target_value": 0.8,
            "unit": "%",
            "direction": "decrease",
            "result_text": "Porosity decreased from 2.4% to 0.8%.",
        },
        scientific_context={
            "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
            "sample": [{"name": "sample state", "value": "as-built"}],
            "process": [{"name": "process", "value": "LPBF"}],
            "test": [
                {
                    "name": "method",
                    "value": "X-ray computed tomography",
                    "applies_to_outcomes": ["porosity"],
                }
            ],
        },
    )

    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(observation,),
    )

    assert experiment.status == "bound"
    assert experiment.has_bound_measurements
    assert experiment.sample_variants[0].variant_label == "as-built"
    assert (
        experiment.measurements[0].variant_id
        == experiment.sample_variants[0].variant_id
    )


def test_a_bound_series_without_a_supported_contrast_is_not_yet_comparable() -> None:
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(_p002_result("np", "NP", 72), _p002_result("p150", "P150", 82)),
    )
    assert (
        experiment.comparison_status(_objective(), "np", "p150")
        == "insufficient_context"
    )


def test_supported_p002_contrast_has_explicit_parent_measurements() -> None:
    baseline = _p002_result("np", "NP", 72)
    target = _p002_result("p150", "P150", 82)
    comparison = SourceObservation.from_mapping(
        {
            **target.to_record(),
            "observation_id": "contrast",
            "derived_from_observation_ids": ["np", "p150"],
            "changed_variables": [
                {
                    "name": "platform preheating",
                    "baseline_value": "without preheating",
                    "target_value": 150,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["platform preheating"],
                "comparable": True,
            },
        }
    )
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(baseline, target, comparison),
    )
    assert len(experiment.measurements) == 2
    assert all("baseline_id" not in item.to_record() for item in experiment.measurements)
    assert "baselines" not in experiment.to_record()
    assert (
        experiment.comparison_status(_objective(), "np", "p150") == "comparable"
    )
    contrast = next(
        item for item in experiment.source_observations if item.observation_id == "contrast"
    )
    assert contrast.derived_from_observation_ids == ("np", "p150")


def test_p004_treatment_states_and_source_disagreement_are_not_pooled() -> None:
    # P004 PDF p9 Table 3: 120 W / 100 mm/s elongations. Prose differs.
    context = {
        "material": [{"name": "alloy", "value": "316L"}],
        "sample": [{"name": "sample", "value": "120/100"}],
        "process": [
            {"name": "process", "value": "SLM"},
            {"name": "laser power", "value": 120, "unit": "W"},
            {"name": "scan speed", "value": 100, "unit": "mm/s"},
        ],
        "test": [
            {
                "name": "crosshead speed",
                "value": 0.005,
                "unit": "mm/s",
                "applies_to_outcomes": ["elongation"],
            }
        ],
    }
    raw = _observation(
        "as-slm",
        scientific_context=context,
        source_ref="table-3",
        source_excerpt="as-SLM(120/100) 35.0 (+/-9.6)",
        source_refs=[
            {
                "source_kind": "table",
                "source_ref": "table-3",
                "page": 9,
                "source_excerpt": "as-SLM(120/100) 35.0 (+/-9.6)",
            }
        ],
        reported_result={
            "outcome": "elongation",
            "value": 35.0,
            "unit": "%",
            "direction": "unknown",
            "result_text": "as-SLM(120/100) 35.0 (+/-9.6)",
        },
    )
    ht = replace(
        raw,
        observation_id="ht-slm",
        source_excerpt="HT-SLM(120/100) 51.2 (+/-5.0)",
        source_refs=(
            {
                "source_kind": "table",
                "source_ref": "table-3",
                "page": 9,
                "source_excerpt": "HT-SLM(120/100) 51.2 (+/-5.0)",
            },
        ),
        reported_result=replace(
            raw.reported_result, value=51.2, result_text="HT-SLM(120/100) 51.2 (+/-5.0)"
        ),
    )
    raw = replace(
        raw,
        scientific_context=replace(
            raw.scientific_context,
            sample=(
                *raw.scientific_context.sample,
                ScientificAttribute("state", "as-SLM"),
            ),
        ),
    )
    ht = replace(
        ht,
        scientific_context=replace(
            ht.scientific_context,
            sample=(
                *ht.scientific_context.sample,
                ScientificAttribute("state", "HT-SLM"),
            ),
        ),
    )
    prose = replace(
        raw,
        observation_id="prose-as-slm",
        source_kind="text_window",
        source_ref="p9-text",
        source_excerpt="The yield strengths and elongation were measured as 464.8 MPa and 32.8%",
        source_refs=(
            {
                "source_kind": "text_window",
                "source_ref": "p9-text",
                "page": 9,
                "source_excerpt": "The yield strengths and elongation were measured as 464.8 MPa and 32.8%",
            },
        ),
        reported_result=replace(raw.reported_result, value=32.8, result_text="32.8%"),
    )
    experiments = assemble_paper_experiments(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(raw, ht, prose),
    )
    assert len(experiments) == 2
    assert sorted(
        item.value_payload["value"] for exp in experiments for item in exp.measurements
    ) == [32.8, 35.0, 51.2]
    merged = next(exp for exp in experiments if len(exp.measurements) == 2)
    assert {
        item.value_payload["value"] for item in merged.measurements
    } == {32.8, 35.0}
    assert {item.unit for exp in experiments for item in exp.measurements} == {"%"}
    assert "9.6" in experiments[0].source_observations[0].reported_result.result_text


def test_same_paper_different_tests_are_not_declared_comparable() -> None:
    left = _p002_result("a", "A", 72)
    right = _p002_result("b", "B", 82)
    right = replace(
        right,
        scientific_context=replace(
            right.scientific_context,
            test=(replace(right.scientific_context.test[0], value=0.1),),
        ),
    )
    experiment = assemble_paper_experiment(
        collection_id="col-1", document_id="doc-1", source_facts=(left, right)
    )
    assert (
        experiment.comparison_status(_objective(), "a", "b") == "non_comparable"
    )


def test_unreported_test_field_is_missing_context_not_a_conflicting_test() -> None:
    left = _p002_result("a", "A", 72)
    right = _p002_result("b", "B", 82)
    right = replace(
        right,
        scientific_context=replace(
            right.scientific_context,
            test=(
                *right.scientific_context.test,
                ScientificAttribute("temperature", 25, "C"),
            ),
        ),
    )
    experiment = assemble_paper_experiment(
        collection_id="col-1", document_id="doc-1", source_facts=(left, right)
    )
    assert (
        experiment.comparison_status(_objective(), "a", "b") == "insufficient_context"
    )


def test_assembly_cannot_relabel_an_observation_from_another_collection() -> None:
    with pytest.raises(ValueError, match="collection"):
        assemble_paper_experiment(
            collection_id="col-other",
            document_id="doc-1",
            source_facts=(_p002_result("a", "A", 72),),
        )


def test_derived_contrast_joins_its_parent_series_despite_merged_sample_context() -> (
    None
):
    left = _p002_result("a", "NP", 72)
    right = _p002_result("b", "P150", 82)
    contrast = replace(
        right,
        observation_id="cmp",
        derived_from_observation_ids=("a", "b"),
        scientific_context=replace(right.scientific_context, sample=()),
    )
    experiments = assemble_paper_experiments(
        collection_id="col-1", document_id="doc-1", source_facts=(left, right, contrast)
    )
    assert len(experiments) == 1
    assert len(experiments[0].measurements) == 2
    assert len(experiments[0].source_observations) == 3


def test_missing_parent_is_not_silently_accepted_as_another_measurement() -> None:
    contrast = replace(
        _p002_result("cmp", "B", 82), derived_from_observation_ids=("unknown", "b")
    )
    with pytest.raises(ValueError, match="parent"):
        assemble_paper_experiments(
            collection_id="col-1", document_id="doc-1", source_facts=(contrast,)
        )


def test_different_research_question_cannot_reuse_comparison_assessment() -> None:
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(_p002_result("a", "A", 72), _p002_result("b", "B", 82)),
    )
    with pytest.raises(ValueError, match="objective"):
        experiment.comparison_status(
            replace(_objective(), objective_id="obj-other"), "a", "b"
        )


def test_measurement_cannot_reference_an_external_sample() -> None:
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(_p002_result("a", "A", 72),),
    )
    with pytest.raises(ValueError, match="outside its experiment"):
        replace(
            experiment,
            measurements=(replace(experiment.measurements[0], variant_id="unrelated"),),
        )


def test_bound_aggregate_round_trips_all_measurement_links_and_source_states() -> None:
    experiment = assemble_paper_experiment(
        collection_id="col-1",
        document_id="doc-1",
        source_facts=(_p002_result("a", "A", 72),),
    )
    assert type(experiment).from_mapping(experiment.to_record()) == experiment


def test_retained_p002_table_survives_read_and_bind_without_methods() -> None:
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "fixtures/agent_p002/source_document.json"
        ).read_text()
    )
    table = SourceTable.from_record(fixture["tables"][0])
    objective = _objective()
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": table.document_id,
            "source_kind": "table",
            "source_ref": table.table_id,
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )

    class EmptyModel:
        def extract_source(self, _payload):
            return EvidenceExtractionsModelOutput()

    read_audits = []
    observations = _extract_source_round(
        collection_id="col-1",
        read_audits=read_audits,
        source_extractor=EmptyModel(),
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={},
        tables_by_document_id={table.document_id: [table]},
        document_trees_by_document_id={},
    )
    facts = reconstruct_paper_experiments(
        collection_id="col-1", source_facts=observations, objectives=(objective,)
    )
    experiments = assemble_paper_experiments(
        collection_id="col-1", document_id=table.document_id, source_facts=facts
    )
    assert read_audits == []
    measured = [
        item
        for experiment in experiments
        for item in experiment.measurements
        if item.property_normalized == "elongation"
    ]
    assert [item.value_payload["value"] for item in measured] == [72, 82]
    assert all(item.epistemic_status == "validated" for item in measured)
    assert all(
        observation.source_refs
        for experiment in experiments
        for observation in experiment.source_observations
    )


def test_source_read_audits_are_not_scientific_observations() -> None:
    route = EvidenceCandidate.from_mapping(
        {
            "evidence_id": "failed-1",
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "evidence_role": "irrelevant",
            "selection_status": "failed",
            "failure_reason": "provider unavailable",
            "status": "rejected",
            "confidence": 0,
        }
    )

    audit = _failed_source_read(
        collection_id="col-1", route=route, error=RuntimeError("provider unavailable")
    )
    assert not isinstance(audit, SourceObservation)
    assert audit == (
        SourceReadAudit(
            collection_id="col-1",
            objective_id="obj-1",
            document_id="doc-1",
            source_kind="table",
            source_ref="table-1",
            disposition="technical_failure",
            reason="RuntimeError: provider unavailable",
        )
    )
