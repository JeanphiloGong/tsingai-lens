"""Public schemas for durable Research Agent Chat trajectories."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.chat import ToolPermissionMode
from domain.chat.permissions import AUTO_ACTIONS


class ChatSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1, max_length=64)


class ChatPermissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["read_only", "confirm", "auto"]
    actions: list[str] = Field(default_factory=list, max_length=len(AUTO_ACTIONS))
    expires_at: str | None = None
    expected_revision: int = Field(ge=0)


class ChatPermissionResponse(BaseModel):
    mode: Literal["read_only", "confirm", "auto"]
    actions: list[str]
    expires_at: str | None
    revision: int


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
    decision_basis: Literal["explicit", "scope_grant"] = "explicit"
    authorization_revision: int | None = None


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=12000)
    branch_revision: bool = False
    source_contexts: list[ChatSourceContextPayload] = Field(
        default_factory=list,
        max_length=12,
    )
    permission_mode: ToolPermissionMode = ToolPermissionMode.CONFIRM


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


class ChatModelCallSummaryResponse(BaseModel):
    call_id: str
    session_id: str
    trigger_message_id: str | None
    response_message_id: str | None
    purpose: Literal["decision", "compaction", "finalization"]
    model: str
    request_digest: str
    status: Literal[
        "recorded",
        "provider_succeeded",
        "provider_failed",
        "response_invalid",
        "cancelled",
    ]
    started_at: str
    finished_at: str | None
    error_code: str | None
    provider_confirmed: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class ChatModelCallResponse(ChatModelCallSummaryResponse):
    request: dict[str, Any]


class ChatModelCallListResponse(BaseModel):
    items: list[ChatModelCallSummaryResponse] = Field(default_factory=list)
    limit: int
    offset: int


class ChatCorrectionCaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_message_id: str = Field(min_length=1, max_length=128)
    feedback_message_id: str = Field(min_length=1, max_length=128)
    corrected_message_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatCorrectionCaseResponse(BaseModel):
    case_id: str
    session_id: str
    original_message_id: str
    feedback_message_id: str
    corrected_message_id: str | None
    original_model_call_id: str
    corrected_model_call_id: str | None
    status: Literal["linked", "unresolved"]
    trace_digest: str
    created_at: str
    updated_at: str


class ChatCorrectionCaseListResponse(BaseModel):
    items: list[ChatCorrectionCaseResponse] = Field(default_factory=list)
    limit: int
    offset: int


class ChatCorrectionCandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_message_id: str | None = Field(default=None, min_length=1, max_length=128)
    answer_message_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatCorrectionCandidateResponse(BaseModel):
    candidate_id: str
    owner_id: str
    collection_id: str
    session_id: str
    challenge_message_id: str | None
    answer_message_id: str | None
    event_ids: list[str]
    model_call_ids: list[str]
    status: Literal[
        "needs_review",
        "ambiguous",
        "no_candidate",
        "invalid_proposal",
        "provider_failed",
    ]
    proposal: dict[str, Any] | None
    request: dict[str, Any]
    raw_response: str | None
    finish_reason: str | None
    error_code: str | None
    selected_case_id: str | None
    selected_sample_id: str | None
    digest: str
    created_at: str
    updated_at: str


class ChatCorrectionCandidateListResponse(BaseModel):
    items: list[ChatCorrectionCandidateResponse] = Field(default_factory=list)
    limit: int
    offset: int


class ChatCorrectionSampleResponse(BaseModel):
    sample_id: str
    case_id: str
    session_id: str
    collection_id: str
    model_call_id: str
    input: dict[str, Any]
    observations: list[dict[str, Any]]
    target: str
    source_refs: list[dict[str, Any]]
    digest: str
    created_at: str
    updated_at: str


class ChatCorrectionSampleListResponse(BaseModel):
    items: list[ChatCorrectionSampleResponse] = Field(default_factory=list)
    limit: int
    offset: int


class ChatCorrectionReviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "reject", "insufficient", "withdraw"]
    reason: str | None = Field(default=None, max_length=4000)
    support_message_ids: list[str] = Field(default_factory=list, max_length=32)


class ChatCorrectionReviewResponse(BaseModel):
    review_id: str
    sample_id: str
    session_id: str
    sample_digest: str
    decision: Literal["accept", "reject", "insufficient", "withdraw"]
    reviewer_id: str
    reason: str | None
    support_message_ids: list[str]
    seq: int
    created_at: str


class ChatCorrectionReviewListResponse(BaseModel):
    items: list[ChatCorrectionReviewResponse] = Field(default_factory=list)


class ChatCorrectionReviewStatusResponse(BaseModel):
    state: Literal[
        "pending",
        "accept",
        "reject",
        "insufficient",
        "withdraw",
        "stale",
    ]
    sample_digest: str
    latest: ChatCorrectionReviewResponse | None = None


class ChatCorrectionDatasetSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    sample_id: str = Field(min_length=1, max_length=64)
    split: Literal["train", "eval"]


class ChatCorrectionDatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1, max_length=64)
    items: list[ChatCorrectionDatasetSelectionRequest] = Field(default_factory=list, max_length=2000)
    paper_families: dict[str, str] = Field(default_factory=dict, max_length=5000)


class ChatCorrectionDatasetRowResponse(BaseModel):
    row_id: str
    sample_id: str
    case_id: str
    session_id: str
    collection_id: str
    model_call_id: str
    input: dict[str, Any]
    observations: list[dict[str, Any]]
    target: str
    review_id: str
    review_digest: str
    source_refs: list[dict[str, Any]]
    paper_families: list[dict[str, str]]
    session_tree_id: str
    split: Literal["train", "eval"]
    content_digest: str


class ChatCorrectionDatasetExclusionResponse(BaseModel):
    sample_id: str
    session_id: str
    case_id: str | None
    reason: Literal[
        "invalid_sample",
        "stale",
        "withdrawn",
        "insufficient",
        "rejected",
        "unresolved",
        "missing_source",
        "missing_paper_family",
        "partition_conflict",
        "conflicting_assignment",
    ]
    detail: str


class ChatCorrectionDatasetResponse(BaseModel):
    schema_version: str
    dataset_id: str
    owner_id: str
    collection_id: str
    provenance: dict[str, Any]
    provenance_digest: str
    rows: list[ChatCorrectionDatasetRowResponse] = Field(default_factory=list)
    exclusions: list[ChatCorrectionDatasetExclusionResponse] = Field(default_factory=list)
    digest: str
    created_at: str
    row_count: int
    excluded_count: int


class ChatCorrectionDatasetListResponse(BaseModel):
    items: list[ChatCorrectionDatasetResponse] = Field(default_factory=list)
    limit: int
    offset: int


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
