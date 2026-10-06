import pytest

from domain.core.objective_experiment_selection import ObjectiveExperimentSelection


def test_selection_keeps_fixed_version_and_explicit_result_keys() -> None:
    selection = ObjectiveExperimentSelection.from_mapping(
        {
            "selection_id": "sel-1",
            "objective_id": "obj-1",
            "analysis_version": 2,
            "experiment_id": "exp-1",
            "experiment_version": 3,
            "outcome": "elongation",
            "measurement_keys": ["m2", "m1", "m1"],
            "missing_context": ["test temperature"],
        }
    )

    assert selection.experiment_version == 3
    assert selection.measurement_keys == ("m2", "m1")
    assert selection.comparison_keys == ()


def test_selection_requires_at_least_one_explicit_result() -> None:
    with pytest.raises(ValueError, match="measurements or comparisons"):
        ObjectiveExperimentSelection(
            selection_id="sel-1",
            objective_id="obj-1",
            analysis_version=1,
            experiment_id="exp-1",
            experiment_version=1,
            outcome="elongation",
        )
