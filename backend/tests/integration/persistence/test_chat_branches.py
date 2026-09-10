from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import inspect

from application.auth.session_service import AuthSessionService, SESSION_COOKIE_NAME
from application.chat import CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat.session_service import ChatSessionService
from application.source.collection_service import CollectionService
from controllers.chat.sessions import router
from domain.chat import ChatMessage, ChatResourceRef, ChatSession, ChatSourceContext, ChatToolCall, ChatToolResult, ToolRisk
from domain.source import Collection, Document, SourceBlock, SourceDocument
from infra.persistence.file.collection_workspace import FileCollectionWorkspace
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from tests.unit.application.test_chat_session_service import _WriteCapability
from tests.unit.application.test_research_agent_runner import _Model

pytestmark = pytest.mark.anyio
NOW = "2026-09-09T00:00:00+00:00"
QUOTE = "The LPBF Ti-6Al-4V specimens were tensile tested at 293 K."
QUESTION = "Which test conditions should I verify before comparing the reported tensile strengths?"
REVISION = "Please identify the test temperature before I compare the tensile strengths."
ANSWER = "The Source reports 293 K. Match temperature and specimen condition before comparing strength."
BASE = "/api/v1/chat-sessions"


class _Sources:
    def __init__(self):
        self.document = SourceDocument(
            document_id="paper", document_order=0, title="LPBF tensile test conditions", text=QUOTE,
            blocks=(SourceBlock(block_id="methods", document_id="paper", block_type="paragraph",
                                text=QUOTE, block_order=0, page=3, heading_path="Methods"),),
        )

    async def read_document(self, collection_id, document_id):
        return self.document if (collection_id, document_id) == ("collection", "paper") else None


@pytest.fixture
async def branch_app(postgres_session_factory, tmp_path):
    auth = AuthSessionService(PostgresAuthRepository(postgres_session_factory))
    users, cookies = [], []
    for email in ("branch-owner@example.test", "branch-other@example.test"):
        users.append(await auth.create_user(email=email, password="synthetic-test-password"))
        cookies.append((await auth.login(email=email, password="synthetic-test-password"))["session_id"])
    collections = PostgresCollectionRepository(postgres_session_factory)
    await collections.add_collection(Collection.create(
        collection_id="collection", owner_user_id=users[0]["user_id"], name="LPBF comparison",
        description=None, now_iso=NOW,
    ))
    await collections.add_documents("collection", (Document(
        document_id="paper", original_filename="lpbf.pdf", stored_filename="lpbf.pdf",
        storage_key="synthetic/lpbf.pdf", sha256="a" * 64, media_type="application/pdf",
        status="ready", size_bytes=100, created_at=NOW,
    ),), updated_at=NOW)
    repository = PostgresChatRepository(postgres_session_factory)
    chat = ChatSession.create(session_id="original", user_id=users[0]["user_id"], collection_id="collection", created_at=NOW)
    await repository.add_session(chat)
    call = ChatToolCall.requested(
        tool_call_id="historical-write", session_id=chat.session_id, assistant_message_id="request",
        name="create_objective_candidate", arguments={"question": "Compare matched LPBF tensile conditions"}, risk=ToolRisk.WRITE,
    ).require_approval()
    call = call.approve(user_id=chat.user_id, arguments_digest=call.arguments_digest, decided_at=NOW).start(NOW).succeed(NOW)
    result = ChatToolResult(tool_call_id=call.tool_call_id, status="succeeded", data={"objective_id": "existing-objective"})
    source = ChatSourceContext(
        resource_ref=ChatResourceRef(resource_type="source", resource_id="paper:methods"),
        collection_id="collection", document_id="paper", document_title="LPBF tensile test conditions",
        source_kind="text_window", source_ref="methods", page=3, quote=QUOTE,
        heading_path="Methods", source_digest=sha256(QUOTE.encode()).hexdigest(),
    )
    messages = (
        ChatMessage.user(message_id="create", session_id=chat.session_id, content="Create an objective candidate to compare LPBF tensile conditions.", created_at=NOW),
        ChatMessage.assistant_tool_calls(message_id="request", session_id=chat.session_id, tool_calls=(call.to_request(),), content="", created_at=NOW),
        ChatMessage.from_tool_result(message_id="result", session_id=chat.session_id, result=result, created_at=NOW),
        ChatMessage.assistant(message_id="created", session_id=chat.session_id, content="The candidate objective was saved.", created_at=NOW),
        ChatMessage.user(message_id="question", session_id=chat.session_id, content=QUESTION, created_at=NOW, source_contexts=(source,)),
        ChatMessage.assistant(message_id="answer", session_id=chat.session_id, content=ANSWER, created_at=NOW),
        ChatMessage.user(message_id="later", session_id=chat.session_id, content="What about specimen orientation?", created_at=NOW),
        ChatMessage.assistant(message_id="later-answer", session_id=chat.session_id, content="Check the specimen orientation separately.", created_at=NOW),
    )
    await repository.save_trajectory(session=chat, messages=messages, tool_calls=(call,), tool_results=(result,))
    model = _Model(*(ModelTurn(content=ANSWER) for _ in range(8)))
    write = _WriteCapability()
    sources = _Sources()
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((write,)))
    service = ChatSessionService(
        collection_service=CollectionService(collections, FileCollectionWorkspace(tmp_path)),
        source_artifact_repository=sources, repository=repository, runner=runner,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.auth_session_service = auth
    app.state.chat_session_service = service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies={SESSION_COOKIE_NAME: cookies[0]}) as client:
        yield SimpleNamespace(client=client, service=service, repository=repository, cookies=cookies,
                              owner=chat.user_id, model=model, sources=sources, write=write,
                              factory=postgres_session_factory)


