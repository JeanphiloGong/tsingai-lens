"""PostgreSQL persistence for Chat correction review snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.evaluation import ChatCorrectionReview, ChatCorrectionSample
from infra.persistence.postgres.models.chat_correction import (
    ChatCorrectionReviewRow,
    ChatCorrectionSampleRow,
)


class PostgresChatCorrectionReviewRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save_sample(self, sample: ChatCorrectionSample) -> ChatCorrectionSample:
        async with self.session_factory.begin() as session:
            existing = await session.get(ChatCorrectionSampleRow, sample.sample_id, with_for_update=True)
            if existing is None:
                existing = await session.scalar(
                    select(ChatCorrectionSampleRow).where(
                        ChatCorrectionSampleRow.case_id == sample.case_id
                    )
                )
            if existing is not None:
                saved = _sample_record(existing)
                if saved.to_record() != sample.to_record():
                    raise ValueError("correction sample identity cannot be reassigned")
                return saved
            row = ChatCorrectionSampleRow(
                sample_id=sample.sample_id,
                case_id=sample.case_id,
                session_id=sample.session_id,
                collection_id=sample.collection_id,
                model_call_id=sample.model_call_id,
                input=sample.input,
                observations=list(sample.observations),
                target=sample.target,
                source_refs=list(sample.source_refs),
                digest=sample.digest,
                created_at=_datetime(sample.created_at),
                updated_at=_datetime(sample.updated_at),
            )
            session.add(row)
            await session.flush()
            return _sample_record(row)

    async def read_sample(self, session_id: str, sample_id: str) -> ChatCorrectionSample | None:
        async with self.session_factory() as session:
            row = await session.get(ChatCorrectionSampleRow, sample_id)
            if row is None or row.session_id != session_id:
                return None
            return _sample_record(row)

    async def list_samples(
        self, session_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[ChatCorrectionSample, ...]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(ChatCorrectionSampleRow)
                .where(ChatCorrectionSampleRow.session_id == session_id)
                .order_by(ChatCorrectionSampleRow.created_at, ChatCorrectionSampleRow.sample_id)
                .offset(max(0, int(offset)))
                .limit(max(1, min(int(limit), 200)))
            )
            return tuple(_sample_record(row) for row in rows)

    async def append_review(self, review: ChatCorrectionReview) -> ChatCorrectionReview:
        async with self.session_factory.begin() as session:
            sample = await session.get(ChatCorrectionSampleRow, review.sample_id, with_for_update=True)
            if sample is None or sample.session_id != review.session_id:
                raise FileNotFoundError(f"chat correction sample not found: {review.sample_id}")
            existing = await session.get(ChatCorrectionReviewRow, review.review_id, with_for_update=True)
            if existing is not None:
                saved = _review_record(existing)
                candidate = replace(review, seq=saved.seq)
                if saved.to_record() != candidate.to_record():
                    raise ValueError("correction review identity cannot be reassigned")
                return saved
            max_seq = await session.scalar(
                select(func.max(ChatCorrectionReviewRow.seq)).where(
                    ChatCorrectionReviewRow.sample_id == review.sample_id
                )
            )
            seq = review.seq if review.seq > 0 else int(max_seq or 0) + 1
            conflict = await session.scalar(
                select(ChatCorrectionReviewRow).where(
                    ChatCorrectionReviewRow.sample_id == review.sample_id,
                    ChatCorrectionReviewRow.seq == seq,
                )
            )
            if conflict is not None:
                raise ValueError("correction review sequence already exists")
            row = ChatCorrectionReviewRow(
                review_id=review.review_id,
                sample_id=review.sample_id,
                session_id=review.session_id,
                sample_digest=review.sample_digest,
                decision=review.decision.value,
                reviewer_id=review.reviewer_id,
                reason=review.reason,
                support_message_ids=list(review.support_message_ids),
                seq=seq,
                created_at=_datetime(review.created_at),
            )
            session.add(row)
            await session.flush()
            return _review_record(row)

    async def list_reviews(
        self, session_id: str, sample_id: str
    ) -> tuple[ChatCorrectionReview, ...]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(ChatCorrectionReviewRow)
                .where(
                    ChatCorrectionReviewRow.session_id == session_id,
                    ChatCorrectionReviewRow.sample_id == sample_id,
                )
                .order_by(ChatCorrectionReviewRow.seq)
            )
            return tuple(_review_record(row) for row in rows)


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _sample_record(row: ChatCorrectionSampleRow) -> ChatCorrectionSample:
    return ChatCorrectionSample(
        sample_id=row.sample_id,
        case_id=row.case_id,
        session_id=row.session_id,
        collection_id=row.collection_id,
        model_call_id=row.model_call_id,
        input=dict(row.input or {}),
        observations=tuple(dict(item) for item in row.observations or []),
        target=row.target,
        source_refs=tuple(dict(item) for item in row.source_refs or []),
        digest=row.digest,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _review_record(row: ChatCorrectionReviewRow) -> ChatCorrectionReview:
    return ChatCorrectionReview(
        review_id=row.review_id,
        sample_id=row.sample_id,
        session_id=row.session_id,
        sample_digest=row.sample_digest,
        decision=row.decision,
        reviewer_id=row.reviewer_id,
        reason=row.reason,
        support_message_ids=tuple(str(item) for item in row.support_message_ids or []),
        seq=row.seq,
        created_at=_iso(row.created_at),
    )


__all__ = ["PostgresChatCorrectionReviewRepository"]
