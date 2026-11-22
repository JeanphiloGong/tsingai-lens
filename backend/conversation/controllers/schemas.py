from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from domain.chat.feedback import FeedbackRating, FeedbackReason
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConversationInputError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    workspace_id: str
    title: str | None
    is_pinned: bool
    current_message_id: str | None
    current_task_id: str | None
    path_revision: int
    forked_from_message_id: str | None
    status: Literal["idle", "running", "approval"]
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    limit: int
    offset: int


class TaskAcceptedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    trigger_message_id: str
    status: Literal["accepted"]


class MessageFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: str
    rating: FeedbackRating
    reason: FeedbackReason | None
    comment: str | None
    response_digest: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    source_contexts: tuple[dict[str, Any], ...]
    my_feedback: MessageFeedbackResponse | None


class ActiveTaskResponse(BaseModel):
    task_id: str
    status: Literal["accepted", "running", "approval_required", "interrupted"]
    checkpoint_revision: int


class ConversationMessagesResponse(BaseModel):
    conversation: ConversationResponse
    tip_message_id: str | None
    items: list[MessageResponse]
    active_tasks: list[ActiveTaskResponse]
    meta: dict[str, bool] = Field(default_factory=lambda: {"has_more": False})


class TreeNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: str
    kind: Literal["message", "task", "conversation"]
    parent_node_id: str | None
    edge_kind: str | None
    conversation_id: str
    message_id: str | None
    task_id: str | None
    preview: str
    forked_from_message_id: str | None = None


class ConversationTreeResponse(BaseModel):
    root_conversation_id: str
    active_path: list[str]
    nodes: list[TreeNodeResponse]


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=64)


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None
    parent_message_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=12000)
    source_contexts: list[dict[str, object]] = Field(default_factory=list, max_length=12)


class EditMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None
    message: str = Field(min_length=1, max_length=12000)
    source_contexts: list[dict[str, object]] | None = Field(default=None, max_length=12)


class RegenerateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None


class ForkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=128)


class ActivePathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_path_revision: int = Field(ge=0, strict=True)
    tip_message_id: str | None = Field(default=None, min_length=1, max_length=128)
    task_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if (self.tip_message_id is None) == (self.task_id is None):
            raise ConversationInputError(
                "conversation_path_invalid", "Exactly one path target is required."
            )
        return self


class ConversationTitleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: object) -> str:
        if isinstance(value, str) and not any(char in value for char in "\x00\r\n"):
            title = value.strip()
            if 1 <= len(title) <= 160:
                return title
        raise ConversationInputError(
            "conversation_title_invalid",
            "Title must contain 1–160 characters on one line.",
        )


class ConversationPinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_pinned: bool

    @field_validator("is_pinned", mode="before")
    @classmethod
    def validate_pin(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        raise ConversationInputError(
            "conversation_pin_invalid", "Pin must be a boolean."
        )


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: FeedbackRating
    reason: FeedbackReason | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("rating", mode="before")
    @classmethod
    def validate_rating(cls, value: object) -> object:
        if value not in ("helpful", "not_helpful"):
            raise ConversationInputError(
                "feedback_rating_invalid", "Unknown feedback rating."
            )
        return value

    @field_validator("reason", mode="before")
    @classmethod
    def validate_reason(cls, value: object) -> object:
        if value not in (None, "incorrect", "incomplete", "unclear", "other"):
            raise ConversationInputError(
                "feedback_reason_invalid", "Unknown feedback reason."
            )
        return value

    @field_validator("comment", mode="before")
    @classmethod
    def clean_comment(cls, value: object) -> object:
        if isinstance(value, str):
            if "\x00" in value:
                raise ConversationInputError(
                    "feedback_comment_invalid", "Feedback cannot contain NUL."
                )
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_rating_reason(self) -> Self:
        if self.reason is not None and self.rating != "not_helpful":
            raise ConversationInputError(
                "feedback_reason_invalid",
                "Only negative feedback can include a reason.",
            )
        return self
