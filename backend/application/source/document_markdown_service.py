from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from application.source.collection_service import CollectionService
from domain.ports import SourceArtifactRepository
from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceTable,
    render_markdown_table,
)
from infra.persistence.factory import build_source_artifact_repository


class DocumentMarkdownNotReadyError(RuntimeError):
    """Raised when Source artifacts are not ready for Markdown projection."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"document markdown not ready: {collection_id}")


class SourceDocumentNotFoundError(FileNotFoundError):
    """Raised when a Source document cannot be found in a collection."""

    def __init__(self, collection_id: str, document_id: str) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        super().__init__(f"document not found: {collection_id}/{document_id}")


class DocumentMarkdownService:
    """Build display-only Markdown projections from Source document artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        source_artifact_repository: SourceArtifactRepository | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.source_artifact_repository = (
            source_artifact_repository
            or build_source_artifact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )

    def get_document_markdown(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        artifacts = self._load_source_artifacts(collection_id)
        document = self._find_document(artifacts, collection_id, document_id)
        blocks = self._document_blocks(artifacts, document_id)
        tables = self._document_tables(artifacts, document_id)
        figures = self._document_figures(artifacts, document_id)

        markdown, source_map, warnings = self._project_markdown(
            document=document,
            blocks=blocks,
            tables=tables,
            figures=figures,
        )

        if not markdown.strip():
            warnings.append("markdown_content_empty")

        return {
            "collection_id": collection_id,
            "document_id": document.document_id,
            "title": self._normalize_text(document.title),
            "source_filename": self._source_filename(document),
            "parser": self._parser_name(document),
            "markdown": markdown,
            "source_map": source_map,
            "warnings": warnings,
        }

    def _load_source_artifacts(self, collection_id: str) -> SourceArtifactSet:
        artifacts = self.source_artifact_repository.read_collection_artifacts(
            collection_id
        )
        if not artifacts.documents:
            raise DocumentMarkdownNotReadyError(collection_id)
        return artifacts

    def _find_document(
        self,
        artifacts: SourceArtifactSet,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument:
        for document in artifacts.documents:
            if str(document.document_id) == str(document_id):
                return document
        raise SourceDocumentNotFoundError(collection_id, document_id)

    def _document_blocks(
        self,
        artifacts: SourceArtifactSet,
        document_id: str,
    ) -> list[SourceBlock]:
        return sorted(
            [
                block
                for block in artifacts.blocks
                if str(block.document_id) == str(document_id)
                and self._normalize_text(block.text)
            ],
            key=lambda block: block.block_order,
        )

    def _document_tables(
        self,
        artifacts: SourceArtifactSet,
        document_id: str,
    ) -> list[SourceTable]:
        return sorted(
            [
                table
                for table in artifacts.tables
                if str(table.document_id) == str(document_id)
            ],
            key=lambda table: table.table_order,
        )

    def _document_figures(
        self,
        artifacts: SourceArtifactSet,
        document_id: str,
    ) -> list[SourceFigure]:
        return sorted(
            [
                figure
                for figure in artifacts.figures
                if str(figure.document_id) == str(document_id)
            ],
            key=lambda figure: figure.figure_order,
        )

    def _project_markdown(
        self,
        *,
        document: SourceDocument,
        blocks: list[SourceBlock],
        tables: list[SourceTable],
        figures: list[SourceFigure],
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        parts: list[str] = []
        source_map: list[dict[str, Any]] = []
        warnings: list[str] = []
        used_tables: set[str] = set()
        used_figures: set[str] = set()

        title = self._normalize_text(document.title)
        if title:
            parts.append(f"# {title}")
            source_map.append(
                self._source_map_entry(
                    markdown_anchor=self._anchor("document", document.document_id),
                    artifact_type="document",
                    artifact_id=document.document_id,
                    page=None,
                    heading_path=None,
                )
            )

        tables_by_caption = self._group_tables_by_caption_block(tables)
        figures_by_caption = self._group_figures_by_caption_block(figures)

        for block in blocks:
            text = self._normalize_text(block.text)
            if not text:
                continue
            block_type = str(block.block_type or "paragraph").strip() or "paragraph"
            if block_type == "title" and title and text.casefold() == title.casefold():
                continue

            rendered = self._render_block(block, text, has_document_title=bool(title))
            if rendered:
                parts.append(rendered)
                source_map.append(
                    self._source_map_entry(
                        markdown_anchor=self._anchor("block", block.block_id),
                        artifact_type="block",
                        artifact_id=block.block_id,
                        block_id=block.block_id,
                        block_type=block_type,
                        page=block.page,
                        heading_path=block.heading_path,
                        text_unit_ids=list(block.text_unit_ids),
                    )
                )

            for table in tables_by_caption.get(block.block_id, []):
                table_markdown = self._render_table(table)
                if table_markdown:
                    parts.append(table_markdown)
                    used_tables.add(table.table_id)
                    source_map.append(self._table_source_map_entry(table))

            for figure in figures_by_caption.get(block.block_id, []):
                figure_markdown = self._render_figure(figure)
                if figure_markdown:
                    parts.append(figure_markdown)
                    used_figures.add(figure.figure_id)
                    source_map.append(self._figure_source_map_entry(figure))

        if not blocks and self._normalize_text(document.text):
            warnings.append("block_structure_missing")
            parts.extend(self._split_document_text(document.text))

        unplaced_tables = [table for table in tables if table.table_id not in used_tables]
        if unplaced_tables:
            parts.append("## Tables")
            for table in unplaced_tables:
                if table.caption_text:
                    parts.append(f"**Table.** {table.caption_text}")
                table_markdown = self._render_table(table)
                if table_markdown:
                    parts.append(table_markdown)
                    source_map.append(self._table_source_map_entry(table))

        unplaced_figures = [
            figure for figure in figures if figure.figure_id not in used_figures
        ]
        if unplaced_figures:
            parts.append("## Figures")
            for figure in unplaced_figures:
                figure_markdown = self._render_figure(figure)
                if figure_markdown:
                    parts.append(figure_markdown)
                    source_map.append(self._figure_source_map_entry(figure))

        return "\n\n".join(parts).strip(), source_map, warnings

    def _render_block(
        self,
        block: SourceBlock,
        text: str,
        *,
        has_document_title: bool,
    ) -> str:
        block_type = str(block.block_type or "paragraph").strip()
        if block_type == "title":
            return f"# {text}" if not has_document_title else f"## {text}"
        if block_type == "heading":
            level = self._markdown_heading_level(block.heading_level, has_document_title)
            return f"{'#' * level} {text}"
        if block_type == "list_item":
            return f"- {text}"
        if block_type == "figure_caption":
            return f"**Figure.** {text}"
        if block_type == "table_caption":
            return f"**Table.** {text}"
        return text

    def _render_table(self, table: SourceTable) -> str | None:
        return render_markdown_table(
            [list(row) for row in table.table_matrix],
            list(table.column_headers),
        )

    def _render_figure(self, figure: SourceFigure) -> str | None:
        caption = self._normalize_text(figure.caption_text)
        label = self._normalize_text(figure.figure_label)
        if caption and label and not caption.casefold().startswith(label.casefold()):
            return f"**{label}.** {caption}"
        if caption:
            return f"**Figure.** {caption}"
        if label:
            return f"**{label}.**"
        return None

    def _markdown_heading_level(
        self,
        source_level: int | None,
        has_document_title: bool,
    ) -> int:
        level = int(source_level or 1)
        if has_document_title:
            level += 1
        return max(1, min(level, 6))

    def _group_tables_by_caption_block(
        self,
        tables: Iterable[SourceTable],
    ) -> dict[str, list[SourceTable]]:
        grouped: dict[str, list[SourceTable]] = {}
        for table in tables:
            if not table.caption_block_id:
                continue
            grouped.setdefault(table.caption_block_id, []).append(table)
        return grouped

    def _group_figures_by_caption_block(
        self,
        figures: Iterable[SourceFigure],
    ) -> dict[str, list[SourceFigure]]:
        grouped: dict[str, list[SourceFigure]] = {}
        for figure in figures:
            if not figure.caption_block_id:
                continue
            grouped.setdefault(figure.caption_block_id, []).append(figure)
        return grouped

    def _split_document_text(self, text: str) -> list[str]:
        return [
            " ".join(chunk.split())
            for chunk in re.split(r"\n\s*\n", text)
            if self._normalize_text(chunk)
        ]

    def _table_source_map_entry(self, table: SourceTable) -> dict[str, Any]:
        return self._source_map_entry(
            markdown_anchor=self._anchor("table", table.table_id),
            artifact_type="table",
            artifact_id=table.table_id,
            table_id=table.table_id,
            page=table.page,
            heading_path=table.heading_path,
        )

    def _figure_source_map_entry(self, figure: SourceFigure) -> dict[str, Any]:
        return self._source_map_entry(
            markdown_anchor=self._anchor("figure", figure.figure_id),
            artifact_type="figure",
            artifact_id=figure.figure_id,
            figure_id=figure.figure_id,
            page=figure.page,
            heading_path=figure.heading_path,
        )

    def _source_map_entry(
        self,
        *,
        markdown_anchor: str,
        artifact_type: str,
        artifact_id: str,
        block_id: str | None = None,
        table_id: str | None = None,
        figure_id: str | None = None,
        block_type: str | None = None,
        page: int | None,
        heading_path: str | None,
        text_unit_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "markdown_anchor": markdown_anchor,
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "block_id": block_id,
            "table_id": table_id,
            "figure_id": figure_id,
            "block_type": block_type,
            "page": page,
            "heading_path": heading_path,
            "text_unit_ids": text_unit_ids or [],
        }

    def _source_filename(self, document: SourceDocument) -> str | None:
        for key in ("source_filename", "original_filename", "stored_filename"):
            value = self._metadata_text(document.metadata, key)
            if value:
                return value
        return None

    def _parser_name(self, document: SourceDocument) -> str | None:
        for key in ("source_parser", "parser", "parser_name"):
            value = self._metadata_text(document.metadata, key)
            if value:
                return value
        return None

    def _metadata_text(self, metadata: Mapping[str, Any], key: str) -> str | None:
        return self._normalize_text(metadata.get(key))

    def _normalize_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).strip().split())
        return text or None

    def _anchor(self, prefix: str, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip()).strip("-")
        return f"{prefix}-{slug or 'item'}"
