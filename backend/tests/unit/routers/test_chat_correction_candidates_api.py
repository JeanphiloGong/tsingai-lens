from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from controllers.chat import sessions as sessions_controller
from controllers.schemas.chat.session import ChatCorrectionCandidateCreateRequest
from domain.evaluation import ChatCorrectionCandidate


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _candidate() -> ChatCorrectionCandidate:
    return ChatCorrectionCandidate.create(
        candidate_id="candidate-1",
        owner_id="researcher",
        collection_id="collection-1",
        session_id="session-1",
        challenge_message_id=None,
        answer_message_id=None,
        event_ids=(),
        model_call_ids=(),
        status="no_candidate",
        proposal=None,
        request={"messages": []},
        raw_response=None,
        finish_reason=None,
        error_code="no_correction_sequence",
        created_at="2026-09-23T00:00:00+00:00",
    )


def _request(service: object | None) -> SimpleNamespace:
    state = SimpleNamespace()
    if service is not None:
        state.chat_correction_candidate_service = service
    return SimpleNamespace(app=SimpleNamespace(state=state))


class _CandidateService:
    def __init__(self, candidate: ChatCorrectionCandidate) -> None:
        self.candidate = candidate
        self.user_ids: list[str] = []

    async def propose_for_user(self, session_id: str, user_id: str, **kwargs):
        self.user_ids.append(user_id)
        assert session_id == "session-1"
        return self.candidate

    async def select_for_user(self, session_id: str, candidate_id: str, user_id: str):
        self.user_ids.append(user_id)
        raise ValueError("only a needs_review candidate can be selected")


async def test_candidate_route_returns_503_when_service_is_not_configured() -> None:
    with pytest.raises(HTTPException) as raised:
        await sessions_controller.create_chat_correction_candidate(
            "session-1",
            ChatCorrectionCandidateCreateRequest(),
            _request(None),
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "chat_correction_candidate_unavailable"


async def test_candidate_route_serializes_a_saved_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _CandidateService(_candidate())

    async def current_user(_request: object) -> str:
        return "researcher"

    monkeypatch.setattr(sessions_controller, "current_user_id", current_user)
    response = await sessions_controller.create_chat_correction_candidate(
        "session-1",
        ChatCorrectionCandidateCreateRequest(),
        _request(service),
    )

    assert response.candidate_id == "candidate-1"
    assert response.status == "no_candidate"
    assert service.user_ids == ["researcher"]


async def test_candidate_selection_maps_non_selectable_proposal_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _CandidateService(_candidate())

    async def current_user(_request: object) -> str:
        return "researcher"

    monkeypatch.setattr(sessions_controller, "current_user_id", current_user)
    with pytest.raises(HTTPException) as raised:
        await sessions_controller.select_chat_correction_candidate(
            "session-1", "candidate-1", _request(service)
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "chat_correction_candidate_not_selectable"
