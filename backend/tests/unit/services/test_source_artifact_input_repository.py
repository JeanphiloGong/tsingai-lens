from __future__ import annotations

from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceDocument,
    SourceReferenceEntry,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
    build_source_document_tree,
)
from application.source import artifact_input_service


class _SourceRepository:
    def __init__(
        self,
        artifacts: SourceArtifactSet,
        references: SourceReferenceSet = SourceReferenceSet(),
    ) -> None:
        self.artifacts = artifacts
        self.references = references

    def read_collection_artifacts(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceArtifactSet:
        return self.artifacts

    def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ):
        document = next(
            item for item in self.artifacts.documents if item.document_id == document_id
        )
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=tuple(
                item
                for item in self.artifacts.blocks
                if item.document_id == document_id
            ),
            tables=tuple(
                item
                for item in self.artifacts.tables
                if item.document_id == document_id
            ),
            figures=tuple(
                item
                for item in self.artifacts.figures
                if item.document_id == document_id
            ),
            references=self.references,
        )


def test_artifact_input_service_uses_explicit_source_repository():
    repository = _SourceRepository(
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
    documents, text_units = artifact_input_service.load_collection_inputs(
        "col_source", repository
    )
    blocks = artifact_input_service.load_blocks_artifact("col_source", repository)
    tables = artifact_input_service.load_tables_artifact("col_source", repository)
    table_rows = artifact_input_service.load_table_rows_artifact(
        "col_source", repository
    )
    table_cells = artifact_input_service.load_table_cells_artifact(
        "col_source", repository
    )

    assert documents[0]["id"] == "doc-1"
    assert text_units is not None
    assert text_units[0]["id"] == "tu-1"
    assert blocks[0]["block_id"] == "blk-1"
    assert tables[0]["table_matrix"] == [["Sample", "Value"], ["A", "1"]]
    assert table_rows[0]["row_text"] == "A | 1"
    assert table_cells[0]["header_path"] == "Value"


def test_artifact_input_service_loads_document_tree():
    source_repository = _SourceRepository(
        SourceArtifactSet(
            documents=(
                SourceDocument(
                    document_id="doc-1",
                    human_readable_id=0,
                    title="Paper",
                    text="Methods\nEvidence text",
                ),
            ),
            blocks=(
                SourceBlock(
                    block_id="blk-heading",
                    document_id="doc-1",
                    block_type="heading",
                    text="Methods",
                    block_order=1,
                    heading_path="Methods",
                    heading_level=1,
                ),
                SourceBlock(
                    block_id="blk-body",
                    document_id="doc-1",
                    block_type="paragraph",
                    text="Evidence text",
                    block_order=2,
                    heading_path="Methods",
                ),
            ),
        ),
        SourceReferenceSet(
            entries=(
                SourceReferenceEntry(
                    reference_id="ref-1",
                    document_id="doc-1",
                    raw_reference="Smith A. Related paper. 2024.",
                ),
            )
        ),
    )
    tree = artifact_input_service.load_document_tree(
        "col_source",
        "doc-1",
        source_repository,
    ).to_record()

    assert tree["document_id"] == "doc-1"
    assert tree["collection_id"] == "col_source"
    assert tree["root_node_id"] == "node_doc-1_document"
    assert tree["nodes"]["node_doc-1_block_blk-body"]["text"] == "Evidence text"
    assert tree["reference_records"]["ref-1"]["raw_reference"].startswith("Smith")
