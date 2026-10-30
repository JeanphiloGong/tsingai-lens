import json
from datetime import datetime, timedelta, timezone

import pytest
from application.chat import (
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
    ToolSpec,
)
from application.chat import session_service as chat_session_service
from domain.chat import ToolPermissionMode, ToolRisk
from domain.chat.permissions import AUTO_ACTIONS, change_permission, permits_automatic
from exceptions import ResourceConflictException, ResourceNotFoundException
from repositories.chat_repository import ChatRepository
from repositories.source_artifact_repository import SourceArtifactRepository
from tests.support.postgres import read_tool_calls, seed_collection
from tests.unit.application.test_chat_session_service import (
    _CollectionService,
    _Question,
    _WriteCapability,
)
from tests.unit.application.test_research_agent_runner import _Model

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "mode,expected",
    [("confirm", "approval_required"), ("read_only", "failed"), ("auto", "completed")],
)
async def test_session_permission_controls_actual_write(
    mode, expected, *, postgres_session_factory
):
    repository = ChatRepository()
    write = _WriteCapability()
    write.spec = ToolSpec(
        name="record_finding_feedback",
        description="Save feedback",
        risk=ToolRisk.WRITE,
        input_model=_Question,
    )
    model = _Model(
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    name=write.spec.name, arguments={"question": "Correct the trend"}
                ),
            )
        ),
        ModelTurn(content="The feedback is saved."),
        discover=(write.spec.name,),
    )
    chat_session_service.ChatRepo = repository
    chat_session_service.collection_service = _CollectionService()
    chat_session_service.SourceArtifactRepo = SourceArtifactRepository()
    chat_session_service.runner = ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((write,))
    )
    service = chat_session_service
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    permission = await repository.set_permission(
        session.session_id,
        "user-1",
        mode=mode,
        actions=[write.spec.name] if mode == "auto" else [],
        expires_at=(
            (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            if mode == "auto"
            else None
        ),
        expected_revision=0,
    )
    result = await service.send_message(
        session.session_id, "user-1", message="Save feedback on this published Finding."
    )
    assert result["status"] == expected, [
        (c.name, c.error_code)
        for c in (await read_tool_calls(repository, session.session_id))
    ]
    calls = [
        call
        for call in (await read_tool_calls(repository, session.session_id))
        if call.name == write.spec.name
    ]
    if mode == "read_only":
        # The write schema is hidden from discovery. A forged model call is
        # still retained as a denied trajectory event for auditability.
        assert len(calls) == 1
        assert calls[0].status.value == "failed"
        assert calls[0].error_code == "tool_permission_denied"
        assert not write.executed
        return
    assert len(calls) == 1
    if mode == "auto":
        assert calls[0].status.value == "succeeded"
        assert calls[0].decision_basis == "scope_grant"
        assert calls[0].authorization_revision == permission["revision"]
    else:
        assert not write.executed


async def test_automatic_grant_is_not_reinterpreted_from_user_phrases(
    *, postgres_session_factory
):
    repository = ChatRepository()
    write = _WriteCapability()
    write.spec = ToolSpec(
        name="record_finding_feedback",
        description="Save feedback",
        risk=ToolRisk.WRITE,
        input_model=_Question,
    )
    chat_session_service.ChatRepo = repository
    chat_session_service.collection_service = _CollectionService()
    chat_session_service.SourceArtifactRepo = SourceArtifactRepository()
    chat_session_service.runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(
                    ModelToolCall(
                        name=write.spec.name, arguments={"question": "Review"}
                    ),
                )
            ),
            ModelTurn(content="The review remains unsaved."),
            discover=(write.spec.name,),
        ),
        capabilities=CapabilityRegistry((write,)),
    )
    service = chat_session_service
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    await repository.set_permission(
        session.session_id,
        "user-1",
        mode="auto",
        actions=[write.spec.name],
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        expected_revision=0,
    )
    result = await service.send_message(
        session.session_id,
        "user-1",
        message="Inspect this feedback, do not save anything.",
    )
    assert result["status"] == "completed"
    assert write.executed


