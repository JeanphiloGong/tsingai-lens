"""Record who confirmed the current task dataset sample revision."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260929_0081"
down_revision = "20260929_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "feedback_dataset_samples" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("feedback_dataset_samples")}
    with op.batch_alter_table("feedback_dataset_samples") as batch:
        if "confirmed_by" not in columns:
            batch.add_column(sa.Column("confirmed_by", sa.String(length=64), nullable=True))
            batch.create_index("ix_feedback_dataset_samples_confirmed_by", ["confirmed_by"])
            batch.create_foreign_key(
                "fk_feedback_dataset_samples_confirmed_by",
                "auth_users",
                ["confirmed_by"],
                ["user_id"],
                ondelete="RESTRICT",
            )
        if "confirmed_at" not in columns:
            batch.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "feedback_dataset_samples" not in inspector.get_table_names():
        return
    constraints = {
        item.get("name")
        for item in inspector.get_foreign_keys("feedback_dataset_samples")
    }
    with op.batch_alter_table("feedback_dataset_samples") as batch:
        if "fk_feedback_dataset_samples_confirmed_by" in constraints:
            batch.drop_constraint("fk_feedback_dataset_samples_confirmed_by", type_="foreignkey")
    indexes = {
        item.get("name")
        for item in inspector.get_indexes("feedback_dataset_samples")
    }
    if "ix_feedback_dataset_samples_confirmed_by" in indexes:
        with op.batch_alter_table("feedback_dataset_samples") as batch:
            batch.drop_index("ix_feedback_dataset_samples_confirmed_by")
    columns = {item["name"] for item in inspector.get_columns("feedback_dataset_samples")}
    with op.batch_alter_table("feedback_dataset_samples") as batch:
        if "confirmed_at" in columns:
            batch.drop_column("confirmed_at")
        if "confirmed_by" in columns:
            batch.drop_column("confirmed_by")
