import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolRequest,
    ToolRisk,
)
from domain.source import Collection
from repositories.auth_repository import AuthRepository, AuthUserRecord
from repositories.chat_repository import ChatRepository, ChatWriteConflict
from repositories.collection_repository import (
    CollectionRepository,
    StoredCollection,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def permission_case(postgres_session_factory):
    now = datetime.now(timezone.utc).isoformat()
    await AuthRepository().add_user(
        AuthUserRecord(
            user_id="u",
            email="permission@example.com",
            display_name=None,
            password_hash="test-only",
            created_at=now,
        )
    )
    await CollectionRepository().add_collection(
        StoredCollection(
            collection=Collection(
                collection_id="c",
                owner_user_id="u",
                name="Test",
                description=None,
                status="idle",
            ),
            created_at=now,
            updated_at=now,
        )
    )
    repo = ChatRepository()
    session = ChatSession.create(
        session_id="s", user_id="u", collection_id="c", created_at=now
    )
    await repo.add_session(session)
    grant = await repo.set_permission(
        "s",
        "u",
        mode="auto",
        actions=["record_finding_feedback"],
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        expected_revision=0,
    )
    call = ChatToolCall.requested(
        tool_call_id="call",
        session_id="s",
        assistant_message_id="m",
        name="record_finding_feedback",
        arguments={},
        risk=ToolRisk.WRITE,
    ).require_approval()
    message = ChatMessage.assistant_tool_calls(
        message_id="m",
        session_id="s",
        content="",
        tool_calls=(
            ChatToolRequest(
                tool_call_id=call.tool_call_id,
                name=call.name,
                arguments=call.arguments,
                position=call.position,
                decision_user_id=call.decision_user_id,
                decision_arguments_digest=call.decision_arguments_digest,
                decided_at=call.decided_at,
                decision_basis=call.decision_basis,
                authorization_revision=call.authorization_revision,
            ),
        ),
        created_at=now,
    )
    await repo.save_trajectory(
        chat_session=session, messages=(message,), tool_calls=(call,), tool_results=()
    )
    return repo, call, grant, now


async def test_automatic_claim_is_durable_and_not_replayed(
    permission_case, postgres_session_factory
):
    repo, call, grant, now = permission_case
    first, second = await asyncio.gather(
        *[
            repo.claim_automatic_call(
                session_id="s", user_id="u", tool_call_id="call", started_at=now
            )
            for _ in range(2)
        ]
    )
    claimed = first or second
    assert (first is None) != (second is None)
    fresh = ChatRepository()
    stored = await fresh.read_tool_call("call")
    assert stored == claimed
    assert stored.decision_basis == "scope_grant"
    assert stored.authorization_revision == grant["revision"]
    assert (
        await fresh.claim_automatic_call(
            session_id="s", user_id="u", tool_call_id="call", started_at=now
        )
        is None
    )


async def test_revoke_blocks_next_claim_and_old_approval(permission_case):
    repo, call, grant, now = permission_case
    await repo.set_permission(
        "s", "u", mode="read_only", actions=[], expires_at=None, expected_revision=1
    )
    assert (
        await repo.claim_automatic_call(
            session_id="s", user_id="u", tool_call_id="call", started_at=now
        )
        is None
    )
    with pytest.raises(ChatWriteConflict) as conflict:
        await repo.decide_tool_call(
            session_id="s",
            user_id="u",
            tool_call_id="call",
            arguments_digest=call.arguments_digest,
            decision="approved",
            decided_at=now,
        )
    assert conflict.value.reason == "permission_read_only"
    assert (await repo.read_tool_call("call")).status.value == "approval_required"


async def test_revoke_racing_claim_has_one_serialized_boundary(permission_case):
    repo, call, grant, now = permission_case
    claimed, revoked = await asyncio.gather(
        repo.claim_automatic_call(
            session_id="s", user_id="u", tool_call_id="call", started_at=now
        ),
        repo.set_permission(
            "s", "u", mode="confirm", actions=[], expires_at=None, expected_revision=1
        ),
    )
    assert revoked["revision"] == 2
    stored = await repo.read_tool_call("call")
    assert stored.status.value == ("running" if claimed else "approval_required")
    assert (
        await repo.claim_automatic_call(
            session_id="s", user_id="u", tool_call_id="call", started_at=now
        )
        is None
    )


async def test_expiry_identity_and_new_grant_do_not_reactivate_queue(permission_case):
    repo, call, grant, now = permission_case
    with pytest.raises(FileNotFoundError):
        await repo.read_permission("s", "other-user")
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert (
        await repo.claim_automatic_call(
            session_id="s", user_id="u", tool_call_id="call", started_at=future
        )
        is None
    )
    with pytest.raises(ValueError, match="unknown_permission_action"):
        await repo.set_permission(
            "s",
            "u",
            mode="auto",
            actions=["future_device_operation"],
            expires_at=future,
            expected_revision=1,
        )
    await repo.set_permission(
        "s",
        "u",
        mode="auto",
        actions=grant["actions"],
        expires_at=future,
        expected_revision=1,
    )
    assert (
        await repo.claim_automatic_call(
            session_id="s", user_id="u", tool_call_id="call", started_at=now
        )
        is None
    )
    with pytest.raises(ValueError, match="revision_conflict"):
        await repo.set_permission(
            "s", "u", mode="confirm", actions=[], expires_at=None, expected_revision=1
        )


async def test_revocation_between_explicit_decision_and_claim_requires_new_decision(
    permission_case,
):
    repo, call, grant, now = permission_case
    await repo.decide_tool_call(
        session_id="s",
        user_id="u",
        tool_call_id="call",
        arguments_digest=call.arguments_digest,
        decision="approved",
        decided_at=now,
    )
    await repo.set_permission(
        "s", "u", mode="confirm", actions=[], expires_at=None, expected_revision=1
    )
    with pytest.raises(ChatWriteConflict) as conflict:
        await repo.claim_approved_tool_call(
            session_id="s", user_id="u", tool_call_id="call", started_at=now
        )
    assert conflict.value.reason == "permission_changed_before_execution"
    await repo.decide_tool_call(
        session_id="s",
        user_id="u",
        tool_call_id="call",
        arguments_digest=call.arguments_digest,
        decision="approved",
        decided_at=now,
    )
    claimed = await repo.claim_approved_tool_call(
        session_id="s", user_id="u", tool_call_id="call", started_at=now
    )
    assert claimed.decision_basis == "explicit"
    assert claimed.authorization_revision == 2
