"""Backfill reliable legacy Chat executions into Agent Task storage."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys

from sqlalchemy import MetaData, Table, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from infra.persistence.database import (  # noqa: E402
    AsyncSessionLocal,
    DatabaseSettings,
    build_database_engine,
)
from infra.persistence.postgres.models.chat import (  # noqa: E402
    AgentOperationORM,
    AgentTaskORM,
    ChatModelCallORM,
)
from infra.persistence.postgres.models.conversation import (  # noqa: E402
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)


@dataclass
class TaskBackfillReport:
    created_task_ids: list[str] = field(default_factory=list)
    created_operation_ids: list[str] = field(default_factory=list)
    linked_model_call_ids: list[str] = field(default_factory=list)
    unresolved_response_ids: list[str] = field(default_factory=list)
    reconciliation_operation_ids: list[str] = field(default_factory=list)
    unresolved: list[dict[str, str]] = field(default_factory=list)

    def add_unresolved(self, response_id: str, reason: str) -> None:
        self.unresolved_response_ids.append(response_id)
        self.unresolved.append({"response_id": response_id, "reason": reason})


def stable_task_id(response_id: str) -> str:
    return "task_legacy_" + hashlib.sha256(response_id.encode("utf-8")).hexdigest()[:32]


def stable_operation_id(task_id: str, tool_call_id: str) -> str:
    value = f"{task_id}:{tool_call_id}".encode("utf-8")
    return "operation_legacy_" + hashlib.sha256(value).hexdigest()[:32]


def _datetime(value: object, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return fallback


def _status(value: object) -> str | None:
    allowed = {
        "accepted",
        "running",
        "approval_required",
        "completed",
        "failed",
        "interrupted",
        "cancelled",
    }
    return value if isinstance(value, str) and value in allowed else None


def _operation_status(call) -> tuple[str, bool]:
    result_status = call.result_status
    if result_status in {"unknown", "needs_reconciliation"} or call.status == "running":
        return "needs_reconciliation", True
    allowed = {
        "requested",
        "approval_required",
        "approved",
        "succeeded",
        "failed",
        "rejected",
    }
    if call.status not in allowed:
        return "needs_reconciliation", True
    return call.status, False


async def _backfill_one(
    db: AsyncSession,
    conversation: ConversationORM,
    snapshot: dict[str, object],
    report: TaskBackfillReport,
) -> tuple[str, tuple[MessageORM, ...]] | None:
    response_id = str(snapshot["response_id"])
    if snapshot.get("response_count", 1) != 1:
        report.add_unresolved(response_id, "response identity is not unique")
        return None
    final_id = snapshot.get("final_message_id")
    if final_id is None and snapshot.get("status") == "completed":
        # The old runtime cleared streamed message_id at completion.
        final_id = snapshot.get("checkpoint_message_id")
    if not isinstance(final_id, str):
        report.add_unresolved(response_id, "persisted final Message identity is missing")
        return None

    tool_requests = literal_column("chat_messages.tool_requests", JSONB)
    position = literal_column("chat_messages.position")
    messages = (
        await db.execute(
            select(MessageORM, tool_requests)
            .where(MessageORM.conversation_id == conversation.conversation_id)
            .order_by(position, MessageORM.message_id)
        )
    ).all()
    final = None
    trigger = None
    turn = []
    for message, requests in messages:
        if message.role == "user":
            trigger = message
            turn.clear()
        turn.append(message)
        if message.message_id == final_id:
            if not requests:
                final = message
            break
    status = _status(snapshot.get("status", "failed"))
    if trigger is None or trigger.role != "user":
        report.add_unresolved(response_id, "trigger Message is not a user Message")
        return None
    if final is None or final.role != "assistant" or not final.content:
        report.add_unresolved(response_id, "final Message is not a non-empty assistant Message")
        return None
    if status != "completed" or snapshot.get("completion_reason") not in {None, "model_answer"}:
        report.add_unresolved(response_id, "legacy response is not a completed model answer")
        return None
    if snapshot.get("trigger_message_id", trigger.message_id) != trigger.message_id:
        report.add_unresolved(response_id, "trigger Message does not match the legacy turn")
        return None
    if conversation.forked_from_message_id or final.copied_from_message_id:
        report.add_unresolved(response_id, "legacy Fork execution requires provenance review")
        return None
    if final.parent_message_id is not None:
        for previous, current in zip(turn, turn[1:]):
            if current.parent_message_id != previous.message_id:
                report.add_unresolved(response_id, "legacy turn does not match the parent path")
                return None
    task_id = stable_task_id(response_id)
    if final.produced_by_task_id not in {None, task_id}:
        report.add_unresolved(response_id, "final Message belongs to another Task")
        return None

    started_at = _datetime(snapshot.get("started_at"), conversation.created_at)
    updated_at = _datetime(snapshot.get("updated_at"), conversation.updated_at)
    finished_at = (
        _datetime(snapshot.get("finished_at"), updated_at)
        if snapshot.get("finished_at") is not None
        else None
    )
    revision = snapshot.get("checkpoint_revision", snapshot.get("sequence", 0))
    if not isinstance(revision, int) or revision < 0:
        report.add_unresolved(response_id, "checkpoint revision is invalid")
        return None
    checkpoint_message_id = snapshot.get("checkpoint_message_id")
    if checkpoint_message_id not in {None, final.message_id}:
        report.add_unresolved(
            response_id,
            "checkpoint Message identity is not the verified final Message",
        )
        return None
    checkpoint = snapshot.get("checkpoint", {})
    if not isinstance(checkpoint, dict):
        report.add_unresolved(response_id, "checkpoint is not a JSON object")
        return None

    task = await db.get(AgentTaskORM, task_id, with_for_update=True)
    if task is None:
        task = AgentTaskORM(
            task_id=task_id,
            session_id=conversation.conversation_id,
            trigger_kind="user_message",
            trigger_message_id=trigger.message_id,
            status="running",
            checkpoint_revision=revision,
            checkpoint=checkpoint,
            started_at=started_at,
            updated_at=updated_at,
            finished_at=finished_at,
        )
        db.add(task)
        await db.flush()
        final.produced_by_task_id = task_id
        await db.flush()
        task.final_message_id = final.message_id
        task.status = "completed"
        report.created_task_ids.append(task_id)
    elif (
        task.session_id != conversation.conversation_id
        or task.trigger_message_id != trigger.message_id
        or task.status != status
        or task.final_message_id != final.message_id
    ):
        report.add_unresolved(response_id, "existing Task does not match the legacy identity")
        return None

    final.produced_by_task_id = task_id
    task.checkpoint_message_id = checkpoint_message_id or (
        final.message_id if status == "completed" else None
    )
    return task_id, tuple(turn)


async def _backfill_operations(
    db: AsyncSession,
    conversation_id: str,
    turn: tuple[MessageORM, ...],
    task_id: str,
    report: TaskBackfillReport,
    tool_calls: Table,
) -> None:
    assistants = {
        message.message_id: message for message in turn if message.role == "assistant"
    }
    calls = (
        await db.execute(
            select(tool_calls)
            .where(
                tool_calls.c.session_id == conversation_id,
                tool_calls.c.assistant_message_id.in_(assistants),
            )
            .order_by(tool_calls.c.position, tool_calls.c.tool_call_id)
        )
    ).all()
    for call in calls:
        message = assistants[call.assistant_message_id]
        if message.produced_by_task_id not in {None, task_id}:
            report.add_unresolved(call.tool_call_id, "assistant Message belongs to another Task")
            continue
        operation_id = stable_operation_id(task_id, call.tool_call_id)
        status, needs_reconciliation = _operation_status(call)
        if needs_reconciliation:
            report.reconciliation_operation_ids.append(operation_id)
        operation = await db.get(AgentOperationORM, operation_id, with_for_update=True)
        if operation is None:
            message.produced_by_task_id = task_id
            await db.flush()
            operation = AgentOperationORM(
                operation_id=operation_id,
                task_id=task_id,
                tool_call_id=call.tool_call_id,
                assistant_message_id=call.assistant_message_id,
                name=call.name,
                arguments=dict(call.arguments),
                arguments_digest=call.arguments_digest,
                risk=call.risk,
                status=status,
                result=(
                    {
                        "tool_call_id": call.tool_call_id,
                        "status": call.result_status,
                        "data": call.result_data or {},
                        "resource_refs": call.result_resource_refs or [],
                        "warnings": call.result_warnings or [],
                        "error_code": call.result_error_code,
                        "error_message": call.result_error_message,
                    }
                    if call.result_status
                    else None
                ),
                error_code=call.result_error_code or call.error_code,
                error_message=call.result_error_message,
                decision_user_id=call.decision_user_id,
                decision_arguments_digest=call.decision_arguments_digest,
                decided_at=call.decided_at,
                started_at=call.started_at,
                finished_at=call.finished_at,
                created_at=call.started_at or datetime.now(UTC),
                updated_at=call.finished_at or call.started_at or datetime.now(UTC),
            )
            db.add(operation)
            report.created_operation_ids.append(operation_id)
        elif operation.task_id != task_id:
            report.unresolved.append(
                {"response_id": task_id, "reason": "Operation belongs to another Task"}
            )


async def _link_model_calls(
    db: AsyncSession,
    conversation_id: str,
    trigger_message_id: str,
    final_message_id: str,
    task_id: str,
    report: TaskBackfillReport,
) -> None:
    calls = (
        await db.scalars(
            select(ChatModelCallORM)
            .where(
                ChatModelCallORM.session_id == conversation_id,
                (ChatModelCallORM.trigger_message_id == trigger_message_id)
                & (
                    (ChatModelCallORM.response_message_id == final_message_id)
                    | (ChatModelCallORM.response_message_id.is_(None))
                ),
            )
            .order_by(ChatModelCallORM.started_at, ChatModelCallORM.call_id)
        )
    ).all()
    for sequence, call in enumerate(calls):
        if call.task_id not in {None, task_id}:
            continue
        call.task_id = task_id
        call.sequence = sequence
        report.linked_model_call_ids.append(call.call_id)


async def run(db: AsyncSession) -> TaskBackfillReport:
    report = TaskBackfillReport()
    async with db.begin():
        connection = await db.connection()
        tool_calls = await connection.run_sync(
            lambda sync: Table("chat_tool_calls", MetaData(), autoload_with=sync)
        )
        snapshot_column = literal_column("chat_conversations.response_snapshot", JSONB)
        old_fork = literal_column("chat_conversations.parent_session_id")
        rows = (
            await db.execute(
                select(ConversationORM, snapshot_column, old_fork)
                .where(snapshot_column.is_not(None))
                .with_for_update(of=ConversationORM)
            )
        ).all()
        response_counts: dict[str, int] = {}
        for _, snapshot, _ in rows:
            if isinstance(snapshot, dict) and isinstance(snapshot.get("response_id"), str):
                response_id = snapshot["response_id"]
                response_counts[response_id] = response_counts.get(response_id, 0) + 1
        for conversation, snapshot, old_parent in rows:
            if snapshot is None:
                continue
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("response_id"), str):
                report.add_unresolved(conversation.conversation_id, "response identity is missing")
                continue
            if response_counts[snapshot["response_id"]] != 1 or old_parent is not None:
                report.add_unresolved(snapshot["response_id"], "response identity or Fork origin is ambiguous")
                continue
            migrated = await _backfill_one(db, conversation, snapshot, report)
            if migrated is None:
                continue
            task_id, turn = migrated
            await _backfill_operations(
                db, conversation.conversation_id, turn, task_id, report, tool_calls
            )
            await _link_model_calls(
                db, conversation.conversation_id, turn[0].message_id, turn[-1].message_id,
                task_id, report,
            )

        unlinked = (
            await db.scalars(
                select(tool_calls.c.tool_call_id).where(
                    ~select(1).where(
                        AgentOperationORM.tool_call_id == tool_calls.c.tool_call_id,
                        AgentOperationORM.assistant_message_id == tool_calls.c.assistant_message_id,
                    ).exists()
                )
            )
        ).all()
        for call_id in unlinked:
            report.add_unresolved(call_id, "tool call has no verified Task")
        feedback = (
            await db.execute(
                select(
                    MessageFeedbackORM.feedback_id,
                    MessageFeedbackORM.user_id,
                    MessageFeedbackORM.response_digest,
                    MessageORM.content,
                    ConversationORM.user_id,
                    AgentTaskORM.task_id,
                )
                .join(MessageORM, MessageORM.message_id == MessageFeedbackORM.message_id)
                .join(ConversationORM, ConversationORM.conversation_id == MessageORM.conversation_id)
                .outerjoin(
                    AgentTaskORM,
                    (AgentTaskORM.task_id == MessageORM.produced_by_task_id)
                    & (AgentTaskORM.final_message_id == MessageORM.message_id)
                    & (AgentTaskORM.status == "completed"),
                )
            )
        ).all()
        for feedback_id, author_id, digest, content, owner_id, task_id in feedback:
            if (
                task_id is None
                or author_id != owner_id
                or digest != hashlib.sha256(content.encode("utf-8")).hexdigest()
            ):
                report.unresolved.append({
                    "feedback_id": feedback_id,
                    "reason": "Feedback target, owner or response digest requires review",
                })
    return report


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


async def _main() -> None:
    engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=engine)
    try:
        async with AsyncSessionLocal() as db:
            report = await run(db)
        print(json.dumps(asdict(report), ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    _parser().parse_args()
    asyncio.run(_main())


__all__ = [
    "TaskBackfillReport",
    "run",
    "stable_operation_id",
    "stable_task_id",
]
