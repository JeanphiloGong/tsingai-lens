from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agent.repositories.task_repository import CheckpointConflict, TaskRepository
from conversation.repositories.conversation_repository import ConversationRepository
from infra.identity.client import SESSION_COOKIE_NAME
from infra.persistence.postgres.models.chat import AgentOperationORM, AgentTaskORM
from infra.persistence.postgres.models.workspace import WorkspaceORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM
from main import app


pytestmark = pytest.mark.anyio
BASE = "/api/v1/conversations"


async def test_delete_soft_deletes_conversation_and_cancels_execution(
    postgres_session_factory, identity_subjects
):
    owner = await identity_subjects.create_subject(email="delete-owner@example.test")
    session = await identity_subjects.issue_session(email="delete-owner@example.test")
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            WorkspaceORM(
                workspace_id="delete-workspace",
                owner_user_id=owner["user_id"],
                name="Conversation deletion",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ConversationORM(
                conversation_id="delete-conversation",
                user_id=owner["user_id"],
                workspace_id="delete-workspace",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            MessageORM(
                message_id="delete-question",
                conversation_id="delete-conversation",
                position=0,
                role="user",
                content="Compare these Sources.",
                created_at=now,
            )
        )
        await db.flush()
        db.add_all(
            AgentTaskORM(
                task_id=f"delete-task-{status}",
                session_id="delete-conversation",
                trigger_kind="user_message",
                trigger_message_id="delete-question",
                status=status,
                started_at=now,
                updated_at=now,
            )
            for status in ("accepted", "running", "approval_required", "interrupted")
        )
        await db.flush()
        db.add_all(
            [
                AgentOperationORM(
                    operation_id="delete-pending-operation",
                    task_id="delete-task-approval_required",
                    name="write_result",
                    arguments={},
                    arguments_digest="a" * 64,
                    risk="write",
                    status="approval_required",
                    created_at=now,
                    updated_at=now,
                ),
                AgentOperationORM(
                    operation_id="delete-running-operation",
                    task_id="delete-task-running",
                    name="write_result",
                    arguments={},
                    arguments_digest="b" * 64,
                    risk="write",
                    status="running",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://lens.test",
        cookies={SESSION_COOKIE_NAME: session["session_id"]},
    ) as client:
        deleted = await client.delete(f"{BASE}/delete-conversation")
        assert deleted.status_code == 200
        assert deleted.json()["data"] == {}
        assert (await client.delete(f"{BASE}/delete-conversation")).status_code == 200
        assert (await client.get(f"{BASE}/delete-conversation")).status_code == 404
        assert (
            await client.get(
                BASE,
                params={"workspace_id": "delete-workspace"},
            )
        ).json()["data"]["items"] == []

    async with postgres_session_factory() as db:
        conversation = await db.get(ConversationORM, "delete-conversation")
        question = await db.get(MessageORM, "delete-question")
        tasks = (
            await db.scalars(
                select(AgentTaskORM).where(
                    AgentTaskORM.session_id == "delete-conversation"
                )
            )
        ).all()
        operations = (
            await db.scalars(
                select(AgentOperationORM).where(
                    AgentOperationORM.task_id.in_(
                        tuple(task.task_id for task in tasks)
                    )
                )
            )
        ).all()
    assert conversation is not None and conversation.deleted_at is not None
    assert question is not None
    assert {task.status for task in tasks} == {"cancelled"}
    assert {
        operation.operation_id: operation.status for operation in operations
    } == {
        "delete-pending-operation": "rejected",
        "delete-running-operation": "needs_reconciliation",
    }


async def test_deleted_conversation_rejects_checkpoint_and_marks_tree_source(
    postgres_session_factory, identity_subjects
):
    owner = await identity_subjects.create_subject(email="delete-tree-owner@example.test")
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            WorkspaceORM(
                workspace_id="delete-tree-workspace",
                owner_user_id=owner["user_id"],
                name="Deleted tree source",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ConversationORM(
                conversation_id="delete-tree-source",
                user_id=owner["user_id"],
                workspace_id="delete-tree-workspace",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            MessageORM(
                message_id="delete-tree-source-message",
                conversation_id="delete-tree-source",
                position=0,
                role="user",
                content="Source question.",
                created_at=now,
            )
        )
        await db.flush()
        db.add(
            AgentTaskORM(
                task_id="delete-tree-task",
                session_id="delete-tree-source",
                trigger_kind="user_message",
                trigger_message_id="delete-tree-source-message",
                status="accepted",
                started_at=now,
                updated_at=now,
            )
        )

    repository = ConversationRepository()
    child = await repository.fork_conversation(
        conversation_id="delete-tree-source",
        message_id="delete-tree-source-message",
        user_id=owner["user_id"],
    )
    await repository.delete_conversation(
        conversation_id="delete-tree-source",
        user_id=owner["user_id"],
    )
    tree = await repository.read_tree(
        conversation_id=child.conversation_id,
        user_id=owner["user_id"],
    )
    source_node = next(
        node
        for node in tree.nodes
        if node.conversation_id == "delete-tree-source"
    )
    assert source_node.deleted_source is True
    assert source_node.edge_kind == "fork_deleted_source"
    assert source_node.preview == "已删除的 Conversation"

    task_repository = TaskRepository()
    with pytest.raises(CheckpointConflict, match="conversation was deleted"):
        await task_repository.write_checkpoint_bundle(
            task_id="delete-tree-task",
            expected_revision=0,
            message=None,
            operation=None,
            step={
                "step_id": "delete-tree-step",
                "sequence": 0,
                "name": "research_turn",
                "status": "completed",
                "checkpoint": {},
            },
            checkpoint={},
            status="running",
        )
