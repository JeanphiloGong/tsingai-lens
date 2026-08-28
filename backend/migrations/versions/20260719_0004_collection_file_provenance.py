"""Add relational collection file and import provenance.

Revision ID: 20260719_0004
Revises: 20260719_0003
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260719_0004"
down_revision: str | Sequence[str] | None = "20260719_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("object_kind", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "object_kind <> ''",
            name=op.f("ck_stored_objects_object_kind_not_empty"),
        ),
        sa.CheckConstraint(
            "storage_key <> ''",
            name=op.f("ck_stored_objects_storage_key_not_empty"),
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name=op.f("ck_stored_objects_sha256_length"),
        ),
        sa.CheckConstraint(
            "sha256 = lower(sha256)",
            name=op.f("ck_stored_objects_sha256_lowercase"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("ck_stored_objects_size_bytes_non_negative"),
        ),
        sa.PrimaryKeyConstraint("object_id", name=op.f("pk_stored_objects")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_stored_objects_storage_key")),
    )
    op.create_table(
        "collection_files",
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_filename", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=True),
        sa.Column("file_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "file_order >= 0",
            name=op.f("ck_collection_files_file_order_non_negative"),
        ),
        sa.CheckConstraint(
            "status <> ''",
            name=op.f("ck_collection_files_status_not_empty"),
        ),
        sa.CheckConstraint(
            "stored_filename <> ''",
            name=op.f("ck_collection_files_stored_filename_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_collection_files_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["stored_objects.object_id"],
            name=op.f("fk_collection_files_object_id_stored_objects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("file_id", name=op.f("pk_collection_files")),
        sa.UniqueConstraint(
            "collection_id",
            "file_id",
            name="uq_collection_files_collection_file_identity",
        ),
        sa.UniqueConstraint(
            "collection_id",
            "file_order",
            name="uq_collection_files_collection_file_order",
        ),
        sa.UniqueConstraint("object_id", name=op.f("uq_collection_files_object_id")),
    )
    op.create_table(
        "collection_imports",
        sa.Column("import_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("adapter_name", sa.String(length=255), nullable=False),
        sa.Column("adapter_version", sa.String(length=255), nullable=True),
        sa.Column("raw_locator", sa.Text(), nullable=True),
        sa.Column("goal_context", _JSON_DOCUMENT, nullable=True),
        sa.Column("warnings", _JSON_DOCUMENT, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "adapter_name <> ''",
            name=op.f("ck_collection_imports_adapter_name_not_empty"),
        ),
        sa.CheckConstraint(
            "channel <> ''",
            name=op.f("ck_collection_imports_channel_not_empty"),
        ),
        sa.CheckConstraint(
            "import_order >= 0",
            name=op.f("ck_collection_imports_import_order_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_collection_imports_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("import_id", name=op.f("pk_collection_imports")),
        sa.UniqueConstraint(
            "collection_id",
            "import_id",
            name="uq_collection_imports_collection_import_identity",
        ),
        sa.UniqueConstraint(
            "collection_id",
            "import_order",
            name="uq_collection_imports_collection_import_order",
        ),
    )
    op.create_table(
        "collection_handoffs",
        sa.Column("handoff_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_channels", _JSON_DOCUMENT, nullable=False),
        sa.Column("goal_context", _JSON_DOCUMENT, nullable=False),
        sa.Column("handoff_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "handoff_order >= 0",
            name=op.f("ck_collection_handoffs_handoff_order_non_negative"),
        ),
        sa.CheckConstraint(
            "kind <> ''",
            name=op.f("ck_collection_handoffs_kind_not_empty"),
        ),
        sa.CheckConstraint(
            "status <> ''",
            name=op.f("ck_collection_handoffs_status_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_collection_handoffs_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("handoff_id", name=op.f("pk_collection_handoffs")),
        sa.UniqueConstraint(
            "collection_id",
            "handoff_order",
            name="uq_collection_handoffs_collection_handoff_order",
        ),
    )
    op.create_table(
        "collection_import_documents",
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("import_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=255), nullable=False),
        sa.Column("origin_channel", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("ingest_status", sa.String(length=64), nullable=False),
        sa.Column("text_units", _JSON_DOCUMENT, nullable=False),
        sa.Column("document_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "document_order >= 0",
            name=op.f("ck_collection_import_documents_document_order_non_negative"),
        ),
        sa.CheckConstraint(
            "ingest_status <> ''",
            name=op.f("ck_collection_import_documents_ingest_status_not_empty"),
        ),
        sa.CheckConstraint(
            "origin_channel <> ''",
            name=op.f("ck_collection_import_documents_origin_channel_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "file_id"],
            ["collection_files.collection_id", "collection_files.file_id"],
            name="fk_import_documents_collection_file",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "import_id"],
            ["collection_imports.collection_id", "collection_imports.import_id"],
            name="fk_import_documents_collection_import",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("file_id", name=op.f("pk_collection_import_documents")),
        sa.UniqueConstraint(
            "import_id",
            "document_order",
            name="uq_import_documents_import_document_order",
        ),
        sa.UniqueConstraint(
            "import_id",
            "source_document_id",
            name="uq_import_documents_import_source_document",
        ),
    )


def downgrade() -> None:
    op.drop_table("collection_import_documents")
    op.drop_table("collection_handoffs")
    op.drop_table("collection_imports")
    op.drop_table("collection_files")
    op.drop_table("stored_objects")
