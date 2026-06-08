from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from starlette.concurrency import run_in_threadpool

from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveNotFoundError,
    ResearchObjectiveReportNotFoundError,
    ResearchObjectiveService,
    ResearchObjectivesNotReadyError,
)
from controllers.schemas.core.research_objectives import (
    ObjectiveListResponse,
    ObjectiveReportRequest,
    ObjectiveReportResponse,
    ObjectiveResearchViewResponse,
)

router = APIRouter(prefix="/collections", tags=["research-objectives"])
research_objective_service = ResearchObjectiveService()


def _research_objectives_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "research_objectives_not_ready",
        "message": (
            "The collection does not have research objectives yet. Finish "
            "processing first."
        ),
        "collection_id": collection_id,
    }


def _research_objective_report_not_found_detail(
    exc: ResearchObjectiveReportNotFoundError,
) -> dict[str, str]:
    return {
        "code": "research_objective_report_not_found",
        "message": str(exc),
        "collection_id": exc.collection_id,
        "objective_id": exc.objective_id,
    }


def _generate_objective_report_background(
    collection_id: str,
    objective_id: str,
    request: ObjectiveReportRequest,
) -> None:
    research_objective_service.generate_objective_report(
        collection_id,
        objective_id,
        language=request.language,
        force_regenerate=False,
    )


@router.get(
    "/{collection_id}/objectives",
    response_model=ObjectiveListResponse,
    summary="读取 collection research objectives",
)
async def list_collection_objectives(collection_id: str) -> ObjectiveListResponse:
    try:
        payload = await run_in_threadpool(
            research_objective_service.list_objective_workspaces,
            collection_id,
        )
    except ResearchObjectivesNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_objectives_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ObjectiveListResponse(**payload)


@router.get(
    "/{collection_id}/objectives/{objective_id}/research-view",
    response_model=ObjectiveResearchViewResponse,
    summary="读取 objective research view",
)
async def get_collection_objective_research_view(
    collection_id: str,
    objective_id: str,
) -> ObjectiveResearchViewResponse:
    try:
        payload = await run_in_threadpool(
            research_objective_service.get_objective_research_view,
            collection_id,
            objective_id,
        )
    except ResearchObjectiveNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "research_objective_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "objective_id": exc.objective_id,
            },
        ) from exc
    except ResearchObjectivesNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_objectives_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ObjectiveResearchViewResponse(**payload)


@router.post(
    "/{collection_id}/objectives/{objective_id}/report",
    response_model=ObjectiveReportResponse,
    summary="生成 objective 科研报告",
)
async def create_collection_objective_report(
    collection_id: str,
    objective_id: str,
    request: ObjectiveReportRequest,
    background_tasks: BackgroundTasks,
) -> ObjectiveReportResponse:
    try:
        payload = await run_in_threadpool(
            research_objective_service.request_objective_report,
            collection_id,
            objective_id,
            language=request.language,
            force_regenerate=request.force_regenerate,
        )
    except ResearchObjectiveNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "research_objective_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "objective_id": exc.objective_id,
            },
        ) from exc
    except ResearchObjectivesNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_objectives_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.get("status") == "generating":
        background_tasks.add_task(
            _generate_objective_report_background,
            collection_id,
            objective_id,
            request,
        )
    return ObjectiveReportResponse(**payload)


@router.get(
    "/{collection_id}/objectives/{objective_id}/report",
    response_model=ObjectiveReportResponse,
    summary="读取 objective 科研报告状态",
)
async def get_collection_objective_report(
    collection_id: str,
    objective_id: str,
) -> ObjectiveReportResponse:
    try:
        payload = await run_in_threadpool(
            research_objective_service.get_objective_report_status,
            collection_id,
            objective_id,
        )
    except ResearchObjectiveReportNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_research_objective_report_not_found_detail(exc),
        ) from exc
    return ObjectiveReportResponse(**payload)
