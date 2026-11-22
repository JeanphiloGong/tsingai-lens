from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from infra.identity.client import SESSION_COOKIE_NAME
from infra.persistence.postgres.models.chat import AgentTaskORM
from infra.persistence.postgres.models.collection import CollectionORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM
from main import app
from sqlalchemy import event

pytestmark = pytest.mark.anyio
BASE = "/api/v1/conversations"


async def test_conversation_path_metadata_and_feedback(
    postgres_session_factory, identity_subjects
):
    owner = await identity_subjects.create_subject(
        email="conversation-owner@example.test"
    )
    other = await identity_subjects.create_subject(
        email="conversation-other@example.test"
    )
    owner_session = await identity_subjects.issue_session(
        email="conversation-owner@example.test"
    )
    other_session = await identity_subjects.issue_session(
        email="conversation-other@example.test"
    )
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add_all(
            CollectionORM(
                collection_id=workspace,
                owner_user_id=user["user_id"],
                name="316L comparison",
                status="idle",
                created_at=now,
                updated_at=now,
            )
            for workspace, user in (("papers", owner), ("private", other))
        )

    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://lens.test",
            cookies={SESSION_COOKIE_NAME: owner_session["session_id"]},
        ) as browser,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://lens.test",
            cookies={SESSION_COOKIE_NAME: owner_session["session_id"]},
        ) as second_browser,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://lens.test",
            cookies={SESSION_COOKIE_NAME: other_session["session_id"]},
        ) as outsider,
    ):
        denied = await browser.post(BASE, json={"workspace_id": "private"})
        assert denied.status_code == 404
        created = await browser.post(BASE, json={"workspace_id": "papers"})
        assert created.status_code == 201
        conversation = created.json()["data"]
        assert conversation["status"] == "idle"
        conversation_id = conversation["conversation_id"]
        path = f"{BASE}/{conversation_id}"
        assert (await browser.get(f"{path}/messages")).json()["data"]["items"] == []
        renamed = await browser.put(
            f"{path}/title", json={"title": "  316L heat treatment  "}
        )
        assert renamed.json()["data"]["title"] == "316L heat treatment"
        pinned = await browser.put(f"{path}/pin", json={"is_pinned": True})
        assert pinned.json()["data"]["is_pinned"] is True
        assert (
            pinned.json()["data"]["updated_at"] == renamed.json()["data"]["updated_at"]
        )
        invalid_pin = await browser.put(f"{path}/pin", json={"is_pinned": "true"})
        assert invalid_pin.status_code == 422
        assert invalid_pin.json()["meta"]["error_code"] == "conversation_pin_invalid"
        assert (await outsider.get(path)).status_code == 404
        assert (await outsider.get(f"{path}/messages")).status_code == 404

        async with postgres_session_factory.begin() as db:
            question = MessageORM(
                message_id="question",
                conversation_id=conversation_id,
                position=0,
                role="user",
                content="Compare the heat treatments.",
                created_at=now,
                source_contexts=[{"source_ref": "methods"}],
            )
            db.add(question)
            await db.flush()
            db.add_all(
                AgentTaskORM(
                    task_id=task_id,
                    session_id=conversation_id,
                    trigger_kind="retry",
                    trigger_message_id="question",
                    request_id=str(uuid4()),
                    request_digest="a" * 64,
                    status=status,
                    started_at=now,
                    updated_at=now,
                )
                for task_id, status in (
                    ("retry-task", "running"),
                    ("approval-task", "approval_required"),
                )
            )
            await db.flush()
            db.add_all(
                [
                    MessageORM(
                        message_id="answer",
                        conversation_id=conversation_id,
                        position=1,
                        role="assistant",
                        content="The test temperatures differ.",
                        parent_message_id="question",
                        created_at=now,
                    ),
                    MessageORM(
                        message_id="retry",
                        conversation_id=conversation_id,
                        position=2,
                        role="assistant",
                        content="Compare matched test conditions first.",
                        parent_message_id="question",
                        created_at=now,
                        produced_by_task_id="retry-task",
                    ),
                ]
            )
            await db.flush()
            row = await db.get(ConversationORM, conversation_id)
            row.current_message_id = "answer"
            task = await db.get(AgentTaskORM, "retry-task")
            task.checkpoint_message_id = "retry"

        engine = postgres_session_factory.kw["bind"].sync_engine
        statements = []

        def record_query(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record_query)
        try:
            listed = await browser.get(BASE, params={"workspace_id": "papers"})
        finally:
            event.remove(engine, "before_cursor_execute", record_query)
        assert len(statements) == 1
        assert listed.json()["data"]["items"][0]["status"] == "approval"
        assert (await browser.get(path)).json()["data"]["status"] == "approval"
        assert (await outsider.get(BASE, params={"workspace_id": "papers"})).json()[
            "data"
        ]["items"] == []

        feedback_path = f"{path}/messages/answer/feedback"
        assert (
            await outsider.put(feedback_path, json={"rating": "helpful"})
        ).status_code == 404
        invalid_target = await browser.put(
            f"{path}/messages/question/feedback", json={"rating": "helpful"}
        )
        assert invalid_target.status_code == 422
        assert (
            invalid_target.json()["meta"]["error_code"]
            == "feedback_message_not_assistant"
        )
        invalid_reason = await browser.put(
            feedback_path, json={"rating": "helpful", "reason": "unclear"}
        )
        assert invalid_reason.status_code == 422
        assert invalid_reason.json()["meta"]["error_code"] == "feedback_reason_invalid"
        feedback = await browser.put(feedback_path, json={"rating": "helpful"})
        saved = feedback.json()["data"]
        assert (
            saved["response_digest"]
            == sha256(b"The test temperatures differ.").hexdigest()
        )
        assert (await browser.put(feedback_path, json={"rating": "helpful"})).json()[
            "data"
        ] == saved
        current = (await browser.get(f"{path}/messages")).json()["data"]
        assert current["items"][0]["source_contexts"] == [{"source_ref": "methods"}]
        assert current["items"][1]["my_feedback"] == saved
        assert {task["task_id"] for task in current["active_tasks"]} == {
            "retry-task",
            "approval-task",
        }

        invalid_selection = await browser.put(
            f"{path}/active-path", json={"expected_path_revision": 0}
        )
        assert invalid_selection.status_code == 422
        missing_target = await browser.put(
            f"{path}/active-path",
            json={
                "expected_path_revision": 0,
                "tip_message_id": "missing",
            },
        )
        assert missing_target.status_code == 404
        selected = await second_browser.put(
            f"{path}/active-path",
            json={
                "expected_path_revision": 0,
                "task_id": "retry-task",
            },
        )
        assert selected.json()["data"]["path_revision"] == 1
        stale = await browser.put(
            f"{path}/active-path",
            json={
                "expected_path_revision": 0,
                "tip_message_id": "answer",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["meta"]["error_code"] == "conversation_path_conflict"
        assert stale.json()["meta"]["current_path_revision"] == 1
        repeated = await browser.put(
            f"{path}/active-path",
            json={
                "expected_path_revision": 1,
                "task_id": "retry-task",
            },
        )
        assert repeated.json()["data"]["path_revision"] == 1
        current = (await browser.get(f"{path}/messages")).json()["data"]
        assert current["conversation"]["path_revision"] == 1
        assert current["tip_message_id"] == "retry"
        assert current["items"][1]["my_feedback"] is None

        assert (await browser.delete(feedback_path)).status_code == 204
        assert (await browser.delete(feedback_path)).status_code == 204
        selected = await browser.put(
            f"{path}/active-path",
            json={
                "expected_path_revision": 1,
                "tip_message_id": "answer",
            },
        )
        assert selected.json()["data"]["path_revision"] == 2
        current = (await browser.get(f"{path}/messages")).json()["data"]
        assert current["items"][1]["my_feedback"] is None
