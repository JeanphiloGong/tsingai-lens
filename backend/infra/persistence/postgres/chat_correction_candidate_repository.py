"""PostgreSQL persistence for Chat correction candidate proposals."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.evaluation import ChatCorrectionCandidate
from infra.persistence.postgres.models.chat_correction_candidate import (
    ChatCorrectionCandidateRow,
)


class PostgresChatCorrectionCandidateRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save_candidate(
        self, candidate: ChatCorrectionCandidate
    ) -> ChatCorrectionCandidate:
        async with self.session_factory.begin() as session:
            existing = await session.get(
                ChatCorrectionCandidateRow, candidate.candidate_id, with_for_update=True
            )
            if existing is not None:
                saved = _candidate_record(existing)
                if saved.to_record() != candidate.to_record():
                    raise ValueError("candidate identity cannot be reassigned")
                return saved
            row = ChatCorrectionCandidateRow(
                candidate_id=candidate.candidate_id,
                owner_id=candidate.owner_id,
                collection_id=candidate.collection_id,
                session_id=candidate.session_id,
                challenge_message_id=candidate.challenge_message_id,
                answer_message_id=candidate.answer_message_id,
                event_ids=list(candidate.event_ids),
                model_call_ids=list(candidate.model_call_ids),
                status=candidate.status.value,
                proposal=candidate.proposal,
                request=candidate.request,
                raw_response=candidate.raw_response,
                finish_reason=candidate.finish_reason,
                error_code=candidate.error_code,
                selected_case_id=candidate.selected_case_id,
                selected_sample_id=candidate.selected_sample_id,
                digest=candidate.digest,
                created_at=_datetime(candidate.created_at),
                updated_at=_datetime(candidate.updated_at),
            )
            session.add(row)
            await session.flush()
            return _candidate_record(row)

    async def read_candidate_for_user(
        self, session_id: str, candidate_id: str, user_id: str
    ) -> ChatCorrectionCandidate | None:
        async with self.session_factory() as session:
            row = await session.get(ChatCorrectionCandidateRow, candidate_id)
            if row is None or row.session_id != session_id or row.owner_id != user_id:
                return None
            return _candidate_record(row)

    async def list_candidates_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatCorrectionCandidate, ...]:
        statement = (
            select(ChatCorrectionCandidateRow)
            .where(
                ChatCorrectionCandidateRow.session_id == session_id,
                ChatCorrectionCandidateRow.owner_id == user_id,
            )
            .order_by(ChatCorrectionCandidateRow.created_at, ChatCorrectionCandidateRow.candidate_id)
            .offset(max(0, int(offset)))
            .limit(max(1, min(int(limit), 200)))
        )
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_candidate_record(row) for row in rows)

    async def mark_selected(
        self,
        session_id: str,
        candidate_id: str,
        user_id: str,
        *,
        case_id: str,
        sample_id: str,
        updated_at: str,
    ) -> ChatCorrectionCandidate:
        async with self.session_factory.begin() as session:
            row = await session.get(ChatCorrectionCandidateRow, candidate_id, with_for_update=True)
            if row is None or row.session_id != session_id or row.owner_id != user_id:
                raise FileNotFoundError(f"chat correction candidate not found: {candidate_id}")
            current = _candidate_record(row)
            if current.selected_sample_id is not None:
                if current.selected_sample_id != sample_id or current.selected_case_id != case_id:
                    raise ValueError("candidate selection cannot be reassigned")
                return current
            selected = current.with_selection(
                case_id=case_id, sample_id=sample_id, updated_at=updated_at
            )
            row.selected_case_id = selected.selected_case_id
            row.selected_sample_id = selected.selected_sample_id
            row.updated_at = _datetime(selected.updated_at)
            row.digest = selected.digest
            await session.flush()
            return _candidate_record(row)


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _candidate_record(row: ChatCorrectionCandidateRow) -> ChatCorrectionCandidate:
    return ChatCorrectionCandidate(
        candidate_id=row.candidate_id,
        owner_id=row.owner_id,
        collection_id=row.collection_id,
        session_id=row.session_id,
        challenge_message_id=row.challenge_message_id,
        answer_message_id=row.answer_message_id,
        event_ids=tuple(str(item) for item in row.event_ids or []),
        model_call_ids=tuple(str(item) for item in row.model_call_ids or []),
        status=row.status,
        proposal=dict(row.proposal) if row.proposal is not None else None,
        request=dict(row.request or {}),
        raw_response=row.raw_response,
        finish_reason=row.finish_reason,
        error_code=row.error_code,
        selected_case_id=row.selected_case_id,
        selected_sample_id=row.selected_sample_id,
        digest=row.digest,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


__all__ = ["PostgresChatCorrectionCandidateRepository"]
