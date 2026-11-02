"""Stop an active response, retain observations, and accept revised instructions."""

import asyncio
from dataclasses import replace

import pytest

from application.chat import CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat import session_service
from domain.chat import ChatToolResult, ToolResultStatus, ToolRisk
from repositories.chat_repository import ChatRepository
from application.auth.session_service import SESSION_COOKIE_NAME
from tests.integration.persistence.test_chat_branches import branch_app  # noqa: F401
from tests.support.chat_model_connections import scripted_chat_runner  # noqa: F401
from tests.unit.application.test_research_agent_runner import _Capability, _Model
from tests.unit.application.test_chat_session_service import _WriteCapability

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("scripted_chat_runner")]


async def test_another_web_instance_stops_model_wait_and_accepts_new_instructions(branch_app, monkeypatch):
    fixture = branch_app
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class Model(_Model):
        async def respond(self, **kwargs):
            if self.turns:
                return await super().respond(**kwargs)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    class Read(_Capability):
        async def execute(self, context, arguments):
            return ChatToolResult(context.tool_call_id, ToolResultStatus.SUCCEEDED,
                                  data={"content": "Test temperature: 293 K."})

    read = Read("read_source", ToolRisk.READ)
    fixture.service.runner = ResearchAgentRunner(
        model=Model(ModelTurn(tool_calls=(ModelToolCall("read_source", {}),))),
        capabilities=CapabilityRegistry((read,)),
    )
    session = await fixture.service.create_session(collection_id="collection", user_id=fixture.owner)
    active = asyncio.create_task(fixture.service.send_message(
        session.session_id, fixture.owner, message="Compare the reported tensile tests.",
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        snapshot = await fixture.repository.read_response_snapshot(session.session_id)
        observer = session_service.ChatSessionService(runner=fixture.service.runner)
        monkeypatch.setattr(session_service, "ChatService", observer)
        path = f"/api/v1/chat-sessions/{session.session_id}/responses/{snapshot.response_id}/stop"
        response = await fixture.client.post(path)
        assert response.json()["data"]["stop_requested"] is True
        turn = await asyncio.wait_for(active, 3)
        assert turn["status"] == "cancelled" and turn["error_code"] == "user_cancelled"
        assert cancelled.is_set()
        saved = await fixture.repository.read_response_snapshot(session.session_id)
        assert saved.status == "cancelled"
        assert not await fixture.repository.is_session_running(session.session_id)
        assert any(m.tool_result and m.tool_result.data.get("content") == "Test temperature: 293 K."
                   for m in await fixture.repository.read_messages(session.session_id))
        assert (await fixture.client.post(path)).json()["data"]["status"] == "cancelled"

        model = _Model(ModelTurn(content="I will now compare only specimens tested at 293 K."))
        fixture.service.runner.model = model
        result = await fixture.client.post(f"/api/v1/chat-sessions/{session.session_id}/messages", json={
            "message": "Change the plan: compare only the 293 K tests.",
        })
        assert result.json()["data"]["status"] == "completed"
        assert next(m for m in reversed(model.contexts[-1]) if m.role.value == "user").content == "Change the plan: compare only the 293 K tests."
        assert any(m.tool_result and m.tool_result.data.get("content") == "Test temperature: 293 K."
                   for m in model.contexts[-1])
        assert (await fixture.client.post(path)).json()["data"]["code"] == "chat_response_changed"
    finally:
        if not active.done():
            active.cancel()
        await asyncio.gather(active, return_exceptions=True)


async def test_stop_request_survives_snapshot_updates_and_rejects_other_users(branch_app):
    fixture = branch_app
    from repositories.chat_repository import ChatResponseSnapshot
    snapshot = ChatResponseSnapshot("response-one", 1, "2026-11-02T00:00:00Z", "2026-11-02T00:00:00Z")
    await fixture.repository.save_response_snapshot("original", snapshot)
    path = "/api/v1/chat-sessions/original/responses/response-one/stop"
    result = await fixture.client.post(path, headers={"cookie": f"{SESSION_COOKIE_NAME}={fixture.cookies[1]}"})
    assert result.json()["code"] != 200
    assert not (await fixture.repository.read_response_snapshot("original")).stop_requested
    assert (await fixture.client.post(path)).json()["data"]["stop_requested"] is True
    await fixture.repository.save_response_snapshot("original", replace(snapshot, sequence=2, content="Partial answer"))
    saved = await fixture.repository.read_response_snapshot("original")
    assert saved.stop_requested and saved.content == "Partial answer"
    next_response = replace(snapshot, response_id="response-two", sequence=0)
    await fixture.repository.save_response_snapshot("original", next_response)
    assert not (await fixture.repository.read_response_snapshot("original")).stop_requested
    assert (await fixture.client.post(path)).json()["data"]["code"] == "chat_response_changed"


@pytest.mark.parametrize("stage", ["requested", "reading"])
async def test_stop_closes_unfinished_reads_before_accepting_another_question(branch_app, monkeypatch, stage):
    fixture = branch_app
    entered = asyncio.Event()

    class Read(_Capability):
        async def execute(self, context, arguments):
            entered.set()
            await asyncio.Event().wait()

    read = Read("read_source", ToolRisk.READ)
    fixture.service.runner = ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall("read_source", {}),))),
        capabilities=CapabilityRegistry((read,)),
    )
    original_save = session_service.ChatRepo.save_trajectory

    async def save_checkpoint(**kwargs):
        await original_save(**kwargs)
        if stage == "requested" and any(c.name == "read_source" and c.status.value == "requested" for c in kwargs["tool_calls"]):
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(session_service.ChatRepo, "save_trajectory", save_checkpoint)
    session = await fixture.service.create_session(collection_id="collection", user_id=fixture.owner)
    active = asyncio.create_task(fixture.service.send_message(session.session_id, fixture.owner, message="Read the test conditions."))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        snapshot = await fixture.repository.read_response_snapshot(session.session_id)
        path = f"/api/v1/chat-sessions/{session.session_id}/responses/{snapshot.response_id}/stop"
        await fixture.client.post(path)
        result = await asyncio.wait_for(active, 3)
        assert result["status"] == "cancelled"
        messages = await fixture.repository.read_messages(session.session_id)
        requests = [call for m in messages for call in m.tool_calls if call.name == "read_source"]
        assert len(requests) == 1
        call = await fixture.repository.read_tool_call(requests[0].tool_call_id)
        assert call.status.value == "failed" and call.error_code == "user_cancelled"
        assert sum(m.tool_result is not None and m.tool_call_id == call.tool_call_id for m in messages) == 1
        fixture.service.runner.model = _Model(ModelTurn(content="I will follow the revised question."))
        revised = await fixture.service.send_message(session.session_id, fixture.owner, message="Use a different comparison.")
        assert revised["status"] == "completed"
    finally:
        if not active.done():
            active.cancel()
        await asyncio.gather(active, return_exceptions=True)


