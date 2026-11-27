from __future__ import annotations

from application.core.objectives.objective_analysis_service import ResearchObjectiveNotFoundError
from application.source import workspace_service
from repositories.objective_repository import ObjectiveRepo


async def read_objective_detail(
    workspace_id: str,
    objective_id: str,
    *,
    user_id: str,
):
    """Read one complete Objective projection after Workspace authorization."""

    await workspace_service.get_workspace_for_user(workspace_id, user_id)
    record = await ObjectiveRepo.read_objective_record(workspace_id, objective_id)
    if record is None:
        raise ResearchObjectiveNotFoundError(workspace_id, objective_id)
    return record
