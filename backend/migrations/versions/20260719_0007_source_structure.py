"""Add versioned Source document structure.

Revision ID: 20260719_0007
Revises: 20260719_0006
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260719_0007"
down_revision: str | Sequence[str] | None = "20260719_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("collection_documents") as batch_op:
        batch_op.create_unique_constraint(
            "uq_collection_documents_membership_version",
            ["collection_id", "collection_document_id", "document_version_id"],
        )

    op.create_table(
        "source_documents",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("collection_document_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("human_readable_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("creation_date", sa.Text(), nullable=True),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "human_readable_id >= 0",
            name=op.f("ck_source_documents_human_readable_id_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_source_documents_collection_build",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "collection_document_id", "document_version_id"],
            [
                "collection_documents.collection_id",
                "collection_documents.collection_document_id",
                "collection_documents.document_version_id",
            ],
            name="fk_source_documents_membership_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "source_document_id", name=op.f("pk_source_documents")
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            name="uq_source_documents_collection_build_document",
        ),
    )
    op.create_index(
        op.f("ix_source_documents_collection_id"),
        "source_documents",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_documents_document_version_id"),
        "source_documents",
        ["document_version_id"],
        unique=False,
    )

    op.create_table(
        "source_text_units",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("text_unit_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("human_readable_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("n_tokens", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "human_readable_id >= 0",
            name=op.f("ck_source_text_units_human_readable_id_non_negative"),
        ),
        sa.CheckConstraint(
            "n_tokens IS NULL OR n_tokens >= 0",
            name=op.f("ck_source_text_units_n_tokens_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_source_text_units_collection_build",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "text_unit_id", name=op.f("pk_source_text_units")
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "text_unit_id",
            name="uq_source_text_units_collection_build_text_unit",
        ),
    )
    op.create_index(
        op.f("ix_source_text_units_collection_id"),
        "source_text_units",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "source_text_unit_documents",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("text_unit_id", sa.String(length=128), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_text_unit_documents_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "text_unit_id"],
            [
                "source_text_units.collection_id",
                "source_text_units.build_id",
                "source_text_units.text_unit_id",
            ],
            name="fk_source_text_unit_documents_text_unit",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "text_unit_id",
            "source_document_id",
            name=op.f("pk_source_text_unit_documents"),
        ),
    )

    op.create_table(
        "source_blocks",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("block_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("block_type", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("char_range_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "block_order >= 0", name=op.f("ck_source_blocks_block_order_non_negative")
        ),
        sa.CheckConstraint(
            "page IS NULL OR page >= 0",
            name=op.f("ck_source_blocks_page_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_blocks_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("build_id", "block_id", name=op.f("pk_source_blocks")),
        sa.UniqueConstraint(
            "collection_id", "build_id", "block_id", name="uq_source_blocks_identity"
        ),
    )
    op.create_index(
        op.f("ix_source_blocks_collection_id"),
        "source_blocks",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "source_block_text_units",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("block_id", sa.String(length=128), nullable=False),
        sa.Column("text_unit_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "block_id"],
            [
                "source_blocks.collection_id",
                "source_blocks.build_id",
                "source_blocks.block_id",
            ],
            name="fk_source_block_text_units_block",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "text_unit_id"],
            [
                "source_text_units.collection_id",
                "source_text_units.build_id",
                "source_text_units.text_unit_id",
            ],
            name="fk_source_block_text_units_text_unit",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "block_id",
            "text_unit_id",
            name=op.f("pk_source_block_text_units"),
        ),
    )

    op.create_table(
        "source_tables",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("table_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("table_order", sa.Integer(), nullable=False),
        sa.Column("caption_text", sa.Text(), nullable=True),
        sa.Column("caption_block_id", sa.String(length=128), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("column_headers", _JSON_DOCUMENT, nullable=False),
        sa.Column("table_matrix", _JSON_DOCUMENT, nullable=False),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "table_order >= 0", name=op.f("ck_source_tables_table_order_non_negative")
        ),
        sa.CheckConstraint(
            "page IS NULL OR page >= 0",
            name=op.f("ck_source_tables_page_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_tables_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("build_id", "table_id", name=op.f("pk_source_tables")),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            "table_id",
            name="uq_source_tables_document_table",
        ),
    )
    op.create_index(
        op.f("ix_source_tables_collection_id"),
        "source_tables",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "source_table_rows",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("row_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("table_id", sa.String(length=128), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("row_text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "row_index >= 0", name=op.f("ck_source_table_rows_row_index_non_negative")
        ),
        sa.CheckConstraint(
            "page IS NULL OR page >= 0",
            name=op.f("ck_source_table_rows_page_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "table_id"],
            [
                "source_tables.collection_id",
                "source_tables.build_id",
                "source_tables.source_document_id",
                "source_tables.table_id",
            ],
            name="fk_source_table_rows_table",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "row_id", name=op.f("pk_source_table_rows")
        ),
        sa.UniqueConstraint(
            "collection_id", "build_id", "row_id", name="uq_source_table_rows_identity"
        ),
    )
    op.create_index(
        op.f("ix_source_table_rows_collection_id"),
        "source_table_rows",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "source_table_cells",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("cell_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("table_id", sa.String(length=128), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("col_index", sa.Integer(), nullable=False),
        sa.Column("cell_text", sa.Text(), nullable=False),
        sa.Column("header_path", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("char_range_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("unit_hint", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "row_index >= 0", name=op.f("ck_source_table_cells_row_index_non_negative")
        ),
        sa.CheckConstraint(
            "col_index >= 0", name=op.f("ck_source_table_cells_col_index_non_negative")
        ),
        sa.CheckConstraint(
            "page IS NULL OR page >= 0",
            name=op.f("ck_source_table_cells_page_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "table_id"],
            [
                "source_tables.collection_id",
                "source_tables.build_id",
                "source_tables.source_document_id",
                "source_tables.table_id",
            ],
            name="fk_source_table_cells_table",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "cell_id", name=op.f("pk_source_table_cells")
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "cell_id",
            name="uq_source_table_cells_identity",
        ),
    )
    op.create_index(
        op.f("ix_source_table_cells_collection_id"),
        "source_table_cells",
        ["collection_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_table_cells_collection_id"), table_name="source_table_cells"
    )
    op.drop_table("source_table_cells")
    op.drop_index(
        op.f("ix_source_table_rows_collection_id"), table_name="source_table_rows"
    )
    op.drop_table("source_table_rows")
    op.drop_index(op.f("ix_source_tables_collection_id"), table_name="source_tables")
    op.drop_table("source_tables")
    op.drop_table("source_block_text_units")
    op.drop_index(op.f("ix_source_blocks_collection_id"), table_name="source_blocks")
    op.drop_table("source_blocks")
    op.drop_table("source_text_unit_documents")
    op.drop_index(
        op.f("ix_source_text_units_collection_id"), table_name="source_text_units"
    )
    op.drop_table("source_text_units")
    op.drop_index(
        op.f("ix_source_documents_document_version_id"),
        table_name="source_documents",
    )
    op.drop_index(
        op.f("ix_source_documents_collection_id"), table_name="source_documents"
    )
    op.drop_table("source_documents")
    with op.batch_alter_table("collection_documents") as batch_op:
        batch_op.drop_constraint(
            "uq_collection_documents_membership_version", type_="unique"
        )
