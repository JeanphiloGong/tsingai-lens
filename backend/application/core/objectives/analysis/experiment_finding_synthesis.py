"""Synthesize Objective Findings directly from fixed experiment selections."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import (
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    ExperimentalVariant,
    PaperExperimentRevision,
)
from domain.core.research_objective import ResearchObjective
from domain.core.scientific_fact import ScientificAttribute, ScientificContext


_DIRECTION_ORDER = ("increase", "decrease", "no_change", "mixed")
_ATTRIBUTION_RANK = {
    "isolated_effect": 0,
    "joint_effect": 1,
    "association_only": 2,
    "descriptive_only": 3,
}
_TERM_SEPARATOR_RE = re.compile(r"[_\W]+", re.UNICODE)


@dataclass(frozen=True)
class ExperimentFindingSynthesisResult:
    groups: tuple[ComparisonGroup, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class _SelectedStudy:
    selection: ObjectiveExperimentSelection
    revision: PaperExperimentRevision
    comparisons: tuple[ExperimentComparison, ...]
    factors: tuple[str, ...]
    direction: str
    attribution_scope: str
    scientific_context: ScientificContext
    units: frozenset[str]
    test_types: frozenset[str]
    subject_values: Mapping[str, frozenset[str]]
    factor_levels: frozenset[str]
    test_parameters: frozenset[str]
    limitations: tuple[str, ...]
    has_incomplete_context: bool


class ExperimentFindingSynthesisService:
    """Build conservative Findings without recreating an Evidence fact layer."""

    def synthesize(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis_version: int,
        revisions: Sequence[PaperExperimentRevision],
        selections: Sequence[ObjectiveExperimentSelection],
    ) -> ExperimentFindingSynthesisResult:
        if objective.collection_id != collection_id:
            raise ValueError("experiment synthesis objective belongs to another collection")
        if analysis_version < 1:
            raise ValueError("experiment synthesis requires a positive analysis version")

        revision_by_identity = {
            (item.experiment_id, item.experiment_version): item for item in revisions
        }
        studies: list[_SelectedStudy] = []
        for selection in sorted(selections, key=lambda item: item.selection_id):
            if (
                selection.objective_id != objective.objective_id
                or selection.analysis_version != analysis_version
            ):
                raise ValueError("experiment selection does not match synthesis snapshot")
            revision = revision_by_identity.get(
                (selection.experiment_id, selection.experiment_version)
            )
            if revision is None:
                raise ValueError(
                    "selection references a missing experiment revision: "
                    f"{selection.experiment_id}/{selection.experiment_version}"
                )
            if not _matches_any(selection.outcome, objective.outcomes):
                continue
            study = _selected_study(selection, revision, objective)
            if study is not None:
                studies.append(study)

        groups: list[ComparisonGroup] = []
        findings: list[Finding] = []
        grouped: dict[tuple[str, tuple[str, ...]], list[_SelectedStudy]] = {}
        for study in studies:
            key = (
                _normalize_term(study.selection.outcome),
                tuple(sorted(_normalize_term(item) for item in study.factors)),
            )
            grouped.setdefault(key, []).append(study)

        rank = 0
        for key in sorted(grouped):
            for cluster in _comparability_clusters(grouped[key]):
                group = None
                if len(cluster) > 1:
                    group = _build_group(
                        collection_id=collection_id,
                        objective=objective,
                        analysis_version=analysis_version,
                        studies=cluster,
                    )
                    groups.append(group)
                finding = _build_finding(
                    collection_id=collection_id,
                    objective=objective,
                    analysis_version=analysis_version,
                    studies=cluster,
                    group=group,
                    display_rank=rank,
                )
                findings.append(finding)
                rank += 1

        return ExperimentFindingSynthesisResult(
            groups=tuple(groups),
            findings=tuple(findings),
        )


def _selected_study(
    selection: ObjectiveExperimentSelection,
    revision: PaperExperimentRevision,
    objective: ResearchObjective,
) -> _SelectedStudy | None:
    comparisons_by_key = {item.comparison_key: item for item in revision.comparisons}
    selected: list[ExperimentComparison] = []
    for key in selection.comparison_keys:
        comparison = comparisons_by_key.get(key)
        if comparison is None:
            raise ValueError(f"selection references a missing comparison: {key}")
        if not _same_term(comparison.outcome, selection.outcome):
            raise ValueError("selection comparison uses another outcome")
        if (
            comparison.status != "ready"
            or comparison.relation_status not in {"direct", "derived"}
            or comparison.direction == "unknown"
            or not comparison.changed_variables
        ):
            continue
        factors = tuple(item.name for item in comparison.changed_variables)
        if not any(_matches_any(item, objective.variables) for item in factors):
            continue
        selected.append(comparison)

    # Measurements remain valid archival results, but without a defensible
    # comparison they cannot answer a factor-to-outcome Objective by themselves.
    if not selected:
        return None

    factor_keys = {
        tuple(sorted(_normalize_term(item.name) for item in comparison.changed_variables))
        for comparison in selected
    }
    if len(factor_keys) != 1:
        raise ValueError("one experiment selection cannot mix comparison factor sets")
    factors = _ordered_factor_names(selected)
    directions = {_normalized_direction(item.direction) for item in selected}
    direction = next(iter(directions)) if len(directions) == 1 else "mixed"
    attribution_scope = _aggregate_attribution(selected, len(factors))
    context = _study_context(revision, selected)
    measurements = _comparison_measurements(revision, selected)
    units = frozenset(
        _normalize_unit(item.unit) for item in measurements if _normalize_unit(item.unit)
    )
    tests = _comparison_tests(revision, measurements)
    test_types = frozenset(
        _normalize_term(item.test_type) for item in tests if _normalize_term(item.test_type)
    )
    variants = _comparison_variants(revision, selected)
    subject_values = _attribute_values(
        attribute
        for variant in variants
        for attribute in variant.subject_attributes
    )
    factor_levels = frozenset(
        _variable_signature(variable)
        for comparison in selected
        for variable in comparison.changed_variables
    )
    test_parameters = frozenset(
        _attribute_signature(attribute)
        for test in tests
        for attribute in test.parameters
    )
    limitations = _terms(
        (
            *selection.missing_context,
            *(reason for item in selected for reason in item.reasons),
            *_attribution_limitations(attribution_scope),
        )
    )
    incomplete = bool(
        selection.missing_context
        or revision.binding_status != "bound"
        or not units
        or not test_types
        or not subject_values
    )
    return _SelectedStudy(
        selection=selection,
        revision=revision,
        comparisons=tuple(selected),
        factors=factors,
        direction=direction,
        attribution_scope=attribution_scope,
        scientific_context=context,
        units=units,
        test_types=test_types,
        subject_values=subject_values,
        factor_levels=factor_levels,
        test_parameters=test_parameters,
        limitations=limitations,
        has_incomplete_context=incomplete,
    )


def _comparability_clusters(
    studies: Sequence[_SelectedStudy],
) -> tuple[tuple[_SelectedStudy, ...], ...]:
    clusters: list[list[_SelectedStudy]] = []
    for study in sorted(studies, key=lambda item: item.selection.selection_id):
        for cluster in clusters:
            if all(
                _pair_comparability(study, member)[0] != "non_comparable"
                for member in cluster
            ):
                cluster.append(study)
                break
        else:
            clusters.append([study])
    return tuple(tuple(cluster) for cluster in clusters)


def _pair_comparability(
    left: _SelectedStudy,
    right: _SelectedStudy,
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    if not _same_term(left.selection.outcome, right.selection.outcome):
        return "non_comparable", ("The selected outcomes differ.",)
    if {_normalize_term(item) for item in left.factors} != {
        _normalize_term(item) for item in right.factors
    }:
        return "non_comparable", ("The changed factor sets differ.",)
    if left.units and right.units and left.units != right.units:
        return "non_comparable", ("Reported units differ and no normalization is recorded.",)
    if left.test_types and right.test_types and left.test_types != right.test_types:
        return "non_comparable", ("Test or characterization methods differ.",)
    for name in set(left.subject_values) & set(right.subject_values):
        if left.subject_values[name] != right.subject_values[name]:
            return "non_comparable", (f"Research-object attribute '{name}' differs.",)

    if left.has_incomplete_context or right.has_incomplete_context:
        reasons.append("At least one selection has incomplete binding context.")
    if left.factor_levels != right.factor_levels:
        reasons.append("Compared factor levels differ across experiments.")
    if left.test_parameters != right.test_parameters:
        reasons.append("Test parameters differ across experiments.")
    if left.subject_values.keys() != right.subject_values.keys():
        reasons.append("Research-object descriptions are only partially aligned.")
    if reasons:
        return "conditional", tuple(reasons)
    return "comparable", ("Outcome, factors, object, method, unit, and conditions align.",)


def _build_group(
    *,
    collection_id: str,
    objective: ResearchObjective,
    analysis_version: int,
    studies: Sequence[_SelectedStudy],
) -> ComparisonGroup:
    pair_results = [
        _pair_comparability(left, right)
        for index, left in enumerate(studies)
        for right in studies[index + 1 :]
    ]
    status = (
        "comparable"
        if pair_results and all(item[0] == "comparable" for item in pair_results)
        else "conditional"
    )
    pair_reasons = _terms(reason for _, reasons in pair_results for reason in reasons)
    member_status = "comparable" if status == "comparable" else "conditional"
    member_reason = (
        "The selected experiment matches the group's outcome, factors, object, "
        "method, unit, and conditions."
        if status == "comparable"
        else "; ".join(pair_reasons)
        or "The selected experiment is comparable only within recorded conditions."
    )
    selection_ids = tuple(item.selection.selection_id for item in studies)
    first = studies[0]
    basis = [
        f"outcome: {first.selection.outcome}",
        "factors: " + ", ".join(first.factors),
    ]
    if len(first.units) == 1 and all(item.units == first.units for item in studies):
        basis.append("unit: " + next(iter(first.units)))
    if len(first.test_types) == 1 and all(
        item.test_types == first.test_types for item in studies
    ):
        basis.append("test method: " + next(iter(first.test_types)))
    return ComparisonGroup(
        group_id=_stable_id(
            "grp",
            collection_id,
            objective.objective_id,
            analysis_version,
            first.selection.outcome,
            selection_ids,
        ),
        objective_id=objective.objective_id,
        analysis_version=analysis_version,
        outcome=first.selection.outcome,
        comparison_target="within_paper_comparison",
        comparison_basis=tuple(basis),
        members=tuple(
            ComparisonGroupMember(
                selection_id=item.selection.selection_id,
                role="included",
                comparability=member_status,
                reason=member_reason,
            )
            for item in studies
        ),
        status=status,
        limitations=pair_reasons if status == "conditional" else (),
    )


def _build_finding(
    *,
    collection_id: str,
    objective: ResearchObjective,
    analysis_version: int,
    studies: Sequence[_SelectedStudy],
    group: ComparisonGroup | None,
    display_rank: int,
) -> Finding:
    first = studies[0]
    directions = {item.direction for item in studies}
    direction = next(iter(directions)) if len(directions) == 1 else "mixed"
    synthesis_status = _synthesis_status(studies, group)
    attribution_scope = max(
        (item.attribution_scope for item in studies),
        key=lambda item: _ATTRIBUTION_RANK[item],
    )
    assertion_strength = (
        "descriptive" if attribution_scope == "descriptive_only" else "associative"
    )
    selection_ids = tuple(item.selection.selection_id for item in studies)
    limitations = _terms(
        (
            *(reason for item in studies for reason in item.limitations),
            *((group.limitations) if group is not None else ()),
            *(
                ("Reported directions differ across the selected comparisons.",)
                if direction == "mixed"
                else ()
            ),
        )
    )
    return Finding(
        collection_id=collection_id,
        objective_id=objective.objective_id,
        analysis_version=analysis_version,
        finding_id=_stable_id(
            "finding",
            collection_id,
            objective.objective_id,
            analysis_version,
            first.selection.outcome,
            first.factors,
            selection_ids,
        ),
        statement=_finding_statement(
            factors=first.factors,
            outcome=first.selection.outcome,
            direction=direction,
            synthesis_status=synthesis_status,
            study_count=len(studies),
        ),
        factors=first.factors,
        outcome=first.selection.outcome,
        direction=direction,
        assertion_strength=assertion_strength,
        attribution_scope=attribution_scope,
        synthesis_status=synthesis_status,
        certainty=_certainty(studies, group),
        display_rank=display_rank,
        mechanisms=(),
        scientific_context=_common_context(
            tuple(item.scientific_context for item in studies)
        ),
        limitations=limitations,
        paper_contributions=(),
        selection_ids=selection_ids,
        comparison_group_ids=((group.group_id,) if group is not None else ()),
    )


def _synthesis_status(
    studies: Sequence[_SelectedStudy],
    group: ComparisonGroup | None,
) -> str:
    if len(studies) == 1:
        return "single_study"
    directions = {item.direction for item in studies}
    if len(directions) == 1 and "mixed" not in directions:
        return "agreement"
    if group is not None and group.status == "conditional":
        return "condition_dependent"
    return "conflict"


def _finding_statement(
    *,
    factors: Sequence[str],
    outcome: str,
    direction: str,
    synthesis_status: str,
    study_count: int,
) -> str:
    factor_text = " and ".join(factors)
    if synthesis_status == "condition_dependent":
        return (
            f"Across {study_count} selected experiments, the relationship between "
            f"{factor_text} and {outcome} varied across reported conditions."
        )
    if synthesis_status == "conflict":
        return (
            f"Across {study_count} selected experiments, {factor_text} was associated "
            f"with conflicting directions for {outcome}."
        )
    direction_text = {
        "increase": f"higher {outcome}",
        "decrease": f"lower {outcome}",
        "no_change": f"no reported change in {outcome}",
        "mixed": f"different reported changes in {outcome}",
    }[direction]
    if synthesis_status == "agreement":
        return (
            f"Across {study_count} selected experiments, {factor_text} was consistently "
            f"associated with {direction_text}."
        )
    return f"In the selected experiment, {factor_text} was associated with {direction_text}."


def _certainty(
    studies: Sequence[_SelectedStudy],
    group: ComparisonGroup | None,
) -> float:
    # This score preserves the existing public Finding contract.  It is a
    # bounded provenance/readiness signal, not a statistical confidence value.
    score = 0.7
    if any(
        comparison.relation_status == "derived"
        for study in studies
        for comparison in study.comparisons
    ):
        score -= 0.1
    if any(item.has_incomplete_context for item in studies):
        score -= 0.1
    if group is not None and group.status == "conditional":
        score -= 0.1
    if len({item.direction for item in studies}) > 1:
        score -= 0.1
    return round(max(0.3, score), 2)


def _aggregate_attribution(
    comparisons: Sequence[ExperimentComparison],
    factor_count: int,
) -> str:
    scopes: list[str] = []
    for item in comparisons:
        scope = item.attribution_scope
        if scope == "isolated_effect" and factor_count != 1:
            scope = "association_only"
        elif scope == "joint_effect" and factor_count < 2:
            scope = "association_only"
        elif scope not in _ATTRIBUTION_RANK:
            scope = "descriptive_only"
        scopes.append(scope)
    return max(scopes, key=lambda item: _ATTRIBUTION_RANK[item])


def _attribution_limitations(scope: str) -> tuple[str, ...]:
    if scope == "joint_effect":
        return ("Multiple factors changed together; no isolated factor effect is claimed.",)
    if scope == "association_only":
        return ("The selected comparisons support association, not isolated causation.",)
    if scope == "descriptive_only":
        return ("The selected records support description only.",)
    return ()


def _study_context(
    revision: PaperExperimentRevision,
    comparisons: Sequence[ExperimentComparison],
) -> ScientificContext:
    variants = _comparison_variants(revision, comparisons)
    measurements = _comparison_measurements(revision, comparisons)
    tests = _comparison_tests(revision, measurements)
    material = _common_attributes(
        tuple(item.subject_attributes for item in variants)
    )
    sample = _common_attributes(tuple(item.state for item in variants))
    process = _common_attributes(
        tuple(item.matched_conditions for item in comparisons)
    )
    test_attributes: list[tuple[ScientificAttribute, ...]] = []
    for item in tests:
        method = ScientificAttribute(name="test_type", value=item.test_type)
        test_attributes.append((method, *item.parameters))
    return ScientificContext(
        material=material,
        sample=sample,
        process=process,
        test=_common_attributes(tuple(test_attributes)),
    )


def _common_context(contexts: Sequence[ScientificContext]) -> ScientificContext:
    return ScientificContext(
        material=_common_attributes(tuple(item.material for item in contexts)),
        sample=_common_attributes(tuple(item.sample for item in contexts)),
        process=_common_attributes(tuple(item.process for item in contexts)),
        test=_common_attributes(tuple(item.test for item in contexts)),
    )


def _comparison_measurements(
    revision: PaperExperimentRevision,
    comparisons: Sequence[ExperimentComparison],
) -> tuple[ExperimentMeasurementResult, ...]:
    by_key = {item.measurement_key: item for item in revision.measurements}
    keys = _terms(
        key
        for comparison in comparisons
        for key in (
            *comparison.baseline_measurement_keys,
            *comparison.target_measurement_keys,
        )
    )
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise ValueError("comparison references missing measurements: " + ", ".join(missing))
    return tuple(by_key[key] for key in keys)


def _comparison_variants(
    revision: PaperExperimentRevision,
    comparisons: Sequence[ExperimentComparison],
) -> tuple[ExperimentalVariant, ...]:
    by_key = {item.variant_key: item for item in revision.variants}
    keys = _terms(
        key
        for comparison in comparisons
        for key in (comparison.baseline_variant_key, comparison.target_variant_key)
    )
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise ValueError("comparison references missing variants: " + ", ".join(missing))
    return tuple(by_key[key] for key in keys)


def _comparison_tests(
    revision: PaperExperimentRevision,
    measurements: Sequence[ExperimentMeasurementResult],
) -> tuple[ExperimentTestCondition, ...]:
    by_key = {item.test_key: item for item in revision.test_conditions}
    keys = _terms(item.test_key for item in measurements if item.test_key)
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise ValueError("measurement references missing tests: " + ", ".join(missing))
    return tuple(by_key[key] for key in keys)


def _ordered_factor_names(
    comparisons: Sequence[ExperimentComparison],
) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for comparison in comparisons:
        for variable in comparison.changed_variables:
            key = _normalize_term(variable.name)
            if key not in seen:
                seen.add(key)
                names.append(variable.name)
    return tuple(names)


def _common_attributes(
    sequences: Sequence[Sequence[ScientificAttribute]],
) -> tuple[ScientificAttribute, ...]:
    if not sequences or any(not sequence for sequence in sequences):
        return ()
    first = {_attribute_signature(item): item for item in sequences[0]}
    common = set(first)
    for sequence in sequences[1:]:
        common &= {_attribute_signature(item) for item in sequence}
    return tuple(first[key] for key in first if key in common)


def _attribute_values(
    attributes: Iterable[ScientificAttribute],
) -> dict[str, frozenset[str]]:
    values: dict[str, set[str]] = {}
    for item in attributes:
        values.setdefault(_normalize_term(item.name), set()).add(
            json.dumps(
                [item.value, _normalize_unit(item.unit)],
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
        )
    return {key: frozenset(items) for key, items in values.items()}


def _attribute_signature(item: ScientificAttribute) -> str:
    return json.dumps(
        [_normalize_term(item.name), item.value, _normalize_unit(item.unit)],
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def _variable_signature(item: Any) -> str:
    return json.dumps(
        [
            _normalize_term(item.name),
            item.baseline_value,
            item.target_value,
            _normalize_unit(item.unit),
        ],
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def _matches_any(value: str, candidates: Sequence[str]) -> bool:
    return any(_terms_match(value, item) for item in candidates)


def _terms_match(left: str, right: str) -> bool:
    left_key = _normalize_term(left)
    right_key = _normalize_term(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def _same_term(left: str, right: str) -> bool:
    return _normalize_term(left) == _normalize_term(right)


def _normalize_term(value: Any) -> str:
    return " ".join(part for part in _TERM_SEPARATOR_RE.split(str(value).casefold()) if part)


def _normalize_unit(value: Any) -> str:
    return "".join(str(value or "").casefold().split())


def _normalized_direction(value: str) -> str:
    return value if value in _DIRECTION_ORDER else "mixed"


def _terms(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return tuple(result)


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
    "ExperimentFindingSynthesisResult",
    "ExperimentFindingSynthesisService",
]
