from __future__ import annotations

import asyncio
from hashlib import sha256
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import delete, func, inspect, select, update

from application.auth.session_service import AuthSessionService, SESSION_COOKIE_NAME
from application.chat.session_service import ChatSessionService
from application.source.collection_service import CollectionService
from controllers.chat.sessions import router
from domain.chat import ChatMessage, ChatSession, ChatToolCall, ChatToolResult, ToolRisk
from domain.source import Collection
from infra.persistence.file.collection_workspace import FileCollectionWorkspace
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from infra.persistence.postgres.models import AuthUser, ChatMessageFeedbackRow, ChatMessageRow, ChatSessionRow
from infra.persistence.postgres.models.collection import Collection as CollectionRow


pytestmark = pytest.mark.anyio
NOW = "2026-09-09T08:00:00+00:00"
ANSWER = "The two LPBF studies used different tensile test temperatures. Compare matching conditions before attributing the strength difference to heat treatment."
PATH = "/api/v1/chat-sessions/chat-1/messages/answer/feedback"


@pytest.fixture
async def feedback_app(postgres_session_factory, tmp_path):
    auth = AuthSessionService(PostgresAuthRepository(postgres_session_factory))
    users, cookies = [], []
    for email in ("feedback-owner@example.test", "feedback-other@example.test"):
        users.append(await auth.create_user(email=email, password="synthetic-test-password"))
        result = await auth.login(email=email, password="synthetic-test-password")
        cookies.append(result["session_id"])
    collections = PostgresCollectionRepository(postgres_session_factory)
    await collections.add_collection(Collection.create(
        collection_id="collection", owner_user_id=users[0]["user_id"],
        name="LPBF comparison", description=None, now_iso=NOW,
    ))
    repository = PostgresChatRepository(postgres_session_factory)
    chat = ChatSession.create(session_id="chat-1", user_id=users[0]["user_id"], collection_id="collection", created_at=NOW)
    await repository.add_session(chat)
    await repository.add_session(ChatSession.create(session_id="chat-2", user_id=users[0]["user_id"], collection_id="collection", created_at=NOW))
    call = ChatToolCall.requested(tool_call_id="call", session_id="chat-1", assistant_message_id="request", name="list_findings", arguments={}, risk=ToolRisk.READ)
    result = ChatToolResult(tool_call_id="call", status="succeeded", data={"findings": []})
    messages = (
        ChatMessage.user(message_id="question", session_id="chat-1", content="Can I compare these LPBF strength results?", created_at=NOW),
        ChatMessage.assistant_tool_calls(message_id="request", session_id="chat-1", tool_calls=(call.to_request(),), content="Inspecting comparison conditions.", created_at=NOW),
        ChatMessage.from_tool_result(message_id="tool-result", session_id="chat-1", result=result, created_at=NOW),
        ChatMessage.assistant(message_id="answer", session_id="chat-1", content=ANSWER, created_at=NOW),
    )
    await repository.save_trajectory(session=chat, messages=messages, tool_calls=(call,), tool_results=(result,))
    service = ChatSessionService(
        collection_service=CollectionService(collections, FileCollectionWorkspace(tmp_path)),
        source_artifact_repository=None, repository=repository, runner=None,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.chat_session_service = service
    app.state.auth_session_service = auth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies={SESSION_COOKIE_NAME: cookies[0]}) as client:
        yield SimpleNamespace(client=client, cookies=cookies, users=users, repository=repository, service=service, sessions=postgres_session_factory)


async def test_researcher_rates_corrects_reloads_and_withdraws(feedback_app):
    app = feedback_app
    original = await app.repository.read_messages("chat-1")
    session = await app.repository.read_session("chat-1")
    first_response = await app.client.put(PATH, json={"rating": "helpful"})
    assert first_response.status_code == 200
    first = first_response.json()
    assert first["response_digest"] == sha256(ANSWER.encode()).hexdigest()
    assert first["user_id"] == app.users[0]["user_id"]
    assert (await app.client.put(PATH, json={"rating": "helpful"})).json() == first

    changed = await app.client.put(PATH, json={"rating": "not_helpful", "reason": "incomplete", "comment": "  Please name the test temperatures and sources.  "})
    assert changed.status_code == 200
    saved = changed.json()
    assert saved["feedback_id"] == first["feedback_id"]
    assert saved["created_at"] == first["created_at"]
    assert saved["comment"] == "Please name the test temperatures and sources."
    assert saved["updated_at"] >= first["updated_at"]
    reloaded = (await app.client.get("/api/v1/chat-sessions/chat-1/messages")).json()
    assert reloaded["feedback"] == [saved]
    assert all("feedback" not in item for item in reloaded["items"])
    assert await app.repository.read_messages("chat-1") == original
    assert await app.repository.read_session("chat-1") == session
    for _ in range(2):
        withdrawn = await app.client.put(PATH, json={"rating": None})
        assert withdrawn.status_code == 200 and withdrawn.json() is None
    assert (await app.client.get("/api/v1/chat-sessions/chat-1/messages")).json()["feedback"] == []


