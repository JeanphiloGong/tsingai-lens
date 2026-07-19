"""Persistence adapter factory helpers."""

from __future__ import annotations

from pathlib import Path

from config import DATA_DIR
from domain.ports import (
    ConfirmedGoalRepository,
    EvaluationRepository,
    ExperimentPlanRepository,
    GoalSessionRepository,
    ResearchUnderstandingRepository,
)
from infra.persistence.sqlite import (
    SqliteConfirmedGoalRepository,
    SqliteEvaluationRepository,
    SqliteExperimentPlanRepository,
    SqliteGoalSessionRepository,
    SqliteResearchUnderstandingRepository,
)


def build_goal_session_repository(
    db_path: Path | None = None,
) -> GoalSessionRepository:
    return SqliteGoalSessionRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_experiment_plan_repository(
    db_path: Path | None = None,
) -> ExperimentPlanRepository:
    return SqliteExperimentPlanRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_confirmed_goal_repository(
    db_path: Path | None = None,
) -> ConfirmedGoalRepository:
    return SqliteConfirmedGoalRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_research_understanding_repository(
    db_path: Path | None = None,
) -> ResearchUnderstandingRepository:
    return SqliteResearchUnderstandingRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_evaluation_repository(
    db_path: Path | None = None,
) -> EvaluationRepository:
    return SqliteEvaluationRepository(db_path or (DATA_DIR / "lens.sqlite"))
