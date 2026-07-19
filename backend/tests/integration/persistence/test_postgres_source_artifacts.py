from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import URL, create_engine, event, select
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


BACKEND_ROOT = Path(__file__).resolve().parents[3]
NOW = "2026-07-19T10:00:00+00:00"


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
    file = CollectionFileRecord(
        file_id="file_source",
        collection_id="col_source",
        object_id="obj_source",
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
        import_id="imp_source",
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
                source_document_id="srcdoc_import",
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
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
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

        repository.replace_collection_artifacts(
            "col_source", "build_source", _artifacts()
        )
        assert (
            repository.read_collection_artifacts("col_source", build_id="build_source")
            == _artifacts()
        )

        orphan_block = replace(_artifacts().blocks[0], document_id="missing-document")
        with pytest.raises(IntegrityError):
            repository.replace_collection_artifacts(
                "col_source",
                "build_source",
                replace(_artifacts(), blocks=(orphan_block,)),
            )
        assert (
            repository.read_collection_artifacts("col_source", build_id="build_source")
            == _artifacts()
        )

        _finish(builds, task, success=True)
        with pytest.raises(ValueError, match="collection build is not writable"):
            repository.replace_collection_artifacts(
                "col_source", "build_source", _artifacts("Rewritten")
            )
        assert repository.list_documents("col_source")[0].title == "Paper"
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        engine.dispose()
