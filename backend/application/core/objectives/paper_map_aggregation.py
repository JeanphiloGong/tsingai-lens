"""Aggregation and status evaluation for one Paper Map."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
import logging
import re
from typing import Any, TYPE_CHECKING

from application.core.objectives import property_matching
from application.core.objectives.discovery.signal_reconciliation import (
    PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT,
    PaperSignalReconciler,
    StructuredPaperSignalReconciliation,
)
from domain.core import PaperResearchMap, PaperResearchScope, PaperResearchSignal
from domain.core import (
    PaperResearchRelationship,
    ReviewKnowledgeItem,
    ReviewSynthesisMap,
)
if TYPE_CHECKING:
    from application.core.objectives.paper_map_extraction import PaperMapExtractionBudget

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict[str, Any]], None]
_SIGNAL_RECONCILIATION_SIGNAL_LIMIT = 12
_SIGNAL_RECONCILIATION_NEARBY_SOURCE_UNIT_DISTANCE = 12
_SOURCE_UNIT_POSITION_PATTERN = re.compile(r"source-unit-(\d+)")

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


@dataclass(frozen=True)
class PaperMapSignalInput:
    """A source-linked unresolved map signal passed between extraction stages."""

    signal: PaperResearchSignal
    source_contexts: tuple[dict[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        signal_record = self.signal.to_record()
        return {
            **{
                key: value
                for key, value in signal_record.items()
                if key not in {"source_refs", "reason"}
            },
            "sources": [
                {
                    "source_unit_id": source.get("source_unit_id"),
                    "section_path": source.get("section_path"),
                    "excerpt": source.get("excerpt"),
                }
                for source in self.source_contexts
            ],
        }


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
            source_unit_coverage=tuple(
                item
                for paper_map in window_maps
                for item in paper_map.source_unit_coverage
            ),
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

    def reconcile_signals(
        self,
        paper_map: PaperResearchMap,
        signal_inputs: list[PaperMapSignalInput],
        *,
        signal_reconciler: PaperSignalReconciler,
        extraction_budget: PaperMapExtractionBudget,
        progress_callback: ProgressCallback | None,
        document_position: int,
        document_count: int,
        document_title: str | None,
        source_filename: str | None,
    ) -> PaperResearchMap:
        unique_inputs = self._unique_signal_inputs(signal_inputs)
        if not unique_inputs:
            return paper_map

        signal_types = {item.signal.signal_type for item in unique_inputs}
        if len(signal_types) == 1:
            missing_role = "outcome" if "variable" in signal_types else "variable"
            reason = f"no {missing_role} signal was found in this paper"
            return replace(
                paper_map,
                unresolved_signals=tuple(
                    replace(item.signal, reason=reason) for item in unique_inputs
                ),
            )

        batches = self._build_signal_reconciliation_batches(
            paper_map.document_id,
            unique_inputs,
            signal_reconciler=signal_reconciler,
        )
        if not batches:
            return replace(
                paper_map,
                unresolved_signals=tuple(
                    replace(
                        item.signal,
                        reason=(
                            f"variable role '{item.signal.variable_role}' is not "
                            "eligible for relationship construction"
                            if not self._signal_is_relationship_eligible(item.signal)
                            else "no paper-scope bridge was found in this paper"
                        ),
                    )
                    for item in unique_inputs
                ),
            )

        notify_progress(
            progress_callback,
            phase="paper_research_map_started",
            current=document_position,
            total=document_count,
            unit="documents",
            message="Reconciling source-linked signals within one paper.",
            active_document_id=paper_map.document_id,
            active_document_title=document_title,
            active_source_filename=source_filename,
            active_operation="paper_reconciliation",
        )
        reconciled_studies: list[PaperResearchScope] = []
        linked_signal_ids: set[str] = set()
        unresolved_reasons: dict[str, str] = {}
        for batch_position, batch in enumerate(batches, start=1):
            if not extraction_budget.reserve(recovery=False):
                logger.warning(
                    "Paper signal reconciliation stopped at the document budget; "
                    "preserving unresolved signals document_id=%s batch_position=%s "
                    "batch_count=%s failure_kind=%s calls=%s max_calls=%s",
                    paper_map.document_id,
                    batch_position,
                    len(batches),
                    extraction_budget.failure_kind,
                    extraction_budget.calls,
                    extraction_budget.max_calls,
                )
                for remaining_batch in batches[batch_position - 1 :]:
                    for item in remaining_batch:
                        unresolved_reasons.setdefault(
                            item.signal.signal_id,
                            (
                                "paper-map judgment budget exhausted before "
                                "reconciliation"
                            ),
                        )
                break
            batch_studies, batch_unresolved = self._reconcile_signal_batch(
                batch,
                signal_reconciler=signal_reconciler,
                document_id=paper_map.document_id,
                batch_position=batch_position,
                batch_count=len(batches),
            )
            reconciled_studies.extend(batch_studies)
            batch_unresolved_ids = {
                signal.signal_id for signal in batch_unresolved
            }
            linked_signal_ids.update(
                item.signal.signal_id
                for item in batch
                if item.signal.signal_id not in batch_unresolved_ids
            )
            for signal in batch_unresolved:
                reason = signal.reason or "paper signal reconciliation failed"
                current_reason = unresolved_reasons.get(signal.signal_id)
                if current_reason is None or current_reason == (
                    "paper signal reconciliation failed"
                ):
                    unresolved_reasons[signal.signal_id] = reason

        unresolved_signals: list[PaperResearchSignal] = []
        for item in unique_inputs:
            signal_id = item.signal.signal_id
            if signal_id in linked_signal_ids:
                continue
            reason = unresolved_reasons.get(signal_id)
            if reason is None:
                if not self._signal_is_relationship_eligible(item.signal):
                    reason = (
                        f"variable role '{item.signal.variable_role}' is not "
                        "eligible for relationship construction"
                    )
                    unresolved_signals.append(replace(item.signal, reason=reason))
                    continue
                opposite_signals = (
                    other.signal
                    for other in unique_inputs
                    if other.signal.signal_type != item.signal.signal_type
                )
                conflicting_fields = self._unique_text_values(
                    field
                    for opposite in opposite_signals
                    for field in property_matching.paper_signal_context_conflicts(
                        (item.signal.to_record(), opposite.to_record())
                    )
                )
                reason = (
                    "Conflicting reconciliation context: "
                    f"{', '.join(conflicting_fields)}."
                    if conflicting_fields
                    else "no paper-scope bridge was found in this paper"
                )
            unresolved_signals.append(replace(item.signal, reason=reason))

        return replace(
            paper_map,
            studies=self.consolidate_studies(
                (*paper_map.studies, *reconciled_studies),
                document_id=paper_map.document_id,
            ),
            unresolved_signals=tuple(unresolved_signals),
        )

    @staticmethod
    def _signal_is_relationship_eligible(signal: PaperResearchSignal) -> bool:
        return signal.signal_type != "variable" or signal.variable_role in {
            "varied",
            "compared",
            "modeled",
        }

    @staticmethod
    def _signal_inputs_share_scope_evidence(
        left: PaperMapSignalInput,
        right: PaperMapSignalInput,
    ) -> bool:
        if property_matching.paper_signal_context_conflicts(
            (left.signal.to_record(), right.signal.to_record())
        ):
            return False

        left_source_keys = {
            (source.source_kind, source.source_ref)
            for source in left.signal.source_refs
        }
        right_source_keys = {
            (source.source_kind, source.source_ref)
            for source in right.signal.source_refs
        }
        if left_source_keys & right_source_keys:
            return True

        def source_positions(item: PaperMapSignalInput) -> tuple[int, ...]:
            positions: list[int] = []
            for source in item.source_contexts:
                source_unit_id = str(source.get("source_unit_id") or "")
                match = _SOURCE_UNIT_POSITION_PATTERN.search(source_unit_id)
                if match is not None:
                    positions.append(int(match.group(1)))
            return tuple(positions)

        left_positions = source_positions(left)
        right_positions = source_positions(right)
        if any(
            abs(left_position - right_position)
            <= _SIGNAL_RECONCILIATION_NEARBY_SOURCE_UNIT_DISTANCE
            for left_position in left_positions
            for right_position in right_positions
        ):
            return True

        placeholder_experiment_labels = {
            "n a",
            "none",
            "not reported",
            "not specified",
            "unknown",
            "uncertain",
        }
        left_experiment = property_matching.axis_key(left.signal.experiment_label)
        right_experiment = property_matching.axis_key(right.signal.experiment_label)
        if (
            left_experiment
            and right_experiment
            and left_experiment not in placeholder_experiment_labels
            and right_experiment not in placeholder_experiment_labels
            and property_matching.axis_values_match(
                left_experiment,
                right_experiment,
            )
        ):
            return True

        return any(
            property_matching.axis_values_match(left_value, right_value)
            for left_value in left.signal.process_context
            for right_value in right.signal.process_context
        )

    def _build_signal_reconciliation_batches(
        self,
        document_id: str,
        signal_inputs: tuple[PaperMapSignalInput, ...],
        *,
        signal_reconciler: PaperSignalReconciler,
    ) -> tuple[tuple[PaperMapSignalInput, ...], ...]:
        variables = tuple(
            item
            for item in signal_inputs
            if item.signal.signal_type == "variable"
            and self._signal_is_relationship_eligible(item.signal)
        )
        outcomes = tuple(
            item for item in signal_inputs if item.signal.signal_type == "outcome"
        )
        batches: list[tuple[PaperMapSignalInput, ...]] = []
        for outcome in outcomes:
            candidates = tuple(
                variable
                for variable in variables
                if self._signal_inputs_share_scope_evidence(variable, outcome)
            )
            current_variables: list[PaperMapSignalInput] = []
            for variable in candidates:
                candidate = (outcome, *current_variables, variable)
                payload = {
                    "document_id": document_id,
                    "signals": [item.to_payload() for item in candidate],
                }
                prompt_tokens = signal_reconciler.estimate_prompt_tokens(payload)
                if (
                    len(candidate) <= _SIGNAL_RECONCILIATION_SIGNAL_LIMIT
                    and prompt_tokens
                    <= PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT
                ):
                    current_variables.append(variable)
                    continue
                if current_variables:
                    batches.append((outcome, *current_variables))
                    current_variables = []

                pair = (outcome, variable)
                pair_payload = {
                    "document_id": document_id,
                    "signals": [item.to_payload() for item in pair],
                }
                pair_prompt_tokens = signal_reconciler.estimate_prompt_tokens(
                    pair_payload
                )
                if (
                    pair_prompt_tokens
                    <= PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT
                ):
                    current_variables.append(variable)
                    continue
                logger.warning(
                    "Paper signal pair exceeds reconciliation prompt limit; "
                    "retaining signals as unresolved document_id=%s outcome_signal_id=%s "
                    "variable_signal_id=%s prompt_tokens=%s limit=%s",
                    document_id,
                    outcome.signal.signal_id,
                    variable.signal.signal_id,
                    pair_prompt_tokens,
                    PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT,
                )
            if current_variables:
                batches.append((outcome, *current_variables))
        return tuple(batches)

    def _reconcile_signal_batch(
        self,
        signal_inputs: tuple[PaperMapSignalInput, ...],
        *,
        signal_reconciler: PaperSignalReconciler,
        document_id: str,
        batch_position: int,
        batch_count: int,
    ) -> tuple[tuple[PaperResearchScope, ...], tuple[PaperResearchSignal, ...]]:
        try:
            parsed = signal_reconciler.reconcile(
                {
                    "document_id": document_id,
                    "signals": [item.to_payload() for item in signal_inputs],
                }
            )
            return self._validate_signal_reconciliation(
                parsed,
                signal_inputs,
                document_id=document_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Paper map signal reconciliation batch failed; retaining batch "
                "signals document_id=%s batch_position=%s batch_count=%s "
                "signal_count=%s",
                document_id,
                batch_position,
                batch_count,
                len(signal_inputs),
                exc_info=True,
            )
            return (
                (),
                tuple(
                    replace(
                        item.signal,
                        reason="paper signal reconciliation failed",
                    )
                    for item in signal_inputs
                ),
            )

    @staticmethod
    def _unique_signal_inputs(
        signal_inputs: list[PaperMapSignalInput],
    ) -> tuple[PaperMapSignalInput, ...]:
        unique: list[PaperMapSignalInput] = []
        seen: set[str] = set()
        for item in signal_inputs:
            if item.signal.signal_id in seen:
                continue
            seen.add(item.signal.signal_id)
            unique.append(item)
        return tuple(unique)

    @classmethod
    def _validate_signal_reconciliation(
        cls,
        parsed: StructuredPaperSignalReconciliation,
        signal_inputs: tuple[PaperMapSignalInput, ...],
        *,
        document_id: str,
    ) -> tuple[tuple[PaperResearchScope, ...], tuple[PaperResearchSignal, ...]]:
        signals_by_id = {item.signal.signal_id: item.signal for item in signal_inputs}
        if len(signals_by_id) != len(signal_inputs):
            raise ValueError("paper signals do not have unique ids")

        linked_ids: set[str] = set()
        rejected_reasons_by_id: dict[str, str] = {}
        studies: list[PaperResearchScope] = []
        for parsed_study in parsed.studies:
            study_groups: list[
                tuple[
                    list[dict[str, Any]],
                    set[str],
                    dict[tuple[object, ...], int],
                ]
            ] = []
            for relationship in parsed_study.relationships:
                raw_signal_ids = tuple(
                    str(value).strip() for value in relationship.signal_ids
                )
                signal_ids = tuple(dict.fromkeys(raw_signal_ids))
                if any(signal_id not in signals_by_id for signal_id in signal_ids):
                    for signal_id in signals_by_id:
                        rejected_reasons_by_id.setdefault(
                            signal_id,
                            "paper signal reconciliation failed",
                        )
                    continue
                supplied_signals = tuple(
                    signals_by_id[signal_id] for signal_id in signal_ids
                )
                for signal in supplied_signals:
                    if cls._signal_is_relationship_eligible(signal):
                        continue
                    rejected_reasons_by_id.setdefault(
                        signal.signal_id,
                        f"variable role '{signal.variable_role}' is not eligible for "
                        "relationship construction",
                    )
                signals = tuple(
                    signal
                    for signal in supplied_signals
                    if cls._signal_is_relationship_eligible(signal)
                )
                signal_ids = tuple(signal.signal_id for signal in signals)
                variables = cls._unique_text_values(
                    signal.label
                    for signal in signals
                    if signal.signal_type == "variable"
                )
                outcomes = cls._unique_text_values(
                    signal.label
                    for signal in signals
                    if signal.signal_type == "outcome"
                )
                if not variables or len(outcomes) != 1:
                    for signal_id in signal_ids:
                        rejected_reasons_by_id.setdefault(
                            signal_id,
                            "paper signal relationship requires variables and one outcome",
                        )
                    continue
                if property_matching.outcome_label_requires_resolution(outcomes[0]):
                    for signal_id in signal_ids:
                        rejected_reasons_by_id.setdefault(
                            signal_id,
                            "outcome requires one specific measurable property",
                        )
                    continue
                context_conflicts = property_matching.paper_signal_context_conflicts(
                    signal.to_record() for signal in signals
                )
                if context_conflicts:
                    reason = (
                        "Conflicting reconciliation context: "
                        f"{', '.join(context_conflicts)}."
                    )
                    for signal_id in signal_ids:
                        rejected_reasons_by_id.setdefault(signal_id, reason)
                    continue
                relationship_record = {
                    "document_id": document_id,
                    "varied_factors": variables,
                    "outcome": outcomes[0],
                    "confidence": min(
                        relationship.confidence,
                        *(signal.confidence for signal in signals),
                    ),
                    "source_refs": [
                        ref.to_record()
                        for ref in unique_source_refs(
                            ref for signal in signals for ref in signal.source_refs
                        )
                    ],
                }
                relationship_key = (
                    tuple(sorted(value.casefold() for value in variables)),
                    outcomes[0].casefold(),
                    tuple(
                        sorted(
                            (ref["source_kind"], ref["source_ref"])
                            for ref in relationship_record["source_refs"]
                        )
                    ),
                )
                compatible_group = next(
                    (
                        group
                        for group in study_groups
                        if cls._signal_contexts_are_compatible(
                            tuple(
                                signals_by_id[signal_id]
                                for signal_id in group[1] | set(signal_ids)
                            )
                        )
                    ),
                    None,
                )
                if compatible_group is None:
                    compatible_group = ([], set(), {})
                    study_groups.append(compatible_group)
                existing_position = compatible_group[2].get(relationship_key)
                if existing_position is None:
                    compatible_group[2][relationship_key] = len(compatible_group[0])
                    compatible_group[0].append(relationship_record)
                else:
                    existing_record = compatible_group[0][existing_position]
                    existing_record["confidence"] = min(
                        existing_record["confidence"],
                        relationship_record["confidence"],
                    )
                compatible_group[1].update(signal_ids)

            for (
                study_relationships,
                study_signal_ids,
                _relationship_positions,
            ) in study_groups:
                repeated_signal_ids = study_signal_ids & linked_ids
                if any(
                    signals_by_id[signal_id].signal_type != "outcome"
                    for signal_id in repeated_signal_ids
                ):
                    for signal_id in study_signal_ids - linked_ids:
                        rejected_reasons_by_id.setdefault(
                            signal_id,
                            "paper variable signal cannot belong to multiple studies",
                        )
                    continue
                study_signals = tuple(
                    signals_by_id[signal_id] for signal_id in study_signal_ids
                )
                studies.append(
                    PaperResearchScope.from_mapping(
                        {
                            "document_id": document_id,
                            **cls._shared_signal_study_context(study_signals),
                            "relationships": study_relationships,
                            "confidence": min(
                                signal.confidence for signal in study_signals
                            ),
                        }
                    )
                )
                linked_ids.update(study_signal_ids)

        unresolved_by_id: dict[str, str] = {}
        for unresolved in parsed.unresolved_signals:
            signal_id = str(unresolved.signal_id).strip()
            if signal_id not in signals_by_id:
                continue
            if signal_id in linked_ids or signal_id in unresolved_by_id:
                continue
            unresolved_by_id[signal_id] = str(unresolved.reason).strip()
        for signal_id, reason in rejected_reasons_by_id.items():
            if signal_id in linked_ids or signal_id in unresolved_by_id:
                continue
            unresolved_by_id[signal_id] = reason
        for signal_id in signals_by_id:
            if signal_id in linked_ids or signal_id in unresolved_by_id:
                continue
            unresolved_by_id[signal_id] = "not linked in this candidate batch"
        return (
            tuple(studies),
            tuple(
                replace(signals_by_id[signal_id], reason=reason)
                for signal_id, reason in unresolved_by_id.items()
            ),
        )

    @classmethod
    def _signal_contexts_are_compatible(
        cls,
        signals: tuple[PaperResearchSignal, ...],
    ) -> bool:
        return not property_matching.paper_signal_context_conflicts(
            signal.to_record() for signal in signals
        )

    @classmethod
    def _shared_signal_study_context(
        cls,
        signals: tuple[PaperResearchSignal, ...],
    ) -> dict[str, Any]:
        if not cls._signal_contexts_are_compatible(signals):
            raise ValueError("paper research signals have conflicting contexts")

        def known_scalar(field_name: str, unknown_value: str | None = None) -> str | None:
            return next(
                (
                    str(value)
                    for signal in signals
                    if (value := getattr(signal, field_name))
                    and value != unknown_value
                ),
                None,
            )

        return {
            "experiment_label": known_scalar("experiment_label"),
            "design_type": known_scalar("design_type", "uncertain") or "uncertain",
            "claim_scope": known_scalar("claim_scope", "uncertain") or "uncertain",
            "material_scope": cls._unique_text_values(
                value for signal in signals for value in signal.material_scope
            ),
            "process_context": cls._unique_text_values(
                value for signal in signals for value in signal.process_context
            ),
        }

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


__all__ = ["PaperMapAggregator", "PaperMapAssessment", "PaperMapSignalInput", "notify_progress", "unique_source_refs"]
