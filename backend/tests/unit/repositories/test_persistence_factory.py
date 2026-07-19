from __future__ import annotations

from infra.persistence.factory import (
    build_artifact_repository,
    build_core_fact_repository,
    build_evaluation_repository,
    build_goal_session_repository,
    build_source_artifact_repository,
    build_task_repository,
)


def test_task_and_artifact_factories_support_memory_backend(tmp_path):
    task_repository = build_task_repository(
        root_dir=tmp_path / "tasks",
        backend="memory",
    )
    artifact_repository = build_artifact_repository(
        root_dir=tmp_path / "collections",
        backend="memory",
    )

    assert task_repository.backend_name == "memory"
    assert artifact_repository.backend_name == "memory"


def test_build_goal_session_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_goal_session_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()


def test_build_source_artifact_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_source_artifact_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()


def test_build_core_fact_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_core_fact_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()


def test_build_evaluation_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_evaluation_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()
