"""Persistence adapter factory helpers."""

from __future__ import annotations

from pathlib import Path

from config import DATA_DIR
from domain.ports import EvaluationRepository
from infra.persistence.sqlite import (
    SqliteEvaluationRepository,
)


def build_evaluation_repository(
    db_path: Path | None = None,
) -> EvaluationRepository:
    return SqliteEvaluationRepository(db_path or (DATA_DIR / "lens.sqlite"))
