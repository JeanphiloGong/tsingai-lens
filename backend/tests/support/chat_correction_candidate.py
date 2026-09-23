from __future__ import annotations

from domain.evaluation import ChatCorrectionCandidate


class MemoryChatCorrectionCandidateRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.candidates: dict[str, ChatCorrectionCandidate] = {}

    async def save_candidate(self, candidate: ChatCorrectionCandidate) -> ChatCorrectionCandidate:
        existing = self.candidates.get(candidate.candidate_id)
        if existing is not None:
            if existing.to_record() != candidate.to_record():
                raise ValueError("candidate identity cannot be reassigned")
            return existing
        self.candidates[candidate.candidate_id] = candidate
        return candidate

    async def read_candidate_for_user(
        self, session_id: str, candidate_id: str, user_id: str
    ) -> ChatCorrectionCandidate | None:
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate.session_id != session_id or candidate.owner_id != user_id:
            return None
        return candidate

    async def list_candidates_for_user(
        self, session_id: str, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[ChatCorrectionCandidate, ...]:
        values = sorted(
            (
                item
                for item in self.candidates.values()
                if item.session_id == session_id and item.owner_id == user_id
            ),
            key=lambda item: (item.created_at, item.candidate_id),
        )
        start = max(0, int(offset))
        return tuple(values[start : start + max(1, min(int(limit), 200))])

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
        candidate = await self.read_candidate_for_user(session_id, candidate_id, user_id)
        if candidate is None:
            raise FileNotFoundError(candidate_id)
        if candidate.selected_sample_id is not None:
            if candidate.selected_sample_id != sample_id or candidate.selected_case_id != case_id:
                raise ValueError("candidate selection cannot be reassigned")
            return candidate
        selected = candidate.with_selection(
            case_id=case_id, sample_id=sample_id, updated_at=updated_at
        )
        self.candidates[candidate_id] = selected
        return selected


__all__ = ["MemoryChatCorrectionCandidateRepository"]
