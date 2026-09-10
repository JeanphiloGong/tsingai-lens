from __future__ import annotations

from contextlib import asynccontextmanager

from application.repositories.chat_repository import ChatResponseSnapshot, ChatSessionBusyError
from domain.chat import ChatMessage, ChatSession, ChatToolCall, ChatToolResult


class MemoryChatRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.messages: dict[str, tuple[ChatMessage, ...]] = {}
        self.calls: dict[str, ChatToolCall] = {}
        self.results: dict[str, ChatToolResult] = {}
        self.active_sessions: set[str] = set()
        self.response_snapshots: dict[str, ChatResponseSnapshot] = {}

    @asynccontextmanager
    async def session_execution(self, session_id: str):
        if session_id in self.active_sessions:
            raise ChatSessionBusyError()
        self.active_sessions.add(session_id)
        try:
            yield
        finally:
            self.active_sessions.remove(session_id)

    async def is_session_running(self, session_id: str) -> bool:
        return session_id in self.active_sessions

    async def read_response_snapshot(self, session_id: str) -> ChatResponseSnapshot | None:
        return self.response_snapshots.get(session_id)

    async def save_response_snapshot(self, session_id: str, snapshot: ChatResponseSnapshot) -> None:
        self.response_snapshots[session_id] = snapshot

    async def read_session_family(self, session: ChatSession) -> tuple[ChatSession, ...]:
        return (session,)

    async def add_session(self, record: ChatSession) -> None:
        self.sessions[record.session_id] = record
        self.messages[record.session_id] = ()

    async def read_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)

    async def read_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        return self.messages.get(session_id, ())

    async def read_feedback(self, session_id: str, user_id: str) -> tuple:
        return ()

    async def read_tool_call(self, tool_call_id: str) -> ChatToolCall | None:
        return self.calls.get(tool_call_id)

    async def save_trajectory(
        self,
        *,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        tool_calls: tuple[ChatToolCall, ...],
        tool_results: tuple[ChatToolResult, ...],
    ) -> None:
        self.sessions[session.session_id] = session
        self.messages[session.session_id] = messages
        self.calls.update((item.tool_call_id, item) for item in tool_calls)
        self.results.update((item.tool_call_id, item) for item in tool_results)

    async def decide_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        arguments_digest: str,
        decision: str,
        decided_at: str,
    ) -> ChatToolCall:
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise FileNotFoundError(f"chat session not found: {session_id}")
        call = self.calls.get(tool_call_id)
        if call is None or call.session_id != session_id:
            raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
        decided = (
            call.approve(
                user_id=user_id,
                arguments_digest=arguments_digest,
                decided_at=decided_at,
            )
            if decision == "approved"
            else call.reject(
                user_id=user_id,
                arguments_digest=arguments_digest,
                decided_at=decided_at,
            )
        )
        self.calls[tool_call_id] = decided
        return decided

    async def claim_approved_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        started_at: str,
    ) -> ChatToolCall | None:
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise FileNotFoundError(f"chat session not found: {session_id}")
        call = self.calls.get(tool_call_id)
        if call is None or call.session_id != session_id:
            raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
        if call.status.value == "approved":
            claimed = call.start(started_at)
            self.calls[tool_call_id] = claimed
            return claimed
        if call.status.value in {"running", "succeeded", "failed"}:
            return None
        raise ValueError(f"cannot claim tool call in status {call.status.value}")


__all__ = ["MemoryChatRepository"]
