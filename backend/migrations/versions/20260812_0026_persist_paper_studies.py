"""Persist source-linked paper studies and relationship lineage.

Revision ID: 20260812_0026
Revises: 20260811_0025
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260812_0026"
down_revision: str | Sequence[str] | None = "20260811_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # Former independent skim axes cannot be converted into experiment identities.
    op.execute("UPDATE objective_builds SET research_objectives_ready = false")
    op.drop_table("objective_document_scope")
    op.create_table(
        "objective_document_scope",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "scope_kind IN ('seed', 'excluded')",
            name=op.f("ck_objective_document_scope_scope_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "collection_id", "objective_id"],
            [
                "objective_build_candidates.build_id",
                "objective_build_candidates.collection_id",
                "objective_build_candidates.objective_id",
            ],
            name="fk_objective_document_scope_build_objective",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "collection_id",
            "objective_id",
            "scope_kind",
            "source_document_id",
            name=op.f("pk_objective_document_scope"),
        ),
    )
    with op.batch_alter_table("objective_paper_skims") as batch_op:
        batch_op.drop_column("possible_objectives")
        batch_op.drop_column("changed_variables")
        batch_op.drop_column("candidate_properties")
        batch_op.drop_column("candidate_processes")
        batch_op.drop_column("candidate_materials")

    op.create_table(
        "objective_paper_source_unit_coverage",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("source_unit_id", sa.String(length=160), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("coverage_order", sa.Integer(), nullable=False),
        sa.Column("window_id", sa.String(length=160), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source_kind IN ('document', 'block', 'table', 'table_row', 'figure')",
            name=op.f("ck_objective_paper_source_unit_coverage_source_kind_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('relationship_emitted', 'unresolved_signal_emitted', "
            "'no_study_signal', 'extraction_failed')",
            name=op.f("ck_objective_paper_source_unit_coverage_status_valid"),
        ),
        sa.CheckConstraint(
            "(status IN ('relationship_emitted', 'unresolved_signal_emitted') "
            "AND reason IS NULL) OR "
            "(status IN ('no_study_signal', 'extraction_failed') "
            "AND reason IS NOT NULL)",
            name=op.f("ck_objective_paper_source_unit_coverage_reason_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "source_document_id"],
            [
                "objective_paper_skims.build_id",
                "objective_paper_skims.source_document_id",
            ],
            name="fk_objective_paper_source_unit_coverage_skim",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_paper_source_unit_coverage_source_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "source_document_id",
            "source_unit_id",
            name=op.f("pk_objective_paper_source_unit_coverage"),
        ),
    )
    op.create_index(
        op.f("ix_objective_paper_source_unit_coverage_collection_id"),
        "objective_paper_source_unit_coverage",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "objective_paper_studies",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("study_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("study_order", sa.Integer(), nullable=False),
        sa.Column("design_type", sa.String(length=32), nullable=False),
        sa.Column("claim_scope", sa.String(length=32), nullable=False),
        sa.Column("experiment_label", sa.Text(), nullable=True),
        sa.Column("material_scope", _JSON_DOCUMENT, nullable=False),
        sa.Column("process_context", _JSON_DOCUMENT, nullable=False),
        sa.Column("sample_context", _JSON_DOCUMENT, nullable=False),
        sa.Column("test_context", _JSON_DOCUMENT, nullable=False),
        sa.Column("comparator", sa.Text(), nullable=True),
        sa.Column("fixed_conditions", _JSON_DOCUMENT, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "design_type IN ('experimental', 'modeling', 'observational', "
            "'mixed', 'uncertain')",
            name=op.f("ck_objective_paper_studies_design_type_valid"),
        ),
        sa.CheckConstraint(
            "claim_scope IN ('current_work', 'synthesis', 'background', 'uncertain')",
            name=op.f("ck_objective_paper_studies_claim_scope_valid"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_objective_paper_studies_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "source_document_id"],
            [
                "objective_paper_skims.build_id",
                "objective_paper_skims.source_document_id",
            ],
            name="fk_objective_paper_studies_skim",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_objective_paper_studies_source_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "source_document_id",
            "study_id",
            name=op.f("pk_objective_paper_studies"),
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            "study_id",
            name="uq_objective_paper_studies_collection_identity",
        ),
    )
    op.create_index(
        op.f("ix_objective_paper_studies_collection_id"),
        "objective_paper_studies",
        ["collection_id"],
        unique=False,
    )

    op.create_table(
        "objective_paper_study_relationships",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("study_id", sa.String(length=128), nullable=False),
        sa.Column("relationship_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("relationship_order", sa.Integer(), nullable=False),
        sa.Column("varied_factors", _JSON_DOCUMENT, nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("source_refs", _JSON_DOCUMENT, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_objective_paper_study_relationships_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "study_id"],
            [
                "objective_paper_studies.collection_id",
                "objective_paper_studies.build_id",
                "objective_paper_studies.source_document_id",
                "objective_paper_studies.study_id",
            ],
            name="fk_objective_paper_study_relationships_study",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "source_document_id",
            "study_id",
            "relationship_id",
            name=op.f("pk_objective_paper_study_relationships"),
        ),
        sa.UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            "study_id",
            "relationship_id",
            name="uq_objective_paper_study_relationships_collection_identity",
        ),
    )

    op.create_table(
        "objective_paper_study_signals",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("signal_order", sa.Integer(), nullable=False),
        sa.Column("payload", _JSON_DOCUMENT, nullable=False),
        sa.ForeignKeyConstraint(
            ["build_id", "source_document_id"],
            [
                "objective_paper_skims.build_id",
                "objective_paper_skims.source_document_id",
            ],
            name="fk_objective_paper_study_signals_skim",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "source_document_id",
            "signal_id",
            name=op.f("pk_objective_paper_study_signals"),
        ),
    )

    op.create_table(
        "objective_paper_study_dispositions",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("study_id", sa.String(length=128), nullable=False),
        sa.Column("relationship_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'promoted', 'rejected')",
            name=op.f("ck_objective_paper_study_dispositions_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND objective_id IS NULL AND reason IS NULL) OR "
            "(status = 'promoted' AND objective_id IS NOT NULL AND reason IS NULL) OR "
            "(status = 'rejected' AND objective_id IS NULL AND reason IS NOT NULL)",
            name=op.f("ck_objective_paper_study_dispositions_result_valid"),
        ),
        sa.ForeignKeyConstraint(
            [
                "collection_id",
                "build_id",
                "source_document_id",
                "study_id",
                "relationship_id",
            ],
            [
                "objective_paper_study_relationships.collection_id",
                "objective_paper_study_relationships.build_id",
                "objective_paper_study_relationships.source_document_id",
                "objective_paper_study_relationships.study_id",
                "objective_paper_study_relationships.relationship_id",
            ],
            name="fk_objective_paper_study_dispositions_relationship",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_paper_study_dispositions_objective",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "source_document_id",
            "study_id",
            "relationship_id",
            name=op.f("pk_objective_paper_study_dispositions"),
        ),
    )

    op.create_table(
        "objective_build_relationship_links",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("study_id", sa.String(length=128), nullable=False),
        sa.Column("relationship_id", sa.String(length=128), nullable=False),
        sa.Column("link_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["build_id", "collection_id", "objective_id"],
            [
                "objective_build_candidates.build_id",
                "objective_build_candidates.collection_id",
                "objective_build_candidates.objective_id",
            ],
            name="fk_objective_build_relationship_links_objective",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "collection_id",
                "build_id",
                "source_document_id",
                "study_id",
                "relationship_id",
            ],
            [
                "objective_paper_study_relationships.collection_id",
                "objective_paper_study_relationships.build_id",
                "objective_paper_study_relationships.source_document_id",
                "objective_paper_study_relationships.study_id",
                "objective_paper_study_relationships.relationship_id",
            ],
            name="fk_objective_build_relationship_links_relationship",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "collection_id",
            "objective_id",
            "source_document_id",
            "study_id",
            "relationship_id",
            name=op.f("pk_objective_build_relationship_links"),
        ),
        sa.UniqueConstraint(
            "build_id",
            "source_document_id",
            "study_id",
            "relationship_id",
            name="uq_objective_build_relationship_links_accounting",
        ),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "revision 20260812_0026 is irreversible because independent PaperSkim "
        "axis lists cannot reconstruct source-linked studies"
    )
