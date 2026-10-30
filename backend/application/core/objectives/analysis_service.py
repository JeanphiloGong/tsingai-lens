from __future__ import annotations

from application.core.objectives.analysis.experiment_projection import experiment_evidence_disposition

import logging
from asyncio import (
    CancelledError,
    Lock,
    Semaphore,
    Task,
    create_task,
    get_running_loop,
    gather,
    run_coroutine_threadsafe,
    to_thread,
)
from dataclasses import asdict, replace
from time import perf_counter
from typing import Any, Callable

from application.core.document_profiles import service as document_profile_service
from application.core.objectives import (
    objective_analysis_service as experiment_analysis_service,
)
from application.core.objectives import (
    objective_input_service,
)
from application.core.objectives.analysis import (
    experiment_analysis_writer,
    experiment_projection,
)
from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriteResult,
)
from application.core.objectives.analysis.analysis_record_source import (
    is_experiment_backed_analysis,
    should_read_experiment_projection,
)
from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
    record_analysis_failure,
)
from application.core.objectives.analysis_errors import analysis_error_message
from application.core.objectives.evidence_map import build_objective_evidence_map
from application.core.objectives.finding_summary import (
    MAX_SUMMARY_EVIDENCE,
    FindingSummaryUnavailable,
    summarize_finding_evidence,
)
from application.core.objectives.discovery.paper_understanding.workflow import PaperResearchMapExtractor
from application.core.objectives.analysis.paper_experiment_extraction import PaperExperimentExtractor
from application.core.objectives.analysis.source_screening import ObjectiveSourceScreener
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
    build_default_structured_response_client,
)
from application.core.objectives.objective_analysis_service import (
    ObjectiveExperimentAnalysisArtifacts,
    ResearchObjectiveNotFoundError,
)
from application.source import collection_service
from domain.core import ResearchObjective
from domain.core.finding import Finding
from domain.core.research_objective import ObjectiveEvidence
from exceptions import (
    ResourceConflictException,
    ResourceNotFoundException,
    ServiceUnavailableException,
)
from infra.llm.usage import capture_llm_usage
from infra.persistence.database import AsyncSessionLocal
from repositories.objective_repository import ObjectiveAnalysis

logger = logging.getLogger(__name__)

_PIPELINE_VERSION = "objective-analysis.v2"
_ANALYSIS_MAX_CONCURRENCY = 4


_EVIDENCE_REVIEW_GAP_LIMIT = 200


