from __future__ import annotations

from application.repositories.auth_repository import AuthUserRecord

from domain.chat import ChatToolRequest

import pytest

from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolRisk,
)
from domain.source import Collection
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)


pytestmark = pytest.mark.anyio


async def test_chat_repository_round_trips_trajectory_and_resumable_approval(
    postgres_session_factory,
) -> None:
    user = {
        "user_id": "user-chat",
        "email": "researcher@example.com",
        "display_name": None,
        "password_hash": "synthetic-password-hash",
        "created_at": "2026-08-19T00:00:00+00:00",
    }
    await PostgresAuthRepository(postgres_session_factory).add_user(AuthUserRecord(**user))
    collection = Collection.create(
        collection_id="col-chat",
        owner_user_id=user["user_id"],
        name="Agent collection",
        description=None,
        now_iso="2026-08-19T00:00:00+00:00",
    )
    await PostgresCollectionRepository(postgres_session_factory).add_collection(
        collection
    )
    repository = PostgresChatRepository(postgres_session_factory)
    chat = ChatSession.create(
        session_id="chat-1",
        user_id=user["user_id"],
        collection_id=collection.collection_id,
        created_at="2026-08-19T00:00:00+00:00",
    )
    await repository.add_session(chat)

    user_message = ChatMessage.user(
        message_id="msg-1",
        session_id=chat.session_id,
        content="读取 collection",
        created_at="2026-08-19T00:00:01+00:00",
        source_contexts=(
            ChatSourceContext(
                resource_ref=ChatResourceRef(
                    resource_type="source",
                    resource_id="doc-source:results",
                    href=(
                        "/collections/col-chat/documents/doc-source"
                        "?view=parsed-paper&source_ref=results&page=3"
                    ),
                ),
                collection_id="col-chat",
                document_id="doc-source",
                document_title="Paper A",
                source_kind="text_window",
                source_ref="results",
                page=3,
                quote="Conductivity improved to 12 mS/cm under EIS.",
                heading_path="Results",
                quote_truncated=True,
                source_digest="a" * 64,
            ),
        ),
    )
    assistant_call = ChatMessage.assistant_tool_calls(
        message_id="msg-2",
        session_id=chat.session_id,
        content="",
        tool_calls=(ChatToolRequest(tool_call_id="call-read", name="get_collection_context", arguments={}, position=0),),


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
    await repository.save_trajectory(
        session=chat.update(
            user_id=chat.user_id,
            collection_id=chat.collection_id,
            updated_at="2026-08-19T00:00:06+00:00",
        ),
        messages=(user_message, assistant_call, tool_message, final_message),
        tool_calls=(read_call,),
        tool_results=(read_result,),
    )

    stored_chat = await repository.read_session(chat.session_id)
    assert stored_chat is not None
    assert stored_chat.collection_id == chat.collection_id
    assert await repository.read_messages(chat.session_id) == (
        user_message,
        assistant_call,
        tool_message,
        final_message,
    )
    assert await repository.read_tool_call(read_call.tool_call_id) == read_call

    write_message = ChatMessage.assistant_tool_calls(
        message_id="msg-5",
        session_id=chat.session_id,
        content="我准备保存候选目标。",
        tool_calls=(ChatToolRequest(tool_call_id="call-write", name="create_objective_candidate", arguments={"question": "How does energy input affect ductility?"}, position=0),),


        created_at="2026-08-19T00:01:00+00:00",
    )
    pending = ChatToolCall.requested(
        tool_call_id="call-write",
        session_id=chat.session_id,
        assistant_message_id=write_message.message_id,
        name="create_objective_candidate",
        arguments=write_message.tool_calls[0].arguments,
        risk=ToolRisk.WRITE,
    ).require_approval()
    await repository.save_trajectory(
        session=chat.update(
            user_id=chat.user_id,
            collection_id=chat.collection_id,
            updated_at="2026-08-19T00:01:00+00:00",
        ),
        messages=(*(await repository.read_messages(chat.session_id)), write_message),
        tool_calls=(read_call, pending),
        tool_results=(read_result,),
    )

    with pytest.raises(ValueError, match="arguments digest"):
        await repository.decide_tool_call(
            session_id=chat.session_id,
            tool_call_id=pending.tool_call_id,
            user_id=user["user_id"],
            arguments_digest="edited-arguments",
            decision="approved",
            decided_at="2026-08-19T00:01:01+00:00",
        )

    approved = await repository.decide_tool_call(
        session_id=chat.session_id,
        tool_call_id=pending.tool_call_id,
        user_id=user["user_id"],
        arguments_digest=pending.arguments_digest,
        decision="approved",
        decided_at="2026-08-19T00:01:01+00:00",
    )

    assert approved.status is ToolCallStatus.APPROVED
    assert await repository.read_tool_call(pending.tool_call_id) == approved
    assert (
        await repository.decide_tool_call(
            session_id=chat.session_id,
            tool_call_id=pending.tool_call_id,
            user_id=user["user_id"],
            arguments_digest=pending.arguments_digest,
            decision="approved",
            decided_at="2026-08-19T00:01:01+00:00",
        )
        == approved
    )

    claimed = await repository.claim_approved_tool_call(
        session_id=chat.session_id,
        tool_call_id=pending.tool_call_id,
        user_id=user["user_id"],
        started_at="2026-08-19T00:01:02+00:00",
    )

    assert claimed is not None
    assert claimed.status is ToolCallStatus.RUNNING
    assert (
        await repository.claim_approved_tool_call(
            session_id=chat.session_id,
            tool_call_id=pending.tool_call_id,
            user_id=user["user_id"],
            started_at="2026-08-19T00:01:03+00:00",
        )
        is None
    )

    write_result = ChatToolResult(tool_call_id=claimed.tool_call_id, status="succeeded")
    finished = claimed.succeed("2026-08-19T00:01:04+00:00")
    batch = tuple(ChatToolCall.requested(
        tool_call_id=f"call-batch-{position}", session_id=chat.session_id,
        assistant_message_id="msg-batch", name="read_source", position=position,
        arguments={"document_id": f"paper-{position}"}, risk=ToolRisk.READ,
    ).start("2026-08-19T00:02:00+00:00").succeed("2026-08-19T00:02:01+00:00") for position in range(2))
    observations = tuple(ChatToolResult(tool_call_id=call.tool_call_id, status="succeeded", data={"document_id": call.arguments["document_id"]}) for call in batch)
    trajectory = (
        *(await repository.read_messages(chat.session_id)),
        ChatMessage.from_tool_result(message_id="msg-write-result", session_id=chat.session_id, result=write_result, created_at="2026-08-19T00:01:04+00:00"),
        ChatMessage.assistant_tool_calls(message_id="msg-batch", session_id=chat.session_id, content="", created_at="2026-08-19T00:02:00+00:00", tool_calls=tuple(call.to_request() for call in batch)),
        *(ChatMessage.from_tool_result(message_id=f"msg-result-{index}", session_id=chat.session_id, result=result, created_at="2026-08-19T00:02:01+00:00") for index, result in enumerate(observations)),
    )
    await repository.save_trajectory(session=chat, messages=trajectory, tool_calls=(finished, *batch), tool_results=(write_result, *observations))
    reloaded = await PostgresChatRepository(postgres_session_factory).read_messages(chat.session_id)
    assert reloaded == trajectory
    assert [request.position for request in reloaded[-3].tool_calls] == [0, 1]
