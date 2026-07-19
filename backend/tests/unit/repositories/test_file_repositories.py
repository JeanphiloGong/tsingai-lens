from __future__ import annotations

from infra.persistence.file import (
    FileArtifactRepository,
    FileTaskRepository,
)


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
