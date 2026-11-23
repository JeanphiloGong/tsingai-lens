from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


TaskStatus = Literal[
    "accepted",
    "running",
    "approval_required",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
]


class TaskAcceptedResponse(BaseModel):
    task_id: str
    trigger_message_id: str
    status: Literal["accepted"]


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    conversation_id: str
    trigger_message_id: str | None
    final_message_id: str | None
    status: TaskStatus
    checkpoint_revision: int
    active_operation_id: str | None
    started_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    limit: int
    offset: int


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_checkpoint_revision: int = Field(ge=0, strict=True)


class OperationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    decision: Literal["approved", "rejected"]
    arguments_digest: str = Field(min_length=64, max_length=64)


class TaskActionResponse(BaseModel):
    task_id: str
    status: Literal["accepted", "interrupted"]


class OperationDecisionResponse(BaseModel):
    operation_id: str
    task_id: str
    status: Literal["approved", "rejected"]


__all__ = [
    "OperationDecisionRequest",
    "OperationDecisionResponse",
    "ResumeRequest",
    "StopRequest",
    "TaskAcceptedResponse",
    "TaskActionResponse",
    "TaskListResponse",
    "TaskResponse",
    "TaskStatus",
]
