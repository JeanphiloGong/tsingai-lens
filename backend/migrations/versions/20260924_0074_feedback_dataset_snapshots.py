"""Persist immutable feedback dataset snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260924_0074"
down_revision = "20260924_0073"
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
    if "feedback_dataset_snapshots" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "feedback_dataset_snapshots",
            sa.Column("dataset_id", sa.String(length=64), nullable=False),
            sa.Column("owner_id", sa.String(length=64), nullable=False),
            sa.Column("collection_id", sa.String(length=64), nullable=False),
            sa.Column("dataset_type", sa.String(length=16), nullable=False),
            sa.Column("rows", _JSON_DOCUMENT, nullable=False),
            sa.Column("exclusions", _JSON_DOCUMENT, nullable=False),
            sa.Column("provenance", _JSON_DOCUMENT, nullable=False),
            sa.Column("manifest", _JSON_DOCUMENT, nullable=False),
            sa.Column("manifest_digest", sa.String(length=64), nullable=False),
            sa.Column("provenance_digest", sa.String(length=64), nullable=False),
            sa.Column("content_digest", sa.String(length=64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("excluded_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id"], ["auth_users.user_id"],
                name="fk_feedback_dataset_snapshots_owner", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["collection_id"], ["collections.collection_id"],
                name="fk_feedback_dataset_snapshots_collection", ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("dataset_id", name="pk_feedback_dataset_snapshots"),
            sa.UniqueConstraint(
                "owner_id", "manifest_digest",
                name="uq_feedback_dataset_owner_manifest",
            ),
            sa.CheckConstraint(
                "dataset_type IN ('evaluation', 'sft', 'preference')",
                name="feedback_dataset_type_valid",
            ),
            sa.CheckConstraint(
                "length(manifest_digest) = 64",
                name="feedback_dataset_manifest_digest_length",
            ),
            sa.CheckConstraint(
                "length(provenance_digest) = 64",
                name="feedback_dataset_provenance_digest_length",
            ),
            sa.CheckConstraint(
                "length(content_digest) = 64",
                name="feedback_dataset_content_digest_length",
            ),
            sa.CheckConstraint(
                "row_count >= 0",
                name="feedback_dataset_row_count_non_negative",
            ),
            sa.CheckConstraint(
                "excluded_count >= 0",
                name="feedback_dataset_excluded_count_non_negative",
            ),
        )
    _create_index("ix_feedback_dataset_snapshots_owner_id", "feedback_dataset_snapshots", ["owner_id"])
    _create_index("ix_feedback_dataset_snapshots_collection_id", "feedback_dataset_snapshots", ["collection_id"])
    _create_index("ix_feedback_dataset_snapshots_dataset_type", "feedback_dataset_snapshots", ["dataset_type"])
    _create_index("ix_feedback_dataset_snapshots_manifest_digest", "feedback_dataset_snapshots", ["manifest_digest"])
    _create_index("ix_feedback_dataset_snapshots_provenance_digest", "feedback_dataset_snapshots", ["provenance_digest"])
    _create_index("ix_feedback_dataset_snapshots_content_digest", "feedback_dataset_snapshots", ["content_digest"])
    _create_index("ix_feedback_dataset_collection_created", "feedback_dataset_snapshots", ["collection_id", "created_at"])


def downgrade() -> None:
    if "feedback_dataset_snapshots" not in inspect(op.get_bind()).get_table_names():
        return
    for name in (
        "ix_feedback_dataset_collection_created",
        "ix_feedback_dataset_snapshots_content_digest",
        "ix_feedback_dataset_snapshots_provenance_digest",
        "ix_feedback_dataset_snapshots_manifest_digest",
        "ix_feedback_dataset_snapshots_dataset_type",
        "ix_feedback_dataset_snapshots_collection_id",
        "ix_feedback_dataset_snapshots_owner_id",
    ):
        _drop_index(name, "feedback_dataset_snapshots")
    op.drop_table("feedback_dataset_snapshots")
