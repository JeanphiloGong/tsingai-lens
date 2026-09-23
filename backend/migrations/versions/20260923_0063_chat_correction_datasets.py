"""Persist immutable Chat correction dataset manifests."""

from alembic import op
import sqlalchemy as sa


revision = "20260923_0063"
down_revision = "20260923_0062"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "chat_correction_datasets" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "chat_correction_datasets",
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("manifest_digest", sa.String(length=64), nullable=False),
        sa.Column("provenance_digest", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["auth_users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.collection_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("dataset_id"),
        sa.CheckConstraint(
            "length(manifest_digest) = 64",
            name="chat_correction_dataset_digest_length",
        ),
        sa.CheckConstraint(
            "length(provenance_digest) = 64",
            name="chat_correction_dataset_provenance_digest_length",
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="chat_correction_dataset_row_count_nonnegative",
        ),
        sa.CheckConstraint(
            "excluded_count >= 0",
            name="chat_correction_dataset_excluded_count_nonnegative",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "manifest_digest",
            name="uq_chat_correction_dataset_owner_digest",
        ),
    )
    for column in ("owner_id", "collection_id", "manifest_digest", "provenance_digest"):
        op.create_index(
            f"ix_chat_correction_datasets_{column}",
            "chat_correction_datasets",
            [column],
        )


def downgrade():
    bind = op.get_bind()
    if "chat_correction_datasets" not in set(sa.inspect(bind).get_table_names()):
        return
    for column in ("provenance_digest", "manifest_digest", "collection_id", "owner_id"):
        op.drop_index(
            f"ix_chat_correction_datasets_{column}",
            table_name="chat_correction_datasets",
        )
    op.drop_table("chat_correction_datasets")
