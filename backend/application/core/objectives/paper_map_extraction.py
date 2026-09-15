"""Model extraction and bounded recovery for one paper's Paper Map windows."""

from __future__ import annotations

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
from application.core.objectives.paper_map_sources import PaperMapSourceSelector
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


class PaperMapExtractionService:
    """Extract, recover, and normalize bounded Paper Map model responses."""

    def extract_window_payloads(
        self,
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
        if len(payloads) <= 1 or self._max_extraction_concurrency() == 1:
            return tuple(
                self._extract_window_batch(
                    collection_id=collection_id,
                    document_id=document_id,
                    payload=payload,
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                )
                for payload in payloads
            )

        with ThreadPoolExecutor(
            max_workers=min(self._max_extraction_concurrency(), len(payloads)),
        ) as executor:
            futures = [
                executor.submit(
                    copy_context().run,
                    self._extract_window_batch,
                    collection_id=collection_id,
                    document_id=document_id,
                    payload=payload,
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                )
                for payload in payloads
            ]
            return tuple(future.result() for future in futures)

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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
        self,
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
                window_map, window_signals = self._resolve_window_result(
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
                    or self._extraction_failure_kind(exc)
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
            (self._failed_source_unit_map(
                document_id=document_id, payload=payload, failure_kind=failure_kind,
            ),),
            (),
        )

    @staticmethod
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

    @classmethod
    def _split_oversized_source_unit(
        cls,
        source_unit: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        content = source_unit.get("content")
        path: tuple[str | int, ...] | None = None
        if isinstance(content, str):
            text = content
        elif isinstance(content, Mapping):
            candidates = [
                (candidate_path, value)
                for candidate_path, value in PaperMapSourceSelector.structured_source_leaves(content)
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
        split_at = PaperMapSourceSelector.natural_text_split(text, 0, hard_end)
        if split_at < minimum or len(text) - split_at < minimum:
            split_at = midpoint
        if split_at < minimum or len(text) - split_at < minimum:
            return ()

        left_text, right_text = text[:split_at], text[split_at:]
        if path is None:
            fragment_contents: tuple[Any, Any] = (left_text, right_text)
        else:
            left_content = cls._replace_structured_path_value(
                content,
                path,
                left_text,
            )
            right_content = cls._replace_structured_path_value(
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

    @classmethod
    def _replace_structured_path_value(
        cls,
        value: Any,
        path: tuple[str | int, ...],
        replacement: Any,
    ) -> Any:
        if not path:
            return replacement
        part, remaining = path[0], path[1:]
        if isinstance(value, Mapping):
            copied = dict(value)
            copied[part] = cls._replace_structured_path_value(
                value[part],
                remaining,
                replacement,
            )
            return copied
        if isinstance(value, (list, tuple)) and isinstance(part, int):
            copied_values = list(value)
            copied_values[part] = cls._replace_structured_path_value(
                value[part],
                remaining,
                replacement,
            )
            return copied_values
        raise ValueError("paper map structured Source path cannot be replaced")

    @staticmethod
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
        self,
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
                self._split_oversized_source_unit(source_units[0])
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
                self.fit_payload_to_prompt_limit(
                    self._payload_with_source_units(
                        candidate,
                        source_units=child_units,
                        suffix=suffix,
                    ),
                    paper_map_extractor=paper_map_extractor,
                )
            )
        return tuple(children)

    def _resolve_window_result(
        self,
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
            signal_payload = item.model_dump()
            signal_payload["claim_scope"] = self._claim_scope_for_document(
                claim_scope=item.claim_scope,
                experiment_label=item.experiment_label,
                source_unit_ids=item.source_unit_ids,
                payload=payload,
                source_units=source_units,
            )
            signals.append(
                self._signal_from_window_result(
                    signal_payload,
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
                    "claim_scope": self._claim_scope_for_document(
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
            retained_relationships = self._deduplicate_window_relationships(
                study.relationships
            )
            for relationship in retained_relationships:
                relationship_source_unit_ids.extend(relationship.source_unit_ids)
            if retained_relationships:
                studies.append(
                    self._study_from_window_result(
                        study,
                        document_id=document_id,
                        source_units=source_units,
                        relationships=retained_relationships,
                    )
                )
        source_unit_coverage = self._derive_source_unit_coverage(
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
            self._review_synthesis_from_window_result(
                parsed.review_synthesis,
                source_units=source_units,
            )
            if is_review
            else ReviewSynthesisMap()
        )
        return (
            PaperResearchMap.from_mapping(
                {
                    "document_id": document_id,
                    "doc_role": parsed.doc_role,
                    "studies": [item.to_record() for item in studies],
                    "unresolved_signals": [item.to_record() for item in signals],
                    "evidence_density": parsed.evidence_density,
                    "confidence": parsed.confidence,
                    "warnings": parsed.warnings,
                    "source_unit_coverage": [
                        item.to_record() for item in source_unit_coverage
                    ],
                    "review_synthesis": review_synthesis.to_record(),
                }
            ),
            tuple(signals),
        )

    @staticmethod
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
                PaperSourceUnitCoverage.from_mapping(
                    {
                        "source_unit_id": source_unit_id,
                        "window_id": payload.get("window_id"),
                        "source_kind": source_unit.get("source_kind"),
                        "source_ref": source_unit.get("source_ref"),
                        "status": expected_status.value,
                        "reason": (
                            "No study relationship or unresolved signal was emitted "
                            "for this Source unit."
                            if expected_status
                            == PaperSourceUnitCoverageStatus.NO_STUDY_SIGNAL
                            else None
                        ),
                    }
                )
            )
        return tuple(coverage)

    @staticmethod
    def _failed_source_unit_map(
        *,
        document_id: str,
        payload: Mapping[str, Any],
        failure_kind: str | None = None,
    ) -> PaperResearchMap:
        reason = "Paper map Source-unit extraction failed after bounded retries."
        if failure_kind:
            reason = f"{reason} Failure type: {failure_kind}."
        return PaperResearchMap.from_mapping(
            {
                "document_id": document_id,
                "source_unit_coverage": [
                    {
                        "source_unit_id": unit.get("source_unit_id"),
                        "window_id": payload.get("window_id"),
                        "source_kind": unit.get("source_kind"),
                        "source_ref": unit.get("source_ref"),
                        "status": "extraction_failed",
                        "reason": reason,
                    }
                    for unit in payload.get("source_units") or ()
                    if isinstance(unit, Mapping)
                ],
                "warnings": [reason],
            }
        )

    @staticmethod
    def _resolved_source_units(
        source_unit_ids: list[str],
        *,
        source_units: Mapping[str, Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], ...] | None:
        ids = tuple(str(value or "").strip() for value in source_unit_ids)
        if not ids or any(not value or value not in source_units for value in ids):
            return None
        return tuple(source_units[value] for value in dict.fromkeys(ids))

    @classmethod
    def _study_from_window_result(
        cls,
        study: StructuredPaperResearchScope,
        *,
        document_id: str,
        source_units: Mapping[str, Mapping[str, Any]],
        relationships: Iterable[StructuredPaperResearchRelationship] | None = None,
    ) -> PaperResearchScope:
        relationship_records: list[dict[str, Any]] = []
        source_relationships = (
            study.relationships if relationships is None else relationships
        )
        for relationship in source_relationships:
            resolved = cls._resolved_source_units(
                relationship.source_unit_ids,
                source_units=source_units,
            )
            if resolved is None:
                raise ValueError(
                    "paper research relationship contains an unknown Source-unit id"
                )
            relationship_records.append(
                {
                    **relationship.model_dump(exclude={"source_unit_ids"}),
                    "source_refs": cls._source_refs_from_units(resolved),
                }
            )
        return PaperResearchScope.from_mapping(
            {
                **study.model_dump(exclude={"relationships"}),
                "document_id": document_id,
                "relationships": relationship_records,
            }
        )

    @staticmethod
    def _window_relationships_are_duplicates(
        left: StructuredPaperResearchRelationship,
        right: StructuredPaperResearchRelationship,
    ) -> bool:
        """Identify one paper-local axis repeated across overlapping windows."""

        return property_matching.axis_collections_are_equivalent(
            left.varied_factors,
            right.varied_factors,
        ) and property_matching.axis_values_match(left.outcome, right.outcome)

    @classmethod
    def _deduplicate_window_relationships(
        cls,
        relationships: Iterable[StructuredPaperResearchRelationship],
    ) -> tuple[StructuredPaperResearchRelationship, ...]:
        """Fold repeated model rows while retaining every supporting Source unit."""

        merged: list[StructuredPaperResearchRelationship] = []
        for relationship in relationships:
            duplicate_position = next(
                (
                    position
                    for position, current in enumerate(merged)
                    if cls._window_relationships_are_duplicates(current, relationship)
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

    @classmethod
    def _review_synthesis_from_window_result(
        cls,
        review_map: StructuredReviewSynthesisMap,
        *,
        source_units: Mapping[str, Mapping[str, Any]],
    ) -> ReviewSynthesisMap:
        record: dict[str, list[dict[str, Any]]] = {}
        for field_name in (
            "synthesis_claims",
            "disputes",
            "evidence_gaps",
            "citation_leads",
        ):
            items: list[dict[str, Any]] = []
            for item in getattr(review_map, field_name):
                resolved = cls._resolved_source_units(
                    item.source_unit_ids,
                    source_units=source_units,
                )
                if resolved is None:
                    raise ValueError(
                        "review knowledge contains an unknown Source-unit id"
                    )
                items.append(
                    {
                        **item.model_dump(exclude={"source_unit_ids"}),
                        "source_refs": cls._source_refs_from_units(resolved),
                    }
                )
            record[field_name] = items
        return ReviewSynthesisMap.from_mapping(record)

    @classmethod
    def _signal_from_window_result(
        cls,
        signal: Mapping[str, Any],
        *,
        document_id: str,
        source_units: Mapping[str, Mapping[str, Any]],
    ) -> PaperResearchSignal:
        source_unit_ids = signal.get("source_unit_ids")
        if not isinstance(source_unit_ids, list):
            raise ValueError("paper research signal requires Source-unit ids")
        resolved = cls._resolved_source_units(
            source_unit_ids,
            source_units=source_units,
        )
        if resolved is None:
            raise ValueError(
                "paper research signal contains an unknown Source-unit id"
            )
        return PaperResearchSignal.from_mapping(
            {
                **dict(signal),
                "document_id": document_id,
                "source_refs": cls._source_refs_from_units(resolved),
            }
        )

    @staticmethod
    def _source_refs_from_units(
        source_units: tuple[Mapping[str, Any], ...],
    ) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for unit in source_units:
            source_kind = str(unit.get("source_kind") or "").strip()
            source_ref = str(unit.get("source_ref") or "").strip()
            key = (source_kind, source_ref)
            if not source_kind or not source_ref or key in seen:
                continue
            seen.add(key)
            refs.append({"source_kind": source_kind, "source_ref": source_ref})
        return refs

    @staticmethod
    def _source_content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
        )


    @classmethod
    def _claim_scope_for_document(
        cls,
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
            cls._source_content_text(unit.get("content")) for unit in resolved
        )
        if _NUMBERED_CITATION_PATTERN.search(source_text) or (
            experiment_label
            and _NAMED_PRIOR_AUTHOR_PATTERN.search(experiment_label)
        ):
            return "background"
        return "uncertain"


__all__ = [
    "PaperMapExtractionBudget",
    "PaperMapExtractionService",
]
