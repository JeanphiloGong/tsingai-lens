"""Model extraction and bounded recovery for one paper's Paper Map windows."""

from __future__ import annotations

from domain.core.research_objective import (
    PaperResearchRelationship, PaperResearchSourceRef, ReviewKnowledgeItem,
    build_paper_research_relationship, build_paper_research_scope, build_paper_research_signal,
)


from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field, replace
import json
import logging
import os
import re
from threading import Lock
from time import monotonic
from typing import Any

from openai import APIConnectionError, APIStatusError

from application.core.objectives import property_matching
from application.core.objectives.discovery.paper_understanding.paper_map_results import (
    StructuredPaperResearchMap,
    StructuredPaperResearchRelationship,
    StructuredPaperResearchScope,
    StructuredPaperResearchSignal,
    StructuredReviewSynthesisMap,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT,
    PaperResearchMapExtractor,
    _review_synthesis_only,
)
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
)
from application.core.objectives import paper_map_sources
from domain.source import SourceDocumentTree
from domain.core import (
    PaperResearchMap,
    PaperResearchScope,
    PaperResearchSignal,
    PaperSourceUnitCoverage,
    PaperSourceUnitCoverageStatus,
    ReviewSynthesisMap,
)

logger = logging.getLogger(__name__)

_PAPER_MAP_FRAGMENT_MIN_CHAR_LIMIT = 800
_DEFAULT_MAX_EXTRACTION_CONCURRENCY = 4
_DEFAULT_DOCUMENT_TIME_BUDGET_SECONDS = 300
_MIN_DOCUMENT_RECOVERY_CALLS = 4
_MAX_DOCUMENT_RECOVERY_CALLS = 16
_NUMBERED_CITATION_PATTERN = re.compile(
    r"\[(?:\s*\d{1,4}\s*(?:(?:,|[-\u2013])\s*\d{1,4}\s*)*)\]"
)
_NAMED_PRIOR_AUTHOR_PATTERN = re.compile(r"\bet\s+al\b", re.IGNORECASE)


@dataclass
class PaperMapExtractionBudget:
    """Per-document call and time budget for map extraction and recovery."""

    deadline: float
    max_calls: int
    max_recovery_calls: int
    calls: int = 0
    recovery_calls: int = 0
    failure_kind: str | None = None
    _lock: Any = field(default_factory=Lock, repr=False)

    def add_capacity(self, calls: int) -> None:
        if calls <= 0:
            return
        with self._lock:
            self.max_calls += calls

    def reserve(self, *, recovery: bool) -> bool:
        with self._lock:
            if monotonic() >= self.deadline:
                self.failure_kind = "document_time_budget_exhausted"
                return False
            if recovery and self.recovery_calls >= self.max_recovery_calls:
                self.failure_kind = "recovery_budget_exhausted"
                return False
            if self.calls >= self.max_calls:
                self.failure_kind = "document_call_budget_exhausted"
                return False
            self.calls += 1
            if recovery:
                self.recovery_calls += 1
            return True


def extract_window_payloads(
    *,
    collection_id: str,
    document_id: str,
    payloads: list[dict[str, Any]],
    paper_map_extractor: PaperResearchMapExtractor,
    extraction_budget: PaperMapExtractionBudget,
) -> tuple[
    tuple[tuple[PaperResearchMap, ...], tuple[PaperResearchSignal, ...]],
    ...,
]:
    if len(payloads) <= 1 or _max_extraction_concurrency() == 1:
        return tuple(
            _extract_window_batch(
                collection_id=collection_id,
                document_id=document_id,
                payload=payload,
                paper_map_extractor=paper_map_extractor,
                extraction_budget=extraction_budget,
            )
            for payload in payloads
        )

    with ThreadPoolExecutor(
        max_workers=min(_max_extraction_concurrency(), len(payloads)),
    ) as executor:
        futures = [
            executor.submit(
                copy_context().run,
                _extract_window_batch,
                collection_id=collection_id,
                document_id=document_id,
                payload=payload,
                paper_map_extractor=paper_map_extractor,
                extraction_budget=extraction_budget,
            )
            for payload in payloads
        ]
        return tuple(future.result() for future in futures)


