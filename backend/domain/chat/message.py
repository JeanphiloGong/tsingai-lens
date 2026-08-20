"""Ordered user, assistant, and capability-result Chat messages."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, Mapping

from domain.chat.tool_call import ChatToolResult, _arguments, _required_text


class ChatMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    session_id: str
    role: ChatMessageRole | str
    content: str
    created_at: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: Mapping[str, Any] | None = None
    tool_result: ChatToolResult | None = None

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
        if self.role is ChatMessageRole.USER and not content:
            raise ValueError("user message content cannot be empty")
        if self.role is ChatMessageRole.ASSISTANT:
            if not content and not self.tool_call_id:
                raise ValueError("assistant message requires content or a tool call")
            if self.tool_call_id:
                _required_text(self.tool_name, "tool_name")
                if self.tool_arguments is None:
                    raise ValueError("tool-calling assistant message requires arguments")
                object.__setattr__(self, "tool_arguments", _arguments(self.tool_arguments))
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
    ) -> "ChatMessage":
        return cls(message_id, session_id, ChatMessageRole.USER, content, created_at)

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
    def assistant_tool_call(
        cls,
        *,
        message_id: str,
        session_id: str,
        content: str,
        tool_call_id: str,
        tool_name: str,
        tool_arguments: Mapping[str, Any],
        created_at: str,
    ) -> "ChatMessage":
        return cls(
            message_id,
            session_id,
            ChatMessageRole.ASSISTANT,
            content,
            created_at,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
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
            tool_name=payload.get("tool_name"),
            tool_arguments=(
                dict(payload["tool_arguments"])
                if isinstance(payload.get("tool_arguments"), Mapping)
                else None
            ),
            tool_result=(
                ChatToolResult.from_mapping(result_payload)
                if isinstance(result_payload, Mapping)
                else None
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
            "tool_name": self.tool_name,
            "tool_arguments": (
                deepcopy(dict(self.tool_arguments))
                if self.tool_arguments is not None
                else None
            ),
            "tool_result": (
                self.tool_result.to_record() if self.tool_result is not None else None
            ),
        }


__all__ = ["ChatMessage", "ChatMessageRole"]
