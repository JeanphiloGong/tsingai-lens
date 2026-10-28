from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.persistence.postgres.models.auth import AuthUser
from tests.integration.persistence.database_cleanup import reset_postgres_schema


@pytest.fixture
def postgres_sync_engine():
    database_url = os.getenv("LENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("LENS_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not str(url.database).endswith("_test"):
        pytest.fail("LENS_TEST_DATABASE_URL must use postgresql+psycopg and a *_test database")

    engine = create_engine(url)
    config = Config(str(ROOT / "alembic.ini"))
    reset_postgres_schema(engine)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        reset_postgres_schema(engine)
        engine.dispose()


@pytest.fixture
def postgres_session_factory(postgres_sync_engine, monkeypatch):
    # TestClient and asyncio.run may use different loops within the same test.
    engine = create_async_engine(postgres_sync_engine.url, poolclass=NullPool)
    with postgres_sync_engine.begin() as connection:
        connection.execute(insert(AuthUser).values(
            user_id="local-user", email="local-fixture@example.com",
            password_hash="!", created_at=datetime.now(timezone.utc),
        ))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr("repositories.feedback_dataset_repository.AsyncSessionLocal", factory)
        monkeypatch.setattr("repositories.collection_repository.AsyncSessionLocal", factory)
        monkeypatch.setattr("repositories.auth_repository.AsyncSessionLocal", factory)
        yield factory
    finally:
        engine.sync_engine.dispose()


@pytest.fixture(autouse=True)
def _patch_domain_model_extractors(monkeypatch):
    from application.core.document_profiles import (
        service as document_profile_service,
    )
    from application.core.objectives import objective_input_service
    from tests.support.fake_domain_model_extractor import FakeDomainModelExtractor

    fake = FakeDomainModelExtractor()
    monkeypatch.setattr(
        document_profile_service,
        "build_default_document_profile_extractor",
        lambda: fake,
    )
    monkeypatch.setattr(
        objective_input_service,
        "build_default_structured_response_client",
        lambda: fake,
    )


@pytest.fixture
def auth_session_service(postgres_session_factory):
    from application.auth import AuthSessionService
    from repositories.auth_repository import AuthRepository

    return AuthSessionService(AuthRepository())


@pytest.fixture
def collection_service(tmp_path, postgres_session_factory):
    from application.source.collection_service import CollectionService
    from infra.persistence.file import FileCollectionWorkspace
    from repositories.collection_repository import CollectionRepository

    return CollectionService(
        repository=CollectionRepository(),
        workspace=FileCollectionWorkspace(tmp_path / "collections"),
    )
