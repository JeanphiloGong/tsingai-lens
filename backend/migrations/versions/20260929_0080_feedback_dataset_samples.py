"""Add task-specific dataset samples, immutable revisions, and build jobs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260929_0080"
down_revision = "20260929_0079"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "feedback_dataset_samples" not in tables:
        op.create_table(
            "feedback_dataset_samples",
            sa.Column("sample_id", sa.String(length=64), nullable=False),
            sa.Column("dataset_id", sa.String(length=64), nullable=False),
            sa.Column("source_case_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("current_revision_id", sa.String(length=64), nullable=True),
            sa.Column("confirmed_revision_id", sa.String(length=64), nullable=True),
            sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("source_digest", sa.String(length=64), nullable=False),
            sa.Column("active_job_id", sa.String(length=64), nullable=True),
            sa.Column("missing_reasons", _JSON_DOCUMENT, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["feedback_datasets.dataset_id"],
                name="fk_feedback_dataset_samples_dataset",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["source_case_id"],
                ["feedback_cases.case_id"],
                name="fk_feedback_dataset_samples_source_case",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["active_job_id"],
                ["analysis_jobs.job_id"],
                name="fk_feedback_dataset_samples_active_job",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("sample_id", name="pk_feedback_dataset_samples"),
            sa.CheckConstraint(
                "status IN ('pending', 'building', 'needs_confirmation', 'needs_input', "
                "'confirmed', 'discarded', 'build_failed')",
                name="feedback_dataset_sample_status_valid",
            ),
            sa.CheckConstraint(
                "generation >= 1",
                name="feedback_dataset_sample_generation_positive",
            ),
            sa.CheckConstraint(
                "length(source_digest) = 64",
                name="feedback_dataset_sample_source_digest_length",
            ),
            sa.UniqueConstraint(
                "dataset_id",
                "source_case_id",
                name="uq_feedback_dataset_samples_dataset_source_case",
            ),
        )
        for name, columns in (
            ("ix_feedback_dataset_samples_dataset_id", ["dataset_id"]),
            ("ix_feedback_dataset_samples_source_case_id", ["source_case_id"]),
            ("ix_feedback_dataset_samples_status", ["status"]),
            ("ix_feedback_dataset_samples_active_job_id", ["active_job_id"]),
            (
                "ix_feedback_dataset_samples_dataset_status",
                ["dataset_id", "status", "updated_at"],
            ),
        ):
            op.create_index(name, "feedback_dataset_samples", columns)

    inspector = inspect(op.get_bind())
    if "feedback_sample_revisions" not in inspector.get_table_names():
        op.create_table(
            "feedback_sample_revisions",
            sa.Column("revision_id", sa.String(length=64), nullable=False),
            sa.Column("sample_id", sa.String(length=64), nullable=False),
            sa.Column("revision_no", sa.Integer(), nullable=False),
            sa.Column("author_kind", sa.String(length=16), nullable=False),
            sa.Column("content", _JSON_DOCUMENT, nullable=False),
            sa.Column("content_digest", sa.String(length=64), nullable=False),
            sa.Column("input_digest", sa.String(length=64), nullable=False),
            sa.Column("construction_spec_version", sa.Integer(), nullable=False),
            sa.Column("provenance", _JSON_DOCUMENT, nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("job_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["sample_id"],
                ["feedback_dataset_samples.sample_id"],
                name="fk_feedback_sample_revisions_sample",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["auth_users.user_id"],
                name="fk_feedback_sample_revisions_created_by",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["job_id"],
                ["analysis_jobs.job_id"],
                name="fk_feedback_sample_revisions_job",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("revision_id", name="pk_feedback_sample_revisions"),
            sa.CheckConstraint(
                "author_kind IN ('worker', 'human')",
                name="feedback_sample_revision_author_kind_valid",
            ),
            sa.CheckConstraint(
                "revision_no >= 1",
                name="feedback_sample_revision_number_positive",
            ),
            sa.CheckConstraint(
                "construction_spec_version >= 1",
                name="feedback_sample_revision_spec_version_positive",
            ),
            sa.CheckConstraint(
                "length(content_digest) = 64",
                name="feedback_sample_revision_content_digest_length",
            ),
            sa.CheckConstraint(
                "length(input_digest) = 64",
                name="feedback_sample_revision_input_digest_length",
            ),
            sa.UniqueConstraint(
                "sample_id",
                "revision_no",
                name="uq_feedback_sample_revisions_sample_number",
            ),
        )
        for name, columns in (
            ("ix_feedback_sample_revisions_sample_id", ["sample_id"]),
            ("ix_feedback_sample_revisions_created_by", ["created_by"]),
            ("ix_feedback_sample_revisions_job_id", ["job_id"]),
            (
                "ix_feedback_sample_revisions_sample_created",
                ["sample_id", "created_at"],
            ),
        ):
            op.create_index(name, "feedback_sample_revisions", columns)

    # These two references are intentionally added after the revision table so
    # the database can enforce that a pointer belongs to an actual revision.
    existing_constraints = {
        item.get("name")
        for item in inspect(op.get_bind()).get_foreign_keys("feedback_dataset_samples")
    }
    with op.batch_alter_table("feedback_dataset_samples") as batch:
        if "fk_feedback_dataset_samples_current_revision" not in existing_constraints:
            batch.create_foreign_key(
                "fk_feedback_dataset_samples_current_revision",
                "feedback_sample_revisions",
                ["current_revision_id"],
                ["revision_id"],
                ondelete="RESTRICT",
            )
        if "fk_feedback_dataset_samples_confirmed_revision" not in existing_constraints:
            batch.create_foreign_key(
                "fk_feedback_dataset_samples_confirmed_revision",
                "feedback_sample_revisions",
                ["confirmed_revision_id"],
                ["revision_id"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "feedback_dataset_samples" in inspector.get_table_names():
        with op.batch_alter_table("feedback_dataset_samples") as batch:
            for name in (
                "fk_feedback_dataset_samples_confirmed_revision",
                "fk_feedback_dataset_samples_current_revision",
            ):
                if name in {
                    item.get("name")
                    for item in inspector.get_foreign_keys("feedback_dataset_samples")
                }:
                    batch.drop_constraint(name, type_="foreignkey")
        for name in (
            "ix_feedback_dataset_samples_dataset_status",
            "ix_feedback_dataset_samples_active_job_id",
            "ix_feedback_dataset_samples_status",
            "ix_feedback_dataset_samples_source_case_id",
            "ix_feedback_dataset_samples_dataset_id",
        ):
            op.drop_index(name, table_name="feedback_dataset_samples")

    inspector = inspect(op.get_bind())
    if "feedback_sample_revisions" in inspector.get_table_names():
        for name in (
            "ix_feedback_sample_revisions_sample_created",
            "ix_feedback_sample_revisions_job_id",
            "ix_feedback_sample_revisions_created_by",
            "ix_feedback_sample_revisions_sample_id",
        ):
            op.drop_index(name, table_name="feedback_sample_revisions")
        op.drop_table("feedback_sample_revisions")
    inspector = inspect(op.get_bind())
    if "feedback_dataset_samples" in inspector.get_table_names():
        op.drop_table("feedback_dataset_samples")
