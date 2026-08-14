"""Name Source document and text-unit sequence fields as ordering metadata."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0028"
down_revision: str | Sequence[str] | None = "20260814_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _rename_order_column(
        table_name="source_documents",
        old_column_name="human_readable_id",
        new_column_name="document_order",
    )
    _rename_order_column(
        table_name="source_text_units",
        old_column_name="human_readable_id",
        new_column_name="text_unit_order",
    )


def downgrade() -> None:
    _rename_order_column(
        table_name="source_text_units",
        old_column_name="text_unit_order",
        new_column_name="human_readable_id",
    )
    _rename_order_column(
        table_name="source_documents",
        old_column_name="document_order",
        new_column_name="human_readable_id",
    )


def _rename_order_column(
    *,
    table_name: str,
    old_column_name: str,
    new_column_name: str,
) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_constraint(
            f"{old_column_name}_non_negative",
            type_="check",
        )
        batch_op.alter_column(
            old_column_name,
            new_column_name=new_column_name,
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            f"{new_column_name}_non_negative",
            f"{new_column_name} >= 0",
        )
