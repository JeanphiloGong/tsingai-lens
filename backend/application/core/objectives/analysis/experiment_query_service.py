"""Read-only projections and exports for experiment-backed analysis."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from application.repositories.comparison_group_repository import ComparisonGroupRepository
from application.repositories.experiment_finding_repository import (
    ExperimentFindingRepository,
)
from application.repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from application.repositories.paper_experiment_repository import (
    PaperExperimentRepository,
    StoredPaperExperimentRevision,
)
from domain.core.comparison_group import ComparisonGroup
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection


@dataclass(frozen=True)
class ExperimentAnalysisBundle:
    """All fixed-version records used by one Objective analysis snapshot."""

    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]
    revisions: tuple[StoredPaperExperimentRevision, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "selections": [item.to_record() for item in self.selections],
            "comparison_groups": [item.to_record() for item in self.groups],
            "findings": [item.to_record() for item in self.findings],
            "experiments": [item.revision.to_record() for item in self.revisions],
        }


class ExperimentQueryService:
    """Assemble one immutable analysis view and expose lossless exports."""

    def __init__(
        self,
        paper_experiment_repository: PaperExperimentRepository,
        selection_repository: ObjectiveExperimentSelectionRepository,
        group_repository: ComparisonGroupRepository,
        finding_repository: ExperimentFindingRepository,
    ) -> None:
        self.paper_experiment_repository = paper_experiment_repository
        self.selection_repository = selection_repository
        self.group_repository = group_repository
        self.finding_repository = finding_repository

    async def read_analysis_bundle(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ExperimentAnalysisBundle:
        if analysis_version < 1:
            raise ValueError("analysis_version must be positive")
        selections = await self.selection_repository.list_selections(
            collection_id,
            objective_id,
            analysis_version,
        )
        groups = await self.group_repository.list_groups(
            collection_id,
            objective_id,
            analysis_version,
        )
        findings = await self.finding_repository.list_findings(
            collection_id,
            objective_id,
            analysis_version,
        )

        revisions_by_identity: dict[tuple[str, int], StoredPaperExperimentRevision] = {}
        for selection in selections:
            identity = (selection.experiment_id, selection.experiment_version)
            if identity in revisions_by_identity:
                continue
            stored = await self.paper_experiment_repository.read_revision(*identity)
            if stored is None:
                raise ValueError(
                    "selection references a missing experiment revision: "
                    f"{identity[0]}/{identity[1]}"
                )
            revisions_by_identity[identity] = stored

        return ExperimentAnalysisBundle(
            selections=selections,
            groups=groups,
            findings=findings,
            revisions=tuple(
                revisions_by_identity[key] for key in sorted(revisions_by_identity)
            ),
        )

    async def export_json(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        bundle = await self.read_analysis_bundle(
            collection_id,
            objective_id,
            analysis_version,
        )
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": analysis_version,
            "projection_version": "paper-experiment-analysis.v1",
            **bundle.to_record(),
        }

    async def export_csv(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> str:
        bundle = await self.read_analysis_bundle(
            collection_id,
            objective_id,
            analysis_version,
        )
        revision_by_identity = {
            (item.revision.experiment_id, item.revision.experiment_version): item.revision
            for item in bundle.revisions
        }
        variants_by_identity = {
            (revision.experiment_id, revision.experiment_version, variant.variant_key): variant
            for revision in (item.revision for item in bundle.revisions)
            for variant in revision.variants
        }
        rows: list[dict[str, str]] = []
        for selection in bundle.selections:
            revision = revision_by_identity.get(
                (selection.experiment_id, selection.experiment_version)
            )
            if revision is None:
                continue
            selected_keys = set(selection.measurement_keys)
            for measurement in revision.measurements:
                if measurement.measurement_key not in selected_keys:
                    continue
                variant = variants_by_identity.get(
                    (
                        revision.experiment_id,
                        revision.experiment_version,
                        measurement.variant_key,
                    )
                )
                rows.append(
                    {
                        "collection_id": collection_id,
                        "objective_id": objective_id,
                        "analysis_version": str(analysis_version),
                        "selection_id": selection.selection_id,
                        "experiment_id": revision.experiment_id,
                        "experiment_version": str(revision.experiment_version),
                        "measurement_key": measurement.measurement_key,
                        "variant_key": measurement.variant_key or "",
                        "variant_label": variant.variant_label if variant else "",
                        "outcome": measurement.outcome,
                        "value": "" if measurement.value is None else str(measurement.value),
                        "unit": measurement.unit or "",
                        "result_text": measurement.result_text or "",
                        "statistics": json.dumps(
                            dict(measurement.statistics), ensure_ascii=False, sort_keys=True
                        ),
                        "measurement_scope": json.dumps(
                            dict(measurement.measurement_scope), ensure_ascii=False, sort_keys=True
                        ),
                        "source_refs": json.dumps(
                            [item.to_record() for item in measurement.source_refs],
                            ensure_ascii=False,
                        ),
                    }
                )

        output = io.StringIO(newline="")
        fieldnames = (
            "collection_id",
            "objective_id",
            "analysis_version",
            "selection_id",
            "experiment_id",
            "experiment_version",
            "measurement_key",
            "variant_key",
            "variant_label",
            "outcome",
            "value",
            "unit",
            "result_text",
            "statistics",
            "measurement_scope",
            "source_refs",
        )
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()


__all__ = ["ExperimentAnalysisBundle", "ExperimentQueryService"]
