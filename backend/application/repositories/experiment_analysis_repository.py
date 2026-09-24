"""Atomic write contract for one automatic experiment analysis graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from application.repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)
from domain.core.comparison_group import ComparisonGroup
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import PaperExperimentRevision


@dataclass(frozen=True)
class ExperimentAnalysisWrite:
    """Complete records that must commit or roll back as one analysis graph."""

    collection_id: str
    objective_id: str
    analysis_version: int
    revisions: tuple[PaperExperimentRevision, ...]
    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]
    created_by: str | None = None

    def __post_init__(self) -> None:
        if not self.collection_id.strip() or not self.objective_id.strip():
            raise ValueError("experiment analysis write requires collection and objective")
        if self.analysis_version < 1:
            raise ValueError("experiment analysis write requires a positive version")

        revision_keys = {
            (item.experiment_id, item.experiment_version) for item in self.revisions
        }
        if len(revision_keys) != len(self.revisions):
            raise ValueError("experiment analysis write contains duplicate revisions")

        selection_ids = {item.selection_id for item in self.selections}
        if len(selection_ids) != len(self.selections):
            raise ValueError("experiment analysis write contains duplicate selections")
        if any(
            item.objective_id != self.objective_id
            or item.analysis_version != self.analysis_version
            or (item.experiment_id, item.experiment_version) not in revision_keys
            for item in self.selections
        ):
            raise ValueError("experiment analysis selection is outside the write scope")

        group_ids = {item.group_id for item in self.groups}
        if len(group_ids) != len(self.groups):
            raise ValueError("experiment analysis write contains duplicate groups")
        if any(
            item.objective_id != self.objective_id
            or item.analysis_version != self.analysis_version
            or not {member.selection_id for member in item.members} <= selection_ids
            for item in self.groups
        ):
            raise ValueError("experiment analysis group is outside the write scope")

        finding_ids = {item.finding_id for item in self.findings}
        if len(finding_ids) != len(self.findings):
            raise ValueError("experiment analysis write contains duplicate findings")
        if any(
            item.collection_id != self.collection_id
            or item.objective_id != self.objective_id
            or item.analysis_version != self.analysis_version
            or not set(item.selection_ids) <= selection_ids
            or not set(item.comparison_group_ids) <= group_ids
            for item in self.findings
        ):
            raise ValueError("experiment analysis Finding is outside the write scope")


@dataclass(frozen=True)
class StoredExperimentAnalysis:
    revisions: tuple[StoredPaperExperimentRevision, ...]
    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]


class ExperimentAnalysisRepository(Protocol):
    async def write_graph(
        self,
        graph: ExperimentAnalysisWrite,
    ) -> StoredExperimentAnalysis: ...


__all__ = [
    "ExperimentAnalysisRepository",
    "ExperimentAnalysisWrite",
    "StoredExperimentAnalysis",
]
