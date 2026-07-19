"""Persistence adapter factory helpers."""

from __future__ import annotations

from pathlib import Path

from config import DATA_DIR
from domain.ports import (
    CoreFactRepository,
    EvaluationRepository,
    ExperimentPlanRepository,
    GoalSessionRepository,
    SourceArtifactRepository,
)
from infra.persistence.sqlite import (
    SqliteCoreFactRepository,
    SqliteEvaluationRepository,
    SqliteExperimentPlanRepository,
    SqliteGoalSessionRepository,
    SqliteSourceArtifactRepository,
)


def build_goal_session_repository(
    db_path: Path | None = None,
) -> GoalSessionRepository:
    return SqliteGoalSessionRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_experiment_plan_repository(
    db_path: Path | None = None,
) -> ExperimentPlanRepository:
    return SqliteExperimentPlanRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_source_artifact_repository(
    db_path: Path | None = None,
) -> SourceArtifactRepository:
    return SqliteSourceArtifactRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_core_fact_repository(
    db_path: Path | None = None,
) -> CoreFactRepository:
    return SqliteCoreFactRepository(db_path or (DATA_DIR / "lens.sqlite"))


def build_evaluation_repository(
    db_path: Path | None = None,
) -> EvaluationRepository:
    return SqliteEvaluationRepository(db_path or (DATA_DIR / "lens.sqlite"))
