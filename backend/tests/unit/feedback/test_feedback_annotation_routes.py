from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from controllers import feedback_cases
from controllers.feedback_cases import FeedbackAnnotationRequest
from domain.feedback import FeedbackAnnotation


def _request(service, user_id: str = "user-1"):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(feedback_case_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


class _Service:
    async def save_annotation_for_user(self, **kwargs):
        if kwargs["user_id"] != "user-1":
            raise FileNotFoundError("feedback case not found")
        return FeedbackAnnotation.build(
            annotation_id="annotation-1", case_id=kwargs["case_id"], version=1,
            problem_type=kwargs["problem_type"], severity=kwargs["severity"], target=kwargs["target"],
            support_source_refs=kwargs["support_source_refs"], dataset_uses=kwargs["dataset_uses"],
            reason=kwargs["reason"], created_by="user-1", created_at="2026-09-24T00:00:00+00:00",
        )


def test_annotation_route_returns_digest_without_accepting_client_identity():
    payload = FeedbackAnnotationRequest(
        problem_type="source_missing", severity="high", target=None,
        support_source_refs=["source-a"], dataset_uses=["evaluation"], reason="checked source",
    )
    response = asyncio.run(
        feedback_cases.save_feedback_annotation("case-1", payload, _request(_Service()))
    )
    assert response.annotation_id == "annotation-1"
    assert response.created_by == "user-1"


def test_annotation_route_maps_stale_digest_to_conflict():
    class StaleService(_Service):
        async def save_annotation_for_user(self, **kwargs):
            raise ValueError("feedback_case_stale")

    payload = FeedbackAnnotationRequest(
        expected_digest="a" * 64, problem_type="source_missing", severity="high",
        dataset_uses=["evaluation"], reason="checked source",
    )
    with pytest.raises(Exception) as error:
        asyncio.run(feedback_cases.save_feedback_annotation("case-1", payload, _request(StaleService())))
    assert getattr(error.value, "status_code", None) == 409
