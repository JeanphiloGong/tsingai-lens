"""Merge current Source and Profile rows into one document preparation aggregate."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260908_0054"
down_revision: str | Sequence[str] | None = "20260908_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if "document_preparations" not in tables:
        op.create_table(
            "document_preparations",
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("source_format", sa.String(length=32), nullable=True),
            sa.Column("parser_name", sa.String(length=128), nullable=True),
            sa.Column("parser_version", sa.String(length=128), nullable=True),
            sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
            sa.Column("artifact_json", _JSON_DOCUMENT, nullable=True),
            sa.Column("profile_json", _JSON_DOCUMENT, nullable=True),
            sa.Column("paper_map_payload", _JSON_DOCUMENT, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["document_id"], ["documents.document_id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("document_id"),
        )

    _backfill(bind)
    if "document_sources" in _tables(bind):
        op.drop_table("document_sources")
    if "document_profiles" in _tables(bind):
        op.drop_table("document_profiles")


def downgrade() -> None:
    raise RuntimeError(
        "20260908_0054 is an irreversible merge of current document artifacts"
    )


def _backfill(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    tables = _tables(bind)
    if "document_preparations" not in tables:
        return
    preparation = sa.Table("document_preparations", metadata, autoload_with=bind)
    source = (
        sa.Table("document_sources", metadata, autoload_with=bind)
        if "document_sources" in tables
        else None
    )
    profile = (
        sa.Table("document_profiles", metadata, autoload_with=bind)
        if "document_profiles" in tables
        else None
    )

    records: dict[str, dict[str, Any]] = {}
    if source is not None:
        for row in bind.execute(sa.select(source)).mappings():
            records[str(row["document_id"])] = {
                "document_id": row["document_id"],
                "source_format": row.get("source_format"),
                "parser_name": row.get("parser_name"),
                "parser_version": row.get("parser_version"),
                "source_fingerprint": row.get("source_fingerprint"),
                "artifact_json": row.get("artifact_json"),
                "created_at": row.get("created_at") or _now(),
                "updated_at": row.get("updated_at") or row.get("created_at") or _now(),
            }
    if profile is not None:
        profile_columns = {column.name for column in profile.columns}
        for row in bind.execute(sa.select(profile)).mappings():
            document_id = str(row["document_id"])
            record = records.setdefault(
                document_id,
                {
                    "document_id": row["document_id"],
                    "created_at": _now(),
                    "updated_at": _now(),
                },
            )
            record["profile_json"] = {
                "document_id": row["document_id"],
                "title": row.get("title"),
                "doc_type": row.get("doc_type"),
                "profile_warnings": row.get("profile_warnings") or [],
                "confidence": row.get("confidence") or 0.0,
                "source_fingerprint": row.get("source_fingerprint"),
                "profile_version": row.get("profile_version"),
                "profile_fingerprint": row.get("profile_fingerprint"),
                "generated_at": _iso(row.get("generated_at")),
            }
            if "paper_map_payload" in profile_columns:
                record["paper_map_payload"] = row.get("paper_map_payload")
            if row.get("generated_at") is not None:
                record["updated_at"] = row["generated_at"]

    existing_ids = {
        str(value)
        for value in bind.execute(sa.select(preparation.c.document_id)).scalars()
    }
    for document_id, record in records.items():
        if document_id in existing_ids:
            bind.execute(
                preparation.update()
                .where(preparation.c.document_id == document_id)
                .values(**{key: value for key, value in record.items() if key != "document_id"})
            )
        else:
            bind.execute(preparation.insert().values(**record))


def _tables(bind: sa.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)
