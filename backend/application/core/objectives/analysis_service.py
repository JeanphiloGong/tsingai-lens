from __future__ import annotations

from asyncio import (
    CancelledError,
    Lock,
    Semaphore,
    Task,
    create_task,
    get_running_loop,
    run_coroutine_threadsafe,
)
from collections.abc import Coroutine
from dataclasses import replace
import logging
from time import perf_counter
from typing import Any, Callable

from application.core.document_profiles.service import DocumentProfileService
from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
    record_analysis_failure,
)
from application.core.objectives.analysis_errors import analysis_error_message
from application.core.objectives.evidence_map import build_objective_evidence_map
from application.core.objectives.objective_analysis_service import (
    ObjectiveAnalysisArtifacts,
    ObjectiveEvidenceAnalysisService,
)
from application.core.objectives.objective_input_service import ObjectiveInputService
from domain.core import ObjectiveAnalysis, ResearchObjective
from application.repositories.objective_repository import ObjectiveRepository
from infra.llm.usage import capture_llm_usage


logger = logging.getLogger(__name__)

_PIPELINE_VERSION = "objective-analysis.v2"
_ANALYSIS_MAX_CONCURRENCY = 4


_EVIDENCE_REVIEW_GAP_LIMIT = 200


def _evidence_review_summary(
    evidence_records: tuple[Any, ...],
) -> dict[str, Any]:
    """Build the researcher-facing disposition of every published Evidence.

    Finding synthesis is intentionally conservative and may return no Finding.
    The evidence ledger still needs to explain what was observed, what remains
    incomplete, and which failures are technical.  This summary is derived at
    read time from the immutable Evidence records, so it does not introduce a
    second persistence contract or silently discard a scientific state.
    """

    status_counts: dict[str, int] = {}
    result_count = 0
    gaps: list[dict[str, Any]] = []
    for evidence in evidence_records:
        status = str(getattr(evidence, "evidence_status", "") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if getattr(evidence, "reported_result", None) is not None:
            result_count += 1
        if status == "comparable":
            continue
        result = getattr(evidence, "reported_result", None)
        gaps.append(
            {
                "evidence_id": str(getattr(evidence, "evidence_id", "") or ""),
                "document_id": str(getattr(evidence, "document_id", "") or ""),
                "source_kind": str(getattr(evidence, "source_kind", "") or ""),
                "source_ref": str(getattr(evidence, "source_ref", "") or ""),
                "page_numbers": list(getattr(evidence, "page_numbers", ()) or ()),
                "evidence_status": status,
                "reason": str(
                    getattr(evidence, "evidence_status_reason", "")
                    or "Evidence is not ready for a strict cross-paper comparison."
                ),
                "outcome": (
                    str(getattr(result, "outcome", "") or "")
                    if result is not None
                    else None
                ),
                "source_excerpt": str(
                    getattr(evidence, "source_excerpt", "") or ""
                )[:1200],
            }
        )
    ordered_gaps = sorted(
        gaps,
        key=lambda item: (
            item["document_id"],
            item["source_kind"],
            item["source_ref"],
            item["evidence_id"],
        ),
    )
    return {
        "total_evidence_count": len(evidence_records),
        "result_count": result_count,
        "comparable_evidence_count": status_counts.get("comparable", 0),
        "gap_count": len(ordered_gaps),
        "status_counts": dict(sorted(status_counts.items())),
        "gaps": ordered_gaps[:_EVIDENCE_REVIEW_GAP_LIMIT],
        "omitted_gap_count": max(0, len(ordered_gaps) - _EVIDENCE_REVIEW_GAP_LIMIT),
    }


def _scientific_abstention(
    artifacts: ObjectiveAnalysisArtifacts,
) -> tuple[str | None, str | None]:
    """Explain a successful analysis with evidence but no defensible Finding.

    A researcher distinguishes a paper that reports an observation from a
    comparison that supports an attributed conclusion.  Preserve that
    distinction in the published analysis instead of exposing ``findings=[]``
    as if the analysis had no useful result or had silently failed.
    """

    if artifacts.findings:
        return None, None

    evidence = tuple(artifacts.evidence_records)
    status_counts: dict[str, int] = {}
    for record in evidence:
        status = record.evidence_status
        status_counts[status] = status_counts.get(status, 0) + 1
    status_note = "; ".join(
        f"{status}={count}" for status, count in sorted(status_counts.items())
    ) or "none"

    if not evidence:
        return (
            "no_grounded_evidence",
            "No source-backed Evidence was retained, so the Objective cannot support a scientific conclusion.",
        )

    reported_results = tuple(
        record
        for record in evidence
        if record.selection_status == "extracted" and record.reported_result is not None
    )
    if reported_results:
        return (
            "insufficient_evidence",
            f"{len(reported_results)} source-backed result(s) were retained, but none satisfied the comparison conditions for a Finding. Evidence status counts: {status_note}.",
        )

    if all(record.evidence_status == "extraction_failed" for record in evidence):
        return (
            "no_grounded_evidence",
            f"{len(evidence)} Evidence item(s) were retained, but all failed technical extraction before a source-backed result could be established. Evidence status counts: {status_note}.",
        )

    return (
        "no_comparable_evidence",
        f"{len(evidence)} Evidence item(s) were retained, but none contained a source-backed reported result that could be compared for this Objective. Evidence status counts: {status_note}.",
    )


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
        evidence_analysis_service: ObjectiveEvidenceAnalysisService,
        objective_input_service: ObjectiveInputService,
        document_profile_service: DocumentProfileService,
        max_concurrency: int = _ANALYSIS_MAX_CONCURRENCY,
        task_factory: Callable[[Coroutine[Any, Any, dict[str, Any]]], Any] = create_task,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("objective analysis concurrency must be positive")
        self.objective_repository = objective_repository
        self.evidence_analysis_service = evidence_analysis_service
        self.objective_input_service = objective_input_service
        self.document_profile_service = document_profile_service
        self._analysis_semaphore = Semaphore(max_concurrency)
        self._task_factory = task_factory
        self._analysis_tasks: set[Any] = set()

    async def recover_interrupted_analyses(self) -> int:
        interrupted_count = (
            await self.objective_repository.interrupt_active_analyses()
        )
        if interrupted_count:
            logger.warning(
                "Recovered interrupted Objective analyses count=%s",
                interrupted_count,
            )
        return interrupted_count

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
            await self.objective_input_service.resolve_prepared_document_inputs(
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
        return await self._result(collection_id, objective.objective_id, analysis=analysis)

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
        return await self._result(collection_id, objective.objective_id, analysis=analysis)

    async def get_analysis_state(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
        return await self._result(collection_id, objective_id)

    async def get_analysis_status(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
        """Read only the active analysis progress needed for polling."""

        objective = await self._require_objective(collection_id, objective_id)
        analysis = await self.objective_repository.read_analysis(
            collection_id,
            objective.objective_id,
            objective.active_analysis_version,
        )
        if analysis is None:
            return {
                "collection_id": collection_id,
                "objective_id": objective.objective_id,
                "analysis_version": None,
                "status": None,
                "phase": None,
                "processed_document_count": 0,
                "total_document_count": 0,
                "current_document_id": None,
                "progress_message": None,
                "error_code": None,
                "error_message": None,
                "created_at": None,
                "started_at": None,
                "completed_at": None,
            }
        return {
            "collection_id": collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": analysis.analysis_version,
            "status": analysis.status,
            "phase": analysis.phase,
            "processed_document_count": analysis.processed_document_count,
            "total_document_count": analysis.total_document_count,
            "current_document_id": analysis.current_document_id,
            "progress_message": analysis.progress_message,
            "error_code": analysis.error_code,
            "error_message": (
                analysis_error_message(analysis.error_code)
                if analysis.status == "failed"
                else analysis.error_message
            ),
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
            "started_at": analysis.started_at.isoformat() if analysis.started_at else None,
            "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
        }

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
            "items": [
                {**item.to_record(), "supports_finding": item.supports_finding}
                for item in evidence
            ],
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
        profiles = await self.document_profile_service.read_document_profiles(
            collection_id,
            tuple(item.document_id for item in analysis.document_inputs),
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
                return await self._result(collection_id, objective.objective_id)
            usage_started_at = perf_counter()
            progress_callback = self._build_progress_callback(claimed)
            with (
                capture_llm_usage() as usage,
                capture_analysis_diagnostics() as diagnostics,
            ):
                artifacts: ObjectiveAnalysisArtifacts | None = None
                try:
                    artifacts = (
                        await self.evidence_analysis_service.generate_objective_analysis_artifacts(
                            collection_id,
                            claimed,
                            progress_callback=progress_callback,
                        )
                    )
                    self._validate_artifacts(artifacts)
                except Exception as exc:
                    record_analysis_failure(
                        exc,
                        collection_id=collection_id,
                        objective_id=objective_id,
                        analysis_version=analysis_version,
                        stage="generate_artifacts",
                    )
                    raise
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
            abstention_reason, abstention_note = _scientific_abstention(artifacts)
            objective, completed = await self.objective_repository.publish_analysis(
                collection_id,
                objective_id,
                analysis_version,
                contributions=artifacts.contributions,
                evidence_records=artifacts.evidence_records,
                findings=artifacts.findings,
                abstention_reason=abstention_reason,
                abstention_note=abstention_note,
            )
            return await self._result(collection_id, objective.objective_id, analysis=completed)
        except Exception as exc:  # noqa: BLE001
            record_analysis_failure(
                exc,
                collection_id=collection_id,
                objective_id=objective_id,
                analysis_version=analysis_version,
                stage="execute_analysis",
            )
            logger.error(
                "Objective analysis failed collection_id=%s objective_id=%s analysis_version=%s error_type=%s",
                collection_id,
                objective_id,
                analysis_version,
                type(exc).__name__,
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
                    error_message=analysis_error_message(self._error_code(exc)),
                )
            return await self._result(collection_id, objective_id, analysis=current)

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
        objective_id: str,
        *,
        analysis: ObjectiveAnalysis | None = None,
    ) -> dict[str, Any]:
        stored_objective = await self.objective_repository.read_objective_record(
            collection_id, objective_id
        )
        if stored_objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        objective = stored_objective.objective
        active = analysis
        if active is None and objective.active_analysis_version is not None:
            active = await self.objective_repository.read_analysis(
                collection_id, objective_id, objective.active_analysis_version
            )
        published = None
        if objective.published_analysis_version is not None:
            if (
                active is not None
                and active.analysis_version == objective.published_analysis_version
            ):
                published = active
            else:
                published = await self.objective_repository.read_analysis(
                    collection_id, objective_id, objective.published_analysis_version
                )
        if active is not None and active.error_code == "analysis_interrupted":
            active = None
        if active is not None and active.status == "failed":
            active = replace(
                active,
                error_message=analysis_error_message(active.error_code),
            )
        findings = ()
        finding_total = 0
        paper_contributions = ()
        evidence_records = ()
        warnings: list[str] = []
        if published is not None:
            paper_contributions = await self.objective_repository.list_contributions(
                collection_id,
                objective.objective_id,
                published.analysis_version,
            )
            findings, finding_total = await self.objective_repository.list_findings(
                collection_id,
                objective.objective_id,
                published.analysis_version,
                offset=0,
                limit=50,
            )
            evidence_records = await self._all_published_evidence(
                collection_id,
                objective.objective_id,
                published.analysis_version,
            )
            seen_warnings: set[str] = set()
            for contribution in paper_contributions:
                for warning in contribution.warnings:
                    scoped_warning = f"{contribution.document_id}: {warning}"
                    if scoped_warning in seen_warnings:
                        continue
                    seen_warnings.add(scoped_warning)
                    warnings.append(scoped_warning)
                for status, count in contribution.evidence_status_counts:
                    if status == "comparable" or count <= 0:
                        continue
                    scoped_status = (
                        f"{contribution.document_id}: {count} Evidence item(s) "
                        f"classified as {status}."
                    )
                    if scoped_status in seen_warnings:
                        continue
                    seen_warnings.add(scoped_status)
                    warnings.append(scoped_status)
                if (
                    contribution.evidence_disposition
                    in {
                        "no_routable_evidence",
                        "no_comparable_evidence",
                        "extraction_failed",
                    }
                    and contribution.evidence_disposition_reason
                ):
                    scoped_reason = (
                        f"{contribution.document_id}: "
                        f"{contribution.evidence_disposition_reason}"
                    )
                    if scoped_reason not in seen_warnings:
                        seen_warnings.add(scoped_reason)
                        warnings.append(scoped_reason)
            for evidence in evidence_records:
                for warning in evidence.warnings:
                    scoped_warning = (
                        f"{evidence.document_id}/{evidence.source_ref}: {warning}"
                    )
                    if scoped_warning in seen_warnings:
                        continue
                    seen_warnings.add(scoped_warning)
                    warnings.append(scoped_warning)
            for finding in findings:
                for warning in finding.warnings:
                    scoped_warning = f"Finding {finding.finding_id}: {warning}"
                    if scoped_warning in seen_warnings:
                        continue
                    seen_warnings.add(scoped_warning)
                    warnings.append(scoped_warning)
        return {
            "collection_id": collection_id,
            "objective": stored_objective,
            "analysis": active,
            "published_analysis": published,
            "findings": findings,
            "finding_total": finding_total,
            "omitted_finding_count": max(0, finding_total - len(findings)),
            "paper_contributions": paper_contributions,
            "evidence_review": _evidence_review_summary(evidence_records),
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
        completed_document_ids: set[str] = set()
        progress_lock = Lock()

        async def persist_progress(progress: dict[str, Any]) -> None:
            # Worker events can overlap; count and persist them in the same order.
            async with progress_lock:
                active_document_id = progress.get("active_document_id")
                if (
                    progress.get("phase") == "objective_document_evidence_completed"
                    and active_document_id
                ):
                    completed_document_ids.add(active_document_id)
                await self.objective_repository.update_analysis_progress(
                    analysis.collection_id,
                    analysis.objective_id,
                    analysis.analysis_version,
                    phase=progress.get("phase") or "running",
                    processed_document_count=max(
                        analysis.processed_document_count,
                        len(completed_document_ids),
                    ),
                    total_document_count=analysis.total_document_count,
                    current_document_id=active_document_id,
                    progress_message=progress.get("message"),
                )

        def update(progress: dict[str, Any]) -> None:
            update_future = run_coroutine_threadsafe(
                persist_progress(progress),
                loop,
            )
            update_future.result()

        return update

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return "provider_timeout"
        if isinstance(exc, ValueError):
            return "invalid_analysis_artifact"
        return "objective_analysis_failed"


__all__ = ["ObjectiveAnalysisDispatchError", "ObjectiveAnalysisService"]
