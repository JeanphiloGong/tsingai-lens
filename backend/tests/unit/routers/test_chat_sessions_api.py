from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from exceptions import ProjectException, ResourceConflictException

try:
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.chat.session_service import (
    ChatApprovalPendingError,
    ChatSessionNotFoundError,
    ChatSourceContextError,
)
from application.pipeline import pipeline_run_service
from controllers.chat import chat_session_routes as sessions_controller
from controllers.chat.schemas import (
    ChatSessionCreateRequest,
    ChatSessionListResponse,
    ChatToolDecisionRequest,
    SendChatMessageRequest,
)
from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ToolPermissionMode,
    ToolRisk,
)
from main import create_app
from repositories.chat_repository import ChatRepository, ChatSessionSummary
from repositories.objective_repository import ObjectiveRepository
from repositories.pipeline_run_repository import PipelineRunRepository


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

    async def list_sessions_for_user(
        self,
        *,
        collection_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ):
        assert collection_id == "col-1"
        assert user_id == "user-1"
        return (
            ChatSessionSummary(
                session=self.session,
                title=(
                    self.messages[0].content.strip().split("\n", 1)[0].strip()[:160]
                    or None
                    if self.messages
                    else None
                ),
            ),
        )

    async def list_messages_for_user(self, session_id: str, user_id: str):
        await self.get_session_for_user(session_id, user_id)
        return self.messages

    async def get_trajectory_for_user(self, session_id: str, user_id: str):
        await self.get_session_for_user(session_id, user_id)
        return {
            "branches": [],
            "branch_draft": None,
            "running": False,
            "messages": self.messages,
            "pending_approval": self.pending,
            "feedback": (),
        }

    async def get_pending_approval_for_user(self, session_id: str, user_id: str):
        await self.get_session_for_user(session_id, user_id)
        return self.pending

    async def send_message(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
        permission_mode: ToolPermissionMode = ToolPermissionMode.CONFIRM,
        branch_revision: int | None = None,
    ) -> dict:
        await self.get_session_for_user(session_id, user_id)
        self.permission_mode = permission_mode
        if message == "blocked":
            raise ChatApprovalPendingError(self.pending.tool_call_id)
        if message == "forged source":
            raise ChatSourceContextError(
                "selected Source quote is not contained in the canonical Source"
            )
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
            "completion_reason": "model_answer",
            "warnings": [],
            "messages": self.messages,
            "pending_approval": None,
            "error_code": None,
        }

    async def send_message_stream(
        self,
        session_id: str,
        user_id: str,
        *,
        message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
        permission_mode: ToolPermissionMode = ToolPermissionMode.CONFIRM,
        branch_revision: int | None = None,
    ):
        turn = await self.send_message(
            session_id,
            user_id,
            message=message,
            source_contexts=source_contexts,
            permission_mode=permission_mode,
            branch_revision=branch_revision,
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
            raise ResourceConflictException(
                "approval arguments digest does not match stored arguments",
                data={"code": "chat_tool_decision_conflict"},
            )
        assert decision == "approved"
        return {
            "status": "completed",
            "messages": (self.messages[-1],),
            "pending_approval": None,
            "error_code": None,
        }


def _request(service: _Service, user_id: str = "user-1") -> SimpleNamespace:
    sessions_controller.chat_session_service = service
    return SimpleNamespace(
        state=SimpleNamespace(current_user={"user_id": user_id}), headers={}
    )


def test_chat_sessions_api_creates_reads_and_posts_ordinary_chat() -> None:
    service = _Service()
    request = _request(service)

    created = sessions_controller.ChatSessionResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.create_chat_session(
                        payload=ChatSessionCreateRequest(collection_id="col-1"),
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    read = sessions_controller.ChatSessionResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.get_chat_session(
                        session_id="chat-1",
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    turn = sessions_controller.ChatTurnResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.send_chat_message(
                        session_id="chat-1",
                        payload=SendChatMessageRequest(message="你好"),
                        request=request,
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    messages = sessions_controller.ChatMessageListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.list_chat_messages(
                        session_id="chat-1",
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )

    assert created.session_id == "chat-1"
    assert read.collection_id == "col-1"
    assert turn.status == "completed"
    assert turn.messages[-1].content.startswith("你好")
    assert [item.role for item in messages.items] == ["user", "assistant"]
    assert messages.pending_approval.tool_call_id == "call-1"


def test_chat_sessions_api_lists_owned_collection_sessions() -> None:
    response = sessions_controller.ChatSessionListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.list_chat_sessions(
                        user_id=_request(_Service()).state.current_user["user_id"],
                        collection_id="col-1",
                        limit=12,
                        offset=0,
                    )
                )
            ).body
        )["data"]
    )

    assert isinstance(response, ChatSessionListResponse)
    assert response.limit == 12
    assert [item.session_id for item in response.items] == ["chat-1"]
    assert response.items[0].title == "你好"


