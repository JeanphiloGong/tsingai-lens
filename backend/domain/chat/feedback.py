"""A user's assessment of a saved answer's usefulness, not scientific review."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from domain.chat.message import ChatMessage, ChatMessageRole


FeedbackRating = Literal["helpful", "not_helpful"]
FeedbackReason = Literal["incorrect", "incomplete", "unclear", "other"]


@dataclass(frozen=True)
class ChatMessageFeedback:
    feedback_id: str
    session_id: str
    message_id: str
    user_id: str
    rating: FeedbackRating
    reason: FeedbackReason | None
    comment: str | None
    response_digest: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if self.rating not in {"helpful", "not_helpful"}:
            raise ValueError("invalid feedback rating")
        if self.reason not in {None, "incorrect", "incomplete", "unclear", "other"}:
            raise ValueError("invalid feedback reason")
        if self.reason is not None and self.rating != "not_helpful":
            raise ValueError("only negative feedback may have a reason")
        if self.comment is not None:
            if "\x00" in self.comment:
                raise ValueError("feedback comment cannot contain a null character")
            if len(self.comment) > 2000:
                raise ValueError("feedback comment cannot exceed 2000 characters")
            object.__setattr__(self, "comment", self.comment.strip() or None)

    @classmethod
    def for_answer(
        cls,
        *,
        message: ChatMessage,
        feedback_id: str,
        user_id: str,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
        now: str,
    ) -> ChatMessageFeedback:
        cls.validate_answer(message)
        return cls(
            feedback_id=feedback_id,
            session_id=message.session_id,
            message_id=message.message_id,
            user_id=user_id,
            rating=rating,
            reason=reason,
            comment=comment,
            response_digest=sha256(message.content.encode("utf-8")).hexdigest(),
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def validate_answer(message: ChatMessage) -> None:
        if (
            message.role is not ChatMessageRole.ASSISTANT
            or not message.content
            or message.tool_calls
        ):
            raise ValueError("feedback requires an assistant text answer without tool requests")
