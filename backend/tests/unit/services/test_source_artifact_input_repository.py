from __future__ import annotations

from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceDocument,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
)
from infra.persistence.sqlite import SqliteSourceArtifactRepository
from application.source import artifact_input_service


def test_artifact_input_service_prefers_sqlite_source_repository(monkeypatch, tmp_path):
    repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    repository.replace_collection_artifacts(
        "col_source",
        SourceArtifactSet(
            documents=(
                SourceDocument(
                    document_id="doc-1",
                    human_readable_id=0,
                    title="Paper",
                    text="Methods",
                    text_unit_ids=("tu-1",),
                ),
            ),
            text_units=(
                SourceTextUnit(
                    text_unit_id="tu-1",
                    human_readable_id=0,
                    text="Methods",
                    n_tokens=3,
                    document_ids=("doc-1",),
                ),
            ),
            blocks=(
                SourceBlock(
                    block_id="blk-1",
                    document_id="doc-1",
                    block_type="heading",
                    text="Methods",
                    block_order=1,
                    text_unit_ids=("tu-1",),
                    heading_path="Methods",
                    heading_level=1,
                ),
            ),
            tables=(
                SourceTable(
                    table_id="tbl-1",
                    document_id="doc-1",
                    table_order=1,
                    caption_text="Table 1",
                    caption_block_id=None,
                    page=1,
                    bbox=None,
                    heading_path="Methods",
                    column_headers=("Sample", "Value"),
                    table_matrix=(("Sample", "Value"), ("A", "1")),
                ),
            ),
            table_rows=(
                SourceTableRow(
                    row_id="row-1",
                    document_id="doc-1",
                    table_id="tbl-1",
                    row_index=1,
                    row_text="A | 1",
                ),
            ),
            table_cells=(
                SourceTableCell(
                    cell_id="cell-1",
                    document_id="doc-1",
                    table_id="tbl-1",
                    row_index=1,
                    col_index=1,
                    cell_text="1",
                    header_path="Value",
                ),
            ),
        ),
    )
    monkeypatch.setattr(artifact_input_service, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        artifact_input_service,
        "build_source_artifact_repository",
        lambda: repository,
    )

    base_dir = tmp_path / "col_source" / "output"
    documents, text_units = artifact_input_service.load_collection_inputs(base_dir)
    blocks = artifact_input_service.load_blocks_artifact(base_dir)
    tables = artifact_input_service.load_tables_artifact(base_dir)
    table_rows = artifact_input_service.load_table_rows_artifact(base_dir)
    table_cells = artifact_input_service.load_table_cells_artifact(base_dir)

    assert documents.iloc[0]["id"] == "doc-1"
    assert text_units is not None
    assert text_units.iloc[0]["id"] == "tu-1"
    assert blocks.iloc[0]["block_id"] == "blk-1"
    assert tables.iloc[0]["table_matrix"] == [["Sample", "Value"], ["A", "1"]]
    assert table_rows.iloc[0]["row_text"] == "A | 1"
    assert table_cells.iloc[0]["header_path"] == "Value"
