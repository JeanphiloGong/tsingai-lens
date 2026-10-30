from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from hashlib import sha256
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from application.auth import session_service as auth_session_service
from application.auth.session_service import SESSION_COOKIE_NAME
from application.chat import session_service as chat_session_service
from application.source import collection_service
from controllers.chat.chat_session_routes import chat_session_router as router
from controllers.exception_router import (
    general_exception_handler,
    http_exception_handler,
    project_exception_handler,
    request_validation_handler,
)
from domain.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatSession,
    ChatToolCall,
    ChatToolRequest,
    ChatToolResult,
    ToolResultStatus,
    ToolRisk,
)
from domain.source import Collection
from exceptions import ProjectException
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from infra.persistence.file.collection_workspace import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from infra.persistence.postgres.models import (
    AuthUser,
    ChatMessageFeedbackRow,
    ChatMessageRow,
    ChatSessionRow,
)
from infra.persistence.postgres.models.collection import Collection as CollectionRow
from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetRow
from repositories.auth_repository import AuthRepository
from repositories.chat_repository import ChatRepository
from repositories.collection_repository import (
    CollectionRepository,
    StoredCollection,
)
from sqlalchemy import delete, func, inspect, select, update
from starlette.exceptions import HTTPException as StarletteHTTPException

pytestmark = pytest.mark.anyio
NOW = "2026-09-09T08:00:00+00:00"
ANSWER = "The two LPBF studies used different tensile test temperatures. Compare matching conditions before attributing the strength difference to heat treatment."
PATH = "/api/v1/chat-sessions/chat-1/messages/answer/feedback"


