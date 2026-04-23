# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Build the final Source handoff artifacts from raw input documents."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)
from infra.source.runtime.chunking import get_encoding_fn
from infra.source.runtime.hashing import gen_sha512_hash
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_rows,
    extract_unit_hint,
    make_table_id,
)
from infra.source.runtime.storage.table_io import (
    load_table_from_storage,
    write_table_to_storage,
)
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.workflow import WorkflowFunctionOutput
from .create_base_text_units import create_base_text_units
from .create_final_documents import create_final_documents
from .create_final_text_units import create_final_text_units
from .create_table_cells import create_table_cells

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceArtifactBundle:
    documents: pd.DataFrame
    text_units: pd.DataFrame
    blocks: pd.DataFrame
    figures: pd.DataFrame
    table_rows: pd.DataFrame
    table_cells: pd.DataFrame
    figure_assets: dict[str, bytes]


async def run_workflow(
    config: SourceRuntimeConfig,
    context: PipelineRunContext,
) -> WorkflowFunctionOutput:
    """Parse mixed raw inputs into the final Source handoff artifacts."""
    logger.info("Workflow started: create_source_artifacts")
    inventory = await load_table_from_storage("documents", context.output_storage)
    output = await create_source_artifacts(
        inventory=inventory,
        config=config,
        context=context,
    )

    context.stats.num_documents = len(output.documents)
    await write_table_to_storage(output.documents, "documents", context.output_storage)
    await write_table_to_storage(output.text_units, "text_units", context.output_storage)
    await write_table_to_storage(output.blocks, "blocks", context.output_storage)
    await write_table_to_storage(output.figures, "figures", context.output_storage)
    await write_table_to_storage(output.table_rows, "table_rows", context.output_storage)
    await write_table_to_storage(output.table_cells, "table_cells", context.output_storage)
    await _clear_directory_storage(context.output_storage, "image_assets")
    for asset_path, asset_bytes in output.figure_assets.items():
        await context.output_storage.set(asset_path, asset_bytes)
    logger.info("Workflow completed: create_source_artifacts")
    return WorkflowFunctionOutput(result=output.documents)


async def create_source_artifacts(
    *,
    inventory: pd.DataFrame,
    config: SourceRuntimeConfig,
    context: PipelineRunContext,
) -> SourceArtifactBundle:
    """Build all final Source artifacts in one pass over the raw inputs."""
    bundles: list[SourceArtifactBundle] = []
    figure_assets: dict[str, bytes] = {}
    pdf_converter: Any | None = None

    for _, row in inventory.iterrows():
        source_path = str(row.get("source_path") or "").strip()
        suffix = Path(source_path).suffix.lower()
        if source_path and suffix == ".pdf":
            if pdf_converter is None:
                pdf_converter = _build_pdf_converter()
            payload = await context.input_storage.get(source_path, as_bytes=True)
            if payload is None:
                raise FileNotFoundError(f"input document not found: {source_path}")
            bundles.append(
                _build_pdf_bundle(
                    row=row,
                    payload=payload,
                    config=config,
                    converter=pdf_converter,
                )
            )
            continue

        text = row.get("text")
        if text is None and source_path:
            text = await context.input_storage.get(source_path, encoding=config.input.encoding)
        bundles.append(
            _build_text_bundle(
                row=row,
                text=str(text or ""),
                config=config,
                callbacks=context.callbacks,
            )
        )
        figure_assets.update(bundles[-1].figure_assets)

    documents = _concat_frames([bundle.documents for bundle in bundles], DOCUMENTS_FINAL_COLUMNS)
    text_units = _concat_frames([bundle.text_units for bundle in bundles], TEXT_UNITS_FINAL_COLUMNS)
    blocks = _concat_frames([bundle.blocks for bundle in bundles], BLOCKS_FINAL_COLUMNS)
    figures = _concat_frames([bundle.figures for bundle in bundles], FIGURES_FINAL_COLUMNS)
    table_rows = _concat_frames([bundle.table_rows for bundle in bundles], TABLE_ROWS_FINAL_COLUMNS)
    table_cells = _concat_frames(
        [bundle.table_cells for bundle in bundles],
        TABLE_CELLS_FINAL_COLUMNS,
    )

    if not documents.empty:
        documents = documents.copy()
        documents["human_readable_id"] = range(len(documents))
    if not text_units.empty:
        text_units = text_units.copy()
        text_units["human_readable_id"] = range(len(text_units))

    return SourceArtifactBundle(
        documents=documents.loc[:, DOCUMENTS_FINAL_COLUMNS],
        text_units=text_units.loc[:, TEXT_UNITS_FINAL_COLUMNS],
        blocks=blocks.loc[:, BLOCKS_FINAL_COLUMNS],
        figures=figures.loc[:, FIGURES_FINAL_COLUMNS],
        table_rows=table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
        figure_assets=dict(figure_assets),
    )