def _max_extraction_concurrency() -> int:
    raw_value = os.getenv("CORE_EXTRACTION_MAX_CONCURRENCY", "").strip()
    if not raw_value:
        return _DEFAULT_MAX_EXTRACTION_CONCURRENCY
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning(
            "Invalid CORE_EXTRACTION_MAX_CONCURRENCY=%s; using default=%s",
            raw_value,
            _DEFAULT_MAX_EXTRACTION_CONCURRENCY,
        )
        return _DEFAULT_MAX_EXTRACTION_CONCURRENCY
    if value < 1:
        logger.warning(
            "Non-positive CORE_EXTRACTION_MAX_CONCURRENCY=%s; using default=%s",
            raw_value,
            _DEFAULT_MAX_EXTRACTION_CONCURRENCY,
        )
        return _DEFAULT_MAX_EXTRACTION_CONCURRENCY
    return value


def document_time_budget_seconds() -> int:
    raw_value = os.getenv(
        "CORE_PAPER_RESEARCH_MAP_DOCUMENT_TIME_BUDGET_SECONDS",
        "",
    ).strip()
    if not raw_value:
        return _DEFAULT_DOCUMENT_TIME_BUDGET_SECONDS
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning(
            "Invalid CORE_PAPER_RESEARCH_MAP_DOCUMENT_TIME_BUDGET_SECONDS=%s; "
            "using default=%s",
            raw_value,
            _DEFAULT_DOCUMENT_TIME_BUDGET_SECONDS,
        )
        return _DEFAULT_DOCUMENT_TIME_BUDGET_SECONDS
    if value < 1:
        logger.warning(
            "Non-positive CORE_PAPER_RESEARCH_MAP_DOCUMENT_TIME_BUDGET_SECONDS=%s; "
            "using default=%s",
            raw_value,
            _DEFAULT_DOCUMENT_TIME_BUDGET_SECONDS,
        )
        return _DEFAULT_DOCUMENT_TIME_BUDGET_SECONDS
    return value


def document_recovery_call_budget(
    window_count: int,
    *,
    selected_source_unit_count: int,
) -> int:
    raw_value = os.getenv("CORE_PAPER_RESEARCH_MAP_MAX_RECOVERY_CALLS", "").strip()
    if raw_value:
        try:
            value = int(raw_value)
        except ValueError:
            logger.warning(
                "Invalid CORE_PAPER_RESEARCH_MAP_MAX_RECOVERY_CALLS=%s; using "
                "the document-sized default",
                raw_value,
            )
        else:
            if value >= 0:
                return value
            logger.warning(
                "Negative CORE_PAPER_RESEARCH_MAP_MAX_RECOVERY_CALLS=%s; using "
                "the document-sized default",
                raw_value,
            )
    return min(
        _MAX_DOCUMENT_RECOVERY_CALLS,
        max(
            _MIN_DOCUMENT_RECOVERY_CALLS,
            window_count,
            selected_source_unit_count + 4,
        ),
    )


