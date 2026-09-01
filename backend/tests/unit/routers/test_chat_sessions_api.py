from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

try:
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.chat.session_service import (
    ChatApprovalPendingError,
    ChatSessionNotFoundError,
)
from application.source.task_service import TaskService
from controllers.chat import sessions as sessions_controller
from controllers.schemas.chat.session import (
    ChatSessionCreateRequest,
    ChatToolDecisionRequest,
    ChatTurnRequest,
)
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ToolRisk,
)
from infra.persistence.memory import MemoryObjectiveRepository, MemoryTaskRepository
from main import create_app


class _Service:
    def __init__(self) -> None:
        self.session = ChatSession.create(
            session_id="chat-1",
            user_id="user-1",
            collection_id="col-1",
            created_at="2026-08-19T00:00:00+00:00",
        )
        self.messages = (
            ChatMessage.user(
                message_id="msg-1",
                session_id="chat-1",
                content="你好",
                created_at="2026-08-19T00:00:01+00:00",
            ),
            ChatMessage.assistant(
                message_id="msg-2",
                session_id="chat-1",
                content="你好，我可以帮助分析文献。",
                created_at="2026-08-19T00:00:02+00:00",
            ),
        )
        self.pending = ChatToolCall.requested(
            tool_call_id="call-1",
            session_id="chat-1",
            assistant_message_id="msg-3",
            name="create_objective_candidate",
            arguments={"question": "How does energy input affect ductility?"},
            risk=ToolRisk.WRITE,
        ).require_approval()

    async def create_session(
        self,
        *,
        collection_id: str,
        user_id: str,
    ) -> ChatSession:
        assert collection_id == "col-1"
        assert user_id == "user-1"
        return self.session

    async def get_session_for_user(
        self,
        session_id: str,
        user_id: str,
    ) -> ChatSession:
        if session_id != "chat-1" or user_id != "user-1":
            raise ChatSessionNotFoundError(session_id)
        return self.session

    async def list_messages_for_user(self, session_id: str, user_id: str):
        await self.get_session_for_user(session_id, user_id)
        return self.messages

    async def get_pending_approval_for_user(self, session_id: str, user_id: str):
        await self.get_session_for_user(session_id, user_id)
        return self.pending

    async def post_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
    ) -> dict:
        await self.get_session_for_user(session_id, user_id)
        if message == "blocked":
            raise ChatApprovalPendingError(self.pending.tool_call_id)
        assert message == "你好"
        if source_contexts:
            self.messages = (
                ChatMessage.user(
                    message_id="msg-source",
                    session_id="chat-1",
                    content=message,
                    created_at="2026-08-31T00:00:00+00:00",
                    source_contexts=source_contexts,
                ),
                self.messages[-1],
            )
        return {
            "status": "completed",
            "messages": self.messages,
            "pending_approval": None,
            "error_code": None,
        }

    async def stream_message_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
    ):
        turn = await self.post_message_for_user(
            session_id,
            user_id,
            message=message,
            source_contexts=source_contexts,
        )

        async def events():
            yield {"type": "text_delta", "content": "你好"}
            yield {"type": "turn", "turn": turn}

        return events()

    async def decide_tool_call_for_user(
        self,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        *,
        arguments_digest: str,
        decision: str,
    ) -> dict:
        await self.get_session_for_user(session_id, user_id)
        assert tool_call_id == "call-1"
        if arguments_digest != self.pending.arguments_digest:
            raise ValueError("approval arguments digest does not match stored arguments")
        assert decision == "approved"
        return {
            "status": "completed",
            "messages": (self.messages[-1],),
            "pending_approval": None,
            "error_code": None,
        }


def _request(service: _Service, user_id: str = "user-1") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(chat_session_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
        headers={},
    )


def test_chat_sessions_api_creates_reads_and_posts_ordinary_chat() -> None:
    service = _Service()
    request = _request(service)

    created = asyncio.run(
        sessions_controller.create_chat_session(
            ChatSessionCreateRequest(collection_id="col-1"),
            request,
        )
    )
    read = asyncio.run(sessions_controller.get_chat_session("chat-1", request))
    turn = asyncio.run(
        sessions_controller.post_chat_message(
            "chat-1",
            ChatTurnRequest(message="你好"),
            request,
        )
    )
    messages = asyncio.run(
        sessions_controller.list_chat_messages("chat-1", request)
    )

    assert created.session_id == "chat-1"
    assert read.collection_id == "col-1"
    assert turn.status == "completed"
    assert turn.messages[-1].content.startswith("你好")
    assert [item.role for item in messages.items] == ["user", "assistant"]
    assert messages.pending_approval.tool_call_id == "call-1"


