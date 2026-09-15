"""Aggregation and status evaluation for one Paper Map."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
import logging
from typing import Any

from application.core.objectives import property_matching
from domain.core import PaperResearchMap, PaperResearchScope, PaperResearchSignal
from domain.core import (
    PaperResearchRelationship,
    ReviewKnowledgeItem,
    ReviewSynthesisMap,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict[str, Any]], None]
_EVIDENCE_DENSITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
_PAPER_MAP_PERSISTED_WARNING_LIMIT = 2


def unique_source_refs(values: Any) -> tuple[Any, ...]:
    """Keep the first occurrence of each source identity."""

    unique: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (value.source_kind, value.source_ref)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return tuple(unique)


@dataclass(frozen=True)
class PaperMapAssessment:
    status: str
    limitations: tuple[str, ...]
    expansion_focus: str | None = None


def notify_progress(
    progress_callback: ProgressCallback | None,
    **progress_detail: Any,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(progress_detail)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Research objective progress callback failed phase=%s",
            progress_detail.get("phase"),
        )


class PaperMapAggregator:
    """Merge window-level model observations into one document Paper Map."""


    def consolidate_window_maps(
        self,
        document_id: str,
        window_maps: list[PaperResearchMap],
        *,
        profile: Any,
    ) -> PaperResearchMap:
        doc_role = self._consolidate_doc_role(window_maps, profile=profile)
        studies = self.consolidate_studies(
            tuple(
                study
                for paper_map in window_maps
                for study in paper_map.studies
            ),
            document_id=document_id,
        )
        if doc_role == "review":
            studies = tuple(
                self._study_with_claim_scope(study, "uncertain")
                if study.claim_scope == "current_work"
                else study
                for study in studies
            )
        return PaperResearchMap(
            document_id=document_id,
            doc_role=doc_role,
            studies=studies,
            evidence_density=max(
                (paper_map.evidence_density for paper_map in window_maps),
                key=lambda value: _EVIDENCE_DENSITY_RANK.get(value, 0),
                default="unknown",
            ),
            confidence=max((paper_map.confidence for paper_map in window_maps), default=0.0),
            warnings=self._unique_text_values(
                warning for paper_map in window_maps for warning in paper_map.warnings
            )[:_PAPER_MAP_PERSISTED_WARNING_LIMIT],
            unresolved_signals=tuple({
                signal.signal_id: signal
                for paper_map in window_maps
                for signal in paper_map.unresolved_signals
            }.values()),
            source_unit_coverage=tuple({
                item.source_unit_id: item
                for paper_map in window_maps
                for item in paper_map.source_unit_coverage
            }.values()),
            review_synthesis=(
                self._consolidate_review_synthesis(
                    tuple(paper_map.review_synthesis for paper_map in window_maps)
                )
                if doc_role == "review"
                else ReviewSynthesisMap()
            ),
        )

    @classmethod
    def _consolidate_review_synthesis(
        cls,
        maps: tuple[ReviewSynthesisMap, ...],
    ) -> ReviewSynthesisMap:
        return ReviewSynthesisMap(
            **{
                field_name: cls._merge_review_knowledge_items(
                    tuple(
                        item
                        for review_map in maps
                        for item in getattr(review_map, field_name)
                    )
                )
                for field_name in (
                    "synthesis_claims",
                    "disputes",
                    "evidence_gaps",
                    "citation_leads",
                )
            }
        )

    @staticmethod
    def _merge_review_knowledge_items(
        items: tuple[ReviewKnowledgeItem, ...],
    ) -> tuple[ReviewKnowledgeItem, ...]:
        merged: list[ReviewKnowledgeItem] = []
        identities: dict[tuple[object, ...], int] = {}
        for item in items:
            identity = (
                item.content.casefold(),
                tuple(value.casefold() for value in item.material_scope),
                tuple(value.casefold() for value in item.variables),
                tuple(value.casefold() for value in item.outcomes),
                tuple(value.casefold() for value in item.conditions),
            )
            position = identities.get(identity)
            if position is None:
                identities[identity] = len(merged)
                merged.append(item)
                continue
            existing = merged[position]
            source_refs = tuple(
                dict.fromkeys((*existing.source_refs, *item.source_refs))
            )
            merged[position] = replace(
                existing,
                source_refs=source_refs,
                confidence=max(existing.confidence, item.confidence),
            )
        return tuple(merged)

    @staticmethod
    def _study_with_claim_scope(study: PaperResearchScope, claim_scope: str) -> PaperResearchScope:
        record = study.to_record()
        record.pop("study_id", None)
        record["claim_scope"] = claim_scope
        record["relationships"] = [
            {
                key: value
                for key, value in relationship.items()
                if key != "relationship_id"
            }
            for relationship in record["relationships"]
        ]
        return PaperResearchScope.from_mapping(record)

    @classmethod
    def consolidate_studies(
        cls,
        studies: tuple[PaperResearchScope, ...],
        *,
        document_id: str,
    ) -> tuple[PaperResearchScope, ...]:
        consolidated: list[PaperResearchScope] = []
        for study in studies:
            duplicate_position = next(
                (
                    position
                    for position, existing in enumerate(consolidated)
                    if cls._studies_are_duplicates(existing, study)
                ),
                None,
            )
            if duplicate_position is None:
                consolidated.append(study)
                continue
            consolidated[duplicate_position] = cls._merge_studies(
                consolidated[duplicate_position],
                study,
                document_id=document_id,
            )
        return tuple(consolidated)

    @classmethod
    def _studies_are_duplicates(
        cls,
        left: PaperResearchScope,
        right: PaperResearchScope,
    ) -> bool:
        if not cls._study_identity_matches(left, right):
            return False
        if cls._relationship_sets_overlap(left.relationships, right.relationships):
            return True
        shared_factor_set = any(
            cls._axis_collections_are_equivalent(
                left_relationship.varied_factors,
                right_relationship.varied_factors,
            )
            for left_relationship in left.relationships
            for right_relationship in right.relationships
        )
        if not shared_factor_set:
            return False
        if left.experiment_label and right.experiment_label:
            return True
        return bool(cls._study_source_keys(left) & cls._study_source_keys(right))

    @classmethod
    def _study_identity_matches(cls, left: PaperResearchScope, right: PaperResearchScope) -> bool:
        for field_name in ("design_type", "claim_scope"):
            left_value = getattr(left, field_name)
            right_value = getattr(right, field_name)
            if (
                left_value != "uncertain"
                and right_value != "uncertain"
                and left_value != right_value
            ):
                return False
        for field_name in ("experiment_label",):
            left_value = getattr(left, field_name)
            right_value = getattr(right, field_name)
            if (
                left_value
                and right_value
                and property_matching.axis_key(left_value)
                != property_matching.axis_key(right_value)
            ):
                return False
        for field_name in (
            "material_scope",
            "process_context",
        ):
            left_values = getattr(left, field_name)
            right_values = getattr(right, field_name)
            if (
                left_values
                and right_values
                and not cls._axis_collections_do_not_conflict(
                    left_values,
                    right_values,
                )
            ):
                return False

        if left.experiment_label and right.experiment_label:
            return True
        return bool(cls._study_source_keys(left) & cls._study_source_keys(right))

    @classmethod
    def _relationship_sets_overlap(
        cls,
        left: tuple[PaperResearchRelationship, ...],
        right: tuple[PaperResearchRelationship, ...],
    ) -> bool:
        return any(
            cls._relationships_are_duplicates(left_item, right_item)
            for left_item in left
            for right_item in right
        )

    @classmethod
    def _relationships_are_duplicates(
        cls,
        left: PaperResearchRelationship,
        right: PaperResearchRelationship,
    ) -> bool:
        return cls._axis_collections_are_equivalent(
            left.varied_factors,
            right.varied_factors,
        ) and property_matching.axis_values_match(left.outcome, right.outcome)

    @staticmethod
    def _axis_collections_do_not_conflict(
        left: tuple[str, ...],
        right: tuple[str, ...],
    ) -> bool:
        smaller, larger = sorted((left, right), key=len)
        return all(
            any(
                property_matching.axis_values_match(smaller_axis, larger_axis)
                for larger_axis in larger
            )
            for smaller_axis in smaller
        )

    @staticmethod
    def _study_source_keys(study: PaperResearchScope) -> set[tuple[str, str]]:
        return {
            (source_ref.source_kind, source_ref.source_ref)
            for relationship in study.relationships
            for source_ref in relationship.source_refs
        }

    @staticmethod
    def _axis_collections_are_equivalent(
        left: tuple[str, ...],
        right: tuple[str, ...],
    ) -> bool:
        return property_matching.axis_collections_are_equivalent(left, right)

    @classmethod
    def _merge_studies(
        cls,
        existing: PaperResearchScope,
        duplicate: PaperResearchScope,
        *,
        document_id: str,
    ) -> PaperResearchScope:
        relationships: list[PaperResearchRelationship] = []
        # A model can emit the same paper-local relationship more than once
        # using casing, punctuation, or an axis alias. Fold both sides through
        # one list so re-deriving stable IDs cannot turn duplicate facts into a
        # domain validation failure.
        for relationship in (*existing.relationships, *duplicate.relationships):
            duplicate_position = next(
                (
                    position
                    for position, current in enumerate(relationships)
                    if cls._relationships_are_duplicates(current, relationship)
                ),
                None,
            )
            if duplicate_position is None:
                relationships.append(relationship)
                continue
            current = relationships[duplicate_position]
            relationships[duplicate_position] = PaperResearchRelationship.from_mapping(
                {
                    "document_id": document_id,
                    "varied_factors": current.varied_factors,
                    "outcome": current.outcome,
                    "source_refs": [
                        source_ref.to_record()
                        for source_ref in unique_source_refs(
                            (*current.source_refs, *relationship.source_refs)
                        )
                    ],
                    "confidence": max(current.confidence, relationship.confidence),
                }
            )
        return PaperResearchScope.from_mapping(
            {
                "document_id": document_id,
                "experiment_label": existing.experiment_label
                or duplicate.experiment_label,
                "design_type": (
                    existing.design_type
                    if existing.design_type != "uncertain"
                    else duplicate.design_type
                ),
                "claim_scope": (
                    existing.claim_scope
                    if existing.claim_scope != "uncertain"
                    else duplicate.claim_scope
                ),
                "material_scope": cls._unique_text_values(
                    (*existing.material_scope, *duplicate.material_scope)
                ),
                "process_context": cls._unique_text_values(
                    (*existing.process_context, *duplicate.process_context)
                ),
                "relationships": [
                    {
                        key: value
                        for key, value in item.to_record().items()
                        if key != "relationship_id"
                    }
                    for item in relationships
                ],
                "confidence": max(existing.confidence, duplicate.confidence),
            },
        )

    @staticmethod
    def _consolidate_doc_role(window_maps: list[PaperResearchMap], *, profile: Any) -> str:
        profile_role = str(getattr(profile, "doc_type", "") or "").strip()
        if profile_role in {"experimental", "review", "mixed", "uncertain"}:
            return profile_role
        roles = {
            paper_map.doc_role for paper_map in window_maps if paper_map.doc_role != "uncertain"
        }
        if not roles:
            return "uncertain"
        if len(roles) == 1:
            return next(iter(roles))
        return "mixed"

    @staticmethod
    def _unique_text_values(values: Any) -> tuple[str, ...]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            unique.append(text)
        return tuple(unique)

    def assess(
        self,
        paper_map: PaperResearchMap,
        *,
        signals: tuple[PaperResearchSignal, ...],
        final: bool,
    ) -> PaperMapAssessment:
        owned_relationships = [
            relationship
            for study in paper_map.studies
            if study.claim_scope in {"current_work", "synthesis"}
            for relationship in study.relationships
            if not property_matching.outcome_label_requires_resolution(
                relationship.outcome
            )
        ]
        limitations: list[str] = []
        if not paper_map.coverage_complete:
            limitations.append("source_extraction_incomplete")
        has_review_judgment = paper_map.doc_role == "review" and any(
            (
                paper_map.review_synthesis.synthesis_claims,
                paper_map.review_synthesis.disputes,
                paper_map.review_synthesis.evidence_gaps,
            )
        )
        visible_signals = self.signals_unresolved_for_discovery(
            paper_map,
            (*signals, *paper_map.unresolved_signals),
        )
        has_unresolved_broad_outcome = any(
            signal.signal_type == "outcome"
            and property_matching.outcome_label_requires_resolution(signal.label)
            for signal in visible_signals
        )
        has_unresolved_outcome = any(
            signal.signal_type == "outcome" for signal in visible_signals
        )
        has_blocking_unresolved_outcome = (
            has_unresolved_broad_outcome
            or (not final and has_unresolved_outcome)
        )
        if (
            (owned_relationships or has_review_judgment)
            and not has_blocking_unresolved_outcome
            and paper_map.coverage_complete
        ):
            return PaperMapAssessment(
                status="sufficient",
                limitations=tuple(limitations),
            )

        has_variable = bool(owned_relationships) or any(
            signal.signal_type == "variable" for signal in visible_signals
        )
        has_outcome = bool(owned_relationships) or any(
            signal.signal_type == "outcome" for signal in visible_signals
        )
        has_broad_outcome = any(
            signal.signal_type == "outcome"
            and property_matching.outcome_label_requires_resolution(signal.label)
            for signal in visible_signals
        )
        has_unowned_relationship = any(
            study.relationships
            and study.claim_scope == "uncertain"
            for study in paper_map.studies
        )

        if not has_variable:
            limitations.append("missing_variable")
        if not has_outcome:
            limitations.append("missing_outcome")
        if has_broad_outcome:
            limitations.append("outcome_too_broad")
        if has_unowned_relationship:
            limitations.append("unclear_ownership")
        if has_variable and has_outcome and not has_broad_outcome:
            limitations.append("relationship_not_established")

        limitations = list(dict.fromkeys(limitations))
        if final or "source_extraction_incomplete" in limitations:
            return PaperMapAssessment(
                status="insufficient_map",
                limitations=tuple(limitations or ("missing_research_scope",)),
            )
        if has_broad_outcome:
            focus = "outcome_specificity"
        elif not has_outcome:
            focus = "missing_outcome"
        elif not has_variable:
            focus = "missing_variable"
        elif has_unowned_relationship:
            focus = "unclear_ownership"
        else:
            focus = "missing_scope"
        return PaperMapAssessment(
            status="needs_expansion",
            limitations=tuple(limitations or ("missing_research_scope",)),
            expansion_focus=focus,
        )

    @classmethod
    def drop_signals_resolved_by_relationships(
        cls,
        paper_map: PaperResearchMap,
    ) -> PaperResearchMap:
        unresolved_signals = tuple(
            signal
            for signal in paper_map.unresolved_signals
            if not cls._signal_is_resolved_by_relationships(paper_map, signal)
        )
        if unresolved_signals == paper_map.unresolved_signals:
            return paper_map
        return replace(paper_map, unresolved_signals=unresolved_signals)

    @classmethod
    def signals_unresolved_for_discovery(
        cls,
        paper_map: PaperResearchMap,
        signals: Iterable[PaperResearchSignal],
    ) -> tuple[PaperResearchSignal, ...]:
        unresolved: list[PaperResearchSignal] = []
        seen: set[str] = set()
        for signal in signals:
            if signal.signal_id in seen:
                continue
            seen.add(signal.signal_id)
            if not cls._signal_is_resolved_by_relationships(paper_map, signal):
                unresolved.append(signal)
        return tuple(unresolved)

    @staticmethod
    def _signal_is_resolved_by_relationships(
        paper_map: PaperResearchMap,
        signal: PaperResearchSignal,
    ) -> bool:
        signal_sources = {
            (source.source_kind, source.source_ref)
            for source in signal.source_refs
        }
        broad_outcome = (
            signal.signal_type == "outcome"
            and property_matching.outcome_label_requires_resolution(signal.label)
        )
        for study in paper_map.studies:
            if (
                signal.claim_scope != "uncertain"
                and study.claim_scope != signal.claim_scope
            ):
                continue
            for relationship in study.relationships:
                relationship_sources = {
                    (source.source_kind, source.source_ref)
                    for source in relationship.source_refs
                }
                sources_overlap = bool(signal_sources & relationship_sources)
                if signal.signal_type == "variable" and sources_overlap and any(
                    property_matching.axis_values_match(signal.label, factor)
                    for factor in relationship.varied_factors
                ):
                    return True
                if signal.signal_type != "outcome":
                    continue
                exact_match = property_matching.axis_values_match(
                    signal.label,
                    relationship.outcome,
                )
                family_match = property_matching.source_text_mentions_axis(
                    relationship.outcome,
                    signal.label,
                )
                expanded_match = broad_outcome and any(
                    property_matching.axis_values_match(
                        relationship.outcome,
                        expanded_axis,
                    )
                    or property_matching.source_text_mentions_axis(
                        relationship.outcome,
                        expanded_axis,
                    )
                    for expanded_axis in property_matching.broad_outcome_expansions(
                        signal.label
                    )
                )
                if sources_overlap and (
                    exact_match or family_match or expanded_match
                ):
                    return True
                if broad_outcome and (
                    expanded_match
                    or PaperMapAggregator._outcome_family_matches(
                        signal.label,
                        relationship.outcome,
                    )
                ):
                    return True
                # A broad paper-level theme may be stated in an Abstract and
                # resolved by a concrete, independently sourced Results axis.
                # Specific unlinked signals remain visible because they may
                # belong to another experiment or comparison in the paper.
                if broad_outcome and family_match:
                    return True
        return False

    @staticmethod
    def _outcome_family_matches(left: str, right: str) -> bool:
        left_key = property_matching.normalize_property_label(left) or ""
        right_key = property_matching.normalize_property_label(right) or ""
        left_words = set(left_key.split())
        right_words = set(right_key.split())
        if "mechanical" in left_words and "mechanical" in right_words:
            return bool(left_words & {"property", "properties"}) and bool(
                right_words & {"property", "properties"}
            )
        if any(token.startswith("microstructur") for token in left_words):
            return any(
                token.startswith("microstructur")
                or token.startswith(("grain", "martensite", "lamella", "phase"))
                for token in right_words
            )
        return False


__all__ = ["PaperMapAggregator", "PaperMapAssessment", "notify_progress", "unique_source_refs"]
