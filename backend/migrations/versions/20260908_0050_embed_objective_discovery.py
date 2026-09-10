"""Store the current Objective discovery snapshot on Collections."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0050"
down_revision: str | Sequence[str] | None = "20260908_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "collections" not in _tables():
        return
    columns = _columns("collections")
    additions = (
        ("discovery_ready", sa.Column("discovery_ready", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("discovery_document_inputs", sa.Column("discovery_document_inputs", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))),
        ("discovery_objective_ids", sa.Column("discovery_objective_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))),
        ("discovery_study_dispositions", sa.Column("discovery_study_dispositions", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))),
        ("discovery_updated_at", sa.Column("discovery_updated_at", sa.DateTime(timezone=True), nullable=True)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("collections", column)

    if "objective_discovery" not in _tables():
        return
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("collections", "objective_discovery"))
    collections = metadata.tables["collections"]
    discovery = metadata.tables["objective_discovery"]
    for row in bind.execute(sa.select(discovery)).mappings():
        bind.execute(
            collections.update()
            .where(collections.c.collection_id == row["collection_id"])
            .values(
                discovery_ready=row["research_objectives_ready"],
                discovery_document_inputs=row["document_inputs"],
                discovery_objective_ids=row["objective_ids"],
                discovery_study_dispositions=row["study_dispositions"],
                discovery_updated_at=row["updated_at"],
            )
        )
    op.drop_table("objective_discovery")


def downgrade() -> None:
    if "collections" not in _tables():
        return
    raise RuntimeError(
        "20260908_0050 is an irreversible consolidation of the current discovery snapshot"
    )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
