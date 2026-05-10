from __future__ import annotations

import json

from domain.source import (
    SourceBlock,
    SourceBoundingBox,
    SourceTable,
    SourceTableCell,
    build_heading_blocks,
    build_source_table_rows_from_cells,
)


def test_source_table_record_renders_complete_table_payload():
    table = SourceTable(
        table_id="tbl_doc-1_1_table_1",
        document_id="doc-1",
        table_order=1,
        caption_text="Table 1 Mechanical results.",
        caption_block_id="blk-doc-1-2",
        page=3,
        bbox=SourceBoundingBox(l=1.0, t=2.0, r=3.0, b=4.0, coord_origin="TOPLEFT"),
        heading_path="Results > Mechanical properties",
        column_headers=("Sample", "Strength (MPa)"),
        table_matrix=(("Sample", "Strength (MPa)"), ("A", "123")),
        metadata={"source": "test"},
    )

    record = table.to_record()

    assert record["row_count"] == 2
    assert record["col_count"] == 2
    assert record["table_matrix"] == [["Sample", "Strength (MPa)"], ["A", "123"]]
    assert "| Sample | Strength (MPa) |" in record["table_markdown"]
    assert record["table_text"] == "Sample | Strength (MPa)\nA | 123"
    assert json.loads(record["bbox"]) == {
        "b": 4.0,
        "coord_origin": "TOPLEFT",
        "l": 1.0,
        "r": 3.0,
        "t": 2.0,
    }


def test_source_table_rows_bind_heading_by_same_page_bbox():
    heading = SourceBlock(
        block_id="blk-doc-1-heading",
        document_id="doc-1",
        block_type="heading",
        text="Results",
        block_order=2,
        page=2,
        bbox=SourceBoundingBox(l=0.0, t=100.0, r=100.0, b=120.0, coord_origin="TOPLEFT"),
        heading_path="Results",
        heading_level=1,
    )
    cells = [
        SourceTableCell(
            cell_id="cell-header",
            document_id="doc-1",
            table_id="tbl-doc-1",
            row_index=0,
            col_index=0,
            cell_text="Sample",
        ),
        SourceTableCell(
            cell_id="cell-sample",
            document_id="doc-1",
            table_id="tbl-doc-1",
            row_index=1,
            col_index=0,
            cell_text="A",
            header_path="Sample",
            page=2,
            bbox=SourceBoundingBox(l=0.0, t=140.0, r=50.0, b=160.0, coord_origin="TOPLEFT"),
        ),
        SourceTableCell(
            cell_id="cell-strength",
            document_id="doc-1",
            table_id="tbl-doc-1",
            row_index=1,
            col_index=1,
            cell_text="123 MPa",
            header_path="Strength",
            page=2,
            bbox=SourceBoundingBox(l=50.0, t=140.0, r=100.0, b=160.0, coord_origin="TOPLEFT"),
        ),
    ]

    rows = build_source_table_rows_from_cells(
        document_id="doc-1",
        cells=cells,
        heading_blocks=build_heading_blocks([heading]),
    )

    assert len(rows) == 1
    record = rows[0].to_record()
    assert record["row_text"] == "A | 123 MPa"
    assert record["heading_path"] == "Results"
    assert json.loads(record["bbox"]) == {
        "b": 160.0,
        "coord_origin": "TOPLEFT",
        "l": 0.0,
        "r": 100.0,
        "t": 140.0,
    }


def test_source_table_cell_record_keeps_document_id_alias():
    record = SourceTableCell(
        cell_id="cell-1",
        document_id="doc-1",
        table_id="tbl-doc-1",
        row_index=1,
        col_index=0,
        cell_text="A",
        header_path="Sample",
    ).to_record()

    assert record["document_id"] == "doc-1"
    assert record["id"] == "doc-1"
