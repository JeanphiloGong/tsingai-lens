from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.chat.model_calls import ModelCallOutcome
from application.chat.session_service import ChatSessionService
from application.repositories.chat_repository import ChatModelCall
from domain.chat import ChatMessage, ChatSession, ChatToolRequest
from tests.support.chat_repository import MemoryChatRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _CollectionService:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        return {"collection_id": collection_id}


def _service(repo: MemoryChatRepository) -> ChatSessionService:
    return ChatSessionService(
        collection_service=_CollectionService(),
        source_artifact_repository=SimpleNamespace(),
        repository=repo,
        runner=SimpleNamespace(),
    )


async def _setup(linked: bool = True) -> tuple[MemoryChatRepository, ChatSessionService, tuple[ChatMessage, ...]]:
    repo = MemoryChatRepository()
    session = ChatSession.create(
        session_id="chat-correction",
        user_id="researcher",
        collection_id="collection",
        created_at="2026-09-23T00:00:00+00:00",
    )
    await repo.add_session(session)
    messages = (
        ChatMessage.user(
            message_id="msg-question",
            session_id=session.session_id,
            content="Compare the material conditions.",
            created_at="2026-09-23T00:00:01+00:00",
        ),
        ChatMessage.assistant(
            message_id="msg-original",
            session_id=session.session_id,
            content="The papers use different material grades.",
            created_at="2026-09-23T00:00:02+00:00",
        ),
        ChatMessage.user(
            message_id="msg-feedback",
            session_id=session.session_id,
            content="An omitted ELI label does not prove a different grade.",
            created_at="2026-09-23T00:00:03+00:00",
        ),
        *(() if not linked else (
            ChatMessage.assistant(
                message_id="msg-corrected",
                session_id=session.session_id,
                content="The evidence is insufficient to claim different grades.",
                created_at="2026-09-23T00:00:04+00:00",
            ),
        )),
    )
    repo.messages[session.session_id] = messages
    call_specs = [("call-original", "msg-original", "2026-09-23T00:00:02+00:00")]
    if linked:
        call_specs.append(("call-corrected", "msg-corrected", "2026-09-23T00:00:04+00:00"))
    for call_id, response_id, started_at in call_specs:
        await repo.start_model_call(
            ChatModelCall(
                call_id=call_id,
                session_id=session.session_id,
                trigger_message_id="msg-question" if call_id == "call-original" else "msg-feedback",
                response_message_id=response_id,
                purpose="decision",
                model="test-model",
                request={"messages": [{"role": "user", "content": response_id}]},
                request_digest=(call_id.replace("call-", "") * 64)[:64],
                started_at=started_at,
            )
        )
        await repo.finish_model_call(
            session_id=session.session_id,
            call_id=call_id,
            outcome=ModelCallOutcome(
                status="provider_succeeded",
                finished_at=started_at,
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
    return repo, _service(repo), messages


async def test_links_explicit_sequence_without_mutating_trajectory() -> None:
    repo, service, before = await _setup()

    case = await service.link_correction_case_for_user(
        "chat-correction",
        "researcher",
        original_message_id="msg-original",
        feedback_message_id="msg-feedback",
        corrected_message_id="msg-corrected",
    )

    assert case.status == "linked"
    assert case.original_model_call_id == "call-original"
    assert case.corrected_model_call_id == "call-corrected"
    assert await repo.read_messages("chat-correction") == before
    assert await service.get_correction_case_for_user("chat-correction", case.case_id, "researcher") == case


async def test_unresolved_case_requires_only_the_original_answer() -> None:
    repo, service, _ = await _setup(linked=False)

    case = await service.link_correction_case_for_user(
        "chat-correction",
        "researcher",
        original_message_id="msg-original",
        feedback_message_id="msg-feedback",
    )

    assert case.status == "unresolved"
    assert case.corrected_message_id is None
    assert case.corrected_model_call_id is None


async def test_tool_request_cannot_be_selected_as_a_final_answer() -> None:
    repo, service, messages = await _setup(linked=False)
    repo.messages["chat-correction"] = (
        messages[0],
        ChatMessage.assistant_tool_calls(
            message_id="msg-tool",
            session_id="chat-correction",
            content="",
            tool_calls=(ChatToolRequest("call-tool", "read_source", {}, 0),),
            created_at="2026-09-23T00:00:02+00:00",
        ),
        messages[2],
    )
    with pytest.raises(ValueError, match="final assistant answer"):
        await service.link_correction_case_for_user(
            "chat-correction",
            "researcher",
            original_message_id="msg-tool",
            feedback_message_id="msg-feedback",
        )


async def test_cross_session_message_is_rejected() -> None:
    _, service, _ = await _setup()
    with pytest.raises(ValueError, match="belong to this session"):
        await service.link_correction_case_for_user(
            "chat-correction",
            "researcher",
            original_message_id="msg-other-session",
            feedback_message_id="msg-feedback",
        )