@pytest.fixture
async def feedback_app(postgres_session_factory, tmp_path):
    auth_session_service.AuthRepo = AuthRepository()
    auth = auth_session_service
    users, cookies = [], []
    for email in ("feedback-owner@example.test", "feedback-other@example.test"):
        users.append(
            await auth.create_user(email=email, password="synthetic-test-password")
        )
        result = await auth.login(email=email, password="synthetic-test-password")
        cookies.append(result["session_id"])
    collections = CollectionRepository()
    await collections.add_collection(
        StoredCollection(
            collection=Collection(
                collection_id="collection",
                owner_user_id=users[0]["user_id"],
                name="LPBF comparison",
                description=None,
                status="idle",
            ),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository = ChatRepository()
    chat = ChatSession.create(
        session_id="chat-1",
        user_id=users[0]["user_id"],
        collection_id="collection",
        created_at=NOW,
    )
    await repository.add_session(chat)
    await repository.add_session(
        ChatSession.create(
            session_id="chat-2",
            user_id=users[0]["user_id"],
            collection_id="collection",
            created_at=NOW,
        )
    )
    call = ChatToolCall.requested(
        tool_call_id="call",
        session_id="chat-1",
        assistant_message_id="request",
        name="list_findings",
        arguments={},
        risk=ToolRisk.READ,
    )
    result = ChatToolResult(
        tool_call_id="call", status=ToolResultStatus.SUCCEEDED, data={"findings": []}
    )
    messages = (
        ChatMessage.user(
            message_id="question",
            session_id="chat-1",
            content="Can I compare these LPBF strength results?",
            created_at=NOW,
        ),
        ChatMessage.assistant_tool_calls(
            message_id="request",
            session_id="chat-1",
            tool_calls=(
                ChatToolRequest(
                    tool_call_id=call.tool_call_id,
                    name=call.name,
                    arguments=call.arguments,
                    position=call.position,
                    decision_user_id=call.decision_user_id,
                    decision_arguments_digest=call.decision_arguments_digest,
                    decided_at=call.decided_at,
                    decision_basis=call.decision_basis,
                    authorization_revision=call.authorization_revision,
                ),
            ),
            content="Inspecting comparison conditions.",
            created_at=NOW,
        ),
        ChatMessage(
            message_id="tool-result",
            session_id="chat-1",
            role=ChatMessageRole.TOOL,
            content=json.dumps(
                asdict(result),
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            created_at=NOW,
            tool_call_id=result.tool_call_id,
            tool_result=result,
        ),
        ChatMessage.assistant(
            message_id="answer", session_id="chat-1", content=ANSWER, created_at=NOW
        ),
    )
    await repository.save_trajectory(
        chat_session=chat, messages=messages, tool_calls=(call,), tool_results=(result,)
    )
    chat_session_service.collection_service = collection_service
    chat_session_service.SourceArtifactRepo = None
    chat_session_service.ChatRepo = repository
    runner = None
    collection_service.CollectionRepo = collections
    collection_service.workspace = FileCollectionWorkspace(tmp_path)
    collection_service.root_dir = collection_service.workspace.root_dir
    collection_service.object_store = FileObjectStore(collection_service.root_dir)
    service = chat_session_service.ChatSessionService(runner=runner)
    app = FastAPI()
    app.state.runtime = SimpleNamespace(chat_session_service=service)
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    app.include_router(router, prefix="/api/v1")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={SESSION_COOKIE_NAME: cookies[0]},
    ) as client:
        yield SimpleNamespace(
            client=client,
            cookies=cookies,
            users=users,
            repository=repository,
            service=service,
            sessions=postgres_session_factory,
        )


async def test_researcher_rates_corrects_reloads_and_withdraws(feedback_app):
    app = feedback_app
    original = await app.repository.read_messages("chat-1")
    session = await app.repository.read_session("chat-1")
    first_response = await app.client.put(PATH, json={"rating": "helpful"})
    assert first_response.status_code == 200
    first = first_response.json()["data"]
    assert first["response_digest"] == sha256(ANSWER.encode()).hexdigest()
    assert first["user_id"] == app.users[0]["user_id"]
    assert (await app.client.put(PATH, json={"rating": "helpful"})).json()[
        "data"
    ] == first

    changed = await app.client.put(
        PATH,
        json={
            "rating": "not_helpful",
            "reason": "incomplete",
            "comment": "  Please name the test temperatures and sources.  ",
        },
    )
    assert changed.status_code == 200
    saved = changed.json()["data"]
    assert saved["feedback_id"] == first["feedback_id"]
    assert saved["created_at"] == first["created_at"]
    assert saved["comment"] == "Please name the test temperatures and sources."
    assert saved["updated_at"] >= first["updated_at"]
    reloaded = (await app.client.get("/api/v1/chat-sessions/chat-1/messages")).json()[
        "data"
    ]
    assert reloaded["feedback"] == [saved]
    assert all("feedback" not in item for item in reloaded["items"])
    assert await app.repository.read_messages("chat-1") == original
    assert await app.repository.read_session("chat-1") == session
    for _ in range(2):
        withdrawn = await app.client.put(PATH, json={"rating": None})
        assert withdrawn.status_code == 200 and withdrawn.json()["data"] == {}
    assert (await app.client.get("/api/v1/chat-sessions/chat-1/messages")).json()[
        "data"
    ]["feedback"] == []


async def test_feedback_permissions_and_input_boundaries(feedback_app):
    app = feedback_app
    app.client.cookies.clear()
    rejection = await app.client.put(PATH, json={"rating": "helpful"})
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200301
    app.client.cookies.set(SESSION_COOKIE_NAME, app.cookies[1])
    rejection = await app.client.put(PATH, json={"rating": "helpful"})
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200201
    rejection = await app.client.get("/api/v1/chat-sessions/chat-1/messages")
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200201
    app.client.cookies.set(SESSION_COOKIE_NAME, app.cookies[0])
    rejection = await app.client.put(
        PATH.replace("chat-1", "chat-2"), json={"rating": "helpful"}
    )
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200201
    for message_id, code in (
        ("missing", 200201),
        ("local-stream-1", 200201),
        ("question", 200100),
        ("request", 200100),
        ("tool-result", 200100),
    ):
        for rating in ("helpful", None):
            response = await app.client.put(
                PATH.replace("/answer/", f"/{message_id}/"), json={"rating": rating}
            )
            assert response.status_code == 200, response.text
            assert response.json()["code"] == code
    for payload in (
        {},
        {"rating": "wrong"},
        {"rating": "not_helpful", "reason": "wrong"},
        {"rating": "helpful", "reason": "incorrect"},
        {"rating": None, "comment": "retained"},
        {"rating": "helpful", "comment": "x" * 2001},
        {"rating": "helpful", "user_id": app.users[1]["user_id"]},
        {"rating": "helpful", "response_digest": "a" * 64},
        {"rating": "not_helpful", "comment": "bad\x00comment"},
    ):
        rejection = await app.client.put(PATH, json=payload)
        assert rejection.status_code == 200
        assert rejection.json()["code"] == 200100
    assert await app.repository.read_feedback("chat-1", app.users[0]["user_id"]) == ()
    async with app.sessions.begin() as database:
        await database.execute(
            update(CollectionRow).values(owner_user_id=app.users[1]["user_id"])
        )
    rejection = await app.client.put(PATH, json={"rating": "helpful"})
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200201
    rejection = await app.client.get("/api/v1/chat-sessions/chat-1/messages")
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200201


async def test_concurrent_feedback_upserts_keep_one_identity(feedback_app):
    app = feedback_app
    results = await asyncio.gather(
        *(app.client.put(PATH, json={"rating": "helpful"}) for _ in range(12))
    )
    assert all(response.status_code == 200 for response in results)
    assert len({response.json()["data"]["feedback_id"] for response in results}) == 1
    assert len({response.json()["data"]["created_at"] for response in results}) == 1
    async with app.sessions() as database:
        assert (
            await database.scalar(
                select(func.count()).select_from(ChatMessageFeedbackRow)
            )
            == 1
        )


@pytest.mark.parametrize(
    "parent", [ChatMessageRow, ChatSessionRow, AuthUser, CollectionRow]
)
async def test_parent_deletion_cascades_feedback(feedback_app, parent):
    app = feedback_app
    assert (await app.client.put(PATH, json={"rating": "helpful"})).status_code == 200
    async with app.sessions.begin() as database:
        if parent is AuthUser:
            await database.execute(
                update(CollectionRow).values(owner_user_id=app.users[1]["user_id"])
            )
            await database.execute(
                update(FeedbackDatasetRow).values(created_by=app.users[1]["user_id"])
            )
            await database.execute(
                delete(AuthUser).where(AuthUser.user_id == app.users[0]["user_id"])
            )
        else:
            await database.execute(delete(parent))
    async with app.sessions() as database:
        assert (
            await database.scalar(
                select(func.count()).select_from(ChatMessageFeedbackRow)
            )
            == 0
        )


async def test_feedback_migration_can_be_rolled_back(postgres_sync_engine):
    config = Config("alembic.ini")
    with postgres_sync_engine.begin() as connection:
        # Isolate feedback DDL from irreversible and later dataset migrations.
        migration = (
            ScriptDirectory.from_config(config).get_revision("20260909_0056").module
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert "chat_message_feedback" not in inspect(connection).get_table_names()
            assert "chat_messages" in inspect(connection).get_table_names()
            migration.upgrade()
            assert "chat_message_feedback" in inspect(connection).get_table_names()
        config.attributes["connection"] = connection
        command.check(config)


def test_latest_feedback_head_refuses_irreversible_downgrade(postgres_sync_engine):
    config = Config("alembic.ini")
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="irreversible"):
            command.downgrade(config, "20260924_0074")