@pytest.mark.parametrize("revoke", [False, True])
async def test_each_automatic_write_rechecks_current_permission(
    revoke, *, postgres_session_factory
):
    from tests.unit.application.test_research_agent_runner import _Capability

    repository = ChatRepository()

    class RevisionCapability(_Capability):
        async def execute(self, context, arguments):
            result = await super().execute(context, arguments)
            if revoke:
                await repository.set_permission(
                    context.session_id,
                    "user-1",
                    mode="read_only",
                    actions=[],
                    expires_at=None,
                    expected_revision=1,
                )
            return result

    finding_write = RevisionCapability(
        "create_finding_version", ToolRisk.WRITE, _Question
    )
    plan_write = _Capability("create_research_plan", ToolRisk.WRITE, _Question)
    model = _Model(
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    "update_execution_plan",
                    {
                        "steps": [
                            {
                                "step_id": "correct",
                                "action": "Save the verified correction",
                                "status": "in_progress",
                            },
                            {
                                "step_id": "follow_up",
                                "action": "Record the next experiment",
                                "status": "pending",
                            },
                        ],
                        "status": "in_progress",
                        "explanation": "Apply the reviewed correction before recording the next experiment.",
                    },
                ),
            )
        ),
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    finding_write.spec.name,
                    {"question": "Publish the revised Finding"},
                ),
            )
        ),
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    plan_write.spec.name,
                    {"question": "Save the follow-up plan"},
                ),
            )
        ),
        ModelTurn(content="Both revisions are saved."),
    )
    chat_session_service.ChatRepo = repository
    chat_session_service.collection_service = _CollectionService()
    chat_session_service.SourceArtifactRepo = SourceArtifactRepository()
    chat_session_service.runner = ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((finding_write, plan_write))
    )
    service = chat_session_service
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    await repository.set_permission(
        session.session_id,
        "user-1",
        mode="auto",
        actions=[
            finding_write.spec.name,
            plan_write.spec.name,
        ],
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        expected_revision=0,
    )
    stream = await service.send_message_stream(
        session.session_id, "user-1", message="Apply the two corrections."
    )
    events = [event async for event in stream]
    result = next(event["turn"] for event in events if event["type"] == "turn")
    assert result["status"] == ("failed" if revoke else "completed")
    assert len(finding_write.executed_arguments) == 1
    assert len(plan_write.executed_arguments) == (0 if revoke else 1)
    calls = [
        call
        for call in (await read_tool_calls(repository, session.session_id))
        if call.name in {finding_write.spec.name, plan_write.spec.name}
    ]
    assert len(calls) == 2
    assert len({call.tool_call_id for call in calls}) == 2
    assert calls[0].decision_basis == "scope_grant"
    assert calls[-1].status.value == ("rejected" if revoke else "succeeded")
    assert result["execution_plan"]["status"] == (
        "permission_denied" if revoke else "completed"
    )
    if revoke:
        assert result["execution_plan"]["blocking_reason"] == "permission_write_denied"
    snapshot = await repository.read_response_snapshot(session.session_id)
    assert snapshot.status == result["status"]
    assert snapshot.progress["execution_plan"] == result["execution_plan"]
    last_progress = [
        event["progress"] for event in events if event["type"] == "progress"
    ][-1]
    assert last_progress["execution_plan"] == result["execution_plan"]


async def test_permission_controller_enforces_owner_and_revision(
    *, postgres_session_factory
):
    from controllers.chat.chat_session_routes import (
        get_chat_permission,
        set_chat_permission,
    )
    from controllers.chat.schemas import ChatPermissionRequest
    from fastapi import HTTPException

    repository = ChatRepository()
    chat_session_service.ChatRepo = repository
    chat_session_service.collection_service = _CollectionService()
    chat_session_service.SourceArtifactRepo = SourceArtifactRepository()
    chat_session_service.runner = ResearchAgentRunner(
        model=_Model(), capabilities=CapabilityRegistry(())
    )
    service = chat_session_service
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    assert (
        json.loads((await get_chat_permission(session.session_id, "user-1")).body)[
            "data"
        ]["mode"]
        == "confirm"
    )
    payload = ChatPermissionRequest(mode="read_only", expected_revision=0)
    assert (
        json.loads(
            (await set_chat_permission(session.session_id, payload, "user-1")).body
        )["data"]["revision"]
        == 1
    )
    with pytest.raises(ResourceConflictException) as conflict:
        await set_chat_permission(session.session_id, payload, "user-1")
    assert conflict.value.code == 200204
    with pytest.raises(ResourceNotFoundException) as forbidden:
        await get_chat_permission(session.session_id, "another-user")
    assert forbidden.value.code == 200201
    fresh = await service.create_session(collection_id="col-1", user_id="user-1")
    assert (
        json.loads((await get_chat_permission(fresh.session_id, "user-1")).body)[
            "data"
        ]["mode"]
        == "confirm"
    )


