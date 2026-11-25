"""The shared Web resources keep startup and shutdown ownership explicit."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

import main
from infra.persistence import database as shared_database
from infra.persistence.file import workspace_files as workspace_module, object_store as store_module


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def resources(monkeypatch, tmp_path):
    events = []
    engine = SimpleNamespace(
        dispose=AsyncMock(side_effect=lambda: events.append("database"))
    )
    identity = SimpleNamespace(
        close=AsyncMock(side_effect=lambda: events.append("identity"))
    )
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "DatabaseSettings", Mock())
    monkeypatch.setattr(main, "build_database_engine", lambda _: engine)
    database_session = SimpleNamespace(execute=AsyncMock(return_value=Mock(all=lambda: [])))
    sessions = MagicMock()
    sessions.return_value.__aenter__.return_value = database_session
    monkeypatch.setattr(shared_database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(main.identity, "IdentityClient", lambda: identity)
    monkeypatch.setattr(
        "infra.llm.chat_model.AsyncOpenAI",
        Mock(side_effect=AssertionError("Web startup must not create a model client")),
    )
    return engine, identity, events


@pytest.mark.anyio
async def test_lifespan_initializes_shared_storage_without_opening_model_client(resources):
    engine, identity, events = resources
    for _ in range(2):
        async with main.lifespan():
            assert store_module.Store.root_dir == workspace_module.Workspace.root_dir
    assert events == ["identity", "database"] * 2
    assert engine.dispose.await_count == 2
    assert identity.close.await_count == 2
