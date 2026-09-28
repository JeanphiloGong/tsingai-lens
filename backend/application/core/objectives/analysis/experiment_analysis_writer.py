"""Prepare and atomically write one automatic Objective experiment graph.

Source extraction returns transient experiment drafts. This service assigns
stable identities, prepares immutable revisions and Objective-scoped
selections, synthesizes Findings, and hands the complete graph to one
repository write. Authored snapshots use their separate publication path.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from application.core.objectives.analysis.experiment_finding_synthesis import (
    ExperimentFindingSynthesisService,
)
from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentDraft,
    ReconciledPaperExperimentOutput,
    bind_model_output,
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
from domain.core.paper_experiment import (
    ExperimentComparison,
    PaperExperimentRevision,
)
from domain.core.research_objective import ObjectiveAnalysis, ResearchObjective


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
    post_bind_diagnostics: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class _PreparedExperimentSelections:
    revisions: tuple[PaperExperimentRevision, ...]
    selections: tuple[ObjectiveExperimentSelection, ...]
    post_bind_diagnostics: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class _SelectionSlice:
    outcome: str
    factor_key: tuple[str, ...]
    measurement_keys: tuple[str, ...]
    comparison_keys: tuple[str, ...]


@dataclass(frozen=True)
class _EmptySynthesis:
    groups: tuple[ComparisonGroup, ...] = ()
    findings: tuple[Finding, ...] = ()


_PHYSICAL_SPLIT_KINDS = frozenset({"physical_split", "split", "independent"})

_TRANSIENT_IDENTITY_FIELDS = frozenset(
    {
        "source_label",
        "source_labels",
        "binding_source_labels",
        "source_ref",
        "source_refs",
        "source_fingerprint",
        "document_id",
        "series_key",
        "series_id",
        "experiment_key",
        "parent_series_key",
        "variant_key",
        "test_key",
        "measurement_key",
        "comparison_key",
    }
)


def _canonical_identity_value(value: Any) -> Any:
    """Normalize boundary evidence without depending on response ordering."""

    if isinstance(value, Mapping):
        return {
            str(key): _canonical_identity_value(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [_canonical_identity_value(item) for item in value]
        return sorted(
            values,
            key=lambda item: json.dumps(
                item, ensure_ascii=True, sort_keys=True, default=str
            ),
        )
    return value


def _identity_value_without_transient_fields(value: Any) -> Any:
    """Remove response-local and Source-location fields before identity hashing.

    Drafts are allowed to use local keys and request-local ``Sxxx`` labels for
    cross-reference.  Neither is a physical property of the paper experiment;
    including either in the stable identity would create a new experiment when
    a later reread renumbers Sources or chooses different local keys.
    """

    if isinstance(value, Mapping):
        return {
            str(key): _identity_value_without_transient_fields(nested)
            for key, nested in value.items()
            if str(key).strip().casefold() not in _TRANSIENT_IDENTITY_FIELDS
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _identity_value_without_transient_fields(item)
            for item in value
        ]
    return value


def _physical_split_discriminator(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return source-backed boundary facts that distinguish independent splits.

    ``series_key`` is intentionally excluded: it is a model-local key and may
    change between extraction calls.  A split with indistinguishable reason
    and evidence remains a collision that the writer must reject rather than
    silently merge into one formal experiment.
    """

    scope_kind = str(payload.get("scope_kind") or "parent").strip().casefold()
    if scope_kind not in _PHYSICAL_SPLIT_KINDS:
        return None
    return {
        "split_reason": str(payload.get("split_reason") or "")
        .strip()
        .casefold(),
        "split_evidence": _canonical_identity_value(
            _identity_value_without_transient_fields(
                payload.get("split_evidence") or ()
            )
        ),
    }


