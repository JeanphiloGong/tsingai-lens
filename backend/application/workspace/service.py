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
            "documents_generated": False,
            "documents_ready": False,
            "document_profiles_generated": False,
            "document_profiles_ready": False,
            "evidence_cards_generated": False,
            "evidence_cards_ready": False,
            "characterization_observations_generated": False,
            "characterization_observations_ready": False,
            "structure_features_generated": False,
            "structure_features_ready": False,
            "test_conditions_generated": False,
            "test_conditions_ready": False,
            "baseline_references_generated": False,
            "baseline_references_ready": False,
            "comparison_rows_generated": False,
            "comparison_rows_ready": False,
            "graph_generated": False,
            "graph_ready": False,
            "sections_generated": False,
            "sections_ready": False,
            "table_cells_generated": False,
            "table_cells_ready": False,
            "procedure_blocks_generated": False,
            "procedure_blocks_ready": False,
            "protocol_steps_generated": False,
            "protocol_steps_ready": False,
            "graphml_generated": False,
            "graphml_ready": False,
            "updated_at": self.collection_service.get_collection(collection_id)["updated_at"],
        }

    def _artifact_path_exists(self, artifacts: dict, filename: str) -> bool:
        output_path = artifacts.get("output_path")
        if not output_path:
            return False
        return (Path(str(output_path)).expanduser().resolve() / filename).exists()

    def _artifact_generated(
        self,
        artifacts: dict,
        generated_key: str,
        filename: str,
    ) -> bool:
        if generated_key in artifacts:
            return bool(artifacts.get(generated_key))
        return self._artifact_path_exists(artifacts, filename)

    def _artifact_ready(
        self,
        artifacts: dict,
        ready_key: str,
    ) -> bool:
        return bool(artifacts.get(ready_key))

    def _build_capabilities(self, artifacts: dict) -> dict:
        graph_ready = self._artifact_ready(artifacts, "graph_ready")
        protocol_generated = self._artifact_generated(
            artifacts,
            "protocol_steps_generated",
            "protocol_steps.parquet",
        )
        return {
            "can_view_graph": graph_ready,
            "can_download_graphml": graph_ready,
            "can_view_protocol_steps": protocol_generated,
            "can_search_protocol": protocol_generated,
            "can_generate_sop": protocol_generated,
        }

    def _build_status_summary(
        self,
        file_count: int,
        latest_task: dict | None,
        artifacts: dict,
        document_summary: dict,
    ) -> str:
        document_profiles_generated = self._artifact_generated(
            artifacts,
            "document_profiles_generated",
            "document_profiles.parquet",
        )
        if latest_task:
            status = str(latest_task.get("status") or "")
            if status == "running":
                return "processing"
            if status == "failed":
                return "attention_required"
            if status == "partial_success":
                return "partial_ready"
        if self._artifact_ready(artifacts, "comparison_rows_ready"):
            return "ready"
        if self._artifact_ready(artifacts, "evidence_cards_ready"):
            return "comparison_pending"
        if self._artifact_ready(artifacts, "document_profiles_ready") or document_profiles_generated:
            return "document_profiled"
        if self._artifact_ready(artifacts, "graph_ready"):
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
        documents_generated = self._artifact_generated(
            artifacts,
            "document_profiles_generated",
            "document_profiles.parquet",
        )
        evidence_generated = self._artifact_generated(
            artifacts,
            "evidence_cards_generated",
            "evidence_cards.parquet",
        )
        comparisons_generated = self._artifact_generated(
            artifacts,
            "comparison_rows_generated",
            "comparison_rows.parquet",
        )
        protocol_generated = self._artifact_generated(
            artifacts,
            "protocol_steps_generated",
            "protocol_steps.parquet",
        )
        documents_ready = self._artifact_ready(
            artifacts,
            "document_profiles_ready",
        ) or document_summary.get("total_documents", 0) > 0
        evidence_ready = self._artifact_ready(artifacts, "evidence_cards_ready")
        comparison_ready = self._artifact_ready(artifacts, "comparison_rows_ready")
        protocol_ready = self._artifact_ready(artifacts, "protocol_steps_ready")
        protocol_candidates = (
            document_summary.get("by_protocol_extractable", {}).get("yes", 0)
            + document_summary.get("by_protocol_extractable", {}).get("partial", 0)
        )

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

        if documents_ready:
            documents_stage = {
                "status": "ready",
                "detail": "Document profiles are available.",
            }
        elif documents_generated:
            documents_stage = {
                "status": "limited",
                "detail": "Document profiling completed, but no profile rows were produced from this collection.",
            }
        else:
            documents_stage = {
                "status": "not_started",
                "detail": "Document profiles are not ready yet.",
            }

        if evidence_ready:
            evidence_stage = {
                "status": "ready",
                "detail": "Evidence cards are available.",
            }
        elif evidence_generated:
            evidence_stage = {
                "status": "limited",
                "detail": "Evidence extraction completed, but no evidence cards were extracted from this collection.",
            }
        elif documents_ready or documents_generated:
            evidence_stage = {
                "status": "not_started",
                "detail": "Evidence cards are not generated yet.",
            }
        else:
            evidence_stage = {
                "status": "not_started",
                "detail": "Evidence cards are not generated yet.",
            }

        if comparison_ready:
            comparisons_stage = {
                "status": "ready",
                "detail": "Comparison rows are available.",
            }
        elif comparisons_generated:
            comparisons_stage = {
                "status": "limited",
                "detail": "Comparison generation completed, but no rows were suitable for structured comparison.",
            }
        elif evidence_ready or evidence_generated or documents_ready or documents_generated:
            comparisons_stage = {
                "status": "not_started",
                "detail": "Comparison rows are not generated yet.",
            }
        else:
            comparisons_stage = {
                "status": "not_started",
                "detail": "Comparison rows are not generated yet.",
            }

        if protocol_ready:
            protocol_stage = {"status": "ready", "detail": "Protocol artifacts are available."}
        elif protocol_generated:
            protocol_stage = {
                "status": "limited",
                "detail": "Protocol artifacts were generated but no usable protocol steps are currently available.",
            }
        elif (documents_ready or documents_generated) and protocol_candidates == 0:
            protocol_stage = {
                "status": "not_applicable",
                "detail": "No protocol-suitable documents were detected in this collection.",
            }
        elif documents_ready or documents_generated:
            protocol_stage = {
                "status": "not_started",
                "detail": "Protocol branch has not generated artifacts yet.",
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
        if self._artifact_generated(
            artifacts,
            "protocol_steps_generated",
            "protocol_steps.parquet",
        ):
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
                "documents_generated": bool(artifacts.get("documents_generated")),
                "documents_ready": bool(artifacts.get("documents_ready")),
                "document_profiles_generated": bool(artifacts.get("document_profiles_generated")),
                "document_profiles_ready": bool(artifacts.get("document_profiles_ready")),
                "evidence_cards_generated": bool(artifacts.get("evidence_cards_generated")),
                "evidence_cards_ready": bool(artifacts.get("evidence_cards_ready")),
                "characterization_observations_generated": bool(
                    artifacts.get("characterization_observations_generated")
                ),
                "characterization_observations_ready": bool(
                    artifacts.get("characterization_observations_ready")
                ),
                "structure_features_generated": bool(
                    artifacts.get("structure_features_generated")
                ),
                "structure_features_ready": bool(
                    artifacts.get("structure_features_ready")
                ),
                "test_conditions_generated": bool(artifacts.get("test_conditions_generated")),
                "test_conditions_ready": bool(artifacts.get("test_conditions_ready")),
                "baseline_references_generated": bool(
                    artifacts.get("baseline_references_generated")
                ),
                "baseline_references_ready": bool(
                    artifacts.get("baseline_references_ready")
                ),
                "comparison_rows_generated": bool(artifacts.get("comparison_rows_generated")),
                "comparison_rows_ready": bool(artifacts.get("comparison_rows_ready")),
                "graph_generated": bool(artifacts.get("graph_generated")),
                "graph_ready": bool(artifacts.get("graph_ready")),
                "sections_generated": bool(artifacts.get("sections_generated")),
                "sections_ready": bool(artifacts.get("sections_ready")),
                "table_cells_generated": bool(artifacts.get("table_cells_generated")),
                "table_cells_ready": bool(artifacts.get("table_cells_ready")),
                "procedure_blocks_generated": bool(artifacts.get("procedure_blocks_generated")),
                "procedure_blocks_ready": bool(artifacts.get("procedure_blocks_ready")),
                "protocol_steps_generated": bool(artifacts.get("protocol_steps_generated")),
                "protocol_steps_ready": bool(artifacts.get("protocol_steps_ready")),
                "graphml_generated": bool(artifacts.get("graphml_generated")),
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
