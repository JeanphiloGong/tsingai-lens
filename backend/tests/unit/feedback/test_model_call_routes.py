from __future__ import annotations

import json
from types import SimpleNamespace

import controllers.chat.chat_session_routes as routes
import pytest
from application.chat.session_service import ChatSessionNotFoundError
from controllers.chat.chat_session_routes import (
    get_chat_model_call,
    list_chat_model_calls,
)
from exceptions import ProjectException, ResourceNotFoundException
from fastapi import HTTPException
from repositories.chat_repository import ChatModelCall

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
    request={
        "model": "audit-model",
        "messages": [{"role": "user", "content": "Compare A and B."}],
    },
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
            raise ResourceNotFoundException("collection not found")
        if session_id != "session-1" or user_id != "user-1":
            raise ChatSessionNotFoundError(session_id)

    async def list_model_calls_for_user(
        self, session_id: str, user_id: str, *, limit: int = 50, offset: int = 0
    ):
        await self._check(session_id, user_id)
        return (CALL,)[offset : offset + limit]

    async def get_model_call_for_user(
        self, session_id: str, call_id: str, user_id: str
    ):
        await self._check(session_id, user_id)
        if call_id != CALL.call_id:
            raise ResourceNotFoundException("chat model call not found")
        return CALL


def _request(service: _Service, user_id: str = "user-1") -> SimpleNamespace:
    routes.chat_session_service = service
    return SimpleNamespace(
        state=SimpleNamespace(current_user={"user_id": user_id}), cookies={}
    )


async def test_model_call_list_is_summary_only_and_supports_paging() -> None:
    response = await list_chat_model_calls(
        session_id="session-1",
        user_id=_request(_Service()).state.current_user["user_id"],
        limit=1,
        offset=0,
    )

    response = json.loads(response.body)["data"]
    assert response["limit"] == 1
    assert response["offset"] == 0
    assert response["items"][0]["call_id"] == CALL.call_id
    assert "request" not in response["items"][0]
    assert response["items"][0]["provider_confirmed"] is True


async def test_model_call_detail_returns_the_exact_request() -> None:
    response = await get_chat_model_call(
        session_id="session-1",
        call_id=CALL.call_id,
        user_id=_request(_Service()).state.current_user["user_id"],
    )

    response = routes.ChatModelCallResponse.model_validate(
        json.loads(response.body)["data"]
    )
    assert response.call_id == CALL.call_id
    assert response.request == CALL.request
    assert response.request_digest == CALL.request_digest


@pytest.mark.parametrize("route", ["list", "detail"])
async def test_model_call_routes_hide_another_user(route: str) -> None:
    with pytest.raises(ProjectException) as error:
        if route == "list":
            await list_chat_model_calls(
                session_id="session-1",
                user_id=_request(_Service(), "user-2").state.current_user["user_id"],
            )
        else:
            await get_chat_model_call(
                session_id="session-1",
                call_id=CALL.call_id,
                user_id=_request(_Service(), "user-2").state.current_user["user_id"],
            )

    assert error.value.code == 200201


@pytest.mark.parametrize("route", ["list", "detail"])
async def test_model_call_routes_map_deleted_collection_to_not_found(
    route: str,
) -> None:
    with pytest.raises(ProjectException) as error:
        if route == "list":
            await list_chat_model_calls(
                session_id="session-1",
                user_id=_request(_Service(collection_missing=True)).state.current_user[
                    "user_id"
                ],
            )
        else:
            await get_chat_model_call(
                session_id="session-1",
                call_id=CALL.call_id,
                user_id=_request(_Service(collection_missing=True)).state.current_user[
                    "user_id"
                ],
            )

    assert error.value.code == 200201
    assert error.value.message == "collection not found"


async def test_model_call_detail_does_not_leak_a_call_from_another_session() -> None:
    with pytest.raises(ProjectException) as error:
        await get_chat_model_call(
            session_id="session-1",
            call_id="missing-call",
            user_id=_request(_Service()).state.current_user["user_id"],
        )

    assert error.value.code == 200201
    assert error.value.message == "chat model call not found"
