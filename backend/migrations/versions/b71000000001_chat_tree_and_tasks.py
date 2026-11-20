"""Add durable Chat tree and Task storage alongside the legacy trajectory."""

from alembic import op
from sqlalchemy import inspect


revision = "b71000000001"
down_revision = "20261118_0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if {
        "agent_tasks",
        "agent_operations",
        "agent_task_steps",
    } <= tables:
        session_columns = {
            column["name"] for column in inspector.get_columns("chat_sessions")
        }
        message_columns = {
            column["name"] for column in inspector.get_columns("chat_messages")
        }
        if {
            "current_message_id",
            "current_task_id",
            "path_revision",
            "forked_from_message_id",
            "fork_request_id",
        } <= session_columns and {
            "parent_message_id",
            "produced_by_task_id",
            "copied_from_message_id",
            "operation_id",
            "tool_requests",
            "tool_result",
        } <= message_columns:
            model_call_columns = {
                column["name"]
                for column in inspector.get_columns("chat_model_calls")
            }
            if {"task_id", "sequence"} - model_call_columns:
                op.execute(
                    """
                    ALTER TABLE chat_model_calls
                        ADD COLUMN task_id varchar(128),
                        ADD COLUMN sequence integer,
                        ADD CONSTRAINT chat_model_call_task_sequence
                            UNIQUE (task_id, sequence),
                        ADD CONSTRAINT chat_model_call_task_same_session
                            FOREIGN KEY (session_id, task_id)
                            REFERENCES agent_tasks (session_id, task_id),
                        ADD CONSTRAINT chat_model_call_sequence_non_negative
                            CHECK (sequence IS NULL OR sequence >= 0);
                    """
                )
            return

    op.execute(
        """
        ALTER TABLE chat_sessions
            ADD COLUMN current_message_id varchar(128),
            ADD COLUMN current_task_id varchar(128),
            ADD COLUMN path_revision bigint NOT NULL DEFAULT 0,
            ADD COLUMN forked_from_message_id varchar(128),
            ADD COLUMN fork_request_id uuid,
            ADD CONSTRAINT chat_path_selection_valid
                CHECK (num_nonnulls(current_message_id, current_task_id) <= 1),
            ADD CONSTRAINT chat_path_revision_valid
                CHECK (path_revision >= 0);
        CREATE UNIQUE INDEX chat_fork_request_unique
            ON chat_sessions (user_id, fork_request_id)
            WHERE fork_request_id IS NOT NULL;
        CREATE INDEX chat_fork_source_idx
            ON chat_sessions (forked_from_message_id);

        ALTER TABLE chat_messages
            ADD COLUMN parent_message_id varchar(128),
            ADD COLUMN produced_by_task_id varchar(128),
            ADD COLUMN copied_from_message_id varchar(128),
            ADD COLUMN operation_id varchar(128),
            ADD COLUMN tool_requests jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN tool_result jsonb,
            ADD CONSTRAINT chat_message_in_session_unique
                UNIQUE (session_id, message_id),
            ADD CONSTRAINT chat_message_task_unique
                UNIQUE (produced_by_task_id, message_id),
            ADD CONSTRAINT chat_message_parent_same_session
                FOREIGN KEY (session_id, parent_message_id)
                REFERENCES chat_messages (session_id, message_id),
            ADD CONSTRAINT chat_message_parent_not_self
                CHECK (parent_message_id IS NULL OR parent_message_id <> message_id),
            ADD CONSTRAINT chat_user_message_has_no_producer
                CHECK (role <> 'user' OR produced_by_task_id IS NULL);
        CREATE INDEX chat_message_children_idx
            ON chat_messages (session_id, parent_message_id);

        CREATE TABLE agent_tasks (
            task_id varchar(128) PRIMARY KEY,
            session_id varchar(128) NOT NULL
                CONSTRAINT fk_agent_tasks_session_id_chat_sessions
                REFERENCES chat_sessions ON DELETE CASCADE,
            trigger_kind varchar(32) NOT NULL
                CONSTRAINT chat_task_trigger_kind_valid
                CHECK (trigger_kind IN
                    ('user_message', 'approval', 'retry', 'schedule', 'system')),
            trigger_message_id varchar(128),
            final_message_id varchar(128),
            checkpoint_message_id varchar(128),
            request_id uuid NOT NULL,
            request_digest varchar(64) NOT NULL
                CONSTRAINT chat_task_digest_length
                CHECK (length(request_digest) = 64),
            status varchar(32) NOT NULL
                CONSTRAINT chat_task_status_valid
                CHECK (status IN
                    ('accepted', 'running', 'approval_required', 'completed',
                     'failed', 'interrupted', 'cancelled')),
            checkpoint_revision bigint NOT NULL DEFAULT 0
                CONSTRAINT chat_task_checkpoint_revision_valid
                CHECK (checkpoint_revision >= 0),
            checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
            model_connection_id varchar(64),
            model_connection_name text,
            started_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            finished_at timestamptz,
            CONSTRAINT agent_tasks_session_task_unique UNIQUE (session_id, task_id),
            CONSTRAINT agent_tasks_request_unique UNIQUE (session_id, request_id),
            CONSTRAINT agent_tasks_trigger_message_same_session
                FOREIGN KEY (session_id, trigger_message_id)
                REFERENCES chat_messages (session_id, message_id),
            CONSTRAINT agent_tasks_checkpoint_message_same_task
                FOREIGN KEY (task_id, checkpoint_message_id)
                REFERENCES chat_messages (produced_by_task_id, message_id),
            CONSTRAINT agent_tasks_final_message_same_task
                FOREIGN KEY (task_id, final_message_id)
                REFERENCES chat_messages (produced_by_task_id, message_id),
            CONSTRAINT chat_task_trigger_message_required CHECK (
                trigger_kind NOT IN ('user_message', 'retry')
                OR trigger_message_id IS NOT NULL
            ),
            CONSTRAINT chat_task_completed_message_valid
                CHECK ((status = 'completed') = (final_message_id IS NOT NULL)),
            CONSTRAINT chat_task_timestamps_valid CHECK (updated_at >= started_at),
            CONSTRAINT chat_task_finished_at_valid
                CHECK (finished_at IS NULL OR finished_at >= started_at)
        );
        CREATE INDEX agent_active_task_idx
            ON agent_tasks (session_id, status, updated_at);

        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_message_task_same_session
                FOREIGN KEY (session_id, produced_by_task_id)
                REFERENCES agent_tasks (session_id, task_id);
        ALTER TABLE chat_sessions
            ADD CONSTRAINT chat_current_message_same_session
                FOREIGN KEY (session_id, current_message_id)
                REFERENCES chat_messages (session_id, message_id),
            ADD CONSTRAINT chat_current_task_same_session
                FOREIGN KEY (session_id, current_task_id)
                REFERENCES agent_tasks (session_id, task_id),
            ADD CONSTRAINT chat_fork_source_fk
                FOREIGN KEY (forked_from_message_id)
                REFERENCES chat_messages (message_id);

        CREATE TABLE agent_operations (
            operation_id varchar(128) PRIMARY KEY,
            task_id varchar(128) NOT NULL
                CONSTRAINT fk_agent_operations_task_id_agent_tasks
                REFERENCES agent_tasks ON DELETE CASCADE,
            tool_call_id varchar(128),
            assistant_message_id varchar(128),
            name varchar(128) NOT NULL,
            arguments jsonb NOT NULL,
            arguments_digest varchar(64) NOT NULL
                CONSTRAINT chat_operation_arguments_digest_length
                CHECK (length(arguments_digest) = 64),
            risk varchar(16) NOT NULL
                CONSTRAINT chat_operation_risk_valid
                CHECK (risk IN ('read', 'draft', 'write', 'unknown')),
            status varchar(32) NOT NULL
                CONSTRAINT chat_operation_status_valid
                CHECK (status IN
                    ('requested', 'approval_required', 'approved', 'running',
                     'succeeded', 'failed', 'rejected', 'needs_reconciliation')),
            idempotency_key varchar(128),
            result jsonb,
            error_code varchar(128),
            error_message text,
            decision_user_id varchar(64),
            decision_arguments_digest varchar(64),
            decided_at timestamptz,
            started_at timestamptz,
            finished_at timestamptz,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT chat_operation_task_operation_unique
                UNIQUE (task_id, operation_id),
            CONSTRAINT chat_operation_task_tool_call_unique
                UNIQUE (task_id, tool_call_id),
            CONSTRAINT chat_operation_assistant_message_same_task
                FOREIGN KEY (task_id, assistant_message_id)
                REFERENCES chat_messages (produced_by_task_id, message_id),
            CONSTRAINT chat_operation_decision_digest_valid CHECK (
                decision_arguments_digest IS NULL
                OR decision_arguments_digest = arguments_digest
            ),
            CONSTRAINT chat_operation_timestamps_valid CHECK (updated_at >= created_at),
            CONSTRAINT chat_operation_finished_at_valid
                CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
        );
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_message_operation_same_task
                FOREIGN KEY (produced_by_task_id, operation_id)
                REFERENCES agent_operations (task_id, operation_id);

        CREATE TABLE agent_task_steps (
            step_id varchar(128) PRIMARY KEY,
            task_id varchar(128) NOT NULL
                CONSTRAINT chat_task_step_task_fk
                REFERENCES agent_tasks ON DELETE CASCADE,
            sequence integer NOT NULL
                CONSTRAINT chat_task_step_sequence_valid CHECK (sequence >= 0),
            name varchar(128) NOT NULL,
            status varchar(24) NOT NULL
                CONSTRAINT chat_task_step_status_valid
                CHECK (status IN ('pending', 'running', 'completed', 'blocked')),
            checkpoint jsonb NOT NULL,
            started_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT chat_task_step_sequence_unique UNIQUE (task_id, sequence),
            CONSTRAINT chat_task_step_finished_at_valid
                CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
        );

        ALTER TABLE chat_model_calls
            ADD COLUMN task_id varchar(128),
            ADD COLUMN sequence integer,
            ADD CONSTRAINT chat_model_call_task_sequence
                UNIQUE (task_id, sequence),
            ADD CONSTRAINT chat_model_call_task_same_session
                FOREIGN KEY (session_id, task_id)
                REFERENCES agent_tasks (session_id, task_id),
            ADD CONSTRAINT chat_model_call_sequence_non_negative
                CHECK (sequence IS NULL OR sequence >= 0);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_model_calls
            DROP CONSTRAINT IF EXISTS chat_model_call_sequence_non_negative,
            DROP CONSTRAINT IF EXISTS chat_model_call_task_sequence,
            DROP CONSTRAINT IF EXISTS chat_model_call_task_same_session,
            DROP COLUMN IF EXISTS sequence,
            DROP COLUMN IF EXISTS task_id;
        DROP INDEX IF EXISTS agent_active_task_idx;
        DROP TABLE IF EXISTS agent_task_steps;
        ALTER TABLE chat_messages
            DROP CONSTRAINT IF EXISTS chat_message_operation_same_task;
        DROP TABLE IF EXISTS agent_operations;
        ALTER TABLE chat_sessions
            DROP CONSTRAINT IF EXISTS chat_current_task_same_session,
            DROP CONSTRAINT IF EXISTS chat_current_message_same_session,
            DROP CONSTRAINT IF EXISTS chat_fork_source_fk;
        ALTER TABLE chat_messages
            DROP CONSTRAINT IF EXISTS chat_message_task_same_session;
        DROP TABLE IF EXISTS agent_tasks;
        DROP INDEX IF EXISTS chat_message_children_idx;
        ALTER TABLE chat_messages
            DROP CONSTRAINT IF EXISTS chat_message_parent_same_session,
            DROP CONSTRAINT IF EXISTS chat_message_parent_not_self,
            DROP CONSTRAINT IF EXISTS chat_user_message_has_no_producer,
            DROP CONSTRAINT IF EXISTS chat_message_task_unique,
            DROP CONSTRAINT IF EXISTS chat_message_in_session_unique,
            DROP COLUMN IF EXISTS parent_message_id,
            DROP COLUMN IF EXISTS produced_by_task_id,
            DROP COLUMN IF EXISTS copied_from_message_id,
            DROP COLUMN IF EXISTS operation_id,
            DROP COLUMN IF EXISTS tool_requests,
            DROP COLUMN IF EXISTS tool_result;
        DROP INDEX IF EXISTS chat_fork_source_idx;
        DROP INDEX IF EXISTS chat_fork_request_unique;
        ALTER TABLE chat_sessions
            DROP CONSTRAINT IF EXISTS chat_path_selection_valid,
            DROP CONSTRAINT IF EXISTS chat_path_revision_valid,
            DROP COLUMN IF EXISTS current_message_id,
            DROP COLUMN IF EXISTS current_task_id,
            DROP COLUMN IF EXISTS path_revision,
            DROP COLUMN IF EXISTS forked_from_message_id,
            DROP COLUMN IF EXISTS fork_request_id;
        """
    )
