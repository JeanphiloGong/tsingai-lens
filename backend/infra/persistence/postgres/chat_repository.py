"""PostgreSQL persistence for Chat sessions and ordered trajectories."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import json
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolRequest,
    ChatToolResult,
    ToolCallStatus,
)
from domain.chat.feedback import ChatMessageFeedback
from application.repositories.chat_repository import ChatResponseSnapshot, ChatSessionBusyError
from infra.persistence.postgres.models.chat import (
    ChatMessageFeedbackRow,
    ChatMessageRow,
    ChatSessionRow,
    ChatToolCallRow,
)


class PostgresChatRepository:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    @asynccontextmanager
    async def session_execution(self, session_id: str):
        # Transaction locks are released even when the worker disconnects or crashes.
        async with self.session_factory.begin() as database:
            acquired = await database.scalar(select(func.pg_try_advisory_xact_lock(
                func.hashtextextended(f"chat-execution:{session_id}", 0),
            )))
            if not acquired:
                raise ChatSessionBusyError()
            # Long model runs must not exhaust the pool needed by their checkpoints.
            connection = await database.connection()
            connection.sync_connection.detach()
            yield

    async def is_session_running(self, session_id: str) -> bool:
        async with self.session_factory.begin() as database:
            return not await database.scalar(select(func.pg_try_advisory_xact_lock(
                func.hashtextextended(f"chat-execution:{session_id}", 0),
            )))

    async def read_response_snapshot(self, session_id: str) -> ChatResponseSnapshot | None:
        async with self.session_factory() as database:
            payload = await database.scalar(select(ChatSessionRow.response_snapshot).where(
                ChatSessionRow.session_id == session_id,
            ))
            if payload is None:
                return None
            return ChatResponseSnapshot(**{
                **payload,
                "warnings": tuple(payload.get("warnings") or ()),
            })

    async def save_response_snapshot(self, session_id: str, snapshot: ChatResponseSnapshot) -> None:
        payload = asdict(snapshot)
        async with self.session_factory.begin() as database:
            await database.execute(update(ChatSessionRow).where(
                ChatSessionRow.session_id == session_id,
            ).values(response_snapshot=payload))

    async def read_session_family(self, session: ChatSession) -> tuple[ChatSession, ...]:
        root_id = session.root_session_id or session.session_id
        async with self.session_factory() as database:
            rows = await database.scalars(select(ChatSessionRow).where(
                ChatSessionRow.user_id == session.user_id,
                ChatSessionRow.collection_id == session.collection_id,
                or_(ChatSessionRow.session_id == root_id, ChatSessionRow.root_session_id == root_id),
            ).order_by(ChatSessionRow.created_at, ChatSessionRow.session_id))
            return tuple(_session_record(row) for row in rows)

    async def add_branch(
        self, *, session: ChatSession, source_session_id: str, before_position: int,
    ) -> ChatSession:
        async with self.session_factory.begin() as database:
            await database.execute(select(func.pg_advisory_xact_lock(
                func.hashtextextended(f"chat-branch:{session.session_id}", 0),
            )))
            source = await database.get(ChatSessionRow, source_session_id, with_for_update=True)
            if source is None or (source.user_id, source.collection_id) != (session.user_id, session.collection_id):
                raise ValueError("branch source must be an owned conversation")
            existing = await database.get(ChatSessionRow, session.session_id)
            if existing is not None:
                saved = _session_record(existing)
                if (saved.user_id, saved.collection_id, saved.parent_session_id,
                    saved.fork_message_id, saved.fork_content) != (
                    session.user_id, session.collection_id, session.parent_session_id,
                    session.fork_message_id, session.fork_content,
                ):
                    raise ValueError("branch request identity was reused for a different revision")
                return saved
            rows = tuple(await database.scalars(select(ChatMessageRow).where(
                ChatMessageRow.session_id == source_session_id,
                ChatMessageRow.position < before_position,
            ).order_by(ChatMessageRow.position)))
            if len(rows) != before_position:
                raise ValueError("branch position is outside the saved trajectory")
            calls = tuple(await database.scalars(select(ChatToolCallRow).where(
                ChatToolCallRow.session_id == source_session_id,
            )))
            if any(call.status not in {"succeeded", "failed", "rejected"} for call in calls):
                raise ChatSessionBusyError()
            message_ids = {row.message_id: f"msg_{uuid4().hex}" for row in rows}
            copied_calls = [call for call in calls if call.assistant_message_id in message_ids]
            call_ids = {call.tool_call_id: f"call_{uuid4().hex}" for call in copied_calls}
            result_ids = {row.tool_call_id for row in rows if row.role == "tool"}
            if set(call_ids) != result_ids:
                raise ValueError("branch history has unresolved tool results")
            database.add(ChatSessionRow(**{
                **session.to_record(),
                "created_at": _datetime(session.created_at),
                "updated_at": _datetime(session.updated_at),
            }))
            await database.flush()
            for row in rows:
                content = row.content
                if row.role == "tool":
                    payload = json.loads(content)
                    payload["tool_call_id"] = call_ids[row.tool_call_id]
                    content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                database.add(ChatMessageRow(
                    message_id=message_ids[row.message_id], session_id=session.session_id,
                    position=row.position, role=row.role, content=content,
                    tool_call_id=call_ids.get(row.tool_call_id),
                    source_contexts=row.source_contexts, created_at=row.created_at,
                ))
            await database.flush()
            for call in copied_calls:
                values = {column.name: getattr(call, column.name) for column in ChatToolCallRow.__table__.columns}
                values.update(
                    tool_call_id=call_ids[call.tool_call_id], session_id=session.session_id,
                    assistant_message_id=message_ids[call.assistant_message_id],
                )
                # Historical decisions describe completed work; only fresh calls can be approved.
                database.add(ChatToolCallRow(**values))
            return session

    async def add_session(self, record: ChatSession) -> None:
        async with self.session_factory.begin() as session:
            session.add(
                ChatSessionRow(
                    session_id=record.session_id,
                    user_id=record.user_id,
                    collection_id=record.collection_id,
                    created_at=_datetime(record.created_at),
                    updated_at=_datetime(record.updated_at),
                )
            )

    async def read_session(self, session_id: str) -> ChatSession | None:
        async with self.session_factory() as session:
            row = await session.get(ChatSessionRow, session_id)
            return _session_record(row) if row is not None else None

    async def read_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        async with self.session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ChatMessageRow)
                    .where(ChatMessageRow.session_id == session_id)
                    .order_by(ChatMessageRow.position)
                )
            )
            call_rows = tuple(
                await session.scalars(
                    select(ChatToolCallRow)
                    .where(ChatToolCallRow.session_id == session_id)
                    .order_by(ChatToolCallRow.assistant_message_id, ChatToolCallRow.position)
                )
            )
            calls_by_id = {row.tool_call_id: row for row in call_rows}
            requests: dict[str, list[ChatToolRequest]] = {}
            for call_row in call_rows:
                requests.setdefault(call_row.assistant_message_id, []).append(_call_record(call_row).to_request())
            return tuple(
                _message_record(
                    row,
                    calls_by_id.get(row.tool_call_id) if row.role == "tool" else None,
                    tuple(requests.get(row.message_id, ())),
                )
                for row in rows
            )

    async def read_message(self, message_id: str) -> ChatMessage | None:
        async with self.session_factory() as session:
            row = await session.get(ChatMessageRow, message_id)
            if row is None:
                return None
            requests = tuple(
                _call_record(call).to_request()
                for call in await session.scalars(
                    select(ChatToolCallRow)
                    .where(ChatToolCallRow.assistant_message_id == message_id)
                    .order_by(ChatToolCallRow.position)
                )
            )
            result = (
                await session.get(ChatToolCallRow, row.tool_call_id)
                if row.role == "tool" and row.tool_call_id else None
            )
            return _message_record(row, result, requests)

    async def read_feedback(
        self, session_id: str, user_id: str
    ) -> tuple[ChatMessageFeedback, ...]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(ChatMessageFeedbackRow).where(
                    ChatMessageFeedbackRow.session_id == session_id,
                    ChatMessageFeedbackRow.user_id == user_id,
                ).order_by(ChatMessageFeedbackRow.created_at, ChatMessageFeedbackRow.feedback_id)
            )
            return tuple(_feedback_record(row) for row in rows)

    async def save_feedback(self, feedback: ChatMessageFeedback) -> ChatMessageFeedback:
        row = ChatMessageFeedbackRow
        statement = insert(row).values(
            feedback_id=feedback.feedback_id,
            session_id=feedback.session_id,
            message_id=feedback.message_id,
            user_id=feedback.user_id,
            rating=feedback.rating,
            reason=feedback.reason,
            comment=feedback.comment,
            response_digest=feedback.response_digest,
            created_at=_datetime(feedback.created_at),
            updated_at=_datetime(feedback.updated_at),
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_chat_message_feedback_user_message",
            set_={
                "rating": statement.excluded.rating,
                "reason": statement.excluded.reason,
                "comment": statement.excluded.comment,
                "response_digest": statement.excluded.response_digest,
                "updated_at": func.greatest(row.updated_at, statement.excluded.updated_at),
            },
            where=or_(
                row.rating != statement.excluded.rating,
                row.reason.is_distinct_from(statement.excluded.reason),
                row.comment.is_distinct_from(statement.excluded.comment),
                row.response_digest != statement.excluded.response_digest,
            ),
        ).returning(row)
        async with self.session_factory.begin() as session:
            saved = (await session.scalars(statement)).one_or_none()
            if saved is None:
                # An identical PUT keeps the original timestamps as well as identity.
                saved = (await session.scalars(select(row).where(
                    row.user_id == feedback.user_id, row.message_id == feedback.message_id,
                ))).one()
            return _feedback_record(saved)

    async def delete_feedback(
        self, *, session_id: str, message_id: str, user_id: str
    ) -> None:
        async with self.session_factory.begin() as session:
            await session.execute(delete(ChatMessageFeedbackRow).where(
                ChatMessageFeedbackRow.session_id == session_id,
                ChatMessageFeedbackRow.message_id == message_id,
                ChatMessageFeedbackRow.user_id == user_id,
            ))

    async def read_tool_call(self, tool_call_id: str) -> ChatToolCall | None:
        async with self.session_factory() as session:
            row = await session.get(ChatToolCallRow, tool_call_id)
            return _call_record(row) if row is not None else None

    async def save_trajectory(
        self,
        *,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        tool_calls: tuple[ChatToolCall, ...],
        tool_results: tuple[ChatToolResult, ...],
    ) -> None:
        if any(message.session_id != session.session_id for message in messages):
            raise ValueError("chat message belongs to another session")
        if any(call.session_id != session.session_id for call in tool_calls):
            raise ValueError("chat tool call belongs to another session")
        async with self.session_factory.begin() as database:
            session_row = await database.get(
                ChatSessionRow, session.session_id, with_for_update=True
            )
            if session_row is None:
                raise ValueError(f"chat session not found: {session.session_id}")
            if (
                session_row.user_id != session.user_id
                or session_row.collection_id != session.collection_id
            ):
                raise ValueError("session identity cannot be reassigned")

            existing_messages = tuple(
                await database.scalars(
                    select(ChatMessageRow)
                    .where(ChatMessageRow.session_id == session.session_id)
                    .order_by(ChatMessageRow.position)
                )
            )
            existing_ids = tuple(row.message_id for row in existing_messages)
            incoming_ids = tuple(message.message_id for message in messages)
            if incoming_ids[: len(existing_ids)] != existing_ids:
                raise ValueError("chat trajectory is append-only")
            session_row.updated_at = _datetime(session.updated_at)

            for position, message in enumerate(messages[len(existing_ids) :], len(existing_ids)):
                if (
                    await database.get(ChatMessageRow, message.message_id)
                    is not None
                ):
                    raise ValueError("message identity cannot be reassigned")
                database.add(
                    ChatMessageRow(
                        message_id=message.message_id,
                        session_id=message.session_id,
                        position=position,
                        role=message.role.value,
                        content=message.content,
                        tool_call_id=message.tool_call_id,
                        source_contexts=[
                            item.to_record() for item in message.source_contexts
                        ],
                        created_at=_datetime(message.created_at),
                    )
                )
            await database.flush()

            for call in tool_calls:
                assistant = next((message for message in messages if message.message_id == call.assistant_message_id), None)
                if assistant is None or call.to_request() not in assistant.tool_calls:
                    raise ValueError("tool call must match its assistant request")
                row = await database.get(ChatToolCallRow, call.tool_call_id)
                if row is None:
                    row = ChatToolCallRow(
                        tool_call_id=call.tool_call_id,
                        session_id=call.session_id,
                        assistant_message_id=call.assistant_message_id,
                        name=call.name,
                        position=call.position,
                        arguments=dict(call.arguments),
                        arguments_digest=call.arguments_digest,
                        risk=call.risk.value,
                        status=call.status.value,
                    )
                    database.add(row)
                elif (
                    row.session_id != call.session_id
                    or row.assistant_message_id != call.assistant_message_id
                    or row.name != call.name
                    or row.arguments_digest != call.arguments_digest
                    or row.position != call.position
                ):
                    raise ValueError("tool call identity cannot be reassigned")
                _update_call_row(row, call)
            await database.flush()

            for message in messages:
                for request in message.tool_calls:
                    call_row = await database.get(ChatToolCallRow, request.tool_call_id)
                    if (call_row is None or call_row.session_id != session.session_id
                            or call_row.assistant_message_id != message.message_id
                            or _call_record(call_row).to_request() != request):
                        raise ValueError("assistant request must have an identical durable call")

            for result in tool_results:
                call_row = await database.get(
                    ChatToolCallRow, result.tool_call_id
                )
                if call_row is None or call_row.session_id != session.session_id:
                    raise ValueError("tool result belongs to an unknown call")
                call_row.result_status = result.status.value
                call_row.result_data = dict(result.data)
                call_row.result_resource_refs = [
                    item.to_record() for item in result.resource_refs
                ]
                call_row.result_warnings = list(result.warnings)
                call_row.result_error_code = result.error_code
                call_row.result_error_message = result.error_message

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
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        async with self.session_factory.begin() as database:
            session_row = await database.get(ChatSessionRow, session_id)
            if session_row is None or session_row.user_id != user_id:
                raise FileNotFoundError(f"chat session not found: {session_id}")
            row = await database.get(
                ChatToolCallRow, tool_call_id, with_for_update=True
            )
            if row is None or row.session_id != session_id:
                raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
            call = _call_record(row)
            expected_status = (
                ToolCallStatus.APPROVED
                if decision == "approved"
                else ToolCallStatus.REJECTED
            )
            if call.status is expected_status:
                if (
                    call.decision_user_id == user_id
                    and call.decision_arguments_digest == arguments_digest
                ):
                    return call
                raise ValueError("tool call was decided with different authority")
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
            _update_call_row(row, decided)
            return decided

    async def claim_approved_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        started_at: str,
    ) -> ChatToolCall | None:
        async with self.session_factory.begin() as database:
            session_row = await database.get(ChatSessionRow, session_id)
            if session_row is None or session_row.user_id != user_id:
                raise FileNotFoundError(f"chat session not found: {session_id}")
            row = await database.get(
                ChatToolCallRow, tool_call_id, with_for_update=True
            )
            if row is None or row.session_id != session_id:
                raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
            call = _call_record(row)
            if call.status is ToolCallStatus.APPROVED:
                claimed = call.start(started_at)
                _update_call_row(row, claimed)
                return claimed
            if call.status in {
                ToolCallStatus.RUNNING,
                ToolCallStatus.SUCCEEDED,
                ToolCallStatus.FAILED,
            }:
                return None
            raise ValueError(
                f"cannot claim tool call in status {call.status.value}"
            )


def _update_call_row(row: ChatToolCallRow, call: ChatToolCall) -> None:
    row.status = call.status.value
    row.started_at = _optional_datetime(call.started_at)
    row.finished_at = _optional_datetime(call.finished_at)
    row.error_code = call.error_code
    row.decision_user_id = call.decision_user_id
    row.decision_arguments_digest = call.decision_arguments_digest
    row.decided_at = _optional_datetime(call.decided_at)


def _session_record(row: ChatSessionRow) -> ChatSession:
    return ChatSession(
        session_id=row.session_id,
        user_id=row.user_id,
        collection_id=row.collection_id,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        root_session_id=row.root_session_id,
        parent_session_id=row.parent_session_id,
        fork_message_id=row.fork_message_id,
        fork_position=row.fork_position,
        fork_content=row.fork_content,
    )


def _call_record(row: ChatToolCallRow) -> ChatToolCall:
    return ChatToolCall.from_mapping(
        {
            "tool_call_id": row.tool_call_id,
            "session_id": row.session_id,
            "assistant_message_id": row.assistant_message_id,
            "position": row.position,
            "name": row.name,
            "arguments": dict(row.arguments),
            "arguments_digest": row.arguments_digest,
            "risk": row.risk,
            "status": row.status,
            "started_at": _optional_iso(row.started_at),
            "finished_at": _optional_iso(row.finished_at),
            "error_code": row.error_code,
            "decision_user_id": row.decision_user_id,
            "decision_arguments_digest": row.decision_arguments_digest,
            "decided_at": _optional_iso(row.decided_at),
        }
    )


def _message_record(
    row: ChatMessageRow,
    result: ChatToolCallRow | None,
    requests: tuple[ChatToolRequest, ...],
) -> ChatMessage:
    return ChatMessage.from_mapping(
        {
            "message_id": row.message_id,
            "session_id": row.session_id,
            "role": row.role,
            "content": row.content,
            "created_at": _iso(row.created_at),
            "tool_call_id": row.tool_call_id,
            "tool_calls": [request.to_record() for request in requests],
            "tool_result": _result_record(result) if result is not None else None,
            "source_contexts": list(row.source_contexts),
        }
    )


def _feedback_record(row: ChatMessageFeedbackRow) -> ChatMessageFeedback:
    return ChatMessageFeedback(
        feedback_id=row.feedback_id,
        session_id=row.session_id,
        message_id=row.message_id,
        user_id=row.user_id,
        rating=row.rating,
        reason=row.reason,
        comment=row.comment,
        response_digest=row.response_digest,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _result_record(row: ChatToolCallRow) -> dict:
    return {
        "tool_call_id": row.tool_call_id,
        "status": row.result_status,
        "data": dict(row.result_data or {}),
        "resource_refs": list(row.result_resource_refs or []),
        "warnings": list(row.result_warnings or []),
        "error_code": row.result_error_code,
        "error_message": row.result_error_message,
    }


def _datetime(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_datetime(value: str | datetime | None) -> datetime | None:
    return None if value is None else _datetime(value)


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


def _optional_iso(value: datetime | None) -> str | None:
    return _iso(value) if value is not None else None


__all__ = ["PostgresChatRepository"]
