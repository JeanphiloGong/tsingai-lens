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
        objective_repository: Any | None = None,
    ) -> None:
        self.paper_experiment_repository = paper_experiment_repository
        self.selection_repository = selection_repository
        self.group_repository = group_repository
        self.finding_repository = finding_repository
        self.objective_repository = objective_repository

    async def read_analysis_bundle(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ExperimentAnalysisBundle:
        if analysis_version < 1:
            raise ValueError("analysis_version must be positive")
        await self._validate_analysis_snapshot(
            collection_id,
            objective_id,
            analysis_version,
        )
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

    async def _validate_analysis_snapshot(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> None:
        """Reject empty or in-flight snapshots when the runtime can inspect them.

        The repository dependency is optional so small in-memory projections can
        remain useful in isolation.  The production wiring supplies the
        Objective repository, which makes the HTTP export a fixed analysis
        snapshot rather than an unscoped query that can return an empty 200 for
        a typo or a running analysis.
        """

        reader = getattr(self.objective_repository, "read_analysis", None)
        if not callable(reader):
            return
        analysis = await reader(collection_id, objective_id, analysis_version)
        if analysis is None:
            raise FileNotFoundError(
                "analysis snapshot not found: "
                f"{collection_id}/{objective_id}/v{analysis_version}"
            )
        status = str(getattr(analysis, "status", "") or "").strip().casefold()
        if status and status != "succeeded":
            raise ValueError(
                "analysis snapshot is not completed: "
                f"{collection_id}/{objective_id}/v{analysis_version}"
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
        tests_by_identity = {
            (revision.experiment_id, revision.experiment_version, test.test_key): test
            for revision in (item.revision for item in bundle.revisions)
            for test in revision.test_conditions
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
                test = tests_by_identity.get(
                    (
                        revision.experiment_id,
                        revision.experiment_version,
                        measurement.test_key,
                    )
                )
                comparison_keys = tuple(
                    comparison.comparison_key
                    for comparison in revision.comparisons
                    if measurement.measurement_key
                    in (
                        *comparison.baseline_measurement_keys,
                        *comparison.target_measurement_keys,
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
                        "variant_subject_attributes": json.dumps(
                            [item.to_record() for item in variant.subject_attributes]
                            if variant
                            else [],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_intervention_attributes": json.dumps(
                            [item.to_record() for item in variant.intervention_attributes]
                            if variant
                            else [],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_state": json.dumps(
                            [item.to_record() for item in variant.state]
                            if variant
                            else [],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_population_scope": json.dumps(
                            dict(variant.population_scope)
                            if variant and variant.population_scope is not None
                            else {},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "variant_binding_status": variant.binding_status if variant else "",
                        "variant_source_refs": json.dumps(
                            [item.to_record() for item in variant.source_refs]
                            if variant
                            else [],
                            ensure_ascii=False,
                        ),
                        "variant_binding_source_refs": json.dumps(
                            [item.to_record() for item in variant.binding_source_refs]
                            if variant
                            else [],
                            ensure_ascii=False,
                        ),
                        "test_key": measurement.test_key or "",
                        "test_type": test.test_type if test else "",
                        "test_parameters": json.dumps(
                            [item.to_record() for item in test.parameters]
                            if test
                            else [],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "test_population_scope": json.dumps(
                            dict(test.population_scope)
                            if test and test.population_scope is not None
                            else {},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "test_method": test.method if test and test.method else "",
                        "test_standard": test.standard if test and test.standard else "",
                        "test_outcome_scope": json.dumps(
                            list(test.outcome_scope) if test else [],
                            ensure_ascii=False,
                        ),
                        "test_protocol_specificity": (
                            test.protocol_specificity if test else ""
                        ),
                        "test_identity_status": (
                            test.test_identity_status if test else ""
                        ),
                        "test_protocol_completeness": (
                            test.protocol_completeness if test else ""
                        ),
                        "test_missing_parameters": json.dumps(
                            list(test.missing_parameters) if test else [],
                            ensure_ascii=False,
                        ),
                        "test_binding_status": test.binding_status if test else "",
                        "test_source_refs": json.dumps(
                            [item.to_record() for item in test.source_refs]
                            if test
                            else [],
                            ensure_ascii=False,
                        ),
                        "test_binding_source_refs": json.dumps(
                            [item.to_record() for item in test.binding_source_refs]
                            if test
                            else [],
                            ensure_ascii=False,
                        ),
                        "test_protocol_evidence": json.dumps(
                            list(test.protocol_evidence) if test else [],
                            ensure_ascii=False,
                        ),
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
                        "binding_source_refs": json.dumps(
                            [item.to_record() for item in measurement.binding_source_refs],
                            ensure_ascii=False,
                        ),
                        "binding_status": measurement.binding_status,
                        "result_kind": measurement.result_kind,
                        "notes": json.dumps(list(measurement.notes), ensure_ascii=False),
                        "comparison_keys": json.dumps(
                            list(comparison_keys), ensure_ascii=False
                        ),
                        "selection_comparison_keys": json.dumps(
                            list(selection.comparison_keys), ensure_ascii=False
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
            "variant_subject_attributes",
            "variant_intervention_attributes",
            "variant_state",
            "variant_population_scope",
            "variant_binding_status",
            "variant_source_refs",
            "variant_binding_source_refs",
            "test_key",
            "test_type",
            "test_parameters",
            "test_population_scope",
            "test_method",
            "test_standard",
            "test_outcome_scope",
            "test_protocol_specificity",
            "test_identity_status",
            "test_protocol_completeness",
            "test_missing_parameters",
            "test_binding_status",
            "test_source_refs",
            "test_binding_source_refs",
            "test_protocol_evidence",
            "outcome",
            "value",
            "unit",
            "result_text",
            "statistics",
            "measurement_scope",
            "source_refs",
            "binding_source_refs",
            "binding_status",
            "result_kind",
            "notes",
            "comparison_keys",
            "selection_comparison_keys",
        )
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()


__all__ = ["ExperimentAnalysisBundle", "ExperimentQueryService"]
