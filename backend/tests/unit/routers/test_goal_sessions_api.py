from __future__ import annotations

import asyncio

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.goal.session_service import GoalSessionService
from application.source.collection_service import CollectionService
from controllers.goal import sessions as sessions_controller
from controllers.schemas.goal.session import (
    GoalSessionCreateRequest,
    GoalSessionMessageRequest,
)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content

    def create(self, **_kwargs):  # noqa: ANN003, ANN201
        return _FakeCompletion(self.content)


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)


class _FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.chat = _FakeChat(content)


@pytest.fixture()
def goal_session_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    service = GoalSessionService(
        collection_service=collection_service,
        llm_client=_FakeLLMClient("General background."),
        model="fake-model",
    )
    monkeypatch.setattr(sessions_controller, "goal_session_service", service)
    return collection_service, service


def test_goal_sessions_route_creates_and_messages_session(goal_session_services):
    collection_service, _service = goal_session_services
    collection = collection_service.create_collection("Copilot Collection")

    session = asyncio.run(
        sessions_controller.create_goal_session(
            GoalSessionCreateRequest(
                collection_id=collection["collection_id"],
                goal_text="Compare LPBF strength and ductility.",
                answer_mode="hybrid",
            )
        )
    )
    response = asyncio.run(
        sessions_controller.post_goal_session_message(
            session.session_id,
            GoalSessionMessageRequest(
                message="What does the collection say?",
                page_context={},
            ),
        )
    )
    messages = asyncio.run(
        sessions_controller.list_goal_session_messages(session.session_id)
    )

    assert session.collection_id == collection["collection_id"]
    assert response.source_mode == "general_fallback"
    assert response.used_evidence_ids == []
    assert len(messages.items) == 2


def test_goal_sessions_route_returns_404_for_missing_session(goal_session_services):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(sessions_controller.get_goal_session("gs_missing"))

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "goal_session_not_found"
