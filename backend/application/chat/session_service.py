"""Application ownership for durable Research Agent Chat sessions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import logging
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from application.chat.agent_runner import AgentRunResult, ResearchAgentRunner
from application.chat.capabilities import AgentContext
from application.core.objectives.evidence_authoring_service import (
    normalize_source_text,
    resolve_canonical_objective_source,
)
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolResultStatus,
)
from application.repositories.source_artifact_repository import SourceArtifactRepository
from application.repositories.chat_repository import ChatRepository, ChatResponseSnapshot, ChatSessionBusyError
from domain.chat.feedback import ChatMessageFeedback, FeedbackRating, FeedbackReason


logger = logging.getLogger(__name__)
_HEARTBEAT_INTERVAL_SECONDS = 15
_SNAPSHOT_INTERVAL_SECONDS = 0.25


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatSessionNotFoundError(FileNotFoundError):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"chat session not found: {session_id}")


class ChatSourceContextError(ValueError):
    pass


class ChatMessageNotFoundError(FileNotFoundError):
    pass


class ChatBranchAlreadyStartedError(RuntimeError):
    pass


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
        source_artifact_repository: SourceArtifactRepository,
        repository: ChatRepository,
        runner: ResearchAgentRunner,
    ) -> None:
        self.collection_service = collection_service
        self.source_artifact_repository = source_artifact_repository
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
            for request in message.tool_calls:
                call = await self.repository.read_tool_call(request.tool_call_id)
                if call is not None and call.status is ToolCallStatus.APPROVAL_REQUIRED:
                    return call
        return None

    async def _branch_origin(
        self, session: ChatSession, position: int,
    ) -> tuple[ChatSession, ChatMessage, str]:
        selected_id = None
        while session.parent_session_id is not None and position <= session.fork_position:
            if position == session.fork_position:
                selected_id = session.session_id
            session = await self.get_session_for_user(session.parent_session_id, session.user_id)
        messages = await self.repository.read_messages(session.session_id)
        return session, messages[position], selected_id or session.session_id

    async def branch_message_for_user(
        self, session_id: str, message_id: str, user_id: str, *,
        request_id: str, message: str | None = None,
    ) -> ChatSession:
        session = await self.get_session_for_user(session_id, user_id)
        async with self.repository.session_execution(session_id):
            messages = await self.repository.read_messages(session_id)
            position = next((index for index, item in enumerate(messages)
                             if item.message_id == message_id and item.role.value == "user"), None)
            if position is None:
                raise ChatMessageNotFoundError("saved user message not found")
            original = messages[position]
            content = original.content if message is None else message.strip()
            if not content or len(content) > 12000:
                raise ValueError("revised question must contain 1 to 12000 characters")
            await self._canonical_source_contexts(session, original.source_contexts)
            pending = await self.get_pending_approval_for_user(session_id, user_id)
            if pending is not None:
                raise ChatApprovalPendingError(pending.tool_call_id)
            origin, anchor, _ = await self._branch_origin(session, position)
            now = _now_iso()
            branch = ChatSession(
                session_id="chat_branch_" + sha256(f"{user_id}:{request_id}".encode()).hexdigest()[:40],
                user_id=user_id, collection_id=session.collection_id,
                created_at=now, updated_at=now,
                root_session_id=session.root_session_id or session.session_id,
                parent_session_id=origin.session_id, fork_message_id=anchor.message_id,
                fork_position=position, fork_content=content,
            )
            return await self.repository.add_branch(
                session=branch, source_session_id=session_id, before_position=position,
            )

    async def get_trajectory_for_user(self, session_id: str, user_id: str) -> dict[str, Any]:
        session = await self.get_session_for_user(session_id, user_id)
        response = await self.repository.read_response_snapshot(session_id)
        # Sample execution before messages, so a just-finished turn still gets a final poll.
        running = await self.repository.is_session_running(session_id)
        if not running:
            latest = await self.repository.read_response_snapshot(session_id)
            if response is not None and response.status == "running":
                if latest == response:
                    latest = replace(response, status="interrupted", error_code="chat_response_interrupted")
            # A snapshot changing during the lock sample needs another update, not an interruption.
            running = latest is not None and latest.status == "running"
            response = latest
        messages = await self.repository.read_messages(session_id)
        family = await self.repository.read_session_family(session)
        branches = []
        positions = sorted({item.fork_position for item in family
                            if item.fork_position is not None and item.fork_position < len(messages)})
        for position in positions:
            message = messages[position]
            if message.role.value != "user":
                continue
            origin, anchor, selected_id = await self._branch_origin(session, position)
            alternatives = [item.session_id for item in family
                            if item.parent_session_id == origin.session_id
                            and item.fork_message_id == anchor.message_id]
            if alternatives:
                ids = [origin.session_id, *alternatives]
                branches.append({"message_id": message.message_id, "session_ids": ids,
                                 "active_session_id": selected_id if selected_id in ids else origin.session_id})
        draft = None
        if session.fork_position is not None and len(messages) == session.fork_position:
            original = await self.repository.read_message(session.fork_message_id)
            if original is not None:
                draft = replace(original, content=session.fork_content)
        pending = None
        for message in reversed(messages):
            for request in message.tool_calls:
                call = await self.repository.read_tool_call(request.tool_call_id)
                if call is not None and call.status is ToolCallStatus.APPROVAL_REQUIRED:
                    pending = call
                    break
            if pending is not None:
                break
        return {"messages": messages, "branches": branches, "branch_draft": draft,
                "running": running, "pending_approval": pending, "response": response,
                "feedback": await self.repository.read_feedback(session_id, user_id)}

    async def stream_updates_for_user(
        self, session_id: str, user_id: str, *, response_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        await self.get_session_for_user(session_id, user_id)

        async def events() -> AsyncIterator[dict[str, Any]]:
            sequence = -1
            checkpoint_id = None
            first = True
            while True:
                # Recheck ownership on each sample, including collection deletion/revocation.
                await self.get_session_for_user(session_id, user_id)
                snapshot = await self.repository.read_response_snapshot(session_id)
                running = await self.repository.is_session_running(session_id)
                if not running or snapshot is None or snapshot.response_id != response_id:
                    yield {"type": "trajectory", "trajectory": await self.get_trajectory_for_user(session_id, user_id)}
                    return
                if snapshot.sequence != sequence:
                    sequence = snapshot.sequence
                    if first or snapshot.checkpoint_message_id != checkpoint_id or snapshot.status != "running":
                        yield {"type": "trajectory", "trajectory": await self.get_trajectory_for_user(session_id, user_id)}
                        checkpoint_id = snapshot.checkpoint_message_id
                    else:
                        yield {"type": "snapshot", "snapshot": snapshot}
                    first = False
                if snapshot.status != "running":
                    return
                await asyncio.sleep(_SNAPSHOT_INTERVAL_SECONDS)

        return events()

    async def set_message_feedback_for_user(
        self,
        session_id: str,
        message_id: str,
        user_id: str,
        *,
        rating: FeedbackRating | None,
        reason: FeedbackReason | None = None,
        comment: str | None = None,
    ) -> ChatMessageFeedback | None:
        await self.get_session_for_user(session_id, user_id)
        message = await self.repository.read_message(message_id)
        if message is None or message.session_id != session_id:
            raise ChatMessageNotFoundError("chat message not found")
        ChatMessageFeedback.validate_answer(message)
        if rating is None:
            if reason is not None or comment is not None:
                raise ValueError("withdrawn feedback cannot have a reason or comment")
            await self.repository.delete_feedback(
                session_id=session_id, message_id=message_id, user_id=user_id
            )
            return None
        feedback = ChatMessageFeedback.for_answer(
            message=message,
            feedback_id=f"feedback_{uuid4().hex}",
            user_id=user_id,
            rating=rating,
            reason=reason,
            comment=comment,
            now=_now_iso(),
        )
        return await self.repository.save_feedback(feedback)

    async def post_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
        branch_revision: bool = False,
    ) -> dict[str, Any]:
        session = await self.get_session_for_user(session_id, user_id)
        if branch_revision:
            source_contexts = await self._branch_source_contexts(session, message)
        source_contexts = await self._canonical_source_contexts(
            session, source_contexts
        )
        async with self.repository.session_execution(session_id):
            previous_messages = await self.repository.read_messages(session_id)
            if branch_revision and len(previous_messages) != session.fork_position:
                raise ChatBranchAlreadyStartedError("this revision has already been sent")
            await self._ensure_turn_ready(previous_messages)
            result = await self._run_response(
                session,
                previous_messages=previous_messages,
                message=message,
                source_contexts=source_contexts,
            )
        return self._turn_record(result, previous_count=len(previous_messages))

    async def stream_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
        branch_revision: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        session = await self.get_session_for_user(session_id, user_id)
        if branch_revision:
            source_contexts = await self._branch_source_contexts(session, message)
        if await self.repository.is_session_running(session_id):
            raise ChatSessionBusyError()
        source_contexts = await self._canonical_source_contexts(
            session, source_contexts
        )
        previous_messages = await self.repository.read_messages(session_id)
        if branch_revision and len(previous_messages) != session.fork_position:
            raise ChatBranchAlreadyStartedError("this revision has already been sent")
        pending = await self.get_pending_approval_for_user(session_id, user_id)
        if pending is not None:
            raise ChatApprovalPendingError(pending.tool_call_id)

        async def events() -> AsyncIterator[dict[str, Any]]:
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            connected = True

            def emit(event: dict[str, Any]) -> None:
                if connected:
                    queue.put_nowait(event)

            async def run_turn() -> None:
                try:
                    async with self.repository.session_execution(session_id):
                        current_messages = await self.repository.read_messages(session_id)
                        if branch_revision and len(current_messages) != session.fork_position:
                            raise ChatBranchAlreadyStartedError("this revision has already been sent")
                        await self._ensure_turn_ready(current_messages)
                        result = await self._run_response(
                            session, previous_messages=current_messages, message=message,
                            source_contexts=source_contexts, emit=emit,
                        )
                    emit(
                        {
                            "type": "turn",
                            "turn": self._turn_record(
                                result,
                                previous_count=len(current_messages),
                            ),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Research Agent streaming turn failed session_id=%s exception_type=%s",
                        session_id, type(exc).__name__,
                    )
                    emit(
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
            try:
                while (event := await queue.get()) is not None:
                    yield event
            finally:
                connected = False

        return events()

    async def _run_response(
        self, session: ChatSession, *, previous_messages: tuple[ChatMessage, ...],
        message: str | None = None, source_contexts: tuple[ChatSourceContext, ...] = (),
        claimed_call: ChatToolCall | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentRunResult:
        # The caller holds the execution lock through the final snapshot write.
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        now = _now_iso()
        snapshot = ChatResponseSnapshot(
            response_id=f"response_{uuid4().hex}", sequence=0,
            started_at=now, updated_at=now,
            checkpoint_message_id=previous_messages[-1].message_id if previous_messages else None,
            progress={"phase": "waiting", "cycle_index": 0, "elapsed_ms": 0},
        )
        saved_sequence = -1
        snapshot_lock = asyncio.Lock()

        def update_snapshot(**changes: Any) -> None:
            nonlocal snapshot
            snapshot = replace(snapshot, sequence=snapshot.sequence + 1, updated_at=_now_iso(), **changes)

        async def flush_snapshot() -> None:
            nonlocal saved_sequence
            async with snapshot_lock:
                if saved_sequence == snapshot.sequence:
                    return
                current = snapshot
                await self.repository.save_response_snapshot(session.session_id, current)
                saved_sequence = current.sequence

        def emit_progress(payload: dict[str, Any]) -> None:
            update_snapshot(progress=dict(payload))
            if emit:
                emit({"type": "progress", "progress": payload})

        def start_response(message_id: str, created_at: str) -> None:
            update_snapshot(message_id=message_id, message_created_at=created_at, content="")
            emit_progress({**snapshot.progress, "phase": "waiting", "elapsed_ms": round((loop.time() - started_at) * 1000)})
            if emit:
                emit({"type": "snapshot", "snapshot": snapshot})

        def emit_text_delta(content: str) -> None:
            def append() -> None:
                if snapshot.message_id is not None:
                    if content and snapshot.progress.get("phase") != "responding":
                        emit_progress({**snapshot.progress, "phase": "responding", "elapsed_ms": round((loop.time() - started_at) * 1000)})
                    update_snapshot(content=snapshot.content + content)
                if emit:
                    emit({"type": "text_delta", "content": content})
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is loop:
                append()
            else:
                loop.call_soon_threadsafe(append)

        async def record_checkpoint(messages: tuple[ChatMessage, ...]) -> None:
            saved_ids = {item.message_id for item in messages}
            update_snapshot(
                checkpoint_message_id=messages[-1].message_id if messages else None,
                **({"message_id": None, "message_created_at": None, "content": ""}
                   if snapshot.message_id in saved_ids else {}),
            )
            await flush_snapshot()
            if emit:
                emit({"type": "trajectory", "trajectory": await self.get_trajectory_for_user(session.session_id, session.user_id)})

        async def save_updates() -> None:
            heartbeat_at = loop.time()
            while True:
                await asyncio.sleep(_SNAPSHOT_INTERVAL_SECONDS)
                if loop.time() - heartbeat_at >= _HEARTBEAT_INTERVAL_SECONDS:
                    heartbeat_at = loop.time()
                    emit_progress({**snapshot.progress, "elapsed_ms": round((loop.time() - started_at) * 1000)})
                try:
                    await flush_snapshot()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Chat response snapshot save failed exception_type=%s", type(exc).__name__)

        await flush_snapshot()
        writer = asyncio.create_task(save_updates())
        try:
            arguments = {
                "context": self._context(session), "previous_messages": previous_messages,
                "checkpoint": self._trajectory_checkpoint(session, on_saved=record_checkpoint),
                "text_delta_callback": emit_text_delta, "progress_callback": emit_progress,
                "response_started_callback": start_response,
            }
            if claimed_call is not None:
                result = await self.runner.resume_claimed_call(**arguments, claimed_call=claimed_call)
            else:
                result = await self.runner.run_turn(**arguments, user_message=message, source_contexts=source_contexts)
            update_snapshot(
                status=result.status.value, message_id=None, message_created_at=None, content="",
                completion_reason=result.completion_reason.value if result.completion_reason else None,
                error_code=result.error_code, warnings=result.warnings,
            )
            return result
        except BaseException:
            update_snapshot(status="interrupted", error_code="chat_response_interrupted")
            raise
        finally:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            await flush_snapshot()

    async def _ensure_turn_ready(self, messages: tuple[ChatMessage, ...]) -> None:
        for message in messages:
            for request in message.tool_calls:
                call = await self.repository.read_tool_call(request.tool_call_id)
                if call is not None and call.status is ToolCallStatus.APPROVAL_REQUIRED:
                    raise ChatApprovalPendingError(call.tool_call_id)
                if call is None or call.status not in {
                    ToolCallStatus.SUCCEEDED, ToolCallStatus.FAILED, ToolCallStatus.REJECTED,
                }:
                    raise ChatSessionBusyError()

    async def _branch_source_contexts(
        self, session: ChatSession, message: str,
    ) -> tuple[ChatSourceContext, ...]:
        if session.fork_message_id is None or message != session.fork_content:
            raise ChatSourceContextError("revision must match the saved branch question")
        original = await self.repository.read_message(session.fork_message_id)
        if original is None or original.session_id != session.parent_session_id:
            raise ChatSourceContextError("the original question is no longer available")
        return original.source_contexts

    async def _canonical_source_contexts(
        self,
        session: ChatSession,
        source_contexts: tuple[ChatSourceContext, ...],
    ) -> tuple[ChatSourceContext, ...]:
        if any(item.collection_id != session.collection_id for item in source_contexts):
            raise ChatSourceContextError(
                "source context does not belong to the Chat collection"
            )
        canonical_contexts: list[ChatSourceContext] = []
        for item in source_contexts:
            try:
                await self.collection_service.get_document(
                    session.collection_id,
                    item.document_id,
                )
            except FileNotFoundError as exc:
                raise ChatSourceContextError(
                    "source context document does not belong to the Chat collection"
                ) from exc
            document = await self.source_artifact_repository.read_document(
                session.collection_id,
                item.document_id,
            )
            if document is None:
                raise ChatSourceContextError(
                    "selected Source content is not prepared for this document"
                )
            if document.document_id != item.document_id:
                raise ChatSourceContextError(
                    "selected Source document identity does not match its "
                    "canonical Source"
                )
            document_title = str(document.title or document.document_id).strip()[:500]
            try:
                canonical = resolve_canonical_objective_source(
                    document,
                    source_kind=item.source_kind,
                    source_ref=item.source_ref,
                )
            except ValueError as exc:
                raise ChatSourceContextError(
                    "selected Source kind is not supported"
                ) from exc
            except FileNotFoundError as exc:
                raise ChatSourceContextError(
                    "selected Source reference does not identify a canonical Source "
                    "in this document"
                ) from exc

            heading_path = (
                str(canonical.heading_path).strip()[:1000]
                if canonical.heading_path is not None
                else None
            )
            canonical_content = str(canonical.content or "")
            normalized_content = normalize_source_text(canonical_content)
            normalized_quote = normalize_source_text(item.quote)
            if not normalized_quote or normalized_quote not in normalized_content:
                raise ChatSourceContextError(
                    "selected Source quote is not contained in the canonical Source"
                )
            digest = sha256(canonical_content.encode("utf-8")).hexdigest()
            if item.source_digest is not None and item.source_digest != digest:
                raise ChatSourceContextError(
                    "selected Source digest does not match the canonical Source"
                )
            query = {
                "view": "parsed-paper",
                "source_ref": item.source_ref,
            }
            if canonical.page is not None:
                query["page"] = str(canonical.page)
            canonical_contexts.append(
                ChatSourceContext(
                    resource_ref=ChatResourceRef(
                        resource_type="source",
                        resource_id=f"{item.document_id}:{item.source_ref}",
                        href=(
                            f"/collections/{session.collection_id}/documents/"
                            f"{item.document_id}?{urlencode(query)}"
                        ),
                    ),
                    collection_id=session.collection_id,
                    document_id=item.document_id,
                    document_title=document_title,
                    source_kind=item.source_kind,
                    source_ref=item.source_ref,
                    page=canonical.page,
                    quote=normalized_quote,
                    heading_path=heading_path,
                    quote_truncated=(
                        item.quote_truncated
                        or normalized_quote != normalized_content
                    ),
                    source_digest=digest,
                )
            )
        return tuple(canonical_contexts)

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
            return {"status": "completed", "completion_reason": "model_answer", "messages": (), "pending_approval": None}
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

        async with self.repository.session_execution(session_id):
            claimed = await self.repository.claim_approved_tool_call(
                session_id=session_id,
                tool_call_id=tool_call_id,
                user_id=user_id,
                started_at=_now_iso(),
            )
            if claimed is None:
                current = await self.repository.read_tool_call(tool_call_id)
                if current is not None and current.status is ToolCallStatus.SUCCEEDED:
                    return {
                        "status": "completed", "completion_reason": "model_answer",
                        "messages": (), "pending_approval": None,
                    }
                if current is not None and current.status is ToolCallStatus.FAILED:
                    return {
                        "status": "failed", "messages": (), "pending_approval": None,
                        "error_code": current.error_code,
                    }
                raise ValueError("approved research action is already running")
            previous_messages = await self.repository.read_messages(session_id)
            run_result = await self._run_response(
                session,
                previous_messages=previous_messages,
                claimed_call=claimed,
            )
        return self._turn_record(
            run_result,
            previous_count=len(previous_messages),
        )

    def _trajectory_checkpoint(
        self,
        session: ChatSession,
        *,
        on_saved: Callable[[tuple[ChatMessage, ...]], Awaitable[None]] | None = None,
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
            if on_saved is not None:
                await on_saved(messages)

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
            "completion_reason": result.completion_reason.value if result.completion_reason else None,
            "warnings": result.warnings,
            "messages": result.messages[previous_count:],
            "pending_approval": result.pending_approval,
            "error_code": result.error_code,
        }


__all__ = [
    "ChatApprovalPendingError",
    "ChatSessionNotFoundError",
    "ChatSourceContextError",
    "ChatSessionService",
]
