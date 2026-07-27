from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import URL, create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from domain.source import (
    CollectionFileRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
    SourceArtifactSet,
    SourceBlock,
    SourceBoundingBox,
    SourceCharRange,
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
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.models.source import SourceDocument as SourceDocumentRow
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from tests.integration.persistence.database_cleanup import reset_postgres_schema


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


@pytest.fixture
def source_repositories(tmp_path):
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "source.sqlite"))
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    sessions = build_session_factory(engine)
    PostgresAuthRepository(sessions).add_user(
        {
            "user_id": "user_source",
            "email": "source@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
        }
    )
    collections = PostgresCollectionRepository(sessions)
    collections.add_collection(
        CollectionRecord(
            collection_id="col_source",
            owner_user_id="user_source",
            name="Source collection",
            description=None,
            status="idle",
            paper_count=0,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    collections.add_collection_import(
        _collection_import("stored-paper.pdf"), updated_at=NOW
    )
    try:
        yield (
            PostgresSourceArtifactRepository(sessions),
            PostgresBuildRepository(sessions),
        )
    finally:
        engine.dispose()


def _collection_import(stored_filename: str) -> CollectionImportRecord:
    digest = sha256(stored_filename.encode("utf-8")).hexdigest()
    suffix = digest[:12]
    file = CollectionFileRecord(
        file_id=f"file_{suffix}",
        collection_id="col_source",
        object_id=f"obj_{suffix}",
        object_kind="source_input",
        original_filename="paper.pdf",
        stored_filename=stored_filename,
        storage_key=f"col_source/input/{stored_filename}",
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=100,
        created_at=NOW,
    )
    return CollectionImportRecord(
        import_id=f"imp_{suffix}",
        collection_id="col_source",
        channel="upload",
        adapter_name="upload",
        adapter_version=None,
        raw_locator="paper.pdf",
        goal_context=None,
        warnings=(),
        ingested_at=NOW,
        documents=(
            CollectionImportDocumentRecord(
                source_document_id=f"srcdoc_{suffix}",
                origin_channel="upload",
                file=file,
                language=None,
                ingest_status="normalized",
                text_units=(),
            ),
        ),
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


def _artifacts(title: str = "Paper") -> SourceArtifactSet:
    bbox = SourceBoundingBox(l=1, t=2, r=3, b=4, coord_origin="top-left")
    return SourceArtifactSet(
        documents=(
            SourceDocument(
                document_id="srcdoc_runtime",
                human_readable_id=0,
                title=title,
                text="Methods\nResult",
                text_unit_ids=("tu-1",),
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
                human_readable_id=0,
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
                bbox=bbox,
                char_range=SourceCharRange(start=8, end=14),
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
                bbox=bbox,
                heading_path="Methods",
                column_headers=("Sample", "Value"),
                table_matrix=(("Sample", "Value"), ("A", "1")),
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
                bbox=bbox,
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
                header_path="Value",
                page=1,
                bbox=bbox,
                char_range=SourceCharRange(start=0, end=1),
                unit_hint="MPa",
            ),
        ),
    )


def _real_shape_artifacts() -> SourceArtifactSet:
    artifacts = _artifacts()
    return replace(
        artifacts,
        documents=(
            replace(
                artifacts.documents[0],
                document_id=REAL_SOURCE_DOCUMENT_ID,
                text_unit_ids=(REAL_SOURCE_TEXT_UNIT_ID,),
            ),
        ),
        text_units=(
            replace(
                artifacts.text_units[0],
                text_unit_id=REAL_SOURCE_TEXT_UNIT_ID,
                document_ids=(REAL_SOURCE_DOCUMENT_ID,),
            ),
        ),
        blocks=(
            replace(
                artifacts.blocks[0],
                block_id=REAL_SOURCE_BLOCK_ID,
                document_id=REAL_SOURCE_DOCUMENT_ID,
                text_unit_ids=(REAL_SOURCE_TEXT_UNIT_ID,),
            ),
        ),
        tables=(
            replace(
                artifacts.tables[0],
                table_id=REAL_SOURCE_TABLE_ID,
                document_id=REAL_SOURCE_DOCUMENT_ID,
                caption_block_id=REAL_SOURCE_BLOCK_ID,
            ),
        ),
        table_rows=(
            replace(
                artifacts.table_rows[0],
                row_id=REAL_SOURCE_ROW_ID,
                document_id=REAL_SOURCE_DOCUMENT_ID,
                table_id=REAL_SOURCE_TABLE_ID,
            ),
        ),
        table_cells=(
            replace(
                artifacts.table_cells[0],
                cell_id="c" * 128,
                document_id=REAL_SOURCE_DOCUMENT_ID,
                table_id=REAL_SOURCE_TABLE_ID,
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
        bbox=SourceBoundingBox(l=1, t=2, r=3, b=4, coord_origin="top-left"),
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
                char_start=13,
                char_end=16,
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


def _finish(
    builds: PostgresBuildRepository, task: TaskRecord, *, success: bool
) -> None:
    status = "completed" if success else "failed"
    builds.finish_build(
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


def test_source_repository_round_trips_structure_with_document_lineage(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_source")
    builds.add_task(task, build_id="build_source")

    repository.replace_collection_artifacts("col_source", "build_source", _artifacts())

    assert repository.read_collection_artifacts("col_source").is_empty()
    restored = repository.read_collection_artifacts(
        "col_source", build_id="build_source"
    )
    assert restored == _artifacts()
    tree = repository.read_document_tree(
        "col_source", "srcdoc_runtime", build_id="build_source"
    )
    assert tree.node_for_source_ref("block", "block-1") is not None
    assert tree.node_for_source_ref("table", "table-1") is not None

    with repository.session_factory() as session:
        row = session.scalar(select(SourceDocumentRow))
        assert row.collection_document_id.startswith("coldoc_")
        assert row.document_version_id.startswith("docver_")
        assert row.build_id == "build_source"


def test_default_reads_keep_last_successful_build_when_next_build_fails(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    first_task = _task("task_first")
    builds.add_task(first_task, build_id="build_first")
    repository.replace_collection_artifacts(
        "col_source", "build_first", _artifacts("First")
    )
    _finish(builds, first_task, success=True)
    with pytest.raises(ValueError, match="collection build is not writable"):
        repository.replace_collection_artifacts(
            "col_source", "build_first", _artifacts("Rewritten")
        )
    assert repository.list_documents("col_source")[0].title == "First"

    second_task = _task("task_second")
    builds.add_task(second_task, build_id="build_second")
    repository.replace_collection_artifacts(
        "col_source", "build_second", _artifacts("Pending")
    )

    assert repository.list_documents("col_source")[0].title == "First"
    assert (
        repository.list_documents("col_source", build_id="build_second")[0].title
        == "Pending"
    )
    _finish(builds, second_task, success=False)
    assert repository.list_documents("col_source")[0].title == "First"


def test_source_repository_versions_figures_and_references_with_the_source_build(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_source_media")
    build_id = "build_source_media"
    builds.add_task(task, build_id=build_id)
    artifacts = replace(_artifacts(), figures=(_figure(build_id),))

    repository.replace_collection_artifacts("col_source", build_id, artifacts)
    repository.replace_collection_references(
        "col_source",
        build_id,
        _references(),
    )

    assert repository.list_figures("col_source") == []
    assert repository.read_collection_references("col_source") == SourceReferenceSet()
    assert repository.list_figures("col_source", build_id=build_id) == [
        _figure(build_id)
    ]
    assert (
        repository.read_collection_references("col_source", build_id=build_id)
        == _references()
    )

    _finish(builds, task, success=True)

    assert repository.list_figures("col_source") == [_figure(build_id)]
    assert repository.read_collection_references("col_source") == _references()
    tree = repository.read_document_tree("col_source", "srcdoc_runtime")
    assert tree.node_for_source_ref("figure", "figure-1") is not None
    assert tree.node_for_source_ref("reference", "reference-1") is not None
    with pytest.raises(ValueError, match="collection build is not writable"):
        repository.replace_collection_references(
            "col_source",
            build_id,
            SourceReferenceSet(),
        )


def test_collection_artifact_read_pins_one_active_build(
    source_repositories,
    monkeypatch,
) -> None:
    repository, builds = source_repositories
    first_task = _task("task_first_snapshot")
    builds.add_task(first_task, build_id="build_first_snapshot")
    repository.replace_collection_artifacts(
        "col_source", "build_first_snapshot", _artifacts("First")
    )
    _finish(builds, first_task, success=True)

    second_task = _task("task_second_snapshot")
    second_build_id = "build_second_snapshot"
    builds.add_task(second_task, build_id=second_build_id)
    repository.replace_collection_artifacts(
        "col_source",
        second_build_id,
        replace(_artifacts("Second"), figures=(_figure(second_build_id),)),
    )
    original_list_text_units = repository.list_text_units

    def activate_then_list_text_units(*args, **kwargs):
        _finish(builds, second_task, success=True)
        return original_list_text_units(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "list_text_units",
        activate_then_list_text_units,
    )

    artifacts = repository.read_collection_artifacts("col_source")

    assert artifacts.documents[0].title == "First"
    assert artifacts.figures == ()


def test_document_tree_read_pins_one_active_build(
    source_repositories,
    monkeypatch,
) -> None:
    repository, builds = source_repositories
    first_task = _task("task_first_tree")
    builds.add_task(first_task, build_id="build_first_tree")
    repository.replace_collection_artifacts(
        "col_source", "build_first_tree", _artifacts("First")
    )
    repository.replace_collection_references(
        "col_source", "build_first_tree", SourceReferenceSet()
    )
    _finish(builds, first_task, success=True)

    second_task = _task("task_second_tree")
    second_build_id = "build_second_tree"
    builds.add_task(second_task, build_id=second_build_id)
    repository.replace_collection_artifacts(
        "col_source",
        second_build_id,
        replace(_artifacts("Second"), figures=(_figure(second_build_id),)),
    )
    repository.replace_collection_references(
        "col_source", second_build_id, _references()
    )
    original_list_blocks = repository.list_blocks

    def activate_then_list_blocks(*args, **kwargs):
        _finish(builds, second_task, success=True)
        return original_list_blocks(*args, **kwargs)

    monkeypatch.setattr(repository, "list_blocks", activate_then_list_blocks)

    tree = repository.read_document_tree("col_source", "srcdoc_runtime")

    assert tree.node_for_source_ref("figure", "figure-1") is None
    assert tree.node_for_source_ref("reference", "reference-1") is None


def test_source_repository_rejects_unresolved_document_and_orphan_links(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_invalid")
    builds.add_task(task, build_id="build_invalid")
    bad_document = replace(
        _artifacts().documents[0], metadata={"source_path": "missing.pdf"}
    )
    with pytest.raises(ValueError, match="exactly one collection file"):
        repository.replace_collection_artifacts(
            "col_source",
            "build_invalid",
            replace(_artifacts(), documents=(bad_document,)),
        )
    assert repository.read_collection_artifacts(
        "col_source", build_id="build_invalid"
    ).is_empty()
    orphan_text_unit = replace(
        _artifacts().text_units[0], document_ids=("missing-document",)
    )
    with pytest.raises(IntegrityError):
        repository.replace_collection_artifacts(
            "col_source",
            "build_invalid",
            replace(_artifacts(), text_units=(orphan_text_unit,)),
        )
    assert repository.read_collection_artifacts(
        "col_source", build_id="build_invalid"
    ).is_empty()


def test_source_repository_rejects_cross_document_and_orphan_reference_links(
    source_repositories,
) -> None:
    repository, builds = source_repositories
    task = _task("task_invalid_references")
    build_id = "build_invalid_references"
    builds.add_task(task, build_id=build_id)
    PostgresCollectionRepository(repository.session_factory).add_collection_import(
        _collection_import("stored-other.pdf"),
        updated_at=NOW,
    )
    first = _artifacts()
    second_document = replace(
        first.documents[0],
        document_id="srcdoc_other",
        title="Other",
        text_unit_ids=(),
        metadata={"source_path": "stored-other.pdf", "source_parser": "docling"},
    )
    second_block = replace(
        first.blocks[0],
        block_id="block-other",
        document_id="srcdoc_other",
        text_unit_ids=(),
    )
    repository.replace_collection_artifacts(
        "col_source",
        build_id,
        replace(
            first,
            documents=first.documents + (second_document,),
            blocks=first.blocks + (second_block,),
        ),
    )
    references = _references()
    cross_document_mention = replace(
        references.mentions[0],
        document_id="srcdoc_other",
        source_block_id="block-other",
    )
    with pytest.raises(IntegrityError):
        repository.replace_collection_references(
            "col_source",
            build_id,
            replace(references, mentions=(cross_document_mention,)),
        )
    with pytest.raises(IntegrityError):
        repository.replace_collection_references(
            "col_source",
            build_id,
            SourceReferenceSet(
                resolutions=(references.resolutions[0],),
                candidates=(references.candidates[0],),
            ),
        )


def test_postgresql_enforces_source_structure_contract() -> None:
    database_url = os.getenv("LENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("LENS_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not str(url.database).endswith(
        "_test"
    ):
        pytest.fail(
            "LENS_TEST_DATABASE_URL must use postgresql+psycopg and a *_test database"
        )

    engine = create_engine(url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        reset_postgres_schema(engine)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        sessions = build_session_factory(engine)
        PostgresAuthRepository(sessions).add_user(
            {
                "user_id": "user_source",
                "email": "source@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
            }
        )
        collections = PostgresCollectionRepository(sessions)
        collections.add_collection(
            CollectionRecord(
                collection_id="col_source",
                owner_user_id="user_source",
                name="Source collection",
                description=None,
                status="idle",
                paper_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        collections.add_collection_import(
            _collection_import("stored-paper.pdf"), updated_at=NOW
        )
        builds = PostgresBuildRepository(sessions)
        repository = PostgresSourceArtifactRepository(sessions)
        task = _task("task_source")
        builds.add_task(task, build_id="build_source")

        real_shape_artifacts = _real_shape_artifacts()
        repository.replace_collection_artifacts(
            "col_source", "build_source", real_shape_artifacts
        )
        assert (
            repository.read_collection_artifacts("col_source", build_id="build_source")
            == real_shape_artifacts
        )

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
                    char_start=None,
                    char_end=None,
                ),
            ),
        )
        repository.replace_collection_references(
            "col_source", "build_source", unordered_references
        )
        ordered_references = repository.read_collection_references(
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

        orphan_block = replace(_artifacts().blocks[0], document_id="missing-document")
        with pytest.raises(IntegrityError):
            repository.replace_collection_artifacts(
                "col_source",
                "build_source",
                replace(_artifacts(), blocks=(orphan_block,)),
            )
        assert (
            repository.read_collection_artifacts("col_source", build_id="build_source")
            == real_shape_artifacts
        )

        _finish(builds, task, success=True)
        with pytest.raises(ValueError, match="collection build is not writable"):
            repository.replace_collection_artifacts(
                "col_source", "build_source", _artifacts("Rewritten")
            )
        assert repository.list_documents("col_source")[0].title == "Paper"
    finally:
        reset_postgres_schema(engine)
        engine.dispose()
