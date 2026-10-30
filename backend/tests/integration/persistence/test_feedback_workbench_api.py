from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

import pytest
from application.auth import session_service as auth_session_service
from application.auth.session_service import SESSION_COOKIE_NAME
from controllers import feedback_case_routes as feedback_cases
from controllers.exception_router import (
    general_exception_handler,
    http_exception_handler,
    project_exception_handler,
    request_validation_handler,
)
from exceptions import ProjectException
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from main import configure_middleware
from repositories.auth_repository import AuthSessionRecord, AuthUserRecord
from starlette.exceptions import HTTPException as StarletteHTTPException
from tests.integration.persistence.test_feedback_workbench import feedback_chain

pytestmark = pytest.mark.anyio

OWNER_ID = "feedback-chain-user"
OTHER_ID = "feedback-api-other"
OTHER_EMAIL = "feedback-api-other@example.test"
OTHER_TOKEN = "feedback-api-other-token"
OWNER_TOKEN = "feedback-api-owner-token"
NOW = "2026-09-25T00:00:00+00:00"


async def _create_session(auth_repository, *, token: str, user_id: str) -> None:
    await auth_repository.add_session(
        AuthSessionRecord(
            session_id=f"session_{user_id}",
            user_id=user_id,
            created_at=NOW,
            expires_at="2030-01-01T00:00:00+00:00",
        ),
        token_hash=sha256(token.encode("utf-8")).hexdigest(),
    )


async def _prepare_case(chain) -> object:
    feedback = await chain.chat_service.set_message_feedback_for_user(
        chain.session.session_id,
        chain.answer.message_id,
        OWNER_ID,
        rating="not_helpful",
        reason="incorrect",
        comment="Paper B contains the missing evidence.",
    )
    assert feedback is not None
    from application.feedback.analysis_handler import FeedbackAnalysisHandler
    from application.feedback.analysis_worker import FeedbackAnalysisWorker

    worker = FeedbackAnalysisWorker(
        job_repository=chain.jobs,
        case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    )
    terminal_job = await worker.run_once()
    assert terminal_job is not None and terminal_job.result_id is not None
    cases = await chain.cases.list_cases(
        collection_id=chain.session.collection_id, status="needs_annotation"
    )
    assert len(cases) == 1
    return cases[0]


@pytest.fixture
async def feedback_api(feedback_chain):
    chain = feedback_chain
    auth_repository = chain.auth
    await auth_repository.add_user(
        AuthUserRecord(
            user_id=OTHER_ID,
            email=OTHER_EMAIL,
            display_name="Other researcher",
            password_hash="synthetic-password-hash",
            created_at=NOW,
        )
    )
    await _create_session(auth_repository, token=OWNER_TOKEN, user_id=OWNER_ID)
    await _create_session(auth_repository, token=OTHER_TOKEN, user_id=OTHER_ID)
    case = await _prepare_case(chain)

    app = FastAPI()
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    configure_middleware(app)
    app.include_router(feedback_cases.feedback_case_router, prefix="/api/v1")
    feedback_cases.feedback_case_service = chain.case_service
    auth_session_service.AuthRepo = auth_repository

    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={SESSION_COOKIE_NAME: OWNER_TOKEN},
        ) as owner,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={SESSION_COOKIE_NAME: OTHER_TOKEN},
        ) as other,
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anonymous,
    ):
        yield SimpleNamespace(
            chain=chain,
            case=case,
            owner=owner,
            other=other,
            anonymous=anonymous,
        )


def _annotation_payload(*, expected_digest: str | None = None, reason: str = "checked"):
    return {
        "expected_digest": expected_digest,
        "problem_type": "source_missing",
        "severity": "high",
        "target": None,
        "support_source_refs": [],
        "dataset_uses": ["evaluation"],
        "reason": reason,
    }


