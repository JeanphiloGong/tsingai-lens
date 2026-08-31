"""Deterministic collection-wide paper screening for one Research Objective."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Protocol

from application.core.objectives import property_matching
from domain.core import PaperResearchMap


ObjectiveScopeClassification = Literal[
    "likely_relevant",
    "needs_inspection",
    "confidently_out_of_scope",
]


class ObjectiveScopeQuestion(Protocol):
    """Scientific question fields required for Paper Map screening."""

    material_scope: Iterable[str]
    variables: Iterable[str]
    outcomes: Iterable[str]


@dataclass(frozen=True)
class ObjectiveScopeDecision:
    """One Paper Map's screening disposition for one Objective."""

    document_id: str
    classification: ObjectiveScopeClassification
    reason: str
    doc_role: str
    map_status: str
    map_limitations: tuple[str, ...]
    support_basis: tuple[str, ...]
    is_seed: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "classification": self.classification,
            "reason": self.reason,
            "doc_role": self.doc_role,
            "map_status": self.map_status,
            "map_limitations": list(self.map_limitations),
            "support_basis": list(self.support_basis),
            "is_seed": self.is_seed,
        }


@dataclass(frozen=True)
class ObjectiveScopePreview:
    """Complete mapped-paper screening result; support remains navigation only."""

    decisions: tuple[ObjectiveScopeDecision, ...]
    support_is_evidence: bool = False

    @property
    def recommended_document_ids(self) -> tuple[str, ...]:
        return tuple(
            item.document_id
            for item in self.decisions
            if item.classification == "likely_relevant"
        )

    @property
    def review_document_ids(self) -> tuple[str, ...]:
        return tuple(
            item.document_id
            for item in self.decisions
            if item.classification == "needs_inspection"
        )

    @property
    def excluded_document_ids(self) -> tuple[str, ...]:
        return tuple(
            item.document_id
            for item in self.decisions
            if item.classification == "confidently_out_of_scope"
        )

    @property
    def counts(self) -> dict[str, int]:
        return {
            "likely_relevant": len(self.recommended_document_ids),
            "needs_inspection": len(self.review_document_ids),
            "confidently_out_of_scope": len(self.excluded_document_ids),
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "recommended_document_ids": list(self.recommended_document_ids),
            "review_document_ids": list(self.review_document_ids),
            "excluded_document_ids": list(self.excluded_document_ids),
            "decisions": [item.to_record() for item in self.decisions],
            "support_is_evidence": self.support_is_evidence,
        }


def screen_objective_scope(
    paper_maps: Iterable[PaperResearchMap],
    *,
    objective: ObjectiveScopeQuestion,
) -> ObjectiveScopePreview:
    """Classify every supplied Paper Map exactly once without extracting Evidence."""

    seed_document_ids = set(getattr(objective, "seed_document_ids", ()))
    explicitly_excluded_ids = set(
        getattr(objective, "excluded_document_ids", ())
    )
    decisions: list[ObjectiveScopeDecision] = []
    seen_document_ids: set[str] = set()
    for paper_map in paper_maps:
        if paper_map.document_id in seen_document_ids:
            raise ValueError(
                f"duplicate Paper Map document_id: {paper_map.document_id}"
            )
        seen_document_ids.add(paper_map.document_id)
        if paper_map.document_id in explicitly_excluded_ids:
            classification: ObjectiveScopeClassification = (
                "confidently_out_of_scope"
            )
            reason = "objective_explicit_exclusion"
            support_basis: tuple[str, ...] = ()
        else:
            classification, reason, support_basis = _classify(
                paper_map,
                objective,
            )
        decisions.append(
            ObjectiveScopeDecision(
                document_id=paper_map.document_id,
                classification=classification,
                reason=reason,
                doc_role=paper_map.doc_role,
                map_status=paper_map.map_status,
                map_limitations=tuple(paper_map.map_limitations),
                support_basis=support_basis,
                is_seed=paper_map.document_id in seed_document_ids,
            )
        )
    return ObjectiveScopePreview(decisions=tuple(decisions))


