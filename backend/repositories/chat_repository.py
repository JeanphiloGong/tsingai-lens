"""PostgreSQL repository for chat."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Protocol
from uuid import uuid4

from domain.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ChatToolRequest,
    ChatToolResult,
    ToolCallStatus,
    ToolResultStatus,
    ToolRisk,
)
from domain.chat.feedback import ChatMessageFeedback
from domain.chat.permissions import (
    change_permission,
    permits_automatic,
)
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import (
    ChatMessageFeedbackRow,
    ChatMessageRow,
    ChatSessionRow,
    ChatToolCallRow,
)
from infra.persistence.postgres.models.feedback import ChatModelCallRow
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

ModelCallPurpose = Literal["decision", "compaction", "finalization"]

ModelCallStatus = Literal[
    "recorded",
    "provider_succeeded",
    "provider_failed",
    "response_invalid",
    "cancelled",
]


@dataclass(frozen=True)
class ModelCallInput:
    session_id: str
    trigger_message_id: str | None
    response_message_id: str | None
    purpose: ModelCallPurpose
    request: Mapping[str, Any]


@dataclass(frozen=True)
class ModelCallOutcome:
    status: ModelCallStatus
    finished_at: str
    error_code: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ModelCallObserver(Protocol):
    async def start(self, call: ModelCallInput) -> str: ...

    async def finish(self, call_id: str, outcome: ModelCallOutcome) -> None: ...


class ChatWriteConflict(ValueError):
    """A rejected write under the repository's locked state."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class ChatRecordNotFound(FileNotFoundError):
    """A requested Chat record disappeared or is outside the user's scope."""


class ChatSessionBusyError(ChatWriteConflict):
    def __init__(self) -> None:
        super().__init__(
            "chat_session_busy",
            "the research response is still running; retry when it finishes",
        )


class ChatSessionHasBranchesError(ChatWriteConflict):
    def __init__(self) -> None:
        super().__init__(
            "chat_session_has_branches",
            "delete this conversation's branches before deleting their source",
        )


@dataclass(frozen=True)
class ChatModelCall:
    call_id: str
    session_id: str
    trigger_message_id: str | None
    response_message_id: str | None
    purpose: ModelCallPurpose
    model: str
    request: dict[str, Any]
    request_digest: str
    started_at: str
    status: ModelCallStatus = "recorded"
    finished_at: str | None = None
    error_code: str | None = None
    provider_confirmed: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ChatResponseSnapshot:
    response_id: str
    sequence: int
    started_at: str
    updated_at: str
    status: Literal[
        "running", "completed", "approval_required", "failed", "interrupted"
    ] = "running"
    message_id: str | None = None
    message_created_at: str | None = None
    content: str = ""
    progress: dict[str, Any] = field(default_factory=dict)
    checkpoint_message_id: str | None = None
    completion_reason: str | None = None
    error_code: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChatSessionSummary:
    """A session plus the first-question projection used by history indexes."""

    session: ChatSession
    title: str | None = None


