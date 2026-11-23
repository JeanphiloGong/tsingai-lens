"""Backfill parent-linked Conversation paths from the V1 linear message order."""

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
from infra.persistence.postgres.models.conversation import (  # noqa: E402
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)


@dataclass
class MigrationReport:
    source_conversation_id: str
    target_conversation_id: str | None = None
    updated_message_count: int = 0
    current_message_id: str | None = None
    unresolved: list[dict[str, str]] = field(default_factory=list)

    def add_unresolved(self, kind: str, record_id: str, reason: str) -> None:
        self.unresolved.append(
            {"kind": kind, "record_id": record_id, "reason": reason}
        )


def response_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def backfill_conversation(
    db: AsyncSession, conversation_id: str
) -> MigrationReport:
    """Backfill one final Conversation in an isolated transaction.

    V1 renamed the historical Chat tables in place, so this reads the current
    Conversation tables. Existing parent links, current selections and
    Feedback are verified before any parent link is changed.
    """

    report = MigrationReport(source_conversation_id=conversation_id)
    async with db.begin():
        conversation = await db.scalar(
            select(ConversationORM)
            .where(ConversationORM.conversation_id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            report.add_unresolved(
                "conversation", conversation_id, "conversation not found"
            )
            return report
        report.target_conversation_id = conversation.conversation_id

        messages = tuple(
            (
                await db.scalars(
                    select(MessageORM)
                    .where(MessageORM.conversation_id == conversation_id)
                    .order_by(MessageORM.position, MessageORM.message_id)
                    .with_for_update()
                )
            ).all()
        )
        positions = [message.position for message in messages]
        if positions != list(range(len(messages))):
            report.add_unresolved(
                "conversation",
                conversation_id,
                "message position is not zero-contiguous",
            )
            return report

        messages_by_id = {message.message_id: message for message in messages}
        expected_parent: str | None = None
        for message in messages:
            if message.source_contexts is None or not isinstance(
                message.source_contexts, list
            ):
                report.add_unresolved(
                    "message",
                    message.message_id,
                    "source_contexts is not a JSON list",
                )
                return report
            if message.parent_message_id not in {None, expected_parent}:
                report.add_unresolved(
                    "message",
                    message.message_id,
                    "parent_message_id does not match the historical order",
                )
                return report
            expected_parent = message.message_id

        feedback_rows = tuple(
            (
                await db.scalars(
                    select(MessageFeedbackORM)
                    .where(MessageFeedbackORM.conversation_id == conversation_id)
                    .order_by(MessageFeedbackORM.feedback_id)
                    .with_for_update()
                )
            ).all()
        )
        for feedback in feedback_rows:
            message = messages_by_id.get(feedback.message_id)
            if message is None or message.role != "assistant" or not message.content:
                report.add_unresolved(
                    "feedback",
                    feedback.feedback_id,
                    "target is not a non-empty assistant message",
                )
                return report
            if feedback.response_digest != response_digest(message.content):
                report.add_unresolved(
                    "feedback",
                    feedback.feedback_id,
                    "response digest does not match the assistant message",
                )
                return report

        last_message_id = messages[-1].message_id if messages else None
        if (
            last_message_id is not None
            and conversation.current_task_id is None
            and conversation.current_message_id not in {None, last_message_id}
        ):
            report.add_unresolved(
                "conversation",
                conversation_id,
                "current_message_id selects a different path",
            )
            return report

        for index, message in enumerate(messages):
            parent_id = messages[index - 1].message_id if index else None
            if message.parent_message_id != parent_id:
                message.parent_message_id = parent_id
                report.updated_message_count += 1

        if last_message_id is not None:
            if conversation.current_task_id is None:
                if conversation.current_message_id is None:
                    conversation.current_message_id = last_message_id
                conversation.path_revision = max(
                    conversation.path_revision, len(messages)
                )
            report.current_message_id = conversation.current_message_id
        conversation.updated_at = datetime.now(UTC)
    return report


async def run(conversation_ids: list[str]) -> list[MigrationReport]:
    reports: list[MigrationReport] = []
    for conversation_id in conversation_ids:
        async with AsyncSessionLocal() as db:
            reports.append(await backfill_conversation(db, conversation_id))
    return reports


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "conversation_id",
        nargs="+",
        help="Conversation IDs to backfill, one transaction per Conversation",
    )
    return parser


async def _main(conversation_ids: list[str]) -> None:
    engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=engine)
    try:
        reports = await run(conversation_ids)
        print(json.dumps([asdict(report) for report in reports], ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args().conversation_id))


__all__ = ["MigrationReport", "backfill_conversation", "response_digest", "run"]