@pytest.mark.parametrize(
    "default, expected",
    [
        (
            {
                "mode": "read_only",
                "actions": [],
                "expires_at": None,
                "revision": 4,
            },
            {"mode": "read_only", "actions": [], "expires_at": None, "revision": 1},
        ),
        (
            {
                "mode": "auto",
                "actions": ["create_finding_version"],
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat(),
                "revision": 4,
            },
            None,
        ),
        (
            {
                "mode": "auto",
                "actions": ["create_finding_version"],
                "expires_at": None,
                "revision": 4,
            },
            None,
        ),
    ],
)
async def test_new_session_inherits_collection_default_permission(
    default, expected, *, postgres_session_factory
) -> None:
    class _CollectionDefaults(_CollectionService):
        async def get_agent_default_permission_for_user(self, collection_id, user_id):
            assert (collection_id, user_id) == ("col-1", "user-1")
            return default

    repository = ChatRepository()
    chat_session_service.ChatRepo = repository
    chat_session_service.collection_service = _CollectionDefaults()
    chat_session_service.SourceArtifactRepo = SourceArtifactRepository()
    chat_session_service.runner = ResearchAgentRunner(
        model=_Model(), capabilities=CapabilityRegistry(())
    )
    service = chat_session_service

    session = await service.create_session(collection_id="col-1", user_id="user-1")

    permission = await repository.read_permission(session.session_id, "user-1")
    if expected is None:
        assert permission["mode"] == "auto"
        assert permission["actions"] == ["create_finding_version"]
        assert permission["expires_at"] == default["expires_at"]
        assert permission["revision"] == 1
    else:
        assert permission == expected


async def test_collection_read_only_default_is_applied_before_runner_tool_selection(
    *, postgres_session_factory
) -> None:
    repository = ChatRepository()

    class _CollectionDefaults(_CollectionService):
        async def get_agent_default_permission_for_user(self, collection_id, user_id):
            return {
                "mode": "read_only",
                "actions": [],
                "expires_at": None,
                "revision": 2,
            }

    chat_session_service.ChatRepo = repository
    chat_session_service.collection_service = _CollectionDefaults()
    chat_session_service.SourceArtifactRepo = SourceArtifactRepository()
    chat_session_service.runner = ResearchAgentRunner(
        model=_Model(), capabilities=CapabilityRegistry(())
    )
    service = chat_session_service
    session = await service.create_session(collection_id="col-1", user_id="user-1")

    assert (
        await service._effective_runner_permission_mode(
            session.session_id, "user-1", ToolPermissionMode.CONFIRM
        )
    ) is ToolPermissionMode.READ_ONLY
    assert (
        await service._effective_runner_permission_mode(
            session.session_id, "user-1", ToolPermissionMode.NONE
        )
    ) is ToolPermissionMode.NONE


def test_automatic_permission_covers_every_registered_write_action() -> None:
    expected = {
        "start_research_process",
        "create_objective_candidate",
        "confirm_objective",
        "start_objective_analysis",
        "record_finding_feedback",
        "curate_finding",
        "create_finding_version",
        "create_paper_experiment_revision",
        "create_research_plan",
        "revise_research_plan",
    }
    assert AUTO_ACTIONS == expected
    permission = change_permission(
        None,
        mode="auto",
        actions=sorted(expected),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        expected_revision=0,
    )
    assert all(
        permits_automatic(
            permission, action, now=datetime.now(timezone.utc).isoformat()
        )
        for action in expected
    )


def test_automatic_permission_without_expiry_stays_active_until_revoked() -> None:
    permission = change_permission(
        None,
        mode="auto",
        actions=["create_finding_version"],
        expires_at=None,
        expected_revision=0,
    )

    assert permission["expires_at"] is None
    assert permits_automatic(
        permission,
        "create_finding_version",
        now=(datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
    )


def test_all_actions_expands_on_the_server() -> None:
    permission = change_permission(
        None,
        mode="auto",
        actions=[],
        all_actions=True,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        expected_revision=0,
    )

    assert permission["actions"] == sorted(AUTO_ACTIONS)


def test_all_actions_does_not_hide_unknown_requested_actions() -> None:
    with pytest.raises(ValueError, match="unknown_permission_action"):
        change_permission(
            None,
            mode="auto",
            actions=["not_a_registered_action"],
            all_actions=True,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            expected_revision=0,
        )


def test_automatic_permission_expiry_is_bounded() -> None:
    with pytest.raises(ValueError, match="cannot_exceed_24_hours"):
        change_permission(
            None,
            mode="auto",
            actions=["create_finding_version"],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=25)).isoformat(),
            expected_revision=0,
        )


@pytest.fixture(autouse=True)
async def research_collection(postgres_session_factory, anyio_backend):
    await seed_collection(postgres_session_factory, "col-1", document_ids=("doc-1",))
