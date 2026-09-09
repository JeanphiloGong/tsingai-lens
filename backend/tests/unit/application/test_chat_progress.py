import asyncio

import pytest

from application.chat.agent_runner import AgentRunResult, AgentRunStatus, AgentCompletionReason
from tests.unit.application.test_chat_session_service import _Model, _Repository, _service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_waiting_heartbeat_keeps_completed_research_counts(monkeypatch):
    monkeypatch.setattr("application.chat.session_service._HEARTBEAT_INTERVAL_SECONDS", 0.01)
    service = _service(_Model(), _Repository())
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    release = asyncio.Event()

    async def slow_turn(**kwargs):
        kwargs["progress_callback"]({
            "phase": "tools", "cycle_index": 2, "executed_tool_count": 5, "elapsed_ms": 0,
        })
        await release.wait()
        return AgentRunResult(status=AgentRunStatus.COMPLETED, messages=(),
                              completion_reason=AgentCompletionReason.MODEL_ANSWER)

    monkeypatch.setattr(service.runner, "run_turn", slow_turn)
    events = await service.stream_message_for_user(session.session_id, "user-1", message="Review the evidence")
    first = await anext(events)
    assert first["progress"]["phase"] == "waiting"
    try:
        completed = await asyncio.wait_for(anext(events), 1)
        heartbeat = await asyncio.wait_for(anext(events), 1)
        assert completed["progress"]["executed_tool_count"] == 5
        assert heartbeat["progress"]["phase"] == "waiting"
        assert heartbeat["progress"]["cycle_index"] == 2
        assert heartbeat["progress"]["executed_tool_count"] == 5
        assert heartbeat["progress"]["elapsed_ms"] > 0
    finally:
        release.set()
        remaining = [event async for event in events]
    assert remaining[-1]["type"] == "turn"
