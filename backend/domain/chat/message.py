"""Ordered user, assistant, and capability-result Chat messages."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import json
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_call_id", _required_text(self.tool_call_id, "tool_call_id"))
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "arguments", _arguments(self.arguments))
        if not isinstance(self.position, int) or isinstance(self.position, bool) or self.position < 0:
            raise ValueError("tool request position must be a non-negative integer")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatToolRequest":
        return cls(
            tool_call_id=str(payload.get("tool_call_id") or ""),
            name=str(payload.get("name") or ""),
            arguments=payload.get("arguments") or {},
            position=payload["position"],
        )

    def to_record(self) -> dict[str, Any]:
        return {"tool_call_id": self.tool_call_id, "name": self.name,
                "arguments": deepcopy(dict(self.arguments)), "position": self.position}


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

    @classmethod
    def from_tool_result(
        cls,
        *,
        message_id: str,
        session_id: str,
        result: ChatToolResult,
        created_at: str,
    ) -> "ChatMessage":
        return cls(
            message_id,
            session_id,
            ChatMessageRole.TOOL,
            json.dumps(result.to_record(), ensure_ascii=True, separators=(",", ":")),
            created_at,
            tool_call_id=result.tool_call_id,
            tool_result=result,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatMessage":
        result_payload = payload.get("tool_result")
        return cls(
            message_id=str(payload.get("message_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            role=str(payload.get("role") or ""),
            content=str(payload.get("content") or ""),
            created_at=str(payload.get("created_at") or ""),
            tool_call_id=payload.get("tool_call_id"),
            tool_calls=tuple(ChatToolRequest.from_mapping(item) for item in payload.get("tool_calls") or ()),
            tool_result=(
                ChatToolResult.from_mapping(result_payload)
                if isinstance(result_payload, Mapping)
                else None
            ),
            source_contexts=tuple(
                ChatSourceContext.from_mapping(item)
                for item in payload.get("source_contexts") or ()
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role.value,
            "content": self.content,
            "created_at": self.created_at,
            "tool_call_id": self.tool_call_id,
            "tool_calls": [item.to_record() for item in self.tool_calls],
            "tool_result": (
                self.tool_result.to_record() if self.tool_result is not None else None
            ),
            "source_contexts": [item.to_record() for item in self.source_contexts],
        }


__all__ = ["ChatMessage", "ChatMessageRole", "ChatToolRequest"]
