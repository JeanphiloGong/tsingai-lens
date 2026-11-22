from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from conversation.repositories import conversation_repository
from infra.persistence.postgres.models.chat import AgentTaskORM
from infra.persistence.postgres.models.conversation import (
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)


def test_conversation_schema_is_present(postgres_sync_engine) -> None:
    inspector = inspect(postgres_sync_engine)
    tables = set(inspector.get_table_names())
    assert {
        "agent_tasks",
        "agent_operations",
        "agent_task_steps",
    } <= tables

    assert "chat_sessions" not in tables
    conversation_columns = {
        item["name"] for item in inspector.get_columns("chat_conversations")
    }
    assert conversation_columns >= {
        "conversation_id",
        "workspace_id",
        "current_message_id",
        "current_task_id",
        "path_revision",
        "forked_from_message_id",
    }
    assert "fork_request_id" not in conversation_columns

    message_columns = {item["name"] for item in inspector.get_columns("chat_messages")}
    assert {
        "parent_message_id",
        "produced_by_task_id",
        "copied_from_message_id",
        "operation_id",
        "tool_requests",
        "tool_result",
    } <= message_columns

    task_constraints = {
        item["name"] for item in inspector.get_check_constraints("agent_tasks")
    }
    assert all(
        any(name.endswith(expected) for name in task_constraints)
        for expected in (
            "chat_task_trigger_kind_valid",
            "chat_task_status_valid",
            "chat_task_digest_length",
        )
    )


