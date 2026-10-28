"""Ordered user, assistant, and capability-result Chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from domain.chat.tool_call import ChatToolResult, _arguments, _required_text
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_call_id", _required_text(self.tool_call_id, "tool_call_id"))
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "arguments", _arguments(self.arguments))
        if not isinstance(self.position, int) or isinstance(self.position, bool) or self.position < 0:
            raise ValueError("tool request position must be a non-negative integer")

@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    session_id: str
    role: ChatMessageRole | str
    content: str
    created_at: str
    tool_call_id: str | None = None
    tool_calls: tuple[ChatToolRequest, ...] = ()
    tool_result: ChatToolResult | None = None
    source_contexts: tuple[ChatSourceContext, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "message_id", _required_text(self.message_id, "message_id")
        )
        object.__setattr__(
            self, "session_id", _required_text(self.session_id, "session_id")
        )
        object.__setattr__(self, "role", ChatMessageRole(self.role))
        object.__setattr__(
            self, "created_at", _required_text(self.created_at, "created_at")
        )
        content = str(self.content or "").strip()
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "source_contexts", tuple(self.source_contexts))
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if self.role is not ChatMessageRole.ASSISTANT and self.tool_calls:
            raise ValueError("only assistant messages carry tool requests")
        if self.role is not ChatMessageRole.TOOL and (self.tool_call_id or self.tool_result):
            raise ValueError("only tool results carry a result call id")
        if self.role is not ChatMessageRole.USER and self.source_contexts:
            raise ValueError("only user messages may carry source contexts")
        if self.role is ChatMessageRole.USER and not content:
            raise ValueError("user message content cannot be empty")
        if self.role is ChatMessageRole.ASSISTANT:
            if not content and not self.tool_calls:
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
