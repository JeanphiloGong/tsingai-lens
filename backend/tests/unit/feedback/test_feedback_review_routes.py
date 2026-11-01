from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from controllers import feedback_case_routes as feedback_cases
from controllers.feedback_case_routes import FeedbackReviewRequest
from domain.feedback import ReviewDecision
from exceptions import ResourceConflictException, ResourceNotFoundException


def _request(service, user_id: str = "user-1"):
    feedback_cases.feedback_case_service = service
    return SimpleNamespace(state=SimpleNamespace(current_user={"user_id": user_id}))


class _Service:
    def __init__(self):
        self.review_kwargs = None

    async def submit_feedback_review_for_user(self, **kwargs):
        self.review_kwargs = kwargs
        return ReviewDecision(
            decision_id="review-1",
            case_id=kwargs["case_id"],
            annotation_digest=kwargs["expected_annotation_digest"],
            decision=kwargs["decision"],
            reason=kwargs["reason"],
            created_by=kwargs["user_id"],
            seq=1,
            created_at="2026-09-24T00:00:00+00:00",
        )

    async def list_feedback_reviews_for_user(self, **kwargs):
        return ()


def test_review_routes_append_and_read_history():
    service = _Service()
    payload = FeedbackReviewRequest(
        expected_annotation_digest="a" * 64, decision="accept", reason="checked"
    )
    response = feedback_cases.FeedbackReviewDecisionResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    feedback_cases.submit_feedback_review(
                        case_id="case-1",
                        payload=payload,
                        user_id=_request(service).state.current_user["user_id"],
                        idempotency_key="retry-1",
                    )
                )
            ).body
        )["data"]
    )
    assert response.decision == "accept"
    assert service.review_kwargs["idempotency_key"] == "retry-1"
    listing = feedback_cases.FeedbackReviewDecisionListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    feedback_cases.list_feedback_reviews(
                        case_id="case-1",
                        user_id=_request(service).state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    assert listing.items == []


def test_review_route_maps_stale_digest_to_conflict():
    class StaleService(_Service):
        async def submit_feedback_review_for_user(self, **kwargs):
            raise ResourceConflictException(
                "The case changed.", data={"code": "feedback_case_stale"}
            )

    payload = FeedbackReviewRequest(
        expected_annotation_digest="a" * 64, decision="accept", reason="checked"
    )
    with pytest.raises(ResourceConflictException) as error:
        feedback_cases.FeedbackReviewDecisionResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        feedback_cases.submit_feedback_review(
                            case_id="case-1",
                            payload=payload,
                            user_id=_request(StaleService()).state.current_user[
                                "user_id"
                            ],
                        )
                    )
                ).body
            )["data"]
        )
    assert error.value.code == 200204
    assert error.value.data["code"] == "feedback_case_stale"
