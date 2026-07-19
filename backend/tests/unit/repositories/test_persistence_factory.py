from __future__ import annotations

from infra.persistence.factory import (
    build_confirmed_goal_repository,
    build_evaluation_repository,
    build_goal_session_repository,
    build_research_understanding_repository,
)


def test_build_goal_session_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_goal_session_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()


def test_build_confirmed_goal_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_confirmed_goal_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()


def test_build_research_understanding_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_research_understanding_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()


def test_build_evaluation_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_evaluation_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()
