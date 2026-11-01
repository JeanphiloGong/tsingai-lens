import pytest
from application.chat import CapabilityRegistry, ModelTurn, ResearchAgentRunner
from application.chat.agent_runner import _RunProgress, AgentCompletionReason
from domain.chat import ChatMessage
from tests.unit.application.test_research_agent_runner import _Model, _context


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content,valid",
    [
        ("Evidence is incomplete; compare conditions next.", True),
        ("The excerpt quotes `<tool_call>` as text; it is not a new action.", True),
        ("<tool_call>update_execution_plan()</tool_call>", False),
        ("Result </undefined>", False),
    ],
)
async def test_finalization_checks_before_streaming(content, valid):
    runner = ResearchAgentRunner(
        model=_Model(ModelTurn(content=content)), capabilities=CapabilityRegistry(())
    )
    user = ChatMessage.user(
        message_id="user-1",
        session_id="chat-1",
        content="Compare IN718 conditions",
        created_at="2026-10-29T00:00:00Z",
    )
    chunks = []
    result = await runner._finalize_with_current_evidence(
        AgentCompletionReason.RESOURCE_BUDGET,
        _RunProgress(runner.limits),
        _context(),
        [user],
        [],
        [],
        checkpoint=None,
        text_delta_callback=chunks.append,
    )
    if valid:
        assert chunks == [content]
        assert result.error_code is None
    else:
        assert chunks == []
        assert result.error_code == "final_answer_unavailable"
    assert result.execution_plan is None
