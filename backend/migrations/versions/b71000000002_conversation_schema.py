"""Name Conversation storage in place and scope feedback to its message."""

from alembic import op


revision = "b71000000002"
down_revision = "b71000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        LOCK TABLE chat_sessions IN ACCESS EXCLUSIVE MODE;

        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM chat_sessions WHERE fork_request_id IS NOT NULL) THEN
                RAISE EXCEPTION 'Cannot remove populated chat_sessions.fork_request_id';
            END IF;
        END $$;

        ALTER TABLE chat_sessions DROP COLUMN fork_request_id;
        ALTER TABLE chat_sessions RENAME TO chat_conversations;
        ALTER TABLE chat_conversations RENAME COLUMN session_id TO conversation_id;
        ALTER TABLE chat_conversations RENAME COLUMN collection_id TO workspace_id;
        ALTER TABLE chat_messages RENAME COLUMN session_id TO conversation_id;
        ALTER TABLE chat_message_feedback RENAME COLUMN session_id TO conversation_id;

        ALTER INDEX ix_chat_sessions_collection_id RENAME TO ix_chat_conversations_workspace_id;
        ALTER INDEX ix_chat_sessions_root_session_id RENAME TO ix_chat_conversations_root_session_id;
        ALTER INDEX ix_chat_sessions_user_id RENAME TO ix_chat_conversations_user_id;
        ALTER INDEX ix_chat_messages_session_id RENAME TO ix_chat_messages_conversation_id;
        ALTER INDEX ix_chat_message_feedback_session_id RENAME TO ix_chat_message_feedback_conversation_id;

        ALTER TABLE chat_message_feedback
            ADD CONSTRAINT chat_feedback_message_same_conversation
            FOREIGN KEY (conversation_id, message_id)
            REFERENCES chat_messages (conversation_id, message_id) ON DELETE CASCADE;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE chat_message_feedback
            DROP CONSTRAINT chat_feedback_message_same_conversation;

        ALTER INDEX ix_chat_message_feedback_conversation_id RENAME TO ix_chat_message_feedback_session_id;
        ALTER INDEX ix_chat_messages_conversation_id RENAME TO ix_chat_messages_session_id;
        ALTER INDEX ix_chat_conversations_user_id RENAME TO ix_chat_sessions_user_id;
        ALTER INDEX ix_chat_conversations_root_session_id RENAME TO ix_chat_sessions_root_session_id;
        ALTER INDEX ix_chat_conversations_workspace_id RENAME TO ix_chat_sessions_collection_id;

        ALTER TABLE chat_message_feedback RENAME COLUMN conversation_id TO session_id;
        ALTER TABLE chat_messages RENAME COLUMN conversation_id TO session_id;
        ALTER TABLE chat_conversations RENAME COLUMN workspace_id TO collection_id;
        ALTER TABLE chat_conversations RENAME COLUMN conversation_id TO session_id;
        ALTER TABLE chat_conversations RENAME TO chat_sessions;
        ALTER TABLE chat_sessions ADD COLUMN fork_request_id uuid;
        CREATE UNIQUE INDEX chat_fork_request_unique ON chat_sessions (user_id, fork_request_id)
            WHERE fork_request_id IS NOT NULL;
    """)
