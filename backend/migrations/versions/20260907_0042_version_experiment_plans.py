"""Store immutable structured experiment-plan revisions.

Revision ID: 20260907_0042
Revises: 20260901_0041
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260907_0042"
down_revision: str | Sequence[str] | None = "20260901_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    existing_columns = _plan_columns()
    if "plan_version" not in existing_columns:
        op.add_column(
            "objective_experiment_plans",
            sa.Column(
                "plan_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
    if "parent_plan_id" not in existing_columns:
        op.add_column(
            "objective_experiment_plans",
            sa.Column("parent_plan_id", sa.String(length=128), nullable=True),
        )
    if "structured_plan" not in existing_columns:
        op.add_column(
            "objective_experiment_plans",
            sa.Column("structured_plan", _JSON_DOCUMENT, nullable=True),
        )
    if "updated_by" not in existing_columns:
        op.add_column(
            "objective_experiment_plans",
            sa.Column("updated_by", sa.String(length=64), nullable=True),
        )

    foreign_keys = _plan_foreign_keys()
    unique_constraints = _plan_unique_constraints()
    parent_foreign_key = "fk_objective_experiment_plans_parent_plan_id"
    updater_foreign_key = "fk_objective_experiment_plans_updated_by_auth_users"
    parent_unique = "uq_objective_experiment_plans_parent_plan_id"
    if (
        parent_foreign_key not in foreign_keys
        or updater_foreign_key not in foreign_keys
        or parent_unique not in unique_constraints
    ):
        with op.batch_alter_table("objective_experiment_plans") as batch_op:
            if parent_foreign_key not in foreign_keys:
                batch_op.create_foreign_key(
                    parent_foreign_key,
                    "objective_experiment_plans",
                    ["parent_plan_id"],
                    ["plan_id"],
                    ondelete="RESTRICT",
                )
            if updater_foreign_key not in foreign_keys:
                batch_op.create_foreign_key(
                    updater_foreign_key,
                    "auth_users",
                    ["updated_by"],
                    ["user_id"],
                    ondelete="SET NULL",
                )
            if parent_unique not in unique_constraints:
                batch_op.create_unique_constraint(
                    parent_unique,
                    ["parent_plan_id"],
                )


def downgrade() -> None:
    with op.batch_alter_table("objective_experiment_plans") as batch_op:
        batch_op.drop_constraint(
            "uq_objective_experiment_plans_parent_plan_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_objective_experiment_plans_updated_by_auth_users",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_objective_experiment_plans_parent_plan_id",
            type_="foreignkey",
        )
    op.drop_column("objective_experiment_plans", "updated_by")
    op.drop_column("objective_experiment_plans", "structured_plan")
    op.drop_column("objective_experiment_plans", "parent_plan_id")
    op.drop_column("objective_experiment_plans", "plan_version")


def _plan_columns() -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(
            "objective_experiment_plans"
        )
    }


def _plan_foreign_keys() -> set[str]:
    return {
        str(constraint["name"])
        for constraint in sa.inspect(op.get_bind()).get_foreign_keys(
            "objective_experiment_plans"
        )
        if constraint.get("name")
    }


def _plan_unique_constraints() -> set[str]:
    return {
        str(constraint["name"])
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(
            "objective_experiment_plans"
        )
        if constraint.get("name")
    }
