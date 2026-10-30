from __future__ import annotations

import logging

import pandas as pd
import pytest
from infra.source.artifact_bundle import SourceArtifactBundle, source_table_payload


@pytest.mark.parametrize(
    ("header_fields", "header_rows", "expected_header_count"),
    [
        ({"header_row_count": 0}, [], 0),
        ({"header_row_count": 1}, [["Power", "Density"]], 1),
        ({"header_row_count": 2}, [["Process", "Result"], ["Power", "Density"]], 2),
        ({}, [["Power", "Density"]], 1),
        ({"header_row_count": None}, [["Power", "Density"]], 1),
    ],
)
def test_table_header_count_preserves_all_measurement_rows(
    header_fields, header_rows, expected_header_count
):
    bundle = SourceArtifactBundle(
        documents=pd.DataFrame([{"id": "doc_1"}]),
        text_units=pd.DataFrame(),
        blocks=pd.DataFrame(),
        figures=pd.DataFrame(),
        tables=pd.DataFrame(
            [
                {
                    "table_id": "table_1",
                    "document_id": "doc_1",
                    "column_headers": ["Power", "Density"],
                    "table_matrix": [
                        *header_rows,
                        ["200 W", "99.5%"],
                        ["250 W", "99.9%"],
                    ],
                    **header_fields,
                }
            ]
        ),
        table_rows=pd.DataFrame(),
        table_cells=pd.DataFrame(),
        figure_assets={},
    )

    table = bundle.to_documents()[0].tables[0]
    assert table.header_row_count == expected_header_count
    assert source_table_payload(table)["table_markdown"] == (
        "| Power | Density |\n| --- | --- |\n" "| 200 W | 99.5% |\n| 250 W | 99.9% |"
    )


def test_to_documents_removes_nul_from_all_source_text(caplog):
    bundle = SourceArtifactBundle(
        documents=pd.DataFrame(
            [
                {
                    "id": "doc_1",
                    "document_order": 0,
                    "title": "Ti\x006Al\x004V",
                    "text": "Document\x00 text",
                    "metadata": {"parser": {"note": "embedded\x00nul"}},
                }
            ]
        ),
        text_units=pd.DataFrame(
            [
                {
                    "id": "unit_1",
                    "text_unit_order": 0,
                    "text": "Unit\x00 text",
                    "document_ids": ["doc_1"],
                }
            ]
        ),
        blocks=pd.DataFrame(
            [
                {
                    "block_id": "block_1",
                    "document_id": "doc_1",
                    "block_type": "paragraph",
                    "text": "Block\x00 text",
                    "block_order": 0,
                }
            ]
        ),
        figures=pd.DataFrame(
            [
                {
                    "figure_id": "figure_1",
                    "document_id": "doc_1",
                    "figure_order": 0,
                    "caption_text": "Figure\x00 caption",
                    "metadata": {"alt": "micro\x00graph"},
                }
            ]
        ),
        tables=pd.DataFrame(
            [
                {
                    "table_id": "table_1",
                    "document_id": "doc_1",
                    "table_order": 0,
                    "caption_text": "Table\x00 caption",
                    "column_headers": ["Power\x00", "Density"],
                    "table_matrix": [["200\x00 W", "99.5%"]],
                    "metadata": {"source": "result\x00s"},
                }
            ]
        ),
        table_rows=pd.DataFrame(
            [
                {
                    "row_id": "row_1",
                    "document_id": "doc_1",
                    "table_id": "table_1",
                    "row_index": 0,
                    "row_text": "200 W\x00 | 99.5%",
                }
            ]
        ),
        table_cells=pd.DataFrame(
            [
                {
                    "cell_id": "cell_1",
                    "id": "doc_1",
                    "document_id": "doc_1",
                    "table_id": "table_1",
                    "row_index": 0,
                    "col_index": 0,
                    "cell_text": "200\x00 W",
                }
            ]
        ),
        figure_assets={},
    )

    with caplog.at_level(logging.WARNING):
        document = bundle.to_documents()[0]

    values = (
        document.title,
        document.text,
        document.metadata["parser"]["note"],
        document.text_units[0].text,
        document.blocks[0].text,
        document.tables[0].caption_text,
        document.tables[0].column_headers[0],
        document.tables[0].table_matrix[0][0],
        document.tables[0].metadata["source"],
        document.table_rows[0].row_text,
        document.table_cells[0].cell_text,
        document.figures[0].caption_text,
        document.figures[0].metadata["alt"],
    )
    assert all("\x00" not in str(value) for value in values)
    assert "documents" in caplog.text


@pytest.mark.parametrize(
    ("raw_page", "expected"),
    [
        (1, 1),
        (2.0, 2),
        ("3", 3),
        (None, None),
        (0, None),
        (-1, None),
        (1.5, None),
        (float("nan"), None),
        (float("inf"), None),
        ("invalid", None),
    ],
)
def test_source_block_page_is_parsed_before_profile_content(raw_page, expected):
    from application.core.document_profiles import service as document_profile_service

    bundle = SourceArtifactBundle(
        documents=pd.DataFrame([{"id": "doc_1"}]),
        text_units=pd.DataFrame(),
        blocks=pd.DataFrame(
            [
                {
                    "block_id": "block_1",
                    "document_id": "doc_1",
                    "block_type": "paragraph",
                    "text": "Laser power versus porosity.",
                    "page": raw_page,
                }
            ]
        ),
        figures=pd.DataFrame(),
        tables=pd.DataFrame(),
        table_rows=pd.DataFrame(),
        table_cells=pd.DataFrame(),
        figure_assets={},
    )
    document = bundle.to_documents()[0]
    document_profile_service.collection_service = None
    document_profile_service.SourceArtifactRepo = None
    document_profile_service.DocumentProfileRepo = None
    content = document_profile_service._build_document_content_blocks(
        "", list(document.blocks)
    )

    assert document.blocks[0].page == expected
    assert content[0]["page"] == expected
    assert content[0]["block_id"] == "block_1"
    assert content[0]["text"] == "Laser power versus porosity."
