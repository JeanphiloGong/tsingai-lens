from __future__ import annotations

import logging
from typing import Any, Callable

from application.core.semantic_build.research_objective_service import (
    ObjectiveAnalysisArtifacts,
    ResearchObjectiveService,
)
from domain.core import ObjectiveAnalysis, ResearchObjective
from domain.ports import ObjectiveRepository


logger = logging.getLogger(__name__)

_PIPELINE_VERSION = "objective-analysis.v2"


class ObjectiveAnalysisService:
    """Run and atomically publish one versioned ResearchObjective analysis."""

    def __init__(
        self,
        *,
        objective_repository: ObjectiveRepository,
        research_objective_service: ResearchObjectiveService,
        model_name: str | None = None,
        prompt_versions: dict[str, str] | None = None,
    ) -> None:
        self.objective_repository = objective_repository
        self.research_objective_service = research_objective_service
        self.model_name = model_name
        self.prompt_versions = dict(prompt_versions or {})

    def confirm_objective(self, collection_id: str, objective_id: str) -> dict[str, Any]:
        objective = self.objective_repository.confirm_objective(
            collection_id, objective_id
        )
        return self._result(collection_id, objective)

    def queue_analysis(self, collection_id: str, objective_id: str) -> dict[str, Any]:
        objective, analysis = self.objective_repository.queue_analysis(
            collection_id,
            objective_id,
            pipeline_version=_PIPELINE_VERSION,
            model_name=self.model_name,
            prompt_versions=self.prompt_versions,
        )
        return self._result(collection_id, objective, analysis=analysis)

    def get_analysis(self, collection_id: str, objective_id: str) -> dict[str, Any]:
        objective = self._require_objective(collection_id, objective_id)
        return self._result(collection_id, objective)

    def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        *,
        analysis_version: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        version = self._published_version(
            collection_id,
            objective_id,
            analysis_version,
        )
        findings, total = self.objective_repository.list_findings(
            collection_id,
            objective_id,
            version,
            offset=offset,
            limit=limit,
        )
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": version,
            "items": [finding.to_record() for finding in findings],
            "offset": offset,
            "limit": limit,
            "total": total,
        }

    def get_finding(
        self,
        collection_id: str,
        objective_id: str,
        finding_id: str,
        *,
        analysis_version: int | None = None,
    ) -> dict[str, Any]:
        version = self._published_version(
            collection_id,
            objective_id,
            analysis_version,
        )
        finding = self.objective_repository.read_finding(
            collection_id,
            objective_id,
            version,
            finding_id,
        )
        if finding is None:
            raise FileNotFoundError(
                f"finding not found: {objective_id}/v{version}/{finding_id}"
            )
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": version,
            "finding": finding.to_record(),
        }

    def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        *,
        analysis_version: int | None = None,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        version = self._published_version(
            collection_id,
            objective_id,
            analysis_version,
        )
        evidence, total = self.objective_repository.list_evidence(
            collection_id,
            objective_id,
            version,
            finding_id=finding_id,
            offset=offset,
            limit=limit,
        )
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": version,
            "finding_id": finding_id,
            "items": [item.to_record() for item in evidence],
            "offset": offset,
            "limit": limit,
            "total": total,
        }

    def run_analysis(self, collection_id: str, objective_id: str) -> dict[str, Any]:
        objective = self._require_objective(collection_id, objective_id)
        analysis_version = objective.active_analysis_version
        if analysis_version is None:
            raise ValueError("objective has no queued analysis")
        claimed = self.objective_repository.claim_analysis(
            collection_id,
            objective_id,
            analysis_version,
        )
        if claimed is None:
            return self._result(collection_id, objective)

        try:
            artifacts = self.research_objective_service.analyze_objective(
                collection_id,
                claimed,
                progress_callback=self._build_progress_callback(claimed),
            )
            self._validate_artifacts(artifacts)
            objective, completed = self.objective_repository.publish_analysis(
                collection_id,
                objective_id,
                analysis_version,
                contributions=artifacts.contributions,
                evidence_records=artifacts.evidence_records,
                findings=artifacts.findings,
            )
            return self._result(collection_id, objective, analysis=completed)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Objective analysis failed collection_id=%s objective_id=%s analysis_version=%s",
                collection_id,
                objective_id,
                analysis_version,
            )
            current = self.objective_repository.read_analysis(
                collection_id,
                objective_id,
                analysis_version,
            )
            if current is not None and current.status in {"queued", "running"}:
                self.objective_repository.fail_analysis(
                    collection_id,
                    objective_id,
                    analysis_version,
                    error_code=self._error_code(exc),
                    error_message=str(exc) or exc.__class__.__name__,
                )
            objective = self._require_objective(collection_id, objective_id)
            return self._result(collection_id, objective)

    @staticmethod
    def _validate_artifacts(artifacts: ObjectiveAnalysisArtifacts) -> None:
        if not artifacts.contributions:
            raise RuntimeError("objective analysis produced no paper contributions")
        if not artifacts.evidence_records:
            raise RuntimeError("objective analysis produced no source-backed evidence")
        if not artifacts.findings:
            raise RuntimeError("objective analysis produced no reviewable findings")

    def _result(
        self,
        collection_id: str,
        objective: ResearchObjective,
        *,
        analysis: ObjectiveAnalysis | None = None,
    ) -> dict[str, Any]:
        active = analysis or self.objective_repository.read_analysis(
            collection_id,
            objective.objective_id,
            objective.active_analysis_version,
        )
        published = self.objective_repository.read_published_analysis(
            collection_id,
            objective.objective_id,
        )
        findings = ()
        if published is not None:
            findings, _total = self.objective_repository.list_findings(
                collection_id,
                objective.objective_id,
                published.analysis_version,
                offset=0,
                limit=50,
            )
        return {
            "collection_id": collection_id,
            "objective": objective,
            "analysis": active,
            "published_analysis": published,
            "findings": findings,
            "warnings": [],
        }

    def _require_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        objective = self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return objective

    def _published_version(
        self,
        collection_id: str,
        objective_id: str,
        requested_version: int | None,
    ) -> int:
        objective = self._require_objective(collection_id, objective_id)
        published_version = objective.published_analysis_version
        if published_version is None:
            raise ValueError("objective has no published analysis")
        if requested_version is not None and requested_version != published_version:
            raise ValueError("requested analysis version is not published")
        return published_version

    def _build_progress_callback(
        self,
        analysis: ObjectiveAnalysis,
    ) -> Callable[[dict[str, Any]], None]:
        def update(progress: dict[str, Any]) -> None:
            current = self._safe_int(progress.get("current"))
            total = self._safe_int(progress.get("total"))
            processed = max(0, current or 0)
            document_total = max(
                analysis.total_document_count,
                total or analysis.total_document_count,
            )
            processed = min(processed, document_total)
            self.objective_repository.update_analysis_progress(
                analysis.collection_id,
                analysis.objective_id,
                analysis.analysis_version,
                phase=str(progress.get("phase") or "running"),
                processed_document_count=processed,
                total_document_count=document_total,
                current_document_id=(
                    str(progress.get("active_document_id"))
                    if progress.get("active_document_id")
                    else None
                ),
                progress_message=(
                    str(progress.get("message")) if progress.get("message") else None
                ),
            )

        return update

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return "provider_timeout"
        if isinstance(exc, ValueError):
            return "invalid_analysis_artifact"
        return "objective_analysis_failed"


__all__ = ["ObjectiveAnalysisService"]
