import pytest
from application.chat import (
    AgentRunLimits,
    CapabilityRegistry,
    ModelTurn,
    ResearchAgentRunner,
    ModelUsage,
)
from application.chat.agent_runner import _RunProgress, AgentCompletionReason
from application.chat.context_builder import ChatModelContext
from tests.unit.application.test_research_agent_runner import _context, _Model


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_research_stops_before_overall_deadline(monkeypatch):
    import application.chat.agent_runner as module

    monkeypatch.setattr(module, "monotonic", lambda: 245.0)
    progress = _RunProgress(AgentRunLimits(max_elapsed_seconds=300), started_at=0.0)
    assert progress.stop_before_model() is AgentCompletionReason.RESOURCE_BUDGET
    assert progress.remaining_seconds() == 55
    assert progress.remaining_research_seconds() == 0


@pytest.mark.anyio
async def test_inflight_decision_cannot_consume_summary_reserve(monkeypatch):
    import application.chat.agent_runner as module

    now = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])

    class Model(_Model):
        async def respond(self, **kwargs):
            if kwargs["tool_specs"]:
                assert kwargs["timeout_seconds"] == 80
                now[0] = 80
                raise TimeoutError("research phase ended")
            return await super().respond(**kwargs)

    model = Model(
        ModelTurn(content="Partial result preserved; orientation is still unknown.")
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(()),
        limits=AgentRunLimits(max_elapsed_seconds=100, max_request_seconds=180),
    )
    result = await runner.run_turn(
        context=_context(), previous_messages=(), user_message="Compare papers"
    )
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert result.error_code is None
    assert model.request_limits == [(20, runner.limits.max_finalization_output_tokens)]
    assert "orientation" in result.messages[-1].content
