# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Build the final Source handoff artifacts from raw input documents."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from infra.source.config.source_runtime_config import GraphRagConfig
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
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
    table_rows: pd.DataFrame
    table_cells: pd.DataFrame


async def run_workflow(
    config: GraphRagConfig,
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
    await write_table_to_storage(output.table_rows, "table_rows", context.output_storage)
    await write_table_to_storage(output.table_cells, "table_cells", context.output_storage)
    logger.info("Workflow completed: create_source_artifacts")
    return WorkflowFunctionOutput(result=output.documents)


async def create_source_artifacts(
    *,
    inventory: pd.DataFrame,
    config: GraphRagConfig,
    context: PipelineRunContext,
) -> SourceArtifactBundle:
    """Build all final Source artifacts in one pass over the raw inputs."""
    bundles: list[SourceArtifactBundle] = []
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

    documents = _concat_frames([bundle.documents for bundle in bundles], DOCUMENTS_FINAL_COLUMNS)
    text_units = _concat_frames([bundle.text_units for bundle in bundles], TEXT_UNITS_FINAL_COLUMNS)
    blocks = _concat_frames([bundle.blocks for bundle in bundles], BLOCKS_FINAL_COLUMNS)
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
        table_rows=table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
    )


def _build_text_bundle(
    *,
    row: pd.Series,
    text: str,
    config: GraphRagConfig,
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
        table_rows=final_table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=final_table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
    )


def _build_pdf_bundle(
    *,
    row: pd.Series,
    payload: bytes,
    config: GraphRagConfig,
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
        table_rows=final_table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=final_table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
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
    config: GraphRagConfig,
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
        block_type = _map_docling_block_type(label, item["text"])
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
        rows.append(
            {
                "block_id": f"blk_{document_id}_{order}",
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

    heading_blocks = []
    if blocks is not None and not blocks.empty:
        heading_blocks = sorted(
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


def _map_docling_block_type(label: str, text: str) -> str:
    lowered = str(label or "").lower()
    if lowered == "title":
        return "title"
    if lowered in {"section_header", "heading"}:
        return "heading"
    if "caption" in lowered:
        return "table_caption"
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