async def test_feedback_permissions_and_input_boundaries(feedback_app):
    app = feedback_app
    app.client.cookies.clear()
    assert (await app.client.put(PATH, json={"rating": "helpful"})).status_code == 401
    app.client.cookies.set(SESSION_COOKIE_NAME, app.cookies[1])
    assert (await app.client.put(PATH, json={"rating": "helpful"})).status_code == 404
    assert (await app.client.get("/api/v1/chat-sessions/chat-1/messages")).status_code == 404
    app.client.cookies.set(SESSION_COOKIE_NAME, app.cookies[0])
    assert (await app.client.put(PATH.replace("chat-1", "chat-2"), json={"rating": "helpful"})).status_code == 404
    for message_id, status in (("missing", 404), ("local-stream-1", 404), ("question", 422), ("request", 422), ("tool-result", 422)):
        response = await app.client.put(PATH.replace("/answer/", f"/{message_id}/"), json={"rating": "helpful"})
        assert response.status_code == status, response.text
    for payload in (
        {}, {"rating": "wrong"}, {"rating": "not_helpful", "reason": "wrong"},
        {"rating": "helpful", "reason": "incorrect"}, {"rating": None, "comment": "retained"},
        {"rating": "helpful", "comment": "x" * 2001}, {"rating": "helpful", "user_id": app.users[1]["user_id"]},
        {"rating": "helpful", "response_digest": "a" * 64},
        {"rating": "not_helpful", "comment": "bad\x00comment"},
    ):
        assert (await app.client.put(PATH, json=payload)).status_code == 422
    assert await app.repository.read_feedback("chat-1", app.users[0]["user_id"]) == ()
    async with app.sessions.begin() as database:
        await database.execute(update(CollectionRow).values(owner_user_id=app.users[1]["user_id"]))
    assert (await app.client.put(PATH, json={"rating": "helpful"})).status_code == 404
    assert (await app.client.get("/api/v1/chat-sessions/chat-1/messages")).status_code == 404


async def test_concurrent_feedback_upserts_keep_one_identity(feedback_app):
    app = feedback_app
    results = await asyncio.gather(*(app.client.put(PATH, json={"rating": "helpful"}) for _ in range(12)))
    assert all(response.status_code == 200 for response in results)
    assert len({response.json()["feedback_id"] for response in results}) == 1
    assert len({response.json()["created_at"] for response in results}) == 1
    async with app.sessions() as database:
        assert await database.scalar(select(func.count()).select_from(ChatMessageFeedbackRow)) == 1


@pytest.mark.parametrize("parent", [ChatMessageRow, ChatSessionRow, AuthUser, CollectionRow])
async def test_parent_deletion_cascades_feedback(feedback_app, parent):
    app = feedback_app
    assert (await app.client.put(PATH, json={"rating": "helpful"})).status_code == 200
    async with app.sessions.begin() as database:
        if parent is AuthUser:
            await database.execute(update(CollectionRow).values(owner_user_id=app.users[1]["user_id"]))
            await database.execute(delete(AuthUser).where(AuthUser.user_id == app.users[0]["user_id"]))
        else:
            await database.execute(delete(parent))
    async with app.sessions() as database:
        assert await database.scalar(select(func.count()).select_from(ChatMessageFeedbackRow)) == 0


async def test_feedback_migration_can_be_rolled_back(postgres_sync_engine):
    config = Config("alembic.ini")
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        assert "chat_message_feedback" in inspect(connection).get_table_names()
        command.downgrade(config, "20260908_0055")
        assert "chat_message_feedback" not in inspect(connection).get_table_names()
        assert "chat_messages" in inspect(connection).get_table_names()
        command.upgrade(config, "head")
        command.check(config)
