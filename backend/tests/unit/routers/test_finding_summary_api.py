from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.core.objectives.finding_summary import FindingSummaryUnavailable
from controllers.core import research_objective_routes
from controllers.core.research_objective_routes import (
    research_objective_router as router,
)
from controllers.dependencies.auth import get_current_user_id
from controllers.exception_router import (
    general_exception_handler,
    http_exception_handler,
    project_exception_handler,
    request_validation_handler,
)
from exceptions import (
    ProjectException,
    ResourceConflictException,
    ResourceNotFoundException,
)
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException


@pytest.fixture
def api():
    app = FastAPI()
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    service = SimpleNamespace(summarize_finding=AsyncMock())
    app.state.runtime = SimpleNamespace(objective_analysis_service=service)
    app.dependency_overrides[get_current_user_id] = lambda: "owner-1"
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client, service


URL = "/api/v1/collections/col-1/objectives/obj-1/findings/f-1/summary"


def test_summary_returns_versioned_citations_without_publishing(api):
    client, service = api
    service.summarize_finding.return_value = {
        "collection_id": "col-1",
        "objective_id": "obj-1",
        "finding_id": "f-1",
        "analysis_version": 2,
        "language": "zh",
        "text": "Paper A reports a strength change.",
        "citation_ids": ["evidence:ev-a"],
        "references": [
            {
                "id": "evidence:ev-a",
                "kind": "evidence",
                "label": "Table 1",
                "document_id": "paper-a",
                "source_ref": "table-1",
                "page_numbers": [5],
            }
        ],
        "model": "model-1",
        "prompt_version": "finding-evidence-summary.v1",
        "generated_at": "2026-09-09T12:00:00+00:00",
    }
    response = client.post(URL, json={"analysis_version": 2, "language": "zh"})
    assert response.status_code == 200
    assert response.json()["data"]["text"] == "Paper A reports a strength change."
    assert not {"basis", "differences", "limitations", "counts"}.intersection(
        response.json()["data"]
    )
    assert response.json()["data"]["references"][0]["page_numbers"] == [5]
    service.summarize_finding.assert_awaited_once_with(
        "col-1", "obj-1", "f-1", analysis_version=2, language="zh", user_id="owner-1"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"analysis_version": 0},
        {"analysis_version": 1, "language": "xx"},
        {"analysis_version": 1, "evidence": "client facts"},
    ],
)
def test_summary_rejects_unversioned_or_client_supplied_facts(api, payload):
    client, service = api
    assert client.post(URL, json=payload).status_code == 200
    assert client.post(URL, json=payload).json()["code"] == 200100
    service.summarize_finding.assert_not_awaited()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (ResourceNotFoundException("Published Finding not found."), 200201, None),
        (
            ResourceConflictException(
                "The published analysis has changed.",
                data={"code": "summary_stale_analysis"},
            ),
            200204,
            "summary_stale_analysis",
        ),
        (
            FindingSummaryUnavailable("summary_input_too_large"),
            200205,
            "summary_input_too_large",
        ),
    ],
)
def test_optional_summary_errors_are_explicit_and_safe(api, error, status, code):
    client, service = api
    service.summarize_finding.side_effect = error
    response = client.post(URL, json={"analysis_version": 1})
    assert response.status_code == 200
    assert response.json()["code"] == status
    assert "private detail" not in response.text
    if code:
        assert response.json()["data"]["code"] == code


@pytest.mark.parametrize(
    "access,code", [("anonymous", 200301), ("other-owner", 200201)]
)
def test_summary_uses_collection_owner_authorization(access, code, monkeypatch):
    from application.auth import SessionNotFoundError
    from application.core.objectives import analysis_service

    app = FastAPI()
    app.add_exception_handler(ProjectException, project_exception_handler)
    resolve_session = AsyncMock(return_value={"user_id": "other-owner"})
    if access == "anonymous":
        resolve_session.side_effect = SessionNotFoundError()
    monkeypatch.setattr(
        "application.auth.session_service.resolve_session", resolve_session
    )
    authorize = AsyncMock(
        side_effect=ResourceNotFoundException("Collection not found.")
    )
    monkeypatch.setattr(
        analysis_service,
        "collection_service",
        SimpleNamespace(get_collection_for_user=authorize),
    )
    repository = SimpleNamespace(read_objective=AsyncMock())
    monkeypatch.setattr(analysis_service, "ObjectiveRepo", repository)
    generate = AsyncMock()
    monkeypatch.setattr(analysis_service, "summarize_finding_evidence", generate)
    monkeypatch.setattr(
        research_objective_routes, "objective_analysis_service", analysis_service
    )
    runtime = analysis_service.ObjectiveAnalysisService()
    app.state.runtime = SimpleNamespace(objective_analysis_service=runtime)
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        response = client.post(URL, json={"analysis_version": 1})
    assert response.status_code == 200
    assert response.json()["code"] == code
    assert runtime._summary_client is None
    repository.read_objective.assert_not_awaited()
    generate.assert_not_called()
    if access == "anonymous":
        authorize.assert_not_awaited()
    else:
        authorize.assert_awaited_once_with("col-1", "other-owner")
