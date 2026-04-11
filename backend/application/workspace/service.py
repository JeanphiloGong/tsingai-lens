from __future__ import annotations

from pathlib import Path

from application.collections.service import CollectionService
from application.documents.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.indexing.task_service import TaskService
from application.workspace.artifact_registry_service import ArtifactRegistryService


class WorkspaceService:
    """Compose collection, task and artifact state into a single workspace view."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        task_service: TaskService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        document_profile_service: DocumentProfileService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.task_service = task_service or TaskService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )

    def _build_default_artifacts(self, collection_id: str) -> dict:
        paths = self.collection_service.get_paths(collection_id)
        return {
            "collection_id": collection_id,
            "output_path": str(paths.output_dir),
            "documents_ready": False,
            "document_profiles_ready": False,
            "evidence_cards_ready": False,
            "comparison_rows_ready": False,
            "graph_ready": False,
            "sections_ready": False,
            "procedure_blocks_ready": False,
            "protocol_steps_ready": False,
            "graphml_ready": False,
            "updated_at": self.collection_service.get_collection(collection_id)["updated_at"],
        }

    def _artifact_path_exists(self, artifacts: dict, filename: str) -> bool:
        output_path = artifacts.get("output_path")
        if not output_path:
            return False
        return (Path(str(output_path)).expanduser().resolve() / filename).exists()

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

    def _build_status_summary(
        self,
        file_count: int,
        latest_task: dict | None,
        artifacts: dict,
        document_summary: dict,
    ) -> str:
        if latest_task:
            status = str(latest_task.get("status") or "")
            if status == "running":
                return "processing"
            if status == "failed":
                return "attention_required"
            if status == "partial_success":
                return "partial_ready"
        if artifacts.get("comparison_rows_ready"):
            return "ready"
        if artifacts.get("evidence_cards_ready"):
            return "comparison_pending"
        if artifacts.get("document_profiles_ready"):
            return "document_profiled"
        if artifacts.get("protocol_steps_ready"):
            return "ready"
        if artifacts.get("graph_ready"):
            return "graph_ready"
        if file_count > 0:
            return "uploaded"
        return "empty"

    def _build_document_summary(self, collection_id: str) -> dict:
        try:
            summary = self.document_profile_service.get_document_summary(collection_id)
        except DocumentProfilesNotReadyError:
            summary = {
                "total_documents": 0,
                "by_doc_type": {},
                "by_protocol_extractable": {},
                "warnings": [],
            }
        return summary

    def _build_workflow(
        self,
        file_count: int,
        latest_task: dict | None,
        artifacts: dict,
        document_summary: dict,
    ) -> dict:
        task_status = str((latest_task or {}).get("status") or "")
        documents_ready = bool(artifacts.get("document_profiles_ready")) or document_summary.get(
            "total_documents", 0
        ) > 0
        evidence_ready = bool(artifacts.get("evidence_cards_ready"))
        comparison_ready = bool(artifacts.get("comparison_rows_ready"))
        protocol_ready = bool(artifacts.get("protocol_steps_ready"))
        protocol_candidates = document_summary.get("by_protocol_extractable", {}).get("yes", 0) + document_summary.get("by_protocol_extractable", {}).get("partial", 0)

        if file_count == 0:
            return {
                "documents": {"status": "not_started", "detail": "No files uploaded."},
                "evidence": {"status": "not_started", "detail": "Evidence cards are not generated yet."},
                "comparisons": {"status": "not_started", "detail": "Comparison rows are not generated yet."},
                "protocol": {"status": "not_applicable", "detail": "Protocol branch is unavailable before indexing."},
            }
        if task_status == "running":
            return {
                "documents": {"status": "processing", "detail": "Document profiling is in progress."},
                "evidence": {"status": "not_started", "detail": "Evidence extraction has not started yet."},
                "comparisons": {"status": "not_started", "detail": "Comparison rows are not generated yet."},
                "protocol": {"status": "not_started", "detail": "Protocol branch has not started yet."},
            }

        documents_stage = {
            "status": "ready" if documents_ready else "not_started",
            "detail": "Document profiles are available." if documents_ready else "Document profiles are not ready yet.",
        }
        evidence_stage_status = "ready" if evidence_ready else ("limited" if documents_ready else "not_started")
        evidence_stage = {
            "status": evidence_stage_status,
            "detail": (
                "Evidence cards are available."
                if evidence_ready
                else (
                    "No evidence cards were extracted from this collection yet."
                    if documents_ready
                    else "Evidence cards are not generated yet."
                )
            ),
        }
        comparisons_stage_status = (
            "ready"
            if comparison_ready
            else ("limited" if evidence_ready or documents_ready else "not_started")
        )
        comparisons_stage = {
            "status": comparisons_stage_status,
            "detail": (
                "Comparison rows are available."
                if comparison_ready
                else (
                    "Comparison rows are not yet available for direct collection-level comparison."
                    if evidence_ready or documents_ready
                    else "Comparison rows are not generated yet."
                )
            ),
        }

        if protocol_ready:
            protocol_stage = {"status": "ready", "detail": "Protocol artifacts are available."}
        elif documents_ready and protocol_candidates == 0:
            protocol_stage = {
                "status": "not_applicable",
                "detail": "No protocol-suitable documents were detected in this collection.",
            }
        elif documents_ready:
            protocol_stage = {
                "status": "limited",
                "detail": "Protocol branch is not ready yet or remains partial for this collection.",
            }
        else:
            protocol_stage = {
                "status": "not_started",
                "detail": "Protocol branch has not started yet.",
            }

        return {
            "documents": documents_stage,
            "evidence": evidence_stage,
            "comparisons": comparisons_stage,
            "protocol": protocol_stage,
        }

    def _build_warnings(self, document_summary: dict) -> list[dict]:
        warnings: list[dict] = []
        total_documents = int(document_summary.get("total_documents", 0) or 0)
        by_doc_type = document_summary.get("by_doc_type", {})
        by_protocol_extractable = document_summary.get("by_protocol_extractable", {})

        review_like = int(by_doc_type.get("review", 0) or 0) + int(by_doc_type.get("mixed", 0) or 0)
        if total_documents and review_like / total_documents >= 0.5:
            warnings.append(
                {
                    "code": "review_heavy_collection",
                    "severity": "warning",
                    "message": "Most documents are review-heavy or mixed, so protocol outputs may stay limited.",
                }
            )
        if total_documents and (int(by_protocol_extractable.get("yes", 0) or 0) + int(by_protocol_extractable.get("partial", 0) or 0)) == 0:
            warnings.append(
                {
                    "code": "protocol_limited_collection",
                    "severity": "warning",
                    "message": "No protocol-suitable documents were detected in this collection.",
                }
            )
        if int(by_doc_type.get("uncertain", 0) or 0) > 0:
            warnings.append(
                {
                    "code": "uncertain_document_profiles",
                    "severity": "info",
                    "message": "Some documents remain uncertain and may need manual review.",
                }
            )
        return warnings

    def _build_links(self, collection_id: str, artifacts: dict) -> dict:
        payload = {
            "documents_profiles": f"/api/v1/collections/{collection_id}/documents/profiles",
            "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
            "comparisons": f"/api/v1/collections/{collection_id}/comparisons",
            "protocol_steps": None,
        }
        if artifacts.get("protocol_steps_ready"):
            payload["protocol_steps"] = f"/api/v1/collections/{collection_id}/protocol/steps"
        return payload

    def get_workspace_overview(
        self,
        collection_id: str,
        recent_task_limit: int = 5,
    ) -> dict:
        collection = self.collection_service.get_collection(collection_id)
        files = self.collection_service.list_files(collection_id)
        recent_tasks = self.task_service.list_tasks(
            collection_id=collection_id,
            limit=recent_task_limit,
        )
        latest_task = recent_tasks[0] if recent_tasks else None
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            artifacts = self._build_default_artifacts(collection_id)
        document_summary = self._build_document_summary(collection_id)
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            pass
        return {
            "collection": collection,
            "file_count": len(files),
            "status_summary": self._build_status_summary(
                len(files),
                latest_task,
                artifacts,
                document_summary,
            ),
            "artifacts": {
                "output_path": artifacts["output_path"],
                "documents_ready": bool(artifacts.get("documents_ready")),
                "document_profiles_ready": bool(artifacts.get("document_profiles_ready")),
                "evidence_cards_ready": bool(artifacts.get("evidence_cards_ready")),
                "comparison_rows_ready": bool(artifacts.get("comparison_rows_ready")),
                "graph_ready": bool(artifacts.get("graph_ready")),
                "sections_ready": bool(artifacts.get("sections_ready")),
                "procedure_blocks_ready": bool(artifacts.get("procedure_blocks_ready")),
                "protocol_steps_ready": bool(artifacts.get("protocol_steps_ready")),
                "graphml_ready": bool(artifacts.get("graphml_ready")),
                "updated_at": artifacts["updated_at"],
            },
            "workflow": self._build_workflow(len(files), latest_task, artifacts, document_summary),
            "document_summary": {
                "total_documents": int(document_summary.get("total_documents", 0) or 0),
                "by_doc_type": dict(document_summary.get("by_doc_type", {})),
                "by_protocol_extractable": dict(
                    document_summary.get("by_protocol_extractable", {})
                ),
            },
            "warnings": self._build_warnings(document_summary),
            "latest_task": latest_task,
            "recent_tasks": recent_tasks,
            "capabilities": self._build_capabilities(artifacts),
            "links": self._build_links(collection_id, artifacts),
        }
