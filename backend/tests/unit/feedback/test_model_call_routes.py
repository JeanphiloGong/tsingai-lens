import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.mark.parametrize("suffix", ["", "/{call_id}"])
def test_model_call_queries_are_retired(suffix: str) -> None:
    path = "/api/v1/chat-sessions/{session_id}/model-calls" + suffix
    assert path not in app.openapi()["paths"]

    client = TestClient(app)
    response = client.get(path.format(session_id="session-1", call_id="call-1"))
    assert response.json()["code"] == 200201
    assert response.json()["data"] == {}


def test_chat_router_is_not_registered_and_module_routes_are_public() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/chat-sessions" not in paths
    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}/messages" in paths
    assert "/api/v1/conversations/{conversation_id}/tasks/{task_id}/events" in paths
