from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.goal.session_service import GoalSessionService
from application.core.comparison_service import ComparisonService
from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
)
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.core.workspace_overview_service import WorkspaceService
from application.source.task_service import TaskService
from tests.support.collection_service import build_test_collection_service
from controllers.goal import sessions as sessions_controller
from controllers.schemas.goal.session import (
    GoalSessionCreateRequest,
    GoalSessionMessageRequest,
)
from infra.persistence.factory import build_goal_session_repository
from infra.persistence.memory import MemoryBuildRepository
from infra.persistence.sqlite import (
    SqliteCoreFactRepository,
    SqliteSourceArtifactRepository,
)
from tests.support.paper_fact_repository import MemoryPaperFactRepository


def _request(goal_session_service, user_id: str = "local-user"):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(goal_session_service=goal_session_service),
        ),
        state=SimpleNamespace(current_user={"user_id": user_id}),
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
def goal_session_services(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    task_service = TaskService(MemoryBuildRepository())
    source_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    paper_fact_repository = MemoryPaperFactRepository()
    core_fact_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    document_profile_service = DocumentProfileService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
    )
    workspace_service = WorkspaceService(
        collection_service=collection_service,
        task_service=task_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        core_fact_repository=core_fact_repository,
        document_profile_service=document_profile_service,
    )
    research_objective_service = ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        core_fact_repository=core_fact_repository,
        document_profile_service=document_profile_service,
    )
    comparison_service = ComparisonService(
        collection_service=collection_service,
        paper_fact_repository=paper_fact_repository,
        core_fact_repository=core_fact_repository,
        document_profile_service=document_profile_service,
    )
    paper_facts_service = PaperFactsService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        core_fact_repository=core_fact_repository,
        document_profile_service=document_profile_service,
    )
    service = GoalSessionService(
        collection_service=collection_service,
        research_view_service=ResearchViewAggregationService(
            collection_service=collection_service,
            source_artifact_repository=source_repository,
            paper_fact_repository=paper_fact_repository,
            core_fact_repository=core_fact_repository,
        ),
        workspace_service=workspace_service,
        research_objective_service=research_objective_service,
        comparison_service=comparison_service,
        paper_facts_service=paper_facts_service,
        goal_session_repository=build_goal_session_repository(tmp_path / "lens.sqlite"),
        llm_client=_FakeLLMClient("General background."),
        model="fake-model",
    )
    return collection_service, service


def test_goal_sessions_route_creates_minimal_session_and_messages(
    goal_session_services,
):
    collection_service, service = goal_session_services
    collection = collection_service.create_collection("Copilot Collection")

    session = asyncio.run(
        sessions_controller.create_goal_session(
            GoalSessionCreateRequest(
                collection_id=collection["collection_id"],
                focused_objective_id="obj_lpbf_strength",
                focused_goal_id="goal_lpbf_strength",
            ),
            _request(service),
        )
    )
    response = asyncio.run(
        sessions_controller.post_goal_session_message(
            session.session_id,
            GoalSessionMessageRequest(
                message="What does the collection say?",
                page_context={},
            ),
            _request(service),
        )
    )
    messages = asyncio.run(
        sessions_controller.list_goal_session_messages(
            session.session_id,
            _request(service),
        )
    )

    assert session.collection_id == collection["collection_id"]
    assert session.focused_objective_id == "obj_lpbf_strength"
    assert session.focused_goal_id == "goal_lpbf_strength"
    assert session.goal_text is None
    assert session.goal_brief_json == {}
    assert session.answer_mode == "hybrid"
    assert response.source_mode == "general_fallback"
    assert response.used_evidence_ids == []
    assert response.source_links == []
    assert len(messages.items) == 2


def test_goal_sessions_route_returns_404_for_missing_session(goal_session_services):
    _collection_service, service = goal_session_services
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            sessions_controller.get_goal_session("gs_missing", _request(service))
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "goal_session_not_found"


def test_goal_sessions_route_hides_other_user_session(goal_session_services):
    collection_service, service = goal_session_services
    collection = collection_service.create_collection("Copilot Collection")
    session = asyncio.run(
        sessions_controller.create_goal_session(
            GoalSessionCreateRequest(collection_id=collection["collection_id"]),
            _request(service, "user-a"),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            sessions_controller.get_goal_session(
                session.session_id,
                _request(service, "user-b"),
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "goal_session_not_found"
