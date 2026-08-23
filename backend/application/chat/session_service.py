"""Application ownership for durable Research Agent Chat sessions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
import logging
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


logger = logging.getLogger(__name__)


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
        self._active_stream_tasks: set[asyncio.Task[None]] = set()

    async def create_session(
        self, *, collection_id: str, user_id: str
    ) -> ChatSession:
        collection = await self.collection_service.get_collection_for_user(
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
        await self.repository.add_session(session)
        return session

    async def get_session_for_user(
        self, session_id: str, user_id: str
    ) -> ChatSession:
        session = await self.repository.read_session(session_id)
        if session is None or session.user_id != user_id:
            raise ChatSessionNotFoundError(session_id)
        await self.collection_service.get_collection_for_user(
            session.collection_id, user_id
        )
        return session

    async def list_messages_for_user(
        self,
        session_id: str,
        user_id: str,
    ) -> tuple[ChatMessage, ...]:
        await self.get_session_for_user(session_id, user_id)
        return await self.repository.read_messages(session_id)

    async def get_pending_approval_for_user(
        self,
        session_id: str,
        user_id: str,
    ) -> ChatToolCall | None:
        messages = await self.list_messages_for_user(session_id, user_id)
        for message in reversed(messages):
            if message.tool_call_id is None:
                continue
            call = await self.repository.read_tool_call(message.tool_call_id)
            if call is not None and call.status is ToolCallStatus.APPROVAL_REQUIRED:
                return call
        return None

    async def post_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
    ) -> dict[str, Any]:
        session = await self.get_session_for_user(session_id, user_id)
        previous_messages = await self.repository.read_messages(session_id)
        pending = await self.get_pending_approval_for_user(session_id, user_id)
        if pending is not None:
            raise ChatApprovalPendingError(pending.tool_call_id)
        result = await self.runner.run_turn(
            context=self._context(session),
            previous_messages=previous_messages,
            user_message=message,
            checkpoint=self._trajectory_checkpoint(session),
        )
        return self._turn_record(result, previous_count=len(previous_messages))

    async def stream_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        session = await self.get_session_for_user(session_id, user_id)
        previous_messages = await self.repository.read_messages(session_id)
        pending = await self.get_pending_approval_for_user(session_id, user_id)
        if pending is not None:
            raise ChatApprovalPendingError(pending.tool_call_id)

        async def events() -> AsyncIterator[dict[str, Any]]:
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def emit_text_delta(content: str) -> None:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "text_delta", "content": content},
                )

            async def run_turn() -> None:
                try:
                    result = await self.runner.run_turn(
                        context=self._context(session),
                        previous_messages=previous_messages,
                        user_message=message,
                        checkpoint=self._trajectory_checkpoint(session),
                        text_delta_callback=emit_text_delta,
                    )
                    await queue.put(
                        {
                            "type": "turn",
                            "turn": self._turn_record(
                                result,
                                previous_count=len(previous_messages),
                            ),
                        }
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Research Agent streaming turn failed session_id=%s",
                        session_id,
                    )
                    await queue.put(
                        {
                            "type": "error",
                            "error": {
                                "code": "chat_stream_failed",
                                "message": "The research response could not be completed.",
                            },
                        }
                    )
                finally:
                    await queue.put(None)

            task = asyncio.create_task(run_turn())
            self._active_stream_tasks.add(task)
            task.add_done_callback(self._active_stream_tasks.discard)
            while (event := await queue.get()) is not None:
                yield event

        return events()

    async def decide_tool_call_for_user(
        self,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        *,
        arguments_digest: str,
        decision: str,
    ) -> dict[str, Any]:
        session = await self.get_session_for_user(session_id, user_id)
        existing = await self.repository.read_tool_call(tool_call_id)
        if existing is None or existing.session_id != session_id:
            raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
        if existing.status is ToolCallStatus.SUCCEEDED:
            return {"status": "completed", "messages": (), "pending_approval": None}
        if existing.status is ToolCallStatus.REJECTED:
            return {"status": "rejected", "messages": (), "pending_approval": None}

        decided = await self.repository.decide_tool_call(
            session_id=session_id,
            tool_call_id=tool_call_id,
            user_id=user_id,
            arguments_digest=arguments_digest,
            decision=decision,
            decided_at=_now_iso(),
        )
        previous_messages = await self.repository.read_messages(session_id)
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
            await self.repository.save_trajectory(
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

        run_result = await self.runner.resume_approved_call(
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
        Awaitable[None],
    ]:
        async def save(
            messages: tuple[ChatMessage, ...],
            tool_calls: tuple[ChatToolCall, ...],
            tool_results: tuple[ChatToolResult, ...],
        ) -> None:
            updated_at = messages[-1].created_at if messages else _now_iso()
            await self.repository.save_trajectory(
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
