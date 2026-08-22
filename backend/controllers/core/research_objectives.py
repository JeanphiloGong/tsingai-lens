from __future__ import annotations

from asyncio import CancelledError, Semaphore, Task, create_task, to_thread
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from controllers.schemas.core.research_objectives import (
    FindingDetailResponse,
    FindingListResponse,
    ObjectiveAnalysisResponse,
    ObjectiveEvidenceListResponse,
    ObjectiveEvidenceMapResponse,
    PaginatedObjectiveListResponse,
    PaperStudyInventoryResponse,
)


router = APIRouter(prefix="/collections", tags=["research-objectives"])
logger = logging.getLogger(__name__)
_OBJECTIVE_ANALYSIS_MAX_CONCURRENCY = 4


@router.get(
    "/{collection_id}/objectives",
    response_model=PaginatedObjectiveListResponse,
    summary="List collection research objectives",
)
async def list_collection_objectives(
    collection_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> PaginatedObjectiveListResponse:
    try:
        objectives = await run_in_threadpool(
            request.app.state.objective_repository.list_objectives,
            collection_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ranked_objectives = [objective.to_record() for objective in objectives]
    page = (
        ranked_objectives[offset:]
        if limit is None
        else ranked_objectives[offset : offset + limit]
    )
    return PaginatedObjectiveListResponse(
        collection_id=collection_id,
        objectives=page,
        offset=offset,
        limit=limit,
        total=len(ranked_objectives),
    )


@router.get(
    "/{collection_id}/paper-study-inventory",
    response_model=PaperStudyInventoryResponse,
    summary="List the persisted paper study inventory",
)
async def list_paper_study_inventory(
    collection_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PaperStudyInventoryResponse:
    try:
        facts = await run_in_threadpool(
            request.app.state.objective_repository.read,
            collection_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    items: list[dict] = []
    coverage_counts = {
        "relationship_emitted": 0,
        "unresolved_signal_emitted": 0,
        "no_study_signal": 0,
        "extraction_failed": 0,
    }
    dispositions = {
        (item.document_id, item.study_id, item.relationship_id): item
        for item in facts.study_dispositions
    }
    for skim in facts.paper_skims:
        for study in skim.studies:
            study_record = study.to_record()
            study_record["relationships"] = []
            for relationship in study.relationships:
                disposition = dispositions.get(
                    (
                        skim.document_id,
                        study.study_id,
                        relationship.relationship_id,
                    )
                )
                relationship_record = relationship.to_record()
                relationship_record["disposition"] = {
                    "status": (
                        disposition.status.value
                        if disposition is not None
                        else "pending"
                    ),
                    "objective_id": (
                        disposition.objective_id
                        if disposition is not None
                        else None
                    ),
                    "reason": disposition.reason if disposition is not None else None,
                }
                study_record["relationships"].append(relationship_record)
            items.append(
                {
                    "item_type": "paper_study",
                    "doc_role": skim.doc_role,
                    **study_record,
                }
            )
        for signal in skim.unresolved_signals:
            items.append(
                {
                    "item_type": "unresolved_signal",
                    "document_id": skim.document_id,
                    "doc_role": skim.doc_role,
                    **signal.to_record(),
                }
            )
        for coverage in skim.source_unit_coverage:
            coverage_counts[coverage.status.value] += 1
            items.append(
                {
                    "item_type": "source_unit_coverage",
                    "document_id": skim.document_id,
                    "doc_role": skim.doc_role,
                    **coverage.to_record(),
                }
            )

    return PaperStudyInventoryResponse(
        collection_id=collection_id,
        research_objectives_ready=facts.research_objectives_ready,
        coverage_complete=coverage_counts["extraction_failed"] == 0,
        source_unit_coverage_counts=coverage_counts,
        items=items[offset : offset + limit],
        offset=offset,
        limit=limit,
        total=len(items),
    )


@router.get(
    "/{collection_id}/objectives/{objective_id}",
    response_model=ObjectiveAnalysisResponse,
    summary="Read a research objective",
)
async def get_collection_objective(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    return await _read_objective_analysis_response(
        collection_id, objective_id, request
    )


@router.post(
    "/{collection_id}/objectives/{objective_id}/confirm",
    response_model=ObjectiveAnalysisResponse,
    summary="Confirm a research objective",
)
async def confirm_collection_objective(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.confirm_objective,
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_objective_analysis_response(payload)


@router.post(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ObjectiveAnalysisResponse,
    summary="Start a research objective analysis",
    name="run_collection_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def start_collection_objective_analysis(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    service = request.app.state.objective_analysis_service
    try:
        payload = await run_in_threadpool(
            service.queue_analysis,
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    analysis = payload.get("analysis")
    if analysis is not None and analysis.status == "queued":
        semaphore = getattr(
            request.app.state,
            "objective_analysis_semaphore",
            None,
        )
        if semaphore is None:
            semaphore = Semaphore(_OBJECTIVE_ANALYSIS_MAX_CONCURRENCY)
            request.app.state.objective_analysis_semaphore = semaphore
        coroutine = _execute_queued_analysis(
            semaphore,
            service,
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
            await run_in_threadpool(
                service.fail_analysis_dispatch,
                collection_id,
                objective_id,
                analysis.analysis_version,
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "objective_analysis_dispatch_failed",
                    "message": (
                        "Objective analysis could not be scheduled. "
                        "Retry the analysis."
                    ),
                    "collection_id": collection_id,
                    "objective_id": objective_id,
                    "analysis_version": analysis.analysis_version,
                },
            ) from exc
        # Keep strong references until asyncio has delivered each task callback.
        tasks = getattr(request.app.state, "objective_analysis_tasks", None)
        if tasks is None:
            tasks = set()
            request.app.state.objective_analysis_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        task.add_done_callback(_log_unexpected_analysis_failure)
    return _to_objective_analysis_response(payload)


@router.get(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ObjectiveAnalysisResponse,
    summary="Read research objective analysis state",
    name="get_collection_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def get_collection_objective_analysis_state(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    return await _read_objective_analysis_response(
        collection_id, objective_id, request
    )


@router.get(
    "/{collection_id}/objectives/{objective_id}/findings",
    response_model=FindingListResponse,
    summary="List published findings",
)
async def list_objective_findings(
    collection_id: str,
    objective_id: str,
    request: Request,
    analysis_version: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> FindingListResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.list_findings,
            collection_id,
            objective_id,
            analysis_version=analysis_version,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingListResponse(**payload)


@router.get(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}",
    response_model=FindingDetailResponse,
    summary="Read one published finding",
)
async def get_objective_finding(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    request: Request,
    analysis_version: int | None = Query(default=None, ge=1),
) -> FindingDetailResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.get_finding,
            collection_id,
            objective_id,
            finding_id,
            analysis_version=analysis_version,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingDetailResponse(**payload)


@router.get(
    "/{collection_id}/objectives/{objective_id}/evidence",
    response_model=ObjectiveEvidenceListResponse,
    summary="List published objective evidence",
)
async def list_objective_evidence(
    collection_id: str,
    objective_id: str,
    request: Request,
    analysis_version: int | None = Query(default=None, ge=1),
    finding_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> ObjectiveEvidenceListResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.list_evidence,
            collection_id,
            objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ObjectiveEvidenceListResponse(**payload)


@router.get(
    "/{collection_id}/objectives/{objective_id}/evidence-map",
    response_model=ObjectiveEvidenceMapResponse,
    summary="Read the published Objective evidence map",
)
async def get_objective_evidence_map(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveEvidenceMapResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.get_evidence_map,
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ObjectiveEvidenceMapResponse(**payload)


async def _read_objective_analysis_response(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.get_analysis_state,
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    return _to_objective_analysis_response(payload)


def _to_objective_analysis_response(payload: dict) -> ObjectiveAnalysisResponse:
    objective = payload["objective"]
    active = payload.get("analysis")
    published = payload.get("published_analysis")
    return ObjectiveAnalysisResponse(
        collection_id=payload["collection_id"],
        objective=objective.to_record(),
        active_analysis=active.to_record() if active is not None else None,
        published_analysis=(published.to_record() if published is not None else None),
        paper_contributions=[
            item.to_record() for item in payload.get("paper_contributions") or ()
        ],
        warnings=payload.get("warnings") or [],
    )


def _objective_not_found(
    collection_id: str,
    objective_id: str,
    exc: Exception,
) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "research_objective_not_found",
            "message": str(exc),
            "collection_id": collection_id,
            "objective_id": objective_id,
        },
    )


async def _execute_queued_analysis(
    semaphore: Semaphore,
    service: Any,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> dict[str, Any]:
    async with semaphore:
        return await to_thread(
            service.execute_queued_analysis,
            collection_id,
            objective_id,
            analysis_version,
        )


def _log_unexpected_analysis_failure(task: Task[dict[str, Any]]) -> None:
    try:
        task.result()
    except CancelledError:
        logger.info("Objective analysis task cancelled during backend shutdown")
    except Exception:  # noqa: BLE001
        logger.exception("Objective analysis crashed after route scheduling")
