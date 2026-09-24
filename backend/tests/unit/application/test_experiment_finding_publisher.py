from __future__ import annotations

import pytest

from application.core.objectives.analysis.experiment_finding_publisher import (
    ExperimentFindingPublisher,
)
from domain.core import ComparisonGroup, ComparisonGroupMember, Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _Selections:
    def __init__(self, values):
        self.values = values

    async def read_selection(self, collection_id, selection_id):
        return self.values.get(selection_id)


class _Groups:
    def __init__(self, values):
        self.values = values

    async def read_group(self, collection_id, group_id):
        return self.values.get(group_id)


class _Findings:
    def __init__(self):
        self.items = []

    async def add_finding(self, finding):
        self.items.append(finding)
        return finding


def _selection(selection_id: str, experiment_id: str) -> ObjectiveExperimentSelection:
    return ObjectiveExperimentSelection.from_mapping(
        {
            "selection_id": selection_id,
            "objective_id": "objective-1",
            "analysis_version": 1,
            "experiment_id": experiment_id,
            "experiment_version": 1,
            "outcome": "elongation",
            "measurement_keys": ["m-1"],
        }
    )


def _finding(**overrides) -> Finding:
    payload = {
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "finding_id": "finding-1",
        "statement": "The selected experiment reports a change.",
        "factors": ["preheating"],
        "outcome": "elongation",
        "direction": "increase",
        "assertion_strength": "descriptive",
        "attribution_scope": "descriptive_only",
        "synthesis_status": "single_study",
        "certainty": 0.4,
        "display_rank": 0,
        "mechanisms": [],
        "scientific_context": {},
        "limitations": [],
        "paper_contributions": [],
        "selection_ids": ["selection-1"],
    }
    payload.update(overrides)
    return Finding.from_mapping(payload)


async def test_publisher_requires_group_for_cross_paper_finding() -> None:
    selections = {
        "selection-1": _selection("selection-1", "experiment-1"),
        "selection-2": _selection("selection-2", "experiment-2"),
    }
    findings = _Findings()
    publisher = ExperimentFindingPublisher(
        _Selections(selections),
        _Groups({}),
        findings,
    )

    with pytest.raises(ValueError, match="ComparisonGroup"):
        await publisher.publish(
            _finding(
                selection_ids=["selection-1", "selection-2"],
                synthesis_status="agreement",
            )
        )
    assert findings.items == []


async def test_publisher_persists_single_study_selection_without_group() -> None:
    findings = _Findings()
    publisher = ExperimentFindingPublisher(
        _Selections({"selection-1": _selection("selection-1", "experiment-1")}),
        _Groups({}),
        findings,
    )

    published = await publisher.publish(_finding())

    assert published.finding.selection_ids == ("selection-1",)
    assert published.groups == ()
    assert findings.items == [published.finding]
