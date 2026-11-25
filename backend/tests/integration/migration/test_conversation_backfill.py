from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import literal_column, select, text

from infra.persistence.postgres.models.workspace import WorkspaceORM
from infra.persistence.postgres.models.conversation import (
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)
from scripts.backfill_conversations import backfill_conversation


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.parametrize("postgres_sync_engine", ["b71000000006"], indirect=True),
]


async def test_backfill_is_idempotent_and_preserves_feedback(
    postgres_session_factory,
):
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            WorkspaceORM(
                workspace_id="migration-v2-workspace",
                owner_user_id="migration-v2-owner",
                name="Migration V2",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        db.add(
            ConversationORM(
                conversation_id="migration-v2-conversation",
                user_id="migration-v2-owner",
                workspace_id="migration-v2-workspace",
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        await db.execute(text("""
            INSERT INTO chat_messages
                (message_id, conversation_id, position, role, content, source_contexts, created_at)
            VALUES (:message_id, :conversation_id, :position, :role, :content,
                    CAST(:source_contexts AS jsonb), :created_at)
        """), [
            {'message_id': "migration-v2-question", 'conversation_id': "migration-v2-conversation", 'position': 0, 'role': "user", 'content': "Compare the papers.", 'source_contexts': '[{"document_id": "paper-a"}]', 'created_at': now},
            {'message_id': "migration-v2-answer-1", 'conversation_id': "migration-v2-conversation", 'position': 1, 'role': "assistant", 'content': "First answer.", 'source_contexts': '[]', 'created_at': now},
            {'message_id': "migration-v2-answer-2", 'conversation_id': "migration-v2-conversation", 'position': 2, 'role': "assistant", 'content': "Second answer.", 'source_contexts': '[]', 'created_at': now},
        ])
        await db.flush()
        db.add(
            MessageFeedbackORM(
                feedback_id="migration-v2-feedback",
                conversation_id="migration-v2-conversation",
                message_id="migration-v2-answer-2",
                user_id="migration-v2-owner",
                rating="helpful",
                response_digest=sha256(b"Second answer.").hexdigest(),
                created_at=now,
                updated_at=now,
            )
        )

    async with postgres_session_factory() as db:
        first = await backfill_conversation(db, "migration-v2-conversation")
    async with postgres_session_factory() as db:
        second = await backfill_conversation(db, "migration-v2-conversation")

    assert first.unresolved == []
    assert second.unresolved == []
    async with postgres_session_factory() as db:
        messages = (
            await db.scalars(
                select(MessageORM)
                .where(MessageORM.conversation_id == "migration-v2-conversation")
                .order_by(literal_column("chat_messages.position"))
            )
        ).all()
        conversation = await db.get(ConversationORM, "migration-v2-conversation")
        feedback = await db.get(MessageFeedbackORM, "migration-v2-feedback")

    assert [message.parent_message_id for message in messages] == [
        None,
        "migration-v2-question",
        "migration-v2-answer-1",
    ]
    assert conversation.current_message_id == "migration-v2-answer-2"
    assert conversation.path_revision == 3
    assert feedback.response_digest == sha256(b"Second answer.").hexdigest()


async def test_backfill_reports_non_contiguous_history(postgres_session_factory):
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            WorkspaceORM(
                workspace_id="migration-v2-gap-workspace",
                owner_user_id="migration-v2-gap-owner",
                name="Migration V2 Gap",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        db.add(
            ConversationORM(
                conversation_id="migration-v2-gap-conversation",
                user_id="migration-v2-gap-owner",
                workspace_id="migration-v2-gap-workspace",
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        await db.execute(text("""
            INSERT INTO chat_messages
                (message_id, conversation_id, position, role, content, source_contexts, created_at)
            VALUES (:message_id, :conversation_id, :position, :role, :content,
                    CAST(:source_contexts AS jsonb), :created_at)
        """), [
            {'message_id': "migration-v2-gap-question", 'conversation_id': "migration-v2-gap-conversation", 'position': 0, 'role': "user", 'content': "Question", 'created_at': now, 'source_contexts': '[]'},
            {'message_id': "migration-v2-gap-answer", 'conversation_id': "migration-v2-gap-conversation", 'position': 2, 'role': "assistant", 'content': "Answer", 'created_at': now, 'source_contexts': '[]'},
        ])

    async with postgres_session_factory() as db:
        report = await backfill_conversation(db, "migration-v2-gap-conversation")

    assert report.unresolved == [
        {
            "kind": "conversation",
            "record_id": "migration-v2-gap-conversation",
            "reason": "message position is not zero-contiguous",
        }
    ]