async def _branch(app, session_id="original", message_id="question", message=REVISION, request_id=None):
    response = await app.client.post(f"{BASE}/{session_id}/branches", json={
        "message_id": message_id, "request_id": request_id or str(uuid4()), "message": message,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _send(app, branch, *, streaming=False):
    response = await app.client.post(f"{BASE}/{branch['session_id']}/messages", json={
        "message": branch["fork_content"], "branch_revision": True,
    }, headers={"Accept": "text/event-stream"} if streaming else {})
    assert response.status_code == 200, response.text
    return response


async def test_edit_preserves_sources_history_and_completed_writes(branch_app):
    app = branch_app
    original = await app.repository.read_messages("original")
    branch = await _branch(app)
    branch_id = branch["session_id"]
    copied = await app.repository.read_messages(branch_id)
    assert len(copied) == 4
    assert [item.content for item in copied if item.role.value != "tool"] == [item.content for item in original[:4] if item.role.value != "tool"]
    assert not ({item.message_id for item in copied} & {item.message_id for item in original})
    copied_call = copied[1].tool_calls[0]
    assert copied_call.tool_call_id != "historical-write"
    assert copied[2].tool_result.tool_call_id == copied_call.tool_call_id
    assert copied[2].tool_result.data["objective_id"] == "existing-objective"
    assert await app.repository.claim_approved_tool_call(session_id=branch_id, tool_call_id=copied_call.tool_call_id, user_id=app.owner, started_at=NOW) is None
    draft = (await app.client.get(f"{BASE}/{branch_id}/messages")).json()["branch_draft"]
    assert draft["content"] == REVISION and draft["source_contexts"][0]["quote"] == QUOTE
    await _send(app, branch, streaming=True)
    saved = (await app.client.get(f"{BASE}/{branch_id}/messages")).json()
    assert saved["items"][4]["content"] == REVISION
    assert saved["items"][4]["source_contexts"][0]["source_digest"] == sha256(QUOTE.encode()).hexdigest()
    assert saved["branch_draft"] is None and saved["running"] is False
    assert saved["branches"][0]["session_ids"] == ["original", branch_id]
    assert saved["branches"][0]["active_session_id"] == branch_id
    assert app.write.executed == []
    assert await app.repository.read_messages("original") == original


async def test_revision_retries_are_idempotent_and_do_not_repeat_generation(branch_app):
    app = branch_app
    request_id = str(uuid4())
    branch = await _branch(app, request_id=request_id)
    assert await _branch(app, request_id=request_id) == branch
    await _send(app, branch)
    count = len(app.model.contexts)
    assert await _branch(app, request_id=request_id) == (await app.client.get(f"{BASE}/{branch['session_id']}")).json()
    for headers in ({}, {"Accept": "text/event-stream"}):
        repeated = await app.client.post(f"{BASE}/{branch['session_id']}/messages", json={"message": REVISION, "branch_revision": True}, headers=headers)
        assert repeated.status_code == 409
    assert len(app.model.contexts) == count
    reused = await app.client.post(f"{BASE}/original/branches", json={"message_id": "question", "request_id": request_id, "message": "Different question"})
    assert reused.status_code == 422


async def test_alternatives_and_nested_edits_keep_separate_version_groups(branch_app):
    app = branch_app
    first = await _branch(app)
    await _send(app, first)
    first_question = (await app.repository.read_messages(first["session_id"]))[4]
    second = await _branch(app, first["session_id"], first_question.message_id, None)
    assert second["parent_session_id"] == "original"
    assert second["fork_message_id"] == "question"
    await _send(app, second)
    earlier = (await app.repository.read_messages(second["session_id"]))[0]
    third = await _branch(app, second["session_id"], earlier.message_id, "Explain the collection scope.")
    assert third["parent_session_id"] == "original" and third["fork_position"] == 0
    await _send(app, third)
    original = (await app.client.get(f"{BASE}/original/messages")).json()
    assert original["branches"][0]["session_ids"] == ["original", third["session_id"]]
    assert original["branches"][1]["session_ids"] == ["original", first["session_id"], second["session_id"]]


async def test_branch_authorization_busy_worker_and_message_boundaries(branch_app):
    app = branch_app
    payload = {"message_id": "question", "request_id": str(uuid4())}
    app.client.cookies.clear()
    assert (await app.client.post(f"{BASE}/original/branches", json=payload)).status_code == 401
    app.client.cookies.set(SESSION_COOKIE_NAME, app.cookies[1])
    assert (await app.client.post(f"{BASE}/original/branches", json=payload)).status_code == 404
    app.client.cookies.set(SESSION_COOKIE_NAME, app.cookies[0])
    for message_id in ("missing", "answer", "result"):
        assert (await app.client.post(f"{BASE}/original/branches", json={**payload, "message_id": message_id})).status_code == 404
    for change in ({"message": " "}, {"message": "bad\x00question"}, {"message": "x" * 12001}, {"request_id": "invalid"}, {"user_id": "other"}):
        assert (await app.client.post(f"{BASE}/original/branches", json={**payload, **change})).status_code == 422
    other_worker = PostgresChatRepository(app.factory)
    async with other_worker.session_execution("original"):
        assert (await app.client.get(f"{BASE}/original/messages")).json()["running"] is True
        assert (await app.client.post(f"{BASE}/original/branches", json=payload)).status_code == 409
        assert (await app.client.post(f"{BASE}/original/messages", json={"message": QUESTION})).status_code == 409
    assert (await app.client.get(f"{BASE}/original/messages")).json()["running"] is False


async def test_regenerated_write_requires_a_fresh_exact_approval(branch_app):
    app = branch_app
    app.service.runner.model = _Model(ModelTurn(tool_calls=(ModelToolCall(name=app.write.spec.name, arguments={"question": "Compare matched LPBF tensile conditions"}),)), ModelTurn(content="The new objective candidate was saved."))
    branch = await _branch(app, message_id="create", message=None)
    turn = (await _send(app, branch)).json()
    assert turn["status"] == "approval_required" and app.write.executed == []
    call = turn["pending_approval"]
    assert call["tool_call_id"] != "historical-write" and call["decision_user_id"] is None
    question_id = turn["messages"][0]["message_id"]
    blocked = await app.client.post(f"{BASE}/{branch['session_id']}/branches", json={"message_id": question_id, "request_id": str(uuid4())})
    assert blocked.status_code == 409
    decision_url = f"{BASE}/{branch['session_id']}/tool-calls/{call['tool_call_id']}/decision"
    approved = await app.client.post(decision_url, json={"decision": "approved", "arguments_digest": call["arguments_digest"]})
    assert approved.status_code == 200, approved.text
    assert len(app.write.executed) == 1


async def test_source_changes_block_revision_without_silently_dropping_context(branch_app):
    app = branch_app
    branch = await _branch(app)
    app.sources.document = replace(app.sources.document, blocks=(replace(app.sources.document.blocks[0], text="The reported temperature was corrected to 573 K."),))
    blocked = await app.client.post(f"{BASE}/{branch['session_id']}/messages", json={"message": REVISION, "branch_revision": True})
    assert blocked.status_code == 422
    assert len(await app.repository.read_messages(branch["session_id"])) == 4
    assert (await app.client.post(f"{BASE}/original/branches", json={"message_id": "question", "request_id": str(uuid4())})).status_code == 422


async def test_disconnected_stream_keeps_the_turn_busy_until_durable_completion(branch_app):
    app = branch_app
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedModel(_Model):
        async def respond(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().respond(**kwargs)

    app.service.runner.model = PausedModel(ModelTurn(content=ANSWER))
    branch = await _branch(app)
    events = await app.service.stream_message_for_user(
        branch["session_id"], app.owner, message=REVISION, branch_revision=True,
    )
    try:
        assert (await anext(events))["type"] == "trajectory"
        await asyncio.wait_for(entered.wait(), timeout=3)
        await events.aclose()
        saved = (await app.client.get(f"{BASE}/{branch['session_id']}/messages")).json()
        assert saved["running"] is True
        question = next(message for message in reversed(saved["items"]) if message["role"] == "user")
        blocked = await app.client.post(f"{BASE}/{branch['session_id']}/branches", json={"message_id": question["message_id"], "request_id": str(uuid4())})
        assert blocked.status_code == 409
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*app.service._active_stream_tasks), timeout=5)
    saved = (await app.client.get(f"{BASE}/{branch['session_id']}/messages")).json()
    assert saved["running"] is False and saved["items"][-1]["content"] == ANSWER


async def test_failed_model_answer_can_be_regenerated_with_the_same_source(branch_app):
    app = branch_app
    app.service.runner.model = _Model(RuntimeError("synthetic provider failure"))
    first = await _branch(app)
    failed = (await _send(app, first)).json()
    assert failed["status"] == "failed"
    question = next(message for message in failed["messages"] if message["role"] == "user")
    app.service.runner.model = _Model(ModelTurn(content=ANSWER))
    second = await _branch(app, first["session_id"], question["message_id"], None)
    completed = (await _send(app, second)).json()
    assert completed["status"] == "completed"
    assert completed["messages"][0]["source_contexts"] == question["source_contexts"]


async def test_branch_migration_round_trip_preserves_original_sessions(branch_app, postgres_sync_engine):
    app = branch_app
    await _branch(app)
    config = Config("alembic.ini")
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "20260909_0056")
        assert "fork_position" not in {column["name"] for column in inspect(connection).get_columns("chat_sessions")}
        command.upgrade(config, "head")
    assert (await app.repository.read_messages("original"))[4].content == QUESTION
