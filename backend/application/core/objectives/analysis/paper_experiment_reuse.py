"""Conservative reuse of all stored experiments covering a routed paper read."""

from __future__ import annotations

from typing import Sequence

from application.core.objectives.analysis.experiment_analysis_writer import (
    _normalized_term,
    _selection_slices,
    _term_matches,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    PaperExperimentSourceBundle,
)
from domain.core.paper_experiment import PaperExperimentRevision
from domain.core.research_objective import ResearchObjective
from repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)


def reusable_paper_experiments(
    candidates: Sequence[StoredPaperExperimentRevision],
    *,
    objective: ResearchObjective,
    bundle: PaperExperimentSourceBundle,
) -> tuple[PaperExperimentRevision, ...]:
    """Reuse fixed facts only when the current read can be fully accounted for.

    Free-text constraints require fresh scientific assessment. Missing source
    coverage or any unresolved experiment also returns control to extraction;
    a single matching result must not hide other experiments in the paper.
    """
    if not candidates or not bundle.source_catalog or bundle.omitted_source_refs:
        return ()
    if objective.constraints:
        return ()
    current_sources = {
        (str(item["source_kind"]), str(item["source_ref"])): str(item["quote"]).strip()
        for item in bundle.source_catalog.values()
    }
    covered: set[tuple[str, str]] = set()
    outcomes: set[str] = set()
    revisions: list[PaperExperimentRevision] = []
    for stored in candidates:
        revision = stored.revision
        if (
            stored.archived_at is not None
            or revision.document_id != bundle.document_id
            or revision.source_fingerprint != bundle.source_fingerprint
            or revision.identity_status == "unknown"
            or any("boundary_scope" not in issue for issue in revision.unresolved_issues)
        ):
            return ()
        material_values = {
            _normalized_term(attribute.value)
            for variant in revision.variants
            for attribute in variant.subject_attributes
        }
        if any(_normalized_term(material) not in material_values for material in objective.material_scope):
            return ()
        slices = _selection_slices(revision, objective)
        if not slices or any(
            not any(
                selection.comparison_keys
                and any(_term_matches(factor, variable) for factor in selection.factor_key)
                for selection in slices
            )
            for variable in objective.variables
        ):
            return ()
        outcomes.update(_normalized_term(item.outcome) for item in slices)
        owners = (
            revision, *revision.variants, *revision.test_conditions,
            *revision.measurements, *revision.comparisons,
            *revision.reported_interpretations,
        )
        for owner in owners:
            for field_name in ("source_refs", "binding_source_refs"):
                for source in getattr(owner, field_name, ()):
                    key = (source.source_kind, source.source_ref)
                    if (
                        source.document_id != bundle.document_id
                        or source.source_fingerprint != bundle.source_fingerprint
                        or current_sources.get(key) != source.quote.strip()
                    ):
                        return ()
                    covered.add(key)
        revisions.append(revision)
    if covered != set(current_sources) or not {
        _normalized_term(item) for item in objective.outcomes
    } <= outcomes:
        return ()
    return tuple(revisions)
