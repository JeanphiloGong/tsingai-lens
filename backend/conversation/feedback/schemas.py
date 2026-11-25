from datetime import datetime
from typing import Self

from conversation.controllers.errors import ConversationInputError

from domain.chat.feedback import FeedbackRating, FeedbackReason
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MessageFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: str
    rating: FeedbackRating
    reason: FeedbackReason | None
    comment: str | None
    response_digest: str
    created_at: datetime
    updated_at: datetime


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
