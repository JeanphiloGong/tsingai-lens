"""Persist analysis candidates for failed Chat tool results.

Tool failures have a different source identity from ratings and natural
language correction signals.  Keep their result rows separate while reusing
the shared analysis-job envelope and human case projection.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260925_0077"
down_revision = "20260925_0076"
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
    if "tool_failure_analysis_results" not in tables:
        op.create_table(
            "tool_failure_analysis_results",
            sa.Column("result_id", sa.String(length=64), nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("signal_id", sa.String(length=320), nullable=False),
            sa.Column("signal_type", sa.String(length=32), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("collection_id", sa.String(length=64), nullable=False),
            sa.Column("tool_call_id", sa.String(length=128), nullable=False),
            sa.Column("assistant_message_id", sa.String(length=128), nullable=False),
            sa.Column("result_message_id", sa.String(length=128), nullable=False),
            sa.Column("tool_name", sa.String(length=128), nullable=False),
            sa.Column("error_code", sa.String(length=128), nullable=False),
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
                name="fk_tool_failure_analysis_results_job", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["chat_sessions.session_id"],
                name="fk_tool_failure_analysis_results_session", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["collection_id"], ["collections.collection_id"],
                name="fk_tool_failure_analysis_results_collection", ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("result_id", name="pk_tool_failure_analysis_results"),
            sa.UniqueConstraint("job_id", name="uq_tool_failure_analysis_results_job_id"),
            sa.UniqueConstraint(
                "tool_call_id", "result_message_id",
                name="uq_tool_failure_analysis_results_observation",
            ),
            sa.CheckConstraint(
                "signal_type IN ('tool_failure')",
                name="tool_failure_analysis_signal_type_valid",
            ),
            sa.CheckConstraint(
                "problem_type = 'tool_failure'",
                name="tool_failure_analysis_problem_type_valid",
            ),
            sa.CheckConstraint(
                "confidence >= 0 AND confidence <= 1",
                name="tool_failure_analysis_confidence_range",
            ),
            sa.CheckConstraint(
                "suggested_target IS NULL",
                name="tool_failure_analysis_target_absent",
            ),
            sa.CheckConstraint(
                "length(input_digest) = 64",
                name="tool_failure_analysis_input_digest_length",
            ),
        )
    for name, columns in (
        ("ix_tool_failure_analysis_results_job_id", ["job_id"]),
        ("ix_tool_failure_analysis_results_signal_id", ["signal_id"]),
        ("ix_tool_failure_analysis_results_session_id", ["session_id"]),
        ("ix_tool_failure_analysis_results_collection_id", ["collection_id"]),
        ("ix_tool_failure_analysis_results_tool_call_id", ["tool_call_id"]),
        ("ix_tool_failure_analysis_results_result_message_id", ["result_message_id"]),
        ("ix_tool_failure_analysis_results_problem_type", ["problem_type"]),
    ):
        _index(name, "tool_failure_analysis_results", columns)

    if "feedback_cases" in tables:
        columns = {item["name"] for item in inspect(bind).get_columns("feedback_cases")}
        if "tool_failure_analysis_result_ids" not in columns:
            op.add_column(
                "feedback_cases",
                sa.Column(
                    "tool_failure_analysis_result_ids",
                    _JSON_DOCUMENT,
                    nullable=False,
                    server_default=sa.text("'[]'"),
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "feedback_cases" in inspect(bind).get_table_names():
        columns = {item["name"] for item in inspect(bind).get_columns("feedback_cases")}
        if "tool_failure_analysis_result_ids" in columns:
            op.drop_column("feedback_cases", "tool_failure_analysis_result_ids")
    if "tool_failure_analysis_results" not in inspect(bind).get_table_names():
        return
    for name in (
        "ix_tool_failure_analysis_results_problem_type",
        "ix_tool_failure_analysis_results_result_message_id",
        "ix_tool_failure_analysis_results_tool_call_id",
        "ix_tool_failure_analysis_results_collection_id",
        "ix_tool_failure_analysis_results_session_id",
        "ix_tool_failure_analysis_results_signal_id",
        "ix_tool_failure_analysis_results_job_id",
    ):
        _drop_index(name, "tool_failure_analysis_results")
    op.drop_table("tool_failure_analysis_results")
