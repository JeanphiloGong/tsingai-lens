from __future__ import annotations

from types import SimpleNamespace

import pytest

from fastapi import HTTPException

from application.chat.session_service import ChatSessionNotFoundError
from application.repositories.chat_repository import ChatModelCall
from controllers.chat.sessions import get_chat_model_call, list_chat_model_calls


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


CALL = ChatModelCall(
    call_id="model-call-1",
    session_id="session-1",
    trigger_message_id="question-1",
    response_message_id="answer-1",
    purpose="decision",
    model="audit-model",
    request={"model": "audit-model", "messages": [{"role": "user", "content": "Compare A and B."}]},
    request_digest="a" * 64,
    status="provider_succeeded",
    started_at="2026-09-24T00:00:00+00:00",
    finished_at="2026-09-24T00:00:01+00:00",
    provider_confirmed=True,
    prompt_tokens=10,
    completion_tokens=4,
    total_tokens=14,
)


class _Service:
    def __init__(self, *, collection_missing: bool = False) -> None:
        self.collection_missing = collection_missing

    async def _check(self, session_id: str, user_id: str) -> None:
        if self.collection_missing:
            raise FileNotFoundError("collection not found")
        if session_id != "session-1" or user_id != "user-1":
            raise ChatSessionNotFoundError(session_id)

    async def list_model_calls_for_user(
        self, session_id: str, user_id: str, *, limit: int = 50, offset: int = 0
    ):
        await self._check(session_id, user_id)
        return (CALL,)[offset : offset + limit]

    async def get_model_call_for_user(self, session_id: str, call_id: str, user_id: str):
        await self._check(session_id, user_id)
        return CALL if call_id == CALL.call_id else None


def _request(service: _Service, user_id: str = "user-1") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(chat_session_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
        cookies={},
    )


async def test_model_call_list_is_summary_only_and_supports_paging() -> None:
    response = await list_chat_model_calls(
        "session-1", _request(_Service()), limit=1, offset=0
    )

    assert response["limit"] == 1
    assert response["offset"] == 0
    assert response["items"][0]["call_id"] == CALL.call_id
    assert "request" not in response["items"][0]
    assert response["items"][0]["provider_confirmed"] is True


async def test_model_call_detail_returns_the_exact_request() -> None:
    response = await get_chat_model_call(
        "session-1", CALL.call_id, _request(_Service())
    )

    assert response.call_id == CALL.call_id
    assert response.request == CALL.request
    assert response.request_digest == CALL.request_digest


@pytest.mark.parametrize("route", ["list", "detail"])
async def test_model_call_routes_hide_another_user(route: str) -> None:
    with pytest.raises(HTTPException) as error:
        if route == "list":
            await list_chat_model_calls("session-1", _request(_Service(), "user-2"))
        else:
            await get_chat_model_call(
                "session-1", CALL.call_id, _request(_Service(), "user-2")
            )

    assert error.value.status_code == 404


@pytest.mark.parametrize("route", ["list", "detail"])
async def test_model_call_routes_map_deleted_collection_to_not_found(route: str) -> None:
    with pytest.raises(HTTPException) as error:
        if route == "list":
            await list_chat_model_calls(
                "session-1", _request(_Service(collection_missing=True))
            )
        else:
            await get_chat_model_call(
                "session-1",
                CALL.call_id,
                _request(_Service(collection_missing=True)),
            )

    assert error.value.status_code == 404
    assert error.value.detail == "collection not found"


async def test_model_call_detail_does_not_leak_a_call_from_another_session() -> None:
    with pytest.raises(HTTPException) as error:
        await get_chat_model_call("session-1", "missing-call", _request(_Service()))

    assert error.value.status_code == 404
    assert error.value.detail == "chat model call not found"
