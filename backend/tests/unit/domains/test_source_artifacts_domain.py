from __future__ import annotations

import json

from domain.source import (
    SourceBlock,
    SourceBoundingBox,
    SourceDocument,
    SourceFigure,
    SourceReferenceEntry,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    build_source_document_tree,
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


def test_source_table_rows_keep_raw_cell_text_without_domain_specific_rewrite():
    header_paths = (
        None,
        "Table 2 > Type of heat treatment",
        "Table 2 > Laser power (W)",
        "Table 2 > Scan speed (mm/s)",
        "Table 2 > Laser energy density (J/ mm 3 )",
        "Table 2 > Density (%)",
    )
    raw_rows = (
        ("as-SLM (140/", "-", "140", "280", "139", "92.19"),
        ("280) HT-SLM (140/ 280)", "Furnace HT", "140", "280", "139", "93.14"),
        ("(140/ 200)", "HIP", "140", "200", "194", "98.75"),
    )
    cells = [
        SourceTableCell(
            cell_id=f"cell-{row_index}-{col_index}",
            document_id="doc-p004",
            table_id="tbl-p004-table-2",
            row_index=row_index,
            col_index=col_index,
            cell_text=cell_text,
            header_path=header_paths[col_index],
        )
        for row_index, row in enumerate(raw_rows, start=1)
        for col_index, cell_text in enumerate(row)
    ]

    rows = build_source_table_rows_from_cells(
        document_id="doc-p004",
        cells=cells,
        heading_blocks=[],
    )

    assert [row.row_text for row in rows] == [
        "as-SLM (140/ | - | 140 | 280 | 139 | 92.19",
        "280) HT-SLM (140/ 280) | Furnace HT | 140 | 280 | 139 | 93.14",
        "(140/ 200) | HIP | 140 | 200 | 194 | 98.75",
    ]


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


def test_source_document_tree_builds_section_parent_child_links():
    document = SourceDocument(
        document_id="doc-1",
        human_readable_id=0,
        title="LPBF 316L",
        text="",
    )
    blocks = (
        SourceBlock(
            block_id="blk-title",
            document_id="doc-1",
            block_type="title",
            text="LPBF 316L",
            block_order=0,
        ),
        SourceBlock(
            block_id="blk-intro",
            document_id="doc-1",
            block_type="heading",
            text="1 Introduction",
            block_order=1,
            heading_path="1 Introduction",
            heading_level=1,
            page=1,
        ),
        SourceBlock(
            block_id="blk-intro-p",
            document_id="doc-1",
            block_type="paragraph",
            text="LPBF 316L has been widely studied.",
            block_order=2,
            heading_path="1 Introduction",
            page=1,
        ),
        SourceBlock(
            block_id="blk-results",
            document_id="doc-1",
            block_type="heading",
            text="2 Results",
            block_order=3,
            heading_path="2 Results",
            heading_level=1,
            page=2,
        ),
        SourceBlock(
            block_id="blk-results-p",
            document_id="doc-1",
            block_type="paragraph",
            text="Relative density increased with energy density.",
            block_order=4,
            heading_path="2 Results",
            text_unit_ids=("tu-results",),
            page=2,
        ),
    )
    table = SourceTable(
        table_id="tbl-density",
        document_id="doc-1",
        table_order=1,
        caption_text="Table 1 Relative density.",
        caption_block_id=None,
        page=2,
        bbox=None,
        heading_path="2 Results",
        column_headers=("Sample", "Relative density"),
        table_matrix=(("Sample", "Relative density"), ("A", "99.1")),
    )
    figure = SourceFigure(
        figure_id="fig-density",
        document_id="doc-1",
        figure_order=1,
        figure_label="Figure 1",
        caption_text="Figure 1 Porosity map.",
        caption_block_id=None,
        page=2,
        bbox=None,
        heading_path="2 Results",
        image_path="image_assets/fig-density.png",
        image_mime_type="image/png",
        image_width=20,
        image_height=10,
        asset_sha256="abc",
    )

    tree = build_source_document_tree(
        document=document,
        blocks=blocks,
        tables=(table,),
        figures=(figure,),
    )

    root = tree.nodes[tree.root_node_id]
    assert root.parent_id is None
    assert [tree.nodes[node_id].title for node_id in root.child_ids] == [
        "1 Introduction",
        "2 Results",
    ]

    results = tree.node_for_source_ref("block", "blk-results")
    assert results is not None
    assert results.parent_id == root.node_id
    assert results.child_ids == (
        "node_doc-1_block_blk-results-p",
        "node_doc-1_table_tbl-density",
        "node_doc-1_figure_fig-density",
    )

    paragraph = tree.nodes["node_doc-1_block_blk-results-p"]
    assert paragraph.parent_id == results.node_id
    assert paragraph.node_type == "paragraph"
    assert paragraph.text_unit_ids == ("tu-results",)

    table_node = tree.nodes["node_doc-1_table_tbl-density"]
    assert table_node.parent_id == results.node_id
    assert table_node.node_type == "table"
    assert table_node.source_ref_id == "tbl-density"
    assert table_node.child_ids == ("node_doc-1_table_caption_tbl-density",)

    figure_node = tree.nodes["node_doc-1_figure_fig-density"]
    assert figure_node.parent_id == results.node_id
    assert figure_node.node_type == "figure"
    assert figure_node.child_ids == ("node_doc-1_figure_caption_fig-density",)


def test_source_document_tree_keeps_references_as_records_linking_to_future_trees():
    document = SourceDocument(
        document_id="doc-1",
        human_readable_id=0,
        title="Paper",
        text="",
    )
    reference_heading = SourceBlock(
        block_id="blk-refs",
        document_id="doc-1",
        block_type="heading",
        text="References",
        block_order=10,
        heading_path="References",
        heading_level=1,
    )
    reference = SourceReferenceEntry(
        reference_id="ref-1",
        document_id="doc-1",
        raw_reference="[1] Smith A. LPBF 316L. 2024.",
        reference_index="1",
        title="LPBF 316L",
        source_block_id="blk-ref-entry",
        metadata={"linked_document_id": "doc-smith-2024", "link_status": "parsed"},
    )

    tree = build_source_document_tree(
        document=document,
        blocks=(reference_heading,),
        references=SourceReferenceSet(entries=(reference,)),
    )

    root = tree.nodes[tree.root_node_id]
    references = tree.nodes[root.child_ids[0]]
    assert references.node_type == "references_section"
    assert references.semantic_role == "references"
    assert references.child_ids == ("node_doc-1_reference_ref-1",)

    reference_node = tree.nodes["node_doc-1_reference_ref-1"]
    assert reference_node.node_type == "reference_entry"
    assert reference_node.source_ref_kind == "reference"
    assert reference_node.source_ref_id == "ref-1"
    assert reference_node.child_ids == ()
    assert tree.reference_records["ref-1"].metadata["linked_document_id"] == "doc-smith-2024"
