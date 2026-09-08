"""Replace build-scoped persistence with the current Document model.

Revision ID: 20260827_0038
Revises: 20260827_0037
Create Date: 2026-08-27 16:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, Float, ForeignKey, JSON, MetaData, String, Table, Text, inspect

from infra.persistence.postgres.base import Base
import infra.persistence.postgres.models  # noqa: F401


revision = "20260827_0038"
down_revision = "20260827_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    table_names = [
        name
        for name in inspect(bind).get_table_names()
        if name != "alembic_version"
    ]
    if table_names:
        previous = MetaData()
        previous.reflect(bind=bind, only=table_names)
        previous.drop_all(bind=bind)
    # This revision historically created the pre-0054 profile table through
    # the then-current ORM. Keep that legacy shape explicit so later
    # migrations can backfill it even though the maintained ORM now owns the
    # merged document_preparations table.
    Base.metadata.create_all(bind=bind)
    if "document_preparations" in inspect(bind).get_table_names():
        op.drop_table("document_preparations")
    legacy = MetaData()
    legacy.reflect(bind=bind, only=("documents", "collections"))
    profiles = Table(
        "document_profiles",
        legacy,
        Column(
            "document_id",
            String(128),
            ForeignKey("documents.document_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("title", Text, nullable=True),
        Column("doc_type", String(32), nullable=False),
        Column("profile_warnings", JSON, nullable=False),
        Column("confidence", Float, nullable=False),
    )
    sources = Table(
        "document_sources",
        legacy,
        Column(
            "document_id",
            String(64),
            ForeignKey("documents.document_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("source_format", String(32), nullable=False),
        Column("parser_name", String(128), nullable=False),
        Column("parser_version", String(128), nullable=False),
        Column("source_fingerprint", String(64), nullable=False),
        Column("artifact_json", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    legacy.create_all(bind=bind, tables=[profiles, sources])


def downgrade() -> None:
    raise RuntimeError(
        "20260827_0038 is an irreversible destructive cutover to current Documents"
    )
