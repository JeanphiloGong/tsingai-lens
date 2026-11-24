"""Record the Agent Registry decision basis on durable Operations."""

from alembic import op


revision = "b71000000006"
down_revision = "b71000000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_operations
            ADD COLUMN decision_basis varchar(32) NOT NULL DEFAULT 'registry';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_operations
            DROP COLUMN decision_basis;
        """
    )
