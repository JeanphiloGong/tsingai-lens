from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveNotFoundError,
    ResearchObjectivesNotReadyError,
)
from controllers.schemas.core.research_objectives import (
    ObjectiveListResponse,
    ObjectiveResearchViewResponse,
)

router = APIRouter(prefix="/collections", tags=["research-objectives"])


def _research_objectives_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "research_objectives_not_ready",
        "message": (
            "The collection does not have research objectives yet. Finish "
            "processing first."
        ),
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/objectives",
    response_model=ObjectiveListResponse,
    summary="读取 collection research objectives",
)
async def list_collection_objectives(
    collection_id: str,
    request: Request,
) -> ObjectiveListResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.research_objective_service.list_objective_workspaces,
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
    request: Request,
) -> ObjectiveResearchViewResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.research_objective_service.get_objective_research_view,
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
