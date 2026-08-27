from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from domain.source import (
    Collection,
    Document,
    assemble_source_documents,
    SourceBlock,
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
    TaskRecord,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.models.source import SourceDocument as SourceDocumentRow
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
BACKEND_ROOT = Path(__file__).resolve().parents[3]
NOW = "2026-07-19T10:00:00+00:00"
REAL_SOURCE_DOCUMENT_ID = "d" * 128
REAL_SOURCE_TEXT_UNIT_ID = "t" * 128
REAL_SOURCE_BLOCK_ID = f"blk_{REAL_SOURCE_DOCUMENT_ID}_1000"
REAL_SOURCE_TABLE_ID = f"tbl_{REAL_SOURCE_DOCUMENT_ID}_1_table_1"
REAL_SOURCE_ROW_ID = (
    f"row_{REAL_SOURCE_DOCUMENT_ID}_{REAL_SOURCE_TABLE_ID}_1"
)
REAL_SOURCE_REFERENCE_ID = f"ref-{REAL_SOURCE_DOCUMENT_ID}-0001"
REAL_SOURCE_CANDIDATE_ID = f"cand-{REAL_SOURCE_REFERENCE_ID}"
REAL_SOURCE_MENTION_ID = (
    f"mention-{REAL_SOURCE_DOCUMENT_ID}-{REAL_SOURCE_BLOCK_ID}-0001"
)


pytestmark = pytest.mark.anyio


@pytest.fixture
async def source_repositories(postgres_session_factory):
    sessions = postgres_session_factory
    await PostgresAuthRepository(sessions).add_user(
        {
            "user_id": "user_source",
            "email": "source@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
        }
    )
    collections = PostgresCollectionRepository(sessions)
    await collections.add_collection(
        Collection(
            collection_id="col_source",
            owner_user_id="user_source",
            name="Source collection",
            description=None,
            status="idle",
            created_at=NOW,
            updated_at=NOW,
            documents=(),
        )
    )
    await collections.add_documents(
        "col_source",
        (_collection_document("stored-paper.pdf"),),
        updated_at=NOW,
    )
    return (
        PostgresSourceArtifactRepository(sessions),
        PostgresBuildRepository(sessions),
    )


def _collection_document(stored_filename: str) -> Document:
    digest = sha256(stored_filename.encode("utf-8")).hexdigest()
    suffix = digest[:12]
    return Document(
        document_id=f"doc_{suffix}",
        original_filename="paper.pdf",
        stored_filename=stored_filename,
        storage_key=f"col_source/input/{stored_filename}",
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=100,
        created_at=NOW,
    )


def _task(task_id: str) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        collection_id="col_source",
        task_type="build",
        status="queued",
        current_stage="queued",
        progress_percent=0,
        progress_detail=None,
        output_path=None,
        errors=(),
        warnings=(),
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        finished_at=None,
    )


def _artifacts(title: str = "Paper") -> tuple[SourceDocument, ...]:
    return assemble_source_documents(
        documents=(
            SourceDocument(
                document_id="srcdoc_runtime",
                document_order=0,
                title=title,
                text="Methods\nResult",
                creation_date=NOW,
                metadata={
                    "source_path": "stored-paper.pdf",
                    "source_parser": "docling",
                },
            ),
        ),
        text_units=(
            SourceTextUnit(
                text_unit_id="tu-1",
                text_unit_order=0,
                text="Result",
                n_tokens=1,
                document_ids=("srcdoc_runtime",),
            ),
        ),
        blocks=(
            SourceBlock(
                block_id="block-1",
                document_id="srcdoc_runtime",
                block_type="paragraph",
                text="Result",
                block_order=0,
                text_unit_ids=("tu-1",),
                page=1,
                heading_path="Methods",
                heading_level=1,
            ),
        ),
        tables=(
            SourceTable(
                table_id="table-1",
                document_id="srcdoc_runtime",
                table_order=0,
                caption_text="Table 1",
                caption_block_id=None,
                page=1,
                heading_path="Methods",
                column_headers=("Sample", "Value"),
                table_matrix=(("Sample", "Value"), ("A", "1")),
                header_row_count=1,
                metadata={"parser": "docling"},
            ),
        ),
        table_rows=(
            SourceTableRow(
                row_id="row-1",
                document_id="srcdoc_runtime",
                table_id="table-1",
                row_index=1,
                row_text="A | 1",
                page=1,
                heading_path="Methods",
            ),
        ),
        table_cells=(
            SourceTableCell(
                cell_id="cell-1",
                document_id="srcdoc_runtime",
                table_id="table-1",
                row_index=1,
                col_index=1,
                cell_text="1",
                row_span=2,
                col_span=1,
                row_header=True,
                header_path="Value",
                page=1,
                unit_hint="MPa",
            ),
        ),
    )