def _build_text_bundle(
    *,
    row: pd.Series,
    text: str,
    config: SourceRuntimeConfig,
    callbacks: Any,
) -> SourceArtifactBundle:
    document_id = _resolve_document_id(row)
    title = _resolve_document_title(row)
    metadata = _build_source_metadata(row, parser_name="plain_text")
    document_frame = pd.DataFrame(
        [
            {
                "id": document_id,
                "title": title,
                "text": text,
                "creation_date": row.get("creation_date"),
                "metadata": metadata,
            }
        ]
    )

    base_text_units = create_base_text_units(
        document_frame,
        callbacks,
        config.chunks.group_by_columns,
        config.chunks.size,
        config.chunks.overlap,
        config.chunks.encoding_model,
        strategy=config.chunks.strategy,
        prepend_metadata=config.chunks.prepend_metadata,
        chunk_size_includes_metadata=config.chunks.chunk_size_includes_metadata,
    )
    final_documents = create_final_documents(document_frame, base_text_units)
    final_text_units = create_final_text_units(base_text_units)
    final_blocks = build_blocks(final_documents, final_text_units)
    final_table_rows = build_table_rows(final_documents, final_text_units)
    final_table_cells = create_table_cells(final_documents, final_text_units)
    return SourceArtifactBundle(
        documents=final_documents.loc[:, DOCUMENTS_FINAL_COLUMNS],
        text_units=final_text_units.loc[:, TEXT_UNITS_FINAL_COLUMNS],
        blocks=final_blocks.loc[:, BLOCKS_FINAL_COLUMNS],
        figures=pd.DataFrame(columns=FIGURES_FINAL_COLUMNS),
        table_rows=final_table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=final_table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
        figure_assets={},
    )


def _build_pdf_bundle(
    *,
    row: pd.Series,
    payload: bytes,
    config: SourceRuntimeConfig,
    converter: Any,
) -> SourceArtifactBundle:
    document = _convert_pdf_document(
        converter=converter,
        filename=_resolve_document_title(row),
        payload=payload,
    )
    document_id = _resolve_document_id(row)
    title = _resolve_document_title(row)
    text_items = _collect_pdf_text_items(document)
    figure_caption_refs, table_caption_refs = _collect_caption_ref_sets(document)
    text_units = _build_pdf_text_units(document_id, text_items, config)
    final_documents = pd.DataFrame(
        [
            {
                "id": document_id,
                "human_readable_id": 0,
                "title": title,
                "text": str(document.export_to_text() or "").strip(),
                "text_unit_ids": text_units["id"].tolist(),
                "creation_date": row.get("creation_date"),
                "metadata": _build_source_metadata(row, parser_name="docling"),
            }
        ],
        columns=DOCUMENTS_FINAL_COLUMNS,
    )
    final_blocks = _build_pdf_blocks(
        document_id=document_id,
        title=title,
        text_items=text_items,
        figure_caption_refs=figure_caption_refs,
        table_caption_refs=table_caption_refs,
    )
    final_figures, figure_assets = _build_pdf_figures(
        document_id=document_id,
        document=document,
        blocks=final_blocks,
        text_items=text_items,
        payload=payload,
    )
    final_table_cells = _build_pdf_table_cells(
        document_id=document_id,
        document=document,
    )
    final_table_rows = _build_pdf_table_rows(
        document_id=document_id,
        blocks=final_blocks,
        table_cells=final_table_cells,
    )
    return SourceArtifactBundle(
        documents=final_documents.loc[:, DOCUMENTS_FINAL_COLUMNS],
        text_units=text_units.loc[:, TEXT_UNITS_FINAL_COLUMNS],
        blocks=final_blocks.loc[:, BLOCKS_FINAL_COLUMNS],
        figures=final_figures.loc[:, FIGURES_FINAL_COLUMNS],
        table_rows=final_table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=final_table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
        figure_assets=figure_assets,
    )


