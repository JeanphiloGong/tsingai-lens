"""Persist model-call audits and the first feedback-analysis workbench slice."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0071"
down_revision = "20260924_0070"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "chat_model_calls",
        sa.Column("call_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("trigger_message_id", sa.String(length=128), nullable=True),
        sa.Column("response_message_id", sa.String(length=128), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("request", _JSON_DOCUMENT, nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "provider_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.session_id"],
            name="fk_chat_model_calls_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("call_id", name="pk_chat_model_calls"),
        sa.CheckConstraint(
            "purpose IN ('decision', 'compaction', 'finalization')",
            name="chat_model_call_purpose_valid",
        ),
        sa.CheckConstraint(
            "status IN ('recorded', 'provider_succeeded', 'provider_failed', "
            "'response_invalid', 'cancelled')",
            name="chat_model_call_status_valid",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="chat_model_call_digest_length",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="chat_model_call_timestamps_valid",
        ),
    )
    op.create_index(
        "ix_chat_model_calls_session_id", "chat_model_calls", ["session_id"]
    )
    op.create_index(
        "ix_chat_model_calls_trigger_message_id",
        "chat_model_calls",
        ["trigger_message_id"],
    )
    op.create_index(
        "ix_chat_model_calls_response_message_id",
        "chat_model_calls",
        ["response_message_id"],
    )
    op.create_index(
        "ix_chat_model_calls_status", "chat_model_calls", ["status"]
    )

    op.create_table(
        "analysis_jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("payload", _JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id", name="pk_analysis_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_analysis_jobs_idempotency_key"),
        sa.CheckConstraint(
            "payload_version >= 1",
            name="analysis_job_payload_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="analysis_job_status_valid",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="analysis_job_timestamps_valid",
        ),
    )
    op.create_index(
        "ix_analysis_jobs_claim",
        "analysis_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index("ix_analysis_jobs_job_type", "analysis_jobs", ["job_type"])
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])
    op.create_index(
        "ix_analysis_jobs_available_at", "analysis_jobs", ["available_at"]
    )

    op.create_table(
        "feedback_analysis_results",
        sa.Column("result_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("feedback_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("anchor_message_id", sa.String(length=128), nullable=False),
        sa.Column("problem_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("related_message_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("suggested_evidence", _JSON_DOCUMENT, nullable=False),
        sa.Column("suggested_target", sa.Text(), nullable=True),
        sa.Column("evidence_coverage", _JSON_DOCUMENT, nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["analysis_jobs.job_id"],
            name="fk_feedback_analysis_results_job",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.session_id"],
            name="fk_feedback_analysis_results_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name="fk_feedback_analysis_results_collection",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("result_id", name="pk_feedback_analysis_results"),
        sa.UniqueConstraint("job_id", name="uq_feedback_analysis_results_job_id"),
        sa.CheckConstraint(
            "problem_type IN ('fact_error', 'source_missing', 'evidence_mismatch', "
            "'retrieval_failure', 'tool_failure', 'intent_mismatch', "
            "'incomplete_answer', 'style_or_format', 'undetermined_dissatisfaction')",
            name="feedback_analysis_problem_type_valid",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="feedback_analysis_confidence_range",
        ),
        sa.CheckConstraint(
            "length(input_digest) = 64",
            name="feedback_analysis_input_digest_length",
        ),
    )
    op.create_index(
        "ix_feedback_analysis_results_feedback_id",
        "feedback_analysis_results",
        ["feedback_id"],
    )
    op.create_index(
        "ix_feedback_analysis_results_job_id",
        "feedback_analysis_results",
        ["job_id"],
    )
    op.create_index(
        "ix_feedback_analysis_results_session_id",
        "feedback_analysis_results",
        ["session_id"],
    )
    op.create_index(
        "ix_feedback_analysis_results_collection_id",
        "feedback_analysis_results",
        ["collection_id"],
    )
    op.create_index(
        "ix_feedback_analysis_results_anchor_message_id",
        "feedback_analysis_results",
        ["anchor_message_id"],
    )
    op.create_index(
        "ix_feedback_analysis_results_problem_type",
        "feedback_analysis_results",
        ["problem_type"],
    )

    op.create_table(
        "feedback_cases",
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("anchor_message_id", sa.String(length=128), nullable=False),
        sa.Column("source_signal_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("analysis_result_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("context_snapshot", _JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("annotation_digest", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name="fk_feedback_cases_collection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.session_id"],
            name="fk_feedback_cases_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("case_id", name="pk_feedback_cases"),
        sa.UniqueConstraint(
            "session_id",
            "anchor_message_id",
            name="uq_feedback_cases_session_anchor",
        ),
        sa.CheckConstraint(
            "status IN ('detected', 'collecting_context', 'needs_annotation', "
            "'ready_for_review', 'rejected', 'insufficient', 'accepted', 'withdrawn')",
            name="feedback_case_status_valid",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="feedback_case_timestamps_valid",
        ),
    )
    op.create_index(
        "ix_feedback_cases_collection_status",
        "feedback_cases",
        ["collection_id", "status", "created_at"],
    )
    op.create_index(
        "ix_feedback_cases_collection_id", "feedback_cases", ["collection_id"]
    )
    op.create_index("ix_feedback_cases_status", "feedback_cases", ["status"])
    op.create_index(
        "ix_feedback_cases_session_id",
        "feedback_cases",
        ["session_id"],
    )
    op.create_index(
        "ix_feedback_cases_anchor_message_id",
        "feedback_cases",
        ["anchor_message_id"],
    )


def downgrade():
    op.drop_index("ix_feedback_cases_anchor_message_id", table_name="feedback_cases")
    op.drop_index("ix_feedback_cases_session_id", table_name="feedback_cases")
    op.drop_index("ix_feedback_cases_status", table_name="feedback_cases")
    op.drop_index("ix_feedback_cases_collection_id", table_name="feedback_cases")
    op.drop_index("ix_feedback_cases_collection_status", table_name="feedback_cases")
    op.drop_table("feedback_cases")

    op.drop_index(
        "ix_feedback_analysis_results_problem_type",
        table_name="feedback_analysis_results",
    )
    op.drop_index(
        "ix_feedback_analysis_results_anchor_message_id",
        table_name="feedback_analysis_results",
    )
    op.drop_index(
        "ix_feedback_analysis_results_collection_id",
        table_name="feedback_analysis_results",
    )
    op.drop_index(
        "ix_feedback_analysis_results_session_id",
        table_name="feedback_analysis_results",
    )
    op.drop_index(
        "ix_feedback_analysis_results_feedback_id",
        table_name="feedback_analysis_results",
    )
    op.drop_index(
        "ix_feedback_analysis_results_job_id",
        table_name="feedback_analysis_results",
    )
    op.drop_table("feedback_analysis_results")

    op.drop_index("ix_analysis_jobs_available_at", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_job_type", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_claim", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")

    op.drop_index(
        "ix_chat_model_calls_response_message_id", table_name="chat_model_calls"
    )
    op.drop_index(
        "ix_chat_model_calls_trigger_message_id", table_name="chat_model_calls"
    )
    op.drop_index("ix_chat_model_calls_status", table_name="chat_model_calls")
    op.drop_index("ix_chat_model_calls_session_id", table_name="chat_model_calls")
    op.drop_table("chat_model_calls")
