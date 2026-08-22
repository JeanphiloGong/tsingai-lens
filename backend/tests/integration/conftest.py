from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from tests.integration.persistence.database_cleanup import reset_postgres_schema


BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def postgres_sync_engine():
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
    try:
        yield engine
    finally:
        reset_postgres_schema(engine)
        engine.dispose()


@pytest.fixture
async def postgres_session_factory(postgres_sync_engine):
    del postgres_sync_engine
    database_url = os.environ["LENS_TEST_DATABASE_URL"]
    engine = build_database_engine(DatabaseSettings(database_url=database_url))
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()
