"""Prepare and atomically write one automatic Objective experiment graph.

Source extraction returns transient experiment drafts. This service assigns
stable identities, prepares immutable revisions and Objective-scoped
selections, synthesizes Findings, and hands the complete graph to one
repository write. Authored snapshots use their separate publication path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from application.core.objectives.analysis.experiment_finding_synthesis import (
    ExperimentFindingSynthesisService,
)
from application.core.objectives.analysis.paper_experiment_revision_converter import (
    convert_paper_experiment,
    stable_experiment_id,
)
from application.repositories.experiment_analysis_repository import (
    ExperimentAnalysisRepository,
    ExperimentAnalysisWrite,
)
from application.repositories.paper_experiment_repository import (
    PaperExperimentRepository,
    StoredPaperExperimentRevision,
)
from application.repositories.transaction import RepositoryTransaction
from domain.core.comparison_group import ComparisonGroup
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import ExperimentComparison, PaperExperimentRevision
from domain.core.research_objective import ObjectiveAnalysis, ResearchObjective
from domain.core.research_process import PaperExperiment as LegacyPaperExperiment


async def _repository_call(
    method: Any,
    *args: Any,
    transaction: RepositoryTransaction | None,
    **kwargs: Any,
) -> Any:
    """Pass the opaque transaction only when the caller supplied one."""

    if transaction is not None:
        kwargs["transaction"] = transaction
    return await method(*args, **kwargs)


@dataclass(frozen=True)
class ExperimentAnalysisWriteResult:
    """Records committed for one Objective analysis snapshot."""

    revisions: tuple[StoredPaperExperimentRevision, ...]
    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class _PreparedExperimentSelections:
    revisions: tuple[PaperExperimentRevision, ...]
    selections: tuple[ObjectiveExperimentSelection, ...]


@dataclass(frozen=True)
class _SelectionSlice:
    outcome: str
    factor_key: tuple[str, ...]
    measurement_keys: tuple[str, ...]
    comparison_keys: tuple[str, ...]


class ExperimentAnalysisWriter:
    """Prepare the complete automatic graph before its single durable write."""

    def __init__(
        self,
        *,
        paper_experiment_repository: PaperExperimentRepository,
        experiment_analysis_repository: ExperimentAnalysisRepository,
        finding_synthesis_service: ExperimentFindingSynthesisService | None = None,
    ) -> None:
        self.paper_experiment_repository = paper_experiment_repository
        self.experiment_analysis_repository = experiment_analysis_repository
        self.finding_synthesis_service = (
            finding_synthesis_service or ExperimentFindingSynthesisService()
        )

    async def write_experiment_analysis(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiments: Sequence[LegacyPaperExperiment],
        source_fingerprints: Mapping[str, str] | None = None,
        created_by: str | None = None,
        transaction: RepositoryTransaction | None = None,
    ) -> ExperimentAnalysisWriteResult:
        """Prepare and commit revisions, selections, groups, and Findings."""

        prepared = await self._prepare_experiment_selections(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            experiments=experiments,
            source_fingerprints=source_fingerprints,
            transaction=transaction,
        )
        synthesis = self.finding_synthesis_service.synthesize(
            collection_id=collection_id,
            objective=objective,
            analysis_version=analysis.analysis_version,
            revisions=prepared.revisions,
            selections=prepared.selections,
        )
        stored = await _repository_call(
            self.experiment_analysis_repository.write_graph,
            ExperimentAnalysisWrite(
                collection_id=collection_id,
                objective_id=objective.objective_id,
                analysis_version=analysis.analysis_version,
                revisions=prepared.revisions,
                selections=prepared.selections,
                groups=synthesis.groups,
                findings=synthesis.findings,
                created_by=created_by,
            ),
            transaction=transaction,
        )
        return ExperimentAnalysisWriteResult(
            revisions=stored.revisions,
            selections=stored.selections,
            groups=stored.groups,
            findings=stored.findings,
        )

    async def _prepare_experiment_selections(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiments: Sequence[LegacyPaperExperiment],
        source_fingerprints: Mapping[str, str] | None,
        transaction: RepositoryTransaction | None,
    ) -> _PreparedExperimentSelections:
        if objective.collection_id != collection_id:
            raise ValueError("experiment analysis objective belongs to another collection")
        if (
            analysis.collection_id != collection_id
            or analysis.objective_id != objective.objective_id
        ):
            raise ValueError("experiment analysis snapshot does not match objective")

        fingerprints = dict(source_fingerprints or {})
        for item in analysis.document_inputs:
            fingerprints.setdefault(item.document_id, item.preparation_fingerprint)

        revisions: list[PaperExperimentRevision] = []
        selections: list[ObjectiveExperimentSelection] = []
        for experiment in sorted(
            experiments,
            key=lambda item: (item.document_id, item.experiment_id),
        ):
            fingerprint = str(fingerprints.get(experiment.document_id) or "").strip()
            if not fingerprint:
                raise ValueError(
                    "experiment analysis requires a preparation fingerprint for "
                    f"document {experiment.document_id}"
                )
            revision, revision_selections = await self._prepare_experiment(
                experiment,
                source_fingerprint=fingerprint,
                collection_id=collection_id,
                objective=objective,
                analysis_version=analysis.analysis_version,
                transaction=transaction,
            )
            revisions.append(revision)
            selections.extend(revision_selections)

        return _PreparedExperimentSelections(
            revisions=tuple(revisions),
            selections=tuple(selections),
        )

    async def _prepare_experiment(
        self,
        experiment: LegacyPaperExperiment,
        *,
        source_fingerprint: str,
        collection_id: str,
        objective: ResearchObjective,
        analysis_version: int,
        transaction: RepositoryTransaction | None,
    ) -> tuple[PaperExperimentRevision, tuple[ObjectiveExperimentSelection, ...]]:
        experiment_id = stable_experiment_id(experiment)
        latest = await _repository_call(
            self.paper_experiment_repository.read_latest_revision,
            experiment_id,
            transaction=transaction,
        )
        current_version = latest.revision.experiment_version if latest is not None else 1
        converted = convert_paper_experiment(
            experiment,
            source_fingerprint=source_fingerprint,
            experiment_version=current_version,
            experiment_id=experiment_id,
        )
        if latest is not None and converted.revision != latest.revision:
            converted = convert_paper_experiment(
                experiment,
                source_fingerprint=source_fingerprint,
                experiment_version=current_version + 1,
                experiment_id=experiment_id,
            )
        revision = converted.revision

        unresolved = tuple(
            str(item.get("description") or "").strip()
            for item in revision.unresolved_issues
            if str(item.get("description") or "").strip()
        )
        selections: list[ObjectiveExperimentSelection] = []
        for selection_slice in _selection_slices(revision, objective):
            factor_label = ", ".join(selection_slice.factor_key)
            selections.append(
                ObjectiveExperimentSelection(
                    selection_id=_stable_id(
                        "sel",
                        collection_id,
                        objective.objective_id,
                        analysis_version,
                        experiment_id,
                        revision.experiment_version,
                        selection_slice.outcome.casefold(),
                        selection_slice.factor_key,
                    ),
                    objective_id=objective.objective_id,
                    analysis_version=analysis_version,
                    experiment_id=experiment_id,
                    experiment_version=revision.experiment_version,
                    outcome=selection_slice.outcome,
                    measurement_keys=selection_slice.measurement_keys,
                    comparison_keys=selection_slice.comparison_keys,
                    missing_context=unresolved,
                    reasons=(
                        "Fixed to the source-grounded PaperExperiment revision for "
                        "this analysis.",
                        (
                            "Selected comparisons for changed factors: "
                            f"{factor_label}."
                            if factor_label
                            else (
                                "Selected reported measurements; no relevant "
                                "comparison was recovered."
                            )
                        ),
                    ),
                )
            )
        return revision, tuple(selections)


def _revision_outcomes(revision: PaperExperimentRevision) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for item in (*revision.measurements, *revision.comparisons):
        key = item.outcome.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(item.outcome)
    return tuple(values)


def _selection_slices(
    revision: PaperExperimentRevision,
    objective: ResearchObjective,
) -> tuple[_SelectionSlice, ...]:
    slices: list[_SelectionSlice] = []
    for outcome in _revision_outcomes(revision):
        if not any(_same_term(outcome, candidate) for candidate in objective.outcomes):
            continue
        comparisons_by_factor: dict[tuple[str, ...], list[ExperimentComparison]] = {}
        for comparison in revision.comparisons:
            if not _same_term(comparison.outcome, outcome):
                continue
            factor_key = tuple(
                sorted(
                    {
                        _normalized_term(item.name)
                        for item in comparison.changed_variables
                        if _normalized_term(item.name)
                    }
                )
            )
            if not factor_key or not any(
                _term_matches(factor, objective_variable)
                for factor in factor_key
                for objective_variable in objective.variables
            ):
                continue
            comparisons_by_factor.setdefault(factor_key, []).append(comparison)

        if comparisons_by_factor:
            for factor_key in sorted(comparisons_by_factor):
                comparisons = comparisons_by_factor[factor_key]
                measurement_keys = tuple(
                    dict.fromkeys(
                        key
                        for comparison in comparisons
                        for key in (
                            *comparison.baseline_measurement_keys,
                            *comparison.target_measurement_keys,
                        )
                    )
                )
                slices.append(
                    _SelectionSlice(
                        outcome=outcome,
                        factor_key=factor_key,
                        measurement_keys=measurement_keys,
                        comparison_keys=tuple(
                            item.comparison_key for item in comparisons
                        ),
                    )
                )
            continue

        measurement_keys = tuple(
            item.measurement_key
            for item in revision.measurements
            if _same_term(item.outcome, outcome)
        )
        if measurement_keys:
            slices.append(
                _SelectionSlice(
                    outcome=outcome,
                    factor_key=(),
                    measurement_keys=measurement_keys,
                    comparison_keys=(),
                )
            )
    return tuple(slices)


def _same_term(left: str, right: str) -> bool:
    return _normalized_term(left) == _normalized_term(right)


def _term_matches(left: str, right: str) -> bool:
    left_key = _normalized_term(left)
    right_key = _normalized_term(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def _normalized_term(value: Any) -> str:
    return " ".join(
        part for part in re.split(r"[_\W]+", str(value).casefold()) if part
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
        parts,
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:28]}"


__all__ = ["ExperimentAnalysisWriteResult", "ExperimentAnalysisWriter"]
