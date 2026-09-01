"""Public schemas for durable Research Agent Chat trajectories."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1, max_length=64)


class ChatSessionResponse(BaseModel):
    session_id: str
    user_id: str
    collection_id: str
    created_at: str
    updated_at: str


class ChatResourceRefResponse(BaseModel):
    resource_type: str
    resource_id: str
    href: str | None = None


class ChatSourceContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_ref: ChatResourceRefResponse
    collection_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    document_title: str = Field(min_length=1, max_length=500)
    source_kind: str = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=512)
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(min_length=1, max_length=6000)
    heading_path: str | None = Field(default=None, max_length=1000)
    quote_truncated: bool = False


class ChatToolResultResponse(BaseModel):
    tool_call_id: str
    status: Literal["succeeded", "queued", "failed"]
    data: dict[str, Any] = Field(default_factory=dict)
    resource_refs: list[ChatResourceRefResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class ChatMessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    created_at: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_result: ChatToolResultResponse | None = None
    source_contexts: list[ChatSourceContextPayload] = Field(default_factory=list)


class ChatToolCallResponse(BaseModel):
    tool_call_id: str
    session_id: str
    assistant_message_id: str
    name: str
    arguments: dict[str, Any]
    arguments_digest: str
    risk: Literal["unknown", "read", "draft", "write"]
    status: Literal[
        "requested",
        "approval_required",
        "approved",
        "running",
        "succeeded",
        "failed",
        "rejected",
    ]
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    decision_user_id: str | None = None
    decision_arguments_digest: str | None = None
    decided_at: str | None = None


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=12000)
    source_contexts: list[ChatSourceContextPayload] = Field(
        default_factory=list,
        max_length=1,
    )


class ChatToolDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    arguments_digest: str = Field(min_length=64, max_length=64)


class ChatTurnResponse(BaseModel):
    status: Literal[
        "completed",
        "approval_required",
        "step_limit_reached",
        "failed",
        "rejected",
    ]
    messages: list[ChatMessageResponse] = Field(default_factory=list)
    pending_approval: ChatToolCallResponse | None = None
    error_code: str | None = None


class ChatMessageListResponse(BaseModel):
    items: list[ChatMessageResponse] = Field(default_factory=list)
    pending_approval: ChatToolCallResponse | None = None
