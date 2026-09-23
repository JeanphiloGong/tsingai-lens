from __future__ import annotations

from dataclasses import replace

from domain.evaluation import ChatCorrectionReview, ChatCorrectionSample


class MemoryChatCorrectionReviewRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.samples: dict[str, ChatCorrectionSample] = {}
        self.reviews: dict[str, list[ChatCorrectionReview]] = {}

    async def save_sample(self, sample: ChatCorrectionSample) -> ChatCorrectionSample:
        existing = self.samples.get(sample.sample_id)
        if existing is not None:
            if existing.to_record() != sample.to_record():
                raise ValueError("correction sample identity cannot be reassigned")
            return existing
        by_case = next((item for item in self.samples.values() if item.case_id == sample.case_id), None)
        if by_case is not None:
            if by_case.to_record() != sample.to_record():
                raise ValueError("correction sample case identity cannot be reassigned")
            return by_case
        self.samples[sample.sample_id] = sample
        self.reviews.setdefault(sample.sample_id, [])
        return sample

    async def read_sample(self, session_id: str, sample_id: str) -> ChatCorrectionSample | None:
        sample = self.samples.get(sample_id)
        return sample if sample is not None and sample.session_id == session_id else None

    async def list_samples(self, session_id: str, *, limit: int = 50, offset: int = 0):
        values = sorted(
            (item for item in self.samples.values() if item.session_id == session_id),
            key=lambda item: (item.created_at, item.sample_id),
        )
        start = max(0, int(offset))
        return tuple(values[start : start + max(1, min(int(limit), 200))])

    async def append_review(self, review: ChatCorrectionReview) -> ChatCorrectionReview:
        if review.sample_id not in self.samples:
            raise FileNotFoundError(review.sample_id)
        values = self.reviews.setdefault(review.sample_id, [])
        existing = next((item for item in values if item.review_id == review.review_id), None)
        if existing is not None:
            return existing
        saved = replace(review, seq=(review.seq or len(values) + 1))
        values.append(saved)
        return saved

    async def list_reviews(self, session_id: str, sample_id: str):
        sample = await self.read_sample(session_id, sample_id)
        if sample is None:
            raise FileNotFoundError(sample_id)
        return tuple(sorted(self.reviews.get(sample_id, []), key=lambda item: item.seq))


__all__ = ["MemoryChatCorrectionReviewRepository"]
