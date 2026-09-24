"""Publish a Finding from explicit experiment selections."""

from __future__ import annotations

from dataclasses import dataclass

from application.repositories.comparison_group_repository import ComparisonGroupRepository
from application.repositories.experiment_finding_repository import (
    ExperimentFindingRepository,
)
from application.repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from domain.core.comparison_group import ComparisonGroup
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection


@dataclass(frozen=True)
class PublishedExperimentFinding:
    finding: Finding
    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]


class ExperimentFindingPublisher:
    """Coordinate references; the repository owns the atomic write."""

    def __init__(
        self,
        selection_repository: ObjectiveExperimentSelectionRepository,
        group_repository: ComparisonGroupRepository,
        finding_repository: ExperimentFindingRepository,
    ) -> None:
        self.selection_repository = selection_repository
        self.group_repository = group_repository
        self.finding_repository = finding_repository

    async def publish(self, finding: Finding) -> PublishedExperimentFinding:
        if finding.paper_contributions:
            raise ValueError("experiment-backed Finding cannot use legacy evidence")
        if not finding.selection_ids:
            raise ValueError("Finding requires at least one experiment selection")

        selections: list[ObjectiveExperimentSelection] = []
        for selection_id in finding.selection_ids:
            selection = await self.selection_repository.read_selection(
                finding.collection_id,
                selection_id,
            )
            if selection is None:
                raise ValueError(f"unknown experiment selection: {selection_id}")
            if (
                selection.objective_id != finding.objective_id
                or selection.analysis_version != finding.analysis_version
                or selection.outcome != finding.outcome
            ):
                raise ValueError("Finding selections do not match its analysis and outcome")
            selections.append(selection)

        groups: list[ComparisonGroup] = []
        for group_id in finding.comparison_group_ids:
            group = await self.group_repository.read_group(
                finding.collection_id,
                group_id,
            )
            if group is None:
                raise ValueError(f"unknown comparison group: {group_id}")
            if (
                group.objective_id != finding.objective_id
                or group.analysis_version != finding.analysis_version
                or group.outcome != finding.outcome
            ):
                raise ValueError("Finding groups do not match its analysis and outcome")
            member_ids = {member.selection_id for member in group.members}
            if not set(finding.selection_ids) <= member_ids:
                raise ValueError("Finding selection is not included in its group")
            groups.append(group)

        experiment_ids = {item.experiment_id for item in selections}
        if len(experiment_ids) > 1 and not groups:
            raise ValueError("cross-paper Finding requires a ComparisonGroup")
        if len(experiment_ids) == 1 and finding.synthesis_status != "single_study":
            raise ValueError("one experiment must use single_study synthesis status")
        if len(experiment_ids) > 1 and finding.synthesis_status == "single_study":
            raise ValueError("multiple experiments cannot use single_study status")

        stored = await self.finding_repository.add_finding(finding)
        return PublishedExperimentFinding(
            finding=stored,
            selections=tuple(selections),
            groups=tuple(groups),
        )


__all__ = ["ExperimentFindingPublisher", "PublishedExperimentFinding"]
