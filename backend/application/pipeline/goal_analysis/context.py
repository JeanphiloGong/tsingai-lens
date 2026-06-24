from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GoalAnalysisContext:
    collection_id: str
    goal_id: str
    services: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)
