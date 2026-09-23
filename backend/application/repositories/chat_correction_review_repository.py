"""Persistence contract for Chat correction samples and review history."""

from __future__ import annotations

from typing import Protocol

from domain.evaluation import ChatCorrectionReview, ChatCorrectionSample


class ChatCorrectionReviewRepository(Protocol):
    backend_name: str

    async def save_sample(
        self, sample: ChatCorrectionSample
    ) -> ChatCorrectionSample: ...

    async def read_sample(
        self, session_id: str, sample_id: str
    ) -> ChatCorrectionSample | None: ...

    async def list_samples(
        self, session_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[ChatCorrectionSample, ...]: ...

    async def append_review(
        self, review: ChatCorrectionReview
    ) -> ChatCorrectionReview: ...

    async def list_reviews(
        self, session_id: str, sample_id: str
    ) -> tuple[ChatCorrectionReview, ...]: ...


__all__ = ["ChatCorrectionReviewRepository"]
