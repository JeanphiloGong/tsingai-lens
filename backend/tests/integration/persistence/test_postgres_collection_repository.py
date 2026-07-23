from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from domain.source import (
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
)
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from tests.integration.persistence.database_cleanup import reset_postgres_schema
from infra.persistence.postgres.models.collection import StoredObject


BACKEND_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def collection_repository(tmp_path):
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "collections.sqlite"),
        )
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    sessions = build_session_factory(engine)
    auth_repository = PostgresAuthRepository(sessions)
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    for user_id in ("user_a", "user_b"):
        auth_repository.add_user(
            {
                "user_id": user_id,
                "email": f"{user_id}@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": now.isoformat(),
            }
        )

    try:
        yield PostgresCollectionRepository(sessions)
    finally:
        engine.dispose()


def _collection(
    collection_id: str,
    owner_user_id: str = "user_a",
    *,
    paper_count: int = 0,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> CollectionRecord:
    created = created_at or datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)
    updated = updated_at or created
    return CollectionRecord(
        collection_id=collection_id,
        owner_user_id=owner_user_id,
        name=f"Collection {collection_id}",
        description=None,
        status="idle",
        paper_count=paper_count,
        created_at=created.isoformat(),
        updated_at=updated.isoformat(),
    )


def _collection_import(
    collection_id: str,
    suffix: str,
    *,
    ingested_at: str,
) -> CollectionImportRecord:
    file_record = CollectionFileRecord(
        file_id=f"file_{suffix}",
        collection_id=collection_id,
        object_id=f"obj_{suffix}",
        object_kind="source_input",
        original_filename=f"{suffix}.pdf",
        stored_filename=f"stored-{suffix}.pdf",
        storage_key=f"{collection_id}/input/stored-{suffix}.pdf",
        sha256=sha256(suffix.encode("utf-8")).hexdigest(),
        media_type="application/pdf",
        status="stored",
        size_bytes=len(suffix),
        created_at=ingested_at,
    )
    return CollectionImportRecord(
        import_id=f"imp_{suffix}",
        collection_id=collection_id,
        channel="search",
        adapter_name="fixture",
        adapter_version="1.0",
        raw_locator=f"doi:{suffix}",
        goal_context={"intent": "compare", "suffix": suffix},
        warnings=(f"warning_{suffix}",),
        ingested_at=ingested_at,
        documents=(
            CollectionImportDocumentRecord(
                source_document_id=f"srcdoc_{suffix}",
                origin_channel="search",
                file=file_record,
                language="en",
                ingest_status="normalized",
                text_units=(
                    {
                        "text_unit_id": f"tu_{suffix}",
                        "sequence": 0,
                        "page_ref": "1",
                        "char_count": len(suffix),
                    },
                ),
            ),
        ),
    )


def test_collection_repository_round_trips_and_orders_owner_records(
    collection_repository,
) -> None:
    collection_repository.add_collection(_collection("col_z"))
    collection_repository.add_collection(_collection("col_a"))
    collection_repository.add_collection(_collection("col_b", "user_b"))

    assert collection_repository.read_collection("col_z") == _collection("col_z")
    assert [
        record.collection_id
        for record in collection_repository.list_collections("user_a")
    ] == ["col_a", "col_z"]
    assert [
        record.collection_id for record in collection_repository.list_collections()
    ] == ["col_a", "col_b", "col_z"]


def test_collection_repository_updates_and_deletes_existing_record(
    collection_repository,
) -> None:
    record = _collection("col_update")
    collection_repository.add_collection(record)
    updated = CollectionRecord(
        **{
            **record.to_record(),
            "name": "Updated collection",
            "status": "completed",
            "paper_count": 2,
            "updated_at": "2026-07-19T09:00:00+00:00",
        }
    )

    assert collection_repository.update_collection(updated) is True
    assert collection_repository.read_collection("col_update") == updated
    assert collection_repository.delete_collection("col_update") is True
    assert collection_repository.read_collection("col_update") is None
    assert collection_repository.update_collection(updated) is False
    assert collection_repository.delete_collection("col_update") is False


