"""Source selection and bounded Paper Map window construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
import json
from typing import Any, Callable

from application.core.objectives import property_matching
from application.core.objectives.discovery.study_window import (
    PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT,
    PaperResearchMapExtractor,
)
from application.core.objectives.paper_map_aggregation import PaperMapSignalInput
from domain.core import PaperResearchMap
from domain.source import SourceDocumentTree

_PAPER_MAP_INITIAL_SOURCE_LIMIT = 16
_PAPER_MAP_VISUAL_SOURCE_LIMIT = 4
_PAPER_MAP_EXPANSION_SOURCE_LIMIT = 8
_PAPER_MAP_FALLBACK_SOURCE_LIMIT_PER_EDGE = 4
_PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT = 4000
_PAPER_MAP_SECTION_PATH_LIMIT = 16
_PAPER_MAP_TABLE_CAPTION_CHAR_LIMIT = 1600
_PAPER_MAP_FIGURE_CAPTION_CHAR_LIMIT = 3500
_PAPER_MAP_HEADING_PATH_CHAR_LIMIT = 240
_PAPER_MAP_COLUMN_HEADER_LIMIT = 12
_PAPER_MAP_COLUMN_HEADER_CHAR_LIMIT = 120
_PAPER_MAP_EXPANSION_SOURCE_BUDGET = 24
_PAPER_MAP_WINDOW_ROLES = ("overview", "methods", "results", "conclusion", "unknown")
_PAPER_MAP_ROLE_BY_SEMANTIC_ROLE = {
    "abstract": "overview",
    "introduction": "overview",
    "methods": "methods",
    "results": "results",
    "conclusion": "conclusion",
}


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
        return len(json.dumps(self.content, ensure_ascii=False, separators=(",", ":")))


class PaperMapSourceSelector:
    """Select readable paper Sources and build bounded model windows."""

    def __init__(self, fit_payload: Callable[..., list[dict[str, Any]]]) -> None:
        self._fit_payload = fit_payload


    def build_payloads(
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
        expansion_search_terms: tuple[str, ...] = (),
        expansion_source_limit: int = _PAPER_MAP_EXPANSION_SOURCE_LIMIT,
        reading_round: int = 2,
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
                search_terms=expansion_search_terms,
                limit=expansion_source_limit,
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
                search_terms=expansion_search_terms,
                limit=expansion_source_limit,
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
                    payload["reading_round"] = reading_round
                    payload["expansion_focus"] = selection_focus
                    payload["window_id"] = (
                        f"round-{reading_round}.{payload['window_id']}"
                    )
                payloads.extend(
                    self._fit_payload(
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
            self._fit_payload(
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

        high_level_text = [
            *abstract_items,
            *conclusion_items,
            *overview_items,
        ]
        visual_items = [*table_items, *figure_items]
        if (
            high_level_text or visual_items
        ) and len(high_level_text) + len(visual_items) <= _PAPER_MAP_INITIAL_SOURCE_LIMIT:
            selected_ids = {id(item) for item in (*high_level_text, *visual_items)}
            return [
                cls._compact_paper_map_item_metadata(item)
                for item in items
                if id(item) in selected_ids
            ]

        visual_capacity = min(_PAPER_MAP_VISUAL_SOURCE_LIMIT, len(visual_items))
        text_capacity = _PAPER_MAP_INITIAL_SOURCE_LIMIT - visual_capacity
        selected_text = cls._select_balanced_items(
            (abstract_items, conclusion_items, overview_items),
            text_capacity,
        )
        if not abstract_items and not conclusion_items and not overview_items:
            edge_count = _PAPER_MAP_FALLBACK_SOURCE_LIMIT_PER_EDGE
            selected_text.extend(fallback_items[:edge_count])
            selected_text.extend(fallback_items[-edge_count:])

        selected_visuals = cls._select_balanced_items(
            (table_items, figure_items),
            min(
                visual_capacity,
                max(_PAPER_MAP_INITIAL_SOURCE_LIMIT - len(selected_text), 0),
            ),
        )
        selected = [
            *selected_text,
            *selected_visuals,
        ]

        selected_ids = {id(item) for item in selected}
        return [
            cls._compact_paper_map_item_metadata(item)
            for item in items
            if id(item) in selected_ids
        ][:_PAPER_MAP_INITIAL_SOURCE_LIMIT]

    @staticmethod
    def _select_balanced_items(
        groups: tuple[list[_PaperMapSourceItem], ...],
        limit: int,
    ) -> list[_PaperMapSourceItem]:
        selected: list[_PaperMapSourceItem] = []
        position = 0
        while len(selected) < limit:
            added = False
            for group in groups:
                if position < len(group):
                    selected.append(group[position])
                    added = True
                    if len(selected) == limit:
                        break
            if not added:
                break
            position += 1
        return selected

    @classmethod
    def _select_paper_map_expansion_items(
        cls,
        items: list[_PaperMapSourceItem],
        *,
        focus: str,
        search_terms: tuple[str, ...] = (),
        limit: int = _PAPER_MAP_EXPANSION_SOURCE_LIMIT,
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
        if search_terms:
            selected.sort(
                key=lambda item: (
                    -cls._paper_map_search_score(item, search_terms),
                    item.order,
                )
            )
        return [
            cls._compact_paper_map_item_metadata(item)
            for item in selected[:limit]
        ]

    @staticmethod
    def _paper_map_search_score(
        item: _PaperMapSourceItem,
        search_terms: tuple[str, ...],
    ) -> int:
        content = (
            json.dumps(item.content, ensure_ascii=False)
            if isinstance(item.content, Mapping)
            else str(item.content or "")
        )
        return sum(
            1
            for term in search_terms
            if property_matching.source_text_mentions_axis(content, term)
        )

    @staticmethod
    def expansion_search_terms(
        paper_map: PaperResearchMap,
        signals: Iterable[PaperMapSignalInput],
    ) -> tuple[str, ...]:
        terms: list[str] = []
        seen: set[str] = set()
        visible_signals = (
            *(item.signal for item in signals),
            *paper_map.unresolved_signals,
        )
        for signal in visible_signals:
            if signal.signal_type != "outcome":
                continue
            normalized = property_matching.normalize_property_label(signal.label)
            candidates = (
                signal.label,
                normalized,
                *property_matching.broad_outcome_expansions(normalized),
            )
            for candidate in candidates:
                term = " ".join(str(candidate or "").strip().split())
                key = term.casefold()
                if term and key not in seen:
                    seen.add(key)
                    terms.append(term)
        return tuple(terms)

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
                return PaperMapSourceSelector._split_table_row_source_item(item)
            return PaperMapSourceSelector._split_structured_source_item(item)
        if not isinstance(item.content, str):
            raise ValueError(
                "paper map Source item cannot fit in a bounded window"
            )
        text = str(item.content)
        chunks: list[str] = []
        start = 0
        while len(text) - start > _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT:
            hard_end = start + _PAPER_MAP_SOURCE_FRAGMENT_CHAR_LIMIT
            split_at = PaperMapSourceSelector.natural_text_split(text, start, hard_end)
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
                end = PaperMapSourceSelector.natural_text_split(row_text, start, end)
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
        for path, value in PaperMapSourceSelector.structured_source_leaves(item.content):
            if isinstance(value, str):
                chunks.extend(
                    PaperMapSourceSelector._split_structured_text_value(
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
    def structured_source_leaves(
        value: Any,
        path: tuple[str | int, ...] = (),
    ) -> tuple[tuple[tuple[str | int, ...], Any], ...]:
        if isinstance(value, Mapping):
            if not value:
                return ((path, {}),)
            return tuple(
                leaf
                for key, child in value.items()
                for leaf in PaperMapSourceSelector.structured_source_leaves(
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
                for leaf in PaperMapSourceSelector.structured_source_leaves(
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
                end = PaperMapSourceSelector.natural_text_split(value, start, end)
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
    def natural_text_split(text: str, start: int, hard_end: int) -> int:
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
                    "profile_warnings": list(profile.profile_warnings)[:2],
                    "confidence": profile.confidence,
                }
                if profile
                else {}
            ),
            "source_units": source_units,
        }

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

__all__ = ["PaperMapSourceSelector"]
