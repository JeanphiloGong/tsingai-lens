from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from infra.persistence.postgres.models.chat import (
    AgentOperationORM,
    AgentTaskORM,
    ChatModelCallORM,
    ChatToolCallORM,
)
from infra.persistence.postgres.models.collection import CollectionORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM
from scripts.backfill_agent_tasks import (
    run,
    stable_operation_id,
    stable_task_id,
)


pytestmark = pytest.mark.anyio


async def test_agent_backfill_is_conservative_and_idempotent(postgres_session_factory):
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            CollectionORM(
                collection_id="migration-v3-workspace",
                owner_user_id="migration-v3-owner",
                name="Migration V3",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ConversationORM(
                conversation_id="migration-v3-conversation",
                user_id="migration-v3-owner",
                workspace_id="migration-v3-workspace",
                response_snapshot={
                    "response_id": "response-reliable",
                    "trigger_message_id": "migration-v3-question",
                    "final_message_id": "migration-v3-answer",
                    "status": "completed",
                    "sequence": 3,
                    "checkpoint": {"next": "done"},
                },
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        db.add_all(
            [
                MessageORM(
                    message_id="migration-v3-question",
                    conversation_id="migration-v3-conversation",
                    position=0,
                    role="user",
                    content="Inspect Source.",
                    created_at=now,
                ),
                MessageORM(
                    message_id="migration-v3-answer",
                    conversation_id="migration-v3-conversation",
                    position=1,
                    role="assistant",
                    content="The Source is ready.",
                    created_at=now,
                ),
            ]
        )
        await db.flush()
        db.add(
            ChatToolCallORM(
                tool_call_id="migration-v3-tool",
                session_id="migration-v3-conversation",
                assistant_message_id="migration-v3-answer",
                name="write_result",
                position=0,
                arguments={"value": "pending"},
                arguments_digest="a" * 64,
                risk="write",
                status="running",
            )
        )
        db.add(
            ChatModelCallORM(
                call_id="migration-v3-model-call",
                session_id="migration-v3-conversation",
                trigger_message_id="migration-v3-question",
                response_message_id="migration-v3-answer",
                purpose="decision",
                model="legacy-model",
                request={},
                request_digest="b" * 64,
                status="provider_succeeded",
                started_at=now,
            )
        )

    async with postgres_session_factory() as db:
        first = await run(db)
    async with postgres_session_factory() as db:
        second = await run(db)

    task_id = stable_task_id("response-reliable")
    operation_id = stable_operation_id(task_id, "migration-v3-tool")
    assert task_id in first.created_task_ids
    assert operation_id in first.reconciliation_operation_ids
    assert second.created_task_ids == []
    async with postgres_session_factory() as db:
        tasks = (
            await db.scalars(select(AgentTaskORM).where(AgentTaskORM.task_id == task_id))
        ).all()
        operations = (
            await db.scalars(
                select(AgentOperationORM).where(
                    AgentOperationORM.operation_id == operation_id
                )
            )
        ).all()
        model_call = await db.get(ChatModelCallORM, "migration-v3-model-call")
        answer = await db.get(MessageORM, "migration-v3-answer")

    assert len(tasks) == 1
    assert len(operations) == 1
    assert operations[0].status == "needs_reconciliation"
    assert model_call.task_id == task_id
    assert model_call.sequence == 0
    assert answer.produced_by_task_id == task_id


async def test_agent_backfill_reports_ambiguous_response(postgres_session_factory):
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            CollectionORM(
                collection_id="migration-v3-ambiguous-workspace",
                owner_user_id="migration-v3-ambiguous-owner",
                name="Migration V3 Ambiguous",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ConversationORM(
                conversation_id="migration-v3-ambiguous-conversation",
                user_id="migration-v3-ambiguous-owner",
                workspace_id="migration-v3-ambiguous-workspace",
                response_snapshot={
                    "response_id": "response-ambiguous",
                    "response_count": 2,
                    "status": "completed",
                },
                created_at=now,
                updated_at=now,
            )
        )

    async with postgres_session_factory() as db:
        report = await run(db)

    assert report.created_task_ids == []
    assert report.unresolved_response_ids == ["response-ambiguous"]
