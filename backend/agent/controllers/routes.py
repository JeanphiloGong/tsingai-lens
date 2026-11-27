from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Annotated

import anyio
from agent.application.task_execution import task_execution
from agent.application.execution_events import operation_activity
from agent.domain.models import Operation
from conversation.controllers.schemas import citation_response
from conversation.repositories.conversation_repository import ConversationRepository

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
    user_id: CurrentUserId,
    after_revision: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    snapshot = await service.read_task(
        conversation_id=conversation_id,
        task_id=task_id,
        user_id=user_id,
        include_operations=True,
    )
    activities = []
    for record in snapshot["operations"]:
        operation = Operation(**record)
        activities.append({
            "operation_id": operation.operation_id, "name": operation.name,
            "status": operation.status,
            **(operation_activity(operation) if operation.result else {}),
        })

    def frame(event):
        return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def body():
        yield frame({
            "event": "task.snapshot", "task_id": task_id, "status": snapshot["status"],
            "checkpoint_revision": snapshot["checkpoint_revision"],
            "final_message_id": snapshot["final_message_id"], "operations": activities,
        })
        if snapshot["status"] not in {"accepted", "running"}:
            return

        # A zero-capacity handoff applies socket backpressure to this request's runner.
        sender, receiver = anyio.create_memory_object_stream(0)
        citations = None

        async def emit(event):
            nonlocal citations
            if event["event"] == "message.citation":
                if citations is None:
                    path = await ConversationRepository().read_current_path(
                        conversation_id=conversation_id, user_id=user_id
                    )
                    citations = {
                        (item.message.message_id, c.document_id, c.source_ref, c.offset):
                            citation_response(c, workspace_id=path.conversation.workspace_id).source.model_dump()
                        for item in path.items for c in item.message.citations
                    }
                source = event["source"]
                visible = citations.get((event["message_id"], source["document_id"], source["source_ref"], event["offset"]))
                if visible is None:
                    return
                event = {**event, "source": visible}
            await sender.send(frame(event))

        async def execute():
            async with sender:
                try:
                    await task_execution.run_task(
                        conversation_id=conversation_id, task_id=task_id, user_id=user_id, emit=emit
                    )
                except (TaskBusyError, CheckpointConflict):
                    # Another subscriber owns execution, or a stop advanced its revision.
                    return

        execution = asyncio.create_task(execute())
        try:
            async with receiver:
                async for chunk in receiver:
                    yield chunk
            await execution
        finally:
            execution.cancel()
            with suppress(asyncio.CancelledError):
                await execution

    return StreamingResponse(
        body(),
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
