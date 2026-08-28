"""Add versioned Source figures and references.

Revision ID: 20260719_0008
Revises: 20260719_0007
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260719_0008"
down_revision: str | Sequence[str] | None = "20260719_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("source_blocks") as batch_op:
        batch_op.create_unique_constraint(
            "uq_source_blocks_document_block",
            ["collection_id", "build_id", "source_document_id", "block_id"],
        )

    op.create_table(
        "source_figures",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("figure_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("figure_order", sa.Integer(), nullable=False),
        sa.Column("figure_label", sa.Text(), nullable=True),
        sa.Column("caption_text", sa.Text(), nullable=True),
        sa.Column("caption_block_id", sa.String(length=128), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _JSON_DOCUMENT, nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("image_storage_key", sa.Text(), nullable=True),
        sa.Column("image_mime_type", sa.String(length=255), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("asset_sha256", sa.String(length=64), nullable=True),
        sa.Column("image_size_bytes", sa.Integer(), nullable=True),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "figure_order >= 0",
            name=op.f("ck_source_figures_figure_order_non_negative"),
        ),
        sa.CheckConstraint(
            "page IS NULL OR page >= 0",
            name=op.f("ck_source_figures_page_non_negative"),
        ),
        sa.CheckConstraint(
            "image_width IS NULL OR image_width >= 0",
            name=op.f("ck_source_figures_image_width_non_negative"),
        ),
        sa.CheckConstraint(
            "image_height IS NULL OR image_height >= 0",
            name=op.f("ck_source_figures_image_height_non_negative"),
        ),
        sa.CheckConstraint(
            "image_size_bytes IS NULL OR image_size_bytes >= 0",
            name=op.f("ck_source_figures_image_size_bytes_non_negative"),
        ),
        sa.CheckConstraint(
            "(image_storage_key IS NULL AND asset_sha256 IS NULL "
            "AND image_size_bytes IS NULL) OR "
            "(image_storage_key IS NOT NULL AND asset_sha256 IS NOT NULL "
            "AND image_size_bytes IS NOT NULL)",
            name=op.f("ck_source_figures_image_object_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_figures_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "figure_id", name=op.f("pk_source_figures")
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            "figure_id",
            name="uq_source_figures_document_figure",
        ),
    )
    op.create_index(
        op.f("ix_source_figures_collection_id"),
        "source_figures",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "source_reference_entries",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("raw_reference", sa.Text(), nullable=False),
        sa.Column("reference_index", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("authors_text", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("doi", sa.Text(), nullable=True),
        sa.Column("source_block_id", sa.String(length=128), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "year IS NULL OR year >= 0",
            name=op.f("ck_source_reference_entries_year_non_negative"),
        ),
        sa.CheckConstraint(
            "page IS NULL OR page >= 0",
            name=op.f("ck_source_reference_entries_page_non_negative"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_source_reference_entries_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_reference_entries_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "source_block_id"],
            [
                "source_blocks.collection_id",
                "source_blocks.build_id",
                "source_blocks.source_document_id",
                "source_blocks.block_id",
            ],
            name="fk_source_reference_entries_block",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "reference_id", name=op.f("pk_source_reference_entries")
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "reference_id",
            name="uq_source_reference_entries_identity",
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "reference_id",
            "source_document_id",
            name="uq_source_reference_entries_document",
        ),
    )
    op.create_index(
        op.f("ix_source_reference_entries_collection_id"),
        "source_reference_entries",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "source_reference_mentions",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("mention_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("reference_id", sa.String(length=128), nullable=True),
        sa.Column("citation_marker", sa.Text(), nullable=False),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("source_block_id", sa.String(length=128), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "page IS NULL OR page >= 0",
            name=op.f("ck_source_reference_mentions_page_non_negative"),
        ),
        sa.CheckConstraint(
            "char_start IS NULL OR char_start >= 0",
            name=op.f("ck_source_reference_mentions_char_start_non_negative"),
        ),
        sa.CheckConstraint(
            "char_end IS NULL OR char_end >= 0",
            name=op.f("ck_source_reference_mentions_char_end_non_negative"),
        ),
        sa.CheckConstraint(
            "char_start IS NULL OR char_end IS NULL OR char_end >= char_start",
            name=op.f("ck_source_reference_mentions_char_range_ordered"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_source_reference_mentions_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_reference_mentions_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "source_block_id"],
            [
                "source_blocks.collection_id",
                "source_blocks.build_id",
                "source_blocks.source_document_id",
                "source_blocks.block_id",
            ],
            name="fk_source_reference_mentions_block",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id", "source_document_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
                "source_reference_entries.source_document_id",
            ],
            name="fk_source_reference_mentions_entry",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "mention_id", name=op.f("pk_source_reference_mentions")
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "mention_id",
            name="uq_source_reference_mentions_identity",
        ),
    )
    op.create_index(
        op.f("ix_source_reference_mentions_collection_id"),
        "source_reference_mentions",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "source_reference_resolutions",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("resolution_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("resolved_title", sa.Text(), nullable=True),
        sa.Column("resolved_authors_text", sa.Text(), nullable=True),
        sa.Column("resolved_year", sa.Integer(), nullable=True),
        sa.Column("resolved_venue", sa.Text(), nullable=True),
        sa.Column("resolved_doi", sa.Text(), nullable=True),
        sa.Column("resolved_url", sa.Text(), nullable=True),
        sa.Column("open_access_url", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "resolved_year IS NULL OR resolved_year >= 0",
            name=op.f(
                "ck_source_reference_resolutions_resolved_year_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_source_reference_resolutions_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
            ],
            name="fk_source_reference_resolutions_entry",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "resolution_id",
            name=op.f("pk_source_reference_resolutions"),
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "resolution_id",
            name="uq_source_reference_resolutions_identity",
        ),
    )
    op.create_index(
        op.f("ix_source_reference_resolutions_collection_id"),
        "source_reference_resolutions",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "source_reference_candidates",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("relevance_reason", sa.Text(), nullable=True),
        sa.Column("cited_by_document_id", sa.String(length=128), nullable=True),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.Column("representative_context", sa.Text(), nullable=True),
        sa.Column("resolved_doi", sa.Text(), nullable=True),
        sa.Column("resolved_url", sa.Text(), nullable=True),
        sa.Column("open_access_url", sa.Text(), nullable=True),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1",
            name=op.f("ck_source_reference_candidates_relevance_score_range"),
        ),
        sa.CheckConstraint(
            "mention_count >= 0",
            name=op.f("ck_source_reference_candidates_mention_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
            ],
            name="fk_source_reference_candidates_entry",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id", "cited_by_document_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
                "source_reference_entries.source_document_id",
            ],
            name="fk_source_reference_candidates_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "candidate_id",
            name=op.f("pk_source_reference_candidates"),
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "candidate_id",
            name="uq_source_reference_candidates_identity",
        ),
    )
    op.create_index(
        op.f("ix_source_reference_candidates_collection_id"),
        "source_reference_candidates",
        ["collection_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_reference_candidates_collection_id"),
        table_name="source_reference_candidates",
    )
    op.drop_table("source_reference_candidates")
    op.drop_index(
        op.f("ix_source_reference_resolutions_collection_id"),
        table_name="source_reference_resolutions",
    )
    op.drop_table("source_reference_resolutions")
    op.drop_index(
        op.f("ix_source_reference_mentions_collection_id"),
        table_name="source_reference_mentions",
    )
    op.drop_table("source_reference_mentions")
    op.drop_index(
        op.f("ix_source_reference_entries_collection_id"),
        table_name="source_reference_entries",
    )
    op.drop_table("source_reference_entries")
    op.drop_index(
        op.f("ix_source_figures_collection_id"), table_name="source_figures"
    )
    op.drop_table("source_figures")
    with op.batch_alter_table("source_blocks") as batch_op:
        batch_op.drop_constraint(
            "uq_source_blocks_document_block", type_="unique"
        )
