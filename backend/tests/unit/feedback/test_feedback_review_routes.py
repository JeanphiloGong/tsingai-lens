from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from controllers import feedback_cases
from controllers.feedback_cases import FeedbackReviewRequest
from domain.feedback import ReviewDecision


def _request(service, user_id: str = "user-1"):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(feedback_case_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


class _Service:
    def __init__(self):
        self.review_kwargs = None

    async def submit_review_for_user(self, **kwargs):
        self.review_kwargs = kwargs
        return ReviewDecision(
            decision_id="review-1", case_id=kwargs["case_id"], annotation_digest=kwargs["expected_annotation_digest"],
            decision=kwargs["decision"], reason=kwargs["reason"], created_by=kwargs["user_id"], seq=1,
            created_at="2026-09-24T00:00:00+00:00",
        )

    async def list_reviews_for_user(self, **kwargs):
        return ()


def test_review_routes_append_and_read_history():
    service = _Service()
    payload = FeedbackReviewRequest(expected_annotation_digest="a" * 64, decision="accept", reason="checked")
    response = asyncio.run(
        feedback_cases.submit_feedback_review(
            "case-1", payload, _request(service), idempotency_key="retry-1"
        )
    )
    assert response.decision == "accept"
    assert service.review_kwargs["idempotency_key"] == "retry-1"
    listing = asyncio.run(feedback_cases.list_feedback_reviews("case-1", _request(service)))
    assert listing.items == []


def test_review_route_maps_stale_digest_to_conflict():
    class StaleService(_Service):
        async def submit_review_for_user(self, **kwargs):
            raise ValueError("feedback_case_stale")

    payload = FeedbackReviewRequest(expected_annotation_digest="a" * 64, decision="accept", reason="checked")
    with pytest.raises(Exception) as error:
        asyncio.run(feedback_cases.submit_feedback_review("case-1", payload, _request(StaleService())))
    assert getattr(error.value, "status_code", None) == 409
