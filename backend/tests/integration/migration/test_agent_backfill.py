"""Replay the deployed Chat snapshot format through the retirement revision."""

from argparse import Namespace
from hashlib import sha256

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from scripts.backfill_agent_tasks import run, stable_task_id
from scripts.backfill_conversations import backfill_conversation


@pytest.mark.anyio
@pytest.mark.parametrize("postgres_sync_engine", ["b71000000006"], indirect=True)
async def test_retirement_replays_real_chat_history(
    postgres_sync_engine, postgres_session_factory
):
    digest = sha256(b"The second paper used 650 C.").hexdigest()
    async with postgres_session_factory.begin() as db:
        await db.execute(text("""
            INSERT INTO workspaces (workspace_id, owner_user_id, name, status, created_at, updated_at)
            VALUES ('papers', 'researcher', 'Heat treatments', 'idle', now(), now())
        """))
        await db.execute(text("""
            INSERT INTO chat_conversations
                (conversation_id, workspace_id, user_id, created_at, updated_at, response_snapshot)
            VALUES
                ('comparison', 'papers', 'researcher', now(), now(),
                 '{"response_id":"response_old","sequence": 4,"status":"completed",
                   "checkpoint_message_id":"answer","message_id": null,"completion_reason":"model_answer"}'),
                ('uncertain', 'papers', 'researcher', now(), now(),
                 '{"response_id":"response_ambiguous","status":"interrupted","message_id":"streamed"}')
        """))
        await db.execute(text("""
            INSERT INTO chat_messages (message_id, conversation_id, position, role, content, created_at)
            VALUES ('question', 'comparison', 0, 'user', 'Compare the heat treatments.', now()),
                   ('request', 'comparison', 1, 'assistant', '', now()),
                   ('answer', 'comparison', 2, 'assistant', 'The second paper used 650 C.', now())
        """))
        await db.execute(text("""
            INSERT INTO chat_message_feedback
                (feedback_id, conversation_id, message_id, user_id, rating, response_digest, created_at, updated_at)
            VALUES ('rating', 'comparison', 'answer', 'researcher', 'helpful', :digest, now(), now())
        """), {"digest": digest})
        await db.execute(text("""
            INSERT INTO chat_tool_calls
                (tool_call_id, assistant_message_id, session_id, name, position, arguments,
                 arguments_digest, risk, status, started_at)
            VALUES ('call-unknown', 'request', 'comparison', 'create_research_plan', 0, '{}',
                    :digest, 'write', 'running', now())
        """), {"digest": sha256(b"{}").hexdigest()})
        await db.execute(text("""
            INSERT INTO chat_model_calls
                (call_id, session_id, trigger_message_id, response_message_id, purpose,
                 model, request, request_digest, status, started_at)
            VALUES ('provider-call', 'comparison', 'question', 'answer', 'decision',
                    'fixture-model', '{}', :digest, 'provider_succeeded', now())
        """), {"digest": sha256(b"{}").hexdigest()})

    async with postgres_session_factory() as db:
        result = await backfill_conversation(db, "comparison")
        assert not result.unresolved
    task_id = stable_task_id("response_old")
    async with postgres_session_factory() as db:
        report = await run(db)
        assert report.created_task_ids == [task_id]
        assert report.linked_model_call_ids == ["provider-call"]
        assert len(report.reconciliation_operation_ids) == 1
        assert report.unresolved_response_ids == ["response_ambiguous"]
        repeated = await run(db)
        assert not repeated.created_task_ids
        assert not repeated.created_operation_ids

    config = Config("alembic.ini")
    with pytest.raises(RuntimeError, match="verify the archive"):
        with postgres_sync_engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")

    config.cmd_opts = Namespace(x=["chat_history_archived=true"])
    with postgres_sync_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")

    with postgres_sync_engine.connect() as conn:
        inspector = inspect(conn)
        assert not inspector.has_table("chat_sessions")
        assert not inspector.has_table("chat_tool_calls")
        assert not inspector.has_table("feedback_cases")
        assert not inspector.has_table("analysis_jobs")
        assert {"position", "tool_requests"}.isdisjoint(
            column["name"] for column in inspector.get_columns("chat_messages")
        )
        assert conn.execute(text("""
            SELECT t.task_id, m.parent_message_id, f.response_digest, o.status, call.sequence
            FROM agent_tasks AS t
            JOIN chat_messages AS m ON m.message_id = t.final_message_id
            JOIN chat_message_feedback AS f ON f.message_id = m.message_id
            JOIN agent_operations AS o ON o.task_id = t.task_id
            JOIN chat_model_calls AS call ON call.task_id = t.task_id
        """)).one() == (task_id, "request", digest, "needs_reconciliation", 0)
