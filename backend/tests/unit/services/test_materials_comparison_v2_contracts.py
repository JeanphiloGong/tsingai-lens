from __future__ import annotations

from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)


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
    assert TABLES_FINAL_COLUMNS == [
        "table_id",
        "document_id",
        "table_order",
        "caption_text",
        "caption_block_id",
        "page",
        "bbox",
        "heading_path",
        "row_count",
        "col_count",
        "column_headers",
        "table_matrix",
        "table_markdown",
        "table_text",
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
