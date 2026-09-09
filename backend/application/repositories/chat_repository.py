from __future__ import annotations

from typing import Protocol

from domain.chat import ChatMessage, ChatSession, ChatToolCall, ChatToolResult


class ChatRepository(Protocol):
    async def add_session(self, record: ChatSession) -> None: ...

    async def read_session(self, session_id: str) -> ChatSession | None: ...

    async def read_messages(
        self, session_id: str
    ) -> tuple[ChatMessage, ...]: ...

    async def read_tool_call(
        self, tool_call_id: str
    ) -> ChatToolCall | None: ...

    async def save_trajectory(
        self,
        *,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        tool_calls: tuple[ChatToolCall, ...],
        tool_results: tuple[ChatToolResult, ...],
    ) -> None: ...

    async def decide_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        arguments_digest: str,
        decision: str,
        decided_at: str,
    ) -> ChatToolCall: ...

    async def claim_approved_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        started_at: str,
    ) -> ChatToolCall | None: ...
