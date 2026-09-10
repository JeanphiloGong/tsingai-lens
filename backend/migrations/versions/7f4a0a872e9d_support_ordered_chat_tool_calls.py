"""support ordered chat tool calls

Revision ID: 7f4a0a872e9d
Revises: 20260908_0046
Create Date: 2026-09-08 18:03:14.765472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f4a0a872e9d'
down_revision: Union[str, Sequence[str], None] = '20260908_0046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    call_columns = {column["name"] for column in inspector.get_columns("chat_tool_calls")}
    message_columns = {column["name"] for column in inspector.get_columns("chat_messages")}
    # The historical 0038 cutover creates current metadata on a fresh database.
    # Accept only the complete target schema, never a partially migrated history.
    if "position" in call_columns:
        unique = {item["name"] for item in inspector.get_unique_constraints("chat_tool_calls")}
        checks = {item["name"] for item in inspector.get_check_constraints("chat_tool_calls")}
        if (not {"tool_name", "tool_arguments"} & message_columns
                and "uq_chat_tool_calls_assistant_position" in unique
                and "ck_chat_tool_calls_position_non_negative" in checks):
            return
        raise RuntimeError("Chat schema is partially migrated; reconcile before upgrading.")
    metadata = sa.MetaData()
    messages = sa.Table("chat_messages", metadata, autoload_with=bind)
    calls = sa.Table("chat_tool_calls", metadata, autoload_with=bind)
    by_message = {row["assistant_message_id"]: row for row in bind.execute(sa.select(calls)).mappings()}
    for message in bind.execute(sa.select(messages).where(messages.c.role == "assistant")).mappings():
        call = by_message.pop(message["message_id"], None)
        if call is None and not message["tool_call_id"] and message["tool_name"] is None and message["tool_arguments"] is None:
            continue
        if (call is None or call["tool_call_id"] != message["tool_call_id"]
                or call["session_id"] != message["session_id"]
                or call["name"] != message["tool_name"]
                or call["arguments"] != message["tool_arguments"]):
            raise RuntimeError("Chat request history does not match durable calls; reconcile before upgrading.")
    if by_message:
        raise RuntimeError("Chat calls have no matching assistant request; reconcile before upgrading.")

    op.add_column("chat_tool_calls", sa.Column("position", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE chat_tool_calls SET position = 0"))
    with op.batch_alter_table("chat_tool_calls") as batch:
        batch.alter_column("position", nullable=False, existing_type=sa.Integer())
        batch.drop_constraint("uq_chat_tool_calls_assistant_message", type_="unique")
        batch.create_unique_constraint("uq_chat_tool_calls_assistant_position", ["assistant_message_id", "position"])
        batch.create_check_constraint(op.f("ck_chat_tool_calls_position_non_negative"), "position >= 0")
    op.execute(messages.update().where(messages.c.role == "assistant").values(tool_call_id=None))
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("tool_name")
        batch.drop_column("tool_arguments")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    multiple = bind.execute(sa.text(
        "SELECT assistant_message_id FROM chat_tool_calls GROUP BY assistant_message_id HAVING COUNT(*) > 1"
    )).first()
    if multiple:
        raise RuntimeError("Cannot downgrade ordered Chat calls: multiple calls would be lost.")
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("tool_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("tool_arguments", sa.JSON(), nullable=True))
    metadata = sa.MetaData()
    messages = sa.Table("chat_messages", metadata, autoload_with=bind)
    calls = sa.Table("chat_tool_calls", metadata, autoload_with=bind)
    for call in bind.execute(sa.select(calls)).mappings():
        bind.execute(messages.update().where(messages.c.message_id == call["assistant_message_id"]).values(
            tool_call_id=call["tool_call_id"], tool_name=call["name"], tool_arguments=call["arguments"]
        ))
    with op.batch_alter_table("chat_tool_calls") as batch:
        batch.drop_constraint("uq_chat_tool_calls_assistant_position", type_="unique")
        batch.drop_constraint(op.f("ck_chat_tool_calls_position_non_negative"), type_="check")
        batch.create_unique_constraint("uq_chat_tool_calls_assistant_message", ["assistant_message_id"])
        batch.drop_column("position")
