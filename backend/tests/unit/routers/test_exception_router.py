import pytest
from controllers.exception_router import (
    general_exception_handler,
    http_exception_handler,
    project_exception_handler,
    request_validation_handler,
)
from exceptions import ProjectException, ResourceConflictException
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException


@pytest.fixture
def api():
    app = FastAPI()
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    saved = []

    @app.post("/confirm")
    async def confirm(revision: int = Query(ge=1)):
        if revision != 2:
            raise ResourceConflictException(
                "The sample changed; review the current revision.",
                data={"code": "sample_revision_conflict", "current_revision": 2},
            )
        saved.append(revision)
        return {"confirmed_revision": revision}

    @app.get("/fault/{kind}")
    async def fault(kind: str):
        raise {
            "value": ValueError,
            "file": FileNotFoundError,
            "runtime": RuntimeError,
        }[kind]("private diagnostic that must stay in server logs")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, saved


def test_conflict_keeps_business_reason_and_stops_before_writing(api):
    client, saved = api
    response = client.post("/confirm?revision=1")

    assert response.status_code == 200
    assert response.json() == {
        "code": 200204,
        "message": "The sample changed; review the current revision.",
        "data": {"code": "sample_revision_conflict", "current_revision": 2},
        "meta": None,
    }
    assert saved == []


def test_request_validation_stops_before_the_operation(api):
    client, saved = api
    response = client.post("/confirm?revision=0")

    assert response.status_code == 200
    assert response.json()["code"] == 200100
    assert response.json()["data"]["errors"][0]["loc"] == ["query", "revision"]
    assert saved == []


@pytest.mark.parametrize("kind", ["value", "file", "runtime"])
def test_unclassified_failures_are_safe_server_errors(api, kind):
    client, _saved = api
    response = client.get(f"/fault/{kind}")

    assert response.status_code == 200
    assert response.json()["code"] == 200000
    assert "private diagnostic" not in response.text


@pytest.mark.parametrize(
    "method,path,code",
    [
        ("get", "/missing", 200201),
        ("get", "/confirm", 200202),
    ],
)
def test_framework_errors_use_the_same_response_contract(api, method, path, code):
    client, _saved = api
    response = getattr(client, method)(path)

    assert response.status_code == 200
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "data", "meta"}
