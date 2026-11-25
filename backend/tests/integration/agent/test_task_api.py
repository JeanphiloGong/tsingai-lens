from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from infra.identity.client import SESSION_COOKIE_NAME
from infra.persistence.postgres.models.chat import AgentOperationORM, AgentTaskORM
from infra.persistence.postgres.models.workspace import WorkspaceORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM
from agent.application.task_execution import task_execution
from agent.repositories.task_repository import TaskRepository
from main import app


pytestmark = pytest.mark.anyio
BASE = "/api/v1/conversations"


async def test_task_api_approval_resume_and_sse(
    postgres_session_factory, identity_subjects, monkeypatch
):
    owner = await identity_subjects.create_subject(email="agent-v4-owner@example.test")
    outsider = await identity_subjects.create_subject(
        email="agent-v4-outsider@example.test"
    )
    owner_session = await identity_subjects.issue_session(
        email="agent-v4-owner@example.test"
    )
    outsider_session = await identity_subjects.issue_session(
        email="agent-v4-outsider@example.test"
    )
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            WorkspaceORM(
                workspace_id="agent-v4-workspace",
                owner_user_id=owner["user_id"],
                name="Agent V4",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        db.add(
            ConversationORM(
                conversation_id="agent-v4-conversation",
                user_id=owner["user_id"],
                workspace_id="agent-v4-workspace",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            MessageORM(
                message_id="agent-v4-question",
                conversation_id="agent-v4-conversation",
                role="user",
                content="Inspect Source.",
                created_at=now,
            )
        )
        await db.flush()
        db.add(
            AgentTaskORM(
                task_id="agent-v4-task",
                session_id="agent-v4-conversation",
                trigger_kind="user_message",
                trigger_message_id="agent-v4-question",
                status="approval_required",
                checkpoint_revision=0,
                checkpoint={
                    "operations": [
                        {
                            "operation_id": "agent-v4-operation",
                            "task_id": "agent-v4-task",
                            "name": "write_result",
                            "arguments_digest": "a" * 64,
                            "status": "approval_required",
                            "decision_arguments_digest": None,
                            "result": None,
                        }
                    ],
                    "steps": [],
                    "messages": [],
                },
                started_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        db.add(
            AgentOperationORM(
                operation_id="agent-v4-operation",
                task_id="agent-v4-task",
                name="write_result",
                arguments={"value": "pending"},
                arguments_digest="a" * 64,
                risk="write",
                status="approval_required",
                created_at=now,
                updated_at=now,
            )
        )

    async def execute_without_provider(*, task_id, user_id, conversation_id=None, resume_revision=None):
        if resume_revision is not None:
            await TaskRepository().resume_task(
                conversation_id=conversation_id,
                task_id=task_id,
                user_id=user_id,
                expected_checkpoint_revision=resume_revision,
            )
        return "running"

    monkeypatch.setattr(task_execution, "run_task", execute_without_provider)

    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://lens.test",
            cookies={SESSION_COOKIE_NAME: owner_session["session_id"]},
        ) as client,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://lens.test",
            cookies={SESSION_COOKIE_NAME: outsider_session["session_id"]},
        ) as other,
    ):
        task_path = f"{BASE}/agent-v4-conversation/tasks/agent-v4-task"
        detail = await client.get(task_path)
        assert detail.status_code == 200
        assert detail.json()["data"]["status"] == "approval_required"
        assert detail.json()["data"]["active_operation_id"] == "agent-v4-operation"
        assert detail.json()["data"]["active_operation"]["arguments_digest"] == "a" * 64

        listed = await client.get(
            f"{BASE}/agent-v4-conversation/tasks",
            params={"status": "approval_required"},
        )
        assert listed.status_code == 200
        assert [item["task_id"] for item in listed.json()["data"]["items"]] == [
            "agent-v4-task"
        ]
        assert (await other.get(task_path)).status_code == 404

        decision_path = f"{task_path}/operations/agent-v4-operation/decision"
        stale = await client.post(
            decision_path,
            json={
                "request_id": "00000000-0000-4000-8000-000000000301",
                "decision": "approved",
                "arguments_digest": "b" * 64,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["meta"]["error_code"] == "operation_decision_conflict"

        approved = await client.post(
            decision_path,
            json={
                "request_id": "00000000-0000-4000-8000-000000000302",
                "decision": "approved",
                "arguments_digest": "a" * 64,
            },
        )
        assert approved.status_code == 200
        assert approved.json()["data"]["status"] == "approved"
        updated = await client.get(task_path)
        assert updated.json()["data"]["status"] == "running"
        assert updated.json()["data"]["checkpoint_revision"] == 1
        assert updated.json()["data"]["active_operation_id"] is None

        events = await client.get(f"{task_path}/events?after_revision=0")
        assert events.status_code == 200
        assert events.headers["content-type"].startswith("text/event-stream")
        assert "event: task.snapshot\n" in events.text
        assert '"revision": 1' in events.text
        assert (await client.get(f"{task_path}/events?after_revision=1")).text == ""
        hidden_events = await other.get(f"{task_path}/events?after_revision=0")
        assert hidden_events.status_code == 404
        assert hidden_events.json()["meta"]["error_code"] == "task_not_found"

        stopped = await client.post(
            f"{task_path}/stop",
            json={"request_id": "00000000-0000-4000-8000-000000000303"},
        )
        assert stopped.status_code == 200
        assert stopped.json()["data"] == {
            "task_id": "agent-v4-task",
            "status": "interrupted",
        }

        stale_resume = await client.post(
            f"{task_path}/resume",
            json={
                "request_id": "00000000-0000-4000-8000-000000000304",
                "expected_checkpoint_revision": 0,
            },
        )
        assert stale_resume.status_code == 409
        resumed = await client.post(
            f"{task_path}/resume",
            json={
                "request_id": "00000000-0000-4000-8000-000000000305",
                "expected_checkpoint_revision": 2,
            },
        )
        assert resumed.status_code == 200
        assert resumed.json()["data"]["status"] == "accepted"

    async with postgres_session_factory() as db:
        operation = await db.get(AgentOperationORM, "agent-v4-operation")
        task = await db.get(AgentTaskORM, "agent-v4-task")
    assert operation is not None and operation.status == "approved"
    assert task is not None and task.status == "running"
    assert task.checkpoint_revision == 3
