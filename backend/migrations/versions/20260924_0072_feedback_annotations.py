"""Persist versioned human annotations for feedback cases."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260924_0072"
down_revision = "20260924_0071"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _create_index(name: str, table_name: str, columns) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)


def _drop_index(name: str, table_name: str) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)


def upgrade() -> None:
    if "feedback_annotations" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "feedback_annotations",
            sa.Column("annotation_id", sa.String(length=64), nullable=False),
            sa.Column("case_id", sa.String(length=64), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("problem_type", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=False),
            sa.Column("target", sa.Text(), nullable=True),
            sa.Column("support_source_refs", _JSON_DOCUMENT, nullable=False),
            sa.Column("dataset_uses", _JSON_DOCUMENT, nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("annotation_digest", sa.String(length=64), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["case_id"], ["feedback_cases.case_id"],
                name="fk_feedback_annotations_case", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"], ["auth_users.user_id"],
                name="fk_feedback_annotations_created_by", ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("annotation_id", name="pk_feedback_annotations"),
            sa.UniqueConstraint("case_id", "version", name="uq_feedback_annotations_case_version"),
            sa.CheckConstraint(
                "problem_type IN ('fact_error', 'source_missing', 'evidence_mismatch', "
                "'retrieval_failure', 'tool_failure', 'intent_mismatch', "
                "'incomplete_answer', 'style_or_format', 'undetermined_dissatisfaction')",
                name="feedback_annotation_problem_type_valid",
            ),
            sa.CheckConstraint(
                "severity IN ('low', 'medium', 'high', 'critical')",
                name="feedback_annotation_severity_valid",
            ),
            sa.CheckConstraint(
                "length(annotation_digest) = 64",
                name="feedback_annotation_digest_length",
            ),
            sa.CheckConstraint("version >= 1", name="feedback_annotation_version_positive"),
        )
    _create_index("ix_feedback_annotations_case_id", "feedback_annotations", ["case_id"])
    _create_index("ix_feedback_annotations_annotation_digest", "feedback_annotations", ["annotation_digest"])
    _create_index("ix_feedback_annotations_created_by", "feedback_annotations", ["created_by"])
    _create_index(
        "ix_feedback_annotations_case_created",
        "feedback_annotations",
        ["case_id", "created_at"],
    )


def downgrade() -> None:
    if "feedback_annotations" not in inspect(op.get_bind()).get_table_names():
        return
    _drop_index("ix_feedback_annotations_case_created", "feedback_annotations")
    _drop_index("ix_feedback_annotations_created_by", "feedback_annotations")
    _drop_index("ix_feedback_annotations_annotation_digest", "feedback_annotations")
    _drop_index("ix_feedback_annotations_case_id", "feedback_annotations")
    op.drop_table("feedback_annotations")
