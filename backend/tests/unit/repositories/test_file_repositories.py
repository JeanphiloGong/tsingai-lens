from __future__ import annotations

from infra.persistence.file import (
    FileArtifactRepository,
    FileCollectionWorkspace,
    FileTaskRepository,
)


def test_file_collection_workspace_round_trips_files_without_meta_json(tmp_path):
    workspace = FileCollectionWorkspace(tmp_path / "collections")
    collection_id = "col_demo"

    paths = workspace.create_collection_dirs(collection_id)
    workspace.write_files(collection_id, [{"stored_filename": "paper.txt"}])

    assert workspace.read_files(collection_id) == [{"stored_filename": "paper.txt"}]
    assert not (paths.collection_dir / "meta.json").exists()


def test_file_collection_workspace_round_trips_import_manifest(tmp_path):
    workspace = FileCollectionWorkspace(tmp_path / "collections")
    collection_id = "col_demo"

    workspace.create_collection_dirs(collection_id)
    workspace.write_import_manifest(
        collection_id,
        {
            "schema_version": 1,
            "collection_id": collection_id,
            "imports": [{"import_id": "imp_demo"}],
        },
    )

    assert workspace.read_import_manifest(collection_id) == {
        "schema_version": 1,
        "collection_id": collection_id,
        "imports": [{"import_id": "imp_demo"}],
    }


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