@pytest.mark.parametrize(
    ("question", "title"),
    [
        (
            "  Compare matched LPBF tensile conditions\nKeep heat treatments separate.",
            "Compare matched LPBF tensile conditions",
        ),
        ("x" * 200, "x" * 160),
        (None, None),
    ],
)
def test_chat_history_title_is_a_bounded_first_question(
    question: str | None,
    title: str | None,
) -> None:
    service = _Service()
    service.messages = (
        ()
        if question is None
        else (
            ChatMessage.user(
                message_id="question",
                session_id=service.session.session_id,
                content=question,
                created_at="2026-08-19T00:00:01+00:00",
            ),
        )
    )
    response = sessions_controller.ChatSessionListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.list_chat_sessions(
                        user_id=_request(service).state.current_user["user_id"],
                        collection_id="col-1",
                        limit=12,
                        offset=0,
                    )
                )
            ).body
        )["data"]
    )
    assert response.items[0].title == title


def test_chat_sessions_api_forwards_explicit_permission_mode() -> None:
    service = _Service()

    sessions_controller.ChatTurnResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.send_chat_message(
                        session_id="chat-1",
                        payload=SendChatMessageRequest(
                            message="你好", permission_mode="none"
                        ),
                        request=_request(service),
                        user_id=_request(service).state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )

    assert service.permission_mode is ToolPermissionMode.NONE


@pytest.mark.parametrize("count", [1, 3, 12])
def test_chat_sessions_api_accepts_traceable_source_contexts(count: int) -> None:
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
        "source_kind": "text_window",
        "source_ref": "results",
        "page": 3,
        "quote": "Conductivity improved to 12 mS/cm under EIS.",
        "heading_path": "Results",
    }

    turn = sessions_controller.ChatTurnResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    sessions_controller.send_chat_message(
                        session_id="chat-1",
                        payload=SendChatMessageRequest(
                            message="你好",
                            source_contexts=[source_context]
                            + [
                                {
                                    **source_context,
                                    "source_ref": f"methods-{index}",
                                    "resource_ref": {
                                        **source_context["resource_ref"],
                                        "resource_id": f"doc-1:methods-{index}",
                                    },
                                }
                                for index in range(1, count)
                            ],
                        ),
                        request=_request(service),
                        user_id=_request(service).state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )

    assert len(turn.messages[0].source_contexts) == count
    if count == 12:
        with pytest.raises(ValueError):
            SendChatMessageRequest(
                message="Explain these blocks", source_contexts=[source_context] * 13
            )
    assert turn.messages[0].source_contexts[0].document_id == "doc-1"
    assert turn.messages[0].source_contexts[0].resource_ref.model_dump() == (
        {
            "resource_type": "source",
            "resource_id": "doc-1:results",
            "href": (
                "/collections/col-1/documents/doc-1"
                "?view=parsed-paper&source_ref=results&page=3"
            ),
        }
    )


