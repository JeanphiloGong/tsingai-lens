from __future__ import annotations

from infra.persistence.factory import build_persistence_bundle
from application.collections.service import CollectionService


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
