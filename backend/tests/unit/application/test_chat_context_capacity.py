import json

import pytest

from application.chat import AgentRunLimits, CapabilityRegistry, ChatContextBuilder, ModelTurn, ResearchAgentRunner
from application.chat.agent_runner import _RunProgress
from tests.unit.application.test_chat_context_builder import _CompactionModel, _tool_pair, _user


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_large_configured_window_keeps_original_history_without_compaction():
    active = _user("active", "Compare the reported measurements.")
    messages = (active, *(m for i in range(12) for m in _tool_pair(
        call_id=f"read-{i}", payload={"content": "Reported measurement and conditions. " * 500})))
    model = _CompactionModel()
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()),
                                 limits=AgentRunLimits(max_context_tokens=500_000, max_elapsed_seconds=None))
    progress = _RunProgress(runner.limits)
    view = await runner._prepare_model_context(messages, (), progress, active_user_message_id="active")
    assert view.messages == messages
    assert not progress.compacted_message_ids
    assert not model.contexts


@pytest.mark.anyio
async def test_each_overflow_uses_model_compaction_even_after_an_earlier_summary():
    active = _user("active", "Keep test orientation unresolved until it is reported.")
    notes = {"scope": active.content, "checks": [], "next_actions": ["Check the remaining measurements."]}
    model = _CompactionModel(*(ModelTurn(content=json.dumps(notes)) for _ in range(3)))
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()),
                                 context_builder=ChatContextBuilder(max_messages=3))
    progress = _RunProgress(runner.limits, restored_elapsed_seconds=190)
    messages = [active, *_tool_pair(call_id="first"), *_tool_pair(call_id="recent")]
    original = tuple(messages)
    for i in range(3):
        view = await runner._prepare_model_context(tuple(messages), (), progress, active_user_message_id="active")
        messages.extend(_tool_pair(call_id=f"next-{i}"))
    assert len(model.contexts) == 3
    assert all(context.compacting for context in model.contexts)
    assert view.messages[-1].tool_call_id == "next-1"
    assert tuple(messages[:len(original)]) == original


def test_window_does_not_skip_large_recent_exchange_to_fill_with_older_messages():
    active = _user("active", "Compare the papers.")
    older = _tool_pair(call_id="small", payload={"content": "Old small observation"})
    recent = _tool_pair(call_id="large", payload={"content": "Recent measurement. " * 10000})
    view = ChatContextBuilder().for_model((active, *older, *recent), max_input_tokens=1000)
    assert view.messages == (active,)


def test_input_capacity_reserves_output_and_instructions_without_extra_read_quota():
    builder = ChatContextBuilder()
    options = dict(context_limit=500_000, output_limit=16_384, system_prompt="Research carefully.", execution_plan=None)
    schema = {"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}
    without = builder.input_budget(**options, tool_schemas=[])
    with_tools = builder.input_budget(**options, tool_schemas=[schema])
    assert 0 < without - with_tools < 1000


@pytest.mark.anyio
async def test_current_request_is_not_reissued_after_completed_plan():
    from dataclasses import replace
    from application.chat.context_builder import ChatModelContext

    active = _user("active", "Rank the inspected experiments by applicability.")
    pair = _tool_pair(call_id="plan", payload={"status": "completed", "steps": [], "explanation": "Sources inspected."})
    call = replace(pair[0], tool_calls=(replace(pair[0].tool_calls[0], name="update_execution_plan"),))
    view = ChatModelContext((active, call, pair[1]), active_user_message_id=active.message_id,
                            execution_plan={"status": "completed", "steps": []})
    messages = view.provider_messages("system")
    assert messages[-1]["role"] == "tool"
    assert sum(message.get("content") == active.content for message in messages) == 1
    assert not any("[CURRENT RESEARCHER REQUEST]" in (message.get("content") or "") for message in messages)