def test_chat_sessions_api_maps_a_forged_source_context_to_422() -> None:
    with pytest.raises(ProjectException) as invalid:
        sessions_controller.ChatTurnResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        sessions_controller.send_chat_message(
                            session_id="chat-1",
                            payload=SendChatMessageRequest(message="forged source"),
                            request=_request(_Service()),
                            user_id=_request(_Service()).state.current_user["user_id"],
                        )
                    )
                ).body
            )["data"]
        )

    assert invalid.value.code == 200100
    assert (
        invalid.value.message
        == "selected Source quote is not contained in the canonical Source"
    )
    assert invalid.value.data == {
        "code": "chat_source_context_invalid",
    }


def test_chat_sessions_api_hides_other_user_and_maps_digest_conflict() -> None:
    service = _Service()
    with pytest.raises(ProjectException) as missing:
        sessions_controller.ChatSessionResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        sessions_controller.get_chat_session(
                            session_id="chat-1",
                            user_id=_request(service, "user-2").state.current_user[
                                "user_id"
                            ],
                        )
                    )
                ).body
            )["data"]
        )
    assert missing.value.code == 200201
    assert missing.value.data["code"] == "chat_session_not_found"

    with pytest.raises(ProjectException) as conflict:
        sessions_controller.ChatTurnResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        sessions_controller.decide_chat_tool_call(
                            session_id="chat-1",
                            tool_call_id="call-1",
                            payload=ChatToolDecisionRequest(
                                decision="approved", arguments_digest="0" * 64
                            ),
                            user_id=_request(service).state.current_user["user_id"],
                        )
                    )
                ).body
            )["data"]
        )
    assert conflict.value.code == 200204
    assert conflict.value.data["code"] == "chat_tool_decision_conflict"


