from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from controllers.schemas.core.confirmed_goals import ConfirmedGoalResponse
from controllers.schemas.core.research_understanding import ResearchUnderstandingResponse


class GoalAnalysisResponse(BaseModel):
    """Confirmed-goal analysis state and output."""

    collection_id: str
    goal: ConfirmedGoalResponse
    understanding: ResearchUnderstandingResponse | None = None
    pipeline_nodes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
