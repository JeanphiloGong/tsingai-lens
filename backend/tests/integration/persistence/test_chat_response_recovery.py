from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import socket

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import AsyncClient
import pytest
from sqlalchemy import inspect, text
import uvicorn

from application.auth.session_service import AuthSessionService, SESSION_COOKIE_NAME
from application.chat import CapabilityRegistry, ResearchAgentRunner
from application.chat.session_service import ChatSessionService
from controllers.chat.sessions import router
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from tests.integration.persistence.test_chat_branches import branch_app  # noqa: F401
from tests.unit.application.test_chat_session_service import _PausedResponseModel

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _server(service, auth):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.chat_session_service = service
    app.state.auth_session_service = auth
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 5)


async def _events(response):
    event = ""
    async for line in response.aiter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            yield event, json.loads(line[6:])


async def test_real_http_disconnect_resumes_on_another_worker_without_duplicate_generation(branch_app):
    fixture = branch_app
    model = _PausedResponseModel()
    writer = fixture.service
    writer.runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()))
    reader = ChatSessionService(
        collection_service=writer.collection_service,
        source_artifact_repository=writer.source_artifact_repository,
        repository=PostgresChatRepository(fixture.factory), runner=writer.runner,
    )
    auth = AuthSessionService(PostgresAuthRepository(fixture.factory))
    cookies = {SESSION_COOKIE_NAME: fixture.cookies[0]}
    try:
        async with _server(writer, auth) as first_url, _server(reader, auth) as second_url:
            async with AsyncClient(base_url=first_url, cookies=cookies, timeout=10) as first, AsyncClient(base_url=second_url, cookies=cookies, timeout=10) as second:
                created = await first.post("/api/v1/chat-sessions", json={"collection_id": "collection"})
                assert created.status_code == 201, created.text
                session_id = created.json()["session_id"]
                path = f"/api/v1/chat-sessions/{session_id}"
                async with first.stream("POST", f"{path}/messages", headers={"Accept": "text/event-stream"}, json={
                    "message": "Before comparing LPBF tensile results, explain which conditions to match. Do not use tools.",
                }) as response:
                    assert response.status_code == 200
                    async for event, payload in _events(response):
                        if event == "text_delta":
                            assert payload["content"] == model.first
                            break
                async with asyncio.timeout(5):
                    while True:
                        saved = (await second.get(f"{path}/messages")).json()
                        if saved["response"]["content"] == model.first:
                            break
                        await asyncio.sleep(0.01)
                snapshot = saved["response"]
                assert saved["running"] and len(saved["items"]) == 1
                assert snapshot["content"].endswith(" ")
                busy = await second.post(f"{path}/messages", headers={"Accept": "text/event-stream"}, json={"message": "Repeat"})
                assert busy.status_code == 409
                async with second.stream("GET", f"{path}/events", params={"response_id": snapshot["response_id"]}) as response:
                    assert response.status_code == 200
                    events = _events(response)
                    event, initial = await anext(events)
                    assert event == "trajectory" and initial["response"]["content"] == model.first
                    model.continue_response.set()
                    event, update = await anext(events)
                    assert event == "snapshot"
                    assert update["message_id"] == snapshot["message_id"]
                    assert update["content"] == model.first + model.second
                    assert update["sequence"] > snapshot["sequence"]
                    model.finish_response.set()
                    final = [item async for item in events][-1][1]
                assert final["response"]["status"] == "completed"
                assert final["items"][-1]["message_id"] == snapshot["message_id"]
                assert final["items"][-1]["content"] == model.first + model.second
                assert len(final["items"]) == 2 and model.calls == 1
                second.cookies.clear()
                assert (await second.get(f"{path}/events", params={"response_id": snapshot["response_id"]})).status_code == 401
                second.cookies.set(SESSION_COOKIE_NAME, fixture.cookies[1])
                assert (await second.get(f"{path}/events", params={"response_id": snapshot["response_id"]})).status_code == 404
    finally:
        model.continue_response.set()
        model.finish_response.set()
        await asyncio.gather(*writer._active_stream_tasks, return_exceptions=True)


async def test_snapshot_migration_preserves_saved_conversations(branch_app, postgres_sync_engine):
    before = await branch_app.repository.read_messages("original")
    config = Config("alembic.ini")
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "20260909_0057")
        assert "response_snapshot" not in {column["name"] for column in inspect(connection).get_columns("chat_sessions")}
        command.upgrade(config, "head")
        assert "response_snapshot" in {column["name"] for column in inspect(connection).get_columns("chat_sessions")}
        assert connection.scalar(text("SELECT count(*) FROM chat_messages WHERE session_id = 'original'")) == len(before)
    assert await branch_app.repository.read_messages("original") == before
