from __future__ import annotations

from fastapi import APIRouter, HTTPException

from application.goal.session_service import (
    GoalSessionNotFoundError,
    GoalSessionService,
)
from controllers.schemas.goal.session import (
    GoalSessionCreateRequest,
    GoalSessionMessageListResponse,
    GoalSessionMessageRequest,
    GoalSessionMessageResponse,
    GoalSessionResponse,
    GoalSessionUpdateRequest,
)

router = APIRouter(prefix="/goal-sessions", tags=["goal-sessions"])
goal_session_service = GoalSessionService()


def _not_found_detail(exc: GoalSessionNotFoundError) -> dict[str, str]:
    return {
        "code": "goal_session_not_found",
        "message": str(exc),
        "session_id": exc.session_id,
    }


@router.post(
    "",
    response_model=GoalSessionResponse,
    summary="Create a collection-bound goal session",
)
async def create_goal_session(payload: GoalSessionCreateRequest) -> GoalSessionResponse:
    try:
        session = goal_session_service.create_session(
            collection_id=payload.collection_id,
            focused_material_id=payload.focused_material_id,
            focused_paper_id=payload.focused_paper_id,
            focused_objective_id=payload.focused_objective_id,
            goal_text=payload.goal_text,
            goal_brief_json=payload.goal_brief_json,
            answer_mode=payload.answer_mode,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoalSessionResponse(**session)


@router.get(
    "/{session_id}",
    response_model=GoalSessionResponse,
    summary="Read a collection-bound goal session",
)
async def get_goal_session(session_id: str) -> GoalSessionResponse:
    try:
        session = goal_session_service.get_session(session_id)
    except GoalSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_not_found_detail(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GoalSessionResponse(**session)


@router.patch(
    "/{session_id}",
    response_model=GoalSessionResponse,
    summary="Update explicit goal session context",
)
async def update_goal_session(
    session_id: str,
    payload: GoalSessionUpdateRequest,
) -> GoalSessionResponse:
    try:
        session = goal_session_service.update_session(
            session_id,
            **payload.model_dump(exclude_unset=True),
        )
    except GoalSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_not_found_detail(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoalSessionResponse(**session)


@router.post(
    "/{session_id}/messages",
    response_model=GoalSessionMessageResponse,
    summary="Post a message into a goal session",
)
async def post_goal_session_message(
    session_id: str,
    payload: GoalSessionMessageRequest,
) -> GoalSessionMessageResponse:
    try:
        response = goal_session_service.post_message(
            session_id,
            message=payload.message,
            page_context=payload.page_context,
        )
    except GoalSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_not_found_detail(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoalSessionMessageResponse(**response)


@router.get(
    "/{session_id}/messages",
    response_model=GoalSessionMessageListResponse,
    summary="List goal session messages",
)
async def list_goal_session_messages(session_id: str) -> GoalSessionMessageListResponse:
    try:
        response = goal_session_service.list_messages(session_id)
    except GoalSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_not_found_detail(exc)) from exc
    return GoalSessionMessageListResponse(**response)