def _real_shape_artifacts() -> tuple[SourceDocument, ...]:
    document = _artifacts()[0]
    return (
        replace(
            document,
            document_id=REAL_SOURCE_DOCUMENT_ID,
            text_units=(
                replace(
                    document.text_units[0],
                    text_unit_id=REAL_SOURCE_TEXT_UNIT_ID,
                    document_ids=(REAL_SOURCE_DOCUMENT_ID,),
                ),
            ),
            blocks=(
                replace(
                    document.blocks[0],
                    block_id=REAL_SOURCE_BLOCK_ID,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    text_unit_ids=(REAL_SOURCE_TEXT_UNIT_ID,),
                ),
            ),
            tables=(
                replace(
                    document.tables[0],
                    table_id=REAL_SOURCE_TABLE_ID,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    caption_block_id=REAL_SOURCE_BLOCK_ID,
                ),
            ),
            table_rows=(
                replace(
                    document.table_rows[0],
                    row_id=REAL_SOURCE_ROW_ID,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    table_id=REAL_SOURCE_TABLE_ID,
                ),
            ),
            table_cells=(
                replace(
                    document.table_cells[0],
                    cell_id="c" * 128,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    table_id=REAL_SOURCE_TABLE_ID,
                ),
            ),
        ),
    )


def _figure(build_id: str) -> SourceFigure:
    return SourceFigure(
        figure_id="figure-1",
        document_id="srcdoc_runtime",
        figure_order=1,
        figure_label="Figure 1",
        caption_text="Figure 1. Result morphology.",
        caption_block_id=None,
        page=1,
        heading_path="Results",
        image_path=(f"col_source/objects/source/{build_id}/figures/{'a' * 64}.png"),
        image_mime_type="image/png",
        image_width=20,
        image_height=10,
        asset_sha256="a" * 64,
        image_size_bytes=9,
        metadata={"parser": "docling"},
    )


def _references() -> SourceReferenceSet:
    return SourceReferenceSet(
        entries=(
            SourceReferenceEntry(
                reference_id="reference-1",
                document_id="srcdoc_runtime",
                raw_reference="[1] Smith A. Result paper. 2024.",
                reference_index="1",
                title="Result paper",
                authors_text="Smith A",
                year=2024,
                source_block_id="block-1",
                page=1,
                confidence=0.9,
                metadata={"sequence": 1},
            ),
        ),
        mentions=(
            SourceReferenceMention(
                mention_id="mention-1",
                document_id="srcdoc_runtime",
                reference_id="reference-1",
                citation_marker="[1]",
                context_text="Prior result [1].",
                source_block_id="block-1",
                page=1,
                confidence=0.9,
                metadata={"raw_marker": "[1]"},
            ),
        ),
        resolutions=(
            SourceReferenceResolution(
                resolution_id="resolution-1",
                reference_id="reference-1",
                provider="crossref",
                status="resolved",
                resolved_title="Result paper",
                resolved_year=2024,
                resolved_doi="10.1000/result",
                resolved_url="https://doi.org/10.1000/result",
                confidence=0.8,
                metadata={"match": "doi"},
            ),
        ),
        candidates=(
            SourceReferenceCandidate(
                candidate_id="candidate-1",
                reference_id="reference-1",
                status="metadata_only",
                relevance_score=0.75,
                relevance_reason="Cited in results.",
                cited_by_document_id="srcdoc_runtime",
                mention_count=1,
                representative_context="Prior result [1].",
                resolved_doi="10.1000/result",
                resolved_url="https://doi.org/10.1000/result",
                metadata={"rank": 1},
            ),
        ),
    )


