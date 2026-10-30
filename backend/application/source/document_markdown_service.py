from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from application.source import collection_service
from domain.source import (
    SourceDocument,
    SourceDocumentNode,
    SourceDocumentTree,
    SourceFigure,
    SourceTable,
    render_markdown_table,
)
from exceptions import ResourceConflictException, ResourceNotFoundException
from infra.source.mapping.text_quality import (
    is_garbled_pdf_text,
    normalize_display_text,
)


class DocumentMarkdownNotReadyError(ResourceConflictException):
    """Raised when Source artifacts are not ready for Markdown projection."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(
            "The collection does not have parsed Markdown yet. Finish preparation first.",
            data={
                "code": "document_markdown_not_ready",
                "collection_id": collection_id,
            },
        )


class SourceDocumentNotFoundError(ResourceNotFoundException):
    """Raised when a Source document cannot be found in a collection."""

    def __init__(self, collection_id: str, document_id: str) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        super().__init__(
            "Document not found in this collection.",
            data={
                "code": "document_not_found",
                "collection_id": collection_id,
                "document_id": document_id,
            },
        )


class SourceFigureImageNotFoundError(ResourceNotFoundException):
    """Raised when a Source figure image cannot be found for a document."""

    def __init__(self, collection_id: str, document_id: str, figure_id: str) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        self.figure_id = figure_id
        super().__init__(
            "Figure image not found in this document.",
            data={
                "code": "figure_not_found",
                "collection_id": collection_id,
                "document_id": document_id,
                "figure_id": figure_id,
            },
        )


class SourceFigureImageUnavailableError(ResourceConflictException):
    """Raised when a figure exists but its extracted image cannot be served."""

    def __init__(
        self,
        collection_id: str,
        document_id: str,
        figure_id: str,
        *,
        code: str = "figure_image_unavailable",
        message: str = "The extracted figure image is not available for this document.",
    ) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        self.figure_id = figure_id
        super().__init__(
            message,
            data={
                "code": code,
                "collection_id": collection_id,
                "document_id": document_id,
                "figure_id": figure_id,
            },
        )


from repositories.source_artifact_repository import SourceArtifactRepo


async def get_document_markdown(
    collection_id: str,
    document_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    collection = await collection_service.get_collection_for_user(
        collection_id, user_id
    )
    documents = await _load_source_documents(collection_id)
    document = _find_document(documents, collection_id, document_id)
    document_tree = await SourceArtifactRepo.read_document_tree(
        collection_id,
        document_id,
    )
    display_names = _document_display_names(collection, document)

    markdown, source_map, warnings = await _project_markdown_from_tree(
        collection_id=collection_id,
        document=document,
        document_tree=document_tree,
        tables_by_id={table.table_id: table for table in document.tables},
        figures_by_id={figure.figure_id: figure for figure in document.figures},
        display_title=display_names["title"],
    )

    if not markdown.strip():
        warnings.append("markdown_content_empty")

    return {
        "collection_id": collection_id,
        "document_id": document.document_id,
        "title": display_names["title"],
        "source_filename": display_names["source_filename"],
        "parser": _parser_name(document),
        "markdown": markdown,
        "source_map": source_map,
        "warnings": warnings,
    }


async def resolve_figure_image_file(
    collection_id: str,
    document_id: str,
    figure_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    document_key = str(document_id or "").strip()
    figure_key = str(figure_id or "").strip()
    if not document_key or not figure_key:
        raise SourceFigureImageNotFoundError(
            collection_id,
            document_key,
            figure_key,
        )

    figure = next(
        (
            item
            for item in await SourceArtifactRepo.list_figures(
                collection_id,
                document_key,
            )
            if item.figure_id == figure_key
        ),
        None,
    )
    if figure is None:
        raise SourceFigureImageNotFoundError(collection_id, document_key, figure_key)
    return _figure_image_payload(collection_id, document_key, figure)


def _figure_image_payload(
    collection_id: str,
    document_key: str,
    figure: SourceFigure,
) -> dict[str, Any]:
    figure_key = figure.figure_id
    image_path = normalize_display_text(figure.image_path)
    if not image_path:
        raise SourceFigureImageUnavailableError(collection_id, document_key, figure_key)

    try:
        content = collection_service.read_figure_asset(
            collection_id,
            image_path,
            normalize_display_text(figure.asset_sha256),
        )
    except ValueError as exc:
        raise SourceFigureImageUnavailableError(
            collection_id,
            document_key,
            figure_key,
            code="figure_image_path_invalid",
            message="The extracted figure image path is invalid.",
        ) from exc
    except (FileNotFoundError, OSError) as exc:
        raise SourceFigureImageUnavailableError(
            collection_id,
            document_key,
            figure_key,
        ) from exc
    if figure.image_size_bytes is not None and len(content) != figure.image_size_bytes:
        raise SourceFigureImageUnavailableError(collection_id, document_key, figure_key)
    media_type = (
        normalize_display_text(figure.image_mime_type) or "application/octet-stream"
    )
    image_suffix = Path(image_path).suffix.lower()
    return {
        "content": content,
        "filename": f"{figure_key}{image_suffix}",
        "media_type": media_type,
    }


async def _load_source_documents(collection_id: str) -> tuple[SourceDocument, ...]:
    documents = await SourceArtifactRepo.read_collection_documents(collection_id)
    if not documents:
        raise DocumentMarkdownNotReadyError(collection_id)
    return documents


def _find_document(
    documents: tuple[SourceDocument, ...],
    collection_id: str,
    document_id: str,
) -> SourceDocument:
    for document in documents:
        if str(document.document_id) == str(document_id):
            return document
    raise SourceDocumentNotFoundError(collection_id, document_id)


async def _project_markdown_from_tree(
    *,
    collection_id: str,
    document: SourceDocument,
    document_tree: SourceDocumentTree,
    tables_by_id: Mapping[str, SourceTable],
    figures_by_id: Mapping[str, SourceFigure],
    display_title: str | None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    parts: list[str] = []
    source_map: list[dict[str, Any]] = []
    warnings: list[str] = []

    title = normalize_display_text(display_title)
    if title:
        parts.append(f"# {title}")
        source_map.append(
            _source_map_entry(
                markdown_anchor=_anchor("document", document.document_id),
                artifact_type="document",
                artifact_id=document.document_id,
                page=None,
                heading_path=None,
            )
        )

    content_rendered = False
    for child_id in document_tree.root.child_ids:
        content_rendered = (
            await _append_tree_node_markdown(
                node=document_tree.nodes[child_id],
                document_tree=document_tree,
                parts=parts,
                source_map=source_map,
                warnings=warnings,
                tables_by_id=tables_by_id,
                figures_by_id=figures_by_id,
                collection_id=collection_id,
                document_id=document.document_id,
                has_document_title=bool(title),
            )
            or content_rendered
        )

    if not content_rendered and normalize_display_text(document.text):
        warnings.append("block_structure_missing")
        parts.extend(_split_document_text(document.text))

    return "\n\n".join(parts).strip(), source_map, warnings


async def _append_tree_node_markdown(
    *,
    node: SourceDocumentNode,
    document_tree: SourceDocumentTree,
    parts: list[str],
    source_map: list[dict[str, Any]],
    warnings: list[str],
    tables_by_id: Mapping[str, SourceTable],
    figures_by_id: Mapping[str, SourceFigure],
    collection_id: str,
    document_id: str,
    has_document_title: bool,
) -> bool:
    node_type = str(node.node_type or "").strip()
    if node_type in {"section", "references_section"}:
        rendered = _render_section_node(node, has_document_title)
        if rendered:
            parts.append(rendered)
            _append_node_source_map(source_map, node, block_type="heading")
        rendered_child = False
        for child_id in node.child_ids:
            rendered_child = (
                await _append_tree_node_markdown(
                    node=document_tree.nodes[child_id],
                    document_tree=document_tree,
                    parts=parts,
                    source_map=source_map,
                    warnings=warnings,
                    tables_by_id=tables_by_id,
                    figures_by_id=figures_by_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    has_document_title=has_document_title,
                )
                or rendered_child
            )
        return bool(rendered) or rendered_child

    if node_type in {"paragraph", "list_item"}:
        text = normalize_display_text(node.text)
        if not text:
            return False
        if is_garbled_pdf_text(text):
            _append_warning(warnings, "garbled_text_blocks_skipped")
            return False
        parts.append(f"- {text}" if node_type == "list_item" else text)
        _append_node_source_map(source_map, node, block_type=node_type)
        return True

    if node_type == "table":
        table = tables_by_id.get(str(node.source_ref_id or ""))
        if table is None:
            return False
        caption = normalize_display_text(table.caption_text)
        if caption:
            parts.append(f"**Table.** {caption}")
        table_markdown = _render_table(table)
        if table_markdown:
            parts.append(table_markdown)
        if caption or table_markdown:
            source_map.append(_table_source_map_entry(table))
            return True
        return False

    if node_type == "figure":
        figure = figures_by_id.get(str(node.source_ref_id or ""))
        if figure is None:
            return False
        figure_markdown = await _render_figure(
            figure,
            collection_id=collection_id,
            document_id=document_id,
        )
        if not figure_markdown:
            return False
        parts.append(figure_markdown)
        source_map.append(_figure_source_map_entry(figure))
        return True

    if node_type == "reference_entry":
        text = normalize_display_text(node.text)
        if not text:
            return False
        parts.append(text)
        _append_node_source_map(source_map, node)
        return True

    if node_type == "caption":
        return False

    return False


def _append_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _render_section_node(
    node: SourceDocumentNode,
    has_document_title: bool,
) -> str | None:
    title = normalize_display_text(node.title)
    if not title:
        return None
    level = _markdown_heading_level(node.level, has_document_title)
    return f"{'#' * level} {title}"


def _append_node_source_map(
    source_map: list[dict[str, Any]],
    node: SourceDocumentNode,
    *,
    block_type: str | None = None,
) -> None:
    source_ref_kind = str(node.source_ref_kind or node.node_type or "").strip()
    source_ref_id = str(node.source_ref_id or node.node_id).strip()
    if not source_ref_id:
        return
    artifact_type = source_ref_kind or str(node.node_type)
    source_map.append(
        _source_map_entry(
            markdown_anchor=_anchor(artifact_type, source_ref_id),
            artifact_type=artifact_type,
            artifact_id=source_ref_id,
            block_id=source_ref_id if artifact_type == "block" else None,
            block_type=block_type,
            page=node.page_start,
            heading_path=_heading_path_text(node.heading_path),
            text_unit_ids=list(node.text_unit_ids),
        )
    )


def _render_table(table: SourceTable) -> str | None:
    return render_markdown_table(
        [list(row) for row in table.table_matrix],
        list(table.column_headers),
        header_row_count=table.header_row_count,
    )


async def _render_figure(
    figure: SourceFigure,
    *,
    collection_id: str,
    document_id: str,
) -> str | None:
    caption = normalize_display_text(figure.caption_text)
    label = normalize_display_text(figure.figure_label)
    image_markdown = None
    if _figure_image_available(
        collection_id=collection_id,
        document_id=document_id,
        figure=figure,
    ):
        alt_text = label or caption or "Figure"
        image_markdown = (
            f"![{_escape_markdown_image_alt(alt_text)}]"
            f"({_figure_image_url(collection_id, document_id, figure.figure_id)})"
        )
    caption_markdown = None
    if caption and label and not caption.casefold().startswith(label.casefold()):
        caption_markdown = f"**{label}.** {caption}"
    elif caption:
        caption_markdown = f"**Figure.** {caption}"
    elif label:
        caption_markdown = f"**{label}.**"
    return (
        "\n\n".join(part for part in (image_markdown, caption_markdown) if part) or None
    )


def _figure_image_available(
    *,
    collection_id: str,
    document_id: str,
    figure: SourceFigure,
) -> bool:
    try:
        _figure_image_payload(collection_id, document_id, figure)
    except SourceFigureImageUnavailableError:
        return False
    return True


def _figure_image_url(
    collection_id: str,
    document_id: str,
    figure_id: str,
) -> str:
    encoded_collection_id = quote(collection_id, safe="")
    encoded_document_id = quote(document_id, safe="")
    encoded_figure_id = quote(figure_id, safe="")
    return (
        "/api/v1/collections/"
        f"{encoded_collection_id}/documents/{encoded_document_id}/figures/"
        f"{encoded_figure_id}/image"
    )


def _escape_markdown_image_alt(value: str) -> str:
    return value.replace("\\", "\\\\").replace("]", "\\]")


def _markdown_heading_level(
    source_level: int | None,
    has_document_title: bool,
) -> int:
    level = int(source_level or 1)
    if has_document_title:
        level += 1
    return max(1, min(level, 6))


def _split_document_text(text: str) -> list[str]:
    return [
        " ".join(chunk.split())
        for chunk in re.split(r"\n\s*\n", text)
        if normalize_display_text(chunk)
    ]


def _table_source_map_entry(table: SourceTable) -> dict[str, Any]:
    return _source_map_entry(
        markdown_anchor=_anchor("table", table.table_id),
        artifact_type="table",
        artifact_id=table.table_id,
        table_id=table.table_id,
        page=table.page,
        heading_path=table.heading_path,
    )


def _figure_source_map_entry(figure: SourceFigure) -> dict[str, Any]:
    return _source_map_entry(
        markdown_anchor=_anchor("figure", figure.figure_id),
        artifact_type="figure",
        artifact_id=figure.figure_id,
        figure_id=figure.figure_id,
        page=figure.page,
        heading_path=figure.heading_path,
    )


def _source_map_entry(
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


def _source_filename(document: SourceDocument) -> str | None:
    for key in (
        "source_filename",
        "original_filename",
        "stored_filename",
        "source_path",
    ):
        value = _metadata_text(document.metadata, key)
        if value:
            return Path(value).name
    return None


def _document_display_names(
    collection: dict[str, Any],
    document: SourceDocument,
) -> dict[str, str | None]:
    stored_to_original = _stored_to_original_filenames(collection)
    source_filename = _source_filename(document)
    display_source_filename = (
        stored_to_original.get(source_filename, source_filename)
        if source_filename
        else None
    )
    title = normalize_display_text(document.title)
    display_title = (
        stored_to_original.get(title, title) if title else display_source_filename
    )
    if display_source_filename and display_title == display_source_filename:
        display_title = display_source_filename
    return {
        "title": display_title,
        "source_filename": display_source_filename,
    }


def _stored_to_original_filenames(collection: dict[str, Any]) -> dict[str, str]:
    filenames: dict[str, str] = {}
    for record in collection["documents"]:
        original = normalize_display_text(record.get("original_filename"))
        stored = normalize_display_text(record.get("stored_filename"))
        if original and stored:
            filenames[Path(stored).name] = Path(original).name
    return filenames


def _heading_path_text(heading_path: tuple[str, ...]) -> str | None:
    text = " > ".join(part.strip() for part in heading_path if part.strip())
    return text or None


def _parser_name(document: SourceDocument) -> str | None:
    for key in ("source_parser", "parser", "parser_name"):
        value = _metadata_text(document.metadata, key)
        if value:
            return value
    return None


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    return normalize_display_text(metadata.get(key))


def _anchor(prefix: str, value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip()).strip("-")
    return f"{prefix}-{slug or 'item'}"
