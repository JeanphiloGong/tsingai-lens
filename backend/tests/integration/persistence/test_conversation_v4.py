from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from infra.identity.client import SESSION_COOKIE_NAME
from infra.persistence.postgres.models.chat import AgentOperationORM, AgentTaskORM
from infra.persistence.postgres.models.collection import CollectionORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM
from main import app


pytestmark = pytest.mark.anyio
BASE = "/api/v1/conversations"


async def test_conversation_commands_tree_and_fork(
    postgres_session_factory, identity_subjects
):
    owner = await identity_subjects.create_subject(email="v4-owner@example.test")
    outsider = await identity_subjects.create_subject(email="v4-outsider@example.test")
    owner_session = await identity_subjects.issue_session(email="v4-owner@example.test")
    outsider_session = await identity_subjects.issue_session(
        email="v4-outsider@example.test"
    )
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            CollectionORM(
                collection_id="v4-workspace",
                owner_user_id=owner["user_id"],
                name="Conversation V4",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )

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
        created = await client.post(BASE, json={"workspace_id": "v4-workspace"})
        assert created.status_code == 201
        conversation_id = created.json()["data"]["conversation_id"]

        accepted = await client.post(
            f"{BASE}/{conversation_id}/messages",
            json={"message": "Compare the reported heat treatments."},
        )
        assert accepted.status_code == 200
        initial = accepted.json()["data"]
        path = f"{BASE}/{conversation_id}/messages"
        pending_path = (await client.get(path)).json()["data"]
        assert pending_path["conversation"]["current_task_id"] == initial["task_id"]
        assert pending_path["conversation"]["path_revision"] == 1
        assert pending_path["tip_message_id"] == initial["trigger_message_id"]

        async with postgres_session_factory.begin() as db:
            task = await db.get(AgentTaskORM, initial["task_id"])
            question = await db.get(MessageORM, initial["trigger_message_id"])
            finished_at = datetime.now(UTC)
            answer = MessageORM(
                message_id="v4-answer",
                conversation_id=conversation_id,
                position=1,
                role="assistant",
                content="The reported conditions differ.",
                parent_message_id=question.message_id,
                produced_by_task_id=task.task_id,
                created_at=finished_at,
            )
            db.add(answer)
            await db.flush()
            task.status = "completed"
            task.final_message_id = answer.message_id
            task.finished_at = finished_at

        feedback = await client.put(
            f"{path}/v4-answer/feedback",
            json={"rating": "helpful"},
        )
        assert feedback.status_code == 200
        current = (await client.get(path)).json()["data"]
        assert current["items"][-1]["message_id"] == "v4-answer"
        assert current["items"][-1]["my_feedback"]["rating"] == "helpful"
        completed_tree = (await client.get(f"{BASE}/{conversation_id}/tree")).json()["data"]
        assert completed_tree["active_path"][-1] == "message:v4-answer"

        retry_a = await client.post(
            f"{BASE}/{conversation_id}/messages/{question.message_id}/regenerations",
            json={},
        )
        retry_b = await client.post(
            f"{BASE}/{conversation_id}/messages/{question.message_id}/regenerations",
            json={},
        )
        edited = await client.post(
            f"{BASE}/{conversation_id}/messages/{question.message_id}/edits",
            json={"message": "Compare only matched heat treatments."},
        )
        assert retry_a.status_code == retry_b.status_code == edited.status_code == 200
        task_ids = {
            retry_a.json()["data"]["task_id"],
            retry_b.json()["data"]["task_id"],
            edited.json()["data"]["task_id"],
        }
        assert len(task_ids) == 3

        edited_task = edited.json()["data"]
        current = (await client.get(path)).json()["data"]
        assert current["conversation"]["current_task_id"] == edited_task["task_id"]
        assert current["conversation"]["path_revision"] == 4
        assert current["tip_message_id"] == edited_task["trigger_message_id"]

        async with postgres_session_factory.begin() as db:
            db.add(
                AgentOperationORM(
                    operation_id="v4-pending-operation",
                    task_id=initial["task_id"],
                    assistant_message_id="v4-answer",
                    name="write_result",
                    arguments={"value": "pending"},
                    arguments_digest="a" * 64,
                    risk="write",
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
            )

        blocked_fork = await client.post(
            f"{BASE}/{conversation_id}/forks",
            json={"message_id": "v4-answer"},
        )
        assert blocked_fork.status_code == 409
        assert blocked_fork.json()["meta"]["error_code"] == "fork_source_not_ready"
        async with postgres_session_factory.begin() as db:
            operation = await db.get(AgentOperationORM, "v4-pending-operation")
            operation.status = "succeeded"

        forked = await client.post(
            f"{BASE}/{conversation_id}/forks",
            json={"message_id": "v4-answer"},
        )
        assert forked.status_code == 200
        fork_id = forked.json()["data"]["conversation_id"]
        assert fork_id != conversation_id

        fork_messages = await client.get(f"{BASE}/{fork_id}/messages")
        assert fork_messages.status_code == 200
        assert fork_messages.json()["data"]["items"][-1]["message_id"] != "v4-answer"
        assert fork_messages.json()["data"]["items"][-1]["my_feedback"] is None

        tree = await client.get(f"{BASE}/{conversation_id}/tree")
        assert tree.status_code == 200
        tree_data = tree.json()["data"]
        assert tree_data["root_conversation_id"] == conversation_id
        assert f"conversation:{conversation_id}" in tree_data["active_path"]
        assert tree_data["active_path"][-1] == f"task:{edited_task['task_id']}"
        assert task_ids <= {
            node["task_id"]
            for node in tree_data["nodes"]
            if node["kind"] == "task"
        }
        fork_node = next(
            node
            for node in tree_data["nodes"]
            if node["kind"] == "conversation" and node["conversation_id"] == fork_id
        )
        assert fork_node["edge_kind"] == "fork"
        assert fork_node["forked_from_message_id"] == "v4-answer"

        assert (
            await other.get(f"{BASE}/{conversation_id}/tree")
        ).status_code == 404

    async with postgres_session_factory() as db:
        edited_message = await db.get(MessageORM, edited.json()["data"]["trigger_message_id"])
        assert edited_message.parent_message_id is None
