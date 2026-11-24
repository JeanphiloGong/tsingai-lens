"""Rename the persisted Collection boundary to Workspace."""

from collections.abc import Sequence

from alembic import op

revision: str = "b71000000005"
down_revision: str | None = "b71000000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OWNING_TABLES = (
    "documents",
    "pipeline_runs",
    "research_objectives",
    "objective_analyses",
    "objective_analysis_legacy_checkpoints",
    "objective_experiment_selection",
    "comparison_group",
    "objective_experiment_plans",
    "finding",
    "finding_feedback_records",
    "finding_curation_records",
    "evaluation_gold_sets",
    "evaluation_prediction_snapshots",
    "evaluation_runs",
    "feedback_analysis_results",
    "feedback_signal_analysis_results",
    "tool_failure_analysis_results",
    "feedback_cases",
    "feedback_dataset_snapshots",
    "feedback_datasets",
)


def upgrade() -> None:
    op.rename_table("collections", "workspaces")
    op.alter_column("workspaces", "collection_id", new_column_name="workspace_id")
    for table_name in _OWNING_TABLES:
        op.alter_column(table_name, "collection_id", new_column_name="workspace_id")


def downgrade() -> None:
    for table_name in reversed(_OWNING_TABLES):
        op.alter_column(table_name, "workspace_id", new_column_name="collection_id")
    op.alter_column("workspaces", "workspace_id", new_column_name="collection_id")
    op.rename_table("workspaces", "collections")
