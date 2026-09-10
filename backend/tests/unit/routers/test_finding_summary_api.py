from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from application.core.objectives.finding_summary import FindingSummaryUnavailable
from controllers.core.research_objectives import router


@pytest.fixture
def api():
    app = FastAPI()
    service = SimpleNamespace(summarize_finding=AsyncMock())
    app.state.objective_analysis_service = service
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
    assert response.json()["text"] == "Paper A reports a strength change."
    assert not {"basis", "differences", "limitations", "counts"}.intersection(
        response.json()
    )
    assert response.json()["references"][0]["page_numbers"] == [5]
    service.summarize_finding.assert_awaited_once_with(
        "col-1", "obj-1", "f-1", analysis_version=2, language="zh"
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
    assert client.post(URL, json=payload).status_code == 422
    service.summarize_finding.assert_not_awaited()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (FileNotFoundError("private detail"), 404, None),
        (ValueError("old version"), 409, "summary_stale_analysis"),
        (
            FindingSummaryUnavailable("summary_input_too_large"),
            503,
            "summary_input_too_large",
        ),
    ],
)
def test_optional_summary_errors_are_explicit_and_safe(api, error, status, code):
    client, service = api
    service.summarize_finding.side_effect = error
    response = client.post(URL, json={"analysis_version": 1})
    assert response.status_code == status
    assert "private detail" not in response.text
    if code:
        assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("access,status", [("anonymous", 401), ("other-owner", 404)])
def test_summary_uses_collection_owner_authorization(access, status):
    from application.auth import SessionNotFoundError
    from main import configure_middleware

    app = FastAPI()
    resolve_session = AsyncMock(return_value={"user_id": "owner-1"})
    if access == "anonymous":
        resolve_session.side_effect = SessionNotFoundError()
    app.state.auth_session_service = SimpleNamespace(resolve_session=resolve_session)
    app.state.collection_service = SimpleNamespace(
        get_collection_for_user=AsyncMock(side_effect=FileNotFoundError())
    )
    summary_service = SimpleNamespace(summarize_finding=AsyncMock())
    app.state.objective_analysis_service = summary_service
    app.include_router(router, prefix="/api/v1")
    configure_middleware(app)
    with TestClient(app) as client:
        response = client.post(URL, json={"analysis_version": 1})
    assert response.status_code == status
    summary_service.summarize_finding.assert_not_awaited()
