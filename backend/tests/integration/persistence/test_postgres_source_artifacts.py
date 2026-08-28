from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

import pytest

from domain.source import (
    Collection,
    Document,
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceReferenceEntry,
    SourceReferenceMention,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)


pytestmark = pytest.mark.anyio

NOW = "2026-08-27T10:00:00+00:00"
COLLECTION_ID = "col_source"


@pytest.fixture
async def source_repository(postgres_session_factory):
    await PostgresAuthRepository(postgres_session_factory).add_user(
        {
            "user_id": "user_source",
            "email": "source@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": datetime(2026, 8, 27, tzinfo=timezone.utc).isoformat(),
        }
    )
    collections = PostgresCollectionRepository(postgres_session_factory)
    await collections.add_collection(
        Collection.create(
            collection_id=COLLECTION_ID,
            owner_user_id="user_source",
            name="Source collection",
            description=None,
            now_iso=NOW,
        )
    )
    await collections.add_documents(
        COLLECTION_ID,
        (_document("doc_a"), _document("doc_b")),
        updated_at=NOW,
    )
    return PostgresSourceArtifactRepository(postgres_session_factory)


def _document(document_id: str) -> Document:
    digest = sha256(document_id.encode("utf-8")).hexdigest()
    return Document(
        document_id=document_id,
        original_filename=f"{document_id}.pdf",
        stored_filename=f"stored-{document_id}.pdf",
        storage_key=f"{COLLECTION_ID}/input/stored-{document_id}.pdf",
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=100,
        created_at=NOW,
        updated_at=NOW,
    )


def _source(document_id: str, *, title: str) -> SourceDocument:
    text_unit = SourceTextUnit(
        text_unit_id=f"tu-{document_id}",
        text_unit_order=0,
        text="Laser power increased from 100 W to 150 W.",
        n_tokens=10,
        document_ids=(document_id,),
    )
    block = SourceBlock(
        block_id=f"block-{document_id}",
        document_id=document_id,
        block_type="paragraph",
        text=text_unit.text,
        block_order=0,
        text_unit_ids=(text_unit.text_unit_id,),
        page=2,
        heading_path="Methods",
        heading_level=1,
    )
    table = SourceTable(
        table_id=f"table-{document_id}",
        document_id=document_id,
        table_order=0,
        caption_text="Process conditions",
        caption_block_id=None,
        page=3,
        heading_path="Methods",
        column_headers=("Sample", "Laser power (W)"),
        table_matrix=(("Sample", "Laser power (W)"), ("A", "100")),
        header_row_count=1,
        metadata={"parser": "docling"},
    )
    table_row = SourceTableRow(
        row_id=f"row-{document_id}",
        document_id=document_id,
        table_id=table.table_id,
        row_index=1,
        row_text="A | 100",
        page=3,
        heading_path="Methods",
    )
    table_cell = SourceTableCell(
        cell_id=f"cell-{document_id}",
        document_id=document_id,
        table_id=table.table_id,
        row_index=1,
        col_index=1,
        cell_text="100",
        header_path="Laser power (W)",
        page=3,
        unit_hint="W",
    )
    figure = SourceFigure(
        figure_id=f"figure-{document_id}",
        document_id=document_id,
        figure_order=0,
        figure_label="Figure 1",
        caption_text="Representative microstructure",
        caption_block_id=None,
        page=4,
        heading_path="Results",
        image_path=None,
        image_mime_type=None,
        image_width=None,
        image_height=None,
        asset_sha256=None,
    )
    return SourceDocument(
        document_id=document_id,
        document_order=0,
        title=title,
        text=f"Methods\n{text_unit.text}",
        creation_date="2025-01-01",
        metadata={"source_parser": "docling"},
        text_units=(text_unit,),
        blocks=(block,),
        tables=(table,),
        table_rows=(table_row,),
        table_cells=(table_cell,),
        figures=(figure,),
    )


async def test_source_repository_round_trips_each_current_document_independently(
    source_repository,
) -> None:
    first = _source("doc_a", title="Paper A")
    second = _source("doc_b", title="Paper B")

    await source_repository.replace_document(COLLECTION_ID, first)
    await source_repository.replace_document(COLLECTION_ID, second)

    assert await source_repository.read_document(COLLECTION_ID, "doc_a") == first
    assert await source_repository.read_document(COLLECTION_ID, "doc_b") == second
    assert await source_repository.read_collection_documents(COLLECTION_ID) == (
        first,
        second,
    )


