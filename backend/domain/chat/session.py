"""Durable identity and ownership for one Chat session."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal


ChatSessionStatus = Literal["idle", "running", "approval"]


@dataclass(frozen=True)
class ChatSession:
    session_id: str
    user_id: str
    collection_id: str
    created_at: str
    updated_at: str
    status: ChatSessionStatus = "idle"
    root_session_id: str | None = None
    parent_session_id: str | None = None
    fork_message_id: str | None = None
    fork_position: int | None = None
    fork_content: str | None = None
    is_pinned: bool = False
    title: str | None = None

    def __post_init__(self) -> None:
        lineage = (self.root_session_id, self.parent_session_id, self.fork_message_id,
                   self.fork_position, self.fork_content)
        if any(value is not None for value in lineage):
            if any(value is None for value in lineage):
                raise ValueError("a conversation branch requires complete lineage")
            if (
                self.fork_position < 0
                or not self.fork_content.strip()
                or len(self.fork_content) > 12000
                or "\x00" in self.fork_content
            ):
                raise ValueError("a conversation branch requires a question and position")
            if not self.root_session_id or not self.parent_session_id or not self.fork_message_id:
                raise ValueError("a conversation branch requires complete lineage")
            if self.parent_session_id == self.session_id:
                raise ValueError("a conversation cannot branch from itself")
        created_at = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
        if updated_at < created_at:
            raise ValueError("updated_at cannot be before created_at")

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        user_id: str,
        collection_id: str,
        created_at: str,
    ) -> "ChatSession":
        return cls(
            session_id=session_id,
            user_id=user_id,
            collection_id=collection_id,
            created_at=created_at,
            updated_at=created_at,
            status="idle",
        )

    def update(
        self,
        *,
        user_id: str,
        collection_id: str,
        updated_at: str,
    ) -> "ChatSession":
        if user_id != self.user_id or collection_id != self.collection_id:
            raise ValueError("session identity cannot be reassigned")
        return replace(self, updated_at=updated_at)


__all__ = ["ChatSession", "ChatSessionStatus"]
