from __future__ import annotations

from domain.shared.enums import (
    DOC_TYPE_MIXED,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
)
from application.source.collection_service import CollectionService
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.source.task_service import TaskService
from domain.ports import CoreFactRepository, SourceArtifactRepository
from infra.persistence.factory import (
    build_core_fact_repository,
)


class WorkspaceService:
    """Compose collection, task and artifact state into a single workspace view."""

    def __init__(
        self,
        collection_service: CollectionService,
        task_service: TaskService,
        source_artifact_repository: SourceArtifactRepository,
        document_profile_service: DocumentProfileService | None = None,
        core_fact_repository: CoreFactRepository | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.task_service = task_service
        self.core_fact_repository = (
            core_fact_repository
            or build_core_fact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.source_artifact_repository = source_artifact_repository
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            core_fact_repository=self.core_fact_repository,
            source_artifact_repository=self.source_artifact_repository,
        )

    def _build_artifacts(self, collection_id: str, collection: dict) -> dict:
        source_artifacts = self.source_artifact_repository.read_collection_artifacts(
            collection_id
        )
        core_facts = self.core_fact_repository.read_collection_facts(collection_id)
        source_artifacts_generated = not source_artifacts.is_empty()
        return {
            "collection_id": collection_id,
            "documents_generated": bool(source_artifacts.documents),
            "documents_ready": bool(source_artifacts.documents),
            "document_profiles_generated": bool(core_facts.document_profiles),
            "document_profiles_ready": bool(core_facts.document_profiles),
            "evidence_anchors_generated": core_facts.paper_facts_generated,
            "evidence_anchors_ready": bool(core_facts.evidence_anchors),
            "method_facts_generated": core_facts.paper_facts_generated,
            "method_facts_ready": bool(core_facts.method_facts),
            "evidence_cards_generated": core_facts.evidence_cards_generated,
            "evidence_cards_ready": core_facts.evidence_cards_ready,
            "characterization_observations_generated": (
                core_facts.paper_facts_generated
            ),
            "characterization_observations_ready": bool(
                core_facts.characterization_observations
            ),
            "structure_features_generated": core_facts.paper_facts_generated,
            "structure_features_ready": bool(core_facts.structure_features),
            "test_conditions_generated": core_facts.paper_facts_generated,
            "test_conditions_ready": bool(core_facts.test_conditions),
            "baseline_references_generated": core_facts.paper_facts_generated,
            "baseline_references_ready": bool(core_facts.baseline_references),
            "sample_variants_generated": core_facts.paper_facts_generated,
            "sample_variants_ready": bool(core_facts.sample_variants),
            "measurement_results_generated": core_facts.paper_facts_generated,
            "measurement_results_ready": bool(core_facts.measurement_results),
            "comparable_results_generated": core_facts.comparison_artifacts_generated,
            "comparable_results_ready": bool(core_facts.comparable_results),
            "collection_comparable_results_generated": (
                core_facts.comparison_artifacts_generated
            ),
            "collection_comparable_results_ready": bool(
                core_facts.collection_comparable_results
            ),
            "collection_comparable_results_stale": False,
            "comparison_rows_generated": core_facts.comparison_artifacts_generated,
            "comparison_rows_ready": bool(core_facts.comparison_rows),
            "comparison_rows_stale": False,
            "graph_generated": core_facts.graph_generated,
            "graph_ready": core_facts.graph_ready,
            "graph_stale": False,
            "blocks_generated": source_artifacts_generated,
            "blocks_ready": bool(source_artifacts.blocks),
            "figures_generated": source_artifacts_generated,
            "figures_ready": bool(source_artifacts.figures),
            "table_rows_generated": source_artifacts_generated,
            "table_rows_ready": bool(source_artifacts.table_rows),
            "table_cells_generated": source_artifacts_generated,
            "table_cells_ready": bool(source_artifacts.table_cells),
            "updated_at": collection["updated_at"],
        }

    def _artifact_generated(
        self,
        artifacts: dict,
        generated_key: str,
    ) -> bool:
        return bool(artifacts.get(generated_key))

    def _artifact_ready(
        self,
        artifacts: dict,
        ready_key: str,
    ) -> bool:
        return bool(artifacts.get(ready_key))

    def _artifact_stale(
        self,
        artifacts: dict,
        stale_key: str,
    ) -> bool:
        return bool(artifacts.get(stale_key))

    def _comparisons_generated(self, artifacts: dict) -> bool:
        return self._artifact_generated(
            artifacts,
            "comparable_results_generated",
        ) and self._artifact_generated(
            artifacts,
            "collection_comparable_results_generated",
        )

    def _comparisons_ready(self, artifacts: dict) -> bool:
        return self._artifact_ready(
            artifacts,
            "comparable_results_ready",
        ) and self._artifact_ready(
            artifacts,
            "collection_comparable_results_ready",
        )

    def _comparisons_stale(self, artifacts: dict) -> bool:
        return self._artifact_stale(
            artifacts,
            "collection_comparable_results_stale",
        )

    def _build_capabilities(self, artifacts: dict) -> dict:
        graph_ready = self._artifact_ready(artifacts, "graph_ready")
        comparisons_generated = self._comparisons_generated(artifacts)
        research_view_generated = self._artifact_ready(
            artifacts,
            "evidence_cards_ready",
        ) or self._artifact_generated(
            artifacts,
            "sample_variants_generated",
        ) or self._artifact_generated(
            artifacts,
            "measurement_results_generated",
        )
        return {
            "can_view_graph": graph_ready,
            "can_view_results": comparisons_generated,
            "can_view_comparable_results": comparisons_generated,
            "can_view_research_view": research_view_generated,
            "can_download_graphml": graph_ready,
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
        )
        comparisons_ready = self._comparisons_ready(artifacts)
        if latest_task:
            status = str(latest_task.get("status") or "")
            if status == "running":
                return "processing"
            if status == "failed":
                return "attention_required"
            if status == "partial_success":
                return "partial_ready"
        if comparisons_ready:
            return "ready"
        if self._artifact_ready(artifacts, "graph_ready"):
            return "graph_ready"
        if self._artifact_ready(artifacts, "evidence_cards_ready"):
            return "comparison_pending"
        if self._artifact_ready(artifacts, "document_profiles_ready") or document_profiles_generated:
            return "document_profiled"
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
        )
        evidence_generated = self._artifact_generated(
            artifacts,
            "evidence_cards_generated",
        )
        comparisons_generated = self._comparisons_generated(artifacts)
        graph_generated = self._artifact_generated(
            artifacts,
            "graph_generated",
        )
        documents_ready = self._artifact_ready(
            artifacts,
            "document_profiles_ready",
        ) or document_summary.get("total_documents", 0) > 0
        evidence_ready = self._artifact_ready(artifacts, "evidence_cards_ready")
        comparison_ready = self._comparisons_ready(artifacts)
        graph_ready = self._artifact_ready(artifacts, "graph_ready")
        graph_stale = self._artifact_stale(artifacts, "graph_stale")

        any_generated = (
            documents_generated
            or evidence_generated
            or comparisons_generated
            or graph_generated
        )
        if file_count == 0 and not any_generated:
            return {
                "documents": {"status": "not_started", "detail": "No files uploaded."},
                "results": {"status": "not_started", "detail": "Collection results are not generated yet."},
                "evidence": {"status": "not_started", "detail": "Evidence cards are not generated yet."},
                "comparisons": {"status": "not_started", "detail": "Collection-scoped comparisons are not generated yet."},
                "graph": {"status": "not_started", "detail": "Graph projection is not generated yet."},
            }
        if task_status == "running":
            return {
                "documents": {"status": "processing", "detail": "Document profiling is in progress."},
                "results": {"status": "not_started", "detail": "Collection results have not been prepared yet."},
                "evidence": {"status": "not_started", "detail": "Paper facts extraction has not started yet."},
                "comparisons": {"status": "not_started", "detail": "Collection-scoped comparisons are not generated yet."},
                "graph": {"status": "not_started", "detail": "Graph projection has not started yet."},
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
                "detail": "Paper facts extraction completed, but no evidence cards were derived from this collection.",
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

        comparisons_stale = self._comparisons_stale(artifacts)
        if comparison_ready:
            results_stage = {
                "status": "ready",
                "detail": "Collection results are available.",
            }
        elif comparisons_stale:
            results_stage = {
                "status": "limited",
                "detail": "Collection results are stale and require reassessment before they are current again.",
            }
        elif comparisons_generated:
            results_stage = {
                "status": "limited",
                "detail": "Result semantics were generated, but no collection-scoped results are currently available.",
            }
        elif documents_ready or documents_generated:
            results_stage = {
                "status": "not_started",
                "detail": "Collection results are not generated yet.",
            }
        else:
            results_stage = {
                "status": "not_started",
                "detail": "Collection results are not generated yet.",
            }

        if comparison_ready:
            comparisons_stage = {
                "status": "ready",
                "detail": "Collection-scoped comparisons are available.",
            }
        elif comparisons_stale:
            comparisons_stage = {
                "status": "limited",
                "detail": "Collection-scoped comparisons are stale and require reassessment before they are current again.",
            }
        elif comparisons_generated:
            comparisons_stage = {
                "status": "limited",
                "detail": "Comparison semantics were generated, but no collection-scoped results were suitable for structured comparison.",
            }
        elif evidence_ready or evidence_generated or documents_ready or documents_generated:
            comparisons_stage = {
                "status": "not_started",
                "detail": "Collection-scoped comparisons are not generated yet.",
            }
        else:
            comparisons_stage = {
                "status": "not_started",
                "detail": "Collection-scoped comparisons are not generated yet.",
            }

        if graph_ready:
            graph_stage = {
                "status": "ready",
                "detail": "Graph view is available.",
            }
        elif graph_stale:
            graph_stage = {
                "status": "limited",
                "detail": "Graph inputs are stale and require reassessment before graph projection is current again.",
            }
        elif graph_generated:
            graph_stage = {
                "status": "limited",
                "detail": "Graph inputs were generated, but no current graph projection is available yet.",
            }
        elif comparison_ready or comparisons_generated:
            graph_stage = {
                "status": "not_started",
                "detail": "Graph projection is not generated yet.",
            }
        else:
            graph_stage = {
                "status": "not_started",
                "detail": "Graph projection has not started yet.",
            }

        return {
            "documents": documents_stage,
            "results": results_stage,
            "evidence": evidence_stage,
            "comparisons": comparisons_stage,
            "graph": graph_stage,
        }

    def _build_warnings(self, document_summary: dict) -> list[dict]:
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

    def _build_links(self, collection_id: str) -> dict:
        payload = {
            "documents": f"/api/v1/collections/{collection_id}/documents/profiles",
            "documents_profiles": f"/api/v1/collections/{collection_id}/documents/profiles",
            "evidence": f"/api/v1/collections/{collection_id}/evidence/cards",
            "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
            "research_view": f"/api/v1/collections/{collection_id}/research-view",
            "research_materials": f"/api/v1/collections/{collection_id}/materials",
            "research_material": (
                f"/api/v1/collections/{collection_id}/materials/"
                "{material_id}/research-view"
            ),
            "research_documents": (
                f"/api/v1/collections/{collection_id}/documents/"
                "{document_id}/research-view"
            ),
            "research_document_materials": (
                f"/api/v1/collections/{collection_id}/documents/"
                "{document_id}/materials"
            ),
            "research_document_material": (
                f"/api/v1/collections/{collection_id}/documents/"
                "{document_id}/materials/{material_id}/research-view"
            ),
            "comparisons": f"/api/v1/collections/{collection_id}/comparisons",
            "results": f"/api/v1/collections/{collection_id}/results",
            "comparable_results": f"/api/v1/comparable-results?collection_id={collection_id}",
            "graph": f"/api/v1/collections/{collection_id}/graph",
        }
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
        document_summary = self._build_document_summary(collection_id)
        artifacts = self._build_artifacts(collection_id, collection)
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
                "documents_generated": bool(artifacts.get("documents_generated")),
                "documents_ready": bool(artifacts.get("documents_ready")),
                "document_profiles_generated": bool(artifacts.get("document_profiles_generated")),
                "document_profiles_ready": bool(artifacts.get("document_profiles_ready")),
                "evidence_anchors_generated": bool(artifacts.get("evidence_anchors_generated")),
                "evidence_anchors_ready": bool(artifacts.get("evidence_anchors_ready")),
                "method_facts_generated": bool(artifacts.get("method_facts_generated")),
                "method_facts_ready": bool(artifacts.get("method_facts_ready")),
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
                "sample_variants_generated": bool(artifacts.get("sample_variants_generated")),
                "sample_variants_ready": bool(artifacts.get("sample_variants_ready")),
                "measurement_results_generated": bool(
                    artifacts.get("measurement_results_generated")
                ),
                "measurement_results_ready": bool(
                    artifacts.get("measurement_results_ready")
                ),
                "comparable_results_generated": bool(
                    artifacts.get("comparable_results_generated")
                ),
                "comparable_results_ready": bool(
                    artifacts.get("comparable_results_ready")
                ),
                "collection_comparable_results_generated": bool(
                    artifacts.get("collection_comparable_results_generated")
                ),
                "collection_comparable_results_ready": bool(
                    artifacts.get("collection_comparable_results_ready")
                ),
                "collection_comparable_results_stale": bool(
                    artifacts.get("collection_comparable_results_stale")
                ),
                "comparison_rows_generated": bool(artifacts.get("comparison_rows_generated")),
                "comparison_rows_ready": bool(artifacts.get("comparison_rows_ready")),
                "comparison_rows_stale": bool(artifacts.get("comparison_rows_stale")),
                "graph_generated": bool(artifacts.get("graph_generated")),
                "graph_ready": bool(artifacts.get("graph_ready")),
                "graph_stale": bool(artifacts.get("graph_stale")),
                "blocks_generated": bool(artifacts.get("blocks_generated")),
                "blocks_ready": bool(artifacts.get("blocks_ready")),
                "figures_generated": bool(artifacts.get("figures_generated")),
                "figures_ready": bool(artifacts.get("figures_ready")),
                "table_rows_generated": bool(artifacts.get("table_rows_generated")),
                "table_rows_ready": bool(artifacts.get("table_rows_ready")),
                "table_cells_generated": bool(artifacts.get("table_cells_generated")),
                "table_cells_ready": bool(artifacts.get("table_cells_ready")),
                "updated_at": artifacts["updated_at"],
            },
            "workflow": self._build_workflow(len(files), latest_task, artifacts, document_summary),
            "document_summary": {
                "total_documents": int(document_summary.get("total_documents", 0) or 0),
                "by_doc_type": dict(document_summary.get("by_doc_type", {})),
            },
            "warnings": self._build_warnings(document_summary),
            "latest_task": latest_task,
            "recent_tasks": recent_tasks,
            "capabilities": self._build_capabilities(artifacts),
            "links": self._build_links(collection_id),
        }
