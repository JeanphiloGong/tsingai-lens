"""Remove request identity fields from durable Agent Tasks."""

from alembic import op


revision = "b71000000003"
down_revision = "b71000000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_tasks
            DROP CONSTRAINT IF EXISTS agent_tasks_request_unique,
            DROP CONSTRAINT IF EXISTS chat_task_digest_length,
            DROP COLUMN IF EXISTS request_id,
            DROP COLUMN IF EXISTS request_digest;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_tasks
            ADD COLUMN request_id uuid,
            ADD COLUMN request_digest varchar(64),
            ADD CONSTRAINT agent_tasks_request_unique
                UNIQUE (session_id, request_id),
            ADD CONSTRAINT chat_task_digest_length
                CHECK (request_digest IS NULL OR length(request_digest) = 64);
        """
    )
