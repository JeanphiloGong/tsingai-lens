"""Persistence contract for owner-scoped Chat correction proposals."""

from __future__ import annotations

from typing import Protocol

from domain.evaluation import ChatCorrectionCandidate


class ChatCorrectionCandidateRepository(Protocol):
    backend_name: str

    async def save_candidate(
        self, candidate: ChatCorrectionCandidate
    ) -> ChatCorrectionCandidate: ...

    async def read_candidate_for_user(
        self, session_id: str, candidate_id: str, user_id: str
    ) -> ChatCorrectionCandidate | None: ...

    async def list_candidates_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatCorrectionCandidate, ...]: ...

    async def mark_selected(
        self,
        session_id: str,
        candidate_id: str,
        user_id: str,
        *,
        case_id: str,
        sample_id: str,
        updated_at: str,
    ) -> ChatCorrectionCandidate: ...


__all__ = ["ChatCorrectionCandidateRepository"]
