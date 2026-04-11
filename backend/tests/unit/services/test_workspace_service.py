from __future__ import annotations

from application.artifact_registry_service import ArtifactRegistryService
from application.collection_service import CollectionService
from application.task_service import TaskService
from application.workspace_service import WorkspaceService


def test_workspace_service_builds_collection_overview(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    workspace_service = WorkspaceService(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Composite Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(collection_id, "paper.txt", b"Experimental Section\nMix and anneal.")

    task_service.create_task(collection_id, "index")
    task_service.update_task(
        task_service.list_tasks(collection_id=collection_id, limit=1)[0]["task_id"],
        status="running",
        current_stage="graphrag_index_started",
        progress_percent=35,
    )
    artifact_registry.upsert(collection_id, collection_service.get_paths(collection_id).output_dir)

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["collection"]["collection_id"] == collection_id
    assert overview["file_count"] == 1
    assert overview["status_summary"] == "processing"
    assert overview["latest_task"]["current_stage"] == "graphrag_index_started"
    assert overview["capabilities"]["can_view_graph"] is False
    assert overview["capabilities"]["can_generate_sop"] is False
