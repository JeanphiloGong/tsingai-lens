from __future__ import annotations

from typing import Protocol
from contextlib import AbstractAsyncContextManager

from domain.chat import ChatMessage, ChatSession, ChatToolCall, ChatToolResult
from domain.chat.feedback import ChatMessageFeedback


class ChatSessionBusyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("the research response is still running; retry when it finishes")


class ChatRepository(Protocol):
    def session_execution(self, session_id: str) -> AbstractAsyncContextManager[None]: ...

    async def is_session_running(self, session_id: str) -> bool: ...

    async def read_session_family(self, session: ChatSession) -> tuple[ChatSession, ...]: ...

    async def add_branch(
        self, *, session: ChatSession, source_session_id: str, before_position: int,
    ) -> ChatSession: ...

    async def add_session(self, record: ChatSession) -> None: ...

    async def read_session(self, session_id: str) -> ChatSession | None: ...

    async def read_messages(
        self, session_id: str
    ) -> tuple[ChatMessage, ...]: ...

    async def read_message(self, message_id: str) -> ChatMessage | None: ...

    async def read_feedback(
        self, session_id: str, user_id: str
    ) -> tuple[ChatMessageFeedback, ...]: ...

    async def save_feedback(self, feedback: ChatMessageFeedback) -> ChatMessageFeedback: ...

    async def delete_feedback(
        self, *, session_id: str, message_id: str, user_id: str
    ) -> None: ...

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
