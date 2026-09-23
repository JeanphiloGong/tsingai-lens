from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.chat.model_calls import ModelCallOutcome
from application.chat.session_service import ChatSessionService
from application.evaluation.chat_correction_review_service import (
    ChatCorrectionReviewService,
    ChatCorrectionReviewStaleError,
)
from application.repositories.chat_repository import ChatModelCall
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolResult,
)
from tests.support.chat_correction_review import MemoryChatCorrectionReviewRepository
from tests.support.chat_repository import MemoryChatRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _CollectionService:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        return {"collection_id": collection_id}


def _source() -> ChatSourceContext:
    return ChatSourceContext(
        resource_ref=ChatResourceRef("source", "doc-1:page-2", "/collections/collection/documents/doc-1"),
        collection_id="collection",
        document_id="doc-1",
        document_title="Alloy study",
        source_kind="page",
        source_ref="page-2",
        page=2,
        quote="The measured density was 99.1%.",
        source_digest="a" * 64,
    )


async def _setup():
    chat = MemoryChatRepository()
    session = ChatSession.create(
        session_id="chat-review",
        user_id="researcher",
        collection_id="collection",
        created_at="2026-09-23T00:00:00+00:00",
    )
    await chat.add_session(session)
    messages = (
        ChatMessage.user(
            message_id="msg-question",
            session_id=session.session_id,
            content="Compare the measured density.",
            created_at="2026-09-23T00:00:01+00:00",
        ),
        ChatMessage.assistant(
            message_id="msg-original",
            session_id=session.session_id,
            content="The density is not reported.",
            created_at="2026-09-23T00:00:02+00:00",
        ),
        ChatMessage(
            message_id="msg-feedback",
            session_id=session.session_id,
            role="user",
            content="The table on page 2 reports a value.",
            created_at="2026-09-23T00:00:03+00:00",
            source_contexts=(_source(),),
        ),
        ChatMessage.from_tool_result(
            message_id="msg-tool-result",
            session_id=session.session_id,
            result=ChatToolResult(
                tool_call_id="tool-1",
                status="succeeded",
                data={"page": 2, "density": "99.1%"},
                resource_refs=(ChatResourceRef("source", "doc-1:page-2"),),
            ),
            created_at="2026-09-23T00:00:04+00:00",
        ),
        ChatMessage(
            message_id="msg-corrected",
            session_id=session.session_id,
            role="assistant",
            content="The measured density is 99.1% on page 2.",
            created_at="2026-09-23T00:00:05+00:00",
        ),
    )
    chat.messages[session.session_id] = messages
    await chat.start_model_call(
        ChatModelCall(
            call_id="call-original",
            session_id=session.session_id,
            trigger_message_id="msg-question",
            response_message_id="msg-original",
            purpose="decision",
            model="test-model",
            request={"model": "test-model", "messages": [{"role": "user", "content": "old"}]},
            request_digest="1" * 64,
            started_at="2026-09-23T00:00:02+00:00",
        )
    )
    await chat.start_model_call(
        ChatModelCall(
            call_id="call-corrected",
            session_id=session.session_id,
            trigger_message_id="msg-feedback",
            response_message_id="msg-corrected",
            purpose="decision",
            model="test-model",
            request={
                "model": "test-model",
                "messages": [
                    {"role": "user", "content": "The table on page 2 reports a value."},
                    {"role": "tool", "content": "99.1%"},
                ],
                "tools": [{"type": "function", "function": {"name": "read_source"}}],
            },
            request_digest="2" * 64,
            started_at="2026-09-23T00:00:05+00:00",
        )
    )
    for call_id in ("call-original", "call-corrected"):
        await chat.finish_model_call(
            session_id=session.session_id,
            call_id=call_id,
            outcome=ModelCallOutcome(
                status="provider_succeeded",
                finished_at="2026-09-23T00:00:06+00:00",
            ),
        )
    case_service = ChatSessionService(
        collection_service=_CollectionService(),
        source_artifact_repository=SimpleNamespace(),
        repository=chat,
        runner=SimpleNamespace(),
    )
    case = await case_service.link_correction_case_for_user(
        session.session_id,
        "researcher",
        original_message_id="msg-original",
        feedback_message_id="msg-feedback",
        corrected_message_id="msg-corrected",
    )
    reviews = MemoryChatCorrectionReviewRepository()
    service = ChatCorrectionReviewService(chat_session_service=case_service, repository=reviews)
    return chat, case_service, service, reviews, case


async def test_sample_freezes_exact_input_observations_and_source_refs() -> None:
    _, _, service, _, case = await _setup()

    sample = await service.create_sample_for_user("chat-review", case.case_id, "researcher")

    assert sample.input["tools"]
    assert any(item["kind"] == "tool_observation" for item in sample.observations)
    assert sample.source_refs[0]["kind"] == "message_source"
    assert sample.validate_digest()


async def test_accept_requires_support_and_withdraw_is_terminal() -> None:
    _, _, service, _, case = await _setup()
    sample = await service.create_sample_for_user("chat-review", case.case_id, "researcher")

    with pytest.raises(ValueError, match="supporting Chat"):
        await service.review_sample_for_user(
            "chat-review", sample.sample_id, "researcher", decision="accept"
        )
    accepted = await service.review_sample_for_user(
        "chat-review",
        sample.sample_id,
        "researcher",
        decision="accept",
        support_message_ids=("msg-tool-result", "msg-corrected"),
    )
    assert accepted.seq == 1
    withdrawn = await service.review_sample_for_user(
        "chat-review",
        sample.sample_id,
        "researcher",
        decision="withdraw",
        reason="The source was superseded.",
    )
    assert withdrawn.seq == 2
    with pytest.raises(ValueError, match="withdrawn"):
        await service.review_sample_for_user(
            "chat-review",
            sample.sample_id,
            "researcher",
            decision="accept",
            support_message_ids=("msg-corrected",),
        )
    assert (await service.status_for_user("chat-review", sample.sample_id, "researcher"))["state"] == "withdraw"


async def test_changed_target_makes_previous_sample_stale() -> None:
    chat, _, service, _, case = await _setup()
    sample = await service.create_sample_for_user("chat-review", case.case_id, "researcher")
    changed = replace(chat.messages["chat-review"][-1], content="A different target")
    chat.messages["chat-review"] = (*chat.messages["chat-review"][:-1], changed)

    with pytest.raises(ChatCorrectionReviewStaleError, match="changed"):
        await service.review_sample_for_user(
            "chat-review",
            sample.sample_id,
            "researcher",
            decision="accept",
            support_message_ids=("msg-corrected",),
        )
    assert (await service.status_for_user("chat-review", sample.sample_id, "researcher"))["state"] == "stale"


async def test_sample_is_owner_scoped() -> None:
    _, _, service, _, case = await _setup()
    sample = await service.create_sample_for_user("chat-review", case.case_id, "researcher")

    with pytest.raises(FileNotFoundError):
        await service.get_sample_for_user("chat-review", sample.sample_id, "other-user")
