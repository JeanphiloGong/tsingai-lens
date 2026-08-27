from __future__ import annotations

from asyncio import (
    CancelledError,
    Semaphore,
    Task,
    create_task,
    get_running_loop,
    run_coroutine_threadsafe,
)
from collections.abc import Coroutine
import logging
from time import perf_counter
from typing import Any, Callable

from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.evidence_map import build_objective_evidence_map
from application.core.objectives.research_objective_service import (
    ObjectiveAnalysisArtifacts,
    ResearchObjectiveService,
)
from domain.core import ObjectiveAnalysis, ResearchObjective
from domain.ports import ObjectiveRepository
from infra.llm.usage import capture_llm_usage


logger = logging.getLogger(__name__)

_PIPELINE_VERSION = "objective-analysis.v2"
_ANALYSIS_MAX_CONCURRENCY = 4


class ObjectiveAnalysisDispatchError(RuntimeError):
    """A queued Objective analysis could not be handed to an asyncio worker."""

    def __init__(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> None:
        super().__init__(
            "Objective analysis could not be scheduled. Retry the analysis."
        )
        self.collection_id = collection_id
        self.objective_id = objective_id
        self.analysis_version = analysis_version


class ObjectiveAnalysisService:
    """Run and atomically publish one versioned ResearchObjective analysis."""

    def __init__(
        self,
        *,
        objective_repository: ObjectiveRepository,
        research_objective_service: ResearchObjectiveService,
        max_concurrency: int = _ANALYSIS_MAX_CONCURRENCY,
        task_factory: Callable[[Coroutine[Any, Any, dict[str, Any]]], Any] = create_task,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("objective analysis concurrency must be positive")
        self.objective_repository = objective_repository
        self.research_objective_service = research_objective_service
        self._analysis_semaphore = Semaphore(max_concurrency)
        self._task_factory = task_factory
        self._analysis_tasks: set[Any] = set()

    async def start_analysis(
        self,
        collection_id: str,
        objective_id: str,
        document_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Confirm, queue, and asynchronously dispatch one canonical analysis."""

        payload = await self.queue_analysis(
            collection_id,
            objective_id,
            document_ids,
        )
        analysis = payload.get("analysis")
        if analysis is None or analysis.status != "queued":
            return payload

        coroutine = self._execute_scheduled_analysis(
            collection_id,
            objective_id,
            analysis.analysis_version,
        )
        try:
            task = self._task_factory(coroutine)
        except Exception as exc:  # noqa: BLE001
            coroutine.close()
            logger.exception(
                "Objective analysis dispatch failed collection_id=%s "
                "objective_id=%s analysis_version=%s",
                collection_id,
                objective_id,
                analysis.analysis_version,
            )
            await self.fail_analysis_dispatch(
                collection_id,
                objective_id,
                analysis.analysis_version,
            )
            raise ObjectiveAnalysisDispatchError(
                collection_id,
                objective_id,
                analysis.analysis_version,
            ) from exc
        self._analysis_tasks.add(task)
        task.add_done_callback(self._analysis_tasks.discard)
        task.add_done_callback(self._log_unexpected_analysis_failure)
        return payload

    async def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        document_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        document_inputs = (
            await self.research_objective_service.resolve_prepared_document_inputs(
                collection_id,
                document_ids,
            )
        )
        objective, analysis = await self.objective_repository.queue_analysis(
            collection_id,
            objective_id,
            document_inputs=document_inputs,
            pipeline_version=_PIPELINE_VERSION,
            model_name=None,
            prompt_versions={},
        )
        return await self._result(collection_id, objective, analysis=analysis)

    async def fail_analysis_dispatch(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        objective = await self._require_objective(collection_id, objective_id)
        analysis = await self.objective_repository.fail_analysis(
            collection_id,
            objective_id,
            analysis_version,
            error_code="analysis_dispatch_failed",
            error_message=(
                "Objective analysis could not be scheduled. Retry the analysis."
            ),
            expected_status="queued",
        )
        return await self._result(collection_id, objective, analysis=analysis)

    async def get_analysis_state(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
        objective = await self._require_objective(collection_id, objective_id)
        return await self._result(collection_id, objective)

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        *,
        analysis_version: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        version = await self._published_version(
            collection_id,
            objective_id,
            analysis_version,
        )
        findings, total = await self.objective_repository.list_findings(
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

    async def get_finding(
        self,
        collection_id: str,
        objective_id: str,
        finding_id: str,
        *,
        analysis_version: int | None = None,
    ) -> dict[str, Any]:
        version = await self._published_version(
            collection_id,
            objective_id,
            analysis_version,
        )
        finding = await self.objective_repository.read_finding(
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

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        *,
        analysis_version: int | None = None,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        version = await self._published_version(
            collection_id,
            objective_id,
            analysis_version,
        )
        evidence, total = await self.objective_repository.list_evidence(
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

    async def get_evidence_map(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
        objective = await self._require_objective(collection_id, objective_id)
        version = await self._published_version(collection_id, objective_id, None)
        analysis = await self.objective_repository.read_published_analysis(
            collection_id,
            objective_id,
        )
        if analysis is None:
            raise ValueError("objective has no published analysis")

        findings = await self._all_published_findings(
            collection_id,
            objective_id,
            version,
        )
        evidence_records = await self._all_published_evidence(
            collection_id,
            objective_id,
            version,
        )
        profiles = await (
            self.research_objective_service.document_profile_service.read_document_profiles(
                collection_id,
                tuple(item.document_id for item in analysis.document_inputs),
            )
        )
        return build_objective_evidence_map(
            objective=objective,
            analysis=analysis,
            contributions=await self.objective_repository.list_contributions(
                collection_id,
                objective_id,
                version,
            ),
            findings=findings,
            evidence_records=evidence_records,
            profiles=profiles,
        )

    async def _all_published_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[Any, ...]:
        records: list[Any] = []
        offset = 0
        while True:
            page, total = await self.objective_repository.list_findings(
                collection_id,
                objective_id,
                analysis_version,
                offset=offset,
                limit=200,
            )
            records.extend(page)
            offset += len(page)
            if offset >= total or not page:
                return tuple(records)

    async def _all_published_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[Any, ...]:
        records: list[Any] = []
        offset = 0
        while True:
            page, total = await self.objective_repository.list_evidence(
                collection_id,
                objective_id,
                analysis_version,
                offset=offset,
                limit=500,
            )
            records.extend(page)
            offset += len(page)
            if offset >= total or not page:
                return tuple(records)

    async def execute_queued_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        try:
            objective = await self._require_objective(collection_id, objective_id)
            claimed = await self.objective_repository.claim_analysis(
                collection_id,
                objective_id,
                analysis_version,
            )
            if claimed is None:
                return await self._result(collection_id, objective)
            usage_started_at = perf_counter()
            progress_callback = self._build_progress_callback(claimed)
            with (
                capture_llm_usage() as usage,
                capture_analysis_diagnostics() as diagnostics,
            ):
                artifacts: ObjectiveAnalysisArtifacts | None = None
                try:
                    artifacts = (
                        await self.research_objective_service.generate_objective_analysis_artifacts(
                            collection_id,
                            claimed,
                            progress_callback=progress_callback,
                        )
                    )
                    self._validate_artifacts(artifacts)
                finally:
                    claimed = await self.objective_repository.update_analysis_execution_stats(
                        collection_id,
                        objective_id,
                        analysis_version,
                        stats=usage.execution_stats(
                            duration_ms=round(
                                (perf_counter() - usage_started_at) * 1000
                            )
                        ),
                        model_name=(
                            usage.model_name
                            or (artifacts.model_name if artifacts is not None else None)
                            or claimed.model_name
                        ),
                        prompt_versions=usage.prompt_versions,
                        diagnostics=diagnostics.records,
                    )
            objective, completed = await self.objective_repository.publish_analysis(
                collection_id,
                objective_id,
                analysis_version,
                contributions=artifacts.contributions,
                evidence_records=artifacts.evidence_records,
                findings=artifacts.findings,
            )
            return await self._result(collection_id, objective, analysis=completed)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Objective analysis failed collection_id=%s objective_id=%s analysis_version=%s",
                collection_id,
                objective_id,
                analysis_version,
            )
            current = await self.objective_repository.read_analysis(
                collection_id,
                objective_id,
                analysis_version,
            )
            if current is not None and current.status in {"queued", "running"}:
                current = await self.objective_repository.fail_analysis(
                    collection_id,
                    objective_id,
                    analysis_version,
                    error_code=self._error_code(exc),
                    error_message=str(exc) or exc.__class__.__name__,
                )
            objective = await self._require_objective(collection_id, objective_id)
            return await self._result(collection_id, objective, analysis=current)

    async def _execute_scheduled_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        async with self._analysis_semaphore:
            return await self.execute_queued_analysis(
                collection_id,
                objective_id,
                analysis_version,
            )

    @staticmethod
    def _log_unexpected_analysis_failure(task: Task[dict[str, Any]]) -> None:
        try:
            task.result()
        except CancelledError:
            logger.info("Objective analysis task cancelled during backend shutdown")
        except Exception:  # noqa: BLE001
            logger.exception("Objective analysis crashed after service scheduling")

    @staticmethod
    def _validate_artifacts(artifacts: ObjectiveAnalysisArtifacts) -> None:
        if not artifacts.contributions:
            raise RuntimeError("objective analysis produced no paper contributions")
        relevant_contributions = tuple(
            contribution
            for contribution in artifacts.contributions
            if contribution.analysis_status != "excluded"
        )
        if relevant_contributions and all(
            contribution.analysis_status == "failed"
            for contribution in relevant_contributions
        ):
            raise RuntimeError(
                "objective analysis failed to extract every relevant paper"
            )

    async def _result(
        self,
        collection_id: str,
        objective: ResearchObjective,
        *,
        analysis: ObjectiveAnalysis | None = None,
    ) -> dict[str, Any]:
        active = analysis or await self.objective_repository.read_analysis(
            collection_id,
            objective.objective_id,
            objective.active_analysis_version,
        )
        published = await self.objective_repository.read_published_analysis(
            collection_id,
            objective.objective_id,
        )
        findings = ()
        paper_contributions = ()
        warnings: list[str] = []
        if published is not None:
            paper_contributions = await self.objective_repository.list_contributions(
                collection_id,
                objective.objective_id,
                published.analysis_version,
            )
            findings, _total = await self.objective_repository.list_findings(
                collection_id,
                objective.objective_id,
                published.analysis_version,
                offset=0,
                limit=50,
            )
            seen_warnings: set[str] = set()
            for contribution in paper_contributions:
                for warning in contribution.warnings:
                    scoped_warning = f"{contribution.document_id}: {warning}"
                    if scoped_warning in seen_warnings:
                        continue
                    seen_warnings.add(scoped_warning)
                    warnings.append(scoped_warning)
        return {
            "collection_id": collection_id,
            "objective": objective,
            "analysis": active,
            "published_analysis": published,
            "findings": findings,
            "paper_contributions": paper_contributions,
            "warnings": warnings,
        }

    async def _require_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return objective

    async def _published_version(
        self,
        collection_id: str,
        objective_id: str,
        requested_version: int | None,
    ) -> int:
        objective = await self._require_objective(collection_id, objective_id)
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
        loop = get_running_loop()
        seen_document_ids: set[str] = set()
        processed_document_count = analysis.processed_document_count
        total_document_count = analysis.total_document_count

        def update(progress: dict[str, Any]) -> None:
            nonlocal processed_document_count
            active_document_id = (
                str(progress.get("active_document_id"))
                if progress.get("active_document_id")
                else None
            )
            if active_document_id:
                seen_document_ids.add(active_document_id)
            if progress.get("unit") in {"documents", "frames"}:
                current = self._safe_int(progress.get("current"))
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
            update_future = run_coroutine_threadsafe(
                self.objective_repository.update_analysis_progress(
                    analysis.collection_id,
                    analysis.objective_id,
                    analysis.analysis_version,
                    phase=str(progress.get("phase") or "running"),
                    processed_document_count=processed_document_count,
                    total_document_count=total_document_count,
                    current_document_id=active_document_id,
                    progress_message=(
                        str(progress.get("message"))
                        if progress.get("message")
                        else None
                    ),
                ),
                loop,
            )
            update_future.result()

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


__all__ = ["ObjectiveAnalysisDispatchError", "ObjectiveAnalysisService"]
