from __future__ import annotations

from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceBoundingBox,
    SourceDocument,
    SourceFigure,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
)
from infra.persistence.sqlite import SqliteSourceArtifactRepository


def test_sqlite_source_artifact_repository_round_trips_artifact_set(tmp_path):
    repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    artifacts = SourceArtifactSet(
        documents=(
            SourceDocument(
                document_id="doc-1",
                human_readable_id=0,
                title="Paper",
                text="Methods\nTable 1 Results",
                text_unit_ids=("tu-1",),
                creation_date="2026-05-10T00:00:00+00:00",
                metadata={"source_parser": "test"},
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
                page=1,
                bbox=SourceBoundingBox(
                    l=0.0,
                    t=10.0,
                    r=100.0,
                    b=20.0,
                    coord_origin="TOPLEFT",
                ),
                heading_path="Methods",
                heading_level=1,
            ),
        ),
        tables=(
            SourceTable(
                table_id="tbl-1",
                document_id="doc-1",
                table_order=1,
                caption_text="Table 1 Results",
                caption_block_id="blk-2",
                page=1,
                bbox=None,
                heading_path="Methods",
                column_headers=("Sample", "Strength (MPa)"),
                table_matrix=(("Sample", "Strength (MPa)"), ("A", "123")),
                metadata={"caption_linkage_method": "test"},
            ),
        ),
        table_rows=(
            SourceTableRow(
                row_id="row-1",
                document_id="doc-1",
                table_id="tbl-1",
                row_index=1,
                row_text="A | 123",
                page=1,
                heading_path="Methods",
            ),
        ),
        table_cells=(
            SourceTableCell(
                cell_id="cell-1",
                document_id="doc-1",
                table_id="tbl-1",
                row_index=1,
                col_index=1,
                cell_text="123",
                header_path="Strength (MPa)",
                page=1,
                unit_hint="MPa",
            ),
        ),
        figures=(
            SourceFigure(
                figure_id="fig-1",
                document_id="doc-1",
                figure_order=1,
                figure_label="Figure 1",
                caption_text="Figure 1 SEM",
                caption_block_id="blk-3",
                page=2,
                bbox=None,
                heading_path="Results",
                image_path="image_assets/fig-1.png",
                image_mime_type="image/png",
                image_width=20,
                image_height=10,
                asset_sha256="abc",
                metadata={"asset_source": "test"},
            ),
        ),
    )

    repository.replace_collection_artifacts("col_test", artifacts)
    restored = repository.read_collection_artifacts("col_test")

    assert restored.documents[0].document_id == "doc-1"
    assert restored.documents[0].text_unit_ids == ("tu-1",)
    assert restored.text_units[0].document_ids == ("doc-1",)
    assert restored.blocks[0].text_unit_ids == ("tu-1",)
    assert restored.tables[0].table_matrix == (
        ("Sample", "Strength (MPa)"),
        ("A", "123"),
    )
    assert restored.table_rows[0].row_text == "A | 123"
    assert restored.table_cells[0].unit_hint == "MPa"
    assert restored.figures[0].image_path == "image_assets/fig-1.png"

    repository.replace_collection_artifacts(
        "col_test",
        SourceArtifactSet(
            documents=(
                SourceDocument(
                    document_id="doc-2",
                    human_readable_id=0,
                    title="Replacement",
                    text="Replacement text",
                ),
            ),
        ),
    )

    replaced = repository.read_collection_artifacts("col_test")
    assert [document.document_id for document in replaced.documents] == ["doc-2"]
    assert replaced.tables == ()
