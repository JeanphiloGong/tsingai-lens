from __future__ import annotations

from typing import Annotated

from agent.application.task_service import TaskService
from agent.controllers.schemas import (
    OperationDecisionRequest,
    OperationDecisionResponse,
    ResumeRequest,
    StopRequest,
    TaskActionResponse,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
)
from agent.repositories.task_repository import (
    CheckpointConflict,
    OperationDecisionConflict,
    TaskBusyError,
    TaskNotFound,
    TaskRepository,
    TaskResumeConflict,
)
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from utils.response import ApiResponse


agent_router = APIRouter(
    prefix="/conversations/{conversation_id}/tasks", tags=["agent"]
)
service = TaskService(TaskRepository())
CurrentUserId = Annotated[str, Depends(get_current_user_id)]


async def task_error_handler(
    _request: Request,
    exc: TaskNotFound
    | CheckpointConflict
    | OperationDecisionConflict
    | TaskResumeConflict
    | TaskBusyError,
) -> JSONResponse:
    if isinstance(exc, TaskNotFound):
        status = 404
        error_code = "task_not_found"
    elif isinstance(exc, CheckpointConflict):
        status = 409
        error_code = "checkpoint_conflict"
    elif isinstance(exc, OperationDecisionConflict):
        status = 409
        error_code = "operation_decision_conflict"
    elif isinstance(exc, TaskResumeConflict):
        status = 409
        error_code = "task_not_resumable"
    else:
        status = 409
        error_code = "task_busy"
    return JSONResponse(
        status_code=status,
        content={
            "code": status,
            "message": str(exc),
            "data": None,
            "meta": {"error_code": error_code},
        },
    )


@agent_router.get("/{task_id}", response_model=ApiResponse[TaskResponse])
async def get_task(
    conversation_id: str,
    task_id: str,
    user_id: CurrentUserId,
) -> ApiResponse[TaskResponse]:
    task = await service.read_task(
        conversation_id=conversation_id,
        task_id=task_id,
        user_id=user_id,
    )
    return ApiResponse(data=TaskResponse.model_validate(task))


@agent_router.get("", response_model=ApiResponse[TaskListResponse])
async def list_tasks(
    conversation_id: str,
    user_id: CurrentUserId,
    status: Annotated[TaskStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[TaskListResponse]:
    tasks = await service.list_tasks(
        conversation_id=conversation_id,
        user_id=user_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ApiResponse(
        data=TaskListResponse(
            items=[TaskResponse.model_validate(task) for task in tasks],
            limit=limit,
            offset=offset,
        )
    )


@agent_router.get("/{task_id}/events")
async def task_events(
    conversation_id: str,
    task_id: str,
    after_revision: Annotated[int, Query(ge=0)] = 0,
    user_id: CurrentUserId = None,
) -> StreamingResponse:
    return StreamingResponse(
        service.events(
            conversation_id=conversation_id,
            task_id=task_id,
            user_id=user_id,
            after_revision=after_revision,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agent_router.post(
    "/{task_id}/stop",
    response_model=ApiResponse[TaskActionResponse],
)
async def stop_task(
    conversation_id: str,
    task_id: str,
    payload: StopRequest,
    user_id: CurrentUserId,
) -> ApiResponse[TaskActionResponse]:
    await service.stop(
        conversation_id=conversation_id,
        task_id=task_id,
        user_id=user_id,
        request_id=str(payload.request_id),
    )
    return ApiResponse(
        data=TaskActionResponse(task_id=task_id, status="interrupted")
    )


@agent_router.post(
    "/{task_id}/resume",
    response_model=ApiResponse[TaskActionResponse],
)
async def resume_task(
    conversation_id: str,
    task_id: str,
    payload: ResumeRequest,
    user_id: CurrentUserId,
) -> ApiResponse[TaskActionResponse]:
    await service.resume(
        conversation_id=conversation_id,
        task_id=task_id,
        user_id=user_id,
        request_id=str(payload.request_id),
        expected_checkpoint_revision=payload.expected_checkpoint_revision,
    )
    return ApiResponse(data=TaskActionResponse(task_id=task_id, status="accepted"))


@agent_router.post(
    "/{task_id}/operations/{operation_id}/decision",
    response_model=ApiResponse[OperationDecisionResponse],
)
async def decide_operation(
    conversation_id: str,
    task_id: str,
    operation_id: str,
    payload: OperationDecisionRequest,
    user_id: CurrentUserId,
) -> ApiResponse[OperationDecisionResponse]:
    await service.decide(
        conversation_id=conversation_id,
        task_id=task_id,
        operation_id=operation_id,
        user_id=user_id,
        decision=payload.decision,
        arguments_digest=payload.arguments_digest,
        request_id=str(payload.request_id),
    )
    return ApiResponse(
        data=OperationDecisionResponse(
            operation_id=operation_id,
            task_id=task_id,
            status=payload.decision,
        )
    )


__all__ = ["agent_router", "service", "task_error_handler"]
