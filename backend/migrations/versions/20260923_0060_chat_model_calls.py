"""Persist exact provider requests for Research Agent Chat calls."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260923_0060"
down_revision = "20260917_0059"
branch_labels = None
depends_on = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # The historical bootstrap migration creates current ORM tables on an
    # empty database. Keep this revision safe for that path while adding the
    # table to databases upgraded from an older persisted schema.
    if "chat_model_calls" in inspector.get_table_names():
        return
    op.create_table(
        "chat_model_calls",
        sa.Column("call_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("trigger_message_id", sa.String(length=128), nullable=True),
        sa.Column("response_message_id", sa.String(length=128), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("request", _JSON_DOCUMENT, nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("provider_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("call_id"),
        sa.CheckConstraint(
            "purpose IN ('decision', 'compaction', 'finalization')",
            name="model_call_purpose_valid",
        ),
        sa.CheckConstraint(
            "status IN ('recorded', 'provider_succeeded', 'provider_failed', 'response_invalid', 'cancelled')",
            name="model_call_status_valid",
        ),
        sa.CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="model_call_times_valid"),
        sa.CheckConstraint("length(request_digest) = 64", name="model_call_digest_length"),
    )
    op.create_index("ix_chat_model_calls_session_id", "chat_model_calls", ["session_id"])
    op.create_index("ix_chat_model_calls_trigger_message_id", "chat_model_calls", ["trigger_message_id"])
    op.create_index("ix_chat_model_calls_response_message_id", "chat_model_calls", ["response_message_id"])


def downgrade():
    if "chat_model_calls" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("ix_chat_model_calls_response_message_id", table_name="chat_model_calls")
    op.drop_index("ix_chat_model_calls_trigger_message_id", table_name="chat_model_calls")
    op.drop_index("ix_chat_model_calls_session_id", table_name="chat_model_calls")
    op.drop_table("chat_model_calls")
