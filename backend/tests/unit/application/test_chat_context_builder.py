from __future__ import annotations

from dataclasses import replace
import json
import pytest
from domain.chat import ChatToolRequest

from domain.chat import ChatMessage, ChatResourceRef, ChatSourceContext, ChatToolResult

from application.chat import ChatContextBuilder


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _CompactionModel:
    def __init__(self, *turns):
        self.turns = iter(turns)
        self.contexts = []

    async def respond(self, *, context, **kwargs):
        self.contexts.append(context)
        turn = next(self.turns)
        if isinstance(turn, Exception):
            raise turn
        return turn


def test_context_token_budget_preserves_complete_call_result_batches():
    active = _user("active", "Compare elongation under the same annealing conditions.")
    pairs = [_tool_pair(call_id=f"source-{i}", payload={
        "content": "Ti-6Al-4V Methods and Results at 850 and 950 C. " * 100,
    }) for i in range(5)]
    messages = (active, *(message for pair in pairs for message in pair))
    view = ChatContextBuilder().for_model(messages, max_input_tokens=6000)
    assert active in view.messages
    assert len(view.messages) < len(messages)
    assert sum(ChatContextBuilder.estimate_tokens(ChatContextBuilder.model_message(message))
               for message in view.messages) + ChatContextBuilder.estimate_tokens(view.rollover_summary) <= 6000
    for call, result in pairs:
        assert (call in view.messages) == (result in view.messages)


@pytest.mark.anyio
async def test_compaction_preserves_research_notes_and_full_archived_history():
    from application.chat import CapabilityRegistry, ModelTurn, ResearchAgentRunner
    from application.chat.agent_runner import _RunProgress

    active = _user("active", "Correct the elongation comparison; do not save.")
    old = _tool_pair(call_id="methods", payload={
        "document_id": "paper-A", "source_ref": "methods-A", "page": 3,
        "content": "Same material and test method; annealing temperatures differ.",
    })
    recent = _tool_pair(call_id="results", payload={"source_ref": "results-A", "page": 10})
    messages = (active, *old, *recent)
    notes = {"scope": active.content, "checks": [{
        "statement": "Paper A methods-A p3 establishes material and tensile method.",
        "conditions": "Temperature comparison, not time; same baseline required.",
        "basis_message_ids": [old[1].message_id], "unresolved": "Read the exact result before correcting the Finding.",
    }], "next_actions": ["Re-read methods-A together with results-A before the final judgment."]}
    model = _CompactionModel(ModelTurn(content=json.dumps(notes)))
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()),
                                 context_builder=ChatContextBuilder(max_messages=3))
    progress = _RunProgress(runner.limits)
    view = await runner._prepare_model_context(messages, (), progress, active_user_message_id="active")
    assert view.messages == (active, *recent)
    assert json.loads(view.working_summary) == notes
    assert progress.compacted_message_ids == {message.message_id for message in old}
    assert messages == (active, *old, *recent)
    assert old[1].tool_result.data["content"].startswith("Same material")
    assert model.contexts[0].compacting
    assert progress.compaction_attempts == 0
    again = await runner._prepare_model_context(messages, (), progress, active_user_message_id="active")
    assert again == view
    assert len(model.contexts) == 1


@pytest.mark.anyio
async def test_failed_compaction_does_not_discard_archived_observations():
    from application.chat import CapabilityRegistry, ModelTurn, ResearchAgentRunner, ModelResponseError
    from application.chat.agent_runner import _RunProgress

    active = _user("active", "Check the same measurement.")
    messages = (active, *_tool_pair(call_id="old"), *_tool_pair(call_id="new"))
    invalid = ModelTurn(content=json.dumps({"scope": "same measurement", "checks": [{
        "statement": "Claim", "conditions": "", "basis_message_ids": ["invented"], "unresolved": "",
    }], "next_actions": []}))
    model = _CompactionModel(invalid, invalid)
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()),
                                 context_builder=ChatContextBuilder(max_messages=3))
    progress = _RunProgress(runner.limits)
    with pytest.raises(ModelResponseError, match="working notes"):
        await runner._prepare_model_context(messages, (), progress, active_user_message_id="active")
    assert not progress.compacted_message_ids
    assert progress.working_summary == ""


@pytest.mark.anyio
async def test_repeated_compaction_has_a_visible_failure_exit():
    from application.chat import CapabilityRegistry, ModelTurn, ResearchAgentRunner, ModelResponseError
    from application.chat.agent_runner import _RunProgress

    active = _user("active", "Keep checking the selected paper.")
    messages = (active, *_tool_pair(call_id="old", payload={"text": "x" * 5000}),
                *_tool_pair(call_id="new", payload={"text": "y" * 5000}))
    notes = {"scope": "selected paper", "checks": [], "next_actions": []}
    model = _CompactionModel(*(ModelTurn(content=json.dumps(notes)) for _ in range(3)))
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()),
                                 context_builder=ChatContextBuilder(max_messages=3))
    progress = _RunProgress(runner.limits, compaction_attempts=3)
    with pytest.raises(ModelResponseError, match="compacted"):
        await runner._prepare_model_context(messages, (), progress, active_user_message_id="active")
    assert messages[2].tool_result is not None


