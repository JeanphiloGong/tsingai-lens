from __future__ import annotations

from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceBoundingBox,
    SourceDocument,
    SourceFigure,
    SourceReferenceCandidate,
    SourceReferenceEntry,
    SourceReferenceMention,
    SourceReferenceResolution,
    SourceReferenceSet,
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


def test_sqlite_source_artifact_repository_keeps_reference_state_separate(tmp_path):
    repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    repository.replace_collection_references(
        "col_refs",
        SourceReferenceSet(
            entries=(
                SourceReferenceEntry(
                    reference_id="ref-doc-1-001",
                    document_id="doc-1",
                    raw_reference=(
                        "[1] Smith A. Additive manufacturing of 316L stainless "
                        "steel. Acta Mater. 2024."
                    ),
                    reference_index="1",
                    title="Additive manufacturing of 316L stainless steel",
                    authors_text="Smith A.",
                    year=2024,
                    doi="10.1000/example",
                    source_block_id="blk-ref",
                    page=12,
                    confidence=0.91,
                    metadata={"section": "references"},
                ),
            ),
            mentions=(
                SourceReferenceMention(
                    mention_id="mention-doc-1-001",
                    document_id="doc-1",
                    reference_id="ref-doc-1-001",
                    citation_marker="[1]",
                    context_text="Prior LPBF 316L work [1] studied porosity.",
                    source_block_id="blk-body",
                    page=2,
                    char_start=22,
                    char_end=25,
                    confidence=0.88,
                    metadata={"source": "body"},
                ),
            ),
            resolutions=(
                SourceReferenceResolution(
                    resolution_id="res-ref-doc-1-001",
                    reference_id="ref-doc-1-001",
                    provider="crossref",
                    status="resolved",
                    resolved_title="Additive manufacturing of 316L stainless steel",
                    resolved_authors_text="Smith, A.",
                    resolved_year=2024,
                    resolved_venue="Acta Materialia",
                    resolved_doi="10.1000/example",
                    resolved_url="https://doi.org/10.1000/example",
                    open_access_url="https://example.test/paper.pdf",
                    confidence=0.83,
                    metadata={"match": "doi"},
                ),
            ),
            candidates=(
                SourceReferenceCandidate(
                    candidate_id="cand-ref-doc-1-001",
                    reference_id="ref-doc-1-001",
                    status="metadata_only",
                    relevance_score=0.75,
                    relevance_reason="Cited in the LPBF process context.",
                    cited_by_document_id="doc-1",
                    mention_count=1,
                    representative_context="Prior LPBF 316L work [1] studied porosity.",
                    resolved_doi="10.1000/example",
                    resolved_url="https://doi.org/10.1000/example",
                    open_access_url="https://example.test/paper.pdf",
                    metadata={"rank": 1},
                ),
            ),
        ),
    )

    restored = repository.read_collection_references("col_refs")
    assert restored.entries[0].reference_id == "ref-doc-1-001"
    assert restored.entries[0].metadata == {"section": "references"}
    assert restored.mentions[0].reference_id == "ref-doc-1-001"
    assert restored.resolutions[0].resolved_venue == "Acta Materialia"
    assert restored.candidates[0].mention_count == 1

    repository.replace_collection_artifacts(
        "col_refs",
        SourceArtifactSet(
            documents=(
                SourceDocument(
                    document_id="doc-1",
                    human_readable_id=0,
                    title="Paper",
                    text="Prior LPBF 316L work [1] studied porosity.",
                ),
            ),
        ),
    )
    assert repository.read_collection_references("col_refs").entries

    repository.replace_collection_references("col_refs", SourceReferenceSet())
    assert repository.read_collection_references("col_refs") == SourceReferenceSet()
    assert repository.read_collection_artifacts("col_refs").documents[0].document_id == "doc-1"


def test_sqlite_source_artifact_repository_reads_document_tree_projection(tmp_path):
    repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    repository.replace_collection_artifacts(
        "col_tree",
        SourceArtifactSet(
            documents=(
                SourceDocument(
                    document_id="doc-1",
                    human_readable_id=0,
                    title="Paper",
                    text="Methods\nResult paragraph",
                    text_unit_ids=("tu-1",),
                ),
                SourceDocument(
                    document_id="doc-2",
                    human_readable_id=1,
                    title="Other Paper",
                    text="Other text",
                ),
            ),
            text_units=(
                SourceTextUnit(
                    text_unit_id="tu-1",
                    human_readable_id=0,
                    text="Result paragraph",
                    n_tokens=2,
                    document_ids=("doc-1",),
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
                    text="Result paragraph",
                    block_order=2,
                    text_unit_ids=("tu-1",),
                    heading_path="Methods",
                    page=2,
                ),
                SourceBlock(
                    block_id="blk-other",
                    document_id="doc-2",
                    block_type="paragraph",
                    text="Other paragraph",
                    block_order=1,
                ),
            ),
            tables=(
                SourceTable(
                    table_id="tbl-1",
                    document_id="doc-1",
                    table_order=1,
                    caption_text="Table 1",
                    caption_block_id=None,
                    page=2,
                    bbox=None,
                    heading_path="Methods",
                    column_headers=("Sample", "Value"),
                    table_matrix=(("Sample", "Value"), ("A", "1")),
                ),
            ),
            figures=(
                SourceFigure(
                    figure_id="fig-1",
                    document_id="doc-1",
                    figure_order=1,
                    figure_label="Figure 1",
                    caption_text="Figure 1 caption",
                    caption_block_id=None,
                    page=3,
                    bbox=None,
                    heading_path="Methods",
                    image_path=None,
                    image_mime_type=None,
                    image_width=None,
                    image_height=None,
                    asset_sha256=None,
                ),
            ),
        ),
    )
    repository.replace_collection_references(
        "col_tree",
        SourceReferenceSet(
            entries=(
                SourceReferenceEntry(
                    reference_id="ref-1",
                    document_id="doc-1",
                    raw_reference="Smith A. Related paper. 2024.",
                    title="Related paper",
                    year=2024,
                ),
                SourceReferenceEntry(
                    reference_id="ref-2",
                    document_id="doc-2",
                    raw_reference="Other reference.",
                ),
            )
        ),
    )

    tree = repository.read_document_tree("col_tree", "doc-1")

    assert tree.document_id == "doc-1"
    assert tree.collection_id == "col_tree"
    assert tree.root.title == "Paper"
    assert tree.node_for_source_ref("block", "blk-body") is not None
    assert tree.node_for_source_ref("table", "tbl-1") is not None
    assert tree.node_for_source_ref("figure", "fig-1") is not None
    assert tree.node_for_source_ref("block", "blk-other") is None
    assert set(tree.reference_records) == {"ref-1"}
    reference_node = tree.node_for_source_ref("reference", "ref-1")
    assert reference_node is not None
    assert reference_node.text == "Smith A. Related paper. 2024."


def test_sqlite_source_artifact_repository_raises_for_missing_document_tree(tmp_path):
    repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")

    try:
        repository.read_document_tree("missing_col", "missing_doc")
    except FileNotFoundError as exc:
        assert "missing_col/missing_doc" in str(exc)
    else:
        raise AssertionError("expected missing source document to raise")
