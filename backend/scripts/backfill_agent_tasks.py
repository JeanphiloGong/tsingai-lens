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

from sqlalchemy import select
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
    ChatToolCallORM,
)
from infra.persistence.postgres.models.conversation import (  # noqa: E402
    ConversationORM,
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


def _operation_status(call: ChatToolCallORM) -> tuple[str, bool]:
    result_status = call.result_status
    if result_status in {"unknown", "needs_reconciliation"}:
        return "needs_reconciliation", True
    if (
        call.risk in {"write", "draft"}
        and call.status == "running"
        and call.finished_at is None
    ):
        return "needs_reconciliation", True
    allowed = {
        "requested",
        "approval_required",
        "approved",
        "running",
        "succeeded",
        "failed",
        "rejected",
    }
    if call.status not in allowed:
        return "needs_reconciliation", True
    return call.status, False


async def _load_snapshots(
    db: AsyncSession,
) -> tuple[tuple[str, dict[str, object]], ...]:
    async with db.begin():
        conversations = (
            await db.scalars(
                select(ConversationORM)
                .where(ConversationORM.response_snapshot.is_not(None))
                .order_by(ConversationORM.conversation_id)
            )
        ).all()
        snapshots: list[tuple[str, dict[str, object]]] = []
        for conversation in conversations:
            snapshot = conversation.response_snapshot
            if not isinstance(snapshot, dict) or not snapshot.get("response_id"):
                continue
            snapshots.append((conversation.conversation_id, snapshot))
    return tuple(snapshots)


async def _backfill_one(
    db: AsyncSession,
    conversation: ConversationORM,
    snapshot: dict[str, object],
    report: TaskBackfillReport,
) -> str | None:
    response_id = str(snapshot["response_id"])
    if snapshot.get("response_count", 1) != 1:
        report.add_unresolved(response_id, "response identity is not unique")
        return None
    trigger_id = snapshot.get("trigger_message_id")
    final_id = snapshot.get("final_message_id")
    if not isinstance(trigger_id, str) or not isinstance(final_id, str):
        report.add_unresolved(response_id, "trigger or final Message identity is missing")
        return None

    messages = (
        await db.scalars(
            select(MessageORM).where(
                MessageORM.conversation_id == conversation.conversation_id,
                MessageORM.message_id.in_((trigger_id, final_id)),
            )
        )
    ).all()
    by_id = {message.message_id: message for message in messages}
    trigger = by_id.get(trigger_id)
    final = by_id.get(final_id)
    status = _status(snapshot.get("status", "failed"))
    if trigger is None or trigger.role != "user":
        report.add_unresolved(response_id, "trigger Message is not a user Message")
        return None
    if final is None or final.role != "assistant" or not final.content:
        report.add_unresolved(response_id, "final Message is not a non-empty assistant Message")
        return None
    if status is None:
        report.add_unresolved(response_id, "Task status is not supported")
        return None
    if status == "completed" and final.message_id is None:
        report.add_unresolved(response_id, "completed response has no final Message")
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
        final.produced_by_task_id = task_id
        task = AgentTaskORM(
            task_id=task_id,
            session_id=conversation.conversation_id,
            trigger_kind="user_message",
            trigger_message_id=trigger.message_id,
            final_message_id=final.message_id if status == "completed" else None,
            status=status,
            checkpoint_revision=revision,
            checkpoint=checkpoint,
            started_at=started_at,
            updated_at=updated_at,
            finished_at=finished_at,
        )
        db.add(task)
        await db.flush()
        report.created_task_ids.append(task_id)
    elif (
        task.session_id != conversation.conversation_id
        or task.trigger_message_id != trigger.message_id
        or task.status != status
    ):
        report.add_unresolved(response_id, "existing Task does not match the legacy identity")
        return None

    final.produced_by_task_id = task_id
    task.checkpoint_message_id = checkpoint_message_id or (
        final.message_id if status == "completed" else None
    )
    return task_id


async def _backfill_operations(
    db: AsyncSession,
    conversation_id: str,
    final_message_id: str,
    task_id: str,
    report: TaskBackfillReport,
) -> None:
    calls = (
        await db.scalars(
            select(ChatToolCallORM)
            .where(
                ChatToolCallORM.session_id == conversation_id,
                ChatToolCallORM.assistant_message_id == final_message_id,
            )
            .order_by(ChatToolCallORM.position, ChatToolCallORM.tool_call_id)
        )
    ).all()
    for call in calls:
        operation_id = stable_operation_id(task_id, call.tool_call_id)
        status, needs_reconciliation = _operation_status(call)
        if needs_reconciliation:
            report.reconciliation_operation_ids.append(operation_id)
        operation = await db.get(AgentOperationORM, operation_id, with_for_update=True)
        if operation is None:
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
                result=call.result_data,
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
                | (ChatModelCallORM.response_message_id == final_message_id),
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
    snapshots = await _load_snapshots(db)
    for conversation_id, snapshot in snapshots:
        async with db.begin():
            conversation = await db.scalar(
                select(ConversationORM)
                .where(ConversationORM.conversation_id == conversation_id)
                .with_for_update()
            )
            if conversation is None:
                report.add_unresolved(
                    str(snapshot["response_id"]), "conversation is missing"
                )
                continue
            task_id = await _backfill_one(db, conversation, snapshot, report)
            if task_id is None:
                continue
            final_id = snapshot.get("final_message_id") or snapshot.get("message_id")
            if not isinstance(final_id, str):
                continue
            await _backfill_operations(
                db,
                conversation.conversation_id,
                final_id,
                task_id,
                report,
            )
            await _link_model_calls(
                db,
                conversation.conversation_id,
                str(snapshot["trigger_message_id"]),
                final_id,
                task_id,
                report,
            )
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