async def test_source_repository_batch_read_is_exact_ordered_and_complete(
    source_repository,
) -> None:
    first = _source("doc_a", title="Paper A")
    second = _source("doc_b", title="Paper B")
    await source_repository.replace_document(COLLECTION_ID, first)
    await source_repository.replace_document(COLLECTION_ID, second)

    selected = await source_repository.read_documents(
        COLLECTION_ID,
        ("doc_b", "doc_a"),
    )

    assert selected == (second, first)
    assert selected[0].table_rows == second.table_rows
    assert selected[0].table_cells == second.table_cells
    with pytest.raises(ValueError, match="must be unique"):
        await source_repository.read_documents(
            COLLECTION_ID,
            ("doc_a", "doc_a"),
        )
    with pytest.raises(FileNotFoundError, match="doc_missing"):
        await source_repository.read_documents(
            COLLECTION_ID,
            ("doc_a", "doc_missing"),
        )


async def test_replacing_one_document_source_does_not_rebuild_other_documents(
    source_repository,
) -> None:
    first = _source("doc_a", title="Paper A")
    second = _source("doc_b", title="Paper B")
    await source_repository.replace_document(COLLECTION_ID, first)
    await source_repository.replace_document(COLLECTION_ID, second)

    revised_first = replace(
        first,
        title="Paper A revised",
        text="Reparsed current source",
        text_units=(),
        blocks=(),
        tables=(),
        table_rows=(),
        table_cells=(),
        figures=(),
    )
    await source_repository.replace_document(COLLECTION_ID, revised_first)

    assert await source_repository.read_document(COLLECTION_ID, "doc_a") == revised_first
    assert await source_repository.read_document(COLLECTION_ID, "doc_b") == second


async def test_source_repository_round_trips_document_references_and_tree(
    source_repository,
) -> None:
    source = _source("doc_a", title="Paper A")
    await source_repository.replace_document(COLLECTION_ID, source)
    references = SourceReferenceSet(
        entries=(
            SourceReferenceEntry(
                reference_id="ref-a-1",
                document_id="doc_a",
                raw_reference="Smith et al. (2024)",
                reference_index="1",
                title="Prior LPBF study",
                source_block_id=source.blocks[0].block_id,
                page=5,
                confidence=0.9,
            ),
        ),
        mentions=(
            SourceReferenceMention(
                mention_id="mention-a-1",
                document_id="doc_a",
                reference_id="ref-a-1",
                citation_marker="[1]",
                context_text="Prior work reported a similar trend [1].",
                source_block_id=source.blocks[0].block_id,
                page=2,
                confidence=0.8,
            ),
        ),
    )

    await source_repository.replace_document_references("doc_a", references)

    assert await source_repository.read_collection_references(COLLECTION_ID) == references
    tree = await source_repository.read_document_tree(COLLECTION_ID, "doc_a")
    assert tree.document_id == "doc_a"
    assert {
        node.source_ref_id for node in tree.nodes.values() if node.source_ref_id
    } >= {
        source.blocks[0].block_id,
        source.tables[0].table_id,
        source.figures[0].figure_id,
    }


async def test_source_reference_batch_excludes_unselected_documents(
    source_repository,
) -> None:
    first = _source("doc_a", title="Paper A")
    second = _source("doc_b", title="Paper B")
    await source_repository.replace_document(COLLECTION_ID, first)
    await source_repository.replace_document(COLLECTION_ID, second)
    await source_repository.replace_document_references(
        "doc_a",
        SourceReferenceSet(
            entries=(
                SourceReferenceEntry(
                    reference_id="ref-a-1",
                    document_id="doc_a",
                    raw_reference="Reference A",
                ),
            ),
        ),
    )
    second_references = SourceReferenceSet(
        entries=(
            SourceReferenceEntry(
                reference_id="ref-b-1",
                document_id="doc_b",
                raw_reference="Reference B",
            ),
        ),
    )
    await source_repository.replace_document_references(
        "doc_b",
        second_references,
    )

    selected = await source_repository.read_collection_references(
        COLLECTION_ID,
        ("doc_b",),
    )

    assert selected == second_references


async def test_source_repository_rejects_cross_document_children_and_references(
    source_repository,
) -> None:
    source = _source("doc_a", title="Paper A")
    foreign_block = replace(source.blocks[0], document_id="doc_b")
    with pytest.raises(ValueError, match="Source children must belong"):
        await source_repository.replace_document(
            COLLECTION_ID,
            replace(source, blocks=(foreign_block,)),
        )

    await source_repository.replace_document(COLLECTION_ID, source)
    foreign_references = SourceReferenceSet(
        entries=(
            SourceReferenceEntry(
                reference_id="ref-b-1",
                document_id="doc_b",
                raw_reference="Foreign reference",
            ),
        )
    )
    with pytest.raises(ValueError, match="Reference entries must belong"):
        await source_repository.replace_document_references(
            "doc_a",
            foreign_references,
        )
