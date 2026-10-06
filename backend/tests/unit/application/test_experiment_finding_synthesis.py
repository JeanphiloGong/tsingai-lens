from __future__ import annotations

from application.core.objectives.analysis.experiment_finding_synthesis import (
    ExperimentFindingSynthesisService,
)
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import PaperExperimentRevision
from domain.core.research_objective import ResearchObjective


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "Does preheat affect elongation?",
            "material_scope": ["316L"],
            "variables": ["preheat"],
            "outcomes": ["elongation"],
            "confirmation_status": "confirmed",
        }
    )


def _revision(
    experiment_id: str,
    document_id: str,
    *,
    direction: str = "increase",
    unit: str = "%",
    test_type: str = "tensile",
    test_temperature: int = 25,
    alloy: str = "316L",
    factors: tuple[str, ...] = ("preheat",),
    binding_status: str = "bound",
    protocol_completeness: str = "complete",
    missing_parameters: tuple[str, ...] = (),
) -> PaperExperimentRevision:
    source = {
        "document_id": document_id,
        "source_fingerprint": f"prepared-{document_id}",
        "source_kind": "table",
        "source_ref": "table-2",
        "quote": "NP 72; P150 82",
    }
    variables = [
        {
            "name": name,
            "baseline_value": 0,
            "target_value": 150 if name == "preheat" else 1000,
            "unit": "C" if name == "preheat" else "mm/s",
        }
        for name in factors
    ]
    attribution = "isolated_effect" if len(factors) == 1 else "joint_effect"
    return PaperExperimentRevision.from_mapping(
        {
            "experiment_id": experiment_id,
            "document_id": document_id,
            "experiment_version": 1,
            "source_fingerprint": f"prepared-{document_id}",
            "label": "Preheat tensile series",
            "scope_description": "NP and P150 tensile results",
            "design_type": "parallel",
            "identity_status": "identified",
            "binding_status": binding_status,
            "variants": [
                {
                    "variant_key": "np",
                    "variant_label": "NP",
                    "subject_attributes": [{"name": "alloy", "value": alloy}],
                    "intervention_attributes": [
                        {"name": "preheat", "value": 0, "unit": "C"}
                    ],
                    "binding_status": "direct",
                },
                {
                    "variant_key": "p150",
                    "variant_label": "P150",
                    "subject_attributes": [{"name": "alloy", "value": alloy}],
                    "intervention_attributes": [
                        {"name": "preheat", "value": 150, "unit": "C"}
                    ],
                    "binding_status": "direct",
                },
            ],
            "test_conditions": [
                {
                    "test_key": "tensile",
                    "test_type": test_type,
                    "parameters": [
                        {
                            "name": "temperature",
                            "value": test_temperature,
                            "unit": "C",
                        }
                    ],
                    "protocol_completeness": protocol_completeness,
                    "missing_parameters": list(missing_parameters),
                    "binding_status": "direct",
                }
            ],
            "measurements": [
                {
                    "measurement_key": "m-np",
                    "outcome": "elongation",
                    "variant_key": "np",
                    "test_key": "tensile",
                    "value": 72,
                    "unit": unit,
                    "binding_status": "direct",
                },
                {
                    "measurement_key": "m-p150",
                    "outcome": "elongation",
                    "variant_key": "p150",
                    "test_key": "tensile",
                    "value": 82,
                    "unit": unit,
                    "binding_status": "direct",
                },
            ],
            "comparisons": [
                {
                    "comparison_key": "c-preheat",
                    "baseline_variant_key": "np",
                    "target_variant_key": "p150",
                    "outcome": "elongation",
                    "baseline_measurement_keys": ["m-np"],
                    "target_measurement_keys": ["m-p150"],
                    "changed_variables": variables,
                    "basis": "reported",
                    "direction": direction,
                    "attribution_scope": attribution,
                    "status": "ready",
                    "relation_status": "direct",
                    "source_refs": [source],
                    "binding_source_refs": [source],
                }
            ],
            "source_refs": [source],
        }
    )


def _selection(experiment_id: str, suffix: str) -> ObjectiveExperimentSelection:
    return ObjectiveExperimentSelection.from_mapping(
        {
            "selection_id": f"selection-{suffix}",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "experiment_id": experiment_id,
            "experiment_version": 1,
            "outcome": "elongation",
            "measurement_keys": ["m-np", "m-p150"],
            "comparison_keys": ["c-preheat"],
        }
    )


