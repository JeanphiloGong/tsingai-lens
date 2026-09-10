"""Store one-to-one Chat tool results on the tool-call ledger."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0048"
down_revision: str | Sequence[str] | None = "20260908_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    call_columns = _columns("chat_tool_calls")
    additions = (
        ("result_status", sa.Column("result_status", sa.String(32), nullable=True)),
        ("result_data", sa.Column("result_data", sa.JSON(), nullable=True)),
        ("result_resource_refs", sa.Column("result_resource_refs", sa.JSON(), nullable=True)),
        ("result_warnings", sa.Column("result_warnings", sa.JSON(), nullable=True)),
        ("result_error_code", sa.Column("result_error_code", sa.String(128), nullable=True)),
        ("result_error_message", sa.Column("result_error_message", sa.Text(), nullable=True)),
    )
    for name, column in additions:
        if name not in call_columns:
            op.add_column("chat_tool_calls", column)

    if "chat_tool_results" not in _tables():
        return

    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("chat_tool_calls", "chat_tool_results"))
    calls = metadata.tables["chat_tool_calls"]
    results = metadata.tables["chat_tool_results"]
    for row in bind.execute(sa.select(results)).mappings():
        bind.execute(
            calls.update()
            .where(calls.c.tool_call_id == row["tool_call_id"])
            .values(
                result_status=row["status"],
                result_data=row["data"],
                result_resource_refs=row["resource_refs"],
                result_warnings=row["warnings"],
                result_error_code=row["error_code"],
                result_error_message=row["error_message"],
            )
        )
    op.drop_table("chat_tool_results")


def downgrade() -> None:
    bind = op.get_bind()
    if "chat_tool_results" not in _tables():
        op.create_table(
            "chat_tool_results",
            sa.Column("tool_call_id", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("resource_refs", sa.JSON(), nullable=False),
            sa.Column("warnings", sa.JSON(), nullable=False),
            sa.Column("error_code", sa.String(128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["tool_call_id"], ["chat_tool_calls.tool_call_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("tool_call_id"),
        )
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("chat_tool_calls", "chat_tool_results"))
    calls = metadata.tables["chat_tool_calls"]
    results = metadata.tables["chat_tool_results"]
    for row in bind.execute(sa.select(calls).where(calls.c.result_status.is_not(None))).mappings():
        bind.execute(
            results.insert().values(
                tool_call_id=row["tool_call_id"],
                status=row["result_status"],
                data=row["result_data"] or {},
                resource_refs=row["result_resource_refs"] or [],
                warnings=row["result_warnings"] or [],
                error_code=row["result_error_code"],
                error_message=row["result_error_message"],
            )
        )
    with op.batch_alter_table("chat_tool_calls") as batch:
        for name, _ in (
            ("result_error_message", None),
            ("result_error_code", None),
            ("result_warnings", None),
            ("result_resource_refs", None),
            ("result_data", None),
            ("result_status", None),
        ):
            if name in _columns("chat_tool_calls"):
                batch.drop_column(name)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