def _classify(
    paper_map: PaperResearchMap,
    question: ObjectiveScopeQuestion,
) -> tuple[ObjectiveScopeClassification, str, tuple[str, ...]]:
    relationship_matches: list[str] = []
    partial_scope = False
    for study in paper_map.studies:
        for relationship in study.relationships:
            if _scope_matches(
                question,
                study.material_scope,
                relationship.varied_factors,
                (relationship.outcome,),
            ):
                relationship_matches.append(relationship.relationship_id)
            elif _scope_partially_matches(
                question,
                study.material_scope,
                relationship.varied_factors,
                (relationship.outcome,),
            ):
                partial_scope = True
    if relationship_matches:
        return (
            "likely_relevant",
            "mapped_research_scope",
            tuple(relationship_matches),
        )

    review_matches: list[str] = []
    for field_name in ("synthesis_claims", "disputes", "evidence_gaps"):
        for position, item in enumerate(
            getattr(paper_map.review_synthesis, field_name)
        ):
            if _scope_matches(
                question,
                item.material_scope,
                item.variables,
                item.outcomes,
            ):
                review_matches.append(f"{field_name}:{position}")
            elif _scope_partially_matches(
                question,
                item.material_scope,
                item.variables,
                item.outcomes,
            ):
                partial_scope = True
    if review_matches:
        return (
            "likely_relevant",
            "review_author_judgment",
            tuple(review_matches),
        )

    citation_matches = tuple(
        f"citation_leads:{position}"
        for position, item in enumerate(paper_map.review_synthesis.citation_leads)
        if _scope_matches(
            question,
            item.material_scope,
            item.variables,
            item.outcomes,
        )
    )
    if citation_matches:
        return "needs_inspection", "citation_lead_only", citation_matches
    if paper_map.map_status != "sufficient":
        return "needs_inspection", "paper_map_incomplete", ()
    if partial_scope or _unresolved_scope_matches(paper_map, question):
        return "needs_inspection", "partial_scope_match", ()
    if _material_scope_conflicts(paper_map, question.material_scope):
        return "confidently_out_of_scope", "material_scope_conflict", ()
    if any(
        property_matching.objective_variable_theme(variable) is not None
        for variable in question.variables
    ):
        return "needs_inspection", "umbrella_scope_not_established", ()
    return "confidently_out_of_scope", "no_mapped_scope_match", ()


def _material_scope_conflicts(
    paper_map: PaperResearchMap,
    requested: Iterable[str],
) -> bool:
    requested_values = tuple(requested)
    if not requested_values:
        return False
    observed_scopes = [
        tuple(study.material_scope)
        for study in paper_map.studies
        if study.material_scope
    ]
    for field_name in (
        "synthesis_claims",
        "disputes",
        "evidence_gaps",
        "citation_leads",
    ):
        observed_scopes.extend(
            tuple(item.material_scope)
            for item in getattr(paper_map.review_synthesis, field_name)
            if item.material_scope
        )
    material_values = tuple(value for scope in observed_scopes for value in scope)
    specific_material_values = tuple(
        value
        for value in material_values
        if property_matching.material_scope_value_is_specific(value)
        or property_matching.material_scope_value_is_broad(value)
    )
    return bool(specific_material_values) and not any(
        property_matching.material_scope_value_is_broad(value)
        for value in specific_material_values
    ) and not any(
        _material_matches(requested_values, observed)
        for observed in observed_scopes
    )


def _scope_matches(
    question: ObjectiveScopeQuestion,
    materials: Iterable[str],
    variables: Iterable[str],
    outcomes: Iterable[str],
) -> bool:
    observed_variables = tuple(variables)
    observed_outcomes = tuple(outcomes)
    return (
        _material_matches(question.material_scope, tuple(materials))
        and all(
            any(
                property_matching.variable_matches_objective_scope(
                    observed,
                    requested,
                )
                for observed in observed_variables
            )
            for requested in question.variables
        )
        and all(
            _outcome_matches(requested, observed_outcomes)
            for requested in question.outcomes
        )
    )


def _scope_partially_matches(
    question: ObjectiveScopeQuestion,
    materials: Iterable[str],
    variables: Iterable[str],
    outcomes: Iterable[str],
) -> bool:
    observed_variables = tuple(variables)
    observed_outcomes = tuple(outcomes)
    if not _material_matches(question.material_scope, tuple(materials)):
        return False
    variable_match = any(
        property_matching.variable_matches_objective_scope(observed, requested)
        for requested in question.variables
        for observed in observed_variables
    )
    outcome_match = any(
        _outcome_matches(requested, observed_outcomes)
        for requested in question.outcomes
    )
    return variable_match or outcome_match


def _material_matches(requested: Iterable[str], observed: Iterable[str]) -> bool:
    requested_values = tuple(requested)
    observed_values = tuple(observed)
    return (
        not requested_values
        or not observed_values
        or any(
            property_matching.material_values_match_for_scope(left, right)
            for left in requested_values
            for right in observed_values
        )
    )


def _unresolved_scope_matches(
    paper_map: PaperResearchMap,
    question: ObjectiveScopeQuestion,
) -> bool:
    return any(
        _material_matches(question.material_scope, signal.material_scope)
        and (
            signal.signal_type == "variable"
            and any(
                property_matching.variable_matches_objective_scope(
                    signal.label,
                    requested,
                )
                for requested in question.variables
            )
            or signal.signal_type == "outcome"
            and any(
                _outcome_matches(requested, (signal.label,))
                for requested in question.outcomes
            )
        )
        for signal in paper_map.unresolved_signals
    )


def _outcome_matches(requested: str, observed: Iterable[str]) -> bool:
    return property_matching.property_matches_target_axes(
        requested,
        target_axes=tuple(observed),
    )


__all__ = [
    "ObjectiveScopeDecision",
    "ObjectiveScopePreview",
    "screen_objective_scope",
]
