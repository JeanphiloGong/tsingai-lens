"""Persistence adapter factory helpers."""

from __future__ import annotations

import os
from pathlib import Path

from config import DATA_DIR
from domain.ports import (
    ArtifactRepository,
    CoreFactRepository,
    EvaluationRepository,
    ExperimentPlanRepository,
    GoalSessionRepository,
    SourceArtifactRepository,
    TaskRepository,
)
from infra.persistence.file import (
    FileArtifactRepository,
    FileTaskRepository,
)
from infra.persistence.memory import (
    MemoryArtifactRepository,
    MemoryTaskRepository,
)
from infra.persistence.sqlite import (
    SqliteCoreFactRepository,
    SqliteEvaluationRepository,
    SqliteExperimentPlanRepository,
    SqliteGoalSessionRepository,
    SqliteSourceArtifactRepository,
)

DEFAULT_PERSISTENCE_BACKEND = "file"


def resolve_persistence_backend(backend: str | None = None) -> str:
    resolved = (
        backend or os.getenv("LENS_PERSISTENCE_BACKEND") or DEFAULT_PERSISTENCE_BACKEND
    )
    normalized = resolved.strip().lower()
    if normalized not in {"file", "memory", "mysql"}:
        raise ValueError(f"unsupported persistence backend: {resolved}")
    return normalized


def build_task_repository(
    root_dir: Path | None = None,
    backend: str | None = None,
) -> TaskRepository:
    resolved = resolve_persistence_backend(backend)
    if resolved == "file":
        return FileTaskRepository(root_dir)
    if resolved == "memory":
        return MemoryTaskRepository(root_dir)
    raise NotImplementedError("mysql persistence adapters are not implemented yet")


def build_artifact_repository(
    root_dir: Path | None = None,
    backend: str | None = None,
) -> ArtifactRepository:
    resolved = resolve_persistence_backend(backend)
    if resolved == "file":
        return FileArtifactRepository(root_dir)
    if resolved == "memory":
        return MemoryArtifactRepository(root_dir)
    raise NotImplementedError("mysql persistence adapters are not implemented yet")


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
