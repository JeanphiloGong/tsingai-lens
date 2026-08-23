from __future__ import annotations

from domain.chat import ChatMessage, ChatSession, ChatToolCall, ChatToolResult


class MemoryChatRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.messages: dict[str, tuple[ChatMessage, ...]] = {}
        self.calls: dict[str, ChatToolCall] = {}
        self.results: dict[str, ChatToolResult] = {}

    async def add_session(self, record: ChatSession) -> None:
        self.sessions[record.session_id] = record
        self.messages[record.session_id] = ()

    async def read_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)

    async def read_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        return self.messages.get(session_id, ())

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


__all__ = ["MemoryChatRepository"]
