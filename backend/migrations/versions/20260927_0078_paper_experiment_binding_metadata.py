"""Persist PaperExperiment sample and test binding metadata.

The domain model can retain a broad or unresolved sample/test relationship
without promoting it to an exact binding.  These columns keep that distinction
when a revision is stored and allow old PaperExperiment rows to upgrade with
explicit ``unknown``/empty values.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260927_0078"
down_revision = "20260925_0077"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _table_columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name in _table_columns(table_name):
        return
    if table_name not in inspect(op.get_bind()).get_table_names():
        return
    op.add_column(table_name, column)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    if column_name not in _table_columns(table_name):
        return
    op.drop_column(table_name, column_name)


def upgrade() -> None:
    # Non-null columns use server defaults so existing revisions remain valid
    # while the application starts recording the richer metadata.
    for column in (
        sa.Column(
            "identity_specificity",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "missing_dimensions_json",
            _JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "identity_evidence_json",
            _JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    ):
        _add_column_if_missing("experimental_variant", column)

    for column in (
        sa.Column(
            "protocol_specificity",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "test_identity_status",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "protocol_completeness",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "missing_parameters_json",
            _JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("standard", sa.String(length=200), nullable=True),
        sa.Column(
            "outcome_scope_json",
            _JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "binding_source_refs_json",
            _JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "protocol_evidence_json",
            _JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    ):
        _add_column_if_missing("test_condition", column)


def downgrade() -> None:
    for column_name in (
        "protocol_evidence_json",
        "binding_source_refs_json",
        "outcome_scope_json",
        "standard",
        "method",
        "missing_parameters_json",
        "protocol_completeness",
        "test_identity_status",
        "protocol_specificity",
    ):
        _drop_column_if_present("test_condition", column_name)
    for column_name in (
        "identity_evidence_json",
        "missing_dimensions_json",
        "identity_specificity",
    ):
        _drop_column_if_present("experimental_variant", column_name)
