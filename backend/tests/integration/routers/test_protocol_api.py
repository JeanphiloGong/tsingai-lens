import pytest

try:
    from fastapi.testclient import TestClient
    from fastapi.middleware.cors import CORSMiddleware

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

if not FASTAPI_AVAILABLE:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from main import PUBLIC_API_PREFIX, PUBLIC_API_V1_PREFIX, app


@pytest.fixture()
def client():
    return TestClient(app)


def test_docs_and_openapi_move_under_api_prefix(client):
    docs_resp = client.get(f"{PUBLIC_API_PREFIX}/docs")
    assert docs_resp.status_code == 200

    redoc_resp = client.get(f"{PUBLIC_API_PREFIX}/redoc")
    assert redoc_resp.status_code == 200

    openapi_resp = client.get(f"{PUBLIC_API_PREFIX}/openapi.json")
    assert openapi_resp.status_code == 200

    openapi_text = openapi_resp.text
    assert (
        f"{PUBLIC_API_V1_PREFIX}/collections/{{collection_id}}/reports/communities"
        in openapi_text
    )
    assert (
        f"{PUBLIC_API_V1_PREFIX}/collections/{{collection_id}}/protocol/steps"
        in openapi_text
    )


def test_static_moves_under_api_prefix(client):
    assert client.get(f"{PUBLIC_API_PREFIX}/static/configs/default.yaml").status_code == 200
    assert client.get("/static/configs/default.yaml").status_code == 404


def test_cors_default_is_not_wildcard_with_credentials():
    cors = next(
        (middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware),
        None,
    )
    assert cors is not None
    options = cors.kwargs
    assert not (
        options.get("allow_origins") == ["*"]
        and options.get("allow_credentials") is True
    )
