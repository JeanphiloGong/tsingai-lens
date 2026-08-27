from __future__ import annotations

from application.core.document_profiles.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from domain.ports import ObjectiveRepository, SourceArtifactRepository
from domain.shared.enums import DOC_TYPE_MIXED, DOC_TYPE_REVIEW, DOC_TYPE_UNCERTAIN


class WorkspaceService:
    """Present collection-build readiness without reconstructing scientific results."""

    def __init__(
        self,
        collection_service: CollectionService,
        task_service: TaskService,
        source_artifact_repository: SourceArtifactRepository,
        objective_repository: ObjectiveRepository,
        document_profile_service: DocumentProfileService,
    ) -> None:
        self.collection_service = collection_service
        self.task_service = task_service
        self.source_artifact_repository = source_artifact_repository
        self.objective_repository = objective_repository
        self.document_profile_service = document_profile_service

    async def _build_artifacts(
        self,
        collection_id: str,
        collection: dict,
        document_summary: dict,
    ) -> dict:
        source_documents = await self.source_artifact_repository.read_collection_documents(
            collection_id
        )
        objective_facts = await self.objective_repository.read(collection_id)
        return {
            "source_documents_ready": bool(source_documents),
            "document_profiles_ready": bool(
                int(document_summary.get("total_documents", 0) or 0)
            ),
            "objective_candidates_ready": objective_facts.research_objectives_ready,
            "updated_at": collection["updated_at"],
        }

    @staticmethod
    def _build_capabilities(artifacts: dict) -> dict:
        documents_ready = bool(artifacts.get("document_profiles_ready"))
        objectives_ready = bool(artifacts.get("objective_candidates_ready"))
        return {
            "can_view_documents": documents_ready,
            "can_view_objectives": objectives_ready,
            "can_view_comparisons": objectives_ready,
        }

    @staticmethod
    def _build_status_summary(
        file_count: int,
        latest_task: dict | None,
        artifacts: dict,
        _document_summary: dict,
    ) -> str:
        task_status = str((latest_task or {}).get("status") or "")
        if task_status in {"queued", "running"}:
            return "processing"
        if task_status == "failed":
            return "attention_required"
        if task_status == "partial_success" and not artifacts.get(
            "objective_candidates_ready"
        ):
            return "partial_ready"
        if artifacts.get("objective_candidates_ready"):
            return "ready"
        if artifacts.get("document_profiles_ready"):
            return "document_profiled"
        if file_count:
            return "uploaded"
        return "empty"

    @staticmethod
    def _build_workflow(
        file_count: int,
        latest_task: dict | None,
        artifacts: dict,
        document_summary: dict,
    ) -> dict:
        task_status = str((latest_task or {}).get("status") or "")
        task_active = task_status in {"queued", "running"}
        task_failed = task_status in {"failed", "partial_success"}
        documents_ready = bool(artifacts.get("document_profiles_ready")) or bool(
            int(document_summary.get("total_documents", 0) or 0)
        )
        objectives_ready = bool(artifacts.get("objective_candidates_ready"))

        if documents_ready:
            documents = {
                "status": "ready",
                "detail": "Document profiles are available.",
            }
        elif task_active:
            documents = {
                "status": "processing",
                "detail": "Document parsing and profiling are in progress.",
            }
        elif task_failed:
            documents = {
                "status": "failed",
                "detail": "The latest build did not produce document profiles.",
            }
        else:
            documents = {
                "status": "not_started",
                "detail": (
                    "Document profiles are not ready yet."
                    if file_count
                    else "No files uploaded."
                ),
            }

        if objectives_ready:
            objectives = {
                "status": "ready",
                "detail": "Objective candidate discovery is complete.",
            }
        elif task_active and documents_ready:
            objectives = {
                "status": "processing",
                "detail": "Objective candidate discovery is in progress.",
            }
        elif task_failed and documents_ready:
            objectives = {
                "status": "failed",
                "detail": "The latest build did not complete Objective discovery.",
            }
        else:
            objectives = {
                "status": "not_started",
                "detail": "Objective discovery starts after document profiles are ready.",
            }

        return {"documents": documents, "objectives": objectives}

    async def _build_document_summary(self, collection_id: str) -> dict:
        try:
            return await self.document_profile_service.get_document_summary(
                collection_id
            )
        except DocumentProfilesNotReadyError:
            return {"total_documents": 0, "by_doc_type": {}, "warnings": []}

    @staticmethod
    def _build_warnings(document_summary: dict) -> list[dict]:
        warnings: list[dict] = []
        total_documents = int(document_summary.get("total_documents", 0) or 0)
        by_doc_type = document_summary.get("by_doc_type", {})
        review_like = int(by_doc_type.get(DOC_TYPE_REVIEW, 0) or 0) + int(
            by_doc_type.get(DOC_TYPE_MIXED, 0) or 0
        )
        if total_documents and review_like / total_documents >= 0.5:
            warnings.append(
                {
                    "code": "review_heavy_collection",
                    "severity": "warning",
                    "message": "Most documents are review-heavy or mixed; experimental evidence may require manual review.",
                }
            )
        if int(by_doc_type.get(DOC_TYPE_UNCERTAIN, 0) or 0) > 0:
            warnings.append(
                {
                    "code": "uncertain_document_profiles",
                    "severity": "info",
                    "message": "Some documents remain uncertain and may need manual review.",
                }
            )
        return warnings

    @staticmethod
    def _build_links(collection_id: str) -> dict:
        base = f"/collections/{collection_id}"
        return {
            "workspace": base,
            "documents": f"{base}/documents",
            "objectives": f"{base}/objectives",
            "comparisons": f"{base}/comparisons",
        }

    async def get_workspace_overview(
        self,
        collection_id: str,
        recent_task_limit: int = 5,
    ) -> dict:
        collection = await self.collection_service.get_collection(collection_id)
        documents = collection["documents"]
        recent_tasks = await self.task_service.list_tasks(
            collection_id=collection_id,
            limit=recent_task_limit,
        )
        latest_task = recent_tasks[0] if recent_tasks else None
        document_summary = await self._build_document_summary(collection_id)
        artifacts = await self._build_artifacts(
            collection_id,
            collection,
            document_summary,
        )
        return {
            "collection": collection,
            "file_count": len(documents),
            "status_summary": self._build_status_summary(
                len(documents), latest_task, artifacts, document_summary
            ),
            "artifacts": artifacts,
            "workflow": self._build_workflow(
                len(documents), latest_task, artifacts, document_summary
            ),
            "document_summary": {
                "total_documents": int(
                    document_summary.get("total_documents", 0) or 0
                ),
                "by_doc_type": dict(document_summary.get("by_doc_type", {})),
            },
            "warnings": self._build_warnings(document_summary),
            "latest_task": latest_task,
            "recent_tasks": recent_tasks,
            "capabilities": self._build_capabilities(artifacts),
            "links": self._build_links(collection_id),
        }
