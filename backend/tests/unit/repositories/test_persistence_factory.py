from __future__ import annotations

from application.source.collection_service import CollectionService
from infra.persistence.factory import (
    build_goal_session_repository,
    build_persistence_bundle,
    build_source_artifact_repository,
)


def test_build_persistence_bundle_supports_memory_backend(tmp_path):
    bundle = build_persistence_bundle(
        collections_root=tmp_path / "collections",
        tasks_root=tmp_path / "tasks",
        backend="memory",
    )

    assert bundle.collection_repository.backend_name == "memory"
    assert bundle.task_repository.backend_name == "memory"
    assert bundle.artifact_repository.backend_name == "memory"


def test_collection_service_uses_memory_backend_when_requested(tmp_path):
    bundle = build_persistence_bundle(
        collections_root=tmp_path / "collections",
        tasks_root=tmp_path / "tasks",
        backend="memory",
    )
    service = CollectionService(
        repository=bundle.collection_repository,
        artifact_repository=bundle.artifact_repository,
    )

    record = service.create_collection("In Memory")

    assert service.repository.backend_name == "memory"
    assert service.artifact_repository.backend_name == "memory"
    assert service.get_collection(record["collection_id"])["name"] == "In Memory"


def test_build_goal_session_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_goal_session_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()


def test_build_source_artifact_repository_uses_sqlite_inside_infra(tmp_path):
    repository = build_source_artifact_repository(tmp_path / "lens.sqlite")

    assert repository.backend_name == "sqlite"
    assert repository.db_path == (tmp_path / "lens.sqlite").resolve()
