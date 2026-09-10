"""Move preparation provenance to the artifacts that produce it.

Revision ID: 20260908_0044
Revises: 20260908_0043
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0044"
down_revision: str | Sequence[str] | None = "20260908_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    profile_columns = _columns("document_profiles")
    for name, column in (
        ("source_fingerprint", sa.Column("source_fingerprint", sa.String(64))),
        ("profile_version", sa.Column("profile_version", sa.String(128))),
        ("profile_fingerprint", sa.Column("profile_fingerprint", sa.String(64))),
        (
            "generated_at",
            sa.Column("generated_at", sa.DateTime(timezone=True)),
        ),
    ):
        if name not in profile_columns:
            op.add_column("document_profiles", column)

    _backfill_profile_provenance(bind)

    document_columns = _columns("documents")
    removable = {
        "parser_version",
        "document_analysis_version",
        "source_fingerprint",
        "profile_fingerprint",
        "preparation_fingerprint",
    }
    if document_columns & removable:
        with op.batch_alter_table("documents") as batch_op:
            for name in sorted(document_columns & removable):
                batch_op.drop_column(name)


def downgrade() -> None:
    raise RuntimeError(
        "20260908_0044 is an irreversible destructive cutover to artifact-owned provenance"
    )


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _backfill_profile_provenance(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("documents", "document_profiles", "document_sources"))
    documents = metadata.tables["documents"]
    profiles = metadata.tables["document_profiles"]
    sources = metadata.tables.get("document_sources")
    now = datetime.now(timezone.utc)

    profile_rows = bind.execute(sa.select(profiles)).mappings().all()
    for profile in profile_rows:
        document = bind.execute(
            sa.select(documents).where(
                documents.c.document_id == profile["document_id"]
            )
        ).mappings().first()
        source = None
        if sources is not None:
            source = bind.execute(
                sa.select(sources).where(
                    sources.c.document_id == profile["document_id"]
                )
            ).mappings().first()
        values = {
            "source_fingerprint": (
                source["source_fingerprint"] if source is not None else None
            ),
            "profile_version": (
                document["document_analysis_version"]
                if document is not None and "document_analysis_version" in document
                else None
            ),
            "profile_fingerprint": (
                document["profile_fingerprint"]
                if document is not None and "profile_fingerprint" in document
                else None
            ),
            "generated_at": now,
        }
        bind.execute(
            profiles.update()
            .where(profiles.c.document_id == profile["document_id"])
            .values(**values)
        )
