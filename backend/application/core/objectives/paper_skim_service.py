from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.extraction import ObjectiveExtractor
from application.core.objectives.schemas import (
    StructuredPaperStudy,
    StructuredPaperSignalReconciliation,
    StructuredPaperSkim,
)
from domain.core import (
    PaperSkim,
    PaperSourceUnitCoverage,
    PaperSourceUnitCoverageStatus,
    PaperStudy,
    PaperStudyRelationship,
    PaperStudySignal,
)
from domain.source import SourceDocument, SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_SKIM_WINDOW_CHARS = 4000
_SKIM_WINDOW_SOURCE_UNIT_LIMIT = 12
_SKIM_HEADING_LIMIT = 16
_SKIM_WARNING_LIMIT = 2
_SKIM_WINDOW_ROLES = ("overview", "methods", "results", "conclusion", "unknown")
_SKIM_ROLE_BY_SEMANTIC_ROLE = {
    "abstract": "overview",
    "introduction": "overview",
    "methods": "methods",
    "results": "results",
    "conclusion": "conclusion",
}
_EVIDENCE_DENSITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class _SkimSourceItem:
    role: str
    order: int
    source_kind: str
    source_ref: str
    content: Any
    section_path: str

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
    signal: PaperStudySignal
    source_contexts: tuple[dict[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.signal.to_record(),
            "sources": [dict(source) for source in self.source_contexts],
        }


class PaperSkimService:
    """Screen every paper through bounded source windows and consolidate its map."""

    def build_collection_paper_skims(
        self,
        collection_id: str,
        *,
        documents: tuple[SourceDocument, ...],
        profiles_by_document_id: Mapping[str, Any],
        document_trees_by_document_id: Mapping[
            str,
            SourceDocumentTree | None,
        ],
        extractor: ObjectiveExtractor,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[PaperSkim, ...]:
        logger.info(
            "Research objective paper skim started collection_id=%s document_count=%s",
            collection_id,
            len(documents),
        )
        paper_skims: list[PaperSkim] = []
        document_count = len(documents)
        for document_position, document in enumerate(documents, start=1):
            source_filename = self._resolve_source_filename(document)
            document_blocks = list(document.blocks)
            document_tables = list(document.tables)
            document_table_rows = list(document.table_rows)
            document_figures = list(document.figures)
            logger.info(
                "Research objective paper skim document started collection_id=%s document_id=%s document_position=%s document_count=%s block_count=%s table_count=%s figure_count=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                len(document_blocks),
                len(document_tables),
                len(document_figures),
            )
            payloads = self._build_paper_skim_payloads(
                collection_id=collection_id,
                document=document,
                profile=profiles_by_document_id.get(document.document_id),
                blocks=document_blocks,
                tables=document_tables,
                table_rows=document_table_rows,
                figures=document_figures,
                document_tree=document_trees_by_document_id.get(document.document_id),
            )
            window_skims: list[PaperSkim] = []
            paper_signals: list[_PaperSignalInput] = []
            window_count = len(payloads)
            for window_position, payload in enumerate(payloads, start=1):
                self._notify_progress(
                    progress_callback,
                    phase="objective_paper_skim_started",
                    current=document_position,
                    total=document_count,
                    unit="documents",
                    message="Scanning papers for candidate research objectives.",
                    active_document_id=document.document_id,
                    active_document_title=getattr(document, "title", None),
                    active_source_filename=source_filename,
                    active_window_position=window_position,
                    active_window_count=window_count,
                    active_window_role=payload["window_role"],
                )
                try:
                    parsed = extractor.extract_paper_skim(payload)
                    window_skim, window_signals = self._resolve_window_result(
                        document_id=document.document_id,
                        payload=payload,
                        parsed=parsed,
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Paper skim window extraction failed; preserving Source-unit "
                        "coverage collection_id=%s document_id=%s window_id=%s",
                        collection_id,
                        document.document_id,
                        payload["window_id"],
                        exc_info=True,
                    )
                    window_skim = self._failed_window_skim(
                        document_id=document.document_id,
                        payload=payload,
                    )
                    window_signals = ()
                window_skims.append(window_skim)
                paper_signals.extend(window_signals)
            paper_skim = self._consolidate_window_skims(
                document.document_id,
                window_skims,
                profile=profiles_by_document_id.get(document.document_id),
            )
            paper_skim = self._reconcile_paper_signals(
                paper_skim,
                paper_signals,
                extractor=extractor,
                progress_callback=progress_callback,
                document_position=document_position,
                document_count=document_count,
                document_title=getattr(document, "title", None),
                source_filename=source_filename,
            )
            paper_skims.append(paper_skim)
            logger.info(
                "Research objective paper skim document finished collection_id=%s document_id=%s document_position=%s document_count=%s window_count=%s doc_role=%s study_count=%s relationship_count=%s unresolved_signal_count=%s completed_documents=%s remaining_documents=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                window_count,
                paper_skim.doc_role,
                len(paper_skim.studies),
                sum(len(study.relationships) for study in paper_skim.studies),
                len(paper_skim.unresolved_signals),
                document_position,
                max(document_count - document_position, 0),
            )
        return tuple(paper_skims)

    def _build_paper_skim_payloads(
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
    ) -> list[dict[str, Any]]:
        items = self._build_source_items(
            document=document,
            blocks=blocks,
            tables=tables,
            table_rows=table_rows,
            figures=figures,
            document_tree=document_tree,
        )
        grouped_items = {role: [] for role in _SKIM_WINDOW_ROLES}
        for item in items:
            grouped_items[item.role].append(item)

        payloads: list[dict[str, Any]] = []
        for role in _SKIM_WINDOW_ROLES:
            role_windows = self._pack_source_items(grouped_items[role])
            for role_window_position, window_items in enumerate(role_windows, start=1):
                payloads.append(
                    self._build_window_payload(
                        collection_id=collection_id,
                        document=document,
                        profile=profile,
                        role=role,
                        role_window_position=role_window_position,
                        items=window_items,
                    )
                )
        if payloads:
            return payloads
        return [
            self._build_window_payload(
                collection_id=collection_id,
                document=document,
                profile=profile,
                role="unknown",
                role_window_position=1,
                items=(),
            )
        ]

    def _build_source_items(
        self,
        *,
        document: Any,
        blocks: list[Any],
        tables: list[Any],
        table_rows: list[Any],
        figures: list[Any],
        document_tree: SourceDocumentTree | None,
    ) -> list[_SkimSourceItem]:
        items = (
            self._text_items_from_tree(document_tree)
            if document_tree is not None
            else self._text_items_from_blocks(blocks)
        )
        if not items and str(getattr(document, "text", "") or "").strip():
            items = [
                _SkimSourceItem(
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
    ) -> list[_SkimSourceItem]:
        return [
            _SkimSourceItem(
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

    def _text_items_from_blocks(self, blocks: list[Any]) -> list[_SkimSourceItem]:
        items: list[_SkimSourceItem] = []
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
                _SkimSourceItem(
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
    ) -> list[_SkimSourceItem]:
        items: list[_SkimSourceItem] = []
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
            items.append(
                _SkimSourceItem(
                    role=role,
                    order=200_000 + int(table.table_order or 0) * 10_000,
                    source_kind="table",
                    source_ref=table.table_id,
                    content={
                        "table_id": table.table_id,
                        "caption_text": str(table.caption_text or ""),
                        "heading_path": str(table.heading_path or ""),
                        "column_headers": [
                            str(value) for value in table.column_headers
                        ],
                    },
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
                            "row_index": row_index,
                            "values": [str(value) for value in row],
                        },
                    )
                    for row_index, row in enumerate(table.table_matrix)
                    if any(str(value).strip() for value in row)
                ]
            )
            items.extend(
                _SkimSourceItem(
                    role=role,
                    order=(
                        200_000
                        + int(table.table_order or 0) * 10_000
                        + row_position
                        + 1
                    ),
                    source_kind=source_kind,
                    source_ref=source_ref,
                    content={"table_id": table.table_id, **row_record},
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
    ) -> list[_SkimSourceItem]:
        items: list[_SkimSourceItem] = []
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
                _SkimSourceItem(
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
        items: list[_SkimSourceItem],
    ) -> list[tuple[_SkimSourceItem, ...]]:
        windows: list[tuple[_SkimSourceItem, ...]] = []
        current: list[_SkimSourceItem] = []
        current_size = 0
        bounded_items = (
            bounded_item
            for item in items
            for bounded_item in PaperSkimService._split_oversized_source_item(item)
        )
        for item in bounded_items:
            separator_size = 2 if current else 0
            if current and (
                len(current) >= _SKIM_WINDOW_SOURCE_UNIT_LIMIT
                or current_size + separator_size + item.size > _SKIM_WINDOW_CHARS
            ):
                windows.append(tuple(current))
                current = []
                current_size = 0
                separator_size = 0
            current.append(item)
            current_size += separator_size + item.size
        if current:
            windows.append(tuple(current))
        return windows

    @staticmethod
    def _split_oversized_source_item(
        item: _SkimSourceItem,
    ) -> tuple[_SkimSourceItem, ...]:
        if item.size <= _SKIM_WINDOW_CHARS:
            return (item,)
        if isinstance(item.content, Mapping):
            return PaperSkimService._split_structured_source_item(item)
        if not isinstance(item.content, str):
            raise ValueError(
                "paper skim Source item cannot fit in a bounded window"
            )
        text = str(item.content)
        chunks: list[str] = []
        start = 0
        while len(text) - start > _SKIM_WINDOW_CHARS:
            hard_end = start + _SKIM_WINDOW_CHARS
            split_at = PaperSkimService._natural_text_split(text, start, hard_end)
            chunks.append(text[start:split_at])
            start = split_at
        chunks.append(text[start:])
        return tuple(
            _SkimSourceItem(
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
    def _split_structured_source_item(
        item: _SkimSourceItem,
    ) -> tuple[_SkimSourceItem, ...]:
        chunks: list[_SkimSourceItem] = []
        for path, value in PaperSkimService._structured_source_leaves(item.content):
            if isinstance(value, str):
                chunks.extend(
                    PaperSkimService._split_structured_text_value(
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
            if chunk.size > _SKIM_WINDOW_CHARS:
                raise ValueError(
                    "paper skim structured Source value cannot fit in a bounded "
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
                for leaf in PaperSkimService._structured_source_leaves(
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
                for leaf in PaperSkimService._structured_source_leaves(
                    child,
                    (*path, position),
                )
            )
        return ((path, value),)

    @staticmethod
    def _split_structured_text_value(
        item: _SkimSourceItem,
        *,
        path: tuple[str | int, ...],
        value: str,
    ) -> tuple[_SkimSourceItem, ...]:
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

        chunks: list[_SkimSourceItem] = []
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
                if candidate.size <= _SKIM_WINDOW_CHARS:
                    end = candidate_end
                    low = candidate_end + 1
                else:
                    high = candidate_end - 1
            if end == start:
                raise ValueError(
                    "paper skim structured Source path cannot fit in a bounded "
                    "window"
                )
            if end < len(value):
                end = PaperSkimService._natural_text_split(value, start, end)
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
        items: tuple[_SkimSourceItem, ...],
    ) -> dict[str, Any]:
        section_paths = self._unique_text_values(
            item.section_path for item in items if item.section_path
        )
        source_units = [
            {
                "source_unit_id": f"{role}-{role_window_position}-source-{position}",
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
                "section_path": item.section_path,
                "content": item.content,
            }
            for position, item in enumerate(items, start=1)
        ]
        return {
            "collection_id": collection_id,
            "document_id": document.document_id,
            "title": str(document.title or "")[:160],
            "window_id": f"{role}-{role_window_position}",
            "window_role": role,
            "section_paths": list(section_paths[:_SKIM_HEADING_LIMIT]),
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

    def _resolve_window_result(
        self,
        *,
        document_id: str,
        payload: Mapping[str, Any],
        parsed: StructuredPaperSkim,
    ) -> tuple[PaperSkim, tuple[_PaperSignalInput, ...]]:
        source_units = {
            str(unit.get("source_unit_id") or ""): unit
            for unit in payload.get("source_units") or ()
            if isinstance(unit, Mapping) and str(unit.get("source_unit_id") or "")
        }
        studies = tuple(
            self._study_from_window_result(
                item,
                document_id=document_id,
                source_units=source_units,
            )
            for item in parsed.studies
        )
        signals = tuple(
            self._signal_from_window_result(
                item.model_dump(),
                document_id=document_id,
                source_units=source_units,
            )
            for item in parsed.unresolved_signals
        )
        source_unit_coverage = self._source_unit_coverage_from_window_result(
            payload=payload,
            parsed=parsed,
            source_units=source_units,
        )
        return (
            PaperSkim.from_mapping(
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
                }
            ),
            signals,
        )

    @staticmethod
    def _source_unit_coverage_from_window_result(
        *,
        payload: Mapping[str, Any],
        parsed: StructuredPaperSkim,
        source_units: Mapping[str, Mapping[str, Any]],
    ) -> tuple[PaperSourceUnitCoverage, ...]:
        input_ids = tuple(source_units)
        if len(input_ids) != len(payload.get("source_units") or ()):
            raise ValueError("paper skim window contains duplicate Source-unit ids")

        coverage_by_id: dict[str, Any] = {}
        for item in parsed.source_unit_coverage:
            source_unit_id = str(item.source_unit_id).strip()
            if source_unit_id in coverage_by_id:
                raise ValueError(
                    "paper skim response contains duplicate Source-unit coverage ids"
                )
            if source_unit_id not in source_units:
                raise ValueError(
                    "paper skim response contains unknown Source-unit coverage id"
                )
            coverage_by_id[source_unit_id] = item
        if set(coverage_by_id) != set(input_ids):
            raise ValueError(
                "paper skim response must account for every Source-unit id exactly once"
            )

        relationship_ids = {
            str(source_unit_id).strip()
            for study in parsed.studies
            for relationship in study.relationships
            for source_unit_id in relationship.source_unit_ids
        }
        signal_ids = {
            str(source_unit_id).strip()
            for signal in parsed.unresolved_signals
            for source_unit_id in signal.source_unit_ids
        }
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
            item = coverage_by_id[source_unit_id]
            if item.status != expected_status.value:
                raise ValueError(
                    "paper skim Source-unit coverage does not agree with emitted facts"
                )
            source_unit = source_units[source_unit_id]
            coverage.append(
                PaperSourceUnitCoverage.from_mapping(
                    {
                        "source_unit_id": source_unit_id,
                        "window_id": payload.get("window_id"),
                        "source_kind": source_unit.get("source_kind"),
                        "source_ref": source_unit.get("source_ref"),
                        "status": item.status,
                        "reason": item.reason,
                    }
                )
            )
        return tuple(coverage)

    @staticmethod
    def _failed_window_skim(
        *,
        document_id: str,
        payload: Mapping[str, Any],
    ) -> PaperSkim:
        reason = "Paper skim window extraction or coverage validation failed."
        return PaperSkim.from_mapping(
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
        study: StructuredPaperStudy,
        *,
        document_id: str,
        source_units: Mapping[str, Mapping[str, Any]],
    ) -> PaperStudy:
        relationships: list[dict[str, Any]] = []
        for relationship in study.relationships:
            resolved = cls._resolved_source_units(
                relationship.source_unit_ids,
                source_units=source_units,
            )
            if resolved is None:
                raise ValueError(
                    "paper study relationship contains an unknown Source-unit id"
                )
            relationships.append(
                {
                    **relationship.model_dump(exclude={"source_unit_ids"}),
                    "source_refs": cls._source_refs_from_units(resolved),
                }
            )
        return PaperStudy.from_mapping(
            {
                **study.model_dump(exclude={"relationships"}),
                "document_id": document_id,
                "relationships": relationships,
            }
        )

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
            raise ValueError("paper study signal requires Source-unit ids")
        resolved = cls._resolved_source_units(
            source_unit_ids,
            source_units=source_units,
        )
        if resolved is None:
            raise ValueError("paper study signal contains an unknown Source-unit id")
        domain_signal = PaperStudySignal.from_mapping(
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
        if isinstance(content, str):
            return content[:800]
        return json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
        )[:800]

    def _reconcile_paper_signals(
        self,
        paper_skim: PaperSkim,
        signal_inputs: list[_PaperSignalInput],
        *,
        extractor: ObjectiveExtractor,
        progress_callback: ProgressCallback | None,
        document_position: int,
        document_count: int,
        document_title: str | None,
        source_filename: str | None,
    ) -> PaperSkim:
        unique_inputs = self._unique_signal_inputs(signal_inputs)
        if not unique_inputs:
            return paper_skim

        signal_types = {item.signal.signal_type for item in unique_inputs}
        if len(signal_types) == 1:
            missing_role = "outcome" if "variable" in signal_types else "variable"
            reason = f"no {missing_role} signal was found in this paper"
            return replace(
                paper_skim,
                unresolved_signals=tuple(
                    replace(item.signal, reason=reason) for item in unique_inputs
                ),
            )

        self._notify_progress(
            progress_callback,
            phase="objective_paper_skim_started",
            current=document_position,
            total=document_count,
            unit="documents",
            message="Reconciling source-linked signals within one paper.",
            active_document_id=paper_skim.document_id,
            active_document_title=document_title,
            active_source_filename=source_filename,
            active_operation="paper_reconciliation",
        )
        try:
            parsed = extractor.reconcile_paper_signals(
                {
                    "document_id": paper_skim.document_id,
                    "signals": [item.to_payload() for item in unique_inputs],
                }
            )
            reconciled_studies, unresolved_signals = (
                self._validate_signal_reconciliation(
                    parsed,
                    unique_inputs,
                    document_id=paper_skim.document_id,
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Paper study signal reconciliation failed; retaining unresolved signals document_id=%s",
                paper_skim.document_id,
                exc_info=True,
            )
            reconciled_studies = ()
            unresolved_signals = tuple(
                replace(item.signal, reason="paper signal reconciliation failed")
                for item in unique_inputs
            )
        return replace(
            paper_skim,
            studies=self._consolidate_studies(
                (*paper_skim.studies, *reconciled_studies),
                document_id=paper_skim.document_id,
            ),
            unresolved_signals=unresolved_signals,
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
    ) -> tuple[tuple[PaperStudy, ...], tuple[PaperStudySignal, ...]]:
        signals_by_id = {item.signal.signal_id: item.signal for item in signal_inputs}
        if len(signals_by_id) != len(signal_inputs):
            raise ValueError("paper signals do not have unique ids")

        linked_ids: set[str] = set()
        conflicting_reasons_by_id: dict[str, str] = {}
        studies: list[PaperStudy] = []
        for parsed_study in parsed.studies:
            study_groups: list[tuple[list[dict[str, Any]], set[str]]] = []
            for relationship in parsed_study.relationships:
                signal_ids = tuple(
                    str(value).strip() for value in relationship.signal_ids
                )
                if len(signal_ids) != len(set(signal_ids)):
                    raise ValueError("paper signal relationship contains duplicate ids")
                if any(signal_id not in signals_by_id for signal_id in signal_ids):
                    raise ValueError("paper signal relationship contains an unknown id")
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
                    raise ValueError(
                        "paper signal relationship requires variables and one outcome"
                    )
                context_conflicts = property_matching.paper_signal_context_conflicts(
                    signal.to_record() for signal in signals
                )
                if context_conflicts:
                    reason = (
                        "Conflicting reconciliation context: "
                        f"{', '.join(context_conflicts)}."
                    )
                    for signal_id in signal_ids:
                        conflicting_reasons_by_id.setdefault(signal_id, reason)
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
                    study_groups.append(([relationship_record], set(signal_ids)))
                else:
                    compatible_group[0].append(relationship_record)
                    compatible_group[1].update(signal_ids)

            for study_relationships, study_signal_ids in study_groups:
                if study_signal_ids & linked_ids:
                    raise ValueError("paper signal cannot belong to multiple studies")
                study_signals = tuple(
                    signals_by_id[signal_id] for signal_id in study_signal_ids
                )
                studies.append(
                    PaperStudy.from_mapping(
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
                raise ValueError("unresolved paper signal contains an unknown id")
            if signal_id in linked_ids or signal_id in unresolved_by_id:
                raise ValueError("paper signal was accounted for more than once")
            unresolved_by_id[signal_id] = str(unresolved.reason).strip()
        for signal_id, reason in conflicting_reasons_by_id.items():
            if signal_id in linked_ids or signal_id in unresolved_by_id:
                continue
            unresolved_by_id[signal_id] = reason
        if linked_ids | set(unresolved_by_id) != set(signals_by_id):
            raise ValueError("paper signal reconciliation did not account for every signal")
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
        signals: tuple[PaperStudySignal, ...],
    ) -> bool:
        return not property_matching.paper_signal_context_conflicts(
            signal.to_record() for signal in signals
        )

    @classmethod
    def _shared_signal_study_context(
        cls,
        signals: tuple[PaperStudySignal, ...],
    ) -> dict[str, Any]:
        if not cls._signal_contexts_are_compatible(signals):
            raise ValueError("paper study signals have conflicting contexts")

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
            "sample_context": cls._unique_text_values(
                value for signal in signals for value in signal.sample_context
            ),
            "test_context": cls._unique_text_values(
                value for signal in signals for value in signal.test_context
            ),
            "comparator": known_scalar("comparator"),
            "fixed_conditions": cls._unique_text_values(
                value for signal in signals for value in signal.fixed_conditions
            ),
        }

    def _consolidate_window_skims(
        self,
        document_id: str,
        window_skims: list[PaperSkim],
        *,
        profile: Any,
    ) -> PaperSkim:
        studies = self._consolidate_studies(
            tuple(
                study
                for skim in window_skims
                for study in skim.studies
            ),
            document_id=document_id,
        )
        return PaperSkim(
            document_id=document_id,
            doc_role=self._consolidate_doc_role(window_skims, profile=profile),
            studies=studies,
            evidence_density=max(
                (skim.evidence_density for skim in window_skims),
                key=lambda value: _EVIDENCE_DENSITY_RANK.get(value, 0),
                default="unknown",
            ),
            confidence=max((skim.confidence for skim in window_skims), default=0.0),
            warnings=self._unique_text_values(
                warning for skim in window_skims for warning in skim.warnings
            )[:_SKIM_WARNING_LIMIT],
            source_unit_coverage=tuple(
                item
                for skim in window_skims
                for item in skim.source_unit_coverage
            ),
        )

    @classmethod
    def _consolidate_studies(
        cls,
        studies: tuple[PaperStudy, ...],
        *,
        document_id: str,
    ) -> tuple[PaperStudy, ...]:
        consolidated: list[PaperStudy] = []
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
        left: PaperStudy,
        right: PaperStudy,
    ) -> bool:
        return (
            cls._study_identity_matches(left, right)
            and cls._relationship_sets_overlap(left.relationships, right.relationships)
        )

    @classmethod
    def _study_identity_matches(cls, left: PaperStudy, right: PaperStudy) -> bool:
        for field_name in ("design_type", "claim_scope"):
            left_value = getattr(left, field_name)
            right_value = getattr(right, field_name)
            if (
                left_value != "uncertain"
                and right_value != "uncertain"
                and left_value != right_value
            ):
                return False
        for field_name in ("experiment_label", "comparator"):
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
            "sample_context",
            "test_context",
            "fixed_conditions",
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
        left: tuple[PaperStudyRelationship, ...],
        right: tuple[PaperStudyRelationship, ...],
    ) -> bool:
        return any(
            cls._relationships_are_duplicates(left_item, right_item)
            for left_item in left
            for right_item in right
        )

    @classmethod
    def _relationships_are_duplicates(
        cls,
        left: PaperStudyRelationship,
        right: PaperStudyRelationship,
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
    def _study_source_keys(study: PaperStudy) -> set[tuple[str, str]]:
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
        existing: PaperStudy,
        duplicate: PaperStudy,
        *,
        document_id: str,
    ) -> PaperStudy:
        relationships: list[PaperStudyRelationship] = list(existing.relationships)
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
            relationships[duplicate_position] = PaperStudyRelationship.from_mapping(
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
        return PaperStudy.from_mapping(
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
                "sample_context": cls._unique_text_values(
                    (*existing.sample_context, *duplicate.sample_context)
                ),
                "test_context": cls._unique_text_values(
                    (*existing.test_context, *duplicate.test_context)
                ),
                "comparator": existing.comparator or duplicate.comparator,
                "fixed_conditions": cls._unique_text_values(
                    (*existing.fixed_conditions, *duplicate.fixed_conditions)
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
    def _consolidate_doc_role(window_skims: list[PaperSkim], *, profile: Any) -> str:
        profile_role = str(getattr(profile, "doc_type", "") or "").strip()
        if profile_role in {"experimental", "review", "mixed", "uncertain"}:
            return profile_role
        roles = {
            skim.doc_role for skim in window_skims if skim.doc_role != "uncertain"
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
            mapped_role = _SKIM_ROLE_BY_SEMANTIC_ROLE.get(semantic_role)
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


__all__ = ["PaperSkimService"]
