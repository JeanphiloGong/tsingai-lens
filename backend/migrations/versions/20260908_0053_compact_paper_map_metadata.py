"""Keep Paper Map metadata in its JSON payload and enforce Objective ownership."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0053"
down_revision: str | Sequence[str] | None = "20260908_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "document_profiles" in _tables():
        _embed_paper_map_metadata(bind)
    if "research_objectives" in _tables() and "collections" in _tables():
        _add_objective_collection_fk(bind)


def downgrade() -> None:
    raise RuntimeError(
        "20260908_0053 is an irreversible schema simplification and integrity fix"
    )


def _embed_paper_map_metadata(bind: sa.Connection) -> None:
    columns = _columns("document_profiles")
    metadata_columns = {
        "paper_map_input_fingerprint",
        "paper_map_version",
        "paper_map_generated_at",
    }
    if not metadata_columns.intersection(columns):
        return

    table = sa.Table("document_profiles", sa.MetaData(), autoload_with=bind)
    for row in bind.execute(sa.select(table)).mappings():
        payload = dict(row.get("paper_map_payload") or {})
        if not payload and not any(
            row.get(name) is not None
            for name in metadata_columns
        ):
            continue
        payload.setdefault("document_id", row["document_id"])
        if row.get("paper_map_input_fingerprint") is not None:
            payload.setdefault("input_fingerprint", row["paper_map_input_fingerprint"])
        if row.get("paper_map_version") is not None:
            payload.setdefault("map_version", row["paper_map_version"])
        generated_at = row.get("paper_map_generated_at")
        if generated_at is not None:
            payload.setdefault("generated_at", _iso_datetime(generated_at))
        bind.execute(
            table.update()
            .where(table.c.document_id == row["document_id"])
            .values(paper_map_payload=payload)
        )

    with op.batch_alter_table("document_profiles") as batch:
        for name in metadata_columns:
            if name in columns:
                batch.drop_column(name)


def _add_objective_collection_fk(bind: sa.Connection) -> None:
    foreign_keys = sa.inspect(bind).get_foreign_keys("research_objectives")
    if any(
        fk.get("constrained_columns") == ["collection_id"]
        and fk.get("referred_table") == "collections"
        for fk in foreign_keys
    ):
        return
    orphan = bind.execute(
        sa.text(
            "SELECT collection_id, objective_id "
            "FROM research_objectives "
            "WHERE collection_id NOT IN (SELECT collection_id FROM collections) "
            "LIMIT 1"
        )
    ).first()
    if orphan is not None:
        raise RuntimeError(
            "cannot add research_objectives collection FK; orphan objective "
            f"{orphan[0]}/{orphan[1]} exists"
        )
    with op.batch_alter_table("research_objectives") as batch:
        batch.create_foreign_key(
            "fk_research_objectives_collection",
            "collections",
            ["collection_id"],
            ["collection_id"],
            ondelete="CASCADE",
        )


def _iso_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
