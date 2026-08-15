from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Callable

from application.core.objectives.research_objective_service import (
    ObjectiveAnalysisArtifacts,
    ResearchObjectiveService,
)
from domain.core import ObjectiveAnalysis, ResearchObjective
from domain.ports import ObjectiveRepository
from infra.llm.usage import capture_llm_usage


logger = logging.getLogger(__name__)

_PIPELINE_VERSION = "objective-analysis.v2"


class ObjectiveAnalysisService:
    """Run and atomically publish one versioned ResearchObjective analysis."""

    def __init__(
        self,
        *,
        objective_repository: ObjectiveRepository,
        research_objective_service: ResearchObjectiveService,
    ) -> None:
        self.objective_repository = objective_repository
        self.research_objective_service = research_objective_service

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
            model_name=None,
            prompt_versions={},
        )
        return self._result(collection_id, objective, analysis=analysis)

    def fail_analysis_dispatch(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        objective = self._require_objective(collection_id, objective_id)
        analysis = self.objective_repository.fail_analysis(
            collection_id,
            objective_id,
            analysis_version,
            error_code="analysis_dispatch_failed",
            error_message=(
                "Objective analysis could not be scheduled. Retry the analysis."
            ),
            expected_status="queued",
        )
        return self._result(collection_id, objective, analysis=analysis)

    def get_analysis_state(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
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

    def execute_queued_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        try:
            objective = self._require_objective(collection_id, objective_id)
            claimed = self.objective_repository.claim_analysis(
                collection_id,
                objective_id,
                analysis_version,
            )
            if claimed is None:
                return self._result(collection_id, objective)
            usage_started_at = perf_counter()
            with capture_llm_usage() as usage:
                try:
                    artifacts = (
                        self.research_objective_service.generate_objective_analysis_artifacts(
                            collection_id,
                            claimed,
                            progress_callback=self._build_progress_callback(claimed),
                        )
                    )
                    self._validate_artifacts(artifacts)
                finally:
                    claimed = self.objective_repository.update_analysis_execution_stats(
                        collection_id,
                        objective_id,
                        analysis_version,
                        stats=usage.execution_stats(
                            duration_ms=round(
                                (perf_counter() - usage_started_at) * 1000
                            )
                        ),
                        model_name=usage.model_name,
                        prompt_versions=usage.prompt_versions,
                    )
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
                current = self.objective_repository.fail_analysis(
                    collection_id,
                    objective_id,
                    analysis_version,
                    error_code=self._error_code(exc),
                    error_message=str(exc) or exc.__class__.__name__,
                )
            objective = self._require_objective(collection_id, objective_id)
            return self._result(collection_id, objective, analysis=current)

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
        paper_contributions = ()
        if published is not None:
            paper_contributions = self.objective_repository.list_contributions(
                collection_id,
                objective.objective_id,
                published.analysis_version,
            )
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
            "paper_contributions": paper_contributions,
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
        seen_document_ids: set[str] = set()
        processed_document_count = analysis.processed_document_count
        total_document_count = analysis.total_document_count

        def update(progress: dict[str, Any]) -> None:
            nonlocal processed_document_count, total_document_count
            active_document_id = (
                str(progress.get("active_document_id"))
                if progress.get("active_document_id")
                else None
            )
            if active_document_id:
                seen_document_ids.add(active_document_id)
            if progress.get("unit") in {"documents", "frames"}:
                current = self._safe_int(progress.get("current"))
                total = self._safe_int(progress.get("total"))
                total_document_count = max(total_document_count, total or 0)
                processed_document_count = max(
                    processed_document_count,
                    current or 0,
                )
            else:
                processed_document_count = max(
                    processed_document_count,
                    len(seen_document_ids),
                )
            processed_document_count = min(
                processed_document_count,
                total_document_count,
            )
            self.objective_repository.update_analysis_progress(
                analysis.collection_id,
                analysis.objective_id,
                analysis.analysis_version,
                phase=str(progress.get("phase") or "running"),
                processed_document_count=processed_document_count,
                total_document_count=total_document_count,
                current_document_id=active_document_id,
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