def test_chat_sessions_api_rejects_a_new_turn_while_write_approval_is_pending() -> None:
    service = _Service()

    with pytest.raises(ProjectException) as conflict:
        sessions_controller.ChatTurnResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        sessions_controller.send_chat_message(
                            session_id="chat-1",
                            payload=SendChatMessageRequest(message="blocked"),
                            request=_request(service),
                            user_id=_request(service).state.current_user["user_id"],
                        )
                    )
                ).body
            )["data"]
        )

    assert conflict.value.code == 200204
    assert conflict.value.data == {
        "code": "chat_tool_approval_pending",
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


def test_chat_http_routes_require_authentication_and_run_an_ordinary_turn(
    monkeypatch, collection_service, *, postgres_session_factory
) -> None:
    service = _Service()
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    monkeypatch.setattr(sessions_controller, "chat_session_service", service)
    monkeypatch.setattr(
        "application.auth.session_service.resolve_session",
        _AuthService().resolve_session,
    )
    monkeypatch.setattr("main.AsyncSessionLocal", postgres_session_factory)
    monkeypatch.setattr(
        "main.build_database_engine",
        lambda _settings: postgres_session_factory.kw["bind"],
    )
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/v1/chat-sessions", json={"collection_id": "col-1"})
        assert response.status_code == 200
        assert response.json()["code"] == 200301

        client.cookies.set("lens_session", "browser-session")
        created = client.post(
            "/api/v1/chat-sessions",
            json={"collection_id": "col-1"},
        )
        turn = client.post(
            "/api/v1/chat-sessions/chat-1/messages",
            json={"message": "你好"},
        )

    assert created.status_code == 200
    assert created.json()["data"]["session_id"] == "chat-1"
    assert turn.status_code == 200
    assert turn.json()["data"]["status"] == "completed"


def test_chat_message_route_streams_text_then_the_persisted_turn(
    monkeypatch, collection_service, *, postgres_session_factory
) -> None:
    service = _Service()
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    monkeypatch.setattr(sessions_controller, "chat_session_service", service)
    monkeypatch.setattr(
        "application.auth.session_service.resolve_session",
        _AuthService().resolve_session,
    )
    monkeypatch.setattr("main.AsyncSessionLocal", postgres_session_factory)
    monkeypatch.setattr(
        "main.build_database_engine",
        lambda _settings: postgres_session_factory.kw["bind"],
    )
    app = create_app()

    with TestClient(app) as client:
        client.cookies.set("lens_session", "browser-session")
        response = client.post(
            "/api/v1/chat-sessions/chat-1/messages",
            headers={"Accept": "text/event-stream"},
            json={"message": "你好"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: text_delta\ndata: {"content":"你好"}' in response.text
    assert "event: turn\n" in response.text
    assert '"status":"completed"' in response.text


def test_title_route_validates_input_and_hides_unowned_sessions(
    monkeypatch, collection_service, *, postgres_session_factory
) -> None:
    import asyncio

    from application.chat import ModelTurn
    from tests.support.postgres import seed_collection
    from tests.unit.application.test_chat_session_service import (
        _Model,
        _service,
    )

    asyncio.run(
        seed_collection(postgres_session_factory, "col-1", document_ids=("doc-1",))
    )
    repository = ChatRepository()
    service = _service(_Model(ModelTurn(content="Answer")), repository)
    session = asyncio.run(
        service.create_session(collection_id="col-1", user_id="user-1")
    )
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    monkeypatch.setattr(sessions_controller, "chat_session_service", service)
    monkeypatch.setattr(
        "application.auth.session_service.resolve_session",
        _AuthService().resolve_session,
    )
    monkeypatch.setattr("main.AsyncSessionLocal", postgres_session_factory)
    monkeypatch.setattr(
        "main.build_database_engine",
        lambda _settings: postgres_session_factory.kw["bind"],
    )
    app = create_app()
    path = f"/api/v1/chat-sessions/{session.session_id}/title"
    with TestClient(app) as client:
        response = client.put(path, json={"title": "New title"})
        assert response.status_code == 200
        assert response.json()["code"] == 200301
        client.cookies.set("lens_session", "browser-session")
        for title in (
            "",
            "   ",
            "x" * 161,
            "line\nbreak",
            "\nTitle",
            "Title\r",
            "nul\x00title",
        ):
            response = client.put(path, json={"title": title})
            assert response.status_code == 200
            assert response.json()["code"] == 200100
        bounded = client.put(path, json={"title": " " + "x" * 160 + " "})
        assert bounded.status_code == 200
        assert bounded.json()["data"]["title"] == "x" * 160
        renamed = client.put(path, json={"title": "  IN718 comparison  "})
        assert renamed.status_code == 200
        assert renamed.json()["data"]["title"] == "IN718 comparison"
        assert (
            client.get(path.removesuffix("/title")).json()["data"]["title"]
            == "IN718 comparison"
        )
        response = client.put(
            "/api/v1/chat-sessions/missing/title", json={"title": "Other"}
        )
        assert response.status_code == 200
        assert response.json()["code"] == 200201


@pytest.mark.parametrize("known", [True, False])
def test_started_chat_stream_reports_safe_error_events(known):
    async def events():
        yield {"type": "text_delta", "content": "Evidence already read."}
        if known:
            raise ResourceConflictException("The response changed.", data={"code": "chat_response_changed"})
        raise RuntimeError("private provider diagnostic")

    async def collect():
        return [item async for item in sessions_controller._chat_event_stream(events())]

    output = asyncio.run(collect())
    assert '"content":"Evidence already read."' in output[0]
    assert output[1].startswith("event: error\n")
    assert ("chat_response_changed" if known else "chat_stream_failed") in output[1]
    assert "private provider diagnostic" not in output[1]


def test_started_chat_stream_preserves_cancellation():
    async def events():
        yield {"type": "text_delta", "content": "Evidence already read."}
        raise asyncio.CancelledError()

    async def collect():
        return [item async for item in sessions_controller._chat_event_stream(events())]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect())
