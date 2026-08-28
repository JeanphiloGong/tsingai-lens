from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from threading import Lock
from time import monotonic
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.discovery.signal_reconciliation import (
    PAPER_SIGNAL_RECONCILIATION_PROMPT_TOKEN_LIMIT,
    PaperSignalReconciler,
    StructuredPaperSignalReconciliation,
)
from application.core.objectives.discovery.study_window import (
    PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT,
    PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT,
    PaperResearchMapExtractor,
    StructuredPaperResearchMap,
    StructuredPaperResearchScope,
    StructuredPaperResearchRelationship,
    StructuredReviewSynthesisMap,
    _review_synthesis_only,
)
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
)
from domain.core import (
    PaperResearchMap,
    PaperSourceUnitCoverage,
    PaperSourceUnitCoverageStatus,
    PaperResearchScope,
    PaperResearchRelationship,
    PaperResearchSignal,
    ReviewKnowledgeItem,
    ReviewSynthesisMap,
)
from domain.source import SourceDocument, SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

# Research-scope limits for the bounded pre-Objective reading rounds.
_PAPER_MAP_INITIAL_SOURCE_LIMIT = 16
_PAPER_MAP_TEXT_SOURCE_LIMIT_PER_ROLE = 4
_PAPER_MAP_VISUAL_SOURCE_LIMIT = 4
_PAPER_MAP_EXPANSION_SOURCE_LIMIT = 8
_PAPER_MAP_FALLBACK_SOURCE_LIMIT_PER_EDGE = 4

# Serialization limits that keep one selected Source from dominating a prompt.
_PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT = 4000
_PAPER_MAP_SECTION_PATH_LIMIT = 16
_PAPER_MAP_PERSISTED_WARNING_LIMIT = 2
_PAPER_MAP_TABLE_CAPTION_CHAR_LIMIT = 1600
_PAPER_MAP_FIGURE_CAPTION_CHAR_LIMIT = 3500
_PAPER_MAP_HEADING_PATH_CHAR_LIMIT = 240
_PAPER_MAP_COLUMN_HEADER_LIMIT = 12
_PAPER_MAP_COLUMN_HEADER_CHAR_LIMIT = 120

# Technical recovery limits; these do not represent scientific outcomes.
_PAPER_MAP_RECOVERY_FRAGMENT_MIN_CHAR_LIMIT = 800
_PAPER_MAP_RECOVERY_SPLIT_DEPTH_LIMIT = 2
_PAPER_MAP_COMPACT_ATTEMPT_LIMIT = 2
_PAPER_MAP_TRANSIENT_STRUCTURED_FAILURE_KINDS = {
    "empty_response",
    "malformed_json",
    "no_json_object",
}
_PAPER_MAP_WINDOW_ROLES = ("overview", "methods", "results", "conclusion", "unknown")
_PAPER_MAP_ROLE_BY_SEMANTIC_ROLE = {
    "abstract": "overview",
    "introduction": "overview",
    "methods": "methods",
    "results": "results",
    "conclusion": "conclusion",
}
_EVIDENCE_DENSITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
_SIGNAL_RECONCILIATION_SIGNAL_LIMIT = 12
_SIGNAL_RECONCILIATION_NEARBY_SOURCE_UNIT_DISTANCE = 12
_SOURCE_UNIT_POSITION_PATTERN = re.compile(r"source-unit-(\d+)")
_DEFAULT_MAX_EXTRACTION_CONCURRENCY = 4
_DEFAULT_DOCUMENT_TIME_BUDGET_SECONDS = 300
_MIN_DOCUMENT_RECOVERY_CALLS = 4
_MAX_DOCUMENT_RECOVERY_CALLS = 16
_NUMBERED_CITATION_PATTERN = re.compile(
    r"\[(?:\s*\d{1,4}\s*(?:(?:,|[-\u2013])\s*\d{1,4}\s*)*)\]"
)
_NAMED_PRIOR_AUTHOR_PATTERN = re.compile(r"\bet\s+al\b", re.IGNORECASE)


