"""Retire the legacy Chat storage after the history backfill and archive."""

from alembic import context, op
from sqlalchemy import text


revision = "b71000000007"
down_revision = "b71000000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        LOCK TABLE chat_conversations, chat_messages, chat_tool_calls
            IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE workspaces, feedback_datasets, analysis_jobs
            IN ACCESS EXCLUSIVE MODE;
    """)
    archived = context.get_x_argument(as_dictionary=True).get("chat_history_archived")
    if archived != "true" and op.get_bind().scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM chat_conversations
            WHERE response_snapshot IS NOT NULL AND response_snapshot <> 'null'::jsonb
               OR parent_session_id IS NOT NULL
        ) OR EXISTS (SELECT 1 FROM chat_tool_calls)
          OR EXISTS (
              SELECT 1 FROM chat_messages
              WHERE tool_requests <> '[]'::jsonb OR tool_call_id IS NOT NULL
                 OR (tool_result IS NOT NULL AND tool_result <> 'null'::jsonb)
          )
          OR EXISTS (SELECT 1 FROM analysis_jobs)
          OR EXISTS (SELECT 1 FROM feedback_datasets)
          OR EXISTS (SELECT 1 FROM feedback_cases)
          OR EXISTS (SELECT 1 FROM feedback_dataset_snapshots)
    """)):
        raise RuntimeError(
            "Review the Chat backfill report and verify the archive before retirement. "
            "See backend/docs/runbooks/chat-retirement.md."
        )

    op.execute("""

        -- Legacy-only conversations have no selected path or parent edges.
        -- Their existing positions recover the original order.
        WITH linear AS (
            SELECT m.message_id,
                   lag(m.message_id) OVER (
                       PARTITION BY m.conversation_id ORDER BY m.position
                   ) AS parent_message_id
            FROM chat_messages AS m
            JOIN chat_conversations AS c USING (conversation_id)
            WHERE c.current_message_id IS NULL AND c.current_task_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM chat_messages AS child
                  WHERE child.conversation_id = c.conversation_id
                    AND child.parent_message_id IS NOT NULL
              )
        )
        UPDATE chat_messages AS m
        SET parent_message_id = linear.parent_message_id
        FROM linear
        WHERE m.message_id = linear.message_id
          AND linear.parent_message_id IS NOT NULL;

        UPDATE chat_conversations AS c
        SET current_message_id = (
                SELECT m.message_id FROM chat_messages AS m
                WHERE m.conversation_id = c.conversation_id
                ORDER BY m.position DESC LIMIT 1
            ),
            path_revision = path_revision + 1
        WHERE c.current_message_id IS NULL AND c.current_task_id IS NULL
          AND EXISTS (
              SELECT 1 FROM chat_messages AS m
              WHERE m.conversation_id = c.conversation_id
          );

        UPDATE chat_conversations AS c
        SET forked_from_message_id = m.message_id
        FROM chat_messages AS m
        JOIN chat_conversations AS parent USING (conversation_id)
        WHERE c.forked_from_message_id IS NULL
          AND c.parent_session_id = parent.conversation_id
          AND c.fork_message_id = m.message_id
          AND c.user_id = parent.user_id
          AND c.workspace_id = parent.workspace_id;

        ALTER INDEX ix_chat_sessions_user_collection_updated
            RENAME TO ix_chat_sessions_user_workspace_updated;

        ALTER INDEX ix_comparison_group_collection_id RENAME TO ix_comparison_group_workspace_id;
        ALTER INDEX ix_documents_collection_id RENAME TO ix_documents_workspace_id;
        ALTER TABLE documents
            RENAME CONSTRAINT uq_documents_collection_content TO uq_documents_workspace_content;
        ALTER TABLE documents
            RENAME CONSTRAINT uq_documents_collection_order TO uq_documents_workspace_order;
        ALTER INDEX ix_evaluation_gold_sets_collection_id RENAME TO ix_evaluation_gold_sets_workspace_id;
        ALTER INDEX ix_evaluation_snapshots_collection RENAME TO ix_evaluation_snapshots_workspace;
        ALTER INDEX ix_evaluation_runs_collection RENAME TO ix_evaluation_runs_workspace;
        ALTER INDEX ix_finding_collection_id RENAME TO ix_finding_workspace_id;
        ALTER INDEX ix_finding_curation_records_collection_id RENAME TO ix_finding_curation_records_workspace_id;
        ALTER INDEX ix_finding_feedback_records_collection_id RENAME TO ix_finding_feedback_records_workspace_id;
        ALTER INDEX ix_objective_experiment_plans_collection_id RENAME TO ix_objective_experiment_plans_workspace_id;
        ALTER INDEX ix_objective_experiment_selection_collection_id RENAME TO ix_objective_experiment_selection_workspace_id;
        ALTER INDEX ix_pipeline_runs_collection_id RENAME TO ix_pipeline_runs_workspace_id;
        ALTER INDEX ix_collections_owner_user_id RENAME TO ix_workspaces_owner_user_id;

        DROP TABLE
            feedback_export_members,
            feedback_dataset_exports,
            feedback_export_previews,
            feedback_sample_actions,
            feedback_sample_revisions,
            feedback_dataset_samples,
            feedback_dataset_migration_runs,
            feedback_datasets,
            feedback_dataset_snapshots,
            feedback_review_decisions,
            feedback_annotations,
            feedback_cases,
            feedback_analysis_results,
            feedback_signal_analysis_results,
            tool_failure_analysis_results,
            analysis_jobs,
            chat_tool_calls
        RESTRICT;
        ALTER TABLE chat_messages
            DROP COLUMN position RESTRICT,
            DROP COLUMN tool_requests RESTRICT,
            DROP COLUMN tool_call_id RESTRICT,
            DROP COLUMN tool_result RESTRICT;
        ALTER TABLE chat_conversations
            DROP COLUMN response_snapshot RESTRICT,
            DROP COLUMN operation_permission RESTRICT,
            DROP COLUMN root_session_id RESTRICT,
            DROP COLUMN parent_session_id RESTRICT,
            DROP COLUMN fork_message_id RESTRICT,
            DROP COLUMN fork_position RESTRICT,
            DROP COLUMN fork_content RESTRICT;
        ALTER TABLE workspaces DROP COLUMN agent_default_permission RESTRICT;
    """)


def downgrade() -> None:
    raise RuntimeError("Restore the pre-retirement PostgreSQL backup.")
