from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final

from application.pipeline.goal_analysis.context import GoalAnalysisContext


NodeFunction = Callable[[GoalAnalysisContext], object]


@dataclass(frozen=True)
class GoalAnalysisNodeDefinition:
    node_id: str
    depends_on: tuple[str, ...]


PREPARE_GOAL: Final = "prepare_goal"
ANALYZE_GOAL: Final = "analyze_goal"
FINALIZE_GOAL: Final = "finalize_goal"


GOAL_ANALYSIS_NODE_DEFINITIONS: Final[tuple[GoalAnalysisNodeDefinition, ...]] = (
    GoalAnalysisNodeDefinition(PREPARE_GOAL, ()),
    GoalAnalysisNodeDefinition(ANALYZE_GOAL, (PREPARE_GOAL,)),
    GoalAnalysisNodeDefinition(FINALIZE_GOAL, (ANALYZE_GOAL,)),
)
