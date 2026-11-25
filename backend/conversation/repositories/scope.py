"""Ownership predicates for Conversation repository reads and writes."""

from infra.persistence.postgres.models.conversation import ConversationORM
from infra.persistence.postgres.models.workspace import WorkspaceORM
from sqlalchemy import and_, select


class ConversationNotFound(FileNotFoundError):
    """The conversation is absent or outside the caller's scope."""

    def __init__(self, message: str, *, code: str = "conversation_not_found") -> None:
        super().__init__(message)
        self.code = code


def owned_conversation(user_id: str, *, include_deleted: bool = False):
    conditions = [
        ConversationORM.user_id == user_id,
        select(1)
        .where(
            WorkspaceORM.workspace_id == ConversationORM.workspace_id,
            WorkspaceORM.owner_user_id == user_id,
        )
        .correlate(ConversationORM)
        .exists(),
    ]
    if not include_deleted:
        conditions.append(ConversationORM.deleted_at.is_(None))
    return and_(*conditions)