def _evidence_review_summary(
    evidence_records: tuple[ObjectiveEvidence, ...],
    *,
    experiment_backed: bool = False,
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
        status, reason = (
            experiment_evidence_disposition(evidence)
            if experiment_backed
            else (evidence.evidence_status, evidence.evidence_status_reason)
        )
        status_counts[status] = status_counts.get(status, 0) + 1
        if evidence.reported_result is not None:
            result_count += 1
        if status == "comparable":
            continue
        result = evidence.reported_result
        gaps.append(
            {
                "evidence_id": evidence.evidence_id,
                "document_id": evidence.document_id,
                "source_kind": evidence.source_kind,
                "source_ref": evidence.source_ref,
                "page_numbers": list(evidence.page_numbers),
                "evidence_status": status,
                "reason": str(
                    reason
                    or "Evidence is not ready for a strict cross-paper comparison."
                ),
                "outcome": (
                    result.outcome
                    if result is not None
                    else None
                ),
                "source_excerpt": evidence.source_excerpt[
                    :1200
                ],
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



def _experiment_abstention(
    result: ExperimentAnalysisWriteResult,
) -> tuple[str | None, str | None]:
    """Explain a successful experiment analysis with no published Finding."""

    findings = result.findings
    selections = result.selections
    if findings:
        return None, None
    if not selections:
        # A partial archive is intentionally written without an Objective
        # selection: its bindings are not strong enough for a Finding.  It is
        # still source-grounded research state, so reporting it as
        # ``no_grounded_evidence`` would erase the distinction between
        # "nothing was recovered" and "something was recovered but needs
        # context".
        revisions = result.revisions
        if any(
            revision.revision.measurements
            or revision.revision.comparisons
            or revision.revision.reported_interpretations
            for revision in revisions
        ):
            return (
                "insufficient_evidence",
                "Source-grounded experiment content was archived, but its partial bindings were not sufficient for an Objective selection or Finding.",
            )
        return (
            "no_grounded_evidence",
            "No Objective-relevant experiment selection was recovered from the prepared Sources.",
        )
    comparison_count = sum(
        bool(selection.comparison_keys) for selection in selections
    )
    if comparison_count:
        return (
            "insufficient_evidence",
            "Source-grounded experiment selections were retained, but none supported a defensible Finding under the recorded comparison conditions.",
        )
    return (
        "no_comparable_evidence",
        "Source-grounded measurements were retained, but no paper-internal comparison was available for this Objective.",
    )


class ObjectiveAnalysisDispatchError(ServiceUnavailableException):
    """A queued Objective analysis could not be handed to an asyncio worker."""

    def __init__(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> None:
        super().__init__(
            "Objective analysis could not be scheduled. Retry the analysis.",
            data={
                "code": "objective_analysis_dispatch_failed",
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": analysis_version,
            },
        )
        self.collection_id = collection_id
        self.objective_id = objective_id
        self.analysis_version = analysis_version


from repositories.objective_repository import ObjectiveRepo, StoredObjective


class ObjectiveAnalysisService:
    """Own analysis tasks and concurrency admitted by one application."""

    def __init__(self, *, max_concurrency: int = _ANALYSIS_MAX_CONCURRENCY) -> None:
        self._analysis_semaphore = Semaphore(max_concurrency)
        self._analysis_tasks: set[Task[dict[str, Any]]] = set()
        self._response_client: StructuredResponseClient | None = None
        self._summary_client: StructuredResponseClient | None = None
        self._source_screener: ObjectiveSourceScreener | None = None
        self._paper_experiment_extractor: PaperExperimentExtractor | None = None
        self._paper_map_extractor: PaperResearchMapExtractor | None = None

    async def close(self) -> None:
        tasks = tuple(self._analysis_tasks)
        for task in tasks:
            task.cancel()
        await gather(*tasks, return_exceptions=True)
        for client in (self._response_client, self._summary_client):
            if client is not None:
                client.client.close()

    def _get_response_client(self) -> StructuredResponseClient:
        if self._response_client is None:
            self._response_client = build_default_structured_response_client()
        return self._response_client

    def _get_summary_client(self) -> StructuredResponseClient:
        if self._summary_client is None:
            try:
                client = build_default_structured_response_client()
                client.client = client.client.with_options(timeout=60.0, max_retries=0)
            except Exception as exc:
                logger.warning("Finding summary unavailable error_type=%s", type(exc).__name__)
                raise FindingSummaryUnavailable("summary_generation_failed") from exc
            self._summary_client = client
        return self._summary_client

    def _get_source_screener(self) -> ObjectiveSourceScreener:
        if self._source_screener is None:
            self._source_screener = ObjectiveSourceScreener(self._get_response_client())
        return self._source_screener

    def _get_paper_map_extractor(self) -> PaperResearchMapExtractor:
        if self._paper_map_extractor is None:
            self._paper_map_extractor = PaperResearchMapExtractor(self._get_response_client())
        return self._paper_map_extractor

    def _get_paper_experiment_extractor(self) -> PaperExperimentExtractor:
        if self._paper_experiment_extractor is None:
            self._paper_experiment_extractor = PaperExperimentExtractor(
                self._get_response_client()
            )
        return self._paper_experiment_extractor

    async def summarize_finding(
        self,
        collection_id: str,
        objective_id: str,
        finding_id: str,
        *,
        user_id: str,
        analysis_version: int,
        language: str,
    ) -> dict[str, Any]:
        try:
            detail = await get_finding(
                collection_id,
                objective_id,
                finding_id,
                analysis_version=analysis_version,
                user_id=user_id,
            )
        except ResourceConflictException as exc:
            raise ResourceConflictException(
                "The published analysis has changed. Reload before generating a summary.",
                data={"code": "summary_stale_analysis"},
            ) from exc
        experiment_backed = await should_read_experiment_projection(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
        )
        if experiment_backed:
            records, total = await experiment_projection.list_analysis_evidence(
                collection_id,
                objective_id,
                analysis_version,
                finding_id=finding_id,
                offset=0,
                limit=MAX_SUMMARY_EVIDENCE,
            )
        else:
            records, total = await ObjectiveRepo.list_evidence(
                collection_id,
                objective_id,
                analysis_version,
                finding_id=finding_id,
                offset=0,
                limit=MAX_SUMMARY_EVIDENCE,
            )
        if total > MAX_SUMMARY_EVIDENCE:
            raise FindingSummaryUnavailable("summary_input_too_large")
        result = await to_thread(
            summarize_finding_evidence,
            finding=detail["finding"],
            evidence=[
                (
                    {
                        "collection_id": item.collection_id,
                        "objective_id": item.objective_id,
                        "analysis_version": item.analysis_version,
                        "evidence_id": item.evidence_id,
                        "document_id": item.document_id,
                        "source_kind": item.source_kind,
                        "source_ref": item.source_ref,
                        "source_excerpt": item.source_excerpt,
                        "page_numbers": list(item.page_numbers),
                        "evidence_role": item.evidence_role,
                        "selection_status": item.selection_status,
                        "selection_reason": item.selection_reason,
                        "evidence_status": (
                                experiment_evidence_disposition(item)[0]
                                if experiment_backed else item.evidence_status
                            ),
                        "evidence_status_reason": (
                                experiment_evidence_disposition(item)[1]
                                if experiment_backed else item.evidence_status_reason
                            ),
                        "changed_variables": [
                            {
                                "name": variable.name,
                                "baseline_value": variable.baseline_value,
                                "target_value": variable.target_value,
                                "unit": variable.unit,
                            }
                            for variable in item.changed_variables
                        ],
                        "comparison": (
                            {
                                "baseline_label": item.comparison.baseline_label,
                                "target_label": item.comparison.target_label,
                                "axis_names": list(item.comparison.axis_names),
                                "comparable": item.comparison.comparable,
                                "incomparability_reasons": list(
                                    item.comparison.incomparability_reasons
                                ),
                            }
                            if item.comparison
                            else None
                        ),
                        "reported_result": (
                            {
                                "outcome": item.reported_result.outcome,
                                "value": item.reported_result.value,
                                "baseline_value": item.reported_result.baseline_value,
                                "target_value": item.reported_result.target_value,
                                "unit": item.reported_result.unit,
                                "direction": item.reported_result.direction,
                                "result_text": item.reported_result.result_text,
                                "result_kind": item.reported_result.result_kind,
                            }
                            if item.reported_result
                            else None
                        ),
                        "attribution_scope": item.attribution_scope,
                        "scientific_context": {
                            "material": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.material
                            ],
                            "sample": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.sample
                            ],
                            "process": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.process
                            ],
                            "test": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.test
                            ],
                        },
                        "resolution_status": item.resolution_status,
                        "failure_reason": item.failure_reason,
                        "confidence": item.confidence,
                        "origin": item.origin,
                        "source_analysis_version": item.source_analysis_version,
                        "supersedes_evidence_id": item.supersedes_evidence_id,
                        "superseded_by_evidence_id": item.superseded_by_evidence_id,
                        "created_by_user_id": item.created_by_user_id,
                        "created_by_tool_call_id": item.created_by_tool_call_id,
                        "created_at": (
                            item.created_at.isoformat()
                            if item.created_at is not None
                            else None
                        ),
                        "authoring_note": item.authoring_note,
                        **({
                            "supports_finding": item.comparison is None or item.comparison.comparable,
                            "eligible_for_finding_authoring": item.comparison is None or item.comparison.comparable,
                            "warnings": list(item.warnings),
                        } if experiment_backed else {}),
                        **({"warnings": list(item.warnings)} if item.warnings else {}),
                        **(
                            {
                                "related_source_refs": [
                                    dict(item) for item in item.related_source_refs
                                ]
                            }
                            if item.related_source_refs or item.related_source_refs_explicit
                            else {}
                        ),
                    }
                )
                for item in records
            ],
            language=language,
            response_client=self._get_summary_client(),
        )
        try:
            await _published_version(collection_id, objective_id, analysis_version)
        except ResourceConflictException as exc:
            raise ResourceConflictException(
                "The published analysis has changed. Reload before generating a summary.",
                data={"code": "summary_stale_analysis"},
            ) from exc
        return result


    async def recover_interrupted_analyses(self) -> int:
        interrupted_count = await ObjectiveRepo.interrupt_active_analyses()
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
        *,
        user_id: str,
    ) -> dict[str, Any]:
        """Confirm, queue, and asynchronously dispatch one canonical analysis."""
        await collection_service.get_collection_for_user(collection_id, user_id)

        payload = await queue_analysis(
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
            task = create_task(coroutine)
        except Exception as exc:  # noqa: BLE001
            coroutine.close()
            logger.exception(
                "Objective analysis dispatch failed collection_id=%s "
                "objective_id=%s analysis_version=%s",
                collection_id,
                objective_id,
                analysis.analysis_version,
            )
            await fail_analysis_dispatch(
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
        task.add_done_callback(_log_unexpected_analysis_failure)
        return payload

    async def execute_queued_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, Any]:
        try:
            objective = await _require_objective(collection_id, objective_id)
            claimed = await ObjectiveRepo.claim_analysis(
                collection_id,
                objective_id,
                analysis_version,
            )
            if claimed is None:
                return await _result(collection_id, objective.objective_id)
            usage_started_at = perf_counter()
            progress_callback = _build_progress_callback(claimed)
            with (
                capture_llm_usage() as usage,
                capture_analysis_diagnostics() as diagnostics,
            ):
                artifacts: ObjectiveExperimentAnalysisArtifacts | None = None
                try:
                    artifacts = await experiment_analysis_service.generate_experiment_analysis_artifacts(
                        collection_id,
                        claimed,
                        progress_callback=progress_callback,
                        response_client=self._get_response_client(),
                        source_screener=self._get_source_screener(),
                        paper_map_extractor=self._get_paper_map_extractor(),
                        paper_experiment_extractor=self._get_paper_experiment_extractor(),
                    )
                    _validate_artifacts(artifacts)
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
                    claimed = await ObjectiveRepo.update_analysis_execution_stats(
                        collection_id,
                        objective_id,
                        analysis_version,
                        stats=usage.execution_stats(
                            duration_ms=round((perf_counter() - usage_started_at) * 1000)
                        ),
                        model_name=(
                            usage.model_name
                            or (artifacts.model_name if artifacts is not None else None)
                            or claimed.model_name
                        ),
                        prompt_versions=usage.prompt_versions,
                        diagnostics=diagnostics.records,
                    )
            async with AsyncSessionLocal() as db, db.begin():
                native_result = await experiment_analysis_writer.write_experiment_analysis(
                    db=db,
                    collection_id=collection_id,
                    objective=objective,
                    analysis=claimed,
                    experiment_outputs=artifacts.experiment_outputs,
                    partial_experiment_outputs=artifacts.partial_experiment_outputs,
                    reused_revisions=artifacts.reused_revisions,
                )
                abstention_reason, abstention_note = _experiment_abstention(native_result)
                objective, completed = await ObjectiveRepo.publish_experiment_analysis(
                    db,
                    collection_id,
                    objective_id,
                    analysis_version,
                    contributions=artifacts.contributions,
                    abstention_reason=abstention_reason,
                    abstention_note=abstention_note,
                )
            return await _result(collection_id, objective.objective_id, analysis=completed)
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
            current = await ObjectiveRepo.read_analysis(
                collection_id,
                objective_id,
                analysis_version,
            )
            if current is not None and current.status in {"queued", "running"}:
                current = await ObjectiveRepo.fail_analysis(
                    collection_id,
                    objective_id,
                    analysis_version,
                    error_code=_error_code(exc),
                    error_message=analysis_error_message(_error_code(exc)),
                )
            return await _result(collection_id, objective_id, analysis=current)

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


async def queue_analysis(
    collection_id: str,
    objective_id: str,
    document_ids: tuple[str, ...],
) -> dict[str, Any]:
    document_inputs = await objective_input_service.resolve_prepared_document_inputs(
        collection_id,
        document_ids,
    )
    objective, analysis = await ObjectiveRepo.queue_analysis(
        collection_id,
        objective_id,
        document_inputs=document_inputs,
        pipeline_version=_PIPELINE_VERSION,
        model_name=None,
        prompt_versions={},
    )
    return await _result(collection_id, objective.objective_id, analysis=analysis)


async def fail_analysis_dispatch(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> dict[str, Any]:
    objective = await _require_objective(collection_id, objective_id)
    analysis = await ObjectiveRepo.fail_analysis(
        collection_id,
        objective_id,
        analysis_version,
        error_code="analysis_dispatch_failed",
        error_message=(
            "Objective analysis could not be scheduled. Retry the analysis."
        ),
        expected_status="queued",
    )
    return await _result(collection_id, objective.objective_id, analysis=analysis)


async def list_objectives(
    collection_id: str, *, user_id: str
) -> tuple[StoredObjective, ...]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    return await ObjectiveRepo.list_objective_records(collection_id)


async def get_analysis_state(
    collection_id: str,
    objective_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    return await _result(collection_id, objective_id)


async def get_analysis_status(
    collection_id: str,
    objective_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Read only the active analysis progress needed for polling."""
    await collection_service.get_collection_for_user(collection_id, user_id)

    objective = await _require_objective(collection_id, objective_id)
    analysis = await ObjectiveRepo.read_analysis(
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
        "completed_at": (
            analysis.completed_at.isoformat() if analysis.completed_at else None
        ),
    }


async def list_findings(
    collection_id: str,
    objective_id: str,
    *,
    user_id: str,
    analysis_version: int | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    version = await _published_version(
        collection_id,
        objective_id,
        analysis_version,
    )
    if await should_read_experiment_projection(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=version,
    ):
        findings, total = await experiment_projection.list_analysis_findings(
            collection_id,
            objective_id,
            version,
            offset=offset,
            limit=limit,
        )
    else:
        findings, total = await ObjectiveRepo.list_findings(
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
        "items": [
            (
                {
                    "collection_id": finding.collection_id,
                    "objective_id": finding.objective_id,
                    "analysis_version": finding.analysis_version,
                    "finding_id": finding.finding_id,
                    "statement": finding.statement,
                    "factors": list(finding.factors),
                    "outcome": finding.outcome,
                    "direction": finding.direction,
                    "assertion_strength": finding.assertion_strength,
                    "attribution_scope": finding.attribution_scope,
                    "synthesis_status": finding.synthesis_status,
                    "certainty": finding.certainty,
                    "display_rank": finding.display_rank,
                    "mechanisms": [
                        {
                            "source_term": mechanism.source_term,
                            "relation_type": mechanism.relation_type,
                            "target_term": mechanism.target_term,
                            "direction": mechanism.direction,
                            "assertion_strength": mechanism.assertion_strength,
                            "supporting_evidence_ids": list(
                                mechanism.supporting_evidence_ids
                            ),
                        }
                        for mechanism in finding.mechanisms
                    ],
                    "scientific_context": {
                        "material": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in finding.scientific_context.material
                        ],
                        "sample": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in finding.scientific_context.sample
                        ],
                        "process": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in finding.scientific_context.process
                        ],
                        "test": [
                            {
                                "name": attribute.name,
                                "value": attribute.value,
                                "unit": attribute.unit,
                                **(
                                    {"context_scope": attribute.context_scope}
                                    if attribute.context_scope != "unknown"
                                    else {}
                                ),
                                **(
                                    {
                                        "applies_to_outcomes": list(
                                            attribute.applies_to_outcomes
                                        )
                                    }
                                    if attribute.applies_to_outcomes
                                    else {}
                                ),
                            }
                            for attribute in finding.scientific_context.test
                        ],
                    },
                    "limitations": list(finding.limitations),
                    "paper_contributions": [
                        {
                            "document_id": contribution.document_id,
                            "analysis_status": contribution.analysis_status,
                            "supporting_evidence_ids": list(
                                contribution.supporting_evidence_ids
                            ),
                            "contradicting_evidence_ids": list(
                                contribution.contradicting_evidence_ids
                            ),
                            "context_evidence_ids": list(
                                contribution.context_evidence_ids
                            ),
                            "condition_boundary_evidence_ids": list(
                                contribution.condition_boundary_evidence_ids
                            ),
                        }
                        for contribution in finding.paper_contributions
                    ],
                    "origin": finding.origin,
                    "source_analysis_version": finding.source_analysis_version,
                    "parent_finding_id": finding.parent_finding_id,
                    "created_by_user_id": finding.created_by_user_id,
                    "created_by_tool_call_id": finding.created_by_tool_call_id,
                    "created_at": (
                        finding.created_at.isoformat() if finding.created_at else None
                    ),
                    **(
                        {"selection_ids": list(finding.selection_ids)}
                        if finding.selection_ids
                        else {}
                    ),
                    **(
                        {"comparison_group_ids": list(finding.comparison_group_ids)}
                        if finding.comparison_group_ids
                        else {}
                    ),
                    **(
                        {"warnings": list(finding.warnings)} if finding.warnings else {}
                    ),
                }
            )
            for finding in findings
        ],
        "evidence_reviews": await _finding_evidence_reviews(
            collection_id, objective_id, version, findings
        ),
        "offset": offset,
        "limit": limit,
        "total": total,
    }


async def get_finding(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    *,
    user_id: str,
    analysis_version: int | None = None,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    version = await _published_version(
        collection_id,
        objective_id,
        analysis_version,
    )
    if await should_read_experiment_projection(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=version,
    ):
        finding = await experiment_projection.read_analysis_finding(
            collection_id,
            objective_id,
            version,
            finding_id,
        )
    else:
        finding = await ObjectiveRepo.read_finding(
            collection_id,
            objective_id,
            version,
            finding_id,
        )
    if finding is None:
        raise ResourceNotFoundException(
            "Published Finding not found.",
            data={
                "code": "finding_not_found",
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": version,
                "finding_id": finding_id,
            },
        )
    return {
        "collection_id": collection_id,
        "objective_id": objective_id,
        "analysis_version": version,
        "finding": (
            {
                "collection_id": finding.collection_id,
                "objective_id": finding.objective_id,
                "analysis_version": finding.analysis_version,
                "finding_id": finding.finding_id,
                "statement": finding.statement,
                "factors": list(finding.factors),
                "outcome": finding.outcome,
                "direction": finding.direction,
                "assertion_strength": finding.assertion_strength,
                "attribution_scope": finding.attribution_scope,
                "synthesis_status": finding.synthesis_status,
                "certainty": finding.certainty,
                "display_rank": finding.display_rank,
                "mechanisms": [
                    {
                        "source_term": mechanism.source_term,
                        "relation_type": mechanism.relation_type,
                        "target_term": mechanism.target_term,
                        "direction": mechanism.direction,
                        "assertion_strength": mechanism.assertion_strength,
                        "supporting_evidence_ids": list(
                            mechanism.supporting_evidence_ids
                        ),
                    }
                    for mechanism in finding.mechanisms
                ],
                "scientific_context": {
                    "material": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in finding.scientific_context.material
                    ],
                    "sample": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in finding.scientific_context.sample
                    ],
                    "process": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in finding.scientific_context.process
                    ],
                    "test": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in finding.scientific_context.test
                    ],
                },
                "limitations": list(finding.limitations),
                "paper_contributions": [
                    {
                        "document_id": contribution.document_id,
                        "analysis_status": contribution.analysis_status,
                        "supporting_evidence_ids": list(
                            contribution.supporting_evidence_ids
                        ),
                        "contradicting_evidence_ids": list(
                            contribution.contradicting_evidence_ids
                        ),
                        "context_evidence_ids": list(contribution.context_evidence_ids),
                        "condition_boundary_evidence_ids": list(
                            contribution.condition_boundary_evidence_ids
                        ),
                    }
                    for contribution in finding.paper_contributions
                ],
                "origin": finding.origin,
                "source_analysis_version": finding.source_analysis_version,
                "parent_finding_id": finding.parent_finding_id,
                "created_by_user_id": finding.created_by_user_id,
                "created_by_tool_call_id": finding.created_by_tool_call_id,
                "created_at": (
                    finding.created_at.isoformat() if finding.created_at else None
                ),
                **(
                    {"selection_ids": list(finding.selection_ids)}
                    if finding.selection_ids
                    else {}
                ),
                **(
                    {"comparison_group_ids": list(finding.comparison_group_ids)}
                    if finding.comparison_group_ids
                    else {}
                ),
                **({"warnings": list(finding.warnings)} if finding.warnings else {}),
            }
        ),
        "evidence_review": (
            await _finding_evidence_reviews(
                collection_id, objective_id, version, (finding,)
            )
        )[finding.finding_id],
    }


async def _finding_evidence_reviews(
    collection_id: str,
    objective_id: str,
    version: int,
    findings: tuple[Finding, ...],
) -> dict[str, Any]:
    if not findings:
        return {}
    evidence = await _all_published_evidence(
        collection_id, objective_id, version,
        experiment_backed=await should_read_experiment_projection(
            collection_id=collection_id, objective_id=objective_id, analysis_version=version,
        ),
    )
    evidence_by_id = {
        item.evidence_id: item for item in evidence
    }
    reviews = {}
    for finding in findings:
        finding_id = finding.finding_id
        replacements = finding.evidence_replacements(evidence_by_id)
        reviews[finding_id] = {
            "needs_review": bool(replacements),
            "evidence_replacements": replacements,
        }
    return reviews



async def list_evidence(
    collection_id: str,
    objective_id: str,
    *,
    user_id: str,
    analysis_version: int | None = None,
    finding_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    version = await _published_version(
        collection_id,
        objective_id,
        analysis_version,
    )
    experiment_backed = await should_read_experiment_projection(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=version,
    )
    if experiment_backed:
        evidence, total = await experiment_projection.list_analysis_evidence(
            collection_id,
            objective_id,
            version,
            finding_id=finding_id,
            offset=offset,
            limit=limit,
        )
    else:
        evidence, total = await ObjectiveRepo.list_evidence(
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
            {
                **(
                    {
                        "collection_id": item.collection_id,
                        "objective_id": item.objective_id,
                        "analysis_version": item.analysis_version,
                        "evidence_id": item.evidence_id,
                        "document_id": item.document_id,
                        "source_kind": item.source_kind,
                        "source_ref": item.source_ref,
                        "source_excerpt": item.source_excerpt,
                        "page_numbers": list(item.page_numbers),
                        "evidence_role": item.evidence_role,
                        "selection_status": item.selection_status,
                        "selection_reason": item.selection_reason,
                        "evidence_status": (
                            experiment_evidence_disposition(item)[0]
                            if experiment_backed else item.evidence_status
                        ),
                        "evidence_status_reason": (
                            experiment_evidence_disposition(item)[1]
                            if experiment_backed else item.evidence_status_reason
                        ),
                        "changed_variables": [
                            {
                                "name": variable.name,
                                "baseline_value": variable.baseline_value,
                                "target_value": variable.target_value,
                                "unit": variable.unit,
                            }
                            for variable in item.changed_variables
                        ],
                        "comparison": (
                            {
                                "baseline_label": item.comparison.baseline_label,
                                "target_label": item.comparison.target_label,
                                "axis_names": list(item.comparison.axis_names),
                                "comparable": item.comparison.comparable,
                                "incomparability_reasons": list(
                                    item.comparison.incomparability_reasons
                                ),
                            }
                            if item.comparison
                            else None
                        ),
                        "reported_result": (
                            {
                                "outcome": item.reported_result.outcome,
                                "value": item.reported_result.value,
                                "baseline_value": item.reported_result.baseline_value,
                                "target_value": item.reported_result.target_value,
                                "unit": item.reported_result.unit,
                                "direction": item.reported_result.direction,
                                "result_text": item.reported_result.result_text,
                                "result_kind": item.reported_result.result_kind,
                            }
                            if item.reported_result
                            else None
                        ),
                        "attribution_scope": item.attribution_scope,
                        "scientific_context": {
                            "material": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.material
                            ],
                            "sample": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.sample
                            ],
                            "process": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.process
                            ],
                            "test": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in item.scientific_context.test
                            ],
                        },
                        "resolution_status": item.resolution_status,
                        "failure_reason": item.failure_reason,
                        "confidence": item.confidence,
                        "origin": item.origin,
                        "source_analysis_version": item.source_analysis_version,
                        "supersedes_evidence_id": item.supersedes_evidence_id,
                        "superseded_by_evidence_id": item.superseded_by_evidence_id,
                        "created_by_user_id": item.created_by_user_id,
                        "created_by_tool_call_id": item.created_by_tool_call_id,
                        "created_at": (
                            item.created_at.isoformat()
                            if item.created_at is not None
                            else None
                        ),
                        "authoring_note": item.authoring_note,
                        **({"warnings": list(item.warnings)} if experiment_backed else {}),
                        **({"warnings": list(item.warnings)} if item.warnings else {}),
                        **(
                            {
                                "related_source_refs": [
                                    dict(item) for item in item.related_source_refs
                                ]
                            }
                            if item.related_source_refs
                            or item.related_source_refs_explicit
                            else {}
                        ),
                    }
                ),
                "supports_finding": (
                    item.comparison is None or item.comparison.comparable
                    if experiment_backed else item.supports_finding
                ),
                "eligible_for_finding_authoring": (
                    item.comparison is None or item.comparison.comparable
                    if experiment_backed else item.eligible_for_finding_authoring
                ),
            }
            for item in evidence
        ],
        "offset": offset,
        "limit": limit,
        "total": total,
    }


async def get_evidence_map(
    collection_id: str,
    objective_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    objective = await _require_objective(collection_id, objective_id)
    version = await _published_version(collection_id, objective_id, None)
    analysis = await ObjectiveRepo.read_published_analysis(
        collection_id,
        objective_id,
    )
    if analysis is None:
        raise ResourceConflictException(
            "Objective has no published analysis.",
            data={"code": "objective_analysis_not_published"},
        )

    findings = await _all_published_findings(
        collection_id,
        objective_id,
        version,
        experiment_backed=is_experiment_backed_analysis(analysis),
    )
    evidence_records = await _all_published_evidence(
        collection_id,
        objective_id,
        version,
        experiment_backed=is_experiment_backed_analysis(analysis),
    )
    profiles = await document_profile_service.read_document_profiles(
        collection_id,
        tuple(item.document_id for item in analysis.document_inputs),
    )
    if is_experiment_backed_analysis(analysis):
        return await experiment_projection.build_evidence_map(
            objective=objective,
            analysis=analysis,
            profiles=profiles,
        )
    return build_objective_evidence_map(
        objective=objective,
        analysis=analysis,
        contributions=await ObjectiveRepo.list_contributions(
            collection_id,
            objective_id,
            version,
        ),
        findings=findings,
        evidence_records=evidence_records,
        profiles=profiles,
    )


async def _all_published_findings(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    experiment_backed: bool,
) -> tuple[Finding, ...]:
    if experiment_backed:
        findings, _ = await experiment_projection.list_analysis_findings(
            collection_id,
            objective_id,
            analysis_version,
            offset=0,
            limit=200,
        )
        return tuple(findings)
    records: list[Any] = []
    offset = 0
    while True:
        page, total = await ObjectiveRepo.list_findings(
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
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    experiment_backed: bool,
) -> tuple[ObjectiveEvidence, ...]:
    if experiment_backed:
        evidence, _ = await experiment_projection.list_analysis_evidence(
            collection_id,
            objective_id,
            analysis_version,
            offset=0,
            limit=500,
        )
        return tuple(evidence)
    records: list[Any] = []
    offset = 0
    while True:
        page, total = await ObjectiveRepo.list_evidence(
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


def _log_unexpected_analysis_failure(task: Task[dict[str, Any]]) -> None:
    try:
        task.result()
    except CancelledError:
        logger.info("Objective analysis task cancelled during backend shutdown")
    except Exception:  # noqa: BLE001
        logger.exception("Objective analysis crashed after service scheduling")


def _validate_artifacts(
    artifacts: ObjectiveExperimentAnalysisArtifacts,
) -> None:
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
        raise RuntimeError("objective analysis failed to extract every relevant paper")


async def _result(
    collection_id: str,
    objective_id: str,
    *,
    analysis: ObjectiveAnalysis | None = None,
) -> dict[str, Any]:
    stored_objective = await ObjectiveRepo.read_objective_record(
        collection_id, objective_id
    )
    if stored_objective is None:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)
    objective = stored_objective.objective
    active = analysis
    if active is None and objective.active_analysis_version is not None:
        active = await ObjectiveRepo.read_analysis(
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
            published = await ObjectiveRepo.read_analysis(
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
        if is_experiment_backed_analysis(published):
            paper_contributions = tuple(
                {
                    **asdict(item),
                    "evidence_status_counts": dict(item.evidence_status_counts),
                }
                for item in await experiment_projection.list_analysis_contributions(
                    collection_id, objective.objective_id, published.analysis_version,
                )
            )
            findings, finding_total = (
                await experiment_projection.list_analysis_findings(
                    collection_id,
                    objective.objective_id,
                    published.analysis_version,
                    offset=0,
                    limit=50,
                )
            )
            evidence_records = await _all_published_evidence(
                collection_id,
                objective.objective_id,
                published.analysis_version,
                experiment_backed=True,
            )
        else:
            contributions = await ObjectiveRepo.list_contributions(
                collection_id,
                objective.objective_id,
                published.analysis_version,
            )
            paper_contributions = tuple(
                {
                    **asdict(item),
                    "evidence_status_counts": dict(item.evidence_status_counts),
                }
                for item in contributions
            )
            findings, finding_total = await ObjectiveRepo.list_findings(
                collection_id,
                objective.objective_id,
                published.analysis_version,
                offset=0,
                limit=50,
            )
            evidence_records = await _all_published_evidence(
                collection_id,
                objective.objective_id,
                published.analysis_version,
                experiment_backed=False,
            )
        seen_warnings: set[str] = set()
        for contribution in paper_contributions:
            document_id = contribution["document_id"]
            for warning in contribution["warnings"]:
                scoped_warning = f"{document_id}: {warning}"
                if scoped_warning in seen_warnings:
                    continue
                seen_warnings.add(scoped_warning)
                warnings.append(scoped_warning)
            for status, count in contribution["evidence_status_counts"].items():
                if status == "comparable" or count <= 0:
                    continue
                scoped_status = (
                    f"{document_id}: {count} Evidence item(s) "
                    f"classified as {status}."
                )
                if scoped_status in seen_warnings:
                    continue
                seen_warnings.add(scoped_status)
                warnings.append(scoped_status)
        for evidence in evidence_records:
            for warning in evidence.warnings:
                scoped_warning = (
                    f"{evidence.document_id}/"
                    f"{evidence.source_ref}: {warning}"
                )
                if scoped_warning in seen_warnings:
                    continue
                seen_warnings.add(scoped_warning)
                warnings.append(scoped_warning)
        for finding in findings:
            for warning in finding.warnings:
                scoped_warning = (
                    f"Finding {finding.finding_id}: {warning}"
                )
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
        "evidence_review": _evidence_review_summary(
            evidence_records, experiment_backed=is_experiment_backed_analysis(published),
        ),
        "warnings": warnings,
    }


async def _require_objective(
    collection_id: str,
    objective_id: str,
) -> ResearchObjective:
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    if objective is None:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)
    return objective


async def _published_version(
    collection_id: str,
    objective_id: str,
    requested_version: int | None,
) -> int:
    objective = await _require_objective(collection_id, objective_id)
    published_version = objective.published_analysis_version
    if published_version is None:
        raise ResourceConflictException(
            "Objective has no published analysis.",
            data={"code": "objective_analysis_not_published"},
        )
    if requested_version is not None and requested_version != published_version:
        raise ResourceConflictException(
            "Requested analysis version is not published.",
            data={
                "code": "analysis_version_not_published",
                "analysis_version": requested_version,
                "published_analysis_version": published_version,
            },
        )
    return published_version


def _build_progress_callback(
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
            await ObjectiveRepo.update_analysis_progress(
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


def _error_code(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "provider_timeout"
    if isinstance(exc, ValueError):
        return "invalid_analysis_artifact"
    return "objective_analysis_failed"


__all__ = [
    "ObjectiveAnalysisDispatchError",
    "ObjectiveAnalysisService",
    "queue_analysis",
    "fail_analysis_dispatch",
    "get_analysis_state",
    "get_analysis_status",
    "list_objectives",
    "list_findings",
    "get_finding",
    "list_evidence",
    "get_evidence_map",
]