def _synthesize(revisions, selections):
    return ExperimentFindingSynthesisService().synthesize(
        collection_id="collection-1",
        objective=_objective(),
        analysis_version=1,
        revisions=revisions,
        selections=selections,
    )


def test_synthesizes_single_study_finding_from_selected_comparison() -> None:
    result = _synthesize(
        (_revision("experiment-a", "paper-a"),),
        (_selection("experiment-a", "a"),),
    )

    assert result.groups == ()
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.selection_ids == ("selection-a",)
    assert finding.factors == ("preheat",)
    assert finding.outcome == "elongation"
    assert finding.direction == "increase"
    assert finding.synthesis_status == "single_study"
    assert finding.assertion_strength == "associative"
    assert finding.paper_contributions == ()


def test_partial_protocol_remains_eligible_but_limits_finding() -> None:
    result = _synthesize(
        (
            _revision(
                "experiment-a",
                "paper-a",
                protocol_completeness="partial",
                missing_parameters=("fixture alignment",),
            ),
        ),
        (_selection("experiment-a", "a"),),
    )

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.selection_ids == ("selection-a",)
    assert finding.certainty == 0.6
    assert any("protocol" in item.casefold() for item in finding.limitations)


def test_groups_aligned_cross_paper_comparisons_and_reports_agreement() -> None:
    result = _synthesize(
        (
            _revision("experiment-a", "paper-a"),
            _revision("experiment-b", "paper-b"),
        ),
        (
            _selection("experiment-a", "a"),
            _selection("experiment-b", "b"),
        ),
    )

    assert len(result.groups) == 1
    assert result.groups[0].status == "comparable"
    assert len(result.groups[0].members) == 2
    assert len(result.findings) == 1
    assert result.findings[0].synthesis_status == "agreement"
    assert result.findings[0].comparison_group_ids == (result.groups[0].group_id,)


def test_preserves_condition_dependent_directions_without_claiming_conflict() -> None:
    result = _synthesize(
        (
            _revision("experiment-a", "paper-a", direction="increase"),
            _revision(
                "experiment-b",
                "paper-b",
                direction="decrease",
                test_temperature=200,
            ),
        ),
        (
            _selection("experiment-a", "a"),
            _selection("experiment-b", "b"),
        ),
    )

    assert result.groups[0].status == "conditional"
    finding = result.findings[0]
    assert finding.direction == "mixed"
    assert finding.synthesis_status == "condition_dependent"
    assert any("Test parameters differ" in item for item in finding.limitations)


def test_keeps_joint_changes_out_of_single_factor_causation() -> None:
    result = _synthesize(
        (
            _revision(
                "experiment-a",
                "paper-a",
                factors=("preheat", "scan speed"),
            ),
        ),
        (_selection("experiment-a", "a"),),
    )

    finding = result.findings[0]
    assert finding.factors == ("preheat", "scan speed")
    assert finding.attribution_scope == "joint_effect"
    assert finding.assertion_strength == "associative"
    assert any("Multiple factors changed together" in item for item in finding.limitations)


def test_does_not_merge_incompatible_methods_or_invent_measurement_only_finding() -> None:
    measurement_only = ObjectiveExperimentSelection.from_mapping(
        {
            "selection_id": "selection-measurement",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "experiment_id": "experiment-c",
            "experiment_version": 1,
            "outcome": "elongation",
            "measurement_keys": ["m-np", "m-p150"],
        }
    )
    result = _synthesize(
        (
            _revision("experiment-a", "paper-a", test_type="tensile"),
            _revision("experiment-b", "paper-b", test_type="nanoindentation"),
            _revision("experiment-c", "paper-c"),
        ),
        (
            _selection("experiment-a", "a"),
            _selection("experiment-b", "b"),
            measurement_only,
        ),
    )

    assert result.groups == ()
    assert len(result.findings) == 2
    assert all(item.synthesis_status == "single_study" for item in result.findings)
    assert all("selection-measurement" not in item.selection_ids for item in result.findings)


def test_matches_non_ascii_objective_terms_without_dropping_them() -> None:
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "预热是否影响延伸率？",
            "variables": ["预热"],
            "outcomes": ["elongation"],
            "confirmation_status": "confirmed",
        }
    )
    revision = _revision(
        "experiment-a",
        "paper-a",
        factors=("预热",),
    )

    result = ExperimentFindingSynthesisService().synthesize(
        collection_id="collection-1",
        objective=objective,
        analysis_version=1,
        revisions=(revision,),
        selections=(_selection("experiment-a", "a"),),
    )

    assert result.findings[0].factors == ("预热",)
