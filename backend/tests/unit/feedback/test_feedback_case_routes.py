from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from application.feedback.feedback_case_service import FeedbackCaseSummary
from controllers import feedback_case_routes as feedback_cases
from exceptions import ResourceConflictException, ResourceNotFoundException
from fastapi import HTTPException


def _request(service, user_id: str = "user-1"):
    feedback_cases.feedback_case_service = service
    return SimpleNamespace(state=SimpleNamespace(current_user={"user_id": user_id}))


class _Service:
    async def list_for_user(self, **kwargs):
        if kwargs["user_id"] != "user-1":
            raise ResourceNotFoundException("collection not found")
        return (
            FeedbackCaseSummary(
                case_id="case-1",
                collection_id="collection-1",
                status="needs_annotation",
                anchor_message_id="answer-1",
                problem_type="source_missing",
                confidence=0.87,
                needs_human_review=True,
                created_at="2026-09-24T00:00:00+00:00",
            ),
        )

    async def read_for_user(self, case_id: str, user_id: str):
        if user_id != "user-1" or case_id != "case-1":
            raise ResourceNotFoundException("feedback case not found")
        return {
            "case_id": "case-1",
            "collection_id": "collection-1",
            "session_id": "session-1",
            "status": "needs_annotation",
            "source_signals": [],
            "question": "Question",
            "answer": "Answer",
            "requested_scope": [],
            "inspected_sources": [],
            "omitted_candidates": [],
            "claim_support": [],
            "gaps": [],
            "analysis": None,
            "annotation": None,
            "current_annotation_digest": None,
            "created_at": "2026-09-24T00:00:00+00:00",
            "updated_at": "2026-09-24T00:00:00+00:00",
        }


def test_feedback_case_routes_return_summary_and_detail_without_client_ids():
    request = _request(_Service())
    listing = feedback_cases.FeedbackCaseListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    feedback_cases.list_feedback_cases(
                        user_id=request.state.current_user["user_id"],
                        collection_id="collection-1",
                        limit=50,
                        offset=0,
                    )
                )
            ).body
        )["data"]
    )
    detail = feedback_cases.FeedbackCaseDetailResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    feedback_cases.get_feedback_case(
                        case_id="case-1", user_id=request.state.current_user["user_id"]
                    )
                )
            ).body
        )["data"]
    )
    assert listing.items[0].problem_type == "source_missing"
    assert listing.limit == 50
    assert detail.question == "Question"


def test_feedback_case_detail_hides_unauthorized_case():
    with pytest.raises(ResourceNotFoundException) as error:
        feedback_cases.FeedbackCaseDetailResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        feedback_cases.get_feedback_case(
                            case_id="case-1",
                            user_id=_request(
                                _Service(), "other-user"
                            ).state.current_user["user_id"],
                        )
                    )
                ).body
            )["data"]
        )
    assert error.value.code == 200201


def test_feedback_case_list_hides_unauthorized_collection():
    with pytest.raises(ResourceNotFoundException) as error:
        feedback_cases.FeedbackCaseListResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        feedback_cases.list_feedback_cases(
                            user_id=_request(
                                _Service(), "other-user"
                            ).state.current_user["user_id"],
                            collection_id="collection-1",
                            limit=50,
                            offset=0,
                        )
                    )
                ).body
            )["data"]
        )
    assert error.value.code == 200201
