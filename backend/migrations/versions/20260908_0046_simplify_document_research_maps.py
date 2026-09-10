"""Remove duplicated profile metadata and type Paper Map provenance.

Revision ID: 20260908_0046
Revises: 20260908_0045
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0046"
down_revision: str | Sequence[str] | None = "20260908_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    profile_columns = _columns("document_profiles")
    profile_changes = bool(
        profile_columns & {"collection_id", "source_filename", "parsing_warnings"}
    )
    if profile_changes:
        with op.batch_alter_table("document_profiles") as batch_op:
            if "parsing_warnings" in profile_columns:
                batch_op.alter_column(
                    "parsing_warnings",
                    new_column_name="profile_warnings",
                )
            for column_name in ("collection_id", "source_filename"):
                if column_name in profile_columns:
                    batch_op.drop_column(column_name)

    if "paper_maps" in _tables():
        paper_map_columns = _columns("paper_maps")
        for column_name, column in (
            ("input_fingerprint", sa.Column("input_fingerprint", sa.String(64))),
            ("map_version", sa.Column("map_version", sa.String(128))),
            ("generated_at", sa.Column("generated_at", sa.DateTime(timezone=True))),
        ):
            if column_name not in paper_map_columns:
                op.add_column("paper_maps", column)

        _normalize_paper_map_rows(op.get_bind())

        if "collection_id" in paper_map_columns:
            with op.batch_alter_table("paper_maps") as batch_op:
                batch_op.drop_column("collection_id")


def downgrade() -> None:
    bind = op.get_bind()
    profile_columns = _columns("document_profiles")
    if "collection_id" not in profile_columns:
        op.add_column(
            "document_profiles",
            sa.Column("collection_id", sa.String(64), nullable=True),
        )
    if "source_filename" not in profile_columns:
        op.add_column(
            "document_profiles",
            sa.Column("source_filename", sa.Text(), nullable=True),
        )
    _restore_profile_metadata(bind)
    with op.batch_alter_table("document_profiles") as batch_op:
        if "profile_warnings" in _columns("document_profiles"):
            batch_op.alter_column(
                "profile_warnings",
                new_column_name="parsing_warnings",
            )
        batch_op.alter_column("collection_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_document_profiles_collection_id_collections",
            "collections",
            ["collection_id"],
            ["collection_id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_document_profiles_collection_id",
            ["collection_id"],
        )

    if "paper_maps" in _tables():
        paper_map_columns = _columns("paper_maps")
        if "collection_id" not in paper_map_columns:
            op.add_column(
                "paper_maps",
                sa.Column("collection_id", sa.String(64), nullable=True),
            )
        _restore_paper_map_payloads(bind)
        with op.batch_alter_table("paper_maps") as batch_op:
            batch_op.alter_column("collection_id", nullable=False)
            batch_op.create_foreign_key(
                "fk_paper_maps_collection_id_collections",
                "collections",
                ["collection_id"],
                ["collection_id"],
                ondelete="CASCADE",
            )
            batch_op.create_index("ix_paper_maps_collection_id", ["collection_id"])
            for column_name in ("input_fingerprint", "map_version", "generated_at"):
                if column_name in paper_map_columns:
                    batch_op.drop_column(column_name)


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _normalize_paper_map_rows(bind: sa.Connection) -> None:
    table = sa.Table("paper_maps", sa.MetaData(), autoload_with=bind)
    for row in bind.execute(sa.select(table)).mappings():
        payload = _mapping(row.get("payload"))
        values = {
            "input_fingerprint": _text(payload.pop("input_fingerprint", None)),
            "map_version": _text(payload.pop("map_version", None)),
            "generated_at": _datetime(payload.pop("generated_at", None)),
        }
        payload.pop("document_id", None)
        values["payload"] = payload
        bind.execute(
            table.update()
            .where(table.c.document_id == row["document_id"])
            .values(**values)
        )


def _restore_profile_metadata(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("documents", "document_profiles"))
    documents = metadata.tables["documents"]
    profiles = metadata.tables["document_profiles"]
    for row in bind.execute(sa.select(profiles)).mappings():
        document = bind.execute(
            sa.select(documents).where(documents.c.document_id == row["document_id"])
        ).mappings().one()
        bind.execute(
            profiles.update()
            .where(profiles.c.document_id == row["document_id"])
            .values(
                collection_id=document["collection_id"],
                source_filename=document["original_filename"],
            )
        )


def _restore_paper_map_payloads(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("documents", "paper_maps"))
    documents = metadata.tables["documents"]
    paper_maps = metadata.tables["paper_maps"]
    for row in bind.execute(sa.select(paper_maps)).mappings():
        document = bind.execute(
            sa.select(documents).where(documents.c.document_id == row["document_id"])
        ).mappings().one()
        payload = _mapping(row.get("payload"))
        payload["document_id"] = row["document_id"]
        payload["input_fingerprint"] = _text(row.get("input_fingerprint"))
        if (map_version := _text(row.get("map_version"))) is not None:
            payload["map_version"] = map_version
        if (generated_at := row.get("generated_at")) is not None:
            payload["generated_at"] = _iso(generated_at)
        bind.execute(
            paper_maps.update()
            .where(paper_maps.c.document_id == row["document_id"])
            .values(
                collection_id=document["collection_id"],
                payload=payload,
            )
        )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    normalized = _text(value)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized.replace("Z", "+00:00"))


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)
