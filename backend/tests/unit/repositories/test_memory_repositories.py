from __future__ import annotations

from infra.persistence.memory import (
    MemoryArtifactRepository,
    MemoryCollectionRepository,
    MemoryTaskRepository,
)
from domain.source import CollectionRecord


def test_memory_collection_repository_round_trips_records_by_owner():
    repository = MemoryCollectionRepository()
    record = CollectionRecord(
        collection_id="col_demo",
        owner_user_id="user_demo",
        name="Demo",
        description=None,
        status="idle",
        paper_count=0,
        created_at="2026-07-19T00:00:00+00:00",
        updated_at="2026-07-19T00:00:00+00:00",
    )

    repository.add_collection(record)

    assert repository.read_collection(record.collection_id) == record
    assert repository.list_collections("user_demo") == (record,)
    assert repository.list_collections("user_other") == ()


def test_memory_task_repository_round_trips_task_records(tmp_path):
    repository = MemoryTaskRepository(tmp_path / "tasks")
    repository.write_task("task_demo", {"task_id": "task_demo", "status": "queued"})

    assert repository.read_task("task_demo")["status"] == "queued"
    assert repository.list_tasks() == [{"task_id": "task_demo", "status": "queued"}]


def test_memory_artifact_repository_round_trips_artifacts(tmp_path):
    repository = MemoryArtifactRepository(tmp_path / "collections")
    repository.write("col_demo", {"collection_id": "col_demo", "graph_ready": True})

    assert repository.read("col_demo") == {
        "collection_id": "col_demo",
        "graph_ready": True,
    }
