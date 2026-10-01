# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Parse input documents and write the Source handoff artifacts."""

from __future__ import annotations

from asyncio import to_thread
import json
import logging
from pathlib import Path
import re
import time
from typing import Any

import pandas as pd

from infra.source.config.source_parser_config import SourceParserConfig
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)
from infra.source.artifact_bundle import SourceArtifactBundle
from infra.source.input_inventory import load_document_inventory
from infra.source.parsers.docling_pdf import build_pdf_bundle, build_pdf_converter
from infra.source.parsers.plain_text import build_text_bundle
from infra.source.storage.file_storage import FileStorage
from infra.source.storage.table_io import write_table_to_storage

logger = logging.getLogger(__name__)


async def build_source_artifacts(
    config: SourceParserConfig,
    input_documents: pd.DataFrame | None = None,
) -> SourceArtifactBundle:
    """Parse supplied documents, or load an inventory from configured storage."""
    started_at = time.perf_counter()
    input_storage = FileStorage(base_dir=config.input.storage.base_dir)
    output_storage = FileStorage(base_dir=config.output.base_dir)
    inventory = input_documents
    if inventory is None:
        inventory = await load_document_inventory(config.input, input_storage)
    input_load_time = time.perf_counter() - started_at
    failures: list[dict[str, str]] = []
    diagnostics = {
        "source_input_failures": list(inventory.attrs.get("load_failures") or []),
        "source_document_failures": failures,
    }
    await output_storage.set(
        "context.json", json.dumps(diagnostics, indent=4, ensure_ascii=False)
    )

    bundles: list[SourceArtifactBundle] = []
    figure_assets: dict[str, bytes] = {}
    pdf_converter: Any | None = None

    for _, row in inventory.iterrows():
        source_path = str(row.get("source_path") or "").strip()
        suffix = Path(source_path).suffix.lower()
        try:
            if source_path and suffix == ".pdf":
                if pdf_converter is None:
                    pdf_converter = await to_thread(build_pdf_converter)
                payload = await input_storage.get(source_path, as_bytes=True)
                if payload is None:
                    raise FileNotFoundError(
                        f"input document not found: {source_path}"
                    )
                bundle = await to_thread(
                    build_pdf_bundle,
                    row=row,
                    payload=payload,
                    config=config,
                    converter=pdf_converter,
                )
            else:
                text = row.get("text")
                if text is None and source_path:
                    text = await input_storage.get(
                        source_path, encoding=config.input.encoding
                    )
                bundle = build_text_bundle(row=row, text=str(text or ""), config=config)
            bundles.append(bundle)
            figure_assets.update(bundle.figure_assets)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, FileNotFoundError):
                error_code = "source_input_unavailable"
            elif suffix == ".pdf":
                error_code = "source_pdf_parse_failed"
            else:
                error_code = "source_text_parse_failed"
            failure = {
                "source_path": source_path or str(row.get("title") or "").strip(),
                "error_code": error_code,
                "error_type": type(exc).__name__,
            }
            failures.append(failure)
            logger.exception(
                "Source document parsing failed source_path=%r error_code=%s",
                failure["source_path"],
                error_code,
            )

    await output_storage.set(
        "context.json", json.dumps(diagnostics, indent=4, ensure_ascii=False)
    )
    if failures and not bundles:
        unit = "document" if len(failures) == 1 else "documents"
        raise RuntimeError(
            f"Source parsing failed for all {len(failures)} input {unit}"
        )

    documents = _concat_frames(
        [bundle.documents for bundle in bundles], DOCUMENTS_FINAL_COLUMNS
    )
    text_units = _concat_frames(
        [bundle.text_units for bundle in bundles], TEXT_UNITS_FINAL_COLUMNS
    )
    if not documents.empty:
        documents["document_order"] = range(len(documents))
    if not text_units.empty:
        text_units["text_unit_order"] = range(len(text_units))

    output = SourceArtifactBundle(
        documents=documents,
        text_units=text_units,
        blocks=_concat_frames(
            [bundle.blocks for bundle in bundles], BLOCKS_FINAL_COLUMNS
        ),
        figures=_concat_frames(
            [bundle.figures for bundle in bundles], FIGURES_FINAL_COLUMNS
        ),
        tables=_concat_frames(
            [bundle.tables for bundle in bundles], TABLES_FINAL_COLUMNS
        ),
        table_rows=_concat_frames(
            [bundle.table_rows for bundle in bundles], TABLE_ROWS_FINAL_COLUMNS
        ),
        table_cells=_concat_frames(
            [bundle.table_cells for bundle in bundles], TABLE_CELLS_FINAL_COLUMNS
        ),
        figure_assets=figure_assets,
    )
    for name in (
        "documents",
        "text_units",
        "blocks",
        "figures",
        "tables",
        "table_rows",
        "table_cells",
    ):
        await write_table_to_storage(getattr(output, name), name, output_storage)
    asset_keys = [
        key
        for key, _ in output_storage.find(
            re.compile(r"^(?P<path>.+)$"), base_dir="image_assets"
        )
    ]
    for key in asset_keys:
        await output_storage.delete(key)
    for asset_path, asset_bytes in output.figure_assets.items():
        await output_storage.set(asset_path, asset_bytes)
    await output_storage.set(
        "stats.json",
        json.dumps(
            {
                "num_documents": len(output.documents),
                "input_load_time": input_load_time,
                "total_runtime": time.perf_counter() - started_at,
            },
            indent=4,
        ),
    )
    logger.info("Source parsing completed documents=%d", len(output.documents))
    return output


def _concat_frames(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    usable = [
        frame.loc[:, columns] for frame in frames if frame is not None and not frame.empty
    ]
    if not usable:
        return pd.DataFrame(columns=columns)
    return pd.concat(usable, ignore_index=True)