class ChatRepository:
    async def read_permission(self, session_id, user_id):
        async with AsyncSessionLocal() as db:
            row = await db.get(ChatSessionRow, session_id)
            if row is None or row.user_id != user_id:
                raise ChatRecordNotFound("chat session not found")
            permission = {
                "mode": "confirm",
                "actions": [],
                "expires_at": None,
                "revision": 0,
            }
            if row.operation_permission:
                permission.update(row.operation_permission)
            return permission

    async def set_permission(self, session_id, user_id, **changes):
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(ChatSessionRow, session_id, with_for_update=True)
            if row is None or row.user_id != user_id:
                raise ChatRecordNotFound("chat session not found")
            row.operation_permission = change_permission(
                row.operation_permission, **changes
            )
            return dict(row.operation_permission)

    async def claim_automatic_call(
        self, *, session_id, tool_call_id, user_id, started_at
    ):
        async with AsyncSessionLocal() as db, db.begin():
            session_row = await db.get(ChatSessionRow, session_id, with_for_update=True)
            if session_row is None or session_row.user_id != user_id:
                raise ChatRecordNotFound("chat session not found")
            row = await db.get(ChatToolCallRow, tool_call_id, with_for_update=True)
            if row is None or row.session_id != session_id:
                raise ChatRecordNotFound("chat tool call not found")
            permission = {
                "mode": "confirm",
                "actions": [],
                "expires_at": None,
                "revision": 0,
            }
            if session_row.operation_permission:
                permission.update(session_row.operation_permission)
            call = ChatToolCall(
                tool_call_id=row.tool_call_id,
                session_id=row.session_id,
                assistant_message_id=row.assistant_message_id,
                position=row.position,
                name=row.name,
                arguments=dict(row.arguments),
                arguments_digest=row.arguments_digest,
                risk=ToolRisk(row.risk),
                status=ToolCallStatus(row.status),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                error_code=row.error_code,
                decision_user_id=row.decision_user_id,
                decision_arguments_digest=row.decision_arguments_digest,
                decided_at=_optional_iso(row.decided_at),
                decision_basis=row.decision_basis,
                authorization_revision=row.authorization_revision,
            )
            if (
                call.status is not ToolCallStatus.APPROVAL_REQUIRED
                or row.proposed_permission_revision != permission["revision"]
                or not permits_automatic(permission, call.name, now=started_at)
            ):
                return None
            call = replace(
                call.approve(
                    user_id=user_id,
                    arguments_digest=call.arguments_digest,
                    decided_at=started_at,
                ),
                decision_basis="scope_grant",
                authorization_revision=permission["revision"],
            )
            claimed = call.start(started_at)
            row.status = claimed.status.value
            row.started_at = _optional_datetime(claimed.started_at)
            row.finished_at = _optional_datetime(claimed.finished_at)
            row.error_code = claimed.error_code
            row.decision_user_id = claimed.decision_user_id
            row.decision_arguments_digest = claimed.decision_arguments_digest
            row.decided_at = _optional_datetime(claimed.decided_at)
            row.decision_basis = claimed.decision_basis
            row.authorization_revision = claimed.authorization_revision
            return claimed

    @asynccontextmanager
    async def session_execution(self, session_id: str):
        # Transaction locks are released even when the worker disconnects or crashes.
        async with AsyncSessionLocal() as db, db.begin():
            acquired = await db.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        func.hashtextextended(f"chat-execution:{session_id}", 0),
                    )
                )
            )
            if not acquired:
                raise ChatSessionBusyError()
            # Long model runs must not exhaust the pool needed by their checkpoints.
            connection = await db.connection()
            connection.sync_connection.detach()
            yield

    async def is_session_running(self, session_id: str) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            return not await db.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        func.hashtextextended(f"chat-execution:{session_id}", 0),
                    )
                )
            )

    async def read_response_snapshot(
        self, session_id: str
    ) -> ChatResponseSnapshot | None:
        async with AsyncSessionLocal() as db:
            payload = await db.scalar(
                select(ChatSessionRow.response_snapshot).where(
                    ChatSessionRow.session_id == session_id,
                )
            )
            if payload is None:
                return None
            return ChatResponseSnapshot(
                **{
                    **payload,
                    "warnings": tuple(payload.get("warnings") or ()),
                }
            )

    async def save_response_snapshot(
        self, session_id: str, snapshot: ChatResponseSnapshot
    ) -> None:
        payload = asdict(snapshot)
        async with AsyncSessionLocal() as db, db.begin():
            await db.execute(
                update(ChatSessionRow)
                .where(
                    ChatSessionRow.session_id == session_id,
                )
                .values(response_snapshot=payload)
            )

    async def read_session_family(
        self, chat_session: ChatSession
    ) -> tuple[ChatSession, ...]:
        root_id = chat_session.root_session_id or chat_session.session_id
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(ChatSessionRow)
                .where(
                    ChatSessionRow.user_id == chat_session.user_id,
                    ChatSessionRow.collection_id == chat_session.collection_id,
                    or_(
                        ChatSessionRow.session_id == root_id,
                        ChatSessionRow.root_session_id == root_id,
                    ),
                )
                .order_by(ChatSessionRow.created_at, ChatSessionRow.session_id)
            )
            return tuple(
                ChatSession(
                    session_id=row.session_id,
                    user_id=row.user_id,
                    collection_id=row.collection_id,
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    status=(
                        {"approval_required": "approval", "running": "running"}.get(
                            (row.response_snapshot or {}).get("status"), "idle"
                        )
                    ),
                    is_pinned=row.is_pinned,
                    root_session_id=row.root_session_id,
                    parent_session_id=row.parent_session_id,
                    fork_message_id=row.fork_message_id,
                    fork_position=row.fork_position,
                    fork_content=row.fork_content,
                    title=row.title,
                )
                for row in rows
            )

    async def add_branch(
        self,
        *,
        chat_session: ChatSession,
        source_session_id: str,
        before_position: int,
    ) -> ChatSession:
        async with AsyncSessionLocal() as db, db.begin():
            await db.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(
                            f"chat-branch:{chat_session.session_id}", 0
                        ),
                    )
                )
            )
            source = await db.get(
                ChatSessionRow, source_session_id, with_for_update=True
            )
            if source is None or (source.user_id, source.collection_id) != (
                chat_session.user_id,
                chat_session.collection_id,
            ):
                raise ChatWriteConflict(
                    "chat_branch_invalid", "branch source must be an owned conversation"
                )
            existing = await db.get(ChatSessionRow, chat_session.session_id)
            if existing is not None:
                saved = ChatSession(
                    session_id=existing.session_id,
                    user_id=existing.user_id,
                    collection_id=existing.collection_id,
                    created_at=_iso(existing.created_at),
                    updated_at=_iso(existing.updated_at),
                    status=(
                        {"approval_required": "approval", "running": "running"}.get(
                            (existing.response_snapshot or {}).get("status"), "idle"
                        )
                    ),
                    is_pinned=existing.is_pinned,
                    root_session_id=existing.root_session_id,
                    parent_session_id=existing.parent_session_id,
                    fork_message_id=existing.fork_message_id,
                    fork_position=existing.fork_position,
                    fork_content=existing.fork_content,
                    title=existing.title,
                )
                if (
                    saved.user_id,
                    saved.collection_id,
                    saved.parent_session_id,
                    saved.fork_message_id,
                    saved.fork_content,
                ) != (
                    chat_session.user_id,
                    chat_session.collection_id,
                    chat_session.parent_session_id,
                    chat_session.fork_message_id,
                    chat_session.fork_content,
                ):
                    raise ChatWriteConflict(
                        "chat_branch_invalid",
                        "branch request identity was reused for a different revision",
                    )
                return saved
            rows = tuple(
                await db.scalars(
                    select(ChatMessageRow)
                    .where(
                        ChatMessageRow.session_id == source_session_id,
                        ChatMessageRow.position < before_position,
                    )
                    .order_by(ChatMessageRow.position)
                )
            )
            if len(rows) != before_position:
                raise ChatWriteConflict(
                    "chat_branch_invalid",
                    "branch position is outside the saved trajectory",
                )
            calls = tuple(
                await db.scalars(
                    select(ChatToolCallRow).where(
                        ChatToolCallRow.session_id == source_session_id,
                    )
                )
            )
            if any(
                call.status not in {"succeeded", "failed", "rejected"} for call in calls
            ):
                raise ChatSessionBusyError()
            message_ids = {row.message_id: f"msg_{uuid4().hex}" for row in rows}
            copied_calls = [
                call for call in calls if call.assistant_message_id in message_ids
            ]
            call_ids = {
                call.tool_call_id: f"call_{uuid4().hex}" for call in copied_calls
            }
            result_ids = {row.tool_call_id for row in rows if row.role == "tool"}
            if set(call_ids) != result_ids:
                raise ChatWriteConflict(
                    "chat_branch_invalid", "branch history has unresolved tool results"
                )
            db.add(
                ChatSessionRow(
                    session_id=chat_session.session_id,
                    user_id=chat_session.user_id,
                    collection_id=chat_session.collection_id,
                    created_at=_datetime(chat_session.created_at),
                    updated_at=_datetime(chat_session.updated_at),
                    root_session_id=chat_session.root_session_id,
                    parent_session_id=chat_session.parent_session_id,
                    fork_message_id=chat_session.fork_message_id,
                    fork_position=chat_session.fork_position,
                    fork_content=chat_session.fork_content,
                )
            )
            await db.flush()
            for row in rows:
                content = row.content
                if row.role == "tool":
                    payload = json.loads(content)
                    payload["tool_call_id"] = call_ids[row.tool_call_id]
                    content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                db.add(
                    ChatMessageRow(
                        message_id=message_ids[row.message_id],
                        session_id=chat_session.session_id,
                        position=row.position,
                        role=row.role,
                        content=content,
                        tool_call_id=call_ids.get(row.tool_call_id),
                        source_contexts=row.source_contexts,
                        created_at=row.created_at,
                    )
                )
            await db.flush()
            for call in copied_calls:
                values = {
                    column.name: getattr(call, column.name)
                    for column in ChatToolCallRow.__table__.columns
                }
                values.update(
                    tool_call_id=call_ids[call.tool_call_id],
                    session_id=chat_session.session_id,
                    assistant_message_id=message_ids[call.assistant_message_id],
                )
                # Historical decisions describe completed work; only fresh calls can be approved.
                db.add(ChatToolCallRow(**values))
            return chat_session

    async def add_session(self, record: ChatSession) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            db.add(
                ChatSessionRow(
                    session_id=record.session_id,
                    user_id=record.user_id,
                    collection_id=record.collection_id,
                    created_at=_datetime(record.created_at),
                    updated_at=_datetime(record.updated_at),
                    is_pinned=record.is_pinned,
                    title=record.title,
                )
            )

    async def read_session(self, session_id: str) -> ChatSession | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(ChatSessionRow, session_id)
            return (
                ChatSession(
                    session_id=row.session_id,
                    user_id=row.user_id,
                    collection_id=row.collection_id,
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    status=(
                        {"approval_required": "approval", "running": "running"}.get(
                            (row.response_snapshot or {}).get("status"), "idle"
                        )
                    ),
                    is_pinned=row.is_pinned,
                    root_session_id=row.root_session_id,
                    parent_session_id=row.parent_session_id,
                    fork_message_id=row.fork_message_id,
                    fork_position=row.fork_position,
                    fork_content=row.fork_content,
                    title=row.title,
                )
                if row is not None
                else None
            )

    async def delete_session(self, *, session_id: str, user_id: str) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            acquired = await db.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        func.hashtextextended(f"chat-execution:{session_id}", 0),
                    )
                )
            )
            if not acquired:
                raise ChatSessionBusyError()
            row = await db.get(ChatSessionRow, session_id, with_for_update=True)
            if row is None or row.user_id != user_id:
                raise ChatRecordNotFound("chat session not found")
            dependent = await db.scalar(
                select(ChatSessionRow.session_id)
                .where(
                    ChatSessionRow.user_id == user_id,
                    ChatSessionRow.collection_id == row.collection_id,
                    or_(
                        ChatSessionRow.parent_session_id == session_id,
                        ChatSessionRow.root_session_id == session_id,
                    ),
                )
                .limit(1)
            )
            if dependent is not None:
                raise ChatSessionHasBranchesError()
            await db.delete(row)

    async def set_session_pin(
        self,
        *,
        session_id: str,
        user_id: str,
        is_pinned: bool,
    ) -> ChatSession:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(ChatSessionRow, session_id, with_for_update=True)
            if row is None or row.user_id != user_id:
                raise ChatRecordNotFound("chat session not found")
            row.is_pinned = is_pinned
            return ChatSession(
                session_id=row.session_id,
                user_id=row.user_id,
                collection_id=row.collection_id,
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                status=(
                    {"approval_required": "approval", "running": "running"}.get(
                        (row.response_snapshot or {}).get("status"), "idle"
                    )
                ),
                is_pinned=row.is_pinned,
                root_session_id=row.root_session_id,
                parent_session_id=row.parent_session_id,
                fork_message_id=row.fork_message_id,
                fork_position=row.fork_position,
                fork_content=row.fork_content,
                title=row.title,
            )

    async def set_session_title(
        self,
        *,
        session_id: str,
        user_id: str,
        title: str,
    ) -> ChatSession:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(ChatSessionRow, session_id, with_for_update=True)
            if row is None or row.user_id != user_id:
                raise ChatRecordNotFound("chat session not found")
            row.title = title
            return ChatSession(
                session_id=row.session_id,
                user_id=row.user_id,
                collection_id=row.collection_id,
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                status=(
                    {"approval_required": "approval", "running": "running"}.get(
                        (row.response_snapshot or {}).get("status"), "idle"
                    )
                ),
                is_pinned=row.is_pinned,
                root_session_id=row.root_session_id,
                parent_session_id=row.parent_session_id,
                fork_message_id=row.fork_message_id,
                fork_position=row.fork_position,
                fork_content=row.fork_content,
                title=row.title,
            )

    async def list_sessions(
        self, *, user_id: str, collection_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[ChatSessionSummary, ...]:
        async with AsyncSessionLocal() as db:
            first_user_message = (
                select(ChatMessageRow.content)
                .where(
                    ChatMessageRow.session_id == ChatSessionRow.session_id,
                    ChatMessageRow.role == "user",
                )
                .order_by(ChatMessageRow.position)
                .limit(1)
                .scalar_subquery()
            )
            rows = await db.execute(
                select(ChatSessionRow, first_user_message.label("first_message_title"))
                .where(
                    ChatSessionRow.user_id == user_id,
                    ChatSessionRow.collection_id == collection_id,
                )
                .order_by(
                    ChatSessionRow.is_pinned.desc(),
                    ChatSessionRow.updated_at.desc(),
                    ChatSessionRow.session_id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
            return tuple(
                ChatSessionSummary(
                    session=ChatSession(
                        session_id=row.session_id,
                        user_id=row.user_id,
                        collection_id=row.collection_id,
                        created_at=_iso(row.created_at),
                        updated_at=_iso(row.updated_at),
                        status=(
                            {"approval_required": "approval", "running": "running"}.get(
                                (row.response_snapshot or {}).get("status"), "idle"
                            )
                        ),
                        is_pinned=row.is_pinned,
                        root_session_id=row.root_session_id,
                        parent_session_id=row.parent_session_id,
                        fork_message_id=row.fork_message_id,
                        fork_position=row.fork_position,
                        fork_content=row.fork_content,
                        title=row.title,
                    ),
                    title=(row.title or title or "")
                    .strip()
                    .split("\n", 1)[0]
                    .strip()[:160]
                    or None,
                )
                for row, title in rows.all()
            )

    async def read_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        async with AsyncSessionLocal() as db:
            rows = tuple(
                await db.scalars(
                    select(ChatMessageRow)
                    .where(ChatMessageRow.session_id == session_id)
                    .order_by(ChatMessageRow.position)
                )
            )
            call_rows = tuple(
                await db.scalars(
                    select(ChatToolCallRow)
                    .where(ChatToolCallRow.session_id == session_id)
                    .order_by(
                        ChatToolCallRow.assistant_message_id, ChatToolCallRow.position
                    )
                )
            )
            calls_by_id = {row.tool_call_id: row for row in call_rows}
            requests: dict[str, list[ChatToolRequest]] = {}
            for call_row in call_rows:
                requests.setdefault(call_row.assistant_message_id, []).append(
                    ChatToolRequest(
                        tool_call_id=call_row.tool_call_id,
                        name=call_row.name,
                        arguments=call_row.arguments,
                        position=call_row.position,
                        decision_user_id=call_row.decision_user_id,
                        decision_arguments_digest=call_row.decision_arguments_digest,
                        decided_at=_optional_iso(call_row.decided_at),
                        decision_basis=call_row.decision_basis,
                        authorization_revision=call_row.authorization_revision,
                    )
                )
            messages: list[ChatMessage] = []
            for row in rows:
                result_row = (
                    calls_by_id.get(row.tool_call_id) if row.role == "tool" else None
                )
                tool_result = None
                if result_row is not None:
                    tool_result = ChatToolResult(
                        tool_call_id=result_row.tool_call_id,
                        status=ToolResultStatus(result_row.result_status),
                        data=result_row.result_data,
                        resource_refs=tuple(
                            ChatResourceRef(
                                resource_type=item["resource_type"],
                                resource_id=item["resource_id"],
                                href=item.get("href"),
                            )
                            for item in result_row.result_resource_refs or ()
                        ),
                        warnings=tuple(result_row.result_warnings),
                        error_code=result_row.result_error_code,
                        error_message=result_row.result_error_message,
                    )
                source_contexts = tuple(
                    ChatSourceContext(
                        resource_ref=ChatResourceRef(
                            resource_type=item["resource_ref"]["resource_type"],
                            resource_id=item["resource_ref"]["resource_id"],
                            href=item["resource_ref"].get("href"),
                        ),
                        collection_id=item["collection_id"],
                        document_id=item["document_id"],
                        document_title=item["document_title"],
                        source_kind=item["source_kind"],
                        source_ref=item["source_ref"],
                        page=item.get("page"),
                        quote=item["quote"],
                        heading_path=item.get("heading_path"),
                        quote_truncated=item.get("quote_truncated", False),
                        source_digest=item.get("source_digest"),
                    )
                    for item in row.source_contexts or ()
                )
                messages.append(
                    ChatMessage(
                        message_id=row.message_id,
                        session_id=row.session_id,
                        role=ChatMessageRole(row.role),
                        content=row.content,
                        created_at=_iso(row.created_at),
                        tool_call_id=row.tool_call_id,
                        tool_calls=tuple(requests.get(row.message_id, ())),
                        tool_result=tool_result,
                        source_contexts=source_contexts,
                    )
                )
            return tuple(messages)

    async def read_message(self, message_id: str) -> ChatMessage | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(ChatMessageRow, message_id)
            if row is None:
                return None
            requests = tuple(
                ChatToolRequest(
                    tool_call_id=call.tool_call_id,
                    name=call.name,
                    arguments=call.arguments,
                    position=call.position,
                    decision_user_id=call.decision_user_id,
                    decision_arguments_digest=call.decision_arguments_digest,
                    decided_at=_optional_iso(call.decided_at),
                    decision_basis=call.decision_basis,
                    authorization_revision=call.authorization_revision,
                )
                for call in await db.scalars(
                    select(ChatToolCallRow)
                    .where(ChatToolCallRow.assistant_message_id == message_id)
                    .order_by(ChatToolCallRow.position)
                )
            )
            result_row = (
                await db.get(ChatToolCallRow, row.tool_call_id)
                if row.role == "tool"
                else None
            )
            tool_result = None
            if result_row is not None:
                tool_result = ChatToolResult(
                    tool_call_id=result_row.tool_call_id,
                    status=ToolResultStatus(result_row.result_status),
                    data=result_row.result_data,
                    resource_refs=tuple(
                        ChatResourceRef(
                            resource_type=item["resource_type"],
                            resource_id=item["resource_id"],
                            href=item.get("href"),
                        )
                        for item in result_row.result_resource_refs or ()
                    ),
                    warnings=tuple(result_row.result_warnings),
                    error_code=result_row.result_error_code,
                    error_message=result_row.result_error_message,
                )
            source_contexts = tuple(
                ChatSourceContext(
                    resource_ref=ChatResourceRef(
                        resource_type=item["resource_ref"]["resource_type"],
                        resource_id=item["resource_ref"]["resource_id"],
                        href=item["resource_ref"].get("href"),
                    ),
                    collection_id=item["collection_id"],
                    document_id=item["document_id"],
                    document_title=item["document_title"],
                    source_kind=item["source_kind"],
                    source_ref=item["source_ref"],
                    page=item.get("page"),
                    quote=item["quote"],
                    heading_path=item.get("heading_path"),
                    quote_truncated=item.get("quote_truncated", False),
                    source_digest=item.get("source_digest"),
                )
                for item in row.source_contexts or ()
            )
            return ChatMessage(
                message_id=row.message_id,
                session_id=row.session_id,
                role=ChatMessageRole(row.role),
                content=row.content,
                created_at=_iso(row.created_at),
                tool_call_id=row.tool_call_id,
                tool_calls=requests,
                tool_result=tool_result,
                source_contexts=source_contexts,
            )

    async def read_feedback(
        self, session_id: str, user_id: str
    ) -> tuple[ChatMessageFeedback, ...]:
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(ChatMessageFeedbackRow)
                .where(
                    ChatMessageFeedbackRow.session_id == session_id,
                    ChatMessageFeedbackRow.user_id == user_id,
                )
                .order_by(
                    ChatMessageFeedbackRow.created_at,
                    ChatMessageFeedbackRow.feedback_id,
                )
            )
            return tuple(
                ChatMessageFeedback(
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
                for row in rows
            )

    async def read_feedback_by_id(self, feedback_id: str) -> ChatMessageFeedback | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(ChatMessageFeedbackRow, feedback_id)
            return (
                ChatMessageFeedback(
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
                if row is not None
                else None
            )

    async def start_model_call(self, call: ChatModelCall) -> ChatModelCall:
        async with AsyncSessionLocal() as db, db.begin():
            if await db.get(ChatSessionRow, call.session_id) is None:
                raise ChatRecordNotFound(f"chat session not found: {call.session_id}")
            existing = await db.get(
                ChatModelCallRow, call.call_id, with_for_update=True
            )
            if existing is not None:
                if (
                    existing.session_id != call.session_id
                    or existing.request_digest != call.request_digest
                ):
                    raise ValueError("model call identity cannot be reassigned")
                return ChatModelCall(
                    call_id=existing.call_id,
                    session_id=existing.session_id,
                    trigger_message_id=existing.trigger_message_id,
                    response_message_id=existing.response_message_id,
                    purpose=existing.purpose,
                    model=existing.model,
                    request=dict(existing.request),
                    request_digest=existing.request_digest,
                    started_at=_iso(existing.started_at),
                    status=existing.status,
                    finished_at=_optional_iso(existing.finished_at),
                    error_code=existing.error_code,
                    provider_confirmed=existing.provider_confirmed,
                    prompt_tokens=existing.prompt_tokens,
                    completion_tokens=existing.completion_tokens,
                    total_tokens=existing.total_tokens,
                )
            row = ChatModelCallRow(
                call_id=call.call_id,
                session_id=call.session_id,
                trigger_message_id=call.trigger_message_id,
                response_message_id=call.response_message_id,
                purpose=call.purpose,
                model=call.model,
                request=dict(call.request),
                request_digest=call.request_digest,
                status=call.status,
                started_at=_datetime(call.started_at),
                finished_at=_optional_datetime(call.finished_at),
                error_code=call.error_code,
                provider_confirmed=call.provider_confirmed,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                total_tokens=call.total_tokens,
            )
            db.add(row)
            await db.flush()
            return ChatModelCall(
                call_id=row.call_id,
                session_id=row.session_id,
                trigger_message_id=row.trigger_message_id,
                response_message_id=row.response_message_id,
                purpose=row.purpose,
                model=row.model,
                request=dict(row.request),
                request_digest=row.request_digest,
                started_at=_iso(row.started_at),
                status=row.status,
                finished_at=_optional_iso(row.finished_at),
                error_code=row.error_code,
                provider_confirmed=row.provider_confirmed,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.total_tokens,
            )

    async def finish_model_call(
        self, *, session_id: str, call_id: str, outcome: ModelCallOutcome
    ) -> ChatModelCall:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(ChatModelCallRow, call_id, with_for_update=True)
            if row is None or row.session_id != session_id:
                raise ChatRecordNotFound(f"chat model call not found: {call_id}")
            if row.finished_at is not None:
                if row.status != outcome.status:
                    raise ValueError("model call outcome cannot be reassigned")
                return ChatModelCall(
                    call_id=row.call_id,
                    session_id=row.session_id,
                    trigger_message_id=row.trigger_message_id,
                    response_message_id=row.response_message_id,
                    purpose=row.purpose,
                    model=row.model,
                    request=dict(row.request),
                    request_digest=row.request_digest,
                    started_at=_iso(row.started_at),
                    status=row.status,
                    finished_at=_optional_iso(row.finished_at),
                    error_code=row.error_code,
                    provider_confirmed=row.provider_confirmed,
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    total_tokens=row.total_tokens,
                )
            row.status = outcome.status
            row.finished_at = _datetime(outcome.finished_at)
            row.error_code = outcome.error_code
            row.provider_confirmed = outcome.status == "provider_succeeded"
            row.prompt_tokens = outcome.prompt_tokens
            row.completion_tokens = outcome.completion_tokens
            row.total_tokens = outcome.total_tokens
            await db.flush()
            return ChatModelCall(
                call_id=row.call_id,
                session_id=row.session_id,
                trigger_message_id=row.trigger_message_id,
                response_message_id=row.response_message_id,
                purpose=row.purpose,
                model=row.model,
                request=dict(row.request),
                request_digest=row.request_digest,
                started_at=_iso(row.started_at),
                status=row.status,
                finished_at=_optional_iso(row.finished_at),
                error_code=row.error_code,
                provider_confirmed=row.provider_confirmed,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.total_tokens,
            )

    async def read_model_calls(
        self, session_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[ChatModelCall, ...]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(ChatModelCallRow)
                .where(ChatModelCallRow.session_id == session_id)
                .order_by(ChatModelCallRow.started_at, ChatModelCallRow.call_id)
                .offset(offset)
                .limit(limit)
            )
            return tuple(
                ChatModelCall(
                    call_id=row.call_id,
                    session_id=row.session_id,
                    trigger_message_id=row.trigger_message_id,
                    response_message_id=row.response_message_id,
                    purpose=row.purpose,
                    model=row.model,
                    request=dict(row.request),
                    request_digest=row.request_digest,
                    started_at=_iso(row.started_at),
                    status=row.status,
                    finished_at=_optional_iso(row.finished_at),
                    error_code=row.error_code,
                    provider_confirmed=row.provider_confirmed,
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    total_tokens=row.total_tokens,
                )
                for row in rows
            )

    async def read_model_call(
        self, session_id: str, call_id: str
    ) -> ChatModelCall | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(ChatModelCallRow, call_id)
            if row is None or row.session_id != session_id:
                return None
            return ChatModelCall(
                call_id=row.call_id,
                session_id=row.session_id,
                trigger_message_id=row.trigger_message_id,
                response_message_id=row.response_message_id,
                purpose=row.purpose,
                model=row.model,
                request=dict(row.request),
                request_digest=row.request_digest,
                started_at=_iso(row.started_at),
                status=row.status,
                finished_at=_optional_iso(row.finished_at),
                error_code=row.error_code,
                provider_confirmed=row.provider_confirmed,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.total_tokens,
            )

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
                "updated_at": func.greatest(
                    row.updated_at, statement.excluded.updated_at
                ),
            },
            where=or_(
                row.rating != statement.excluded.rating,
                row.reason.is_distinct_from(statement.excluded.reason),
                row.comment.is_distinct_from(statement.excluded.comment),
                row.response_digest != statement.excluded.response_digest,
            ),
        ).returning(row)
        async with AsyncSessionLocal() as db, db.begin():
            saved = (await db.scalars(statement)).one_or_none()
            if saved is None:
                # An identical PUT keeps the original timestamps as well as identity.
                saved = (
                    await db.scalars(
                        select(row).where(
                            row.user_id == feedback.user_id,
                            row.message_id == feedback.message_id,
                        )
                    )
                ).one()
            return ChatMessageFeedback(
                feedback_id=saved.feedback_id,
                session_id=saved.session_id,
                message_id=saved.message_id,
                user_id=saved.user_id,
                rating=saved.rating,
                reason=saved.reason,
                comment=saved.comment,
                response_digest=saved.response_digest,
                created_at=_iso(saved.created_at),
                updated_at=_iso(saved.updated_at),
            )

    async def delete_feedback(
        self, *, session_id: str, message_id: str, user_id: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            await db.execute(
                delete(ChatMessageFeedbackRow).where(
                    ChatMessageFeedbackRow.session_id == session_id,
                    ChatMessageFeedbackRow.message_id == message_id,
                    ChatMessageFeedbackRow.user_id == user_id,
                )
            )

    async def read_tool_call(self, tool_call_id: str) -> ChatToolCall | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(ChatToolCallRow, tool_call_id)
            return (
                ChatToolCall(
                    tool_call_id=row.tool_call_id,
                    session_id=row.session_id,
                    assistant_message_id=row.assistant_message_id,
                    position=row.position,
                    name=row.name,
                    arguments=dict(row.arguments),
                    arguments_digest=row.arguments_digest,
                    risk=ToolRisk(row.risk),
                    status=ToolCallStatus(row.status),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    error_code=row.error_code,
                    decision_user_id=row.decision_user_id,
                    decision_arguments_digest=row.decision_arguments_digest,
                    decided_at=_optional_iso(row.decided_at),
                    decision_basis=row.decision_basis,
                    authorization_revision=row.authorization_revision,
                )
                if row is not None
                else None
            )

    async def abort_running_tool_calls(
        self, *, session_id: str, error_code: str, finished_at: str
    ) -> tuple[ChatToolCall, ...]:
        async with AsyncSessionLocal() as db, db.begin():
            rows = tuple(
                await db.scalars(
                    select(ChatToolCallRow)
                    .where(
                        ChatToolCallRow.session_id == session_id,
                        ChatToolCallRow.status == ToolCallStatus.RUNNING.value,
                    )
                    .with_for_update()
                )
            )
            aborted = []
            for row in rows:
                call = ChatToolCall(
                    tool_call_id=row.tool_call_id,
                    session_id=row.session_id,
                    assistant_message_id=row.assistant_message_id,
                    position=row.position,
                    name=row.name,
                    arguments=dict(row.arguments),
                    arguments_digest=row.arguments_digest,
                    risk=ToolRisk(row.risk),
                    status=ToolCallStatus(row.status),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    error_code=row.error_code,
                    decision_user_id=row.decision_user_id,
                    decision_arguments_digest=row.decision_arguments_digest,
                    decided_at=_optional_iso(row.decided_at),
                    decision_basis=row.decision_basis,
                    authorization_revision=row.authorization_revision,
                ).fail(error_code, finished_at)
                row.status = call.status.value
                row.started_at = _optional_datetime(call.started_at)
                row.finished_at = _optional_datetime(call.finished_at)
                row.error_code = call.error_code
                row.decision_user_id = call.decision_user_id
                row.decision_arguments_digest = call.decision_arguments_digest
                row.decided_at = _optional_datetime(call.decided_at)
                row.decision_basis = call.decision_basis
                row.authorization_revision = call.authorization_revision
                aborted.append(call)
            return tuple(aborted)

    async def save_trajectory(
        self,
        *,
        chat_session: ChatSession,
        messages: tuple[ChatMessage, ...],
        tool_calls: tuple[ChatToolCall, ...],
        tool_results: tuple[ChatToolResult, ...],
    ) -> None:
        if any(message.session_id != chat_session.session_id for message in messages):
            raise ValueError("chat message belongs to another session")
        if any(call.session_id != chat_session.session_id for call in tool_calls):
            raise ValueError("chat tool call belongs to another session")
        async with AsyncSessionLocal() as db, db.begin():
            session_row = await db.get(
                ChatSessionRow, chat_session.session_id, with_for_update=True
            )
            if session_row is None:
                raise ValueError(f"chat session not found: {chat_session.session_id}")
            if (
                session_row.user_id != chat_session.user_id
                or session_row.collection_id != chat_session.collection_id
            ):
                raise ValueError("session identity cannot be reassigned")

            existing_messages = tuple(
                await db.scalars(
                    select(ChatMessageRow)
                    .where(ChatMessageRow.session_id == chat_session.session_id)
                    .order_by(ChatMessageRow.position)
                )
            )
            existing_ids = tuple(row.message_id for row in existing_messages)
            incoming_ids = tuple(message.message_id for message in messages)
            if incoming_ids[: len(existing_ids)] != existing_ids:
                raise ValueError("chat trajectory is append-only")
            session_row.updated_at = _datetime(chat_session.updated_at)

            for position, message in enumerate(
                messages[len(existing_ids) :], len(existing_ids)
            ):
                if await db.get(ChatMessageRow, message.message_id) is not None:
                    raise ValueError("message identity cannot be reassigned")
                db.add(
                    ChatMessageRow(
                        message_id=message.message_id,
                        session_id=message.session_id,
                        position=position,
                        role=message.role.value,
                        content=message.content,
                        tool_call_id=message.tool_call_id,
                        source_contexts=[
                            {
                                "resource_ref": {
                                    "resource_type": item.resource_ref.resource_type,
                                    "resource_id": item.resource_ref.resource_id,
                                    "href": item.resource_ref.href,
                                },
                                "collection_id": item.collection_id,
                                "document_id": item.document_id,
                                "document_title": item.document_title,
                                "source_kind": item.source_kind,
                                "source_ref": item.source_ref,
                                "page": item.page,
                                "quote": item.quote,
                                "heading_path": item.heading_path,
                                "quote_truncated": item.quote_truncated,
                                "source_digest": item.source_digest,
                            }
                            for item in message.source_contexts
                        ],
                        created_at=_datetime(message.created_at),
                    )
                )
            await db.flush()

            for call in tool_calls:
                assistant = next(
                    (
                        message
                        for message in messages
                        if message.message_id == call.assistant_message_id
                    ),
                    None,
                )
                if (
                    assistant is None
                    or ChatToolRequest(
                        tool_call_id=call.tool_call_id,
                        name=call.name,
                        arguments=call.arguments,
                        position=call.position,
                        decision_user_id=call.decision_user_id,
                        decision_arguments_digest=call.decision_arguments_digest,
                        decided_at=call.decided_at,
                        decision_basis=call.decision_basis,
                        authorization_revision=call.authorization_revision,
                    )
                    not in assistant.tool_calls
                ):
                    raise ValueError("tool call must match its assistant request")
                row = await db.get(ChatToolCallRow, call.tool_call_id)
                if row is None:
                    row = ChatToolCallRow(
                        tool_call_id=call.tool_call_id,
                        session_id=call.session_id,
                        assistant_message_id=call.assistant_message_id,
                        name=call.name,
                        position=call.position,
                        arguments=call.arguments,
                        arguments_digest=call.arguments_digest,
                        risk=call.risk.value,
                        status=call.status.value,
                        proposed_permission_revision=(
                            session_row.operation_permission or {}
                        ).get("revision", 0),
                    )
                    db.add(row)
                elif (
                    row.session_id != call.session_id
                    or row.assistant_message_id != call.assistant_message_id
                    or row.name != call.name
                    or row.arguments_digest != call.arguments_digest
                    or row.position != call.position
                ):
                    raise ValueError("tool call identity cannot be reassigned")
                row.status = call.status.value
                row.started_at = _optional_datetime(call.started_at)
                row.finished_at = _optional_datetime(call.finished_at)
                row.error_code = call.error_code
                # Historical continuations must not clear a saved approval.
                has_decision = any(
                    (
                        call.decision_user_id,
                        call.decision_arguments_digest,
                        call.decided_at,
                        call.authorization_revision,
                    )
                )
                if has_decision:
                    row.decision_user_id = call.decision_user_id
                    row.decision_arguments_digest = call.decision_arguments_digest
                    row.decided_at = _optional_datetime(call.decided_at)
                    row.decision_basis = call.decision_basis
                    row.authorization_revision = call.authorization_revision
            await db.flush()

            for message in messages:
                for request in message.tool_calls:
                    call_row = await db.get(ChatToolCallRow, request.tool_call_id)
                    if (
                        call_row is None
                        or call_row.session_id != chat_session.session_id
                        or call_row.assistant_message_id != message.message_id
                        or ChatToolRequest(
                            tool_call_id=call_row.tool_call_id,
                            name=call_row.name,
                            arguments=call_row.arguments,
                            position=call_row.position,
                            decision_user_id=call_row.decision_user_id,
                            decision_arguments_digest=call_row.decision_arguments_digest,
                            decided_at=_optional_iso(call_row.decided_at),
                            decision_basis=call_row.decision_basis,
                            authorization_revision=call_row.authorization_revision,
                        )
                        != request
                    ):
                        raise ValueError(
                            "assistant request must have an identical durable call"
                        )

            for result in tool_results:
                call_row = await db.get(ChatToolCallRow, result.tool_call_id)
                if call_row is None or call_row.session_id != chat_session.session_id:
                    raise ValueError("tool result belongs to an unknown call")
                call_row.result_status = result.status.value
                call_row.result_data = deepcopy(result.data)
                call_row.result_resource_refs = [
                    asdict(item) for item in result.resource_refs
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
        async with AsyncSessionLocal() as db, db.begin():
            session_row = await db.get(ChatSessionRow, session_id, with_for_update=True)
            if session_row is None or session_row.user_id != user_id:
                raise ChatRecordNotFound(f"chat session not found: {session_id}")
            permission = {
                "mode": "confirm",
                "actions": [],
                "expires_at": None,
                "revision": 0,
            }
            if session_row.operation_permission:
                permission.update(session_row.operation_permission)
            if decision == "approved" and permission["mode"] == "read_only":
                raise ChatWriteConflict(
                    "permission_read_only", "This conversation is read-only."
                )
            row = await db.get(ChatToolCallRow, tool_call_id, with_for_update=True)
            if row is None or row.session_id != session_id:
                raise ChatRecordNotFound(f"chat tool call not found: {tool_call_id}")
            call = ChatToolCall(
                tool_call_id=row.tool_call_id,
                session_id=row.session_id,
                assistant_message_id=row.assistant_message_id,
                position=row.position,
                name=row.name,
                arguments=dict(row.arguments),
                arguments_digest=row.arguments_digest,
                risk=ToolRisk(row.risk),
                status=ToolCallStatus(row.status),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                error_code=row.error_code,
                decision_user_id=row.decision_user_id,
                decision_arguments_digest=row.decision_arguments_digest,
                decided_at=_optional_iso(row.decided_at),
                decision_basis=row.decision_basis,
                authorization_revision=row.authorization_revision,
            )
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
                    if (
                        decision == "approved"
                        and call.authorization_revision != permission["revision"]
                    ):
                        call = replace(
                            call,
                            authorization_revision=permission["revision"],
                            decision_basis="explicit",
                            decided_at=decided_at,
                        )
                        row.status = call.status.value
                        row.started_at = _optional_datetime(call.started_at)
                        row.finished_at = _optional_datetime(call.finished_at)
                        row.error_code = call.error_code
                        row.decision_user_id = call.decision_user_id
                        row.decision_arguments_digest = call.decision_arguments_digest
                        row.decided_at = _optional_datetime(call.decided_at)
                        row.decision_basis = call.decision_basis
                        row.authorization_revision = call.authorization_revision
                    return call
                raise ChatWriteConflict(
                    "chat_tool_decision_conflict",
                    "tool call was decided with different authority",
                )
            try:
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
                if decision == "approved":
                    decided = replace(
                        decided, authorization_revision=permission["revision"]
                    )
            except ValueError as exc:
                raise ChatWriteConflict(
                    "chat_tool_decision_conflict", str(exc)
                ) from exc
            row.status = decided.status.value
            row.started_at = _optional_datetime(decided.started_at)
            row.finished_at = _optional_datetime(decided.finished_at)
            row.error_code = decided.error_code
            row.decision_user_id = decided.decision_user_id
            row.decision_arguments_digest = decided.decision_arguments_digest
            row.decided_at = _optional_datetime(decided.decided_at)
            row.decision_basis = decided.decision_basis
            row.authorization_revision = decided.authorization_revision
            return decided

    async def claim_approved_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        started_at: str,
    ) -> ChatToolCall | None:
        async with AsyncSessionLocal() as db, db.begin():
            session_row = await db.get(ChatSessionRow, session_id, with_for_update=True)
            if session_row is None or session_row.user_id != user_id:
                raise ChatRecordNotFound(f"chat session not found: {session_id}")
            row = await db.get(ChatToolCallRow, tool_call_id, with_for_update=True)
            if row is None or row.session_id != session_id:
                raise ChatRecordNotFound(f"chat tool call not found: {tool_call_id}")
            call = ChatToolCall(
                tool_call_id=row.tool_call_id,
                session_id=row.session_id,
                assistant_message_id=row.assistant_message_id,
                position=row.position,
                name=row.name,
                arguments=dict(row.arguments),
                arguments_digest=row.arguments_digest,
                risk=ToolRisk(row.risk),
                status=ToolCallStatus(row.status),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                error_code=row.error_code,
                decision_user_id=row.decision_user_id,
                decision_arguments_digest=row.decision_arguments_digest,
                decided_at=_optional_iso(row.decided_at),
                decision_basis=row.decision_basis,
                authorization_revision=row.authorization_revision,
            )
            if call.status is ToolCallStatus.APPROVED:
                permission = {
                    "mode": "confirm",
                    "actions": [],
                    "expires_at": None,
                    "revision": 0,
                }
                if session_row.operation_permission:
                    permission.update(session_row.operation_permission)
                if permission["mode"] == "read_only" or (
                    (call.authorization_revision or 0) != permission["revision"]
                ):
                    raise ChatWriteConflict(
                        "permission_changed_before_execution",
                        "Permission changed before execution.",
                    )
                claimed = call.start(started_at)
                row.status = claimed.status.value
                row.started_at = _optional_datetime(claimed.started_at)
                row.finished_at = _optional_datetime(claimed.finished_at)
                row.error_code = claimed.error_code
                row.decision_user_id = claimed.decision_user_id
                row.decision_arguments_digest = claimed.decision_arguments_digest
                row.decided_at = _optional_datetime(claimed.decided_at)
                row.decision_basis = claimed.decision_basis
                row.authorization_revision = claimed.authorization_revision
                return claimed
            if call.status in {
                ToolCallStatus.RUNNING,
                ToolCallStatus.SUCCEEDED,
                ToolCallStatus.FAILED,
            }:
                return None
            raise ChatWriteConflict(
                "chat_tool_decision_conflict",
                f"cannot claim tool call in status {call.status.value}",
            )


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


__all__ = ["ChatRepository"]


ChatRepo = ChatRepository()