def _user(message_id: str, content: str) -> ChatMessage:
    return ChatMessage.user(
        message_id=message_id,
        session_id="chat-1",
        content=content,
        created_at="2026-08-19T00:00:00+00:00",
    )


def _assistant(message_id: str, content: str) -> ChatMessage:
    return ChatMessage.assistant(
        message_id=message_id,
        session_id="chat-1",
        content=content,
        created_at="2026-08-19T00:00:00+00:00",
    )


def _tool_pair(
    *,
    call_id: str = "call-1",
    payload: dict | None = None,
) -> tuple[ChatMessage, ChatMessage]:
    call = ChatMessage.assistant_tool_calls(
        message_id=f"msg-{call_id}",
        session_id="chat-1",
        content="",
        tool_calls=(ChatToolRequest(tool_call_id=call_id, name="get_collection_context", arguments={}, position=0),),


        created_at="2026-08-19T00:00:00+00:00",
    )
    result = ChatMessage.from_tool_result(
        message_id=f"msg-result-{call_id}",
        session_id="chat-1",
        result=ChatToolResult(
            tool_call_id=call_id,
            status="succeeded",
            data=payload or {"collection_id": "col-1"},
        ),
        created_at="2026-08-19T00:00:00+00:00",
    )
    return call, result


def test_context_builder_keeps_tool_call_and_result_as_one_protocol_unit() -> None:
    call, result = _tool_pair()
    messages = (
        _user("msg-old-user", "old question"),
        _assistant("msg-old-answer", "old answer"),
        call,
        result,
    )

    selected = ChatContextBuilder(max_messages=3, max_chars=2_000).for_model(
        messages
    ).messages

    assert selected == (messages[0], call, result)


def test_context_builder_returns_a_bounded_recent_suffix() -> None:
    call, result = _tool_pair()
    latest = _user("msg-latest", "new question")
    messages = (
        _user("msg-old-user", "x" * 900),
        _assistant("msg-old-answer", "y" * 900),
        call,
        result,
        latest,
    )

    selected = ChatContextBuilder(max_messages=3, max_chars=1_000).for_model(messages).messages

    assert selected[-1] == latest
    assert selected == (call, result, latest)
    assert len(selected) <= 3
    assert sum(len(item.content) for item in selected) <= 1_000
    assert not (
        selected and selected[0].role.value == "tool"
    )


def test_context_builder_budgets_tool_result_once_for_model_wire_content() -> None:
    user = _user("msg-user", "split energy input effects into focused questions")
    call = ChatMessage.assistant_tool_calls(
        message_id="msg-scope-call",
        session_id="chat-1",
        content="I will preview the relevant paper scope.",
        tool_calls=(ChatToolRequest(tool_call_id="call-scope", name="preview_research_scope", arguments={"question": "How does energy input affect ductility?"}, position=0),),


        created_at="2026-08-19T00:00:00+00:00",
    )
    result = ChatMessage.from_tool_result(
        message_id="msg-scope-result",
        session_id="chat-1",
        result=ChatToolResult(
            tool_call_id="call-scope",
            status="succeeded",
            data={"scope_records": ["x" * 4000]},
        ),
        created_at="2026-08-19T00:00:00+00:00",
    )

    selected = ChatContextBuilder(max_messages=3, max_chars=5_000).for_model(
        (user, call, result)
    ).messages

    assert selected == (user, call, result)


def test_context_builder_preserves_active_user_request_when_observations_fill_budget() -> None:
    user = _user(
        "msg-active-user",
        "Compare the selected papers and clearly report what remains unread.",
    )
    older_call, older_result = _tool_pair(
        call_id="call-older",
        payload={"papers": ["a" * 700]},
    )
    latest_call, latest_result = _tool_pair(
        call_id="call-latest",
        payload={"findings": ["b" * 700]},
    )
    latest_unit_size = sum(
        ChatContextBuilder._size(item) for item in (latest_call, latest_result)
    )
    budget = ChatContextBuilder._size(user) + latest_unit_size + 10

    selected = ChatContextBuilder(max_messages=5, max_chars=budget + 300, max_summary_chars=300).for_model(
        (user, older_call, older_result, latest_call, latest_result)
    ).messages

    assert selected == (user, latest_call, latest_result)


def test_rollover_keeps_lineage_without_source_text_or_errors() -> None:
    call, result = _tool_pair(payload={
        "document_id": "paper-1", "source_ref": "methods-3", "source_digest": "a" * 64,
        "next_offset": 2000, "content": "secret-source-text" * 500,
        "error_message": "private-provider-error", "api_key": "private-key",
    })
    active = _user("active", "Compare Methods and Results, retaining uncertainty.")
    builder = ChatContextBuilder(max_chars=1500, max_summary_chars=650)
    view = builder.for_model((active, call, result))
    assert view.messages == (active,)
    assert "methods-3" in view.rollover_summary
    assert "paper-1" in view.rollover_summary
    assert "next_offset" in view.rollover_summary
    assert all(text not in view.rollover_summary for text in ("secret-source-text", "private-provider-error", "private-key"))
    assert json.loads(view.rollover_summary)["entries"]
    assert sum(builder._size(message) for message in view.messages) + len(view.rollover_summary) <= builder.max_chars


