from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_chat_tree_schema_is_present(postgres_sync_engine) -> None:
    inspector = inspect(postgres_sync_engine)
    tables = set(inspector.get_table_names())
    assert {
        "agent_tasks",
        "agent_operations",
        "agent_task_steps",
    } <= tables

    session_columns = {item["name"] for item in inspector.get_columns("chat_sessions")}
    assert {
        "current_message_id",
        "current_task_id",
        "path_revision",
        "forked_from_message_id",
        "fork_request_id",
    } <= session_columns

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
                INSERT INTO chat_sessions
                    (session_id, user_id, collection_id, created_at, updated_at)
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
                    (message_id, session_id, position, role, content, created_at)
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
                            (message_id, session_id, position, parent_message_id,
                             role, content, created_at)
                        VALUES ('tree-b-child', 'tree-b', 1, 'tree-a-question',
                                'assistant', 'Invalid parent', :now)
                        """
                    ),
                    {"now": now},
                )
        finally:
            savepoint.rollback()

        savepoint = connection.begin_nested()
        try:
            with pytest.raises(IntegrityError, match="chat_message_task_same_session"):
                connection.execute(
                    text(
                        """
                        INSERT INTO chat_messages
                            (message_id, session_id, position, parent_message_id,
                             produced_by_task_id, role, content, created_at)
                        VALUES ('tree-b-produced', 'tree-b', 1, 'tree-b-question',
                                'tree-task-a', 'assistant', 'Invalid task', :now)
                        """
                    ),
                    {"now": now},
                )
        finally:
            savepoint.rollback()
