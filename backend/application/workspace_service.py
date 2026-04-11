from __future__ import annotations

from application.artifact_registry_service import ArtifactRegistryService
from application.collection_service import CollectionService
from application.task_service import TaskService


class WorkspaceService:
    """Compose collection, task and artifact state into a single workspace view."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        task_service: TaskService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.task_service = task_service or TaskService()
        self.artifact_registry_service = artifact_registry_service or ArtifactRegistryService()

    def _build_default_artifacts(self, collection_id: str) -> dict:
        paths = self.collection_service.get_paths(collection_id)
        return {
            "collection_id": collection_id,
            "output_path": str(paths.output_dir),
            "documents_ready": False,
            "graph_ready": False,
            "sections_ready": False,
            "procedure_blocks_ready": False,
            "protocol_steps_ready": False,
            "graphml_ready": False,
            "updated_at": self.collection_service.get_collection(collection_id)["updated_at"],
        }

    def _build_capabilities(self, artifacts: dict) -> dict:
        graph_ready = bool(artifacts.get("graph_ready"))
        protocol_ready = bool(artifacts.get("protocol_steps_ready"))
        return {
            "can_view_graph": graph_ready,
            "can_download_graphml": graph_ready,
            "can_view_protocol_steps": protocol_ready,
            "can_search_protocol": protocol_ready,
            "can_generate_sop": protocol_ready,
        }

    def _build_status_summary(self, file_count: int, latest_task: dict | None, artifacts: dict) -> str:
        if latest_task:
            status = str(latest_task.get("status") or "")
            if status == "running":
                return "processing"
            if status == "failed":
                return "attention_required"
            if status == "partial_success":
                return "partial_ready"
        if artifacts.get("protocol_steps_ready"):
            return "ready"
        if artifacts.get("graph_ready"):
            return "graph_ready"
        if file_count > 0:
            return "uploaded"
        return "empty"

    def get_workspace_overview(self, collection_id: str, recent_task_limit: int = 5) -> dict:
        collection = self.collection_service.get_collection(collection_id)
        files = self.collection_service.list_files(collection_id)
        recent_tasks = self.task_service.list_tasks(collection_id=collection_id, limit=recent_task_limit)
        latest_task = recent_tasks[0] if recent_tasks else None
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            artifacts = self._build_default_artifacts(collection_id)
        return {
            "collection": collection,
            "file_count": len(files),
            "status_summary": self._build_status_summary(len(files), latest_task, artifacts),
            "artifacts": {
                "output_path": artifacts["output_path"],
                "documents_ready": bool(artifacts.get("documents_ready")),
                "graph_ready": bool(artifacts.get("graph_ready")),
                "sections_ready": bool(artifacts.get("sections_ready")),
                "procedure_blocks_ready": bool(artifacts.get("procedure_blocks_ready")),
                "protocol_steps_ready": bool(artifacts.get("protocol_steps_ready")),
                "graphml_ready": bool(artifacts.get("graphml_ready")),
                "updated_at": artifacts["updated_at"],
            },
            "latest_task": latest_task,
            "recent_tasks": recent_tasks,
            "capabilities": self._build_capabilities(artifacts),
        }