def _real_shape_references() -> SourceReferenceSet:
    references = _references()
    return replace(
        references,
        entries=(
            replace(
                references.entries[0],
                reference_id=REAL_SOURCE_REFERENCE_ID,
                document_id=REAL_SOURCE_DOCUMENT_ID,
                source_block_id=REAL_SOURCE_BLOCK_ID,
            ),
        ),
        mentions=(
            replace(
                references.mentions[0],
                mention_id=REAL_SOURCE_MENTION_ID,
                document_id=REAL_SOURCE_DOCUMENT_ID,
                reference_id=REAL_SOURCE_REFERENCE_ID,
                source_block_id=REAL_SOURCE_BLOCK_ID,
            ),
        ),
        resolutions=(
            replace(
                references.resolutions[0],
                reference_id=REAL_SOURCE_REFERENCE_ID,
            ),
        ),
        candidates=(
            replace(
                references.candidates[0],
                candidate_id=REAL_SOURCE_CANDIDATE_ID,
                reference_id=REAL_SOURCE_REFERENCE_ID,
                cited_by_document_id=REAL_SOURCE_DOCUMENT_ID,
            ),
        ),
    )


async def _finish(
    builds: PostgresBuildRepository, task: TaskRecord, *, success: bool
) -> None:
    status = "completed" if success else "failed"
    await builds.finish_build(
        replace(
            task,
            status=status,
            current_stage="artifacts_ready" if success else "failed",
            progress_percent=100,
            updated_at="2026-07-19T10:05:00+00:00",
            started_at="2026-07-19T10:01:00+00:00",
            finished_at="2026-07-19T10:05:00+00:00",
        ),
        build_status="succeeded" if success else "failed",
        activate=success,
    )