def _extract_window_batch(
    *,
    collection_id: str,
    document_id: str,
    payload: Mapping[str, Any],
    paper_map_extractor: PaperResearchMapExtractor,
    extraction_budget: PaperMapExtractionBudget,
) -> tuple[tuple[PaperResearchMap, ...], tuple[PaperResearchSignal, ...]]:
    request_count = 0
    budget_failure_kind = None

    def before_request() -> float:
        nonlocal request_count, budget_failure_kind
        if not extraction_budget.reserve(recovery=request_count > 0):
            budget_failure_kind = extraction_budget.failure_kind
            raise RuntimeError(budget_failure_kind)
        request_count += 1
        return max(0.001, extraction_budget.deadline - monotonic())

    failure_kind = None
    for attempt in range(2):
        try:
            parsed = paper_map_extractor.extract(
                dict(payload), before_request=before_request,
            )
            window_map, window_signals = _resolve_window_result(
                document_id=document_id, payload=payload, parsed=parsed,
            )
            logger.info(
                "Paper map reading finished collection_id=%s document_id=%s "
                "window_id=%s reading_round=%s source_unit_ids=%s requests=%s",
                collection_id, document_id, payload.get("window_id"),
                payload.get("reading_round", 1),
                [unit.get("source_unit_id") for unit in payload.get("source_units") or ()],
                request_count,
            )
            return (window_map,), window_signals
        except Exception as exc:
            failure_kind = (
                budget_failure_kind
                or _extraction_failure_kind(exc)
                or type(exc).__name__
            )
            if attempt == 0 and failure_kind == "provider_unavailable":
                continue
            logger.warning(
                "Paper map reading incomplete collection_id=%s document_id=%s "
                "window_id=%s reading_round=%s source_unit_ids=%s "
                "requests=%s failure_kind=%s",
                collection_id, document_id, payload.get("window_id"),
                payload.get("reading_round", 1),
                [unit.get("source_unit_id") for unit in payload.get("source_units") or ()],
                request_count, failure_kind,
                exc_info=True,
            )
            break
    return (
        (_failed_source_unit_map(
            document_id=document_id, payload=payload, failure_kind=failure_kind,
        ),),
        (),
    )


def _extraction_failure_kind(error: Exception) -> str | None:
    if isinstance(error, (APIConnectionError, TimeoutError)):
        return "provider_unavailable"
    if isinstance(error, APIStatusError):
        return "provider_unavailable" if error.status_code >= 500 or error.status_code == 429 else None
    if isinstance(error, StructuredOutputSaturatedError):
        return "output_saturated"
    if isinstance(error, json.JSONDecodeError):
        return "malformed_json"
    if not isinstance(error, RuntimeError):
        return None
    message = str(error).casefold()
    if "empty response content" in message or "empty json text" in message:
        return "empty_response"
    if "no json object" in message:
        return "no_json_object"
    if "extraction unavailable" in message:
        return "provider_unavailable"
    return None


