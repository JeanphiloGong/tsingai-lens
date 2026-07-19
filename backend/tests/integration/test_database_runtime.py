from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Barrier

from pydantic import ValidationError
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, func
from sqlalchemy import insert, select

from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_config_import_is_silent() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""


def test_database_settings_requires_database_url(monkeypatch) -> None:
    monkeypatch.delenv("LENS_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        DatabaseSettings(_env_file=None)


@pytest.mark.parametrize(
    ("database_url", "message"),
    [
        ("not a database URL", "valid SQLAlchemy URL"),
        ("sqlite+pysqlite:///:memory:", "postgresql\\+psycopg"),
        ("postgresql+psycopg://localhost", "database name"),
    ],
)
def test_database_engine_rejects_invalid_configuration(
    database_url: str,
    message: str,
) -> None:
    settings = DatabaseSettings(database_url=database_url, _env_file=None)

    with pytest.raises(ValueError, match=message):
        build_database_engine(settings)


def test_database_engine_uses_sync_psycopg_and_masks_credentials() -> None:
    sensitive_value = "synthetic-sensitive-value"
    settings = DatabaseSettings(
        database_url=(
            f"postgresql+psycopg://lens:{sensitive_value}@localhost/lens_test"
        ),
        _env_file=None,
    )

    engine = build_database_engine(settings)
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
        assert sensitive_value not in repr(settings)
        assert sensitive_value not in str(engine.url)
    finally:
        engine.dispose()


def test_session_factory_commits_successful_transaction(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'commit.sqlite'}")
    metadata = MetaData()
    records = Table(
        "records",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("value", String, nullable=False),
    )
    metadata.create_all(engine)
    sessions = build_session_factory(engine)

    with sessions.begin() as session:
        session.execute(insert(records).values(id=1, value="committed"))

    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(records)) == 1
    engine.dispose()


def test_session_factory_rolls_back_failed_transaction(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'rollback.sqlite'}")
    metadata = MetaData()
    records = Table(
        "records",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("value", String, nullable=False),
    )
    metadata.create_all(engine)
    sessions = build_session_factory(engine)

    with pytest.raises(RuntimeError, match="rollback"):
        with sessions.begin() as session:
            session.execute(insert(records).values(id=1, value="discarded"))
            raise RuntimeError("force rollback")

    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(records)) == 0
    engine.dispose()


def test_session_factory_creates_one_session_per_thread() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = build_session_factory(engine)
    barrier = Barrier(2)

    def open_session() -> int:
        with sessions() as session:
            barrier.wait(timeout=5)
            return id(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(open_session),
            executor.submit(open_session),
        )
        session_ids = [future.result() for future in futures]

    assert len(set(session_ids)) == 2
    engine.dispose()