async def test_source_repository_round_trips_structure_with_document_lineage(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_source")
    await builds.add_task(task, build_id="build_source")

    await repository.replace_collection_documents(
        "col_source", "build_source", _artifacts()
    )

    assert not await repository.read_collection_documents("col_source")
    restored = await repository.read_collection_documents(
        "col_source", build_id="build_source"
    )
    assert restored == _artifacts()
    tree = await repository.read_document_tree(
        "col_source", "srcdoc_runtime", build_id="build_source"
    )
    assert tree.node_for_source_ref("block", "block-1") is not None
    assert tree.node_for_source_ref("table", "table-1") is not None

    async with repository.session_factory() as session:
        row = await session.scalar(select(SourceDocumentRow))
        assert row.collection_document_id.startswith("coldoc_")
        assert row.document_version_id.startswith("docver_")
        assert row.build_id == "build_source"


async def test_default_reads_keep_last_successful_build_when_next_build_fails(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    first_task = _task("task_first")
    await builds.add_task(first_task, build_id="build_first")
    await repository.replace_collection_documents(
        "col_source", "build_first", _artifacts("First")
    )
    await _finish(builds, first_task, success=True)
    with pytest.raises(ValueError, match="collection build is not writable"):
        await repository.replace_collection_documents(
            "col_source", "build_first", _artifacts("Rewritten")
        )
    assert (await repository.list_documents("col_source"))[0].title == "First"

    second_task = _task("task_second")
    await builds.add_task(second_task, build_id="build_second")
    await repository.replace_collection_documents(
        "col_source", "build_second", _artifacts("Pending")
    )

    assert (await repository.list_documents("col_source"))[0].title == "First"
    assert (
        (await repository.list_documents("col_source", build_id="build_second"))[0].title
        == "Pending"
    )
    await _finish(builds, second_task, success=False)
    assert (await repository.list_documents("col_source"))[0].title == "First"


async def test_source_repository_versions_figures_and_references_with_the_source_build(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_source_media")
    build_id = "build_source_media"
    await builds.add_task(task, build_id=build_id)
    document = _artifacts()[0]
    artifacts = (replace(document, figures=(_figure(build_id),)),)

    await repository.replace_collection_documents("col_source", build_id, artifacts)
    await repository.replace_collection_references(
        "col_source",
        build_id,
        _references(),
    )

    assert await repository.list_figures("col_source") == []
    assert await repository.read_collection_references(
        "col_source"
    ) == SourceReferenceSet()
    assert await repository.list_figures("col_source", build_id=build_id) == [
        _figure(build_id)
    ]
    assert (
        await repository.read_collection_references("col_source", build_id=build_id)
        == _references()
    )

    await _finish(builds, task, success=True)

    assert await repository.list_figures("col_source") == [_figure(build_id)]
    assert await repository.read_collection_references("col_source") == _references()
    tree = await repository.read_document_tree("col_source", "srcdoc_runtime")
    assert tree.node_for_source_ref("figure", "figure-1") is not None
    assert tree.node_for_source_ref("reference", "reference-1") is not None
    with pytest.raises(ValueError, match="collection build is not writable"):
        await repository.replace_collection_references(
            "col_source",
            build_id,
            SourceReferenceSet(),
        )


async def test_collection_artifact_read_pins_one_active_build(
    source_repositories,
    monkeypatch,
) -> None:
    repository, builds = source_repositories
    first_task = _task("task_first_snapshot")
    await builds.add_task(first_task, build_id="build_first_snapshot")
    await repository.replace_collection_documents(
        "col_source", "build_first_snapshot", _artifacts("First")
    )
    await _finish(builds, first_task, success=True)

    second_task = _task("task_second_snapshot")
    second_build_id = "build_second_snapshot"
    await builds.add_task(second_task, build_id=second_build_id)
    await repository.replace_collection_documents(
        "col_source",
        second_build_id,
        (
            replace(
                _artifacts("Second")[0],
                figures=(_figure(second_build_id),),
            ),
        ),
    )
    original_list_text_units = repository.list_text_units

    async def activate_then_list_text_units(*args, **kwargs):
        await _finish(builds, second_task, success=True)
        return await original_list_text_units(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "list_text_units",
        activate_then_list_text_units,
    )

    artifacts = await repository.read_collection_documents("col_source")

    assert artifacts[0].title == "First"
    assert artifacts[0].figures == ()


async def test_document_tree_read_pins_one_active_build(
    source_repositories,
    monkeypatch,
) -> None:
    repository, builds = source_repositories
    first_task = _task("task_first_tree")
    await builds.add_task(first_task, build_id="build_first_tree")
    await repository.replace_collection_documents(
        "col_source", "build_first_tree", _artifacts("First")
    )
    await repository.replace_collection_references(
        "col_source", "build_first_tree", SourceReferenceSet()
    )
    await _finish(builds, first_task, success=True)

    second_task = _task("task_second_tree")
    second_build_id = "build_second_tree"
    await builds.add_task(second_task, build_id=second_build_id)
    await repository.replace_collection_documents(
        "col_source",
        second_build_id,
        (
            replace(
                _artifacts("Second")[0],
                figures=(_figure(second_build_id),),
            ),
        ),
    )
    await repository.replace_collection_references(
        "col_source", second_build_id, _references()
    )
    original_list_blocks = repository.list_blocks

    async def activate_then_list_blocks(*args, **kwargs):
        await _finish(builds, second_task, success=True)
        return await original_list_blocks(*args, **kwargs)

    monkeypatch.setattr(repository, "list_blocks", activate_then_list_blocks)

    tree = await repository.read_document_tree("col_source", "srcdoc_runtime")

    assert tree.node_for_source_ref("figure", "figure-1") is None
    assert tree.node_for_source_ref("reference", "reference-1") is None


async def test_source_repository_rejects_unresolved_document_and_orphan_links(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_invalid")
    await builds.add_task(task, build_id="build_invalid")
    document = _artifacts()[0]
    bad_document = replace(document, metadata={"source_path": "missing.pdf"})
    with pytest.raises(ValueError, match="exactly one collection document"):
        await repository.replace_collection_documents(
            "col_source",
            "build_invalid",
            (bad_document,),
        )
    assert await repository.read_collection_documents(
        "col_source", build_id="build_invalid"
    ) == ()
    orphan_text_unit = replace(
        document.text_units[0], document_ids=("missing-document",)
    )
    with pytest.raises(IntegrityError):
        await repository.replace_collection_documents(
            "col_source",
            "build_invalid",
            (replace(document, text_units=(orphan_text_unit,)),),
        )
    assert await repository.read_collection_documents(
        "col_source", build_id="build_invalid"
    ) == ()


async def test_source_repository_rejects_cross_document_and_orphan_reference_links(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_invalid_references")
    build_id = "build_invalid_references"
    await builds.add_task(task, build_id=build_id)
    await PostgresCollectionRepository(
        repository.session_factory
    ).add_documents(
        "col_source",
        (_collection_document("stored-other.pdf"),),
        updated_at=NOW,
    )
    first = _artifacts()
    first_document = first[0]
    second_document = replace(
        first_document,
        document_id="srcdoc_other",
        title="Other",
        metadata={"source_path": "stored-other.pdf", "source_parser": "docling"},
        text_units=(),
        blocks=(),
        tables=(),
        table_rows=(),
        table_cells=(),
        figures=(),
    )
    second_block = replace(
        first_document.blocks[0],
        block_id="block-other",
        document_id="srcdoc_other",
        text_unit_ids=(),
    )
    await repository.replace_collection_documents(
        "col_source",
        build_id,
        first + (replace(second_document, blocks=(second_block,)),),
    )
    references = _references()
    cross_document_mention = replace(
        references.mentions[0],
        document_id="srcdoc_other",
        source_block_id="block-other",
    )
    with pytest.raises(IntegrityError):
        await repository.replace_collection_references(
            "col_source",
            build_id,
            replace(references, mentions=(cross_document_mention,)),
        )
    with pytest.raises(IntegrityError):
        await repository.replace_collection_references(
            "col_source",
            build_id,
            SourceReferenceSet(
                resolutions=(references.resolutions[0],),
                candidates=(references.candidates[0],),
            ),
        )


async def test_postgresql_enforces_source_structure_contract(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_source")
    await builds.add_task(task, build_id="build_source")

    real_shape_artifacts = _real_shape_artifacts()
    await repository.replace_collection_documents(
        "col_source", "build_source", real_shape_artifacts
    )
    assert await repository.read_collection_documents(
        "col_source", build_id="build_source"
    ) == real_shape_artifacts

    unordered_references = _real_shape_references()
    unordered_references = replace(
        unordered_references,
        entries=(
            unordered_references.entries[0],
            replace(
                unordered_references.entries[0],
                reference_id="reference-null-index",
                raw_reference="Unnumbered reference.",
                reference_index=None,
                source_block_id=None,
            ),
        ),
        mentions=(
            unordered_references.mentions[0],
            replace(
                unordered_references.mentions[0],
                mention_id="mention-null-position",
                reference_id=None,
                citation_marker="[?]",
                source_block_id=None,
            ),
        ),
    )
    await repository.replace_collection_references(
        "col_source", "build_source", unordered_references
    )
    ordered_references = await repository.read_collection_references(
        "col_source", build_id="build_source"
    )
    assert [entry.reference_id for entry in ordered_references.entries] == [
        "reference-null-index",
        REAL_SOURCE_REFERENCE_ID,
    ]
    assert [mention.mention_id for mention in ordered_references.mentions] == [
        "mention-null-position",
        REAL_SOURCE_MENTION_ID,
    ]

    document = _artifacts()[0]
    orphan_block = replace(document.blocks[0], document_id="missing-document")
    with pytest.raises(IntegrityError):
        await repository.replace_collection_documents(
            "col_source",
            "build_source",
            (replace(document, blocks=(orphan_block,)),),
        )
    assert await repository.read_collection_documents(
        "col_source", build_id="build_source"
    ) == real_shape_artifacts

    await _finish(builds, task, success=True)
    with pytest.raises(ValueError, match="collection build is not writable"):
        await repository.replace_collection_documents(
            "col_source", "build_source", _artifacts("Rewritten")
        )
    assert (await repository.list_documents("col_source"))[0].title == "Paper"