@dataclass(frozen=True)
class _PaperMapSourceItem:
    role: str
    order: int
    source_kind: str
    source_ref: str
    content: Any
    section_path: str
    source_unit_id: str = ""

    @property
    def size(self) -> int:
        if isinstance(self.content, str):
            return len(self.content)
        return len(
            json.dumps(
                self.content,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )


@dataclass(frozen=True)
class _PaperSignalInput:
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


@dataclass(frozen=True)
class _PaperMapAssessment:
    status: str
    limitations: tuple[str, ...]
    expansion_focus: str | None = None


@dataclass
class _PaperExtractionBudget:
    deadline: float
    max_calls: int
    max_recovery_calls: int
    calls: int = 0
    recovery_calls: int = 0
    failure_kind: str | None = None
    _lock: Any = field(default_factory=Lock, repr=False)

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


class PaperResearchMapService:
    """Build a bounded Source-linked map of each paper's stated research scope."""

    def build_document_paper_map(
        self,
        collection_id: str,
        *,
        document: SourceDocument,
        profile: Any,
        document_tree: SourceDocumentTree | None,
        paper_map_extractor: PaperResearchMapExtractor,
        signal_reconciler: PaperSignalReconciler,
        progress_callback: ProgressCallback | None = None,
    ) -> PaperResearchMap:
        return self.build_collection_paper_maps(
            collection_id,
            documents=(document,),
            profiles_by_document_id={document.document_id: profile},
            document_trees_by_document_id={document.document_id: document_tree},
            paper_map_extractor=paper_map_extractor,
            signal_reconciler=signal_reconciler,
            progress_callback=progress_callback,
        )[0]

    def build_collection_paper_maps(
        self,
        collection_id: str,
        *,
        documents: tuple[SourceDocument, ...],
        profiles_by_document_id: Mapping[str, Any],
        document_trees_by_document_id: Mapping[
            str,
            SourceDocumentTree | None,
        ],
        paper_map_extractor: PaperResearchMapExtractor,
        signal_reconciler: PaperSignalReconciler,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        logger.info(
            "Research objective paper map started collection_id=%s document_count=%s",
            collection_id,
            len(documents),
        )
        paper_maps: list[PaperResearchMap] = []

        document_count = len(documents)
        for document_position, document in enumerate(documents, start=1):
            source_filename = self._resolve_source_filename(document)
            document_blocks = list(document.blocks)
            document_tables = list(document.tables)
            document_table_rows = list(document.table_rows)
            document_figures = list(document.figures)
            logger.info(
                "Research objective paper map document started collection_id=%s document_id=%s document_position=%s document_count=%s block_count=%s table_count=%s figure_count=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                len(document_blocks),
                len(document_tables),
                len(document_figures),
            )
            payloads = self._build_paper_map_payloads(
                collection_id=collection_id,
                document=document,
                profile=profiles_by_document_id.get(document.document_id),
                blocks=document_blocks,
                tables=document_tables,
                table_rows=document_table_rows,
                figures=document_figures,
                document_tree=document_trees_by_document_id.get(document.document_id),
                paper_map_extractor=paper_map_extractor,
            )
            window_maps: list[PaperResearchMap] = []
            paper_signals: list[_PaperSignalInput] = []
            window_count = len(payloads)
            selected_source_unit_count = sum(
                len(payload.get("source_units") or ()) for payload in payloads
            )
            recovery_call_budget = self._document_recovery_call_budget(
                window_count,
                selected_source_unit_count=selected_source_unit_count,
            )
            extraction_budget = _PaperExtractionBudget(
                deadline=monotonic() + self._document_time_budget_seconds(),
                max_calls=window_count + recovery_call_budget,
                max_recovery_calls=recovery_call_budget,
            )
            for window_position, payload in enumerate(payloads, start=1):
                self._notify_progress(
                    progress_callback,
                    phase="paper_research_map_started",
                    current=document_position,
                    total=document_count,
                    unit="documents",
                    message="Mapping paper scope for candidate research objectives.",
                    active_document_id=document.document_id,
                    active_document_title=getattr(document, "title", None),
                    active_source_filename=source_filename,
                    active_window_position=window_position,
                    active_window_count=window_count,
                    active_window_role=payload["window_role"],
                )
            for batch_maps, batch_signals in self._extract_window_payloads(
                collection_id=collection_id,
                document_id=document.document_id,
                payloads=payloads,
                paper_map_extractor=paper_map_extractor,
                extraction_budget=extraction_budget,
            ):
                window_maps.extend(batch_maps)
                paper_signals.extend(batch_signals)
            paper_map = self._consolidate_window_maps(
                document.document_id,
                window_maps,
                profile=profiles_by_document_id.get(document.document_id),
            )
            assessment = self._assess_paper_map(
                paper_map,
                signals=tuple(item.signal for item in paper_signals),
                final=False,
            )
            if assessment.expansion_focus is not None:
                selected_source_keys = frozenset(
                    (
                        str(unit.get("source_kind") or ""),
                        str(unit.get("source_ref") or ""),
                    )
                    for payload in payloads
                    for unit in payload.get("source_units") or ()
                    if isinstance(unit, Mapping)
                )
                expansion_payloads = self._build_paper_map_payloads(
                    collection_id=collection_id,
                    document=document,
                    profile=profiles_by_document_id.get(document.document_id),
                    blocks=document_blocks,
                    tables=document_tables,
                    table_rows=document_table_rows,
                    figures=document_figures,
                    document_tree=document_trees_by_document_id.get(
                        document.document_id
                    ),
                    paper_map_extractor=paper_map_extractor,
                    selection_focus=assessment.expansion_focus,
                    excluded_source_keys=selected_source_keys,
                )
                for expansion_position, payload in enumerate(
                    expansion_payloads,
                    start=1,
                ):
                    self._notify_progress(
                        progress_callback,
                        phase="paper_research_map_started",
                        current=document_position,
                        total=document_count,
                        unit="documents",
                        message=(
                            "Expanding the paper map for one missing scientific "
                            "scope element."
                        ),
                        active_document_id=document.document_id,
                        active_document_title=getattr(document, "title", None),
                        active_source_filename=source_filename,
                        active_window_position=expansion_position,
                        active_window_count=len(expansion_payloads),
                        active_window_role=(
                            f"targeted_{assessment.expansion_focus}"
                        ),
                    )
                for batch_maps, batch_signals in self._extract_window_payloads(
                    collection_id=collection_id,
                    document_id=document.document_id,
                    payloads=expansion_payloads,
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                ):
                    window_maps.extend(batch_maps)
                    paper_signals.extend(batch_signals)
                payloads.extend(expansion_payloads)
                paper_map = self._consolidate_window_maps(
                    document.document_id,
                    window_maps,
                    profile=profiles_by_document_id.get(document.document_id),
                )
            paper_map = self._reconcile_paper_signals(
                paper_map,
                paper_signals,
                signal_reconciler=signal_reconciler,
                extraction_budget=extraction_budget,
                progress_callback=progress_callback,
                document_position=document_position,
                document_count=document_count,
                document_title=getattr(document, "title", None),
                source_filename=source_filename,
            )
            final_assessment = self._assess_paper_map(
                paper_map,
                signals=paper_map.unresolved_signals,
                final=True,
            )
            paper_map = replace(
                paper_map,
                map_status=final_assessment.status,
                map_limitations=final_assessment.limitations,
            )
            paper_maps.append(paper_map)
            logger.info(
                "Research objective paper map document finished collection_id=%s document_id=%s document_position=%s document_count=%s window_count=%s doc_role=%s study_count=%s relationship_count=%s unresolved_signal_count=%s completed_documents=%s remaining_documents=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                len(payloads),
                paper_map.doc_role,
                len(paper_map.studies),
                sum(len(study.relationships) for study in paper_map.studies),
                len(paper_map.unresolved_signals),
                document_position,
                max(document_count - document_position, 0),
            )
        return tuple(paper_maps)

    def _extract_window_payloads(
        self,
        *,
        collection_id: str,
        document_id: str,
        payloads: list[dict[str, Any]],
        paper_map_extractor: PaperResearchMapExtractor,
        extraction_budget: _PaperExtractionBudget,
    ) -> tuple[
        tuple[tuple[PaperResearchMap, ...], tuple[_PaperSignalInput, ...]],
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
    def _document_time_budget_seconds() -> int:
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
    def _document_recovery_call_budget(
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

    def _build_paper_map_payloads(
        self,
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
        excluded_source_keys: frozenset[tuple[str, str]] = frozenset(),
    ) -> list[dict[str, Any]]:
        source_items = self._build_source_items(
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
            self._select_paper_map_items(available_items)
            if selection_focus is None
            else self._select_paper_map_expansion_items(
                available_items,
                focus=selection_focus,
            )
        )
        bounded_items: list[_PaperMapSourceItem] = []
        for item in selected_items:
            fragments = self._split_oversized_source_item(item)
            bounded_items.extend(
                replace(
                    fragment,
                    source_unit_id=(
                        item.source_unit_id
                        if len(fragments) == 1
                        else f"{item.source_unit_id}-fragment-{position:02d}"
                    ),
                )
                for position, fragment in enumerate(fragments, start=1)
            )
        items = (
            self._select_paper_map_items(bounded_items)
            if selection_focus is None
            else self._select_paper_map_expansion_items(
                bounded_items,
                focus=selection_focus,
            )
        )
        payloads: list[dict[str, Any]] = []
        role_window_positions = {role: 0 for role in _PAPER_MAP_WINDOW_ROLES}
        for role_items in self._paper_map_item_groups(items):
            role = role_items[0].role
            for window_items in self._pack_source_items(list(role_items)):
                role_window_positions[role] += 1
                payload = self._build_window_payload(
                    collection_id=collection_id,
                    document=document,
                    profile=profile,
                    role=role,
                    role_window_position=role_window_positions[role],
                    items=window_items,
                )
                if selection_focus is not None:
                    payload["reading_round"] = 2
                    payload["expansion_focus"] = selection_focus
                    payload["window_id"] = f"round-2.{payload['window_id']}"
                payloads.extend(
                    self._fit_payload_to_prompt_limit(
                        payload,
                        paper_map_extractor=paper_map_extractor,
                    )
                )
        if payloads:
            return payloads
        if selection_focus is not None:
            return []
        empty_payload = self._build_window_payload(
            collection_id=collection_id,
            document=document,
            profile=profile,
            role="unknown",
            role_window_position=1,
            items=(),
        )
        return list(
            self._fit_payload_to_prompt_limit(
                empty_payload,
                paper_map_extractor=paper_map_extractor,
            )
        )

    @classmethod
    def _select_paper_map_items(
        cls,
        items: list[_PaperMapSourceItem],
    ) -> list[_PaperMapSourceItem]:
        """Select how a researcher maps scope before inspecting experiments."""

        abstract_items: list[_PaperMapSourceItem] = []
        conclusion_items: list[_PaperMapSourceItem] = []
        overview_items: list[_PaperMapSourceItem] = []
        table_items: list[_PaperMapSourceItem] = []
        figure_items: list[_PaperMapSourceItem] = []
        fallback_items: list[_PaperMapSourceItem] = []
        for item in items:
            section = cls._normalized_section_path(item.section_path)
            compact_section = section.replace(" ", "")
            is_visual_summary = False
            if isinstance(item.content, Mapping):
                caption = str(item.content.get("caption_text") or "").strip()
                if item.source_kind == "figure":
                    is_visual_summary = bool(caption)
                elif item.source_kind == "table" and "row_text" not in item.content:
                    is_visual_summary = bool(
                        caption or item.content.get("column_headers")
                    )
            if is_visual_summary:
                if item.source_kind == "table":
                    table_items.append(item)
                else:
                    figure_items.append(item)
                continue
            if item.source_kind == "table_row":
                continue
            if "abstract" in compact_section or "highlight" in compact_section:
                abstract_items.append(item)
            elif item.role == "conclusion" or any(
                label in section
                for label in ("conclusion", "summary", "key finding")
            ):
                conclusion_items.append(item)
            elif item.role == "overview":
                overview_items.append(item)
            elif item.source_kind in {"block", "document"}:
                fallback_items.append(item)

        selected_text = [
            *abstract_items[:_PAPER_MAP_TEXT_SOURCE_LIMIT_PER_ROLE],
            *conclusion_items[:_PAPER_MAP_TEXT_SOURCE_LIMIT_PER_ROLE],
            *overview_items[:_PAPER_MAP_TEXT_SOURCE_LIMIT_PER_ROLE],
        ]
        if not abstract_items and not conclusion_items and not overview_items:
            edge_count = _PAPER_MAP_FALLBACK_SOURCE_LIMIT_PER_EDGE
            selected_text.extend(fallback_items[:edge_count])
            selected_text.extend(fallback_items[-edge_count:])

        visual_capacity = min(
            _PAPER_MAP_VISUAL_SOURCE_LIMIT,
            max(_PAPER_MAP_INITIAL_SOURCE_LIMIT - len(selected_text), 0),
        )
        if table_items and figure_items:
            table_limit = visual_capacity // 2
            figure_limit = visual_capacity - table_limit
        elif table_items:
            table_limit, figure_limit = visual_capacity, 0
        else:
            table_limit, figure_limit = 0, visual_capacity
        selected = [
            *selected_text,
            *table_items[:table_limit],
            *figure_items[:figure_limit],
        ]

        selected_ids = {id(item) for item in selected}
        return [
            cls._compact_paper_map_item_metadata(item)
            for item in items
            if id(item) in selected_ids
        ][:_PAPER_MAP_INITIAL_SOURCE_LIMIT]

    @classmethod
    def _select_paper_map_expansion_items(
        cls,
        items: list[_PaperMapSourceItem],
        *,
        focus: str,
    ) -> list[_PaperMapSourceItem]:
        selected: list[_PaperMapSourceItem] = []
        for item in items:
            if item.source_kind == "table_row":
                continue
            section = cls._normalized_section_path(item.section_path)
            compact_section = section.replace(" ", "")
            is_visual = cls._is_paper_map_visual(item)
            if focus in {"missing_outcome", "outcome_specificity"}:
                include = item.role == "results" or (
                    is_visual
                    and any(
                        label in section
                        for label in (
                            "result",
                            "characterization",
                            "microstructure",
                            "mechanical",
                            "property",
                        )
                    )
                )
            elif focus == "missing_variable":
                include = item.role == "methods" or (
                    item.role == "overview"
                    and "introduction" in compact_section
                )
            elif focus == "unclear_ownership":
                include = item.role in {"overview", "conclusion"}
            else:
                include = item.role in {
                    "overview",
                    "methods",
                    "results",
                    "conclusion",
                    "unknown",
                }
            if include:
                selected.append(item)
        return [
            cls._compact_paper_map_item_metadata(item)
            for item in selected[:_PAPER_MAP_EXPANSION_SOURCE_LIMIT]
        ]

    @staticmethod
    def _normalized_section_path(section_path: str) -> str:
        return " ".join(
            "".join(
                character if character.isalpha() else " "
                for character in section_path
            )
            .casefold()
            .split()
        )

    @staticmethod
    def _is_paper_map_visual(item: _PaperMapSourceItem) -> bool:
        if not isinstance(item.content, Mapping):
            return False
        caption = str(item.content.get("caption_text") or "").strip()
        if item.source_kind == "figure":
            return bool(caption)
        return bool(
            item.source_kind == "table"
            and "row_text" not in item.content
            and (caption or item.content.get("column_headers"))
        )

    @staticmethod
    def _compact_paper_map_item_metadata(
        item: _PaperMapSourceItem,
    ) -> _PaperMapSourceItem:
        if not isinstance(item.content, Mapping) or "caption_text" not in item.content:
            return item

        content = dict(item.content)
        caption_limit = (
            _PAPER_MAP_FIGURE_CAPTION_CHAR_LIMIT
            if item.source_kind == "figure"
            else _PAPER_MAP_TABLE_CAPTION_CHAR_LIMIT
        )
        content["caption_text"] = str(content.get("caption_text") or "")[
            :caption_limit
        ]
        content["heading_path"] = str(content.get("heading_path") or "")[
            :_PAPER_MAP_HEADING_PATH_CHAR_LIMIT
        ]
        if item.source_kind == "table":
            content["column_headers"] = [
                str(value)[:_PAPER_MAP_COLUMN_HEADER_CHAR_LIMIT]
                for value in content.get("column_headers") or ()
            ][:_PAPER_MAP_COLUMN_HEADER_LIMIT]
        return replace(item, content=content)

    @staticmethod
    def _paper_map_item_groups(
        items: list[_PaperMapSourceItem],
    ) -> tuple[tuple[_PaperMapSourceItem, ...], ...]:
        groups: dict[str, list[_PaperMapSourceItem]] = {}
        for item in items:
            groups.setdefault(item.role, []).append(item)
        return tuple(tuple(group) for group in groups.values())

    def _build_source_items(
        self,
        *,
        document: Any,
        blocks: list[Any],
        tables: list[Any],
        table_rows: list[Any],
        figures: list[Any],
        document_tree: SourceDocumentTree | None,
    ) -> list[_PaperMapSourceItem]:
        items = (
            self._text_items_from_tree(document_tree)
            if document_tree is not None
            else self._text_items_from_blocks(blocks)
        )
        if not items and str(getattr(document, "text", "") or "").strip():
            items = [
                _PaperMapSourceItem(
                    role="unknown",
                    order=0,
                    source_kind="document",
                    source_ref=document.document_id,
                    content=str(document.text).strip(),
                    section_path="Unsectioned",
                )
            ]
        items.extend(self._table_items(tables, table_rows, document_tree))
        items.extend(self._figure_items(figures, document_tree))
        return sorted(items, key=lambda item: (item.order, item.source_kind))

    def _text_items_from_tree(
        self,
        document_tree: SourceDocumentTree,
    ) -> list[_PaperMapSourceItem]:
        return [
            _PaperMapSourceItem(
                role=self._tree_node_window_role(document_tree, node),
                order=int(getattr(node, "order", 0) or 0),
                source_kind=str(node.source_ref_kind or "block"),
                source_ref=str(node.source_ref_id or node.node_id),
                content=str(node.text or "").strip(),
                section_path=self._tree_section_label(node),
            )
            for node in self._document_tree_nodes_in_order(document_tree)
            if node.node_type in {"paragraph", "list_item"}
            and not self._tree_node_in_reference_branch(document_tree, node)
            and str(node.text or "").strip()
        ]

    def _text_items_from_blocks(self, blocks: list[Any]) -> list[_PaperMapSourceItem]:
        items: list[_PaperMapSourceItem] = []
        for block in sorted(
            blocks,
            key=lambda item: int(getattr(item, "block_order", 0) or 0),
        ):
            if getattr(block, "block_type", "") not in {"paragraph", "list_item"}:
                continue
            text = str(getattr(block, "text", "") or "").strip()
            section_path = str(getattr(block, "heading_path", "") or "").strip()
            role = self._window_role_from_text(section_path)
            if not text or role == "references":
                continue
            items.append(
                _PaperMapSourceItem(
                    role=role,
                    order=int(getattr(block, "block_order", 0) or 0),
                    source_kind="block",
                    source_ref=str(getattr(block, "block_id", "") or ""),
                    content=text,
                    section_path=section_path or "Unsectioned",
                )
            )
        return items

    def _table_items(
        self,
        tables: list[Any],
        table_rows: list[Any],
        document_tree: SourceDocumentTree | None,
    ) -> list[_PaperMapSourceItem]:
        items: list[_PaperMapSourceItem] = []
        rows_by_table_id: dict[str, list[Any]] = {}
        for row in table_rows:
            rows_by_table_id.setdefault(str(row.table_id), []).append(row)
        for table in sorted(tables, key=lambda item: item.table_order):
            role = self._source_ref_window_role(
                document_tree,
                source_ref_kind="table",
                source_ref_id=table.table_id,
                heading_path=table.heading_path,
            )
            if role == "references":
                continue
            table_context = {
                "table_id": table.table_id,
                "caption_text": str(table.caption_text or ""),
                "heading_path": str(table.heading_path or ""),
                "column_headers": [str(value) for value in table.column_headers],
            }
            items.append(
                _PaperMapSourceItem(
                    role=role,
                    order=200_000 + int(table.table_order or 0) * 10_000,
                    source_kind="table",
                    source_ref=table.table_id,
                    content=table_context,
                    section_path=str(table.heading_path or "").strip()
                    or "Unsectioned",
                )
            )
            explicit_rows = sorted(
                rows_by_table_id.get(str(table.table_id), ()),
                key=lambda row: int(row.row_index),
            )
            row_records = (
                [
                    (
                        "table_row",
                        str(row.row_id),
                        {
                            "table_context": table_context,
                            "row_id": str(row.row_id),
                            "row_index": int(row.row_index),
                            "row_text": str(row.row_text or ""),
                        },
                    )
                    for row in explicit_rows
                    if str(row.row_text or "").strip()
                ]
                if explicit_rows
                else [
                    (
                        "table",
                        table.table_id,
                        {
                            "table_context": table_context,
                            "row_index": row_index,
                            "row_text": " | ".join(str(value) for value in row),
                        },
                    )
                    for row_index, row in enumerate(table.table_matrix)
                    if any(str(value).strip() for value in row)
                ]
            )
            items.extend(
                _PaperMapSourceItem(
                    role=role,
                    order=(
                        200_000
                        + int(table.table_order or 0) * 10_000
                        + row_position
                        + 1
                    ),
                    source_kind=source_kind,
                    source_ref=source_ref,
                    content=row_record,
                    section_path=str(table.heading_path or "").strip()
                    or "Unsectioned",
                )
                for row_position, (source_kind, source_ref, row_record) in enumerate(
                    row_records
                )
            )
        return items

    def _figure_items(
        self,
        figures: list[Any],
        document_tree: SourceDocumentTree | None,
    ) -> list[_PaperMapSourceItem]:
        items: list[_PaperMapSourceItem] = []
        for figure in sorted(figures, key=lambda item: item.figure_order):
            role = self._source_ref_window_role(
                document_tree,
                source_ref_kind="figure",
                source_ref_id=figure.figure_id,
                heading_path=figure.heading_path,
            )
            if role == "references":
                continue
            items.append(
                _PaperMapSourceItem(
                    role=role,
                    order=300_000 + int(figure.figure_order or 0) * 10,
                    source_kind="figure",
                    source_ref=figure.figure_id,
                    content={
                        "figure_id": figure.figure_id,
                        "caption_text": str(figure.caption_text or ""),
                        "heading_path": str(figure.heading_path or ""),
                    },
                    section_path=str(figure.heading_path or "").strip()
                    or "Unsectioned",
                )
            )
        return items

    @staticmethod
    def _pack_source_items(
        items: list[_PaperMapSourceItem],
    ) -> list[tuple[_PaperMapSourceItem, ...]]:
        windows: list[tuple[_PaperMapSourceItem, ...]] = []
        current: list[_PaperMapSourceItem] = []
        for item in items:
            if current and len(current) >= PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT:
                windows.append(tuple(current))
                current = []
            current.append(item)
        if current:
            windows.append(tuple(current))
        return windows

    @staticmethod
    def _split_oversized_source_item(
        item: _PaperMapSourceItem,
    ) -> tuple[_PaperMapSourceItem, ...]:
        if item.size <= _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT:
            return (item,)
        if isinstance(item.content, Mapping):
            if "row_text" in item.content:
                return PaperResearchMapService._split_table_row_source_item(item)
            return PaperResearchMapService._split_structured_source_item(item)
        if not isinstance(item.content, str):
            raise ValueError(
                "paper map Source item cannot fit in a bounded window"
            )
        text = str(item.content)
        chunks: list[str] = []
        start = 0
        while len(text) - start > _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT:
            hard_end = start + _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT
            split_at = PaperResearchMapService._natural_text_split(text, start, hard_end)
            chunks.append(text[start:split_at])
            start = split_at
        chunks.append(text[start:])
        return tuple(
            _PaperMapSourceItem(
                role=item.role,
                order=item.order + position,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                content=chunk,
                section_path=item.section_path,
            )
            for position, chunk in enumerate(chunks)
        )

    @staticmethod
    def _split_table_row_source_item(
        item: _PaperMapSourceItem,
    ) -> tuple[_PaperMapSourceItem, ...]:
        content = dict(item.content)
        row_text = str(content.pop("row_text", ""))
        chunks: list[_PaperMapSourceItem] = []
        start = 0
        while start < len(row_text):
            low = start + 1
            high = len(row_text)
            end = start
            while low <= high:
                candidate_end = (low + high) // 2
                candidate = replace(
                    item,
                    content={
                        **content,
                        "structured_path": ["row_text"],
                        "fragment_start": start,
                        "fragment": row_text[start:candidate_end],
                    },
                )
                if candidate.size <= _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT:
                    end = candidate_end
                    low = candidate_end + 1
                else:
                    high = candidate_end - 1
            if end == start:
                raise ValueError(
                    "paper map table context cannot fit in a bounded window"
                )
            if end < len(row_text):
                end = PaperResearchMapService._natural_text_split(row_text, start, end)
            chunks.append(
                replace(
                    item,
                    content={
                        **content,
                        "structured_path": ["row_text"],
                        "fragment_start": start,
                        "fragment": row_text[start:end],
                    },
                )
            )
            start = end
        return tuple(chunks)

    @staticmethod
    def _split_structured_source_item(
        item: _PaperMapSourceItem,
    ) -> tuple[_PaperMapSourceItem, ...]:
        chunks: list[_PaperMapSourceItem] = []
        for path, value in PaperResearchMapService._structured_source_leaves(item.content):
            if isinstance(value, str):
                chunks.extend(
                    PaperResearchMapService._split_structured_text_value(
                        item,
                        path=path,
                        value=value,
                    )
                )
                continue
            chunk = replace(
                item,
                content={
                    "structured_path": list(path),
                    "value": value,
                },
            )
            if chunk.size > _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT:
                raise ValueError(
                    "paper map structured Source value cannot fit in a bounded "
                    "window"
                )
            chunks.append(chunk)
        return tuple(chunks)

    @staticmethod
    def _structured_source_leaves(
        value: Any,
        path: tuple[str | int, ...] = (),
    ) -> tuple[tuple[tuple[str | int, ...], Any], ...]:
        if isinstance(value, Mapping):
            if not value:
                return ((path, {}),)
            return tuple(
                leaf
                for key, child in value.items()
                for leaf in PaperResearchMapService._structured_source_leaves(
                    child,
                    (*path, str(key)),
                )
            )
        if isinstance(value, (list, tuple)):
            if not value:
                return ((path, []),)
            return tuple(
                leaf
                for position, child in enumerate(value)
                for leaf in PaperResearchMapService._structured_source_leaves(
                    child,
                    (*path, position),
                )
            )
        return ((path, value),)

    @staticmethod
    def _split_structured_text_value(
        item: _PaperMapSourceItem,
        *,
        path: tuple[str | int, ...],
        value: str,
    ) -> tuple[_PaperMapSourceItem, ...]:
        if not value:
            return (
                replace(
                    item,
                    content={
                        "structured_path": list(path),
                        "fragment_start": 0,
                        "fragment": "",
                    },
                ),
            )

        chunks: list[_PaperMapSourceItem] = []
        start = 0
        while start < len(value):
            low = start + 1
            high = len(value)
            end = start
            while low <= high:
                candidate_end = (low + high) // 2
                candidate = replace(
                    item,
                    content={
                        "structured_path": list(path),
                        "fragment_start": start,
                        "fragment": value[start:candidate_end],
                    },
                )
                if candidate.size <= _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT:
                    end = candidate_end
                    low = candidate_end + 1
                else:
                    high = candidate_end - 1
            if end == start:
                raise ValueError(
                    "paper map structured Source path cannot fit in a bounded "
                    "window"
                )
            if end < len(value):
                end = PaperResearchMapService._natural_text_split(value, start, end)
            chunks.append(
                replace(
                    item,
                    content={
                        "structured_path": list(path),
                        "fragment_start": start,
                        "fragment": value[start:end],
                    },
                )
            )
            start = end
        return tuple(chunks)

    @staticmethod
    def _natural_text_split(text: str, start: int, hard_end: int) -> int:
        chunk = text[start:hard_end]
        minimum = len(chunk) // 2
        for boundary in ("\n\n", ". ", "? ", "! ", "\n"):
            position = chunk.rfind(boundary, minimum)
            if position >= 0:
                return start + position + len(boundary)
        for position in range(len(chunk) - 1, minimum - 1, -1):
            if chunk[position].isspace():
                return start + position + 1
        return hard_end

    def _build_window_payload(
        self,
        *,
        collection_id: str,
        document: Any,
        profile: Any,
        role: str,
        role_window_position: int,
        items: tuple[_PaperMapSourceItem, ...],
    ) -> dict[str, Any]:
        section_paths = self._unique_text_values(
            item.section_path for item in items if item.section_path
        )
        source_unit_ids = [item.source_unit_id for item in items]
        if not all(source_unit_ids) or len(source_unit_ids) != len(
            set(source_unit_ids)
        ):
            raise ValueError("paper map Source-unit ids must be non-empty and unique")
        source_units = [
            {
                "source_unit_id": item.source_unit_id,
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
                "section_path": item.section_path,
                "content": item.content,
            }
            for item in items
        ]
        return {
            "collection_id": collection_id,
            "document_id": document.document_id,
            "title": str(document.title or "")[:160],
            "window_id": f"{role}-{role_window_position}",
            "window_role": role,
            "section_paths": list(section_paths[:_PAPER_MAP_SECTION_PATH_LIMIT]),
            "document_profile": (
                {
                    "doc_type": profile.doc_type,
                    "parsing_warnings": list(profile.parsing_warnings)[:2],
                    "confidence": profile.confidence,
                }
                if profile
                else {}
            ),
            "source_units": source_units,
        }

    def _extract_window_batch(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: Mapping[str, Any],
        paper_map_extractor: PaperResearchMapExtractor,
        extraction_budget: _PaperExtractionBudget,
        attempt: int = 1,
        content_split_depth: int = 0,
    ) -> tuple[tuple[PaperResearchMap, ...], tuple[_PaperSignalInput, ...]]:
        if not extraction_budget.reserve(recovery=attempt > 1):
            failure_kind = extraction_budget.failure_kind or "recovery_budget_exhausted"
            logger.warning(
                "Paper map document budget exhausted; preserving partial coverage "
                "collection_id=%s document_id=%s window_id=%s attempt=%s "
                "source_unit_count=%s failure_kind=%s recovery_calls=%s "
                "max_recovery_calls=%s",
                collection_id,
                document_id,
                payload.get("window_id"),
                attempt,
                len(payload.get("source_units") or ()),
                failure_kind,
                extraction_budget.recovery_calls,
                extraction_budget.max_recovery_calls,
            )
            return (
                (
                    self._failed_source_unit_map(
                        document_id=document_id,
                        payload=payload,
                        failure_kind=failure_kind,
                    ),
                ),
                (),
            )
        try:
            parsed = paper_map_extractor.extract(dict(payload))
            window_map, window_signals = self._resolve_window_result(
                document_id=document_id,
                payload=payload,
                parsed=parsed,
            )
            return (window_map,), window_signals
        except Exception as exc:  # noqa: BLE001
            source_units = tuple(
                unit
                for unit in payload.get("source_units") or ()
                if isinstance(unit, Mapping)
            )
            failure_kind = self._single_source_recovery_kind(exc)
            if (
                len(source_units) > 1
                and failure_kind is not None
                and callable(
                    getattr(paper_map_extractor, "extract_source_signals", None)
                )
            ):
                return self._recover_source_units_through_compact_signals(
                    collection_id=collection_id,
                    document_id=document_id,
                    payload=payload,
                    source_units=source_units,
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                    attempt=attempt,
                    full_failure_kind=failure_kind,
                )
            if len(source_units) > 1:
                logger.warning(
                    "Paper map batch failed; splitting retry "
                    "collection_id=%s document_id=%s window_id=%s attempt=%s "
                    "source_unit_count=%s error=%s",
                    collection_id,
                    document_id,
                    payload.get("window_id"),
                    attempt,
                    len(source_units),
                    exc,
                )
                midpoint = len(source_units) // 2
                child_maps: list[PaperResearchMap] = []
                child_signals: list[_PaperSignalInput] = []
                for branch, child_units in (
                    ("left", source_units[:midpoint]),
                    ("right", source_units[midpoint:]),
                ):
                    retry_maps, retry_signals = self._extract_window_batch(
                        collection_id=collection_id,
                        document_id=document_id,
                        payload=self._payload_with_source_units(
                            payload,
                            source_units=child_units,
                            suffix=f"retry-{branch}",
                        ),
                        paper_map_extractor=paper_map_extractor,
                        extraction_budget=extraction_budget,
                        attempt=attempt + 1,
                    )
                    child_maps.extend(retry_maps)
                    child_signals.extend(retry_signals)
                return tuple(child_maps), tuple(child_signals)

            final_error = exc
            final_failure_kind = failure_kind
            if (
                len(source_units) == 1
                and failure_kind is not None
                and content_split_depth == 0
            ):
                compact_result = self._recover_single_source_through_compact_signals(
                    collection_id=collection_id,
                    document_id=document_id,
                    payload=payload,
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                    attempt=attempt,
                    full_failure_kind=failure_kind,
                )
                if compact_result is not None:
                    return compact_result
            if (
                len(source_units) == 1
                and failure_kind is not None
            ):
                fragment_result = self._recover_single_source_through_fragments(
                    collection_id=collection_id,
                    document_id=document_id,
                    payload=payload,
                    source_unit=source_units[0],
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                    attempt=attempt,
                    content_split_depth=content_split_depth,
                    failure_kind=failure_kind,
                )
                if fragment_result is not None:
                    return fragment_result

            logger.warning(
                "Paper map Source-unit extraction failed permanently "
                "collection_id=%s document_id=%s window_id=%s attempt=%s "
                "source_unit_count=%s error=%s failure_kind=%s",
                collection_id,
                document_id,
                payload.get("window_id"),
                attempt,
                len(source_units),
                final_error,
                final_failure_kind or "non_recoverable",
            )
            return (
                (
                    self._failed_source_unit_map(
                        document_id=document_id,
                        payload=payload,
                        failure_kind=final_failure_kind,
                    ),
                ),
                (),
            )

    def _recover_source_units_through_compact_signals(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: Mapping[str, Any],
        source_units: tuple[Mapping[str, Any], ...],
        paper_map_extractor: PaperResearchMapExtractor,
        extraction_budget: _PaperExtractionBudget,
        attempt: int,
        full_failure_kind: str,
    ) -> tuple[tuple[PaperResearchMap, ...], tuple[_PaperSignalInput, ...]]:
        recovered_maps: list[PaperResearchMap] = []
        recovered_signals: list[_PaperSignalInput] = []
        for position, source_unit in enumerate(source_units, start=1):
            singleton_payload = self._payload_with_source_units(
                payload,
                source_units=(source_unit,),
                suffix=f"compact-{position:02d}",
            )
            recovered = self._recover_single_source_through_compact_signals(
                collection_id=collection_id,
                document_id=document_id,
                payload=singleton_payload,
                paper_map_extractor=paper_map_extractor,
                extraction_budget=extraction_budget,
                attempt=attempt + 1,
                full_failure_kind=full_failure_kind,
            )
            if recovered is None:
                recovered = self._recover_single_source_through_fragments(
                    collection_id=collection_id,
                    document_id=document_id,
                    payload=singleton_payload,
                    source_unit=source_unit,
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                    attempt=attempt + 1,
                    content_split_depth=0,
                    failure_kind=f"compact_{full_failure_kind}",
                )
                if recovered is None:
                    recovered = (
                        (
                            self._failed_source_unit_map(
                                document_id=document_id,
                                payload=singleton_payload,
                                failure_kind="compact_unavailable",
                            ),
                        ),
                        (),
                    )
            maps, signals = recovered
            recovered_maps.extend(maps)
            recovered_signals.extend(signals)
        logger.warning(
            "Paper map batch recovered through source-local signals "
            "collection_id=%s document_id=%s window_id=%s source_unit_count=%s "
            "full_failure_kind=%s",
            collection_id,
            document_id,
            payload.get("window_id"),
            len(source_units),
            full_failure_kind,
        )
        return tuple(recovered_maps), tuple(recovered_signals)

    def _recover_single_source_through_compact_signals(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: Mapping[str, Any],
        paper_map_extractor: PaperResearchMapExtractor,
        extraction_budget: _PaperExtractionBudget,
        attempt: int,
        full_failure_kind: str,
    ) -> (
        tuple[tuple[PaperResearchMap, ...], tuple[_PaperSignalInput, ...]] | None
    ):
        extract_source_signals = getattr(
            paper_map_extractor,
            "extract_source_signals",
            None,
        )
        if not callable(extract_source_signals):
            return None

        final_error: Exception = RuntimeError(full_failure_kind)
        final_failure_kind = f"compact_{full_failure_kind}"
        final_compact_failure_kind: str | None = None
        for compact_attempt in range(
            1,
            _PAPER_MAP_COMPACT_ATTEMPT_LIMIT + 1,
        ):
            if not extraction_budget.reserve(recovery=True):
                final_failure_kind = (
                    extraction_budget.failure_kind or "recovery_budget_exhausted"
                )
                final_error = RuntimeError(final_failure_kind)
                final_compact_failure_kind = None
                break
            try:
                compact = extract_source_signals(dict(payload))
                fallback_warning = (
                    "Paper-scope mapping could not produce valid structured output "
                    "for one Source; retained explicit source-local signals for paper "
                    "reconciliation."
                )
                compact = compact.model_copy(
                    update={
                        "warnings": [fallback_warning, *compact.warnings][:2],
                    }
                )
                window_map, window_signals = self._resolve_window_result(
                    document_id=document_id,
                    payload=payload,
                    parsed=compact,
                )
                logger.warning(
                    "Paper map Source recovered through source-local signals "
                    "collection_id=%s document_id=%s window_id=%s attempt=%s "
                    "compact_attempt=%s source_unit_count=1 full_failure_kind=%s "
                    "signal_count=%s",
                    collection_id,
                    document_id,
                    payload.get("window_id"),
                    attempt,
                    compact_attempt,
                    full_failure_kind,
                    len(compact.unresolved_signals),
                )
                return (window_map,), window_signals
            except Exception as compact_exc:  # noqa: BLE001
                compact_failure_kind = self._single_source_recovery_kind(compact_exc)
                final_error = compact_exc
                final_compact_failure_kind = compact_failure_kind
                final_failure_kind = (
                    f"compact_{compact_failure_kind}"
                    if compact_failure_kind
                    else "compact_non_recoverable"
                )
                will_retry = (
                    compact_attempt < _PAPER_MAP_COMPACT_ATTEMPT_LIMIT
                    and compact_failure_kind
                    in _PAPER_MAP_TRANSIENT_STRUCTURED_FAILURE_KINDS
                )
                logger.warning(
                    "Paper map compact Source recovery failed "
                    "collection_id=%s document_id=%s window_id=%s attempt=%s "
                    "compact_attempt=%s compact_attempt_limit=%s failure_kind=%s "
                    "will_retry=%s error=%s",
                    collection_id,
                    document_id,
                    payload.get("window_id"),
                    attempt,
                    compact_attempt,
                    _PAPER_MAP_COMPACT_ATTEMPT_LIMIT,
                    compact_failure_kind or "non_recoverable",
                    will_retry,
                    compact_exc,
                )
                if will_retry:
                    continue
                break

        source_units = tuple(
            unit
            for unit in payload.get("source_units") or ()
            if isinstance(unit, Mapping)
        )
        if (
            final_compact_failure_kind is not None
            and len(source_units) == 1
            and self._split_single_source_unit_for_retry(source_units[0])
        ):
            logger.warning(
                "Paper map compact Source recovery remains technically unreadable; "
                "allowing bounded content fragmentation collection_id=%s "
                "document_id=%s window_id=%s attempt=%s failure_kind=%s error=%s",
                collection_id,
                document_id,
                payload.get("window_id"),
                attempt,
                final_compact_failure_kind,
                final_error,
            )
            return None

        logger.warning(
            "Paper map Source-unit compact recovery failed permanently "
            "collection_id=%s document_id=%s window_id=%s attempt=%s "
            "source_unit_count=1 error=%s failure_kind=%s",
            collection_id,
            document_id,
            payload.get("window_id"),
            attempt,
            final_error,
            final_failure_kind,
        )
        return (
            (
                self._failed_source_unit_map(
                    document_id=document_id,
                    payload=payload,
                    failure_kind=final_failure_kind,
                ),
            ),
            (),
        )

    def _recover_single_source_through_fragments(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: Mapping[str, Any],
        source_unit: Mapping[str, Any],
        paper_map_extractor: PaperResearchMapExtractor,
        extraction_budget: _PaperExtractionBudget,
        attempt: int,
        content_split_depth: int,
        failure_kind: str,
    ) -> tuple[tuple[PaperResearchMap, ...], tuple[_PaperSignalInput, ...]] | None:
        if content_split_depth >= _PAPER_MAP_RECOVERY_SPLIT_DEPTH_LIMIT:
            return None
        fragments = self._split_single_source_unit_for_retry(source_unit)
        if not fragments:
            return None

        logger.warning(
            "Paper map singleton failed; splitting Source content "
            "collection_id=%s document_id=%s window_id=%s attempt=%s "
            "content_split_depth=%s failure_kind=%s",
            collection_id,
            document_id,
            payload.get("window_id"),
            attempt,
            content_split_depth,
            failure_kind,
        )
        fragment_maps: list[PaperResearchMap] = []
        fragment_signals: list[_PaperSignalInput] = []
        for branch, fragment in zip(("left", "right"), fragments, strict=True):
            retry_maps, retry_signals = self._extract_window_batch(
                collection_id=collection_id,
                document_id=document_id,
                payload=self._payload_with_source_units(
                    payload,
                    source_units=(fragment,),
                    suffix=f"content-{branch}",
                ),
                paper_map_extractor=paper_map_extractor,
                extraction_budget=extraction_budget,
                attempt=attempt + 1,
                content_split_depth=content_split_depth + 1,
            )
            fragment_maps.extend(retry_maps)
            fragment_signals.extend(retry_signals)
        return (
            self._collapse_single_source_fragment_coverage(
                payload=payload,
                maps=tuple(fragment_maps),
            ),
            tuple(fragment_signals),
        )

    @staticmethod
    def _single_source_recovery_kind(error: Exception) -> str | None:
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
        return None

    @classmethod
    def _split_single_source_unit_for_retry(
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
                for candidate_path, value in cls._structured_source_leaves(content)
                if isinstance(value, str)
            ]
            if not candidates:
                return ()
            path, text = max(candidates, key=lambda item: len(item[1]))
        else:
            return ()

        minimum = _PAPER_MAP_RECOVERY_FRAGMENT_MIN_CHAR_LIMIT
        if len(text) < minimum * 2:
            return ()
        midpoint = len(text) // 2
        hard_end = min(
            len(text) - minimum,
            midpoint + min(200, len(text) // 10),
        )
        split_at = cls._natural_text_split(text, 0, hard_end)
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
    def _collapse_single_source_fragment_coverage(
        *,
        payload: Mapping[str, Any],
        maps: tuple[PaperResearchMap, ...],
    ) -> tuple[PaperResearchMap, ...]:
        source_units = [
            unit
            for unit in payload.get("source_units") or ()
            if isinstance(unit, Mapping)
        ]
        if len(source_units) != 1:
            raise ValueError("content-fragment recovery requires one Source unit")
        source_unit = source_units[0]
        source_unit_id = str(source_unit.get("source_unit_id") or "")
        coverage = tuple(
            item for paper_map in maps for item in paper_map.source_unit_coverage
        )
        if not coverage or any(
            item.source_unit_id != source_unit_id for item in coverage
        ):
            raise ValueError(
                "content-fragment recovery produced invalid Source coverage"
            )

        statuses = {item.status for item in coverage}
        if PaperSourceUnitCoverageStatus.EXTRACTION_FAILED in statuses:
            status = PaperSourceUnitCoverageStatus.EXTRACTION_FAILED
            reason = next(
                (
                    item.reason
                    for item in coverage
                    if item.status is status and item.reason
                ),
                "Paper map Source-unit extraction remained incomplete after "
                "bounded content splitting.",
            )
        elif PaperSourceUnitCoverageStatus.RELATIONSHIP_EMITTED in statuses:
            status = PaperSourceUnitCoverageStatus.RELATIONSHIP_EMITTED
            reason = None
        elif PaperSourceUnitCoverageStatus.UNRESOLVED_SIGNAL_EMITTED in statuses:
            status = PaperSourceUnitCoverageStatus.UNRESOLVED_SIGNAL_EMITTED
            reason = None
        else:
            status = PaperSourceUnitCoverageStatus.NO_STUDY_SIGNAL
            reason = (
                "No study relationship or unresolved signal was emitted for this "
                "Source unit."
            )

        parent_coverage = PaperSourceUnitCoverage.from_mapping(
            {
                "source_unit_id": source_unit_id,
                "window_id": payload.get("window_id"),
                "source_kind": source_unit.get("source_kind"),
                "source_ref": source_unit.get("source_ref"),
                "status": status.value,
                "reason": reason,
            }
        )
        return tuple(
            replace(
                paper_map,
                source_unit_coverage=(parent_coverage,) if position == 0 else (),
            )
            for position, paper_map in enumerate(maps)
        )

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

    def _fit_payload_to_prompt_limit(
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
            raise ValueError(
                "one PaperResearchMap Source unit exceeds the complete prompt-token limit: "
                f"window_id={candidate.get('window_id')} "
                f"prompt_tokens={prompt_tokens} "
                f"limit={PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT}"
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
                self._fit_payload_to_prompt_limit(
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
    ) -> tuple[PaperResearchMap, tuple[_PaperSignalInput, ...]]:
        document_profile = payload.get("document_profile")
        is_review = isinstance(document_profile, Mapping) and (
            str(document_profile.get("doc_type") or "").strip() == "review"
        )
        if is_review:
            parsed = _review_synthesis_only(parsed)
        if parsed.output_saturated:
            raise StructuredOutputSaturatedError(
                "PaperResearchMap model reported that the bounded output omitted visible facts"
            )
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
            retained_relationships = []
            for relationship in study.relationships:
                retained_relationships.append(relationship)
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
    ) -> _PaperSignalInput:
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
        domain_signal = PaperResearchSignal.from_mapping(
            {
                **dict(signal),
                "document_id": document_id,
                "source_refs": cls._source_refs_from_units(resolved),
            }
        )
        return _PaperSignalInput(
            signal=domain_signal,
            source_contexts=tuple(
                {
                    "source_unit_id": str(unit.get("source_unit_id") or ""),
                    "source_kind": str(unit.get("source_kind") or ""),
                    "source_ref": str(unit.get("source_ref") or ""),
                    "section_path": str(unit.get("section_path") or ""),
                    "excerpt": cls._source_excerpt(unit.get("content")),
                }
                for unit in resolved
            ),
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
    def _source_excerpt(content: Any) -> str:
        return PaperResearchMapService._source_content_text(content)[:800]

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

    def _reconcile_paper_signals(
        self,
        paper_map: PaperResearchMap,
        signal_inputs: list[_PaperSignalInput],
        *,
        signal_reconciler: PaperSignalReconciler,
        extraction_budget: _PaperExtractionBudget,
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
                        reason="no paper-scope bridge was found in this paper",
                    )
                    for item in unique_inputs
                ),
            )

        self._notify_progress(
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
            studies=self._consolidate_studies(
                (*paper_map.studies, *reconciled_studies),
                document_id=paper_map.document_id,
            ),
            unresolved_signals=tuple(unresolved_signals),
        )

    @staticmethod
    def _signal_inputs_share_scope_evidence(
        left: _PaperSignalInput,
        right: _PaperSignalInput,
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

        def source_positions(item: _PaperSignalInput) -> tuple[int, ...]:
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
        signal_inputs: tuple[_PaperSignalInput, ...],
        *,
        signal_reconciler: PaperSignalReconciler,
    ) -> tuple[tuple[_PaperSignalInput, ...], ...]:
        variables = tuple(
            item for item in signal_inputs if item.signal.signal_type == "variable"
        )
        outcomes = tuple(
            item for item in signal_inputs if item.signal.signal_type == "outcome"
        )
        batches: list[tuple[_PaperSignalInput, ...]] = []
        for outcome in outcomes:
            candidates = tuple(
                variable
                for variable in variables
                if self._signal_inputs_share_scope_evidence(variable, outcome)
            )
            current_variables: list[_PaperSignalInput] = []
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
        signal_inputs: tuple[_PaperSignalInput, ...],
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
        signal_inputs: list[_PaperSignalInput],
    ) -> tuple[_PaperSignalInput, ...]:
        unique: list[_PaperSignalInput] = []
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
        signal_inputs: tuple[_PaperSignalInput, ...],
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
                signals = tuple(signals_by_id[signal_id] for signal_id in signal_ids)
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
                        for ref in cls._unique_source_refs(
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

    def _consolidate_window_maps(
        self,
        document_id: str,
        window_maps: list[PaperResearchMap],
        *,
        profile: Any,
    ) -> PaperResearchMap:
        doc_role = self._consolidate_doc_role(window_maps, profile=profile)
        studies = self._consolidate_studies(
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

    @staticmethod
    def _assess_paper_map(
        paper_map: PaperResearchMap,
        *,
        signals: tuple[PaperResearchSignal, ...],
        final: bool,
    ) -> _PaperMapAssessment:
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
        if owned_relationships or has_review_judgment:
            return _PaperMapAssessment(
                status="sufficient",
                limitations=tuple(limitations),
            )

        visible_signals = tuple((*signals, *paper_map.unresolved_signals))
        has_variable = any(
            signal.signal_type == "variable" for signal in visible_signals
        )
        has_outcome = any(
            signal.signal_type == "outcome" for signal in visible_signals
        )
        has_broad_outcome = any(
            signal.signal_type == "outcome"
            and property_matching.outcome_label_requires_resolution(signal.label)
            for signal in visible_signals
        )
        has_unowned_relationship = any(
            study.relationships
            and study.claim_scope not in {"current_work", "synthesis"}
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
            return _PaperMapAssessment(
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
        return _PaperMapAssessment(
            status="needs_expansion",
            limitations=tuple(limitations or ("missing_research_scope",)),
            expansion_focus=focus,
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
    def _consolidate_studies(
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
        relationships: list[PaperResearchRelationship] = list(existing.relationships)
        for relationship in duplicate.relationships:
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
                        for source_ref in cls._unique_source_refs(
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
    def _unique_source_refs(values: Any) -> tuple[Any, ...]:
        unique: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for value in values:
            key = (value.source_kind, value.source_ref)
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        return tuple(unique)

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

    def _source_ref_window_role(
        self,
        document_tree: SourceDocumentTree | None,
        *,
        source_ref_kind: str,
        source_ref_id: str,
        heading_path: str | None,
    ) -> str:
        heading_role = self._window_role_from_text(heading_path)
        if heading_role != "unknown":
            return heading_role
        if document_tree is not None:
            node = document_tree.node_for_source_ref(source_ref_kind, source_ref_id)
            if node is not None:
                return self._tree_node_window_role(document_tree, node)
        return "unknown"

    def _tree_node_window_role(
        self,
        document_tree: SourceDocumentTree,
        node: Any,
    ) -> str:
        current = node
        while current is not None:
            semantic_role = str(getattr(current, "semantic_role", "") or "")
            if semantic_role == "references":
                return "references"
            mapped_role = _PAPER_MAP_ROLE_BY_SEMANTIC_ROLE.get(semantic_role)
            if mapped_role is not None:
                return mapped_role
            parent_id = getattr(current, "parent_id", None)
            current = document_tree.nodes.get(parent_id) if parent_id else None
        return self._window_role_from_text(self._tree_section_label(node))

    @staticmethod
    def _window_role_from_text(value: Any) -> str:
        text = " ".join(
            "".join(character if character.isalpha() else " " for character in str(value))
            .lower()
            .split()
        )
        if "reference" in text:
            return "references"
        if "abstract" in text or "introduction" in text:
            return "overview"
        if any(token in text for token in ("method", "material", "experimental")):
            return "methods"
        if any(token in text for token in ("result", "discussion")):
            return "results"
        if "conclusion" in text:
            return "conclusion"
        return "unknown"

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

    @staticmethod
    def _document_tree_nodes_in_order(
        document_tree: SourceDocumentTree,
    ) -> list[Any]:
        return sorted(
            document_tree.nodes.values(),
            key=lambda node: (int(getattr(node, "order", 0) or 0), node.node_id),
        )

    @staticmethod
    def _tree_node_in_reference_branch(
        document_tree: SourceDocumentTree,
        node: Any,
    ) -> bool:
        current = node
        while current is not None:
            if current.node_type in {"references_section", "reference_entry"}:
                return True
            if getattr(current, "semantic_role", None) == "references":
                return True
            parent_id = getattr(current, "parent_id", None)
            current = document_tree.nodes.get(parent_id) if parent_id else None
        return False

    @staticmethod
    def _tree_section_label(node: Any) -> str:
        if getattr(node, "heading_path", ()):
            return " > ".join(str(part) for part in node.heading_path if str(part))
        title = str(getattr(node, "title", "") or "").strip()
        return title or "Unsectioned"

    @staticmethod
    def _resolve_source_filename(document: Any) -> str | None:
        metadata = getattr(document, "metadata", {}) or {}
        for key in ("source_filename", "original_filename", "stored_filename"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return None

    @staticmethod
    def _notify_progress(
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


__all__ = ["PaperResearchMapService"]