async def test_stop_waits_for_approved_write_checkpoint_without_repeating_write(branch_app, monkeypatch):
    fixture = branch_app
    entered, finish, observed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Write(_WriteCapability):
        async def execute(self, context, arguments):
            entered.set()
            await finish.wait()
            return await super().execute(context, arguments)

    write = Write()
    fixture.service.runner = ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall("create_objective_candidate", {"question": "Compare 293 K tests"}),))),
        capabilities=CapabilityRegistry((write,)),
    )
    session = await fixture.service.create_session(collection_id="collection", user_id=fixture.owner)
    first = await fixture.service.send_message(session.session_id, fixture.owner, message="Save the objective.")
    pending = first["pending_approval"]
    original_read = ChatRepository.read_response_snapshot

    async def read_snapshot(self, session_id):
        snapshot = await original_read(self, session_id)
        if snapshot and snapshot.stop_requested:
            observed.set()
        return snapshot

    monkeypatch.setattr(ChatRepository, "read_response_snapshot", read_snapshot)
    active = asyncio.create_task(fixture.service.decide_tool_call_for_user(
        session.session_id, pending.tool_call_id, fixture.owner,
        arguments_digest=pending.arguments_digest, decision="approved",
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        snapshot = await fixture.repository.read_response_snapshot(session.session_id)
        path = f"/api/v1/chat-sessions/{session.session_id}/responses/{snapshot.response_id}/stop"
        assert (await fixture.client.post(path)).json()["data"]["stop_requested"]
        await asyncio.wait_for(observed.wait(), 3)
        assert not active.done() and not write.executed
        finish.set()
        result = await asyncio.wait_for(active, 3)
        assert result["status"] == "cancelled"
        assert len(write.executed) == 1
        saved = await fixture.repository.read_tool_call(pending.tool_call_id)
        assert saved.status.value == "succeeded"
        messages = await fixture.repository.read_messages(session.session_id)
        assert sum(m.tool_result is not None and m.tool_call_id == pending.tool_call_id for m in messages) == 1
    finally:
        finish.set()
        if not active.done():
            active.cancel()
        await asyncio.gather(active, return_exceptions=True)
