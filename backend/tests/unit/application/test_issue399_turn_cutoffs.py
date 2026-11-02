"""Long, progressing research keeps its per-request execution boundaries."""

import asyncio
from dataclasses import replace

import pytest

from application.chat import (
    AgentCompletionReason,
    CapabilityRegistry,
    ModelResponseError,
    ModelToolCall,
    ModelTurn,
    ModelUsage,
    ResearchAgentRunner,
)
from application.chat.agent_runner import AgentRunLimits, _RunProgress
import application.chat.agent_runner as module
from application.chat.context_builder import ChatModelContext
from domain.chat import ChatMessage, ToolRisk
from tests.unit.application.test_research_agent_runner import (
    _Capability,
    _Model,
    _QuestionArguments,
    _context,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("elapsed_ms,total_tokens", [(601_000, 0), (0, 1_500_000), (601_000, 1_500_000)])
def test_default_limits_do_not_stop_a_long_research_continuation(elapsed_ms, total_tokens):
    progress = _RunProgress(AgentRunLimits())
    progress.restore_persisted_progress({
        "elapsed_ms": elapsed_ms,
        "total_tokens": total_tokens,
        "model_cycles": 10,
        "executed_tool_count": 20,
    })

    assert progress.stop_before_model() is None
    assert progress.restored_elapsed_seconds == elapsed_ms / 1000
    assert progress.model_tokens == total_tokens
    assert progress.limits.max_request_seconds is None


@pytest.mark.anyio
async def test_progressing_reads_cross_old_time_and_token_cutoffs(monkeypatch):
    now = [module.monotonic()]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])

    class Model(_Model):
        async def respond(self, **kwargs):
            turn = await super().respond(**kwargs)
            now[0] += 125
            return replace(turn, usage=ModelUsage(prompt_tokens=400_000, total_tokens=400_000))

    read = _Capability("read_source", ToolRisk.READ, _QuestionArguments)
    read.spec = replace(read.spec, initially_available=True)
    model = Model(
        *(ModelTurn(tool_calls=(ModelToolCall("read_source", {"question": paper}),))
          for paper in ("paper-1", "paper-2", "paper-3")),
        ModelTurn(content="Three reported experiments were inspected; comparability remains qualified."),
    )
    events = []
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,)),
    ).run_turn(
        context=_context(), previous_messages=(), user_message="Compare three experiments.",
        progress_callback=events.append,
    )

    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER
    assert [item["question"] for item in read.executed_arguments] == ["paper-1", "paper-2", "paper-3"]
    assert events[-1]["elapsed_ms"] > 300_000
    assert events[-1]["total_tokens"] > 1_000_000
    assert events[-1]["remaining_seconds"] is None
    assert events[-1]["remaining_token_budget"] is None
    assert [timeout for timeout, _ in model.request_limits] == [None] * 4


@pytest.mark.anyio
async def test_unbounded_turn_keeps_a_timeout_for_each_request():
    cancelled = asyncio.Event()

    class Model:
        async def respond(self, **kwargs):
            assert kwargs["timeout_seconds"] == 0.01
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    limits = AgentRunLimits(max_request_seconds=0.01)
    runner = ResearchAgentRunner(model=Model(), capabilities=CapabilityRegistry(()), limits=limits)
    progress = _RunProgress(limits)
    progress.restore_persisted_progress({"elapsed_ms": 601_000, "total_tokens": 1_500_000})
    context = ChatModelContext((ChatMessage.user(
        message_id="u", session_id="chat-1", content="Compare the reported experiments.",
        created_at="2026-11-02T00:00:00Z",
    ),))

    with pytest.raises(ModelResponseError) as failure:
        await runner._respond(context, (), progress, None)
    assert failure.value.reason == "provider_timeout"
    assert cancelled.is_set()


@pytest.mark.anyio
async def test_unbounded_turn_still_cancels_an_inflight_request():
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class Model:
        async def respond(self, **kwargs):
            assert kwargs["timeout_seconds"] is None
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    runner = ResearchAgentRunner(model=Model(), capabilities=CapabilityRegistry(()))
    task = asyncio.create_task(runner.run_turn(
        context=_context(), previous_messages=(), user_message="Inspect the literature.",
    ))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
