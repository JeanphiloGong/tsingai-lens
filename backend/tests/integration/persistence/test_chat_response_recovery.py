from __future__ import annotations

from exceptions import ProjectException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from controllers.exception_router import project_exception_handler, http_exception_handler, request_validation_handler, general_exception_handler

import asyncio
import json
import multiprocessing
import os
import socket
from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest
import uvicorn
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from application.auth import session_service as auth_session_service
from application.auth.session_service import SESSION_COOKIE_NAME
from application.chat import CapabilityRegistry, ModelTurn, ResearchAgentRunner
from application.chat import session_service as chat_session_service
from controllers.chat.chat_session_routes import chat_session_router as router
from fastapi import FastAPI
from httpx import AsyncClient
from repositories.auth_repository import AuthRepository
from repositories.chat_repository import ChatRepository
from sqlalchemy import inspect, text
from tests.integration.persistence.test_chat_branches import branch_app  # noqa: F401
from tests.unit.application.test_chat_session_service import _PausedResponseModel

pytestmark = pytest.mark.anyio


class _ProcessPausedModel:
    first = _PausedResponseModel.first
    second = _PausedResponseModel.second

    def __init__(self, resume, finish, calls):
        self.resume = resume
        self.finish = finish
        self.calls = calls

    async def respond(self, *, text_delta_callback=None, **kwargs):
        with self.calls.get_lock():
            self.calls.value += 1
        text_delta_callback(self.first)
        while not self.resume.is_set():
            await asyncio.sleep(0.01)
        text_delta_callback(self.second)
        while not self.finish.is_set():
            await asyncio.sleep(0.01)
        return ModelTurn(content=self.first + self.second)


