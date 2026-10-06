"""Add an isolated analysis result for natural-language correction signals.

The P1 ``feedback_analysis_results`` table remains unchanged: its
``feedback_id`` is still required and continues to identify a persisted
thumbs-up/thumbs-down record.  This migration stores message-derived
candidate signals separately while allowing them to appear in the existing
human workbench case projection.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260925_0076"
down_revision = "20260924_0075"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _index(name: str, table: str, columns: list[str]) -> None:
    if name not in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, columns)


def _drop_index(name: str, table: str) -> None:
    if name in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}:
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "feedback_signal_analysis_results" not in tables:
        op.create_table(
            "feedback_signal_analysis_results",
            sa.Column("result_id", sa.String(length=64), nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("signal_id", sa.String(length=160), nullable=False),
            sa.Column("signal_type", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("collection_id", sa.String(length=64), nullable=False),
            sa.Column("anchor_message_id", sa.String(length=128), nullable=False),
            sa.Column("trigger_message_id", sa.String(length=128), nullable=False),
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
                ["job_id"], ["analysis_jobs.job_id"],
                name="fk_feedback_signal_analysis_results_job", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["chat_sessions.session_id"],
                name="fk_feedback_signal_analysis_results_session", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["collection_id"], ["collections.collection_id"],
                name="fk_feedback_signal_analysis_results_collection", ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("result_id", name="pk_feedback_signal_analysis_results"),
            sa.UniqueConstraint("job_id", name="uq_feedback_signal_analysis_results_job_id"),
            sa.CheckConstraint(
                "signal_type IN ('natural_language_correction')",
                name="feedback_signal_analysis_type_valid",
            ),
            sa.CheckConstraint(
                "problem_type IN ('fact_error', 'source_missing', 'evidence_mismatch', "
                "'retrieval_failure', 'tool_failure', 'intent_mismatch', "
                "'incomplete_answer', 'style_or_format', 'undetermined_dissatisfaction')",
                name="feedback_signal_analysis_problem_type_valid",
            ),
            sa.CheckConstraint(
                "confidence >= 0 AND confidence <= 1",
                name="feedback_signal_analysis_confidence_range",
            ),
            sa.CheckConstraint(
                "suggested_target IS NULL",
                name="feedback_signal_analysis_target_absent",
            ),
            sa.CheckConstraint(
                "length(input_digest) = 64",
                name="feedback_signal_analysis_input_digest_length",
            ),
        )
    for name, columns in (
        ("ix_feedback_signal_analysis_results_job_id", ["job_id"]),
        ("ix_feedback_signal_analysis_results_signal_id", ["signal_id"]),
        ("ix_feedback_signal_analysis_results_signal_type", ["signal_type"]),
        ("ix_feedback_signal_analysis_results_session_id", ["session_id"]),
        ("ix_feedback_signal_analysis_results_collection_id", ["collection_id"]),
        ("ix_feedback_signal_analysis_results_anchor_message_id", ["anchor_message_id"]),
        ("ix_feedback_signal_analysis_results_trigger_message_id", ["trigger_message_id"]),
        ("ix_feedback_signal_analysis_results_problem_type", ["problem_type"]),
    ):
        _index(name, "feedback_signal_analysis_results", columns)

    if "feedback_cases" in tables:
        columns = {item["name"] for item in inspect(bind).get_columns("feedback_cases")}
        if "signal_analysis_result_ids" not in columns:
            op.add_column(
                "feedback_cases",
                sa.Column(
                    "signal_analysis_result_ids",
                    _JSON_DOCUMENT,
                    nullable=False,
                    server_default=sa.text("'[]'"),
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "feedback_cases" in inspect(bind).get_table_names():
        columns = {item["name"] for item in inspect(bind).get_columns("feedback_cases")}
        if "signal_analysis_result_ids" in columns:
            op.drop_column("feedback_cases", "signal_analysis_result_ids")
    if "feedback_signal_analysis_results" not in inspect(bind).get_table_names():
        return
    for name in (
        "ix_feedback_signal_analysis_results_problem_type",
        "ix_feedback_signal_analysis_results_trigger_message_id",
        "ix_feedback_signal_analysis_results_anchor_message_id",
        "ix_feedback_signal_analysis_results_collection_id",
        "ix_feedback_signal_analysis_results_session_id",
        "ix_feedback_signal_analysis_results_signal_type",
        "ix_feedback_signal_analysis_results_signal_id",
        "ix_feedback_signal_analysis_results_job_id",
    ):
        _drop_index(name, "feedback_signal_analysis_results")
    op.drop_table("feedback_signal_analysis_results")
