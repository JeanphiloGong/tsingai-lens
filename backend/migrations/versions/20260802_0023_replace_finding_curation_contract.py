"""Replace retired Finding curation fields with one atomic Finding record."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260802_0023"
down_revision = "20260802_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_document = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    op.execute("DELETE FROM finding_curation_records")
    with op.batch_alter_table("finding_curation_records") as batch_op:
        for column_name in (
            "curated_statement",
            "curated_support_grade",
            "curated_review_status",
            "curated_variables",
            "curated_mediators",
            "curated_outcomes",
            "curated_direction",
            "curated_scope_summary",
            "curated_evidence_ids",
        ):
            batch_op.drop_column(column_name)
        batch_op.add_column(sa.Column("curated_finding", json_document, nullable=False))


def downgrade() -> None:
    raise NotImplementedError(
        "revision 20260802_0023 is irreversible because retired curation "
        "semantics cannot be reconstructed"
    )
