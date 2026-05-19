# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Build the final Source handoff artifacts from raw input documents."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

import pandas as pd

from infra.persistence.factory import build_source_artifact_repository
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
from infra.source.runtime.parsers.docling_pdf import build_pdf_bundle, build_pdf_converter
from infra.source.runtime.parsers.plain_text import build_text_bundle
from infra.source.runtime.storage.table_io import (
    load_table_from_storage,
    write_table_to_storage,
)
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.workflow import WorkflowFunctionOutput

logger = logging.getLogger(__name__)


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
    await write_table_to_storage(output.tables, "tables", context.output_storage)
    await write_table_to_storage(output.table_rows, "table_rows", context.output_storage)
    await write_table_to_storage(output.table_cells, "table_cells", context.output_storage)
    await _clear_directory_storage(context.output_storage, "image_assets")
    for asset_path, asset_bytes in output.figure_assets.items():
        await context.output_storage.set(asset_path, asset_bytes)
    _persist_source_artifacts(
        config=config,
        context=context,
        output=output,
    )
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
                pdf_converter = build_pdf_converter()
            payload = await context.input_storage.get(source_path, as_bytes=True)
            if payload is None:
                raise FileNotFoundError(f"input document not found: {source_path}")
            bundles.append(
                build_pdf_bundle(
                    row=row,
                    payload=payload,
                    config=config,
                    converter=pdf_converter,
                )
            )
            figure_assets.update(bundles[-1].figure_assets)
            continue

        text = row.get("text")
        if text is None and source_path:
            text = await context.input_storage.get(source_path, encoding=config.input.encoding)
        bundles.append(
            build_text_bundle(
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
    tables = _concat_frames([bundle.tables for bundle in bundles], TABLES_FINAL_COLUMNS)
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
        tables=tables.loc[:, TABLES_FINAL_COLUMNS],
        table_rows=table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
        figure_assets=dict(figure_assets),
    )


def _concat_frames(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    usable = [frame.loc[:, columns] for frame in frames if frame is not None and not frame.empty]
    if not usable:
        return pd.DataFrame(columns=columns)
    return pd.concat(usable, ignore_index=True)


async def _clear_directory_storage(storage: Any, directory: str) -> None:
    pattern = re.compile(r"^(?P<path>.+)$")
    keys = [key for key, _ in storage.find(pattern, base_dir=directory)]
    for key in keys:
        await storage.delete(key)


def _persist_source_artifacts(
    *,
    config: SourceRuntimeConfig,
    context: PipelineRunContext,
    output: SourceArtifactBundle,
) -> None:
    collection_id = _resolve_collection_id(config=config, context=context)
    if collection_id is None:
        return
    repository = build_source_artifact_repository()
    repository.replace_collection_artifacts(collection_id, output.to_artifact_set())
    logger.info(
        "Persisted Source artifacts to SQLite collection_id=%s document_count=%s table_count=%s table_cell_count=%s",
        collection_id,
        len(output.documents),
        len(output.tables),
        len(output.table_cells),
    )


def _resolve_collection_id(
    *,
    config: SourceRuntimeConfig,
    context: PipelineRunContext,
) -> str | None:
    additional_context = context.state.get("additional_context")
    if isinstance(additional_context, dict):
        collection_id = str(additional_context.get("collection_id") or "").strip()
        if collection_id:
            return collection_id
    root_name = Path(config.root_dir).name
    return root_name if root_name.startswith("col_") else None
