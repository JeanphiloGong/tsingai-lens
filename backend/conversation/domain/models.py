"""Immutable Conversation messages and selected parent-chain paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Role = Literal["user", "assistant", "tool"]


# declares the domain type representing one conversation message
@dataclass(frozen=True)
class Message:
    message_id: str
    conversation_id: str
    parent_message_id: str | None
    role: Role
    content: str
    produced_by_task_id: str | None = None
    copied_from_message_id: str | None = None

    # defines validation that the dataclass runs immediately after its generated initializer finishes
    def __post_init__(self) -> None:
        if self.parent_message_id == self.message_id:
            raise ValueError("message cannot be its own parent")
        if self.role == "user" and self.produced_by_task_id is not None:
            raise ValueError("user message cannot be produced by a task")


# declares a value object representing an ordered chain of messages
@dataclass(frozen=True)
class ConversationPath:
    items: tuple[Message, ...]
    tip_message_id: str | None

    def __post_init__(self) -> None:
        if not self.items:
            if self.tip_message_id is not None:
                raise ValueError("an empty path cannot have a tip message")
            return
        if self.tip_message_id != self.items[-1].message_id:
            raise ValueError("path tip must be the last message")


# defines `path_to`, which reconstructs a conversation path ending at `tip_id`
def path_to(messages: dict[str, Message], tip_id: str | None) -> ConversationPath:
    path: list[Message] = []
    seen: set[str] = set()
    while tip_id is not None:
        if tip_id in seen or tip_id not in messages:
            raise ValueError("message path is missing or cyclic")
        seen.add(tip_id)
        message = messages[tip_id]
        path.append(message)
        tip_id = message.parent_message_id

    path.reverse()
    if path and any(item.conversation_id != path[0].conversation_id for item in path):
        raise ValueError("message path crosses conversations")
    return ConversationPath(tuple(path), path[-1].message_id if path else None)


__all__ = ["ConversationPath", "Message", "Role", "path_to"]
