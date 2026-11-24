from datetime import UTC, datetime

import pytest
from infra.persistence.postgres.models.workspace import WorkspaceORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM

from agent.repositories.task_repository import (
    CheckpointConflict,
    TaskNotFound,
    TaskRepository,
)


pytestmark = pytest.mark.anyio


async def test_task_checkpoint_and_bundle_persist_atomically(
    postgres_session_factory, identity_subjects
):
    owner = await identity_subjects.create_subject(email="agent-v2-owner@example.test")
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            WorkspaceORM(
                workspace_id="agent-v2-workspace",
                owner_user_id=owner["user_id"],
                name="Agent V2",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ConversationORM(
                conversation_id="agent-v2-conversation",
                user_id=owner["user_id"],
                workspace_id="agent-v2-workspace",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            MessageORM(
                message_id="agent-v2-question",
                conversation_id="agent-v2-conversation",
                position=0,
                role="user",
                content="Inspect the Source.",
                created_at=now,
            )
        )

    repository = TaskRepository()
    async with postgres_session_factory.begin() as db:
        await repository.insert_accepted_task(
            db,
            task_id="agent-v2-task",
            conversation_id="agent-v2-conversation",
            trigger_message_id="agent-v2-question",
        )

    context = await repository.load_for_execution(
        task_id="agent-v2-task", user_id=owner["user_id"]
    )
    assert context.workspace_id == "agent-v2-workspace"
    assert context.checkpoint_revision == 0
    assert context.status == "accepted"

    assert (
        await repository.save_checkpoint(
            task_id="agent-v2-task",
            expected_revision=0,
            checkpoint={"next": "read"},
            status="running",
        )
        == 1
    )
    with pytest.raises(CheckpointConflict):
        await repository.save_checkpoint(
            task_id="agent-v2-task",
            expected_revision=0,
            checkpoint={"next": "again"},
            status="running",
        )

    revision = await repository.write_checkpoint_bundle(
        task_id="agent-v2-task",
        expected_revision=1,
        message={
            "message_id": "agent-v2-answer",
            "parent_message_id": "agent-v2-question",
            "role": "assistant",
            "content": "The Source is ready for inspection.",
        },
        operation={
            "operation_id": "agent-v2-operation",
            "name": "read_source",
            "arguments": {"source": "Source.pdf"},
            "arguments_digest": "a" * 64,
            "status": "succeeded",
            "risk": "read",
        },
        step={
            "step_id": "agent-v2-step",
            "sequence": 0,
            "name": "inspect_source",
            "status": "completed",
            "checkpoint": {"operation": "agent-v2-operation"},
        },
        checkpoint={"next": "finalize"},
        status="completed",
    )
    assert revision == 2

    saved = await repository.read_task(
        conversation_id="agent-v2-conversation",
        task_id="agent-v2-task",
        user_id=owner["user_id"],
    )
    assert saved["status"] == "completed"
    assert saved["checkpoint_revision"] == 2
    with pytest.raises(TaskNotFound):
        await repository.read_task(
            conversation_id="agent-v2-conversation",
            task_id="agent-v2-task",
            user_id="another-user",
        )
