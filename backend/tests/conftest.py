from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _patch_core_llm_extractor(monkeypatch):
    from application.core import comparison_service
    from application.core.semantic_build import (
        document_profile_service,
        paper_facts_service,
        research_objective_service,
    )
    from tests.support.fake_core_llm_extractor import FakeCoreLLMStructuredExtractor

    fake = FakeCoreLLMStructuredExtractor()
    monkeypatch.setattr(
        document_profile_service,
        "build_default_core_llm_structured_extractor",
        lambda: fake,
    )
    monkeypatch.setattr(
        paper_facts_service,
        "build_default_core_llm_structured_extractor",
        lambda: fake,
    )
    monkeypatch.setattr(
        research_objective_service,
        "build_default_core_llm_structured_extractor",
        lambda: fake,
    )


@pytest.fixture
def auth_session_service(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import URL, create_engine

    from application.auth import AuthSessionService
    from infra.persistence.database import build_session_factory
    from infra.persistence.postgres.auth_repository import PostgresAuthRepository

    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "auth.sqlite"),
        ),
        connect_args={"check_same_thread": False},
    )
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    service = AuthSessionService(PostgresAuthRepository(build_session_factory(engine)))
    try:
        yield service
    finally:
        engine.dispose()
