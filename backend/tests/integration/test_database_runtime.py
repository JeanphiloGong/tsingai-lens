from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys

from pydantic import ValidationError
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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


@pytest.mark.anyio
async def test_database_engine_uses_async_psycopg_and_masks_credentials() -> None:
    sensitive_value = "synthetic-sensitive-value"
    settings = DatabaseSettings(
        database_url=(
            f"postgresql+psycopg://lens:{sensitive_value}@localhost/lens_test"
        ),
        _env_file=None,
    )

    engine = build_database_engine(settings)
    try:
        assert isinstance(engine, AsyncEngine)
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
        assert engine.dialect.is_async is True
        assert sensitive_value not in repr(settings)
        assert sensitive_value not in str(engine.url)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_session_factory_creates_one_async_session_per_task() -> None:
    settings = DatabaseSettings(
        database_url="postgresql+psycopg://lens:secret@localhost/lens_test",
        _env_file=None,
    )
    engine = build_database_engine(settings)
    sessions = build_session_factory(engine)

    async def open_session() -> AsyncSession:
        session = sessions()
        await asyncio.sleep(0)
        return session

    first, second = await asyncio.gather(open_session(), open_session())
    try:
        assert isinstance(sessions, async_sessionmaker)
        assert isinstance(first, AsyncSession)
        assert isinstance(second, AsyncSession)
        assert first is not second
    finally:
        for session in (first, second):
            await session.close()
        await engine.dispose()
