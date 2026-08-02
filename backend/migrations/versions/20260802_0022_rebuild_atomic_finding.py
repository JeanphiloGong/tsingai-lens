"""Rebuild the atomic scientific Finding contract.

Revision ID: 20260802_0022
Revises: 20260802_0021
Create Date: 2026-08-02 19:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260802_0022"
down_revision: Union[str, Sequence[str], None] = "20260802_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Invalidate analyses and replace the old Finding payload directly."""

    op.execute(
        "UPDATE research_objectives "
        "SET active_analysis_version = NULL, published_analysis_version = NULL"
    )
    op.execute("DELETE FROM objective_finding_relation_evidence_links")
    op.execute("DELETE FROM objective_finding_evidence_links")
    op.execute("DELETE FROM objective_analyses")

    op.drop_table("objective_finding_derivations")

    json_document = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    with op.batch_alter_table("objective_findings") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_objective_findings_finding_level_valid"), type_="check"
        )
        batch_op.drop_constraint(
            op.f("ck_objective_findings_evidence_strength_valid"), type_="check"
        )
        batch_op.drop_constraint(
            op.f("ck_objective_findings_confidence_range"), type_="check"
        )
        batch_op.drop_constraint(
            op.f("ck_objective_findings_paper_count_positive"), type_="check"
        )
        for column_name in (
            "finding_level",
            "variables",
            "mediators",
            "outcomes",
            "scope_summary",
            "evidence_strength",
            "generalization_status",
            "paper_count",
            "confidence",
        ):
            batch_op.drop_column(column_name)
        batch_op.add_column(
            sa.Column(
                "factors",
                json_document,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(sa.Column("outcome", sa.Text(), nullable=False))
        batch_op.alter_column(
            "direction",
            existing_type=sa.Text(),
            type_=sa.String(length=32),
            nullable=False,
        )
        batch_op.add_column(
            sa.Column("assertion_strength", sa.String(length=16), nullable=False)
        )
        batch_op.add_column(
            sa.Column("attribution_scope", sa.String(length=32), nullable=False)
        )
        batch_op.add_column(
            sa.Column("synthesis_status", sa.String(length=32), nullable=False)
        )
        batch_op.add_column(sa.Column("certainty", sa.Float(), nullable=False))
        batch_op.create_check_constraint(
            op.f("ck_objective_findings_certainty_range"),
            "certainty >= 0 AND certainty <= 1",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_findings_direction_valid"),
            "direction IN ('increase', 'decrease', 'improve', 'worsen', "
            "'no_change', 'mixed', 'unknown')",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_findings_assertion_strength_valid"),
            "assertion_strength IN ('causal', 'associative', 'descriptive')",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_findings_attribution_scope_valid"),
            "attribution_scope IN ('isolated_effect', 'joint_effect', "
            "'association_only', 'descriptive_only')",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_findings_synthesis_status_valid"),
            "synthesis_status IN ('agreement', 'conflict', "
            "'condition_dependent', 'insufficient_confirmation')",
        )

    with op.batch_alter_table("objective_findings") as batch_op:
        batch_op.alter_column("factors", server_default=None)

    with op.batch_alter_table("objective_finding_contexts") as batch_op:
        for column_name in (
            "material_system",
            "process_conditions",
            "sample_state",
            "test_conditions",
            "comparison_baseline",
        ):
            batch_op.drop_column(column_name)
        batch_op.add_column(
            sa.Column(
                "scientific_context",
                json_document,
                nullable=False,
                server_default=sa.text(
                    "'{\"material\": [], \"sample\": [], "
                    "\"process\": [], \"test\": []}'"
                ),
            )
        )

    with op.batch_alter_table("objective_finding_contexts") as batch_op:
        batch_op.alter_column("scientific_context", server_default=None)

    with op.batch_alter_table("objective_finding_relations") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_objective_finding_relations_assertion_strength_valid"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_finding_relations_assertion_strength_valid"),
            "assertion_strength IN ('causal', 'associative', 'descriptive')",
        )

    with op.batch_alter_table("objective_finding_evidence_links") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_objective_finding_evidence_links_link_role_valid"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_finding_evidence_links_link_role_valid"),
            "link_role IN ('supporting', 'contradicting', 'context', 'boundary')",
        )
        batch_op.create_unique_constraint(
            op.f(
                "uq_objective_finding_evidence_links_link_role_position_unique"
            ),
            [
                "collection_id",
                "objective_id",
                "analysis_version",
                "finding_id",
                "link_role",
                "position",
            ],
        )

    with op.batch_alter_table(
        "objective_finding_relation_evidence_links"
    ) as batch_op:
        batch_op.create_unique_constraint(
            op.f("uq_obj_find_rel_evidence_relation_position"),
            [
                "collection_id",
                "objective_id",
                "analysis_version",
                "finding_id",
                "relation_order",
                "position",
            ],
        )

    op.create_table(
        "objective_finding_paper_contributions",
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.String(length=128), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("paper_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "paper_order >= 0",
            name=op.f(
                "ck_objective_finding_paper_contributions_paper_order_non_negative"
            ),
        ),
        sa.UniqueConstraint(
            "collection_id",
            "objective_id",
            "analysis_version",
            "finding_id",
            "paper_order",
            name=op.f(
                "uq_objective_finding_paper_contributions_paper_order_unique"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version", "finding_id"],
            [
                "objective_findings.collection_id",
                "objective_findings.objective_id",
                "objective_findings.analysis_version",
                "objective_findings.finding_id",
            ],
            name="fk_objective_finding_paper_contributions_finding",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "collection_id",
                "objective_id",
                "analysis_version",
                "source_document_id",
            ],
            [
                "objective_paper_contributions.collection_id",
                "objective_paper_contributions.objective_id",
                "objective_paper_contributions.analysis_version",
                "objective_paper_contributions.source_document_id",
            ],
            name="fk_objective_finding_paper_contributions_contribution",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            "objective_id",
            "analysis_version",
            "finding_id",
            "source_document_id",
            name=op.f("pk_objective_finding_paper_contributions"),
        ),
    )


def downgrade() -> None:
    """Old Finding semantics cannot be reconstructed after invalidation."""

    raise NotImplementedError(
        "20260802_0022 is irreversible: atomic Findings cannot recover the old "
        "multi-outcome Finding and derivation payloads"
    )
