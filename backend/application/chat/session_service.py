"""Application ownership for durable Research Agent Chat sessions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from application.chat.agent_runner import AgentRunResult, ResearchAgentRunner
from application.chat.capabilities import AgentContext
from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolResultStatus,
)
from domain.ports import ChatRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatSessionNotFoundError(FileNotFoundError):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"chat session not found: {session_id}")


class ChatApprovalPendingError(RuntimeError):
    def __init__(self, tool_call_id: str) -> None:
        self.tool_call_id = tool_call_id
        super().__init__(
            "resolve the pending research action before sending another message"
        )


class ChatSessionService:
    def __init__(
        self,
        *,
        collection_service: Any,
        repository: ChatRepository,
        runner: ResearchAgentRunner,
    ) -> None:
        self.collection_service = collection_service
        self.repository = repository
        self.runner = runner

    def create_session(self, *, collection_id: str, user_id: str) -> ChatSession:
        collection = self.collection_service.get_collection_for_user(
            collection_id,
            user_id,
        )
        now = _now_iso()
        session = ChatSession.create(
            session_id=f"chat_{uuid4().hex[:16]}",
            user_id=user_id,
            collection_id=str(collection["collection_id"]),
            created_at=now,
        )
        self.repository.add_session(session)
        return session

    def get_session_for_user(self, session_id: str, user_id: str) -> ChatSession:
        session = self.repository.read_session(session_id)
        if session is None or session.user_id != user_id:
            raise ChatSessionNotFoundError(session_id)
        self.collection_service.get_collection_for_user(session.collection_id, user_id)
        return session

    def list_messages_for_user(
        self,
        session_id: str,
        user_id: str,
    ) -> tuple[ChatMessage, ...]:
        self.get_session_for_user(session_id, user_id)
        return self.repository.read_messages(session_id)

    def get_pending_approval_for_user(
        self,
        session_id: str,
        user_id: str,
    ) -> ChatToolCall | None:
        messages = self.list_messages_for_user(session_id, user_id)
        for message in reversed(messages):
            if message.tool_call_id is None:
                continue
            call = self.repository.read_tool_call(message.tool_call_id)
            if call is not None and call.status is ToolCallStatus.APPROVAL_REQUIRED:
                return call
        return None

    def post_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
    ) -> dict[str, Any]:
        session = self.get_session_for_user(session_id, user_id)
        previous_messages = self.repository.read_messages(session_id)
        pending = self.get_pending_approval_for_user(session_id, user_id)
        if pending is not None:
            raise ChatApprovalPendingError(pending.tool_call_id)
        result = self.runner.run_turn(
            context=self._context(session),
            previous_messages=previous_messages,
            user_message=message,
            checkpoint=self._trajectory_checkpoint(session),
        )
        return self._turn_record(result, previous_count=len(previous_messages))

    def decide_tool_call_for_user(
        self,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        *,
        arguments_digest: str,
        decision: str,
    ) -> dict[str, Any]:
        session = self.get_session_for_user(session_id, user_id)
        existing = self.repository.read_tool_call(tool_call_id)
        if existing is None or existing.session_id != session_id:
            raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
        if existing.status is ToolCallStatus.SUCCEEDED:
            return {"status": "completed", "messages": (), "pending_approval": None}
        if existing.status is ToolCallStatus.REJECTED:
            return {"status": "rejected", "messages": (), "pending_approval": None}

        decided = self.repository.decide_tool_call(
            session_id=session_id,
            tool_call_id=tool_call_id,
            user_id=user_id,
            arguments_digest=arguments_digest,
            decision=decision,
            decided_at=_now_iso(),
        )
        previous_messages = self.repository.read_messages(session_id)
        if decided.status is ToolCallStatus.REJECTED:
            result = ChatToolResult(
                tool_call_id=decided.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="user_rejected",
                error_message="The user rejected this research action.",
            )
            result_message = ChatMessage.from_tool_result(
                message_id=f"msg_{uuid4().hex[:16]}",
                session_id=session_id,
                result=result,
                created_at=_now_iso(),
            )
            updated_session = session.update(
                user_id=user_id,
                collection_id=session.collection_id,
                updated_at=result_message.created_at,
            )
            self.repository.save_trajectory(
                session=updated_session,
                messages=(*previous_messages, result_message),
                tool_calls=(decided,),
                tool_results=(result,),
            )
            return {
                "status": "rejected",
                "messages": (result_message,),
                "pending_approval": None,
            }

        run_result = self.runner.resume_approved_call(
            context=self._context(session),
            previous_messages=previous_messages,
            approved_call=decided,
            checkpoint=self._trajectory_checkpoint(session),
        )
        return self._turn_record(
            run_result,
            previous_count=len(previous_messages),
        )

    def _trajectory_checkpoint(
        self,
        session: ChatSession,
    ) -> Callable[
        [
            tuple[ChatMessage, ...],
            tuple[ChatToolCall, ...],
            tuple[ChatToolResult, ...],
        ],
        None,
    ]:
        def save(
            messages: tuple[ChatMessage, ...],
            tool_calls: tuple[ChatToolCall, ...],
            tool_results: tuple[ChatToolResult, ...],
        ) -> None:
            updated_at = messages[-1].created_at if messages else _now_iso()
            self.repository.save_trajectory(
                session=session.update(
                    user_id=session.user_id,
                    collection_id=session.collection_id,
                    updated_at=updated_at,
                ),
                messages=messages,
                tool_calls=tool_calls,
                tool_results=tool_results,
            )

        return save

    @staticmethod
    def _context(session: ChatSession) -> AgentContext:
        return AgentContext(
            session_id=session.session_id,
            user_id=session.user_id,
            collection_id=session.collection_id,
        )

    @staticmethod
    def _turn_record(
        result: AgentRunResult,
        *,
        previous_count: int,
    ) -> dict[str, Any]:
        return {
            "status": result.status.value,
            "messages": result.messages[previous_count:],
            "pending_approval": result.pending_approval,
            "error_code": result.error_code,
        }


__all__ = [
    "ChatApprovalPendingError",
    "ChatSessionNotFoundError",
    "ChatSessionService",
]
