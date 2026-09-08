"""Store the current Paper Map beside its Document Profile."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0047"
down_revision: str | Sequence[str] | None = "7f4a0a872e9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "document_profiles" not in _tables():
        return
    profile_columns = _columns("document_profiles")
    additions = (
        ("paper_map_payload", sa.Column("paper_map_payload", sa.JSON(), nullable=True)),
        ("paper_map_input_fingerprint", sa.Column("paper_map_input_fingerprint", sa.String(64), nullable=True)),
        ("paper_map_version", sa.Column("paper_map_version", sa.String(128), nullable=True)),
        ("paper_map_generated_at", sa.Column("paper_map_generated_at", sa.DateTime(timezone=True), nullable=True)),
    )
    for name, column in additions:
        if name not in profile_columns:
            op.add_column("document_profiles", column)

    if "paper_maps" not in _tables():
        return

    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("document_profiles", "paper_maps"))
    profiles = metadata.tables["document_profiles"]
    paper_maps = metadata.tables["paper_maps"]
    for row in bind.execute(sa.select(paper_maps)).mappings():
        payload = dict(row.get("payload") or {})
        payload.pop("document_id", None)
        bind.execute(
            profiles.update()
            .where(profiles.c.document_id == row["document_id"])
            .values(
                paper_map_payload=payload,
                paper_map_input_fingerprint=row.get("input_fingerprint"),
                paper_map_version=row.get("map_version"),
                paper_map_generated_at=row.get("generated_at"),
            )
        )
    op.drop_table("paper_maps")


def downgrade() -> None:
    bind = op.get_bind()
    if "document_profiles" not in _tables():
        return
    if "paper_maps" not in _tables():
        op.create_table(
            "paper_maps",
            sa.Column("document_id", sa.String(128), nullable=False),
            sa.Column("input_fingerprint", sa.String(64), nullable=True),
            sa.Column("map_version", sa.String(128), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.document_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("document_id"),
        )
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("document_profiles", "paper_maps"))
    profiles = metadata.tables["document_profiles"]
    paper_maps = metadata.tables["paper_maps"]
    for row in bind.execute(sa.select(profiles).where(profiles.c.paper_map_payload.is_not(None))).mappings():
        bind.execute(
            paper_maps.insert().values(
                document_id=row["document_id"],
                input_fingerprint=row["paper_map_input_fingerprint"],
                map_version=row["paper_map_version"],
                generated_at=row["paper_map_generated_at"],
                payload=row["paper_map_payload"],
            )
        )
    with op.batch_alter_table("document_profiles") as batch:
        for name, _ in (
            ("paper_map_generated_at", None),
            ("paper_map_version", None),
            ("paper_map_input_fingerprint", None),
            ("paper_map_payload", None),
        ):
            if name in _columns("document_profiles"):
                batch.drop_column(name)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