def test_incomplete_batch_is_never_sent_as_partial_protocol() -> None:
    call, result = _tool_pair()
    request = ChatToolRequest("call-2", "read_source", {"document_id": "paper-2"}, 1)
    call = replace(call, tool_calls=(*call.tool_calls, request))
    user = _user("active", "Compare two papers")
    view = ChatContextBuilder().for_model((user, call, result))
    assert view.messages == (user,)
    assert "call-2" in view.rollover_summary
    assert "paper-2" in view.rollover_summary


def test_transient_instruction_does_not_replace_the_research_question() -> None:
    user = _user("active", "Compare the selected papers")
    instruction = _user("transient", "Give a final answer using inspected Sources.")
    view = ChatContextBuilder(max_chars=1000).for_model(
        (user, _assistant("long-answer", "old" * 1000), instruction), active_user_message_id=user.message_id)
    assert view.messages == (user, instruction)
    with pytest.raises(ValueError, match="exceed context budget"):
        ChatContextBuilder(max_chars=1000).for_model((_user("large", "x" * 2000),))


def test_rollover_preserves_selected_source_and_pending_approval_lineage() -> None:
    active = replace(_user("active", "Check this measured result."), source_contexts=(
        ChatSourceContext(
            resource_ref=ChatResourceRef("source", "paper-1:results-2"),
            collection_id="col-1", document_id="paper-1", document_title="Paper 1",
            source_kind="text_window", source_ref="results-2", page=2, quote="The measured elongation was 8%.",
        ),
    ))
    pending, _ = _tool_pair(call_id="pending", payload={})
    pending = replace(pending, tool_calls=(ChatToolRequest(
        "pending", "create_evidence_version", {"document_id": "paper-1", "source_ref": "results-2"}, 0,
    ),))
    messages = (_assistant("old", "old source text" * 1000), active, pending)
    builder = ChatContextBuilder(max_chars=1800, max_summary_chars=500)

    view = builder.for_model(messages)

    assert view.messages == (active,)
    assert view.messages[0].source_contexts == active.source_contexts
    assert "pending" in view.rollover_summary
    assert "results-2" in view.rollover_summary
    assert "old source text" not in view.rollover_summary
    assert len(messages) == 3
    assert sum(builder._size(item) for item in view.messages) + len(view.rollover_summary) <= builder.max_chars


def test_complete_batch_is_indivisible_under_message_budget() -> None:
    first, result = _tool_pair()
    second_request = ChatToolRequest("call-2", "read_source", {}, 1)
    first = replace(first, tool_calls=(*first.tool_calls, second_request))
    second_result = ChatMessage.from_tool_result(
        message_id="result-2", session_id="chat-1",
        result=ChatToolResult(tool_call_id="call-2", status="succeeded", data={"document_id": "paper-2"}),
        created_at="2026-09-08T00:00:00+00:00",
    )
    active = _user("active", "Compare the two papers")
    messages = (active, first, result, second_result)

    view = ChatContextBuilder(max_messages=3).for_model(messages)

    assert view.messages == (active,)
    assert "paper-2" in view.rollover_summary
    assert ChatContextBuilder(max_messages=4).for_model(messages).messages == messages


def test_default_context_keeps_eight_findings_for_a_constrained_research_plan() -> None:
    user = _user("active", "Compare the evidence gaps and draft a plan: power <= 300 W, at most 4 samples per group.")
    requests = []
    results = []
    for index in range(8):
        call_id = f"finding-call-{index}"
        requests.append(ChatToolRequest(call_id, "inspect_published_finding", {
            "objective_id": "elongation", "finding_id": f"finding-{index}"
        }, index))
        results.append(ChatMessage.from_tool_result(
            message_id=f"result-{index}", session_id="chat-1",
            result=ChatToolResult(tool_call_id=call_id, status="succeeded", data={
                "finding": {"finding_id": f"finding-{index}", "statement": "Annealing changes elongation; process conditions limit transferability."},
                "evidence": [{
                    "evidence_id": f"evidence-{index}-{page}",
                    "document_id": "lpbf-tc4",
                    "source_ref": f"results-{page}",
                    "source_excerpt": (
                        "The annealed Ti-6Al-4V specimen showed improved elongation with reduced strength. "
                        "Specimen orientation and test temperature were held fixed; no independent laser-power effect was measured. "
                    ) * 4,
                } for page in range(8)],
            }), created_at="2026-09-09T00:00:00+00:00",
        ))
    call = ChatMessage.assistant_tool_calls(
        message_id="finding-batch", session_id="chat-1", content="",
        tool_calls=tuple(requests), created_at="2026-09-09T00:00:00+00:00",
    )
    messages = (user, call, *results)
    view = ChatContextBuilder().for_model(messages)
    assert view.messages == messages
    assert not view.rollover_summary
