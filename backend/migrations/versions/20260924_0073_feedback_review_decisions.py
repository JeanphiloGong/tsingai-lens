"""Persist append-only review decisions for feedback annotations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260924_0073"
down_revision = "20260924_0072"
branch_labels = None
depends_on = None


def _create_index(name: str, table_name: str, columns) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)


def _drop_index(name: str, table_name: str) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)


def upgrade() -> None:
    if "feedback_review_decisions" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "feedback_review_decisions",
            sa.Column("decision_id", sa.String(length=64), nullable=False),
            sa.Column("case_id", sa.String(length=64), nullable=False),
            sa.Column("annotation_digest", sa.String(length=64), nullable=False),
            sa.Column("decision", sa.String(length=16), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["case_id"], ["feedback_cases.case_id"],
                name="fk_feedback_review_decisions_case", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"], ["auth_users.user_id"],
                name="fk_feedback_review_decisions_created_by", ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("decision_id", name="pk_feedback_review_decisions"),
            sa.UniqueConstraint("case_id", "seq", name="uq_feedback_review_case_seq"),
            sa.CheckConstraint(
                "decision IN ('accept', 'reject', 'insufficient', 'withdraw')",
                name="feedback_review_decision_valid",
            ),
            sa.CheckConstraint(
                "length(annotation_digest) = 64",
                name="feedback_review_digest_length",
            ),
            sa.CheckConstraint("seq >= 1", name="feedback_review_seq_positive"),
        )
    _create_index("ix_feedback_review_decisions_case_id", "feedback_review_decisions", ["case_id"])
    _create_index("ix_feedback_review_decisions_annotation_digest", "feedback_review_decisions", ["annotation_digest"])
    _create_index("ix_feedback_review_decisions_created_by", "feedback_review_decisions", ["created_by"])
    _create_index("ix_feedback_review_case_created", "feedback_review_decisions", ["case_id", "created_at"])


def downgrade() -> None:
    if "feedback_review_decisions" not in inspect(op.get_bind()).get_table_names():
        return
    _drop_index("ix_feedback_review_case_created", "feedback_review_decisions")
    _drop_index("ix_feedback_review_decisions_created_by", "feedback_review_decisions")
    _drop_index("ix_feedback_review_decisions_annotation_digest", "feedback_review_decisions")
    _drop_index("ix_feedback_review_decisions_case_id", "feedback_review_decisions")
    op.drop_table("feedback_review_decisions")
