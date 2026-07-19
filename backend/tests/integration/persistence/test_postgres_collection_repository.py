from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from domain.source import CollectionRecord
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)


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
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        command.upgrade(config, "head")

    sessions = build_session_factory(engine)
    auth_repository = PostgresAuthRepository(sessions)
    repository = PostgresCollectionRepository(sessions)
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
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
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        engine.dispose()