def _build_pdf_converter() -> Any:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=False)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def _convert_pdf_document(*, converter: Any, filename: str, payload: bytes) -> Any:
    from docling.datamodel.base_models import DocumentStream

    result = converter.convert(
        DocumentStream(
            name=filename,
            stream=BytesIO(payload),
        )
    )
    return result.document


def _collect_pdf_text_items(document: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(getattr(document, "texts", []) or []):
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "index": index,
                "ref": f"#/texts/{index}",
                "text": text,
                "label": str(getattr(item, "label", "") or ""),
                "page": _first_page(getattr(item, "prov", None)),
                "bbox": _serialize_prov_bbox(getattr(item, "prov", None)),
                "char_range": _serialize_char_range(getattr(item, "prov", None)),
            }
        )
    return rows


def _build_pdf_text_units(
    document_id: str,
    text_items: list[dict[str, Any]],
    config: SourceRuntimeConfig,
) -> pd.DataFrame:
    encode, _ = get_encoding_fn(config.chunks.encoding_model)
    rows: list[dict[str, Any]] = []
    for item in text_items:
        text = str(item["text"]).strip()
        row_id = gen_sha512_hash(
            {
                "document_id": document_id,
                "index": int(item["index"]),
                "text": text,
            },
            ["document_id", "index", "text"],
        )
        rows.append(
            {
                "id": row_id,
                "human_readable_id": len(rows),
                "text": text,
                "n_tokens": len(encode(text)),
                "document_ids": [document_id],
            }
        )
        item["text_unit_id"] = row_id
    return pd.DataFrame(rows, columns=TEXT_UNITS_FINAL_COLUMNS)


