"""Read and write the signed-in researcher's answer ratings."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from conversation.repositories.scope import ConversationNotFound, owned_conversation
from domain.chat.feedback import FeedbackRating, FeedbackReason
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import AgentTaskORM
from infra.persistence.postgres.models.conversation import (
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class FeedbackTargetInvalid(ValueError):
    """Feedback requires a saved final answer."""


CAN_RATE_MESSAGE = and_(
    MessageORM.role == "assistant",
    MessageORM.content != "",
    MessageORM.copied_from_message_id.is_(None),
    select(1)
    .where(
        AgentTaskORM.task_id == MessageORM.produced_by_task_id,
        AgentTaskORM.session_id == MessageORM.conversation_id,
        AgentTaskORM.status == "completed",
        AgentTaskORM.final_message_id == MessageORM.message_id,
    )
    .correlate(MessageORM)
    .exists(),
)


@dataclass(frozen=True)
class MessageFeedbackView:
    feedback_id: str
    rating: str
    reason: str | None
    comment: str | None
    response_digest: str
    created_at: datetime
    updated_at: datetime


def to_feedback_view(row: MessageFeedbackORM) -> MessageFeedbackView:
    return MessageFeedbackView(
        row.feedback_id,
        row.rating,
        row.reason,
        row.comment,
        row.response_digest,
        row.created_at,
        row.updated_at,
    )


class FeedbackRepository:
    async def upsert_feedback(
        self,
        *,
        conversation_id: str,
        message_id: str,
        user_id: str,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
    ) -> MessageFeedbackView:
        async with AsyncSessionLocal() as db, db.begin():
            message = await self._feedback_target(
                db, conversation_id, message_id, user_id
            )
            row = MessageFeedbackORM
            statement = insert(row).values(
                feedback_id=f"feedback_{uuid4().hex}",
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                rating=rating,
                reason=reason,
                comment=comment,
                response_digest=sha256(message.content.encode("utf-8")).hexdigest(),
                created_at=func.now(),
                updated_at=func.now(),
            )
            submitted = statement.excluded
            saved = (
                await db.scalars(
                    statement.on_conflict_do_update(
                        constraint="uq_chat_message_feedback_user_message",
                        set_={
                            "rating": submitted.rating,
                            "reason": submitted.reason,
                            "comment": submitted.comment,
                            "response_digest": submitted.response_digest,
                            "updated_at": func.greatest(
                                row.updated_at, submitted.updated_at
                            ),
                        },
                        where=or_(
                            row.rating != submitted.rating,
                            row.reason.is_distinct_from(submitted.reason),
                            row.comment.is_distinct_from(submitted.comment),
                            row.response_digest != submitted.response_digest,
                        ),
                    ).returning(row)
                )
            ).one_or_none()
            if saved is None:
                saved = (
                    await db.scalars(
                        select(row).where(
                            row.user_id == user_id,
                            row.message_id == message_id,
                        )
                    )
                ).one()
            return to_feedback_view(saved)

    async def delete_feedback(
        self, *, conversation_id: str, message_id: str, user_id: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            await self._feedback_target(db, conversation_id, message_id, user_id)
            await db.execute(
                delete(MessageFeedbackORM).where(
                    MessageFeedbackORM.conversation_id == conversation_id,
                    MessageFeedbackORM.message_id == message_id,
                    MessageFeedbackORM.user_id == user_id,
                )
            )

    async def _feedback_target(
        self,
        db: AsyncSession,
        conversation_id: str,
        message_id: str,
        user_id: str,
    ) -> MessageORM:
        target = (
            await db.execute(
                select(MessageORM, CAN_RATE_MESSAGE)
                .join(
                    ConversationORM,
                    ConversationORM.conversation_id == MessageORM.conversation_id,
                )
                .where(
                    MessageORM.conversation_id == conversation_id,
                    MessageORM.message_id == message_id,
                    owned_conversation(user_id),
                )
                .with_for_update(of=MessageORM, read=True)
            )
        ).one_or_none()
        if target is None:
            raise ConversationNotFound(
                "Feedback message not found.", code="feedback_message_not_found"
            )
        message, can_rate = target
        if not can_rate:
            raise FeedbackTargetInvalid("Feedback requires a saved final answer.")
        return message
