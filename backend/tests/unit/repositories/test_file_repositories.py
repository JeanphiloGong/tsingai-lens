from __future__ import annotations

from infra.persistence.file import (
    FileArtifactRepository,
    FileCollectionRepository,
    FileTaskRepository,
)


def test_file_collection_repository_round_trips_records_and_files(tmp_path):
    repository = FileCollectionRepository(tmp_path / "collections")
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


def test_file_task_repository_round_trips_task_records(tmp_path):
    repository = FileTaskRepository(tmp_path / "tasks")
    repository.write_task("task_demo", {"task_id": "task_demo", "status": "queued"})

    assert repository.read_task("task_demo")["status"] == "queued"
    assert repository.list_tasks() == [{"task_id": "task_demo", "status": "queued"}]


def test_file_artifact_repository_round_trips_artifacts(tmp_path):
    repository = FileArtifactRepository(tmp_path / "collections")
    repository.write("col_demo", {"collection_id": "col_demo", "graph_ready": True})

    assert repository.read("col_demo") == {
        "collection_id": "col_demo",
        "graph_ready": True,
    }
