"""Persist task-dataset export previews and immutable downloads."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260929_0083"
down_revision = "20260929_0082"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "feedback_export_previews" not in tables:
        op.create_table(
            "feedback_export_previews",
            sa.Column("preview_id", sa.String(length=64), nullable=False),
            sa.Column("dataset_id", sa.String(length=64), nullable=False),
            sa.Column("members", _JSON_DOCUMENT, nullable=False),
            sa.Column("issues", _JSON_DOCUMENT, nullable=False),
            sa.Column("preview_digest", sa.String(length=64), nullable=False),
            sa.Column("requested_count", sa.Integer(), nullable=False),
            sa.Column("exportable_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["feedback_datasets.dataset_id"],
                name="fk_feedback_export_previews_dataset",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("preview_id", name="pk_feedback_export_previews"),
            sa.CheckConstraint(
                "length(preview_digest) = 64",
                name="feedback_export_preview_digest_len",
            ),
        )
        op.create_index(
            "ix_feedback_export_previews_dataset_created",
            "feedback_export_previews",
            ["dataset_id", "created_at"],
        )

    inspector = inspect(op.get_bind())
    if "feedback_dataset_exports" not in inspector.get_table_names():
        op.create_table(
            "feedback_dataset_exports",
            sa.Column("export_id", sa.String(length=64), nullable=False),
            sa.Column("dataset_id", sa.String(length=64), nullable=False),
            sa.Column("export_no", sa.Integer(), nullable=False),
            sa.Column("schema_version", sa.String(length=64), nullable=False),
            sa.Column("rows", _JSON_DOCUMENT, nullable=False),
            sa.Column("provenance", _JSON_DOCUMENT, nullable=False),
            sa.Column("manifest", _JSON_DOCUMENT, nullable=False),
            sa.Column("preview_id", sa.String(length=64), nullable=False),
            sa.Column("preview_digest", sa.String(length=64), nullable=False),
            sa.Column("member_digest", sa.String(length=64), nullable=False),
            sa.Column("content_digest", sa.String(length=64), nullable=False),
            sa.Column("provenance_digest", sa.String(length=64), nullable=False),
            sa.Column("manifest_digest", sa.String(length=64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["feedback_datasets.dataset_id"],
                name="fk_feedback_dataset_exports_dataset",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["preview_id"],
                ["feedback_export_previews.preview_id"],
                name="fk_feedback_dataset_exports_preview",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["auth_users.user_id"],
                name="fk_feedback_dataset_exports_creator",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("export_id", name="pk_feedback_dataset_exports"),
            sa.UniqueConstraint(
                "dataset_id", "export_no", name="uq_feedback_dataset_exports_number"
            ),
            sa.UniqueConstraint(
                "dataset_id", "idempotency_key", name="uq_feedback_dataset_exports_idempotency"
            ),
            sa.CheckConstraint(
                "export_no >= 1", name="feedback_dataset_export_number_positive"
            ),
            sa.CheckConstraint("row_count > 0", name="feedback_dataset_export_rows_positive"),
            sa.CheckConstraint(
                "length(preview_digest) = 64",
                name="feedback_dataset_export_preview_len",
            ),
            sa.CheckConstraint(
                "length(member_digest) = 64",
                name="feedback_dataset_export_member_len",
            ),
            sa.CheckConstraint(
                "length(content_digest) = 64",
                name="feedback_dataset_export_content_len",
            ),
            sa.CheckConstraint(
                "length(provenance_digest) = 64",
                name="feedback_dataset_export_provenance_len",
            ),
            sa.CheckConstraint(
                "length(manifest_digest) = 64",
                name="feedback_dataset_export_manifest_len",
            ),
        )
        op.create_index(
            "ix_feedback_dataset_exports_dataset_created",
            "feedback_dataset_exports",
            ["dataset_id", "created_at"],
        )
        op.create_index(
            "ix_feedback_dataset_exports_preview_id",
            "feedback_dataset_exports",
            ["preview_id"],
        )

    inspector = inspect(op.get_bind())
    if "feedback_export_members" not in inspector.get_table_names():
        op.create_table(
            "feedback_export_members",
            sa.Column("export_id", sa.String(length=64), nullable=False),
            sa.Column("row_key", sa.String(length=64), nullable=False),
            sa.Column("sample_id", sa.String(length=64), nullable=False),
            sa.Column("revision_id", sa.String(length=64), nullable=False),
            sa.Column("content_digest", sa.String(length=64), nullable=False),
            sa.Column("input_digest", sa.String(length=64), nullable=False),
            sa.Column("provenance_digest", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ["export_id"],
                ["feedback_dataset_exports.export_id"],
                name="fk_feedback_export_members_export",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["sample_id"],
                ["feedback_dataset_samples.sample_id"],
                name="fk_feedback_export_members_sample",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["revision_id"],
                ["feedback_sample_revisions.revision_id"],
                name="fk_feedback_export_members_revision",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint(
                "export_id", "row_key", name="pk_feedback_export_members"
            ),
            sa.CheckConstraint(
                "length(row_key) = 64", name="feedback_export_member_row_key_len"
            ),
            sa.CheckConstraint(
                "length(content_digest) = 64",
                name="feedback_export_member_content_len",
            ),
            sa.CheckConstraint(
                "length(input_digest) = 64", name="feedback_export_member_input_len"
            ),
        )
        op.create_index(
            "ix_feedback_export_members_sample", "feedback_export_members", ["sample_id"]
        )
        op.create_index(
            "ix_feedback_export_members_revision",
            "feedback_export_members",
            ["revision_id"],
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "feedback_export_members" in inspector.get_table_names():
        op.drop_index("ix_feedback_export_members_revision", table_name="feedback_export_members")
        op.drop_index("ix_feedback_export_members_sample", table_name="feedback_export_members")
        op.drop_table("feedback_export_members")
    if "feedback_dataset_exports" in inspector.get_table_names():
        op.drop_index(
            "ix_feedback_dataset_exports_preview_id", table_name="feedback_dataset_exports"
        )
        op.drop_index(
            "ix_feedback_dataset_exports_dataset_created",
            table_name="feedback_dataset_exports",
        )
        op.drop_table("feedback_dataset_exports")
    if "feedback_export_previews" in inspector.get_table_names():
        op.drop_index(
            "ix_feedback_export_previews_dataset_created",
            table_name="feedback_export_previews",
        )
        op.drop_table("feedback_export_previews")
