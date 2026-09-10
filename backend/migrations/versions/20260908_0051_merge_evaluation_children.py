"""Embed evaluation aggregate children in their parent records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0051"
down_revision: str | Sequence[str] | None = "20260908_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables()
    additions = (
        (
            "evaluation_gold_sets",
            "items",
            sa.Column("items", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        ),
        (
            "evaluation_prediction_snapshots",
            "items",
            sa.Column("items", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        ),
        (
            "evaluation_runs",
            "scores",
            sa.Column("scores", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        ),
        (
            "evaluation_runs",
            "failures",
            sa.Column("failures", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        ),
    )
    for table_name, column_name, column in additions:
        if table_name in tables and column_name not in _columns(table_name):
            op.add_column(table_name, column)

    if "evaluation_gold_sets" in tables and "evaluation_gold_items" in tables:
        _embed_children(
            bind,
            parent_name="evaluation_gold_sets",
            child_name="evaluation_gold_items",
            parent_key="gold_id",
            target_column="items",
            sort_keys=("document_id", "family", "item_key", "gold_item_id"),
        )
    if (
        "evaluation_prediction_snapshots" in tables
        and "evaluation_prediction_items" in tables
    ):
        _embed_children(
            bind,
            parent_name="evaluation_prediction_snapshots",
            child_name="evaluation_prediction_items",
            parent_key="snapshot_id",
            target_column="items",
            sort_keys=("document_id", "family", "item_key", "item_id"),
        )
    if "evaluation_runs" in tables and "evaluation_scores" in tables:
        _embed_children(
            bind,
            parent_name="evaluation_runs",
            child_name="evaluation_scores",
            parent_key="evaluation_run_id",
            target_column="scores",
            sort_keys=("family", "metric", "score_id"),
        )
    if "evaluation_runs" in tables and "evaluation_failures" in tables:
        _embed_children(
            bind,
            parent_name="evaluation_runs",
            child_name="evaluation_failures",
            parent_key="evaluation_run_id",
            target_column="failures",
            sort_keys=("document_id", "family", "failure_id"),
        )

    for table_name in (
        "evaluation_failures",
        "evaluation_scores",
        "evaluation_prediction_items",
        "evaluation_gold_items",
    ):
        if table_name in _tables():
            op.drop_table(table_name)


def downgrade() -> None:
    if "evaluation_gold_sets" not in _tables():
        return
    raise RuntimeError(
        "20260908_0051 is an irreversible consolidation of evaluation aggregates"
    )


def _embed_children(
    bind: sa.Connection,
    *,
    parent_name: str,
    child_name: str,
    parent_key: str,
    target_column: str,
    sort_keys: tuple[str, ...],
) -> None:
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=(parent_name, child_name))
    parent = metadata.tables[parent_name]
    child = metadata.tables[child_name]
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for row in bind.execute(sa.select(child)).mappings():
        grouped[str(row[parent_key])].append(dict(row))
    for key, rows in grouped.items():
        rows.sort(key=lambda row: tuple(str(row.get(name) or "") for name in sort_keys))
        bind.execute(
            parent.update()
            .where(parent.c[parent_key] == key)
            .values(**{target_column: rows})
        )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
