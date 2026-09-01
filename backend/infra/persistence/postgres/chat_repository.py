"""PostgreSQL persistence for Chat sessions and ordered trajectories."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
)
from infra.persistence.postgres.models.chat import (
    ChatMessageRow,
    ChatSessionRow,
    ChatToolCallRow,
    ChatToolResultRow,
)


class PostgresChatRepository:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

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
            result_ids = {
                row.tool_call_id
                for row in rows
                if row.role == "tool" and row.tool_call_id is not None
            }
            results = {
                row.tool_call_id: row
                for row in await session.scalars(
                    select(ChatToolResultRow).where(
                        ChatToolResultRow.tool_call_id.in_(result_ids)
                    )
                )
            } if result_ids else {}
            return tuple(
                _message_record(
                    row,
                    results.get(row.tool_call_id) if row.role == "tool" else None,
                )
                for row in rows
            )

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
                ChatSessionRow, session.session_id
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
                        tool_name=message.tool_name,
                        tool_arguments=(
                            dict(message.tool_arguments)
                            if message.tool_arguments is not None
                            else None
                        ),
                        source_contexts=[
                            item.to_record() for item in message.source_contexts
                        ],
                        created_at=_datetime(message.created_at),
                    )
                )
            await database.flush()

            for call in tool_calls:
                row = await database.get(ChatToolCallRow, call.tool_call_id)
                if row is None:
                    row = ChatToolCallRow(
                        tool_call_id=call.tool_call_id,
                        session_id=call.session_id,
                        assistant_message_id=call.assistant_message_id,
                        name=call.name,
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
                ):
                    raise ValueError("tool call identity cannot be reassigned")
                _update_call_row(row, call)
            await database.flush()

            for result in tool_results:
                call_row = await database.get(
                    ChatToolCallRow, result.tool_call_id
                )
                if call_row is None or call_row.session_id != session.session_id:
                    raise ValueError("tool result belongs to an unknown call")
                row = await database.get(
                    ChatToolResultRow, result.tool_call_id
                )
                if row is None:
                    row = ChatToolResultRow(
                        tool_call_id=result.tool_call_id,
                        status=result.status.value,
                        data={},
                        resource_refs=[],
                        warnings=[],
                    )
                    database.add(row)
                row.status = result.status.value
                row.data = dict(result.data)
                row.resource_refs = [item.to_record() for item in result.resource_refs]
                row.warnings = list(result.warnings)
                row.error_code = result.error_code
                row.error_message = result.error_message

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
    )


def _call_record(row: ChatToolCallRow) -> ChatToolCall:
    return ChatToolCall.from_mapping(
        {
            "tool_call_id": row.tool_call_id,
            "session_id": row.session_id,
            "assistant_message_id": row.assistant_message_id,
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
    result: ChatToolResultRow | None,
) -> ChatMessage:
    return ChatMessage.from_mapping(
        {
            "message_id": row.message_id,
            "session_id": row.session_id,
            "role": row.role,
            "content": row.content,
            "created_at": _iso(row.created_at),
            "tool_call_id": row.tool_call_id,
            "tool_name": row.tool_name,
            "tool_arguments": row.tool_arguments,
            "tool_result": _result_record(result) if result is not None else None,
            "source_contexts": list(row.source_contexts),
        }
    )


def _result_record(row: ChatToolResultRow) -> dict:
    return {
        "tool_call_id": row.tool_call_id,
        "status": row.status,
        "data": dict(row.data),
        "resource_refs": list(row.resource_refs),
        "warnings": list(row.warnings),
        "error_code": row.error_code,
        "error_message": row.error_message,
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
