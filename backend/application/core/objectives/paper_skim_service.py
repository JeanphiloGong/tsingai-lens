from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from application.core.objectives.extraction import ObjectiveExtractor
from domain.core import PaperSkim
from domain.source import SourceArtifactSet, SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_SKIM_TEXT_PREVIEW_CHARS = 4000
_SKIM_HEADING_LIMIT = 16


class PaperSkimService:
    """Build one bounded research map for every document in a collection build."""

    def build_collection_paper_skims(
        self,
        collection_id: str,
        *,
        artifacts: SourceArtifactSet,
        profiles_by_document_id: Mapping[str, Any],
        document_trees_by_document_id: Mapping[
            str,
            SourceDocumentTree | None,
        ],
        extractor: ObjectiveExtractor,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[PaperSkim, ...]:
        blocks_by_document_id = self._group_by_document_id(artifacts.blocks)
        tables_by_document_id = self._group_by_document_id(artifacts.tables)
        figures_by_document_id = self._group_by_document_id(artifacts.figures)

        logger.info(
            "Research objective paper skim started collection_id=%s document_count=%s",
            collection_id,
            len(artifacts.documents),
        )
        paper_skims: list[PaperSkim] = []
        document_count = len(artifacts.documents)
        for document_position, document in enumerate(artifacts.documents, start=1):
            source_filename = self._resolve_source_filename(document)
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
            )
            document_blocks = blocks_by_document_id.get(document.document_id, [])
            document_tables = tables_by_document_id.get(document.document_id, [])
            document_figures = figures_by_document_id.get(document.document_id, [])
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
            payload = self._build_paper_skim_payload(
                collection_id=collection_id,
                document=document,
                profile=profiles_by_document_id.get(document.document_id),
                blocks=document_blocks,
                tables=document_tables,
                figures=document_figures,
                document_tree=document_trees_by_document_id.get(document.document_id),
            )
            parsed = extractor.extract_paper_skim(payload)
            paper_skim = PaperSkim.from_mapping(
                {
                    **parsed.model_dump(),
                    "document_id": document.document_id,
                    "title": document.title,
                    "source_filename": source_filename,
                }
            )
            paper_skims.append(paper_skim)
            logger.info(
                "Research objective paper skim document finished collection_id=%s document_id=%s document_position=%s document_count=%s doc_role=%s candidate_materials=%s candidate_processes=%s candidate_properties=%s possible_objectives=%s completed_documents=%s remaining_documents=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                paper_skim.doc_role,
                len(paper_skim.candidate_materials),
                len(paper_skim.candidate_processes),
                len(paper_skim.candidate_properties),
                len(paper_skim.possible_objectives),
                document_position,
                max(document_count - document_position, 0),
            )
        return tuple(paper_skims)

    def _build_paper_skim_payload(
        self,
        *,
        collection_id: str,
        document: Any,
        profile: Any,
        blocks: list[Any],
        tables: list[Any],
        figures: list[Any],
        document_tree: SourceDocumentTree | None = None,
    ) -> dict[str, Any]:
        ordered_blocks = sorted(
            blocks,
            key=lambda item: int(getattr(item, "block_order", 0) or 0),
        )
        headings = self._extract_headings_from_tree(document_tree)
        if not headings:
            headings = self._extract_headings(ordered_blocks)
        text_preview = self._build_text_preview_from_tree(document_tree)
        if not text_preview:
            text_preview = self._build_text_preview(document, ordered_blocks)
        return {
            "collection_id": collection_id,
            "document_id": document.document_id,
            "title": str(document.title or "")[:160],
            "document_profile": (
                {
                    "doc_type": profile.doc_type,
                    "parsing_warnings": list(profile.parsing_warnings)[:2],
                    "confidence": profile.confidence,
                }
                if profile
                else {}
            ),
            "text_preview": text_preview[:_SKIM_TEXT_PREVIEW_CHARS],
            "headings": headings[:4],
            "table_captions": [
                {
                    "table_id": table.table_id,
                    "caption_text": str(table.caption_text or "")[:160],
                    "heading_path": str(table.heading_path or "")[:120],
                    "column_headers": [
                        str(value)[:80] for value in table.column_headers[:4]
                    ],
                }
                for table in sorted(tables, key=lambda item: item.table_order)[:2]
            ],
            "figure_captions": [
                {
                    "figure_id": figure.figure_id,
                    "caption_text": str(figure.caption_text or "")[:160],
                    "heading_path": str(figure.heading_path or "")[:120],
                }
                for figure in sorted(figures, key=lambda item: item.figure_order)[:2]
            ],
        }

    @staticmethod
    def _extract_headings(blocks: list[Any]) -> list[str]:
        headings: list[str] = []
        seen: set[str] = set()
        for block in blocks:
            heading = ""
            if getattr(block, "block_type", "") == "heading":
                heading = str(getattr(block, "text", "") or "").strip()
            if not heading:
                heading = str(getattr(block, "heading_path", "") or "").strip()
            if not heading:
                continue
            key = heading.lower()
            if key in seen:
                continue
            seen.add(key)
            headings.append(heading)
            if len(headings) >= _SKIM_HEADING_LIMIT:
                break
        return headings

    def _extract_headings_from_tree(
        self,
        document_tree: SourceDocumentTree | None,
    ) -> list[str]:
        if document_tree is None:
            return []
        headings: list[str] = []
        seen: set[str] = set()
        for node in self._document_tree_nodes_in_order(document_tree):
            if node.node_type not in {"section", "references_section"}:
                continue
            heading = self._tree_section_label(node)
            if not heading:
                continue
            key = heading.lower()
            if key in seen:
                continue
            seen.add(key)
            headings.append(heading)
            if len(headings) >= _SKIM_HEADING_LIMIT:
                break
        return headings

    @staticmethod
    def _build_text_preview(document: Any, blocks: list[Any]) -> str:
        parts = [
            str(getattr(block, "text", "") or "").strip()
            for block in blocks
            if str(getattr(block, "text", "") or "").strip()
            and getattr(block, "block_type", "") in {"paragraph", "list_item"}
        ]
        text = "\n\n".join(parts).strip()
        if not text:
            text = str(document.text or "").strip()
        return text[:_SKIM_TEXT_PREVIEW_CHARS]

    def _build_text_preview_from_tree(
        self,
        document_tree: SourceDocumentTree | None,
    ) -> str:
        if document_tree is None:
            return ""
        parts = [
            str(node.text or "").strip()
            for node in self._document_tree_nodes_in_order(document_tree)
            if node.node_type in {"paragraph", "list_item"}
            and not self._tree_node_in_reference_branch(document_tree, node)
            and str(node.text or "").strip()
        ]
        return "\n\n".join(parts).strip()[:_SKIM_TEXT_PREVIEW_CHARS]

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
    def _group_by_document_id(values: tuple[Any, ...]) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = {}
        for value in values:
            document_id = str(getattr(value, "document_id", "") or "")
            if document_id:
                grouped.setdefault(document_id, []).append(value)
        return grouped

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
