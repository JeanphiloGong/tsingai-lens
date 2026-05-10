from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)
from infra.source.runtime.artifact_bundle import SourceArtifactBundle
from infra.source.runtime.chunking import get_encoding_fn
from infra.source.runtime.hashing import gen_sha512_hash
from infra.source.runtime.mapping.block_artifacts import (
    build_pdf_blocks,
    collect_caption_ref_sets,
    collect_pdf_text_items,
)
from infra.source.runtime.mapping.figure_artifacts import build_pdf_figures
from infra.source.runtime.mapping.table_artifacts import (
    build_pdf_table_cells,
    build_pdf_table_rows,
    build_pdf_tables,
)
from infra.source.runtime.parsers.common import (
    build_source_metadata,
    resolve_document_id,
    resolve_document_title,
)


def build_pdf_bundle(
    *,
    row: pd.Series,
    payload: bytes,
    config: SourceRuntimeConfig,
    converter: Any,
) -> SourceArtifactBundle:
    document = convert_pdf_document(
        converter=converter,
        filename=resolve_document_title(row),
        payload=payload,
    )
    document_id = resolve_document_id(row)
    title = resolve_document_title(row)
    text_items = collect_pdf_text_items(document)
    figure_caption_refs, table_caption_refs = collect_caption_ref_sets(document)
    text_units = build_pdf_text_units(document_id, text_items, config)
    final_documents = pd.DataFrame(
        [
            {
                "id": document_id,
                "human_readable_id": 0,
                "title": title,
                "text": str(document.export_to_text() or "").strip(),
                "text_unit_ids": text_units["id"].tolist(),
                "creation_date": row.get("creation_date"),
                "metadata": build_source_metadata(row, parser_name="docling"),
            }
        ],
        columns=DOCUMENTS_FINAL_COLUMNS,
    )
    final_blocks = build_pdf_blocks(
        document_id=document_id,
        title=title,
        text_items=text_items,
        figure_caption_refs=figure_caption_refs,
        table_caption_refs=table_caption_refs,
    )
    final_figures, figure_assets = build_pdf_figures(
        document_id=document_id,
        document=document,
        blocks=final_blocks,
        text_items=text_items,
        payload=payload,
    )
    final_tables = build_pdf_tables(
        document_id=document_id,
        document=document,
        blocks=final_blocks,
        text_items=text_items,
    )
    final_table_cells = build_pdf_table_cells(
        document_id=document_id,
        document=document,
    )
    final_table_rows = build_pdf_table_rows(
        document_id=document_id,
        blocks=final_blocks,
        table_cells=final_table_cells,
    )
    return SourceArtifactBundle(
        documents=final_documents.loc[:, DOCUMENTS_FINAL_COLUMNS],
        text_units=text_units.loc[:, TEXT_UNITS_FINAL_COLUMNS],
        blocks=final_blocks.loc[:, BLOCKS_FINAL_COLUMNS],
        figures=final_figures.loc[:, FIGURES_FINAL_COLUMNS],
        tables=final_tables.loc[:, TABLES_FINAL_COLUMNS],
        table_rows=final_table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=final_table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
        figure_assets=figure_assets,
    )


def build_pdf_converter() -> Any:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=False)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def convert_pdf_document(*, converter: Any, filename: str, payload: bytes) -> Any:
    from docling.datamodel.base_models import DocumentStream

    result = converter.convert(
        DocumentStream(
            name=filename,
            stream=BytesIO(payload),
        )
    )
    return result.document


def build_pdf_text_units(
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