def _split_oversized_source_unit(
    source_unit: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    content = source_unit.get("content")
    path: tuple[str | int, ...] | None = None
    if isinstance(content, str):
        text = content
    elif isinstance(content, Mapping):
        candidates = [
            (candidate_path, value)
            for candidate_path, value in paper_map_sources.structured_source_leaves(content)
            if isinstance(value, str)
        ]
        if not candidates:
            return ()
        path, text = max(candidates, key=lambda item: len(item[1]))
    else:
        return ()

    minimum = _PAPER_MAP_FRAGMENT_MIN_CHAR_LIMIT
    if len(text) < minimum * 2:
        return ()
    midpoint = len(text) // 2
    hard_end = min(
        len(text) - minimum,
        midpoint + min(200, len(text) // 10),
    )
    split_at = paper_map_sources.natural_text_split(text, 0, hard_end)
    if split_at < minimum or len(text) - split_at < minimum:
        split_at = midpoint
    if split_at < minimum or len(text) - split_at < minimum:
        return ()

    left_text, right_text = text[:split_at], text[split_at:]
    if path is None:
        fragment_contents: tuple[Any, Any] = (left_text, right_text)
    else:
        left_content = _replace_structured_path_value(
            content,
            path,
            left_text,
        )
        right_content = _replace_structured_path_value(
            content,
            path,
            right_text,
        )
        if path == ("fragment",) and isinstance(right_content, dict):
            start = int(right_content.get("fragment_start") or 0)
            right_content["fragment_start"] = start + split_at
        fragment_contents = (left_content, right_content)

    return tuple(
        {**dict(source_unit), "content": fragment_content}
        for fragment_content in fragment_contents
    )


def _replace_structured_path_value(
    value: Any,
    path: tuple[str | int, ...],
    replacement: Any,
) -> Any:
    if not path:
        return replacement
    part, remaining = path[0], path[1:]
    if isinstance(value, Mapping):
        copied = dict(value)
        copied[part] = _replace_structured_path_value(
            value[part],
            remaining,
            replacement,
        )
        return copied
    if isinstance(value, (list, tuple)) and isinstance(part, int):
        copied_values = list(value)
        copied_values[part] = _replace_structured_path_value(
            value[part],
            remaining,
            replacement,
        )
        return copied_values
    raise ValueError("paper map structured Source path cannot be replaced")


def _payload_with_source_units(
    payload: Mapping[str, Any],
    *,
    source_units: tuple[Mapping[str, Any], ...],
    suffix: str,
) -> dict[str, Any]:
    child_payload = dict(payload)
    child_payload["window_id"] = f"{payload.get('window_id')}.{suffix}"
    child_payload["section_paths"] = list(
        dict.fromkeys(
            str(unit.get("section_path") or "").strip()
            for unit in source_units
            if str(unit.get("section_path") or "").strip()
        )
    )
    child_payload["source_units"] = [dict(unit) for unit in source_units]
    return child_payload


def fit_payload_to_prompt_limit(
    payload: Mapping[str, Any],
    *,
    paper_map_extractor: PaperResearchMapExtractor,
) -> tuple[dict[str, Any], ...]:
    candidate = dict(payload)
    prompt_tokens = paper_map_extractor.estimate_prompt_tokens(candidate)
    if prompt_tokens <= PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT:
        return (candidate,)

    source_units = tuple(
        unit
        for unit in candidate.get("source_units") or ()
        if isinstance(unit, Mapping)
    )
    if len(source_units) <= 1:
        fragments = (
            _split_oversized_source_unit(source_units[0])
            if source_units else ()
        )
        if not fragments:
            raise ValueError(
                "one PaperResearchMap Source unit exceeds the complete prompt-token limit: "
                f"window_id={candidate.get('window_id')} "
                f"prompt_tokens={prompt_tokens} "
                f"limit={PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT}"
            )
        source_units = tuple(
            {
                **fragment,
                "source_unit_id": f"{fragment['source_unit_id']}-fragment-{position:02d}",
            }
            for position, fragment in enumerate(fragments, start=1)
        )

    logger.info(
        "Paper map prompt exceeds token limit; splitting before extraction "
        "window_id=%s source_unit_count=%s prompt_tokens=%s limit=%s",
        candidate.get("window_id"),
        len(source_units),
        prompt_tokens,
        PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT,
    )
    midpoint = len(source_units) // 2
    children: list[dict[str, Any]] = []
    for suffix, child_units in (
        ("prompt-left", source_units[:midpoint]),
        ("prompt-right", source_units[midpoint:]),
    ):
        children.extend(
            fit_payload_to_prompt_limit(
                _payload_with_source_units(
                    candidate,
                    source_units=child_units,
                    suffix=suffix,
                ),
                paper_map_extractor=paper_map_extractor,
            )
        )
    return tuple(children)


def _resolve_window_result(
    *,
    document_id: str,
    payload: Mapping[str, Any],
    parsed: StructuredPaperResearchMap,
) -> tuple[PaperResearchMap, tuple[PaperResearchSignal, ...]]:
    document_profile = payload.get("document_profile")
    is_review = isinstance(document_profile, Mapping) and (
        str(document_profile.get("doc_type") or "").strip() == "review"
    )
    if is_review:
        parsed = _review_synthesis_only(parsed)
    source_units = {
        str(unit.get("source_unit_id") or ""): unit
        for unit in payload.get("source_units") or ()
        if isinstance(unit, Mapping) and str(unit.get("source_unit_id") or "")
    }
    study_identities = [study.identity_key() for study in parsed.studies]
    if len(study_identities) != len(set(study_identities)):
        raise ValueError("paper map response contains duplicate study identities")
    studies: list[PaperResearchScope] = []
    signals = []
    for item in parsed.unresolved_signals:
        item = item.model_copy(
            update={"claim_scope": _claim_scope_for_document(
                claim_scope=item.claim_scope,
                experiment_label=item.experiment_label,
                source_unit_ids=item.source_unit_ids,
                payload=payload,
                source_units=source_units,
            )}
        )
        signals.append(
            _signal_from_window_result(
                item,
                document_id=document_id,
                source_units=source_units,
            )
        )
    relationship_source_unit_ids: list[str] = []
    signal_source_unit_ids = [
        source_unit_id
        for item in parsed.unresolved_signals
        for source_unit_id in item.source_unit_ids
    ]
    for study in parsed.studies:
        study = study.model_copy(
            update={
                "claim_scope": _claim_scope_for_document(
                    claim_scope=study.claim_scope,
                    experiment_label=study.experiment_label,
                    source_unit_ids=[
                        source_unit_id
                        for relationship in study.relationships
                        for source_unit_id in relationship.source_unit_ids
                    ],
                    payload=payload,
                    source_units=source_units,
                ),
            }
        )
        retained_relationships = _deduplicate_window_relationships(
            study.relationships
        )
        for relationship in retained_relationships:
            relationship_source_unit_ids.extend(relationship.source_unit_ids)
        if retained_relationships:
            studies.append(
                _study_from_window_result(
                    study,
                    document_id=document_id,
                    source_units=source_units,
                    relationships=retained_relationships,
                )
            )
    source_unit_coverage = _derive_source_unit_coverage(
        payload=payload,
        source_units=source_units,
        relationship_source_unit_ids=relationship_source_unit_ids,
        signal_source_unit_ids=signal_source_unit_ids,
    )
    if parsed.output_saturated:
        source_unit_coverage = tuple(
            replace(
                item,
                status=PaperSourceUnitCoverageStatus.EXTRACTION_FAILED,
                reason="Bounded Paper Map output omitted visible scope; retained supported relationships.",
            )
            for item in source_unit_coverage
        )
    review_synthesis = (
        _review_synthesis_from_window_result(
            parsed.review_synthesis,
            source_units=source_units,
        )
        if is_review
        else ReviewSynthesisMap()
    )
    return (
        PaperResearchMap(
            document_id=document_id,
            doc_role=parsed.doc_role,
            studies=tuple(studies),
            unresolved_signals=tuple(signals),
            evidence_density=parsed.evidence_density,
            confidence=parsed.confidence,
            warnings=tuple(parsed.warnings),
            source_unit_coverage=source_unit_coverage,
            review_synthesis=review_synthesis,
        ),
        tuple(signals),
    )


def _derive_source_unit_coverage(
    *,
    payload: Mapping[str, Any],
    source_units: Mapping[str, Mapping[str, Any]],
    relationship_source_unit_ids: Iterable[str],
    signal_source_unit_ids: Iterable[str],
) -> tuple[PaperSourceUnitCoverage, ...]:
    input_ids = tuple(source_units)
    if len(input_ids) != len(payload.get("source_units") or ()):
        raise ValueError("paper map window contains duplicate Source-unit ids")

    relationship_ids = {
        str(source_unit_id).strip()
        for source_unit_id in relationship_source_unit_ids
    }
    signal_ids = {
        str(source_unit_id).strip()
        for source_unit_id in signal_source_unit_ids
    }
    unknown_ids = (relationship_ids | signal_ids) - set(input_ids)
    if unknown_ids:
        raise ValueError(
            "paper map response contains unknown Source-unit ids: "
            + ", ".join(sorted(unknown_ids))
        )
    coverage: list[PaperSourceUnitCoverage] = []
    for source_unit_id in input_ids:
        expected_status = (
            PaperSourceUnitCoverageStatus.RELATIONSHIP_EMITTED
            if source_unit_id in relationship_ids
            else (
                PaperSourceUnitCoverageStatus.UNRESOLVED_SIGNAL_EMITTED
                if source_unit_id in signal_ids
                else PaperSourceUnitCoverageStatus.NO_STUDY_SIGNAL
            )
        )
        source_unit = source_units[source_unit_id]
        coverage.append(
            PaperSourceUnitCoverage(
                source_unit_id=source_unit_id,
                window_id=str(payload.get("window_id") or "").strip(),
                source_kind=str(source_unit.get("source_kind") or "").strip(),
                source_ref=str(source_unit.get("source_ref") or "").strip(),
                status=expected_status,
                reason=(
                    "No study relationship or unresolved signal was emitted for this Source unit."
                    if expected_status == PaperSourceUnitCoverageStatus.NO_STUDY_SIGNAL else None
                ),
            )
        )
    return tuple(coverage)


def _failed_source_unit_map(
    *,
    document_id: str,
    payload: Mapping[str, Any],
    failure_kind: str | None = None,
) -> PaperResearchMap:
    reason = "Paper map Source-unit extraction failed after bounded retries."
    if failure_kind:
        reason = f"{reason} Failure type: {failure_kind}."
    return PaperResearchMap(
        document_id=document_id, doc_role="uncertain", studies=(),
        evidence_density="unknown", confidence=0.0, warnings=(reason,),
        source_unit_coverage=tuple(
            PaperSourceUnitCoverage(
                source_unit_id=str(unit.get("source_unit_id") or "").strip(),
                window_id=str(payload.get("window_id") or "").strip(),
                source_kind=str(unit.get("source_kind") or "").strip(),
                source_ref=str(unit.get("source_ref") or "").strip(),
                status=PaperSourceUnitCoverageStatus.EXTRACTION_FAILED, reason=reason,
            )
            for unit in payload.get("source_units") or ()
        ),
    )


def _resolved_source_units(
    source_unit_ids: list[str],
    *,
    source_units: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...] | None:
    ids = tuple(str(value or "").strip() for value in source_unit_ids)
    if not ids or any(not value or value not in source_units for value in ids):
        return None
    return tuple(source_units[value] for value in dict.fromkeys(ids))


def _study_from_window_result(
    study: StructuredPaperResearchScope,
    *,
    document_id: str,
    source_units: Mapping[str, Mapping[str, Any]],
    relationships: Iterable[StructuredPaperResearchRelationship] | None = None,
) -> PaperResearchScope:
    bound_relationships: list[PaperResearchRelationship] = []
    source_relationships = study.relationships if relationships is None else relationships
    for relationship in source_relationships:
        resolved = _resolved_source_units(relationship.source_unit_ids, source_units=source_units)
        if resolved is None:
            raise ValueError("paper research relationship contains an unknown Source-unit id")
        bound_relationships.append(build_paper_research_relationship(
            document_id=document_id, varied_factors=tuple(relationship.varied_factors),
            outcome=relationship.outcome.strip(), source_refs=_source_refs_from_units(resolved),
            confidence=relationship.confidence,
        ))
    return build_paper_research_scope(
        document_id=document_id, design_type=study.design_type, claim_scope=study.claim_scope,
        experiment_label=study.experiment_label, material_scope=tuple(study.material_scope),
        process_context=tuple(study.process_context), relationships=tuple(bound_relationships),
        confidence=study.confidence,
    )


def _window_relationships_are_duplicates(
    left: StructuredPaperResearchRelationship,
    right: StructuredPaperResearchRelationship,
) -> bool:
    """Identify one paper-local axis repeated across overlapping windows."""

    return property_matching.axis_collections_are_equivalent(
        left.varied_factors,
        right.varied_factors,
    ) and property_matching.axis_values_match(left.outcome, right.outcome)


def _deduplicate_window_relationships(
    relationships: Iterable[StructuredPaperResearchRelationship],
) -> tuple[StructuredPaperResearchRelationship, ...]:
    """Fold repeated model rows while retaining every supporting Source unit."""

    merged: list[StructuredPaperResearchRelationship] = []
    for relationship in relationships:
        duplicate_position = next(
            (
                position
                for position, current in enumerate(merged)
                if _window_relationships_are_duplicates(current, relationship)
            ),
            None,
        )
        if duplicate_position is None:
            merged.append(relationship)
            continue
        current = merged[duplicate_position]
        merged[duplicate_position] = (
            StructuredPaperResearchRelationship.model_validate(
                {
                    "varied_factors": list(current.varied_factors),
                    "outcome": current.outcome,
                    "source_unit_ids": list(
                        dict.fromkeys(
                            (*current.source_unit_ids, *relationship.source_unit_ids)
                        )
                    ),
                    "confidence": max(
                        current.confidence,
                        relationship.confidence,
                    ),
                }
            )
        )
    return tuple(merged)


def _review_synthesis_from_window_result(
    review_map: StructuredReviewSynthesisMap,
    *,
    source_units: Mapping[str, Mapping[str, Any]],
) -> ReviewSynthesisMap:
    groups: dict[str, tuple[ReviewKnowledgeItem, ...]] = {}
    for field_name in ("synthesis_claims", "disputes", "evidence_gaps", "citation_leads"):
        items: list[ReviewKnowledgeItem] = []
        for item in getattr(review_map, field_name):
            resolved = _resolved_source_units(item.source_unit_ids, source_units=source_units)
            if resolved is None:
                raise ValueError("review knowledge contains an unknown Source-unit id")
            items.append(ReviewKnowledgeItem(
                content=item.content, material_scope=tuple(item.material_scope),
                variables=tuple(item.variables), outcomes=tuple(item.outcomes),
                conditions=tuple(item.conditions), source_refs=_source_refs_from_units(resolved),
                confidence=item.confidence,
            ))
        groups[field_name] = tuple(items)
    return ReviewSynthesisMap(**groups)


def _signal_from_window_result(
    signal: StructuredPaperResearchSignal,
    *,
    document_id: str,
    source_units: Mapping[str, Mapping[str, Any]],
) -> PaperResearchSignal:
    resolved = _resolved_source_units(
        signal.source_unit_ids,
        source_units=source_units,
    )
    if resolved is None:
        raise ValueError(
            "paper research signal contains an unknown Source-unit id"
        )
    return build_paper_research_signal(
        document_id=document_id, signal_type=signal.signal_type, label=signal.label,
        variable_role=signal.variable_role,
        design_type=signal.design_type, claim_scope=signal.claim_scope,
        experiment_label=signal.experiment_label, material_scope=tuple(signal.material_scope),
        process_context=tuple(signal.process_context), source_refs=_source_refs_from_units(resolved),
        confidence=signal.confidence,
    )


def _source_refs_from_units(
    source_units: tuple[Mapping[str, Any], ...],
) -> tuple[PaperResearchSourceRef, ...]:
    refs: list[PaperResearchSourceRef] = []
    seen: set[tuple[str, str]] = set()
    for unit in source_units:
        source_kind = str(unit.get("source_kind") or "").strip()
        source_ref = str(unit.get("source_ref") or "").strip()
        key = (source_kind, source_ref)
        if not source_kind or not source_ref or key in seen:
            continue
        seen.add(key)
        refs.append(PaperResearchSourceRef(source_kind=source_kind, source_ref=source_ref))
    return tuple(refs)


def _source_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(
        content,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _claim_scope_for_document(
    *,
    claim_scope: str,
    experiment_label: str | None,
    source_unit_ids: Iterable[str],
    payload: Mapping[str, Any],
    source_units: Mapping[str, Mapping[str, Any]],
) -> str:
    profile = payload.get("document_profile")
    doc_type = (
        str(profile.get("doc_type") or "").strip()
        if isinstance(profile, Mapping)
        else ""
    )
    if doc_type != "review" or claim_scope != "current_work":
        return claim_scope

    resolved = tuple(
        source_units[source_unit_id]
        for source_unit_id in dict.fromkeys(
            str(value or "").strip() for value in source_unit_ids
        )
        if source_unit_id in source_units
    )
    source_text = "\n".join(
        _source_content_text(unit.get("content")) for unit in resolved
    )
    if _NUMBERED_CITATION_PATTERN.search(source_text) or (
        experiment_label
        and _NAMED_PRIOR_AUTHOR_PATTERN.search(experiment_label)
    ):
        return "background"
    return "uncertain"


def build_payloads(
    *,
    collection_id: str,
    document: Any,
    profile: Any,
    blocks: list[Any],
    tables: list[Any],
    table_rows: list[Any],
    figures: list[Any],
    document_tree: SourceDocumentTree | None = None,
    paper_map_extractor: PaperResearchMapExtractor,
    selection_focus: str | None = None,
    expansion_search_terms: tuple[str, ...] = (),
    expansion_source_limit: int = paper_map_sources._PAPER_MAP_EXPANSION_SOURCE_LIMIT,
    reading_round: int = 2,
    excluded_source_keys: frozenset[tuple[str, str]] = frozenset(),
) -> list[dict[str, Any]]:
    source_items = paper_map_sources._build_source_items(
        document=document,
        blocks=blocks,
        tables=tables,
        table_rows=table_rows,
        figures=figures,
        document_tree=document_tree,
    )
    identified_items = [
        replace(item, source_unit_id=f"source-unit-{position:06d}")
        for position, item in enumerate(source_items, start=1)
    ]
    available_items = [
        item
        for item in identified_items
        if (item.source_kind, item.source_ref) not in excluded_source_keys
    ]
    selected_items = (
        paper_map_sources._select_paper_map_items(available_items)
        if selection_focus is None
        else paper_map_sources._select_paper_map_expansion_items(
            available_items,
            focus=selection_focus,
            search_terms=expansion_search_terms,
            limit=expansion_source_limit,
        )
    )
    if not selected_items and selection_focus is not None:
        return []
    roles = {item.role for item in selected_items}
    payload = paper_map_sources._build_window_payload(
        collection_id=collection_id,
        document=document,
        profile=profile,
        role=next(iter(roles)) if len(roles) == 1 else "overview",
        role_window_position=1,
        items=tuple(selected_items),
    )
    if selection_focus is not None:
        payload["reading_round"] = reading_round
        payload["expansion_focus"] = selection_focus
        payload["window_id"] = f"round-{reading_round}.{payload['window_id']}"
    return list(
        fit_payload_to_prompt_limit(
            payload,
            paper_map_extractor=paper_map_extractor,
        )
    )


def build_context_reading_payloads(
    *,
    previous_payloads: list[dict[str, Any]],
    new_payloads: list[dict[str, Any]],
    unresolved_signals: tuple[PaperResearchSignal, ...],
    paper_map_extractor: PaperResearchMapExtractor,
    reading_round: int,
) -> list[dict[str, Any]]:
    """Read missing passages alongside the original unresolved context."""

    if not previous_payloads or not unresolved_signals:
        return new_payloads
    context_keys = {
        (source.source_kind, source.source_ref)
        for signal in unresolved_signals
        for source in signal.source_refs
    }
    context_units = {
        unit["source_unit_id"]: unit
        for payload in previous_payloads
        for unit in payload.get("source_units") or ()
        if not context_keys or (unit["source_kind"], unit["source_ref"]) in context_keys
    }
    units = {
        **context_units,
        **{
            unit["source_unit_id"]: unit
            for payload in new_payloads
            for unit in payload.get("source_units") or ()
        },
    }
    payload = dict((new_payloads or previous_payloads)[0])
    payload.update(
        window_id=f"context-round-{reading_round}",
        window_role="overview",
        reading_round=reading_round,
        source_units=list(units.values()),
        section_paths=list(dict.fromkeys(
            unit.get("section_path", "") for unit in units.values()
        )),
    )
    return list(fit_payload_to_prompt_limit(payload, paper_map_extractor=paper_map_extractor))
