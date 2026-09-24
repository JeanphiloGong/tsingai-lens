"""Write experiment-backed analysis records from one completed legacy run.

The source extraction pipeline still returns the legacy in-process experiment
and Finding objects.  This service is the one-way application boundary used
while the hard switch is being completed: it assigns stable identities,
persists immutable revisions, creates Objective-scoped selections, and then
publishes Findings that point at those selections.

It deliberately does not copy legacy Evidence records into the new Finding.
The caller can keep the old publication path during the migration checkpoint;
this writer only owns the new experiment-domain records.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from application.core.objectives.analysis.experiment_finding_publisher import (
    ExperimentFindingPublisher,
)
from application.core.objectives.analysis.experiment_finding_synthesis import (
    ExperimentFindingSynthesisService,
)
from application.core.objectives.analysis.paper_experiment_revision_converter import (
    ConvertedPaperExperiment,
    convert_paper_experiment,
    stable_experiment_id,
)
from application.repositories.comparison_group_repository import (
    ComparisonGroupRepository,
)
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
from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import ExperimentComparison, PaperExperimentRevision
from domain.core.research_objective import (
    ObjectiveAnalysis,
    ResearchObjective,
)
from domain.core.research_process import PaperExperiment as LegacyPaperExperiment


@dataclass(frozen=True)
class ExperimentAnalysisWriteResult:
    """Records written for one Objective analysis snapshot."""

    revisions: tuple[StoredPaperExperimentRevision, ...]
    selections: tuple[ObjectiveExperimentSelection, ...]
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]
    skipped_finding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentSelectionWriteResult:
    """Fixed experiment revisions and Objective-scoped selections."""

    revisions: tuple[StoredPaperExperimentRevision, ...]
    selections: tuple[ObjectiveExperimentSelection, ...]


@dataclass(frozen=True)
class _ExperimentContext:
    stored: StoredPaperExperimentRevision
    converted: ConvertedPaperExperiment
    selections_by_outcome: Mapping[str, tuple[ObjectiveExperimentSelection, ...]]
    outcome_by_observation_id: Mapping[str, str]


@dataclass(frozen=True)
class _PreparedExperimentSelections:
    result: ExperimentSelectionWriteResult
    contexts: tuple[_ExperimentContext, ...]
    selection_by_id: Mapping[str, ObjectiveExperimentSelection]


@dataclass(frozen=True)
class _SelectionSlice:
    outcome: str
    factor_key: tuple[str, ...]
    measurement_keys: tuple[str, ...]
    comparison_keys: tuple[str, ...]


class ExperimentAnalysisWriter:
    """Persist the new experiment-domain side of a completed analysis."""

    def __init__(
        self,
        *,
        paper_experiment_repository: PaperExperimentRepository,
        selection_repository: ObjectiveExperimentSelectionRepository,
        group_repository: ComparisonGroupRepository,
        finding_publisher: ExperimentFindingPublisher,
        finding_repository: ExperimentFindingRepository | None = None,
        finding_synthesis_service: ExperimentFindingSynthesisService | None = None,
    ) -> None:
        self.paper_experiment_repository = paper_experiment_repository
        self.selection_repository = selection_repository
        self.group_repository = group_repository
        self.finding_publisher = finding_publisher
        # Retain the repository as an explicit dependency for callers that
        # want to inspect the concrete writer graph.  Publishing remains
        # delegated to ExperimentFindingPublisher so validation is centralized.
        self.finding_repository = finding_repository
        self.finding_synthesis_service = (
            finding_synthesis_service or ExperimentFindingSynthesisService()
        )

    async def write(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiments: Sequence[LegacyPaperExperiment],
        findings: Sequence[Finding],
        source_fingerprints: Mapping[str, str] | None = None,
        created_by: str | None = None,
    ) -> ExperimentAnalysisWriteResult:
        """Write revisions, selections, optional groups, and Findings.

        ``source_fingerprints`` is normally derived from the frozen
        ``analysis.document_inputs``.  It is injectable for replay tests and
        for a later caller that has already resolved the prepared document
        inputs.
        """

        prepared = await self._write_experiment_selections(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            experiments=experiments,
            source_fingerprints=source_fingerprints,
            created_by=created_by,
        )

        groups: list[ComparisonGroup] = []
        published_findings: list[Finding] = []
        skipped_finding_ids: list[str] = []
        group_by_selection_key: dict[tuple[str, ...], ComparisonGroup] = {}

        for finding in sorted(
            findings,
            key=lambda item: (item.display_rank, item.finding_id),
        ):
            selected = self._select_for_finding(
                finding,
                prepared.contexts,
                selection_by_id=prepared.selection_by_id,
            )
            if not selected:
                skipped_finding_ids.append(finding.finding_id)
                continue

            selected_ids = tuple(item.selection_id for item in selected)
            experiment_ids = {item.experiment_id for item in selected}
            group_ids: tuple[str, ...] = ()
            if len(experiment_ids) > 1:
                key = tuple(sorted(selected_ids))
                group = group_by_selection_key.get(key)
                if group is None:
                    group = self._build_comparison_group(
                        finding,
                        selected,
                        collection_id=collection_id,
                    )
                    group = await self.group_repository.add_group(collection_id, group)
                    group_by_selection_key[key] = group
                    groups.append(group)
                group_ids = (group.group_id,)

            converted_finding = self._convert_finding(
                finding,
                selection_ids=selected_ids,
                comparison_group_ids=group_ids,
                experiment_count=len(experiment_ids),
            )
            published = await self.finding_publisher.publish(converted_finding)
            published_findings.append(published.finding)

        return ExperimentAnalysisWriteResult(
            revisions=prepared.result.revisions,
            selections=prepared.result.selections,
            groups=tuple(groups),
            findings=tuple(published_findings),
            skipped_finding_ids=tuple(skipped_finding_ids),
        )

    async def write_experiment_selections(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiments: Sequence[LegacyPaperExperiment],
        source_fingerprints: Mapping[str, str] | None = None,
        created_by: str | None = None,
    ) -> ExperimentSelectionWriteResult:
        """Persist experiment facts and selections without publishing Findings.

        Finding synthesis is a separate scientific decision over these fixed
        records.  Keeping this operation independent lets that decision read
        the same immutable revisions that later queries and exports use.
        """

        prepared = await self._write_experiment_selections(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            experiments=experiments,
            source_fingerprints=source_fingerprints,
            created_by=created_by,
        )
        return prepared.result

    async def write_experiment_analysis(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiments: Sequence[LegacyPaperExperiment],
        source_fingerprints: Mapping[str, str] | None = None,
        created_by: str | None = None,
    ) -> ExperimentAnalysisWriteResult:
        """Persist and publish analysis without consuming legacy Findings."""

        prepared = await self._write_experiment_selections(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            experiments=experiments,
            source_fingerprints=source_fingerprints,
            created_by=created_by,
        )
        synthesis = self.finding_synthesis_service.synthesize(
            collection_id=collection_id,
            objective=objective,
            analysis_version=analysis.analysis_version,
            revisions=tuple(item.revision for item in prepared.result.revisions),
            selections=prepared.result.selections,
        )
        groups: list[ComparisonGroup] = []
        for group in synthesis.groups:
            groups.append(
                await self.group_repository.add_group(collection_id, group)
            )
        findings: list[Finding] = []
        for finding in synthesis.findings:
            published = await self.finding_publisher.publish(finding)
            findings.append(published.finding)
        return ExperimentAnalysisWriteResult(
            revisions=prepared.result.revisions,
            selections=prepared.result.selections,
            groups=tuple(groups),
            findings=tuple(findings),
        )

    async def _write_experiment_selections(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiments: Sequence[LegacyPaperExperiment],
        source_fingerprints: Mapping[str, str] | None,
        created_by: str | None,
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

        contexts: list[_ExperimentContext] = []
        revisions: list[StoredPaperExperimentRevision] = []
        selections: list[ObjectiveExperimentSelection] = []
        selection_by_id: dict[str, ObjectiveExperimentSelection] = {}

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
            context, context_selections = await self._write_experiment(
                experiment,
                source_fingerprint=fingerprint,
                collection_id=collection_id,
                objective=objective,
                analysis_version=analysis.analysis_version,
                created_by=created_by,
            )
            contexts.append(context)
            revisions.append(context.stored)
            selections.extend(context_selections)
            selection_by_id.update(
                (item.selection_id, item) for item in context_selections
            )

        return _PreparedExperimentSelections(
            result=ExperimentSelectionWriteResult(
                revisions=tuple(revisions),
                selections=tuple(selections),
            ),
            contexts=tuple(contexts),
            selection_by_id=selection_by_id,
        )

    async def _write_experiment(
        self,
        experiment: LegacyPaperExperiment,
        *,
        source_fingerprint: str,
        collection_id: str,
        objective: ResearchObjective,
        analysis_version: int,
        created_by: str | None,
    ) -> tuple[_ExperimentContext, tuple[ObjectiveExperimentSelection, ...]]:
        experiment_id = stable_experiment_id(experiment)
        latest = await self.paper_experiment_repository.read_latest_revision(
            experiment_id
        )
        current_version = latest.revision.experiment_version if latest is not None else 1
        converted = convert_paper_experiment(
            experiment,
            source_fingerprint=source_fingerprint,
            experiment_version=current_version,
            experiment_id=experiment_id,
        )
        if latest is not None and converted.revision == latest.revision:
            stored = latest
        else:
            if latest is not None:
                current_version += 1
                converted = convert_paper_experiment(
                    experiment,
                    source_fingerprint=source_fingerprint,
                    experiment_version=current_version,
                    experiment_id=experiment_id,
                )
            stored = await self.paper_experiment_repository.add_revision(
                converted.revision,
                created_by=created_by,
            )

        selections_by_outcome: dict[
            str, list[ObjectiveExperimentSelection]
        ] = {}
        selections: list[ObjectiveExperimentSelection] = []
        unresolved = tuple(
            str(item.get("description") or "").strip()
            for item in converted.revision.unresolved_issues
            if str(item.get("description") or "").strip()
        )
        for selection_slice in _selection_slices(converted.revision, objective):
            factor_label = ", ".join(selection_slice.factor_key)
            selection = ObjectiveExperimentSelection(
                selection_id=_stable_id(
                    "sel",
                    collection_id,
                    objective.objective_id,
                    analysis_version,
                    experiment_id,
                    converted.revision.experiment_version,
                    selection_slice.outcome.casefold(),
                    selection_slice.factor_key,
                ),
                objective_id=objective.objective_id,
                analysis_version=analysis_version,
                experiment_id=experiment_id,
                experiment_version=converted.revision.experiment_version,
                outcome=selection_slice.outcome,
                measurement_keys=selection_slice.measurement_keys,
                comparison_keys=selection_slice.comparison_keys,
                missing_context=unresolved,
                reasons=(
                    "Fixed to the source-grounded PaperExperiment revision for this analysis.",
                    (
                        f"Selected comparisons for changed factors: {factor_label}."
                        if factor_label
                        else (
                            "Selected reported measurements; no relevant comparison "
                            "was recovered."
                        )
                    ),
                ),
            )
            stored_selection = await self.selection_repository.add_selection(
                collection_id,
                selection,
                revision_id=stored.revision_id,
            )
            selections.append(stored_selection)
            selections_by_outcome.setdefault(
                selection_slice.outcome.casefold(), []
            ).append(stored_selection)

        outcome_by_observation_id: dict[str, str] = {}
        for (
            observation_id,
            measurement_key,
        ) in converted.measurement_key_by_observation_id.items():
            measurement = next(
                (
                    item
                    for item in converted.revision.measurements
                    if item.measurement_key == measurement_key
                ),
                None,
            )
            if measurement is not None:
                outcome_by_observation_id[observation_id] = measurement.outcome
        for (
            observation_id,
            comparison_key,
        ) in converted.comparison_key_by_observation_id.items():
            comparison = next(
                (
                    item
                    for item in converted.revision.comparisons
                    if item.comparison_key == comparison_key
                ),
                None,
            )
            if comparison is not None:
                outcome_by_observation_id[observation_id] = comparison.outcome

        return (
            _ExperimentContext(
                stored=stored,
                converted=converted,
                selections_by_outcome={
                    key: tuple(items) for key, items in selections_by_outcome.items()
                },
                outcome_by_observation_id=outcome_by_observation_id,
            ),
            tuple(selections),
        )

    @staticmethod
    def _select_for_finding(
        finding: Finding,
        contexts: Sequence[_ExperimentContext],
        *,
        selection_by_id: Mapping[str, ObjectiveExperimentSelection],
    ) -> tuple[ObjectiveExperimentSelection, ...]:
        if finding.selection_ids:
            selected = tuple(
                selection_by_id[item]
                for item in finding.selection_ids
                if item in selection_by_id
            )
            if selected:
                return selected

        evidence_ids = _finding_source_ids(finding)
        document_ids = {
            item.document_id
            for item in finding.paper_contributions
            if item.document_id.strip()
        }
        selected: list[ObjectiveExperimentSelection] = []
        for context in contexts:
            if document_ids and context.converted.revision.document_id not in document_ids:
                continue
            outcomes = {
                context.outcome_by_observation_id[item]
                for item in evidence_ids
                if item in context.outcome_by_observation_id
            }
            if not outcomes:
                outcomes = {
                    outcome
                    for outcome in context.selections_by_outcome
                    if _same_term(outcome, finding.outcome)
                }
            for outcome in sorted(outcomes):
                for selection in context.selections_by_outcome.get(
                    outcome.casefold(), ()
                ):
                    if _same_term(selection.outcome, finding.outcome):
                        selected.append(selection)
        unique: dict[str, ObjectiveExperimentSelection] = {
            item.selection_id: item for item in selected
        }
        return tuple(unique[key] for key in sorted(unique))

    @staticmethod
    def _build_comparison_group(
        finding: Finding,
        selections: Sequence[ObjectiveExperimentSelection],
        *,
        collection_id: str,
    ) -> ComparisonGroup:
        selected_ids = tuple(sorted(item.selection_id for item in selections))
        target = (
            "within_paper_comparison"
            if all(item.comparison_keys for item in selections)
            else "measurement"
        )
        return ComparisonGroup(
            group_id=_stable_id(
                "grp",
                collection_id,
                finding.objective_id,
                finding.analysis_version,
                finding.outcome.casefold(),
                selected_ids,
            ),
            objective_id=finding.objective_id,
            analysis_version=finding.analysis_version,
            outcome=finding.outcome,
            comparison_target=target,
            comparison_basis=("same reported outcome",),
            members=tuple(
                ComparisonGroupMember(
                    selection_id=item.selection_id,
                    role="included",
                    comparability="conditional",
                    reason=(
                        "Selected by the source-grounded Finding; material, test, "
                        "and unit alignment remains conditional across papers."
                    ),
                )
                for item in selections
            ),
            status="conditional",
            limitations=(
                "Cross-paper members are retained as a conditional comparison; "
                "no pooled estimate is implied.",
            ),
        )

    @staticmethod
    def _convert_finding(
        finding: Finding,
        *,
        selection_ids: tuple[str, ...],
        comparison_group_ids: tuple[str, ...],
        experiment_count: int,
    ) -> Finding:
        if not selection_ids:
            raise ValueError("selection-backed Finding requires selections")
        synthesis_status = finding.synthesis_status
        if experiment_count <= 1:
            synthesis_status = "single_study"
        elif synthesis_status == "single_study":
            synthesis_status = "insufficient_confirmation"

        attribution_scope = finding.attribution_scope
        if attribution_scope == "isolated_effect" and len(finding.factors) != 1:
            attribution_scope = "association_only"
        if attribution_scope == "joint_effect" and len(finding.factors) < 2:
            attribution_scope = "association_only"
        assertion_strength = finding.assertion_strength
        if attribution_scope == "descriptive_only":
            assertion_strength = "descriptive"
        elif assertion_strength == "causal" and attribution_scope != "isolated_effect":
            assertion_strength = "associative"

        payload = finding.to_record()
        payload.update(
            {
                "paper_contributions": [],
                "selection_ids": list(selection_ids),
                "comparison_group_ids": list(comparison_group_ids),
                "mechanisms": [],
                "assertion_strength": assertion_strength,
                "attribution_scope": attribution_scope,
                "synthesis_status": synthesis_status,
                "origin": "system_generated",
                "source_analysis_version": None,
                "parent_finding_id": None,
                "created_by_user_id": None,
                "created_by_tool_call_id": None,
                "created_at": None,
                "limitations": list(finding.limitations)
                + [
                    "Legacy Evidence bindings were replaced by explicit experiment selections."
                ],
            }
        )
        return Finding.from_mapping(payload)


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
        comparisons_by_factor: dict[
            tuple[str, ...], list[ExperimentComparison]
        ] = {}
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


def _finding_source_ids(finding: Finding) -> tuple[str, ...]:
    values: list[str] = []
    for contribution in finding.paper_contributions:
        values.extend(contribution.supporting_evidence_ids)
        values.extend(contribution.contradicting_evidence_ids)
        values.extend(contribution.context_evidence_ids)
        values.extend(contribution.condition_boundary_evidence_ids)
    return tuple(dict.fromkeys(values))


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


__all__ = [
    "ExperimentAnalysisWriteResult",
    "ExperimentAnalysisWriter",
    "ExperimentSelectionWriteResult",
]