def _build_pdf_blocks(
    *,
    document_id: str,
    title: str,
    text_items: list[dict[str, Any]],
    figure_caption_refs: set[str],
    table_caption_refs: set[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    heading_stack: list[str] = []
    order = 1
    saw_title = False

    if not any(str(item.get("label") or "").lower() == "title" for item in text_items) and title:
        rows.append(
            {
                "block_id": f"blk_{document_id}_{order}",
                "document_id": document_id,
                "block_type": "title",
                "text": title,
                "block_order": order,
                "text_unit_ids": [],
                "page": None,
                "bbox": None,
                "char_range": None,
                "heading_path": title,
                "heading_level": 0,
            }
        )
        order += 1

    for item in text_items:
        label = str(item["label"] or "").lower()
        if label == "title":
            saw_title = True
        block_type = _map_docling_block_type(
            label,
            item["text"],
            caption_ref=item.get("ref"),
            figure_caption_refs=figure_caption_refs,
            table_caption_refs=table_caption_refs,
        )
        heading_path: str | None = None
        heading_level: int | None = None
        if block_type == "heading":
            heading_level = _infer_heading_level_from_text(item["text"])
            heading_stack = _update_heading_stack(heading_stack, item["text"], heading_level)
            heading_path = " > ".join(heading_stack)
        elif block_type == "title":
            heading_path = item["text"]
        else:
            heading_path = " > ".join(heading_stack) if heading_stack else None
        block_id = f"blk_{document_id}_{order}"
        rows.append(
            {
                "block_id": block_id,
                "document_id": document_id,
                "block_type": block_type,
                "text": item["text"],
                "block_order": order,
                "text_unit_ids": [item["text_unit_id"]] if item.get("text_unit_id") else [],
                "page": item["page"],
                "bbox": item.get("bbox"),
                "char_range": item["char_range"],
                "heading_path": heading_path,
                "heading_level": heading_level,
            }
        )
        item["block_id"] = block_id
        item["heading_path"] = heading_path
        order += 1

    if not saw_title and title and not rows:
        rows.append(
            {
                "block_id": f"blk_{document_id}_{order}",
                "document_id": document_id,
                "block_type": "title",
                "text": title,
                "block_order": order,
                "text_unit_ids": [],
                "page": None,
                "bbox": None,
                "char_range": None,
                "heading_path": title,
                "heading_level": 0,
            }
        )

    return pd.DataFrame(rows, columns=BLOCKS_FINAL_COLUMNS)


def _build_pdf_table_cells(*, document_id: str, document: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for table_index, table in enumerate(getattr(document, "tables", []) or [], start=1):
        table_id = make_table_id(document_id, table_index, None)
        header_paths = _build_docling_header_paths(table)
        table_page = _first_page(getattr(table, "prov", None))

        for cell_index, cell in enumerate(getattr(getattr(table, "data", None), "table_cells", []) or []):
            row_index = int(getattr(cell, "start_row_offset_idx", 0))
            col_index = int(getattr(cell, "start_col_offset_idx", 0))
            cell_text = str(getattr(cell, "text", "") or "").strip()
            header_path = None
            if not bool(getattr(cell, "column_header", False)) and not bool(getattr(cell, "row_header", False)):
                header_path = header_paths.get(col_index)
            rows.append(
                {
                    "cell_id": gen_sha512_hash(
                        {
                            "document_id": document_id,
                            "table_id": table_id,
                            "cell_index": cell_index,
                            "row_index": row_index,
                            "col_index": col_index,
                            "text": cell_text,
                        },
                        ["document_id", "table_id", "cell_index", "row_index", "col_index", "text"],
                    ),
                    "id": document_id,
                    "table_id": table_id,
                    "row_index": row_index,
                    "col_index": col_index,
                    "cell_text": cell_text,
                    "header_path": header_path,
                    "page": table_page,
                    "bbox": _serialize_bbox(getattr(cell, "bbox", None)),
                    "char_range": None,
                    "unit_hint": extract_unit_hint(header_path, cell_text),
                }
            )
    return pd.DataFrame(rows, columns=TABLE_CELLS_FINAL_COLUMNS)


def _build_pdf_table_rows(
    *,
    document_id: str,
    blocks: pd.DataFrame,
    table_cells: pd.DataFrame | None,
) -> pd.DataFrame:
    if table_cells is None or table_cells.empty:
        return pd.DataFrame(columns=TABLE_ROWS_FINAL_COLUMNS)

    heading_blocks = _build_heading_blocks(blocks)

    rows: list[dict[str, Any]] = []
    for table_id, table_frame in table_cells.groupby("table_id", sort=False):
        first_data_row = None
        for row_index in sorted(int(value) for value in table_frame["row_index"].dropna().tolist()):
            row_frame = table_frame[table_frame["row_index"].astype(int) == row_index]
            if row_frame["header_path"].isna().all():
                continue
            if first_data_row is None:
                first_data_row = row_index
            ordered_cells = row_frame.sort_values("col_index")
            row_text = " | ".join(
                str(value).strip()
                for value in ordered_cells["cell_text"].tolist()
                if str(value).strip()
            )
            if not row_text:
                continue
            page = _first_non_null(ordered_cells["page"].tolist())
            rows.append(
                {
                    "row_id": f"row_{document_id}_{table_id}_{row_index}",
                    "document_id": document_id,
                    "table_id": str(table_id),
                    "row_index": row_index,
                    "row_text": row_text,
                    "page": page,
                    "bbox": _merge_bbox_payloads(ordered_cells["bbox"].tolist()),
                    "heading_path": _resolve_heading_path_for_page(page, heading_blocks),
                }
            )

    return pd.DataFrame(rows, columns=TABLE_ROWS_FINAL_COLUMNS)


def _build_pdf_figures(
    *,
    document_id: str,
    document: Any,
    blocks: pd.DataFrame,
    text_items: list[dict[str, Any]],
    payload: bytes,
) -> tuple[pd.DataFrame, dict[str, bytes]]:
    pictures = getattr(document, "pictures", []) or []
    if not pictures:
        return pd.DataFrame(columns=FIGURES_FINAL_COLUMNS), {}

    heading_blocks = _build_heading_blocks(blocks)
    text_item_by_ref = {
        str(item.get("ref")): item
        for item in text_items
        if str(item.get("ref") or "").strip()
    }
    figure_caption_blocks = _build_figure_caption_blocks(blocks)
    used_caption_block_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    figure_assets: dict[str, bytes] = {}
    pdf_document: Any | None = None

    try:
        for figure_order, picture in enumerate(pictures, start=1):
            page = _first_page(getattr(picture, "prov", None))
            bbox_obj = _first_bbox(getattr(picture, "prov", None))
            bbox = _serialize_bbox(bbox_obj)
            caption_text, caption_ref, linkage_method = _extract_picture_caption(
                picture=picture,
                document=document,
            )
            caption_block_id = None
            if caption_ref is not None:
                caption_item = text_item_by_ref.get(caption_ref)
                if caption_item is not None:
                    caption_block_id = _normalize_optional_text(caption_item.get("block_id"))
            if caption_block_id is None:
                fallback_block = _find_nearest_caption_block(
                    page=page,
                    figure_bbox=bbox,
                    caption_blocks=figure_caption_blocks,
                    used_block_ids=used_caption_block_ids,
                )
                if fallback_block is not None:
                    caption_block_id = str(fallback_block["block_id"])
                    caption_text = caption_text or _normalize_optional_text(
                        fallback_block.get("text")
                    )
                    linkage_method = "same_page_nearest_caption"
            if caption_block_id is not None:
                used_caption_block_ids.add(caption_block_id)

            (
                image_bytes,
                image_width,
                image_height,
                image_mime_type,
                asset_sha256,
                asset_source,
                pdf_document,
            ) = _extract_picture_asset(
                picture=picture,
                document=document,
                payload=payload,
                pdf_document=pdf_document,
            )

            figure_id = gen_sha512_hash(
                {
                    "document_id": document_id,
                    "figure_order": figure_order,
                    "page": page,
                    "bbox": bbox,
                    "caption_text": caption_text,
                },
                ["document_id", "figure_order", "page", "bbox", "caption_text"],
            )
            image_path = None
            if image_bytes is not None:
                image_path = f"image_assets/{figure_id}.png"
                figure_assets[image_path] = image_bytes

            rows.append(
                {
                    "figure_id": figure_id,
                    "document_id": document_id,
                    "figure_order": figure_order,
                    "figure_label": _extract_figure_label(caption_text),
                    "caption_text": caption_text,
                    "caption_block_id": caption_block_id,
                    "page": page,
                    "bbox": bbox,
                    "heading_path": _resolve_heading_path_for_page(page, heading_blocks),
                    "image_path": image_path,
                    "image_mime_type": image_mime_type,
                    "image_width": image_width,
                    "image_height": image_height,
                    "asset_sha256": asset_sha256,
                    "metadata": {
                        "docling_ref": f"#/pictures/{figure_order - 1}",
                        "picture_label": _normalize_label(getattr(picture, "label", None)),
                        "caption_linkage_method": linkage_method,
                        "asset_source": asset_source,
                    },
                }
            )
    finally:
        if pdf_document is not None:
            pdf_document.close()

    return pd.DataFrame(rows, columns=FIGURES_FINAL_COLUMNS), figure_assets


def _collect_caption_ref_sets(document: Any) -> tuple[set[str], set[str]]:
    figure_caption_refs: set[str] = set()
    table_caption_refs: set[str] = set()
    for picture in getattr(document, "pictures", []) or []:
        for ref in getattr(picture, "captions", []) or []:
            cref = _normalize_optional_text(getattr(ref, "cref", None))
            if cref is not None:
                figure_caption_refs.add(cref)
    for table in getattr(document, "tables", []) or []:
        for ref in getattr(table, "captions", []) or []:
            cref = _normalize_optional_text(getattr(ref, "cref", None))
            if cref is not None:
                table_caption_refs.add(cref)
    return figure_caption_refs, table_caption_refs


def _build_heading_blocks(blocks: pd.DataFrame | None) -> list[dict[str, Any]]:
    if blocks is None or blocks.empty:
        return []
    return sorted(
        [
            {
                "page": item.get("page"),
                "heading_path": str(item.get("heading_path") or "").strip() or None,
                "block_order": int(item.get("block_order") or 0),
            }
            for item in blocks.to_dict(orient="records")
            if str(item.get("heading_path") or "").strip()
        ],
        key=lambda item: (item["page"] is None, item["page"], item["block_order"]),
    )


def _build_figure_caption_blocks(blocks: pd.DataFrame | None) -> list[dict[str, Any]]:
    if blocks is None or blocks.empty:
        return []
    rows = []
    for item in blocks.to_dict(orient="records"):
        if str(item.get("block_type") or "").strip() != "figure_caption":
            continue
        rows.append(
            {
                "block_id": str(item.get("block_id") or ""),
                "text": str(item.get("text") or "").strip(),
                "page": _safe_int(item.get("page")),
                "bbox": item.get("bbox"),
                "block_order": int(item.get("block_order") or 0),
            }
        )
    return rows


def _extract_picture_caption(*, picture: Any, document: Any) -> tuple[str | None, str | None, str]:
    caption_text = None
    if hasattr(picture, "caption_text"):
        caption_text = _normalize_optional_text(picture.caption_text(document))
    caption_ref = None
    for ref in getattr(picture, "captions", []) or []:
        caption_ref = _normalize_optional_text(getattr(ref, "cref", None))
        if caption_ref is None:
            continue
        if caption_text is not None:
            return caption_text, caption_ref, "docling_caption_ref"
        try:
            caption_text = _normalize_optional_text(ref.resolve(document).text)
        except Exception:  # noqa: BLE001
            caption_text = None
        return caption_text, caption_ref, "docling_caption_ref"
    return caption_text, caption_ref, "none"


def _find_nearest_caption_block(
    *,
    page: int | None,
    figure_bbox: str | None,
    caption_blocks: list[dict[str, Any]],
    used_block_ids: set[str],
) -> dict[str, Any] | None:
    normalized_page = _safe_int(page)
    candidates = [
        item
        for item in caption_blocks
        if item.get("block_id")
        and item["block_id"] not in used_block_ids
        and (normalized_page is None or _safe_int(item.get("page")) == normalized_page)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            _caption_distance_score(figure_bbox, item.get("bbox")),
            int(item.get("block_order") or 0),
        ),
    )


def _caption_distance_score(figure_bbox: Any, caption_bbox: Any) -> float:
    figure = _load_bbox_payload(figure_bbox)
    caption = _load_bbox_payload(caption_bbox)
    if figure is None or caption is None:
        return float("inf")
    figure_bottom = float(figure.get("b", 0.0))
    caption_top = float(caption.get("t", 0.0))
    return abs(caption_top - figure_bottom)


def _extract_picture_asset(
    *,
    picture: Any,
    document: Any,
    payload: bytes,
    pdf_document: Any | None,
) -> tuple[bytes | None, int | None, int | None, str | None, str | None, str, Any | None]:
    image = None
    asset_source = "missing"
    try:
        if hasattr(picture, "get_image"):
            image = picture.get_image(document)
            if image is not None:
                asset_source = "docling_crop"
    except Exception:  # noqa: BLE001
        logger.warning("Docling figure crop failed; falling back to PDF crop", exc_info=True)

    if image is None:
        try:
            pdf_document = pdf_document or _open_pdf_document(payload)
            image = _crop_picture_from_pdf(pdf_document=pdf_document, picture=picture)
            if image is not None:
                asset_source = "pymupdf_crop"
        except Exception:  # noqa: BLE001
            logger.warning("PDF figure crop failed", exc_info=True)

    if image is None:
        return None, None, None, None, None, asset_source, pdf_document

    asset_bytes = _serialize_png_image(image)
    return (
        asset_bytes,
        int(getattr(image, "width", 0) or 0),
        int(getattr(image, "height", 0) or 0),
        "image/png",
        hashlib.sha256(asset_bytes).hexdigest(),
        asset_source,
        pdf_document,
    )


def _open_pdf_document(payload: bytes) -> Any:
    import fitz

    return fitz.open(stream=payload, filetype="pdf")


def _crop_picture_from_pdf(*, pdf_document: Any, picture: Any) -> Any | None:
    from PIL import Image
    import fitz

    page_number = _first_page(getattr(picture, "prov", None))
    bbox = _first_bbox(getattr(picture, "prov", None))
    if page_number is None or bbox is None:
        return None
    page_index = page_number - 1
    if page_index < 0 or page_index >= len(pdf_document):
        return None
    page = pdf_document.load_page(page_index)
    clip_bbox = bbox
    if hasattr(bbox, "to_top_left_origin"):
        clip_bbox = bbox.to_top_left_origin(page_height=float(page.rect.height))
    clip = fitz.Rect(*clip_bbox.as_tuple())
    if clip.width <= 0 or clip.height <= 0:
        return None
    pixmap = page.get_pixmap(clip=clip, alpha=False)
    mode = "RGBA" if getattr(pixmap, "alpha", 0) else "RGB"
    return Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)


def _serialize_png_image(image: Any) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _extract_figure_label(caption_text: str | None) -> str | None:
    normalized = _normalize_optional_text(caption_text)
    if normalized is None:
        return None
    match = re.match(r"^\s*((?:fig(?:ure)?\.?)\s*\d+[a-z]?)\b", normalized, re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).strip()


def _build_docling_header_paths(table: Any) -> dict[int, str]:
    header_by_col: dict[int, list[str]] = {}
    for cell in getattr(getattr(table, "data", None), "table_cells", []) or []:
        if not bool(getattr(cell, "column_header", False)):
            continue
        text = str(getattr(cell, "text", "") or "").strip()
        if not text:
            continue
        start = int(getattr(cell, "start_col_offset_idx", 0))
        end = int(getattr(cell, "end_col_offset_idx", start + 1))
        if end <= start:
            end = start + 1
        for col_index in range(start, end):
            values = header_by_col.setdefault(col_index, [])
            if text not in values:
                values.append(text)
    return {
        col_index: " > ".join(values)
        for col_index, values in header_by_col.items()
        if values
    }


def _resolve_document_id(row: pd.Series) -> str:
    document_id = str(row.get("id") or "").strip()
    if document_id:
        return document_id
    source_path = str(row.get("source_path") or "").strip()
    title = _resolve_document_title(row)
    return gen_sha512_hash(
        {
            "source_path": source_path,
            "title": title,
        },
        ["source_path", "title"],
    )


def _resolve_document_title(row: pd.Series) -> str:
    title = str(row.get("title") or "").strip()
    if title:
        return title
    source_path = str(row.get("source_path") or "").strip()
    if source_path:
        return Path(source_path).name
    return str(row.get("id") or "document")


def _build_source_metadata(row: pd.Series, *, parser_name: str) -> dict[str, Any]:
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        payload = dict(metadata)
    else:
        payload = {}
    source_path = str(row.get("source_path") or "").strip()
    source_type = str(row.get("source_type") or Path(source_path).suffix.lstrip(".")).strip()
    if source_path:
        payload["source_path"] = source_path
    if source_type:
        payload["source_type"] = source_type
    payload["source_parser"] = parser_name
    return payload


def _concat_frames(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    usable = [frame.loc[:, columns] for frame in frames if frame is not None and not frame.empty]
    if not usable:
        return pd.DataFrame(columns=columns)
    return pd.concat(usable, ignore_index=True)


def _first_page(provenance: Any) -> int | None:
    if not provenance:
        return None
    first = provenance[0]
    page_no = getattr(first, "page_no", None)
    return int(page_no) if page_no is not None else None


def _serialize_char_range(provenance: Any) -> str | None:
    if not provenance:
        return None
    first = provenance[0]
    charspan = getattr(first, "charspan", None)
    if not charspan:
        return None
    return json.dumps(
        {
            "start": int(charspan[0]),
            "end": int(charspan[1]),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _serialize_prov_bbox(provenance: Any) -> str | None:
    if not provenance:
        return None
    first = provenance[0]
    return _serialize_bbox(getattr(first, "bbox", None))


def _serialize_bbox(bbox: Any) -> str | None:
    if bbox is None:
        return None
    return json.dumps(
        {
            "l": float(getattr(bbox, "l", 0.0)),
            "t": float(getattr(bbox, "t", 0.0)),
            "r": float(getattr(bbox, "r", 0.0)),
            "b": float(getattr(bbox, "b", 0.0)),
            "coord_origin": str(getattr(getattr(bbox, "coord_origin", None), "value", None) or ""),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _map_docling_block_type(
    label: str,
    text: str,
    *,
    caption_ref: str | None,
    figure_caption_refs: set[str],
    table_caption_refs: set[str],
) -> str:
    lowered = str(label or "").lower()
    if lowered == "title":
        return "title"
    if lowered in {"section_header", "heading"}:
        return "heading"
    if "caption" in lowered:
        if caption_ref and caption_ref in figure_caption_refs:
            return "figure_caption"
        if caption_ref and caption_ref in table_caption_refs:
            return "table_caption"
        normalized_text = " ".join(str(text or "").split()).lower()
        if normalized_text.startswith(("table ", "tab. ")):
            return "table_caption"
        if normalized_text.startswith(("figure ", "fig. ", "fig ")):
            return "figure_caption"
        return "figure_caption"
    if "list" in lowered:
        return "list_item"
    return "paragraph"


def _infer_heading_level_from_text(text: str) -> int:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return 1
    parts = normalized.split(maxsplit=1)
    if parts and all(part.isdigit() for part in parts[0].split(".")):
        return len(parts[0].split("."))
    return 1


def _update_heading_stack(
    stack: list[str],
    heading: str,
    level: int,
) -> list[str]:
    normalized = " ".join(str(heading or "").split())
    if not normalized:
        return list(stack)
    effective_level = max(1, int(level or 1))
    if effective_level > len(stack) + 1:
        effective_level = len(stack) + 1
    return [*stack[: effective_level - 1], normalized]


def _first_non_null(values: list[Any]) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        return value
    return None


def _merge_bbox_payloads(values: list[Any]) -> str | None:
    payloads = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            payloads.append(json.loads(value))
        elif isinstance(value, dict):
            payloads.append(value)
    if not payloads:
        return None
    return json.dumps(
        {
            "l": min(float(payload.get("l", 0.0)) for payload in payloads),
            "t": min(float(payload.get("t", 0.0)) for payload in payloads),
            "r": max(float(payload.get("r", 0.0)) for payload in payloads),
            "b": max(float(payload.get("b", 0.0)) for payload in payloads),
            "coord_origin": str(payloads[0].get("coord_origin") or ""),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _resolve_heading_path_for_page(
    page: int | None,
    heading_blocks: list[dict[str, Any]],
) -> str | None:
    if not heading_blocks:
        return None
    normalized_page = _safe_int(page)
    eligible = [
        item
        for item in heading_blocks
        if item.get("heading_path")
        and (
            normalized_page is None
            or _safe_int(item.get("page")) is None
            or _safe_int(item.get("page")) <= normalized_page
        )
    ]
    if not eligible:
        return heading_blocks[-1].get("heading_path")
    return eligible[-1].get("heading_path")


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_bbox(provenance: Any) -> Any | None:
    if not provenance:
        return None
    first = provenance[0]
    return getattr(first, "bbox", None)


def _load_bbox_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return json.loads(text)
    if isinstance(value, dict):
        return value
    return {
        "l": float(getattr(value, "l", 0.0)),
        "t": float(getattr(value, "t", 0.0)),
        "r": float(getattr(value, "r", 0.0)),
        "b": float(getattr(value, "b", 0.0)),
        "coord_origin": str(getattr(getattr(value, "coord_origin", None), "value", None) or ""),
    }


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    return text or None


def _normalize_label(value: Any) -> str | None:
    if value is None:
        return None
    normalized = getattr(value, "value", value)
    return _normalize_optional_text(normalized)


async def _clear_directory_storage(storage: Any, directory: str) -> None:
    pattern = re.compile(r"^(?P<path>.+)$")
    keys = [key for key, _ in storage.find(pattern, base_dir=directory)]
    for key in keys:
        await storage.delete(key)
