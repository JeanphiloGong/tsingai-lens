from __future__ import annotations

from infra.persistence.memory import (
    MemoryArtifactRepository,
    MemoryCollectionRepository,
    MemoryTaskRepository,
)


def test_memory_collection_repository_round_trips_records_and_files(tmp_path):
    repository = MemoryCollectionRepository(tmp_path / "collections")
    collection_id = "col_demo"

    repository.create_collection_dirs(collection_id)
    repository.write_collection(
        collection_id,
        {
            "collection_id": collection_id,
            "name": "Demo",
            "status": "idle",
        },
    )
    repository.write_files(collection_id, [{"stored_filename": "paper.txt"}])

    assert repository.collection_exists(collection_id) is True
    assert repository.read_collection(collection_id)["name"] == "Demo"
    assert repository.read_files(collection_id) == [{"stored_filename": "paper.txt"}]


def test_memory_collection_repository_round_trips_import_manifest(tmp_path):
    repository = MemoryCollectionRepository(tmp_path / "collections")
    collection_id = "col_demo"

    repository.create_collection_dirs(collection_id)
    repository.write_import_manifest(
        collection_id,
        {
            "schema_version": 1,
            "collection_id": collection_id,
            "imports": [{"import_id": "imp_demo"}],
        },
    )

    assert repository.read_import_manifest(collection_id) == {
        "schema_version": 1,
        "collection_id": collection_id,
        "imports": [{"import_id": "imp_demo"}],
    }


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