def test_chat_tree_rejects_cross_conversation_links(postgres_sync_engine) -> None:
    now = datetime.now(timezone.utc)
    request_id = str(uuid4())
    with postgres_sync_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO collections
                    (collection_id, owner_user_id, name, status, created_at, updated_at)
                VALUES ('tree-workspace', 'tree-user', 'Tree fixture', 'idle', :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO chat_conversations
                    (conversation_id, user_id, workspace_id, created_at, updated_at)
                VALUES ('tree-a', 'tree-user', 'tree-workspace', :now, :now),
                       ('tree-b', 'tree-user', 'tree-workspace', :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO chat_messages
                    (message_id, conversation_id, position, role, content, created_at)
                VALUES ('tree-a-question', 'tree-a', 0, 'user', 'Question', :now),
                       ('tree-b-question', 'tree-b', 0, 'user', 'Question', :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO agent_tasks
                    (task_id, session_id, trigger_kind, trigger_message_id,
                     request_id, request_digest, status, started_at, updated_at)
                VALUES ('tree-task-a', 'tree-a', 'user_message', 'tree-a-question',
                        CAST(:request AS uuid), :digest, 'accepted', :now, :now)
                """
            ),
            {"request": request_id, "digest": "a" * 64, "now": now},
        )

        savepoint = connection.begin_nested()
        try:
            with pytest.raises(IntegrityError, match="chat_message_parent_same_session"):
                connection.execute(
                    text(
                        """
                        INSERT INTO chat_messages
                            (message_id, conversation_id, position, parent_message_id,
                             role, content, created_at)
                        VALUES ('tree-b-child', 'tree-b', 1, 'tree-a-question',
                                'assistant', 'Invalid parent', :now)
                        """
                    ),
                    {"now": now},
                )
        finally:
            savepoint.rollback()

        with pytest.raises(IntegrityError, match="chat_message_task_same_session"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO chat_messages
                        (message_id, conversation_id, position, parent_message_id,
                         produced_by_task_id, role, content, created_at)
                    VALUES ('tree-b-produced', 'tree-b', 1, 'tree-b-question',
                            'tree-task-a', 'assistant', 'Invalid task', :now)
                """), {"now": now})

        with pytest.raises(IntegrityError, match="chat_feedback_message_same_conversation"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO chat_message_feedback
                        (feedback_id, conversation_id, message_id, user_id, rating,
                         response_digest, created_at, updated_at)
                    VALUES ('invalid-feedback', 'tree-b', 'tree-a-question', 'tree-user',
                            'helpful', repeat('a', 64), :now, :now)
                """), {"now": now})


@pytest.mark.anyio
async def test_read_selected_branch_with_scoped_feedback(
    postgres_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(conversation_repository, "AsyncSessionLocal", postgres_session_factory)
    now = datetime.now(timezone.utc)
    async with postgres_session_factory.begin() as db:
        await db.execute(text("""
            INSERT INTO collections
                (collection_id, owner_user_id, name, status, created_at, updated_at)
            VALUES ('workspace-a', 'owner', 'Research papers', 'idle', :now, :now),
                   ('workspace-b', 'other', 'Other papers', 'idle', :now, :now)
        """), {"now": now})
        db.add_all([
            ConversationORM(conversation_id="thread", workspace_id="workspace-a",
                            user_id="owner", path_revision=3, created_at=now, updated_at=now),
            ConversationORM(conversation_id="empty", workspace_id="workspace-a",
                            user_id="owner", created_at=now, updated_at=now),
            ConversationORM(conversation_id="wrong-workspace", workspace_id="workspace-b",
                            user_id="owner", created_at=now, updated_at=now),
        ])
        await db.flush()
        db.add(MessageORM(
            message_id="question", conversation_id="thread", role="user", position=0,
            content="Compare the reported heat treatment conditions.",
            source_contexts=[{"document_id": "paper-a", "source_ref": "methods"}],
            created_at=now,
        ))
        await db.flush()
        db.add_all([
            MessageORM(message_id="first", conversation_id="thread", parent_message_id="question",
                       position=1, role="assistant", content="First answer", created_at=now),
            MessageORM(message_id="retry", conversation_id="thread", parent_message_id="question",
                       position=2, role="assistant", content="Retry answer", created_at=now),
        ])
        await db.flush()
        thread = await db.get(ConversationORM, "thread")
        thread.current_message_id = "retry"
        db.add_all([
            MessageFeedbackORM(feedback_id="mine", conversation_id="thread", message_id="retry",
                               user_id="owner", rating="helpful", response_digest="a" * 64,
                               created_at=now, updated_at=now),
            MessageFeedbackORM(feedback_id="other", conversation_id="thread", message_id="retry",
                               user_id="other", rating="not_helpful", response_digest="a" * 64,
                               created_at=now, updated_at=now),
        ])

    repository = conversation_repository.ConversationRepository()
    result = await repository.read_current_path(conversation_id="thread", user_id="owner")
    assert result.conversation.path_revision == 3
    assert result.path.tip_message_id == "retry"
    assert [item.message.message_id for item in result.items] == ["question", "retry"]
    assert result.items[0].source_contexts[0]["source_ref"] == "methods"
    assert result.items[0].my_feedback is None
    assert result.items[-1].my_feedback.feedback_id == "mine"

    async with postgres_session_factory.begin() as db:
        task = AgentTaskORM(
            task_id="retry-task", session_id="thread", trigger_kind="retry",
            trigger_message_id="question", request_id=str(uuid4()),
            request_digest="a" * 64, status="running",
            started_at=now, updated_at=now,
        )
        db.add(task)
        await db.flush()
        answer = await db.get(MessageORM, "retry")
        answer.produced_by_task_id = task.task_id
        await db.flush()
        task.checkpoint_message_id = "retry"
        thread = await db.get(ConversationORM, "thread")
        thread.current_message_id = None
        thread.current_task_id = "retry-task"
        thread.path_revision = 4

    task_result = await repository.read_current_path(conversation_id="thread", user_id="owner")
    assert task_result.path.tip_message_id == "retry"
    assert [item.message.message_id for item in task_result.items] == ["question", "retry"]
    assert task_result.items[-1].message.produced_by_task_id == "retry-task"
    assert task_result.items[-1].my_feedback == result.items[-1].my_feedback
    assert task_result.conversation.path_revision == 4

    result = await repository.read_current_path(conversation_id="empty", user_id="owner")
    assert result.path.tip_message_id is None
    assert result.items == ()

    with pytest.raises(conversation_repository.ConversationNotFound):
        await repository.read_current_path(conversation_id="thread", user_id="other")
    with pytest.raises(conversation_repository.ConversationNotFound):
        await repository.read_current_path(conversation_id="wrong-workspace", user_id="owner")


def test_conversation_rename_round_trip_preserves_history(postgres_sync_engine) -> None:
    config = Config("alembic.ini")
    with postgres_sync_engine.begin() as db:
        config.attributes["connection"] = db
        command.downgrade(config, "b71000000001")
        db.execute(text("""
            INSERT INTO collections
                (collection_id, owner_user_id, name, status, created_at, updated_at)
            VALUES ('workspace', 'owner', 'Research papers', 'idle', now(), now());
            INSERT INTO chat_sessions (session_id, collection_id, user_id, created_at, updated_at)
            VALUES ('thread', 'workspace', 'owner', now(), now());
            INSERT INTO chat_messages (message_id, session_id, position, role, content, created_at)
            VALUES ('question', 'thread', 0, 'user', 'Compare the papers', now()),
                   ('answer', 'thread', 1, 'assistant', 'Comparison', now());
            INSERT INTO chat_message_feedback
                (feedback_id, session_id, message_id, user_id, rating, response_digest,
                 created_at, updated_at)
            VALUES ('feedback', 'thread', 'answer', 'owner', 'helpful', repeat('a', 64),
                    now(), now());
        """))
        for _ in range(2):
            command.upgrade(config, "head")
            assert db.execute(select(ConversationORM.workspace_id)).scalar_one() == "workspace"
            assert db.execute(
                select(MessageORM.conversation_id, MessageORM.content).where(
                    MessageORM.message_id == "answer"
                )
            ).one() == ("thread", "Comparison")
            assert db.execute(
                select(MessageFeedbackORM.conversation_id, MessageFeedbackORM.message_id)
            ).one() == ("thread", "answer")
            command.downgrade(config, "b71000000001")
            assert db.execute(text(
                "SELECT session_id, message_id FROM chat_message_feedback"
            )).one() == ("thread", "answer")

        fork_request_id = uuid4()
        db.execute(text("UPDATE chat_sessions SET fork_request_id = :request_id"),
                   {"request_id": fork_request_id})
        with pytest.raises(DBAPIError, match="Cannot remove populated"):
            with db.begin_nested():
                command.upgrade(config, "head")
        assert db.scalar(text("SELECT fork_request_id FROM chat_sessions")) == fork_request_id
