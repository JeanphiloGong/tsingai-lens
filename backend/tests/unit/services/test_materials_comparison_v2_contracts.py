from __future__ import annotations

from application.source.artifact_input_service import resolve_collection_artifact_paths
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)


def test_collection_artifact_paths_include_materials_comparison_v2_source_targets(tmp_path):
    paths = resolve_collection_artifact_paths(tmp_path / "collection-output")

    assert paths.documents.name == "documents.parquet"
    assert paths.text_units.name == "text_units.parquet"
    assert paths.blocks.name == "blocks.parquet"
    assert paths.figures.name == "figures.parquet"
    assert paths.table_rows.name == "table_rows.parquet"
    assert paths.table_cells.name == "table_cells.parquet"
    assert paths.image_assets_dir.name == "image_assets"
    assert paths.procedure_blocks.name == "procedure_blocks.parquet"


def test_source_contract_columns_cover_materials_comparison_v2_targets():
    assert DOCUMENTS_FINAL_COLUMNS == [
        "id",
        "human_readable_id",
        "title",
        "text",
        "text_unit_ids",
        "creation_date",
        "metadata",
    ]
    assert TEXT_UNITS_FINAL_COLUMNS == [
        "id",
        "human_readable_id",
        "text",
        "n_tokens",
        "document_ids",
    ]
    assert BLOCKS_FINAL_COLUMNS == [
        "block_id",
        "document_id",
        "block_type",
        "text",
        "block_order",
        "text_unit_ids",
        "page",
        "bbox",
        "char_range",
        "heading_path",
        "heading_level",
    ]
    assert FIGURES_FINAL_COLUMNS == [
        "figure_id",
        "document_id",
        "figure_order",
        "figure_label",
        "caption_text",
        "caption_block_id",
        "page",
        "bbox",
        "heading_path",
        "image_path",
        "image_mime_type",
        "image_width",
        "image_height",
        "asset_sha256",
        "metadata",
    ]
    assert TABLE_ROWS_FINAL_COLUMNS == [
        "row_id",
        "document_id",
        "table_id",
        "row_index",
        "row_text",
        "page",
        "bbox",
        "heading_path",
    ]
    assert TABLE_CELLS_FINAL_COLUMNS == [
        "cell_id",
        "id",
        "table_id",
        "row_index",
        "col_index",
        "cell_text",
        "header_path",
        "page",
        "bbox",
        "char_range",
        "unit_hint",
    ]
