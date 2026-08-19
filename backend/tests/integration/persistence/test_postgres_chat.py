from __future__ import annotations

import pytest

from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolRisk,
)
from infra.persistence.postgres.chat_repository import PostgresChatRepository


def test_chat_repository_round_trips_trajectory_and_resumable_approval(
    auth_session_service,
    collection_service,
) -> None:
    user = auth_session_service.create_user(
        email="researcher@example.com",
        password="test-password",
    )
    collection = collection_service.create_collection(
        "Agent collection",
        owner_user_id=user["user_id"],
    )
    repository = PostgresChatRepository(
        auth_session_service.repository.session_factory
    )
    chat = ChatSession.create(
        session_id="chat-1",
        user_id=user["user_id"],
        collection_id=collection["collection_id"],
        created_at="2026-08-19T00:00:00+00:00",
    )
    repository.add_session(chat)

    user_message = ChatMessage.user(
        message_id="msg-1",
        session_id=chat.session_id,
        content="读取 collection",
        created_at="2026-08-19T00:00:01+00:00",
    )
    assistant_call = ChatMessage.assistant_tool_call(
        message_id="msg-2",
        session_id=chat.session_id,
        content="",
        tool_call_id="call-read",
        tool_name="get_collection_context",
        tool_arguments={},
        created_at="2026-08-19T00:00:02+00:00",
    )
    read_call = ChatToolCall.requested(
        tool_call_id="call-read",
        session_id=chat.session_id,
        assistant_message_id=assistant_call.message_id,
        name="get_collection_context",
        arguments={},
        risk=ToolRisk.READ,
    ).start("2026-08-19T00:00:03+00:00").succeed(
        "2026-08-19T00:00:04+00:00"
    )
    read_result = ChatToolResult(
        tool_call_id=read_call.tool_call_id,
        status="succeeded",
        data={"document_count": 10},
    )
    tool_message = ChatMessage.from_tool_result(
        message_id="msg-3",
        session_id=chat.session_id,
        result=read_result,
        created_at="2026-08-19T00:00:05+00:00",
    )
    final_message = ChatMessage.assistant(
        message_id="msg-4",
        session_id=chat.session_id,
        content="当前 collection 有 10 篇文献。",
        created_at="2026-08-19T00:00:06+00:00",
    )
    repository.save_trajectory(
        session=chat.update(
            user_id=chat.user_id,
            collection_id=chat.collection_id,
            updated_at="2026-08-19T00:00:06+00:00",
        ),
        messages=(user_message, assistant_call, tool_message, final_message),
        tool_calls=(read_call,),
        tool_results=(read_result,),
    )

    assert repository.read_session(chat.session_id).collection_id == chat.collection_id
    assert repository.read_messages(chat.session_id) == (
        user_message,
        assistant_call,
        tool_message,
        final_message,
    )
    assert repository.read_tool_call(read_call.tool_call_id) == read_call

    write_message = ChatMessage.assistant_tool_call(
        message_id="msg-5",
        session_id=chat.session_id,
        content="我准备保存候选目标。",
        tool_call_id="call-write",
        tool_name="create_objective_candidate",
        tool_arguments={"question": "How does energy input affect ductility?"},
        created_at="2026-08-19T00:01:00+00:00",
    )
    pending = ChatToolCall.requested(
        tool_call_id="call-write",
        session_id=chat.session_id,
        assistant_message_id=write_message.message_id,
        name="create_objective_candidate",
        arguments=write_message.tool_arguments or {},
        risk=ToolRisk.WRITE,
    ).require_approval()
    repository.save_trajectory(
        session=chat.update(
            user_id=chat.user_id,
            collection_id=chat.collection_id,
            updated_at="2026-08-19T00:01:00+00:00",
        ),
        messages=(*repository.read_messages(chat.session_id), write_message),
        tool_calls=(read_call, pending),
        tool_results=(read_result,),
    )

    with pytest.raises(ValueError, match="arguments digest"):
        repository.decide_tool_call(
            session_id=chat.session_id,
            tool_call_id=pending.tool_call_id,
            user_id=user["user_id"],
            arguments_digest="edited-arguments",
            decision="approved",
            decided_at="2026-08-19T00:01:01+00:00",
        )

    approved = repository.decide_tool_call(
        session_id=chat.session_id,
        tool_call_id=pending.tool_call_id,
        user_id=user["user_id"],
        arguments_digest=pending.arguments_digest,
        decision="approved",
        decided_at="2026-08-19T00:01:01+00:00",
    )

    assert approved.status is ToolCallStatus.APPROVED
    assert repository.read_tool_call(pending.tool_call_id) == approved
    assert (
        repository.decide_tool_call(
            session_id=chat.session_id,
            tool_call_id=pending.tool_call_id,
            user_id=user["user_id"],
            arguments_digest=pending.arguments_digest,
            decision="approved",
            decided_at="2026-08-19T00:01:01+00:00",
        )
        == approved
    )
