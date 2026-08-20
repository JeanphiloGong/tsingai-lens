from __future__ import annotations

import logging

import pandas as pd

from infra.source.runtime.artifact_bundle import SourceArtifactBundle


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
    assert "doc_1" in caplog.text
