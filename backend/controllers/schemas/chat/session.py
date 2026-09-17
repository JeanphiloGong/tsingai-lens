"""Public schemas for durable Research Agent Chat trajectories."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1, max_length=64)


class ChatSessionResponse(BaseModel):
    session_id: str
    user_id: str
    collection_id: str
    created_at: str
    updated_at: str
    root_session_id: str | None = None
    parent_session_id: str | None = None
    fork_message_id: str | None = None
    fork_position: int | None = None
    fork_content: str | None = None


class ChatBranchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=128)
    request_id: UUID
    message: str | None = Field(default=None, min_length=1, max_length=12000)
    mode: Literal["revise", "continue"] = "revise"


class ChatBranchOptions(BaseModel):
    message_id: str
    session_ids: list[str]
    active_session_id: str


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
    source_digest: str | None = Field(default=None, min_length=64, max_length=64)


class ChatToolResultResponse(BaseModel):
    tool_call_id: str
    status: Literal["succeeded", "queued", "failed"]
    data: dict[str, Any] = Field(default_factory=dict)
    resource_refs: list[ChatResourceRefResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class ChatToolRequestResponse(BaseModel):
    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    position: int = Field(ge=0)


class ChatMessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    created_at: str
    tool_call_id: str | None = None
    tool_calls: list[ChatToolRequestResponse] = Field(default_factory=list)
    tool_result: ChatToolResultResponse | None = None
    source_contexts: list[ChatSourceContextPayload] = Field(default_factory=list)


class ChatToolCallResponse(BaseModel):
    tool_call_id: str
    session_id: str
    assistant_message_id: str
    position: int = Field(ge=0)
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
    branch_revision: bool = False
    source_contexts: list[ChatSourceContextPayload] = Field(
        default_factory=list,
        max_length=12,
    )


class ChatToolDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    arguments_digest: str = Field(min_length=64, max_length=64)


class ChatTurnResponse(BaseModel):
    status: Literal[
        "completed",
        "approval_required",
        "failed",
        "rejected",
    ]
    messages: list[ChatMessageResponse] = Field(default_factory=list)
    pending_approval: ChatToolCallResponse | None = None
    error_code: str | None = None
    completion_reason: Literal["model_answer", "resource_budget", "no_progress", "emergency_ceiling"] | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_completion(self) -> "ChatTurnResponse":
        if self.status == "completed":
            if self.completion_reason is None or self.error_code is not None:
                raise ValueError("completed turn requires a reason and no error code")
        elif self.completion_reason is not None:
            raise ValueError("only completed turns have a completion reason")
        return self


class ChatMessageFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["helpful", "not_helpful"] | None
    reason: Literal["incorrect", "incomplete", "unclear", "other"] | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_details(self) -> ChatMessageFeedbackRequest:
        if self.rating is None and (self.reason is not None or self.comment is not None):
            raise ValueError("withdrawn feedback cannot have a reason or comment")
        if self.reason is not None and self.rating != "not_helpful":
            raise ValueError("only negative feedback may have a reason")
        return self


class ChatMessageFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: str
    session_id: str
    message_id: str
    user_id: str
    rating: Literal["helpful", "not_helpful"]
    reason: Literal["incorrect", "incomplete", "unclear", "other"] | None
    comment: str | None
    response_digest: str
    created_at: str
    updated_at: str


class ChatResponseSnapshotResponse(BaseModel):
    response_id: str
    sequence: int
    started_at: str
    updated_at: str
    status: Literal["running", "completed", "approval_required", "failed", "interrupted"]
    message_id: str | None = None
    message_created_at: str | None = None
    content: str = ""
    progress: dict[str, Any] = Field(default_factory=dict)
    checkpoint_message_id: str | None = None
    completion_reason: str | None = None
    error_code: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ChatMessageListResponse(BaseModel):
    items: list[ChatMessageResponse] = Field(default_factory=list)
    pending_approval: ChatToolCallResponse | None = None
    feedback: list[ChatMessageFeedbackResponse] = Field(default_factory=list)
    branches: list[ChatBranchOptions] = Field(default_factory=list)
    branch_draft: ChatMessageResponse | None = None
    running: bool = False
    response: ChatResponseSnapshotResponse | None = None


class ChatTreeNodeResponse(BaseModel):
    message: ChatMessageResponse
    parent_message_id: str | None
    answer: str
    status: Literal["completed", "running", "approval_required", "failed", "interrupted", "incomplete", "draft"]
    can_branch: bool


class ChatTreeResponse(BaseModel):
    root_session_id: str
    active_path: list[str]
    nodes: list[ChatTreeNodeResponse]
