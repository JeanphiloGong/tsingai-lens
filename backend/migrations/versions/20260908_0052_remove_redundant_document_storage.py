"""Remove redundant Source and collection count storage."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260908_0052"
down_revision: str | Sequence[str] | None = "20260908_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    if "document_sources" in _tables():
        _compact_document_sources(bind)
    if "collections" in _tables() and "paper_count" in _columns("collections"):
        _remove_collection_count(bind)


def downgrade() -> None:
    raise RuntimeError(
        "20260908_0052 is an irreversible removal of redundant Source and count fields"
    )


def _compact_document_sources(bind: sa.Connection) -> None:
    old = sa.Table("document_sources", sa.MetaData(), autoload_with=bind)
    temporary_name = "document_sources_compact"
    if temporary_name in _tables():
        op.drop_table(temporary_name)
    op.create_table(
        temporary_name,
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("source_format", sa.String(length=32), nullable=False),
        sa.Column("parser_name", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=128), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("artifact_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.document_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )
    compact = sa.Table(temporary_name, sa.MetaData(), autoload_with=bind)
    rows = bind.execute(sa.select(old)).mappings()
    for row in rows:
        bind.execute(
            compact.insert().values(
                document_id=row["document_id"],
                source_format=row["source_format"],
                parser_name=row["parser_name"],
                parser_version=row["parser_version"],
                source_fingerprint=row["source_fingerprint"],
                artifact_json=row["artifact_json"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
    op.drop_table("document_sources")
    op.rename_table(temporary_name, "document_sources")


def _remove_collection_count(bind: sa.Connection) -> None:
    check_constraints = sa.inspect(bind).get_check_constraints("collections")
    count_constraints = [
        constraint["name"]
        for constraint in check_constraints
        if constraint.get("name") and "paper_count" in str(constraint.get("sqltext"))
    ]
    with op.batch_alter_table("collections") as batch:
        for constraint_name in count_constraints:
            batch.drop_constraint(op.f(constraint_name), type_="check")
        batch.drop_column("paper_count")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