def _identity_payload(*, document_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a stable physical-study identity without Objective/source coordinates."""

    variants = payload.get("experimental_variants") or payload.get("variants") or ()
    physical_variants = [
        {
            "variant_label": item.get("variant_label"),
            "subject_attributes": _canonical_identity_value(
                _identity_value_without_transient_fields(
                    item.get("subject_attributes") or ()
                )
            ),
            "intervention_attributes": _canonical_identity_value(
                _identity_value_without_transient_fields(
                    item.get("intervention_attributes") or ()
                )
            ),
            "state": _canonical_identity_value(
                _identity_value_without_transient_fields(item.get("state") or ())
            ),
            "population_scope": _canonical_identity_value(
                _identity_value_without_transient_fields(
                    item.get("population_scope") or {}
                )
            ),
        }
        for item in variants
        if isinstance(item, Mapping)
    ]
    if not physical_variants:
        raise ValueError("cannot allocate an experiment identity without physical variants")
    identity = {
        "document_id": document_id,
        "physical_variants": sorted(
            physical_variants,
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        ),
        "scope_kind": str(payload.get("scope_kind") or "parent").strip().casefold(),
        # A selected stratum can reuse the same visible variant labels while
        # representing a different source-backed slice of the parent series.
        # Keep that physical selector in the identity, but never include
        # provider-local keys or Source coordinates.
        "scope_selector": _canonical_identity_value(
            _identity_value_without_transient_fields(
                payload.get("scope_selector") or {}
            )
        ),
    }
    split_discriminator = _physical_split_discriminator(payload)
    if split_discriminator is not None:
        identity["split_discriminator"] = split_discriminator
    return identity


def _assert_identity_boundary_is_decidable(
    payload: Mapping[str, Any],
    *,
    allow_partial_archive: bool = False,
) -> None:
    scope_kind = str(payload.get("scope_kind") or "unknown").strip().casefold()
    if scope_kind == "unknown" and not allow_partial_archive:
        raise ValueError(
            "experiment boundary is unknown; manual reconciliation is required"
        )
    if scope_kind in {"selected_stratum", "follow_up"}:
        if not str(payload.get("parent_series_key") or "").strip():
            raise ValueError("scoped experiment lacks parent series key")
        if not payload.get("scope_selector"):
            raise ValueError("scoped experiment lacks scope selector")
    if scope_kind in {"physical_split", "split", "independent"} and not payload.get(
        "split_evidence"
    ):
        raise ValueError("physical split lacks source-backed split evidence")


def stable_draft_experiment_id(*, document_id: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _identity_payload(document_id=document_id, payload=payload),
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "pexp_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:28]


def stable_partial_archive_experiment_id(
    *,
    document_id: str,
    source_fingerprint: str,
    local_key: str,
    payload: Mapping[str, Any],
) -> str:
    """Allocate an identity for an unresolved archive without claiming a study.

    A partial archive can contain source-grounded measurements before the
    sample/experiment boundary is known.  It still needs a durable key so the
    report is not lost, but that key must not be confused with the physical
    parent-study identity used by ready revisions.  The request-local series
    key and preparation fingerprint keep two unresolved slices from silently
    merging; the payload (with response-local IDs and Source coordinates
    removed) makes retries deterministic for the same archive content.
    """

    archive_payload = {
        "document_id": str(document_id).strip(),
        "source_fingerprint": str(source_fingerprint).strip(),
        "local_key": str(local_key).strip(),
        "content": _canonical_identity_value(
            _identity_value_without_transient_fields(payload)
        ),
    }
    encoded = json.dumps(
        archive_payload,
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "pexp_partial_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _advisory_lock_identity_for_draft(
    *,
    output: ReconciledPaperExperimentOutput,
    draft: PaperExperimentDraft,
    local_key: str,
    allow_partial_archive: bool,
) -> str:
    """Return the identity whose latest-revision read takes the advisory lock.

    ``read_latest_revision`` locks the stable content identity before the
    writer resolves a possible reread to an older physical identity.  Sorting
    this key before any transactional reads makes concurrent writers acquire
    their per-draft locks in the same order, even when model output ordering
    differs.  Boundary validation stays here so sorting cannot mask the
    strict ready-output errors handled by ``_prepare_draft``.
    """

    payload = draft.payload
    _assert_identity_boundary_is_decidable(
        payload,
        allow_partial_archive=allow_partial_archive,
    )
    variants = payload.get("experimental_variants") or payload.get("variants") or ()
    has_physical_variants = any(isinstance(item, Mapping) for item in variants)
    if allow_partial_archive and not has_physical_variants:
        return stable_partial_archive_experiment_id(
            document_id=output.output.document_id,
            source_fingerprint=output.output.source_fingerprint,
            local_key=local_key,
            payload=payload,
        )
    return stable_draft_experiment_id(
        document_id=output.output.document_id,
        payload=payload,
    )


def _normalized_scope_kind(value: Any) -> str:
    kind = str(value or "").strip().casefold()
    return "parent" if kind in {"", "parent", "matrix"} else kind


def _collect_draft_source_labels(value: Any, labels: set[str]) -> None:
    """Collect response-local Source labels without trusting model IDs."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().casefold()
            if normalized in {
                "source_label",
                "source_labels",
                "binding_source_labels",
                "variant_binding_source_labels",
                "test_binding_source_labels",
            }:
                values = nested if isinstance(nested, (list, tuple, set)) else (nested,)
                labels.update(
                    str(item).strip()
                    for item in values
                    if str(item).strip()
                )
            else:
                _collect_draft_source_labels(nested, labels)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _collect_draft_source_labels(nested, labels)


def _draft_source_keys(
    output: ReconciledPaperExperimentOutput,
    draft: PaperExperimentDraft,
) -> set[tuple[str, str]]:
    labels = set(draft.source_labels)
    _collect_draft_source_labels(draft.payload, labels)
    refs: set[tuple[str, str]] = set()
    for label in labels:
        source = output.output.source_labels.get(label)
        if not isinstance(source, Mapping):
            continue
        source_kind = str(source.get("source_kind") or "").strip()
        source_ref = str(source.get("source_ref") or "").strip()
        if source_kind and source_ref:
            refs.add((source_kind, source_ref))
    return refs


def _revision_source_keys(revision: PaperExperimentRevision) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    owners = (
        revision,
        *revision.variants,
        *revision.test_conditions,
        *revision.measurements,
        *revision.comparisons,
        *revision.reported_interpretations,
    )
    for owner in owners:
        for field_name in ("source_refs", "binding_source_refs"):
            for source in getattr(owner, field_name, ()):
                source_kind = str(getattr(source, "source_kind", "")).strip()
                source_ref = str(getattr(source, "source_ref", "")).strip()
                if source_kind and source_ref:
                    refs.add((source_kind, source_ref))
    return refs


def _variant_labels_from_payload(payload: Mapping[str, Any]) -> set[str]:
    variants = payload.get("experimental_variants") or payload.get("variants") or ()
    return {
        str(item.get("variant_label") or "").strip().casefold()
        for item in variants
        if isinstance(item, Mapping) and str(item.get("variant_label") or "").strip()
    }


def _variant_labels_from_revision(revision: PaperExperimentRevision) -> set[str]:
    return {
        item.variant_label.strip().casefold()
        for item in revision.variants
        if item.variant_label.strip()
    }


def _scope_metadata_from_revision(revision: PaperExperimentRevision) -> Mapping[str, Any]:
    for issue in revision.unresolved_issues:
        if not isinstance(issue, Mapping):
            continue
        metadata = issue.get("boundary_scope")
        if isinstance(metadata, Mapping):
            return metadata
    return {}


def _same_scope_selector(left: Any, right: Any) -> bool:
    if not isinstance(left, Mapping):
        return not right
    if not isinstance(right, Mapping):
        return False
    return _canonical_identity_value(left) == _canonical_identity_value(right)


def _is_reusable_revision_candidate(
    *,
    output: ReconciledPaperExperimentOutput,
    draft: PaperExperimentDraft,
    payload: Mapping[str, Any],
    stored: StoredPaperExperimentRevision,
) -> bool:
    """Match a reread to one prior physical experiment conservatively.

    The content hash remains the fast path.  This fallback exists for a
    legitimate reread that adds context or only returns the Objective-relevant
    subset of variants.  It requires both variant and Source lineage overlap;
    an ambiguous or disjoint candidate is deliberately left for manual
    reconciliation instead of being assigned another experiment's identity.
    """

    revision = stored.revision
    if revision.identity_status == "unknown":
        return False
    current_variants = _variant_labels_from_payload(payload)
    previous_variants = _variant_labels_from_revision(revision)
    if not current_variants or not previous_variants:
        return False
    if not (
        current_variants <= previous_variants
        or previous_variants <= current_variants
    ):
        return False
    current_design = str(payload.get("design_type") or "unknown").strip().casefold()
    previous_design = str(revision.design_type or "unknown").strip().casefold()
    if (
        current_design != "unknown"
        and previous_design != "unknown"
        and current_design != previous_design
    ):
        return False
    current_scope = _normalized_scope_kind(payload.get("scope_kind"))
    previous_metadata = _scope_metadata_from_revision(revision)
    previous_scope = _normalized_scope_kind(previous_metadata.get("scope_kind"))
    if current_scope != previous_scope:
        return False
    current_selector = payload.get("scope_selector")
    previous_selector = previous_metadata.get("scope_selector")
    if current_selector is not None and not _same_scope_selector(
        current_selector, previous_selector
    ):
        return False
    if current_scope in _PHYSICAL_SPLIT_KINDS:
        # Boundary evidence is intentionally conservative.  The exact content
        # hash handles unchanged splits; a changed split must be reconciled
        # explicitly rather than attached to another split by labels alone.
        return False
    current_sources = _draft_source_keys(output, draft)
    previous_sources = _revision_source_keys(revision)
    if not current_sources or not previous_sources:
        return False
    return bool(
        current_sources & previous_sources
        and (
            current_sources <= previous_sources
            or previous_sources <= current_sources
        )
    )


async def _resolve_experiment_identity(
    *,
    repository: PaperExperimentRepository,
    output: ReconciledPaperExperimentOutput,
    draft: PaperExperimentDraft,
    document_id: str,
    payload: Mapping[str, Any],
    transaction: RepositoryTransaction | None,
) -> tuple[str, StoredPaperExperimentRevision | None]:
    """Reuse one prior identity when a bounded reread changes its content."""

    content_identity = stable_draft_experiment_id(
        document_id=document_id,
        payload=payload,
    )
    list_latest = getattr(repository, "list_latest_for_document", None)
    if not callable(list_latest):
        # Implementations without the candidate-list operation cannot perform
        # content-based identity reuse.  The single read also takes the
        # transaction-scoped identity lock in the PostgreSQL repository.
        latest = await _repository_call(
            repository.read_latest_revision,
            content_identity,
            transaction=transaction,
        )
        return content_identity, latest

    # Inspect candidates before taking any identity lock.  If we lock the
    # content hash first and only later discover that the draft reuses another
    # identity, two concurrent writes can acquire those two locks in opposite
    # orders.  The final read below acquires exactly one lock: the identity
    # that this draft will actually write.
    candidates = await _repository_call(
        list_latest,
        document_id,
        transaction=transaction,
    )
    exact = next(
        (
            item
            for item in candidates
            if isinstance(item, StoredPaperExperimentRevision)
            and item.revision.experiment_id == content_identity
        ),
        None,
    )
    if exact is not None:
        latest = await _repository_call(
            repository.read_latest_revision,
            content_identity,
            transaction=transaction,
        )
        return content_identity, latest

    matches = tuple(
        item
        for item in candidates
        if isinstance(item, StoredPaperExperimentRevision)
        and _is_reusable_revision_candidate(
            output=output,
            draft=draft,
            payload=payload,
            stored=item,
        )
    )
    if len(matches) > 1:
        raise ValueError(
            "multiple prior PaperExperiment identities match this reread; "
            "manual boundary reconciliation is required"
        )
    if matches:
        matched = matches[0]
        matched_identity = matched.revision.experiment_id
        latest = await _repository_call(
            repository.read_latest_revision,
            matched_identity,
            transaction=transaction,
        )
        return matched_identity, latest

    latest = await _repository_call(
        repository.read_latest_revision,
        content_identity,
        transaction=transaction,
    )
    return content_identity, latest


def same_revision_content(
    left: PaperExperimentRevision,
    right: PaperExperimentRevision,
) -> bool:
    left_record = left.to_record()
    right_record = right.to_record()
    for record in (left_record, right_record):
        record.pop("experiment_version", None)
        record.pop("experiment_id", None)
    return left_record == right_record


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def _finalize_revision(
    revision: PaperExperimentRevision,
) -> tuple[PaperExperimentRevision, tuple[str, ...]]:
    """Recompute comparison state only after formal Source binding."""

    measurements = {item.measurement_key: item for item in revision.measurements}
    finalized: list[ExperimentComparison] = []
    diagnostics: list[str] = []
    for comparison in revision.comparisons:
        reasons = list(comparison.reasons)
        selected = [
            measurements[key]
            for key in (
                *comparison.baseline_measurement_keys,
                *comparison.target_measurement_keys,
            )
            if key in measurements
        ]
        baseline = [
            measurements[key]
            for key in comparison.baseline_measurement_keys
            if key in measurements
        ]
        target = [
            measurements[key]
            for key in comparison.target_measurement_keys
            if key in measurements
        ]
        numbers = [
            (_numeric_value(item.value if item.value is not None else item.result_text), item.unit)
            for item in (*baseline, *target)
        ]
        units = {str(unit or "").strip().casefold() for _, unit in numbers}
        valid = bool(
            selected
            and len(baseline) == 1
            and len(target) == 1
            and all(item.binding_status == "direct" for item in selected)
            and len(units) == 1
            and "" not in units
            and all(number is not None for number, _ in numbers)
        )
        if not valid:
            reasons.append(
                "Comparison could not be finalized after formal variant/test/source binding."
            )
            diagnostics.append(
                f"comparison {comparison.comparison_key} was downgraded after binding"
            )
            finalized.append(
                replace(
                    comparison,
                    direction="unknown",
                    status="insufficient_context",
                    relation_status="uncertain",
                    attribution_scope="undetermined",
                    reasons=tuple(dict.fromkeys(reasons)),
                )
            )
            continue
        baseline_value = numbers[0][0]
        target_value = numbers[1][0]
        assert baseline_value is not None and target_value is not None
        direction = (
            "increase"
            if target_value > baseline_value
            else "decrease"
            if target_value < baseline_value
            else "no_change"
        )
        factors = tuple(comparison.changed_variables)
        attribution = "joint_effect" if len(factors) > 1 else "association_only"
        finalized.append(
            replace(
                comparison,
                direction=direction,
                status="ready",
                relation_status="direct" if comparison.basis == "reported" else "derived",
                attribution_scope=attribution,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )
    finalized_revision = replace(revision, comparisons=tuple(finalized))
    return finalized_revision, tuple(dict.fromkeys(diagnostics))


def _build_selection(
    *,
    collection_id: str,
    objective: ResearchObjective,
    analysis_version: int,
    revision: PaperExperimentRevision,
    selection_slice: _SelectionSlice,
) -> ObjectiveExperimentSelection:
    factor_label = ", ".join(selection_slice.factor_key)
    selected_targets = {
        *(f"measurements/{key}" for key in selection_slice.measurement_keys),
        *(f"comparisons/{key}" for key in selection_slice.comparison_keys),
    }
    unresolved = tuple(
        str(item.get("description") or "").strip()
        for item in revision.unresolved_issues
        if str(item.get("description") or "").strip()
        and (
            str(item.get("target_ref") or "") in selected_targets
            or str(item.get("target_ref") or "") == "experiment"
        )
    )
    return ObjectiveExperimentSelection(
        selection_id=_stable_id(
            "sel",
            collection_id,
            objective.objective_id,
            analysis_version,
            revision.experiment_id,
            revision.experiment_version,
            selection_slice.outcome.casefold(),
            selection_slice.factor_key,
        ),
        objective_id=objective.objective_id,
        analysis_version=analysis_version,
        experiment_id=revision.experiment_id,
        experiment_version=revision.experiment_version,
        outcome=selection_slice.outcome,
        measurement_keys=selection_slice.measurement_keys,
        comparison_keys=selection_slice.comparison_keys,
        missing_context=unresolved,
        reasons=(
            "Fixed to the source-grounded PaperExperiment revision for this analysis.",
            (
                f"Selected comparisons for changed factors: {factor_label}."
                if factor_label
                else "Selected reported measurements; no relevant comparison was recovered."
            ),
        ),
    )


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
        experiment_outputs: Sequence[ReconciledPaperExperimentOutput],
        partial_experiment_outputs: Sequence[ReconciledPaperExperimentOutput] = (),
        allow_finding: bool = True,
        created_by: str | None = None,
        transaction: RepositoryTransaction | None = None,
    ) -> ExperimentAnalysisWriteResult:
        """Prepare and commit revisions, selections, groups, and Findings."""

        prepared = await self._prepare_experiment_selections(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            experiment_outputs=experiment_outputs,
            partial_experiment_outputs=partial_experiment_outputs,
            include_selections=allow_finding,
            created_by=created_by,
            transaction=transaction,
        )
        if allow_finding and prepared.selections:
            synthesis = self.finding_synthesis_service.synthesize(
                collection_id=collection_id,
                objective=objective,
                analysis_version=analysis.analysis_version,
                revisions=prepared.revisions,
                selections=prepared.selections,
            )
        else:
            synthesis = _EmptySynthesis()
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
            post_bind_diagnostics=prepared.post_bind_diagnostics,
        )

    async def write_single_experiment_revision(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiment_output: ReconciledPaperExperimentOutput,
        create_selection: bool,
        created_by: str | None = None,
        transaction: RepositoryTransaction | None = None,
    ) -> ExperimentAnalysisWriteResult:
        """Write one Agent-authored experiment graph and synthesize its Findings.

        Agent authoring deliberately shares the same preparation, identity,
        binding, and repository transaction as automatic analysis.  The only
        difference is the graph scope: one reconciled output and, when the
        Objective has an active analysis, its explicit Selection.
        """

        prepared = await self._prepare_experiment_selections(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            experiment_outputs=(experiment_output,),
            partial_experiment_outputs=(),
            include_selections=create_selection,
            created_by=created_by,
            transaction=transaction,
        )
        synthesis = (
            self.finding_synthesis_service.synthesize(
                collection_id=collection_id,
                objective=objective,
                analysis_version=analysis.analysis_version,
                revisions=prepared.revisions,
                selections=prepared.selections,
            )
            if create_selection and prepared.selections
            else _EmptySynthesis()
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
            post_bind_diagnostics=prepared.post_bind_diagnostics,
        )

    async def _prepare_experiment_selections(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        experiment_outputs: Sequence[ReconciledPaperExperimentOutput],
        partial_experiment_outputs: Sequence[ReconciledPaperExperimentOutput],
        include_selections: bool,
        created_by: str | None,
        transaction: RepositoryTransaction | None,
    ) -> _PreparedExperimentSelections:
        if objective.collection_id != collection_id:
            raise ValueError("experiment analysis objective belongs to another collection")
        if (
            analysis.collection_id != collection_id
            or analysis.objective_id != objective.objective_id
        ):
            raise ValueError("experiment analysis snapshot does not match objective")

        revisions: list[PaperExperimentRevision] = []
        selections: list[ObjectiveExperimentSelection] = []
        diagnostics: dict[str, list[str]] = {}
        identity_owners: dict[tuple[str, str], tuple[str, str, str]] = {}
        prepared_by_position: dict[
            tuple[int, int],
            tuple[
                PaperExperimentRevision,
                tuple[ObjectiveExperimentSelection, ...],
                tuple[str, ...],
            ],
        ] = {}
        # PostgreSQL's transaction-scoped advisory lock is acquired inside
        # ``read_latest_revision``.  A concurrent analysis may contain the
        # same Drafts in a different response order, so construct all work
        # items first and acquire those locks in one deterministic order.
        work_items: list[tuple[str, int, int, Any, bool, bool, Any, str]] = []
        output_specs = (
            *[(item, include_selections, False) for item in experiment_outputs],
            *[(item, False, True) for item in partial_experiment_outputs],
        )
        # Serialize all identity resolution for each source document before
        # taking the finer-grained content-identity locks below.  This covers
        # rereads whose content hash changed but whose lineage resolves to an
        # existing physical experiment, and locks documents in one global
        # order to avoid cross-document deadlocks.
        if transaction is not None:
            document_ids = sorted(
                {
                    output.output.document_id
                    for output, _, _ in output_specs
                }
            )
            for document_id in document_ids:
                await _repository_call(
                    self.paper_experiment_repository.lock_document,
                    document_id,
                    transaction=transaction,
                )
        for output_index, (
            output,
            output_include_selections,
            allow_partial_archive,
        ) in enumerate(output_specs):
            for draft_index, (draft, local_key) in enumerate(
                zip(
                    output.output.experiments,
                    output.accepted_experiment_keys,
                    strict=True,
                )
            ):
                lock_identity = _advisory_lock_identity_for_draft(
                    output=output,
                    draft=draft,
                    local_key=local_key,
                    allow_partial_archive=allow_partial_archive,
                )
                work_items.append(
                    (
                        lock_identity,
                        output_index,
                        draft_index,
                        output,
                        output_include_selections,
                        allow_partial_archive,
                        draft,
                        local_key,
                    )
                )

        for (
            _lock_identity,
            _output_index,
            _draft_index,
            output,
            output_include_selections,
            allow_partial_archive,
            draft,
            local_key,
        ) in sorted(work_items, key=lambda item: item[:3]):
            revision, revision_selections, revision_diagnostics = (
                await self._prepare_draft(
                    output=output,
                    draft=draft,
                    local_key=local_key,
                    collection_id=collection_id,
                    objective=objective,
                    analysis_version=analysis.analysis_version,
                    include_selections=output_include_selections,
                    allow_partial_archive=allow_partial_archive,
                    created_by=created_by,
                    transaction=transaction,
                )
            )
            identity_key = (revision.document_id, revision.experiment_id)
            owner = (
                output.output.document_id,
                local_key,
                str(draft.payload.get("scope_kind") or "parent")
                .strip()
                .casefold(),
            )
            previous_owner = identity_owners.get(identity_key)
            if previous_owner is not None and previous_owner[:2] != owner[:2]:
                raise ValueError(
                    "experiment identity collision requires manual boundary "
                    "reconciliation: "
                    f"{identity_key[1]} is used by {previous_owner[1]!r} "
                    f"and {owner[1]!r}"
                )
            identity_owners.setdefault(identity_key, owner)
            prepared_by_position[(_output_index, _draft_index)] = (
                revision,
                revision_selections,
                revision_diagnostics,
            )

        # Lock acquisition follows the stable identity order above, while the
        # returned graph retains the caller/model order for API compatibility.
        for position in sorted(prepared_by_position):
            revision, revision_selections, revision_diagnostics = prepared_by_position[
                position
            ]
            revisions.append(revision)
            selections.extend(revision_selections)
            if revision_diagnostics:
                diagnostics.setdefault(revision.document_id, []).extend(
                    revision_diagnostics
                )

        return _PreparedExperimentSelections(
            revisions=tuple(revisions),
            selections=tuple(selections),
            post_bind_diagnostics={
                document_id: tuple(dict.fromkeys(items))
                for document_id, items in diagnostics.items()
            },
        )

    async def _prepare_draft(
        self,
        *,
        output: ReconciledPaperExperimentOutput,
        draft: PaperExperimentDraft,
        local_key: str,
        collection_id: str,
        objective: ResearchObjective,
        analysis_version: int,
        include_selections: bool,
        allow_partial_archive: bool,
        created_by: str | None,
        transaction: RepositoryTransaction | None,
    ) -> tuple[
        PaperExperimentRevision,
        tuple[ObjectiveExperimentSelection, ...],
        tuple[str, ...],
    ]:
        payload = dict(draft.payload)
        document_id = output.output.document_id
        source_fingerprint = output.output.source_fingerprint
        _assert_identity_boundary_is_decidable(
            payload,
            allow_partial_archive=allow_partial_archive,
        )
        variants = payload.get("experimental_variants") or payload.get("variants") or ()
        has_physical_variants = any(
            isinstance(item, Mapping) for item in variants
        )
        if has_physical_variants or not allow_partial_archive:
            # Keep the strict formal-identity path unchanged.  In particular,
            # an incomplete ready Draft must still fail instead of being
            # silently downgraded into an archive.
            experiment_id, latest = await _resolve_experiment_identity(
                repository=self.paper_experiment_repository,
                output=output,
                draft=draft,
                document_id=document_id,
                payload=payload,
                transaction=transaction,
            )
        else:
            experiment_id = stable_partial_archive_experiment_id(
                document_id=document_id,
                source_fingerprint=source_fingerprint,
                local_key=local_key,
                payload=payload,
            )
            latest = await _repository_call(
                self.paper_experiment_repository.read_latest_revision,
                experiment_id,
                transaction=transaction,
            )
        candidate_version = (
            latest.revision.experiment_version + 1 if latest is not None else 1
        )
        single_output = ReconciledPaperExperimentOutput(
            output=replace(output.output, experiments=(draft,)),
            accepted_experiment_keys=(local_key,),
            audit_issues=output.audit_issues,
        )
        candidate = bind_model_output(
            single_output,
            experiment_ids=(experiment_id,),
            experiment_versions=(candidate_version,),
            document_id=document_id,
            source_fingerprint=source_fingerprint,
        )[0]
        finalized, diagnostics = _finalize_revision(candidate)
        if (
            allow_partial_archive
            and str(payload.get("scope_kind") or "unknown").strip().casefold()
            == "unknown"
        ):
            # Keep an auditable archive record without presenting its unresolved
            # boundary as an identified reusable experiment. Partial outputs
            # never create selections, so this identity cannot feed a Finding.
            finalized = replace(finalized, identity_status="unknown")
        if latest is not None and same_revision_content(finalized, latest.revision):
            revision = latest.revision
        else:
            revision = finalized

        selections: tuple[ObjectiveExperimentSelection, ...] = ()
        # A revision may intentionally retain unrelated partial measurements.
        # Selection eligibility is decided per requested slice, not by the
        # aggregate binding status of every record in the revision.
        if include_selections:
            selections = tuple(
                _build_selection(
                    collection_id=collection_id,
                    objective=objective,
                    analysis_version=analysis_version,
                    revision=revision,
                    selection_slice=selection_slice,
                )
                for selection_slice in _selection_slices(revision, objective)
            )
        return revision, selections, diagnostics

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
            if comparison.status != "ready" or comparison.relation_status not in {
                "direct",
                "derived",
            }:
                continue
            measurements_by_key = {
                item.measurement_key: item for item in revision.measurements
            }
            comparison_measurements = [
                measurements_by_key.get(key)
                for key in (
                    *comparison.baseline_measurement_keys,
                    *comparison.target_measurement_keys,
                )
            ]
            if any(
                item is None or item.binding_status != "direct"
                for item in comparison_measurements
            ):
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
            and item.binding_status == "direct"
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
