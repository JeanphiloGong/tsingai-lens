"""The shared Web resources keep startup and shutdown ownership explicit."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import main
from application.chat import session_service as shared_chat_service
from infra.persistence import database as shared_database
from infra.persistence.file import collection_workspace as workspace_module, object_store as store_module


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
    monkeypatch.setattr(shared_database, "AsyncSessionLocal", Mock())
    monkeypatch.setattr(main.identity, "IdentityClient", lambda: identity)
    monkeypatch.setattr(
        "infra.llm.chat_model.AsyncOpenAI",
        Mock(side_effect=AssertionError("Web startup must not create a model client")),
    )
    return engine, identity, events


@pytest.mark.anyio
async def test_lifespan_starts_without_model_and_cancels_chat_before_shutdown(resources):
    engine, identity, events = resources
    previous = None
    for _ in range(2):
        async with main.lifespan():
            service = shared_chat_service.ChatService
            assert service is not previous
            assert store_module.Store.root_dir == workspace_module.Workspace.root_dir

            async def active_turn():
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append("turn")

            task = asyncio.create_task(active_turn())
            service._active_stream_tasks.add(task)
            await asyncio.sleep(0)
        assert task.cancelled()
        previous = service
    assert events == ["turn", "identity", "database"] * 2
    assert engine.dispose.await_count == 2
    assert identity.close.await_count == 2


@pytest.mark.anyio
async def test_chat_startup_failure_closes_created_resources(resources, monkeypatch):
    engine, identity, events = resources
    monkeypatch.setattr(
        shared_chat_service,
        "ChatSessionService",
        Mock(side_effect=RuntimeError("chat startup failed")),
    )
    with pytest.raises(RuntimeError, match="chat startup failed"):
        async with main.lifespan():
            pytest.fail("failed startup must not serve requests")
    assert events == ["identity", "database"]
    identity.close.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.anyio
async def test_chat_shutdown_failure_still_closes_identity_and_database(resources, monkeypatch):
    _, _, events = resources
    service = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("chat close failed")))
    monkeypatch.setattr(shared_chat_service, "ChatSessionService", lambda **_: service)
    with pytest.raises(RuntimeError, match="chat close failed"):
        async with main.lifespan():
            assert shared_chat_service.ChatService is service
    assert events == ["identity", "database"]
