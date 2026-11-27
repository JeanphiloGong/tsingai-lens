from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from conversation.application.source_context import InvalidSourceContext
from conversation.controllers.errors import ConversationInputError
from domain.chat.resource_ref import ChatResourceRef
from domain.chat.source_context import ChatSourceContext
from conversation.feedback.schemas import MessageFeedbackResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class CitationSourceResponse(BaseModel):
    document_id: str
    source_ref: str
    source_kind: str
    document_title: str
    page: int | str | None
    heading_path: str | None
    caption: str | None
    figure_label: str | None
    href: str


class AnswerCitationResponse(BaseModel):
    offset: int
    source: CitationSourceResponse


class MessageResponse(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    created_at: datetime
    source_contexts: tuple[dict[str, Any], ...]
    citations: list[AnswerCitationResponse] = Field(default_factory=list)
    my_feedback: MessageFeedbackResponse | None
    can_rate: bool


class ActiveTaskResponse(BaseModel):
    task_id: str
    status: Literal["accepted", "running", "approval_required", "interrupted"]
    checkpoint_revision: int
    active_operation: dict[str, Any] | None = None


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
    deleted_source: bool = False


class ConversationTreeResponse(BaseModel):
    root_conversation_id: str
    active_path: list[str]
    nodes: list[TreeNodeResponse]


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=64)


class SourceResourceRef(BaseModel):
    resource_type: str
    resource_id: str
    href: str | None = None


class SourceContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_ref: SourceResourceRef
    workspace_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    document_title: str = Field(min_length=1, max_length=500)
    source_kind: str = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=512)
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(min_length=1, max_length=6000)
    heading_path: str | None = Field(default=None, max_length=1000)
    quote_truncated: bool = False
    source_digest: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


def source_contexts_from_request(
    items: list[SourceContextRequest],
) -> tuple[ChatSourceContext, ...]:
    try:
        return tuple(
            ChatSourceContext(
                resource_ref=ChatResourceRef(**item.resource_ref.model_dump()),
                **item.model_dump(exclude={"resource_ref"}),
            )
            for item in items
        )
    except ValueError as exc:
        raise InvalidSourceContext("Selected Source context is invalid.") from exc


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None
    parent_message_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=12000)
    source_contexts: list[SourceContextRequest] = Field(default_factory=list, max_length=12)
    model_connection_id: str | None = Field(default=None, min_length=1, max_length=64)


class EditMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None
    message: str = Field(min_length=1, max_length=12000)
    source_contexts: list[SourceContextRequest] | None = Field(default=None, max_length=12)


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
