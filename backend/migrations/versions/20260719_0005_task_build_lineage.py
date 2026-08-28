"""Add relational task and collection-build lineage.

Revision ID: 20260719_0005
Revises: 20260719_0004
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260719_0005"
down_revision: str | Sequence[str] | None = "20260719_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_stage", sa.String(length=128), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("progress_detail", _JSON_DOCUMENT, nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("errors", _JSON_DOCUMENT, nullable=False),
        sa.Column("warnings", _JSON_DOCUMENT, nullable=False),
        sa.Column("details", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "current_stage <> ''",
            name=op.f("ck_tasks_current_stage_not_empty"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name=op.f("ck_tasks_valid_finished_at"),
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name=op.f("ck_tasks_valid_progress_percent"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name=op.f("ck_tasks_valid_started_at"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial_success', 'failed')",
            name=op.f("ck_tasks_valid_status"),
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name=op.f("ck_tasks_valid_timestamps"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_tasks_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_tasks")),
    )
    op.create_index(
        op.f("ix_tasks_collection_id"),
        "tasks",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "collection_builds",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("build_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "build_number > 0",
            name=op.f("ck_collection_builds_build_number_positive"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name=op.f("ck_collection_builds_valid_finished_at"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name=op.f("ck_collection_builds_valid_started_at"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'building', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_collection_builds_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_collection_builds_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.task_id"],
            name=op.f("fk_collection_builds_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("build_id", name=op.f("pk_collection_builds")),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            name="uq_collection_builds_collection_build_identity",
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_number",
            name="uq_collection_builds_collection_build_number",
        ),
        sa.UniqueConstraint("task_id", name=op.f("uq_collection_builds_task_id")),
    )
    op.create_index(
        op.f("ix_collection_builds_collection_id"),
        "collection_builds",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "build_stages",
        sa.Column("stage_id", sa.String(length=64), nullable=False),
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("stage_kind", sa.String(length=128), nullable=False),
        sa.Column("stage_version", sa.Integer(), nullable=False),
        sa.Column("stage_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("errors", _JSON_DOCUMENT, nullable=False),
        sa.Column("warnings", _JSON_DOCUMENT, nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_build_stages_valid_timestamps"),
        ),
        sa.CheckConstraint(
            "stage_kind <> ''",
            name=op.f("ck_build_stages_stage_kind_not_empty"),
        ),
        sa.CheckConstraint(
            "stage_order >= 0",
            name=op.f("ck_build_stages_stage_order_non_negative"),
        ),
        sa.CheckConstraint(
            "stage_version > 0",
            name=op.f("ck_build_stages_stage_version_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')",
            name=op.f("ck_build_stages_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["build_id"],
            ["collection_builds.build_id"],
            name=op.f("fk_build_stages_build_id_collection_builds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stage_id", name=op.f("pk_build_stages")),
        sa.UniqueConstraint(
            "build_id",
            "stage_kind",
            "stage_version",
            name="uq_build_stages_build_kind_version",
        ),
        sa.UniqueConstraint(
            "build_id",
            "stage_order",
            name="uq_build_stages_build_stage_order",
        ),
    )
    op.create_index(
        op.f("ix_build_stages_build_id"),
        "build_stages",
        ["build_id"],
        unique=False,
    )
    op.create_table(
        "artifact_versions",
        sa.Column("artifact_version_id", sa.String(length=64), nullable=False),
        sa.Column("build_stage_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_kind", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=True),
        sa.Column("details", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "artifact_kind <> ''",
            name=op.f("ck_artifact_versions_artifact_kind_not_empty"),
        ),
        sa.CheckConstraint(
            "content_version > 0",
            name=op.f("ck_artifact_versions_content_version_positive"),
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name=op.f("ck_artifact_versions_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('generated', 'ready', 'stale')",
            name=op.f("ck_artifact_versions_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["build_stage_id"],
            ["build_stages.stage_id"],
            name=op.f("fk_artifact_versions_build_stage_id_build_stages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["stored_objects.object_id"],
            name=op.f("fk_artifact_versions_object_id_stored_objects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "artifact_version_id",
            name=op.f("pk_artifact_versions"),
        ),
        sa.UniqueConstraint(
            "build_stage_id",
            "artifact_kind",
            "schema_version",
            "content_version",
            name="uq_artifact_versions_stage_kind_version",
        ),
    )
    op.create_index(
        op.f("ix_artifact_versions_build_stage_id"),
        "artifact_versions",
        ["build_stage_id"],
        unique=False,
    )
    op.create_table(
        "collection_active_builds",
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_active_builds_collection_build",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            name=op.f("pk_collection_active_builds"),
        ),
        sa.UniqueConstraint(
            "build_id",
            name=op.f("uq_collection_active_builds_build_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("collection_active_builds")
    op.drop_index(
        op.f("ix_artifact_versions_build_stage_id"),
        table_name="artifact_versions",
    )
    op.drop_table("artifact_versions")
    op.drop_index(op.f("ix_build_stages_build_id"), table_name="build_stages")
    op.drop_table("build_stages")
    op.drop_index(
        op.f("ix_collection_builds_collection_id"),
        table_name="collection_builds",
    )
    op.drop_table("collection_builds")
    op.drop_index(op.f("ix_tasks_collection_id"), table_name="tasks")
    op.drop_table("tasks")