async def test_feedback_api_requires_auth_and_hides_collection_from_other_user(
    feedback_api,
):
    fixture = feedback_api
    path = "/api/v1/feedback-cases"
    rejection = await fixture.anonymous.get(path)
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200301

    listing = await fixture.owner.get(
        path, params={"collection_id": fixture.case.collection_id}
    )
    assert listing.status_code == 200, listing.text
    assert [item["case_id"] for item in listing.json()["data"]["items"]] == [
        fixture.case.case_id
    ]

    detail = await fixture.owner.get(f"{path}/{fixture.case.case_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["case_id"] == fixture.case.case_id

    rejection = await fixture.other.get(
        path, params={"collection_id": fixture.case.collection_id}
    )
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200201
    rejection = await fixture.other.get(f"{path}/{fixture.case.case_id}")
    assert rejection.status_code == 200
    assert rejection.json()["code"] == 200201


async def test_annotation_digest_conflict_and_rejected_case_revision_are_http_visible(
    feedback_api,
):
    fixture = feedback_api
    path = f"/api/v1/feedback-cases/{fixture.case.case_id}"

    first = await fixture.owner.patch(f"{path}/annotation", json=_annotation_payload())
    assert first.status_code == 200, first.text
    first_annotation = first.json()["data"]
    assert first_annotation["version"] == 1
    digest = first_annotation["annotation_digest"]

    stale_annotation = await fixture.owner.patch(
        f"{path}/annotation", json=_annotation_payload(reason="stale write")
    )
    assert stale_annotation.status_code == 200
    assert stale_annotation.json()["code"] == 200204
    assert stale_annotation.json()["data"]["code"] == "feedback_case_stale"

    rejected = await fixture.owner.post(
        f"{path}/review",
        json={
            "expected_annotation_digest": digest,
            "decision": "reject",
            "reason": "Add the source explanation before accepting.",
        },
        headers={"Idempotency-Key": "reject-v1"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["decision"] == "reject"

    revised = await fixture.owner.patch(
        f"{path}/annotation",
        json=_annotation_payload(
            expected_digest=digest, reason="Clarified source omission."
        ),
    )
    assert revised.status_code == 200, revised.text
    revised_annotation = revised.json()["data"]
    assert revised_annotation["version"] == 2
    assert revised_annotation["annotation_digest"] != digest

    stale_review = await fixture.owner.post(
        f"{path}/review",
        json={
            "expected_annotation_digest": digest,
            "decision": "accept",
            "reason": "Old annotation cannot be accepted.",
        },
        headers={"Idempotency-Key": "stale-review"},
    )
    assert stale_review.status_code == 200
    assert stale_review.json()["code"] == 200204
    assert stale_review.json()["data"]["code"] == "feedback_case_stale"

    current = await fixture.owner.get(path)
    assert current.json()["data"]["status"] == "ready_for_review"


async def test_review_http_retry_replays_one_append_only_decision(feedback_api):
    fixture = feedback_api
    path = f"/api/v1/feedback-cases/{fixture.case.case_id}"
    annotation = await fixture.owner.patch(
        f"{path}/annotation", json=_annotation_payload()
    )
    assert annotation.status_code == 200, annotation.text
    digest = annotation.json()["data"]["annotation_digest"]
    payload = {
        "expected_annotation_digest": digest,
        "decision": "accept",
        "reason": "The evidence boundary was checked.",
    }
    headers = {"Idempotency-Key": "accept-retry-1"}

    first = await fixture.owner.post(f"{path}/review", json=payload, headers=headers)
    second = await fixture.owner.post(f"{path}/review", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["data"] == first.json()["data"]
    assert (
        len(
            (await fixture.owner.get(f"{path}/review-decisions")).json()["data"][
                "items"
            ]
        )
        == 1
    )

    conflicting_retry = await fixture.owner.post(
        f"{path}/review",
        json={**payload, "reason": "A different logical request."},
        headers=headers,
    )
    assert conflicting_retry.status_code == 200
    assert conflicting_retry.json()["code"] == 200204
    assert (
        conflicting_retry.json()["data"]["code"] == "review_decision_identity_conflict"
    )
