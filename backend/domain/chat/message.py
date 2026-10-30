"""Ordered user, assistant, and capability-result Chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from domain.chat.tool_call import ChatToolResult
from domain.chat.source_context import ChatSourceContext


class ChatMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ChatToolRequest:
    tool_call_id: str
    name: str
    arguments: Mapping[str, Any]
    position: int
    # Approval metadata is carried through the in-memory trajectory so an
    # approval continuation can rebuild calls without borrowing another call's
    # decision. It is intentionally omitted from the public message record.
    decision_user_id: str | None = None
    decision_arguments_digest: str | None = None
    decided_at: str | None = None
    decision_basis: str = "explicit"
    authorization_revision: int | None = None

@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    session_id: str
    role: ChatMessageRole
    content: str
    created_at: str
    tool_call_id: str | None = None
    tool_calls: tuple[ChatToolRequest, ...] = ()
    tool_result: ChatToolResult | None = None
    source_contexts: tuple[ChatSourceContext, ...] = ()

    def __post_init__(self) -> None:
        if self.role is not ChatMessageRole.ASSISTANT and self.tool_calls:
            raise ValueError("only assistant messages carry tool requests")
        if self.role is not ChatMessageRole.TOOL and (self.tool_call_id or self.tool_result):
            raise ValueError("only tool results carry a result call id")
        if self.role is not ChatMessageRole.USER and self.source_contexts:
            raise ValueError("only user messages may carry source contexts")
        if self.role is ChatMessageRole.USER and not self.content:
            raise ValueError("user message content cannot be empty")
        if self.role is ChatMessageRole.ASSISTANT:
            if not self.content and not self.tool_calls:
                raise ValueError("assistant message requires content or a tool call")
            if tuple(item.position for item in self.tool_calls) != tuple(range(len(self.tool_calls))):
                raise ValueError("assistant tool calls require contiguous positions")
            ids = [item.tool_call_id for item in self.tool_calls]
            if len(ids) != len(set(ids)):
                raise ValueError("assistant tool call ids must be unique")
        if self.role is ChatMessageRole.TOOL:
            if self.tool_result is None:
                raise ValueError("tool message requires tool_result")
            if self.tool_call_id != self.tool_result.tool_call_id:
                raise ValueError("tool message identity does not match tool result")

    @classmethod
    def user(
        cls,
        *,
        message_id: str,
        session_id: str,
        content: str,
        created_at: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
    ) -> "ChatMessage":
        return cls(
            message_id,
            session_id,
            ChatMessageRole.USER,
            content,
            created_at,
            source_contexts=source_contexts,
        )

    @classmethod
    def assistant(
        cls,
        *,
        message_id: str,
        session_id: str,
        content: str,
        created_at: str,
    ) -> "ChatMessage":
        return cls(message_id, session_id, ChatMessageRole.ASSISTANT, content, created_at)

    @classmethod
    def assistant_tool_calls(
        cls,
        *,
        message_id: str,
        session_id: str,
        content: str,
        tool_calls: tuple[ChatToolRequest, ...],
        created_at: str,
    ) -> "ChatMessage":
        return cls(
            message_id,
            session_id,
            ChatMessageRole.ASSISTANT,
            content,
            created_at,
            tool_calls=tool_calls,
        )


__all__ = ["ChatMessage", "ChatMessageRole", "ChatToolRequest"]
