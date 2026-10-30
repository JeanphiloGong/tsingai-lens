import asyncio

import pytest
from application.chat.agent_runner import (
    AgentCompletionReason,
    AgentRunResult,
    AgentRunStatus,
)
from application.chat import session_service as chat_session_service
from repositories.chat_repository import ChatRepository
from tests.support.postgres import seed_collection
from tests.unit.application.test_chat_session_service import _Model, _service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_heartbeat_preserves_research_phase_and_completed_counts(
    monkeypatch, *, postgres_session_factory
):
    monkeypatch.setattr(
        "application.chat.session_service._HEARTBEAT_INTERVAL_SECONDS", 0.1
    )
    monkeypatch.setattr(
        "application.chat.session_service._SNAPSHOT_INTERVAL_SECONDS", 0.05
    )
    service = _service(_Model(), ChatRepository())
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    release = asyncio.Event()

    async def slow_turn(**kwargs):
        kwargs["progress_callback"](
            {
                "phase": "tools",
                "cycle_index": 2,
                "executed_tool_count": 5,
                "elapsed_ms": 0,
            }
        )
        await release.wait()
        return AgentRunResult(
            status=AgentRunStatus.COMPLETED,
            messages=kwargs["previous_messages"],
            completion_reason=AgentCompletionReason.MODEL_ANSWER,
        )

    monkeypatch.setattr(service.runner, "run_turn", slow_turn)
    events = await service.send_message_stream(
        session.session_id, "user-1", message="Review the evidence"
    )

    async def finish_turn():
        return [event async for event in events]

    try:
        completed = await asyncio.wait_for(anext(events), 5)
        heartbeat = await asyncio.wait_for(anext(events), 5)
        assert completed["progress"]["phase"] == "tools"
        assert completed["progress"]["executed_tool_count"] == 5
        assert heartbeat["progress"]["phase"] == "tools"
        assert heartbeat["progress"]["cycle_index"] == 2
        assert heartbeat["progress"]["executed_tool_count"] == 5
        assert heartbeat["progress"]["elapsed_ms"] > 0
    finally:
        release.set()
        remaining = await asyncio.wait_for(finish_turn(), 5)
    assert remaining[-1]["type"] == "turn"
    snapshot = await chat_session_service.ChatRepo.read_response_snapshot(session.session_id)
    assert snapshot.status == "completed"
    assert not await chat_session_service.ChatRepo.is_session_running(session.session_id)


@pytest.fixture(autouse=True)
async def research_collection(postgres_session_factory, anyio_backend):
    await seed_collection(postgres_session_factory, "col-1", document_ids=("doc-1",))
