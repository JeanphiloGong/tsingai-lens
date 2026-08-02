"""Rebuild ObjectiveEvidence scientific attribution.

Revision ID: 20260802_0021
Revises: 20260802_0020
Create Date: 2026-08-02 17:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260802_0021"
down_revision: Union[str, Sequence[str], None] = "20260802_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Invalidate analyses and replace the old Evidence payload directly."""

    op.execute(
        "UPDATE research_objectives "
        "SET active_analysis_version = NULL, published_analysis_version = NULL"
    )
    op.execute("DELETE FROM objective_finding_relation_evidence_links")
    op.execute("DELETE FROM objective_finding_evidence_links")
    op.execute("DELETE FROM objective_analyses")

    json_document = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    with op.batch_alter_table("objective_evidence") as batch_op:
        batch_op.drop_column("evidence_kind")
        batch_op.drop_column("property_normalized")
        batch_op.drop_column("material_system")
        batch_op.drop_column("sample_context")
        batch_op.drop_column("process_context")
        batch_op.drop_column("test_condition")
        batch_op.drop_column("resolved_condition")
        batch_op.drop_column("value_payload")
        batch_op.drop_column("unit")
        batch_op.drop_column("baseline_context")
        batch_op.drop_column("interpretation")
        batch_op.drop_column("join_keys")
        batch_op.add_column(
            sa.Column(
                "changed_variables",
                json_document,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column("comparison", json_document, nullable=True)
        )
        batch_op.add_column(
            sa.Column("reported_result", json_document, nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "attribution_scope",
                sa.String(length=32),
                nullable=False,
                server_default="not_attributable",
            )
        )
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
        batch_op.create_check_constraint(
            "attribution_scope_valid",
            "attribution_scope IN ('isolated_effect', 'joint_effect', "
            "'association_only', 'descriptive_only', 'not_attributable')",
        )

    with op.batch_alter_table("objective_evidence") as batch_op:
        batch_op.alter_column("changed_variables", server_default=None)
        batch_op.alter_column("attribution_scope", server_default=None)
        batch_op.alter_column("scientific_context", server_default=None)


def downgrade() -> None:
    """Old Evidence attribution cannot be reconstructed after invalidation."""

    raise NotImplementedError(
        "20260802_0021 is irreversible: old Evidence payloads cannot recover "
        "changed variables, comparability, or attribution scope"
    )
