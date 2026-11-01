import json
import pytest
from application.chat import (
    CapabilityRegistry,
    ChatContextBuilder,
    ModelTurn,
    ResearchAgentRunner,
)
from application.chat.agent_runner import _RunProgress
from tests.unit.application.test_chat_context_builder import (
    _user,
    _tool_pair,
    _CompactionModel,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_original_parameter_message_is_not_replaced_by_recent_tool_output():
    table = _user("table", "A01 250 500 90 30 90\n" * 150)
    active = _user("active", "Produce A-H using the original table.")
    pair = _tool_pair(call_id="recent", payload={"content": "passage " * 600})
    view = ChatContextBuilder(max_messages=3).for_model(
        (table, *pair, active), active_user_message_id="active", max_input_tokens=10000
    )
    assert table in view.messages
    assert active in view.messages
    assert all(m not in view.messages for m in pair)


def test_oversized_user_input_fails_instead_of_summarizing_numbers():
    table = _user("table", "A01 250 500 90 30 90\n" * 400)
    with pytest.raises(ValueError, match="context budget"):
        ChatContextBuilder().for_model(
            (table, _user("active", "Continue")),
            active_user_message_id="active",
            max_input_tokens=500,
        )


@pytest.mark.anyio
async def test_historical_notes_reach_new_turn_without_old_budget_or_actions():
    prior = _user("prior", "Read Methods")
    pair = _tool_pair(call_id="methods", payload={"content": "orientation unknown"})
    notes = {
        "scope": "old scope",
        "checks": [
            {
                "statement": "orientation unknown",
                "conditions": "as-built",
                "basis_message_ids": [pair[1].message_id],
                "unresolved": "orientation",
            }
        ],
        "next_actions": ["old task"],
    }
    checkpoint = {
        "user_message_id": "prior",
        "working_summary": json.dumps(notes),
        "compacted_message_ids": [m.message_id for m in pair],
    }

    class Model:
        async def respond(self, *, context, **kwargs):
            summary = json.loads(context.working_summary)
            assert summary["checks"] == notes["checks"]
            assert summary["scope"] != "old scope" and not summary["next_actions"]
            assert pair[1] in context.messages
            return ModelTurn(content="Need orientation before comparison")

    events = []
    from application.chat import AgentContext

    result = await ResearchAgentRunner(
        model=Model(), capabilities=CapabilityRegistry(())
    ).run_turn(
        context=AgentContext("chat-1", "user-1", "col-1"),
        previous_messages=(prior, *pair),
        user_message="Use these sources for a new comparison",
        context_checkpoint=checkpoint,
        progress_callback=events.append,
    )
    assert result.error_code is None
    assert result.execution_plan is None
    assert events[-1]["executed_tool_count"] == 0


@pytest.mark.anyio
async def test_compaction_accepts_citation_from_validated_previous_notes():
    notes = {
        "scope": "history",
        "checks": [
            {
                "statement": "orientation unknown",
                "conditions": "as-built",
                "basis_message_ids": ["historical-result"],
                "unresolved": "orientation",
            }
        ],
        "next_actions": [],
    }
    runner = ResearchAgentRunner(
        model=_CompactionModel(ModelTurn(content=json.dumps(notes))),
        capabilities=CapabilityRegistry(()),
    )
    progress = _RunProgress(runner.limits, working_summary=json.dumps(notes))
    out = await runner._compact_working_notes(
        _user("active", "Continue"),
        list(_tool_pair(call_id="new")),
        progress,
        notes_budget=6000,
        execution_plan=None,
    )
    assert json.loads(out) == notes


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["other-user-message", "bad-json", "unknown-basis"])
async def test_invalid_history_does_not_replace_current_request(invalid):
    from application.chat import AgentContext

    prior = _user("prior", "Old task")
    notes = {"scope": "old", "checks": [], "next_actions": []}
    if invalid == "unknown-basis":
        notes["checks"] = [
            {
                "statement": "unsupported",
                "conditions": "",
                "basis_message_ids": ["missing"],
                "unresolved": "",
            }
        ]
    checkpoint = {
        "user_message_id": "different" if invalid == "other-user-message" else "prior",
        "working_summary": "broken" if invalid == "bad-json" else json.dumps(notes),
    }

    class Model:
        async def respond(self, *, context, **kwargs):
            assert not context.working_summary
            assert context.messages[-1].content == "New task"
            return ModelTurn(content="New task needs evidence")

    result = await ResearchAgentRunner(
        model=Model(), capabilities=CapabilityRegistry(())
    ).run_turn(
        context=AgentContext("chat-1", "user-1", "col-1"),
        previous_messages=(prior,),
        user_message="New task",
        context_checkpoint=checkpoint,
    )
    assert result.error_code is None


@pytest.mark.anyio
async def test_interrupted_plan_reaches_new_request_as_pending_runtime_work():
    from application.chat import AgentContext, ModelToolCall
    from tests.unit.application.test_research_agent_runner import _Model

    first = await ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(
                    ModelToolCall(
                        "update_execution_plan",
                        {
                            "steps": [
                                {
                                    "step_id": "orientation",
                                    "action": "Check tensile orientation",
                                    "status": "in_progress",
                                }
                            ],
                            "status": "in_progress",
                            "explanation": "The specimen orientation is unresolved.",
                        },
                    ),
                )
            ),
            ModelTurn(content="Will inspect later"),
            ModelTurn(content="Still inspecting later"),
            ModelTurn(content="Orientation remains unchecked."),
            discover=("update_execution_plan",),
        ),
        capabilities=CapabilityRegistry(()),
    ).run_turn(
        context=AgentContext("chat-1", "user-1", "col-1"),
        previous_messages=(),
        user_message="Compare orientation",
    )

    class Model:
        async def respond(self, *, context, **kwargs):
            notes = json.loads(context.working_summary)
            assert any(
                "Check tensile orientation" in check["statement"]
                for check in notes["checks"]
            )
            assert all(
                check["conditions"] == "Runtime work only; not scientific evidence."
                for check in notes["checks"]
            )
            assert not notes["next_actions"]
            assert context.messages[-1].content == "Continue but exclude paper B"
            return ModelTurn(content="Paper B excluded; orientation is still unknown.")

    events = []
    second = await ResearchAgentRunner(
        model=Model(), capabilities=CapabilityRegistry(())
    ).run_turn(
        context=AgentContext("chat-1", "user-1", "col-1"),
        previous_messages=first.messages,
        user_message="Continue but exclude paper B",
        progress_callback=events.append,
    )
    assert second.error_code is None
    assert second.execution_plan is None
    assert events[-1]["executed_tool_count"] == 0