def test_chat_sessions_api_accepts_one_traceable_source_context() -> None:
    service = _Service()
    source_context = {
        "resource_ref": {
            "resource_type": "source",
            "resource_id": "doc-1:results",
            "href": (
                "/collections/col-1/documents/doc-1"
                "?view=parsed-paper&source_ref=results&page=3"
            ),
        },
        "collection_id": "col-1",
        "document_id": "doc-1",
        "document_title": "Paper A",
        "source_kind": "paragraph",
        "source_ref": "results",
        "page": 3,
        "quote": "Conductivity improved to 12 mS/cm under EIS.",
        "heading_path": "Results",
    }

    turn = asyncio.run(
        sessions_controller.post_chat_message(
            "chat-1",
            ChatTurnRequest(message="你好", source_contexts=[source_context]),
            _request(service),
        )
    )

    assert turn.messages[0].source_contexts[0].document_id == "doc-1"
    assert turn.messages[0].source_contexts[0].resource_ref.model_dump() == (
        ChatResourceRef(
            resource_type="source",
            resource_id="doc-1:results",
            href=(
                "/collections/col-1/documents/doc-1"
                "?view=parsed-paper&source_ref=results&page=3"
            ),
        ).to_record()
    )


def test_chat_sessions_api_hides_other_user_and_maps_digest_conflict() -> None:
    service = _Service()
    with pytest.raises(HTTPException) as missing:
        asyncio.run(
            sessions_controller.get_chat_session(
                "chat-1",
                _request(service, "user-2"),
            )
        )
    assert missing.value.status_code == 404
    assert missing.value.detail["code"] == "chat_session_not_found"

    with pytest.raises(HTTPException) as conflict:
        asyncio.run(
            sessions_controller.decide_chat_tool_call(
                "chat-1",
                "call-1",
                ChatToolDecisionRequest(
                    decision="approved",
                    arguments_digest="0" * 64,
                ),
                _request(service),
            )
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail["code"] == "chat_tool_decision_conflict"


def test_chat_sessions_api_rejects_a_new_turn_while_write_approval_is_pending() -> None:
    service = _Service()

    with pytest.raises(HTTPException) as conflict:
        asyncio.run(
            sessions_controller.post_chat_message(
                "chat-1",
                ChatTurnRequest(message="blocked"),
                _request(service),
            )
        )

    assert conflict.value.status_code == 409
    assert conflict.value.detail == {
        "code": "chat_tool_approval_pending",
        "message": "resolve the pending research action before sending another message",
        "tool_call_id": "call-1",
    }


class _AuthService:
    async def ensure_bootstrap_user(self) -> None:
        return None

    async def resolve_session(self, session_id: str | None) -> dict:
        if session_id != "browser-session":
            from application.auth import SessionNotFoundError

            raise SessionNotFoundError("authentication required")
        return {"user_id": "user-1", "email": "researcher@example.com"}


def test_chat_http_routes_require_authentication_and_run_an_ordinary_turn() -> None:
    service = _Service()
    inert_task_service = TaskService(MemoryTaskRepository())
    app = create_app(
        auth_session_service=_AuthService(),
        collection_service=SimpleNamespace(),
        task_service=inert_task_service,
        source_artifact_repository=object(),
        document_profile_repository=object(),
        paper_map_repository=object(),
        objective_repository=MemoryObjectiveRepository(),
        finding_review_repository=object(),
        experiment_plan_repository=object(),
        chat_session_service=service,
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/chat-sessions",
            json={"collection_id": "col-1"},
        ).status_code == 401

        client.cookies.set("lens_session", "browser-session")
        created = client.post(
            "/api/v1/chat-sessions",
            json={"collection_id": "col-1"},
        )
        turn = client.post(
            "/api/v1/chat-sessions/chat-1/messages",
            json={"message": "你好"},
        )

    assert created.status_code == 201
    assert created.json()["session_id"] == "chat-1"
    assert turn.status_code == 200
    assert turn.json()["status"] == "completed"


def test_chat_message_route_streams_text_then_the_persisted_turn() -> None:
    service = _Service()
    app = create_app(
        auth_session_service=_AuthService(),
        collection_service=SimpleNamespace(),
        task_service=TaskService(MemoryTaskRepository()),
        source_artifact_repository=object(),
        document_profile_repository=object(),
        paper_map_repository=object(),
        objective_repository=MemoryObjectiveRepository(),
        finding_review_repository=object(),
        experiment_plan_repository=object(),
        chat_session_service=service,
    )

    with TestClient(app) as client:
        client.cookies.set("lens_session", "browser-session")
        response = client.post(
            "/api/v1/chat-sessions/chat-1/messages",
            headers={"Accept": "text/event-stream"},
            json={"message": "你好"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: text_delta\ndata: {\"content\":\"你好\"}" in response.text
    assert "event: turn\n" in response.text
    assert '"status":"completed"' in response.text