def _worker(database_url, listener, ready, stop, resume, finish, calls, active_tasks, sources):
    """Bind a fresh module graph and database factory in each spawned worker."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from repositories import auth_repository, chat_repository, collection_repository
    from application.source import collection_service
    from controllers.exception_router import project_exception_handler
    from exceptions import ProjectException

    async def serve():
        engine = create_async_engine(database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_repository.AsyncSessionLocal = factory
        chat_repository.AsyncSessionLocal = factory
        collection_repository.AsyncSessionLocal = factory
        auth_session_service.AuthRepo = AuthRepository()
        collection_service.CollectionRepo = collection_repository.CollectionRepository()
        chat_session_service.collection_service = collection_service
        chat_session_service.SourceArtifactRepo = sources
        chat_session_service.ChatRepo = ChatRepository()
        runner = ResearchAgentRunner(
            model=_ProcessPausedModel(resume, finish, calls), capabilities=CapabilityRegistry(()),
        )
        service = chat_session_service.ChatSessionService(runner=runner)
        app = FastAPI()
        app.state.runtime = SimpleNamespace(chat_session_service=service)
        app.add_exception_handler(ProjectException, project_exception_handler)
        app.include_router(router, prefix="/api/v1")
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("worker stopped before accepting requests")
                    await asyncio.sleep(0.01)
            ready.send(os.getpid())
            while not stop.is_set() and not task.done():
                await asyncio.sleep(0.01)
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(task, 10)
                await asyncio.wait_for(
                    asyncio.gather(*service._active_stream_tasks), 10,
                )
                active_tasks.value = len(service._active_stream_tasks)
            finally:
                await engine.dispose()
                ready.close()
                listener.close()

    asyncio.run(serve())


@asynccontextmanager
async def _server(database_url, resume, finish, calls, sources):
    process_context = multiprocessing.get_context("spawn")
    stop = process_context.Event()
    active_tasks = process_context.Value("i", -1)
    receive, send = process_context.Pipe(duplex=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        process = process_context.Process(target=_worker, args=(
            database_url, listener, send, stop, resume, finish, calls, active_tasks, sources,
        ))
        process.start()
        send.close()
        try:
            async with asyncio.timeout(20):
                while not receive.poll():
                    assert process.is_alive(), f"worker exited with {process.exitcode}"
                    await asyncio.sleep(0.01)
            pid = receive.recv()
            assert pid == process.pid
            yield f"http://127.0.0.1:{listener.getsockname()[1]}", pid
        finally:
            resume.set()
            finish.set()
            stop.set()
            await asyncio.to_thread(process.join, 15)
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 5)
            receive.close()
            assert process.exitcode == 0, f"worker {process.pid} did not shut down cleanly"
            assert active_tasks.value == 0
            process.close()


async def _events(response):
    event = ""
    async for line in response.aiter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            yield event, json.loads(line[6:])


async def test_real_http_disconnect_resumes_on_another_worker_without_duplicate_generation(branch_app):
    fixture = branch_app
    process_context = multiprocessing.get_context("spawn")
    resume, finish = process_context.Event(), process_context.Event()
    calls = process_context.Value("i", 0)
    database_url = fixture.factory.kw["bind"].url.render_as_string(hide_password=False)
    cookies = {SESSION_COOKIE_NAME: fixture.cookies[0]}
    async with (
        _server(database_url, resume, finish, calls, fixture.sources) as (first_url, writer_pid),
        _server(database_url, resume, finish, calls, fixture.sources) as (second_url, reader_pid),
    ):
        assert writer_pid != reader_pid
        assert os.getpid() not in (writer_pid, reader_pid)
        async with (
            AsyncClient(base_url=first_url, cookies=cookies, timeout=15) as first,
            AsyncClient(base_url=second_url, cookies=cookies, timeout=15) as second,
        ):
            created = await first.post("/api/v1/chat-sessions", json={"collection_id": "collection"})
            assert created.status_code == 200 and created.json()["code"] == 200, created.text
            session_id = created.json()["data"]["session_id"]
            path = f"/api/v1/chat-sessions/{session_id}"
            async with first.stream("POST", f"{path}/messages", headers={"Accept": "text/event-stream"}, json={
                "message": "Before comparing LPBF tensile results, explain which conditions to match. Do not use tools.",
            }) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                async for event, payload in _events(response):
                    if event == "text_delta":
                        assert payload["content"] == _ProcessPausedModel.first
                        break
            async with asyncio.timeout(10):
                while True:
                    response = await second.get(f"{path}/messages")
                    assert response.json()["code"] == 200, response.text
                    saved = response.json()["data"]
                    if saved["response"]["content"] == _ProcessPausedModel.first:
                        break
                    await asyncio.sleep(0.02)
            snapshot = saved["response"]
            assert saved["running"] and len(saved["items"]) == 1
            assert snapshot["content"].endswith(" ")
            busy = await second.post(f"{path}/messages", headers={"Accept": "text/event-stream"}, json={"message": "Repeat"})
            assert busy.json()["code"] == 200204
            assert busy.json()["data"]["code"] == "chat_session_busy"
            async with second.stream("GET", f"{path}/events", params={"response_id": snapshot["response_id"]}) as response:
                assert response.status_code == 200
                events = _events(response)
                event, initial = await anext(events)
                assert event == "trajectory" and initial["response"]["content"] == _ProcessPausedModel.first
                resume.set()
                async with asyncio.timeout(10):
                    async for event, update in events:
                        if event == "snapshot" and update["content"] == _ProcessPausedModel.first + _ProcessPausedModel.second:
                            break
                    else:
                        pytest.fail("reader never observed the writer's second text checkpoint")
                assert update["message_id"] == snapshot["message_id"]
                assert update["sequence"] > snapshot["sequence"]
                finish.set()
                remaining = [item async for item in events]
                assert remaining[-1][0] == "trajectory"
                final = remaining[-1][1]
                sequences = [snapshot["sequence"], update["sequence"]] + [
                    payload["sequence"] for event, payload in remaining if event == "snapshot"
                ]
                assert all(right > left for left, right in zip(sequences, sequences[1:]))
            assert final["response"]["status"] == "completed"
            assert final["items"][-1]["message_id"] == snapshot["message_id"]
            assert final["items"][-1]["content"] == _ProcessPausedModel.first + _ProcessPausedModel.second
            assert len(final["items"]) == 2 and calls.value == 1
            persisted = await fixture.repository.read_messages(session_id)
            assert len(persisted) == 2
            assert len({message.message_id for message in persisted}) == 2
            second.cookies.clear()
            unauthorized = await second.get(f"{path}/events", params={"response_id": snapshot["response_id"]})
            assert unauthorized.json()["code"] == 200301
            second.cookies.set(SESSION_COOKIE_NAME, fixture.cookies[1])
            forbidden = await second.get(f"{path}/events", params={"response_id": snapshot["response_id"]})
            assert forbidden.json()["code"] == 200201



async def test_snapshot_migration_preserves_saved_conversations(
    branch_app, postgres_sync_engine
):
    before = await branch_app.repository.read_messages("original")
    config = Config("alembic.ini")
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        # Exercise this migration without crossing the irreversible 0075 step.
        migration = (
            ScriptDirectory.from_config(config).get_revision("20260910_0058").module
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert "response_snapshot" not in {
                column["name"]
                for column in inspect(connection).get_columns("chat_sessions")
            }
            migration.upgrade()
        assert "response_snapshot" in {
            column["name"]
            for column in inspect(connection).get_columns("chat_sessions")
        }
        assert connection.scalar(
            text("SELECT count(*) FROM chat_messages WHERE session_id = 'original'")
        ) == len(before)
    assert await branch_app.repository.read_messages("original") == before