@pytest.mark.parametrize(
    "record",
    [
        _collection("col_orphan", "user_missing"),
        _collection("col_negative", paper_count=-1),
        _collection(
            "col_time",
            created_at=datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_collection_repository_rejects_invalid_relational_records(
    collection_repository,
    record: CollectionRecord,
) -> None:
    with pytest.raises(IntegrityError):
        collection_repository.add_collection(record)


def test_collection_repository_rejects_duplicate_identity(
    collection_repository,
) -> None:
    record = _collection("col_duplicate")
    collection_repository.add_collection(record)

    with pytest.raises(IntegrityError):
        collection_repository.add_collection(record)


def test_collection_repository_round_trips_ordered_file_provenance_and_handoffs(
    collection_repository,
) -> None:
    collection_id = "col_provenance"
    collection_repository.add_collection(_collection(collection_id))
    second = _collection_import(
        collection_id,
        "second",
        ingested_at="2026-07-19T08:02:00+00:00",
    )
    first = _collection_import(
        collection_id,
        "first",
        ingested_at="2026-07-19T08:01:00+00:00",
    )
    later_handoff = CollectionHandoffRecord(
        handoff_id="handoff_z",
        collection_id=collection_id,
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T08:04:00+00:00",
        source_channels=("upload", "search"),
        goal_context={"research_brief": {"intent": "compare"}},
    )
    earlier_handoff = CollectionHandoffRecord(
        handoff_id="handoff_a",
        collection_id=collection_id,
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T08:03:00+00:00",
        source_channels=("upload",),
        goal_context={"research_brief": {"intent": "review"}},
    )

    collection_repository.add_collection_import(
        second,
        updated_at="2026-07-19T08:02:00+00:00",
    )
    collection_repository.add_collection_import(
        first,
        updated_at="2026-07-19T08:03:00+00:00",
    )
    collection_repository.add_collection_handoff(later_handoff)
    collection_repository.add_collection_handoff(earlier_handoff)

    assert collection_repository.list_collection_files(collection_id) == (
        second.documents[0].file,
        first.documents[0].file,
    )
    assert collection_repository.list_collection_imports(collection_id) == (
        second,
        first,
    )
    assert collection_repository.list_collection_handoffs(collection_id) == (
        later_handoff,
        earlier_handoff,
    )
    stored_collection = collection_repository.read_collection(collection_id)
    assert stored_collection is not None
    assert stored_collection.paper_count == 2
    assert stored_collection.status == "ready"
    assert stored_collection.updated_at == "2026-07-19T08:03:00+00:00"


def test_collection_import_rolls_back_all_state_for_invalid_object_integrity(
    collection_repository,
) -> None:
    collection_id = "col_invalid_object"
    original_collection = _collection(collection_id)
    collection_repository.add_collection(original_collection)
    import_record = _collection_import(
        collection_id,
        "invalid",
        ingested_at="2026-07-19T08:01:00+00:00",
    )
    invalid_file = replace(import_record.documents[0].file, sha256="A" * 64)
    invalid_import = replace(
        import_record,
        documents=(replace(import_record.documents[0], file=invalid_file),),
    )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        collection_repository.add_collection_import(
            invalid_import,
            updated_at="2026-07-19T08:02:00+00:00",
        )

    assert collection_repository.list_collection_files(collection_id) == ()
    assert collection_repository.list_collection_imports(collection_id) == ()
    assert collection_repository.read_collection(collection_id) == original_collection


def test_collection_delete_removes_file_provenance_and_object_metadata(
    collection_repository,
) -> None:
    collection_id = "col_delete_provenance"
    collection_repository.add_collection(_collection(collection_id))
    import_record = _collection_import(
        collection_id,
        "delete",
        ingested_at="2026-07-19T08:01:00+00:00",
    )
    handoff = CollectionHandoffRecord(
        handoff_id="handoff_delete",
        collection_id=collection_id,
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T08:02:00+00:00",
        source_channels=("upload",),
        goal_context={"research_brief": {"intent": "compare"}},
    )
    collection_repository.add_collection_import(
        import_record,
        updated_at="2026-07-19T08:01:00+00:00",
    )
    collection_repository.add_collection_handoff(handoff)

    assert collection_repository.delete_collection(collection_id) is True

    assert collection_repository.read_collection(collection_id) is None
    assert collection_repository.list_collection_files(collection_id) == ()
    assert collection_repository.list_collection_imports(collection_id) == ()
    assert collection_repository.list_collection_handoffs(collection_id) == ()
    with collection_repository.session_factory() as session:
        assert (
            session.get(StoredObject, import_record.documents[0].file.object_id) is None
        )


def test_postgresql_enforces_collection_contract() -> None:
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
    reset_postgres_schema(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    sessions = build_session_factory(engine)
    auth_repository = PostgresAuthRepository(sessions)
    repository = PostgresCollectionRepository(sessions)
    now = datetime(2026, 7, 19, 9, tzinfo=timezone.utc)
    try:
        auth_repository.add_user(
            {
                "user_id": "user_constraints",
                "email": "collection-constraints@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": now.isoformat(),
            }
        )
        repository.add_collection(_collection("col_constraints", "user_constraints"))

        with pytest.raises(IntegrityError):
            repository.add_collection(_collection("col_orphan_pg", "user_missing"))
        with pytest.raises(IntegrityError):
            repository.add_collection(
                _collection("col_negative_pg", "user_constraints", paper_count=-1)
            )
        with pytest.raises(IntegrityError):
            repository.add_collection(
                _collection(
                    "col_time_pg",
                    "user_constraints",
                    created_at=now,
                    updated_at=now - timedelta(seconds=1),
                )
            )

        import_record = _collection_import(
            "col_constraints",
            "postgres",
            ingested_at=now.isoformat(),
        )
        repository.add_collection_import(
            import_record,
            updated_at=now.isoformat(),
        )
        assert repository.list_collection_imports("col_constraints") == (import_record,)

        invalid_import = _collection_import(
            "col_constraints",
            "invalid-postgres",
            ingested_at=now.isoformat(),
        )
        invalid_file = replace(
            invalid_import.documents[0].file,
            sha256="A" * 64,
        )
        invalid_import = replace(
            invalid_import,
            documents=(replace(invalid_import.documents[0], file=invalid_file),),
        )
        with pytest.raises(ValueError, match="lowercase SHA-256"):
            repository.add_collection_import(
                invalid_import,
                updated_at=now.isoformat(),
            )
    finally:
        reset_postgres_schema(engine)
        engine.dispose()
