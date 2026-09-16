from __future__ import annotations

from domain.chat import ChatToolRequest

from collections import deque
import asyncio
import json
from dataclasses import replace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from application.chat import capability_policy, intent_policy
from application.chat import (
    AgentContext,
    AgentCompletionReason,
    AgentRunLimits,
    ModelUsage,
    AgentRunStatus,
    CapabilityExecutionContext,
    CapabilityRegistry,
    ModelResponseError,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
    ToolSpec,
    evaluate_authorization,
)
import application.chat.agent_runner as agent_runner_module
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolResultStatus,
    ToolRisk,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _QuestionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class _CountingArguments(BaseModel):
    validation_count: ClassVar[int] = 0

    question: str

    @classmethod
    def model_validate(cls, obj, **kwargs):  # noqa: ANN001
        cls.validation_count += 1
        return super().model_validate(obj, **kwargs)


class _FindingArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str
    finding_id: str


class _ObjectiveArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str


class _RevisionArguments(_ObjectiveArguments):
    parent_plan_id: str


class _Model:
    # Script domain decisions; perform the actual discovery round trip when a
    # scripted call needs a deferred schema. all_tool_spec_names includes both.
    def __init__(self, *turns: ModelTurn | Exception, discover: tuple[str, ...] = (), source_inspection_required: bool = False) -> None:
        self.turns = deque(turns)
        self.discover = discover
        self.source_inspection_required = source_inspection_required
        self.discovery_decisions: list[tuple[str, ...]] = []
        self.all_tool_spec_names: list[tuple[str, ...]] = []
        self.tool_spec_names: list[tuple[str, ...]] = []
        self.contexts: list[tuple[ChatMessage, ...]] = []
        self.request_limits: list[tuple[float, int]] = []

    async def respond(
        self,
        *,
        context: tuple,
        tool_specs: tuple[ToolSpec, ...],
        text_delta_callback=None,  # noqa: ANN001
        timeout_seconds=180.0,
        max_output_tokens=16_384,
    ) -> ModelTurn:
        messages = context.messages
        assert messages
        names = tuple(item.name for item in tool_specs)
        self.all_tool_spec_names.append(names)
        catalog = next((spec for spec in tool_specs if spec.name == "discover_research_tools"), None)
        next_turn = self.turns[0] if self.turns else None
        requested = self.discover or (
            tuple(call.name for call in next_turn.tool_calls)
            if isinstance(next_turn, ModelTurn) else ()
        )
        missing = tuple(name for name in requested if name not in names and catalog and f"- {name} [" in catalog.description)
        if missing:
            self.discover = ()
            self.discovery_decisions.append(missing)
            return ModelTurn(tool_calls=(ModelToolCall(name="discover_research_tools", arguments={"tool_names": list(missing), "source_inspection_required": self.source_inspection_required}),))
        self.contexts.append(messages)
        self.request_limits.append((timeout_seconds, max_output_tokens))
        self.tool_spec_names.append(tuple(name for name in names if name != "discover_research_tools"))
        turn = self.turns.popleft()
        if isinstance(turn, Exception):
            raise turn
        if text_delta_callback is not None and turn.content:
            for chunk in (turn.content[:2], turn.content[2:]):
                if chunk:
                    text_delta_callback(chunk)
        return turn


class _Capability:
    def __init__(
        self,
        name: str,
        risk: ToolRisk,
        input_model: type[BaseModel] = _NoArguments,
        *,
        fail_with: Exception | None = None,
        result_status: ToolResultStatus = ToolResultStatus.SUCCEEDED,
        result_data: dict[str, Any] | None = None,
        resource_refs: tuple[ChatResourceRef, ...] = (),
    ) -> None:
        self.spec = ToolSpec(
            name=name,
            description=f"Test capability {name}",
            risk=risk,
            input_model=input_model,
        )
        self.fail_with = fail_with
        self.result_status = result_status
        self.result_data = result_data
        self.resource_refs = resource_refs
        self.executed_arguments: list[dict[str, Any]] = []
        self.executed_call_ids: list[str] = []

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: BaseModel,
    ) -> ChatToolResult:
        assert context.user_id == "user-1"
        values = arguments.model_dump()
        self.executed_arguments.append(values)
        self.executed_call_ids.append(context.tool_call_id)
        if self.fail_with is not None:
            raise self.fail_with
        return ChatToolResult(
            tool_call_id="ignored-by-runner",
            status=self.result_status,
            data=(
                self.result_data
                if self.result_data is not None
                else {"arguments": values, "collection_id": context.collection_id}
            ),
            resource_refs=self.resource_refs or (
                (ChatResourceRef(resource_type="objective_analysis", resource_id="objective-1:1"),)
                if self.result_status is ToolResultStatus.QUEUED else ()
            ),
        )


def _context() -> AgentContext:
    return AgentContext(
        session_id="chat-1",
        user_id="user-1",
        collection_id="col-1",
    )


async def test_greeting_completes_without_calling_a_tool() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    model = _Model(ModelTurn(content="你好，我可以帮助你分析当前文献集合。"))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((capability,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="你好",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert [message.role for message in result.messages] == ["user", "assistant"]
    assert result.messages[-1].content.startswith("你好")
    assert result.tool_calls == ()
    assert capability.executed_arguments == []
    assert model.tool_spec_names == [()]


async def test_research_read_returns_to_the_same_agent_loop_without_nested_review() -> None:
    capability = _Capability(
        "read_source",
        ToolRisk.READ,
        result_data={
            "document_id": "paper-1",
            "source_ref": "results",
            "source_kind": "text_window",
            "source_digest": "digest-1",
            "content_truncated": False,
            "content": "The inspected results report improved elongation.",
        },
        resource_refs=(ChatResourceRef(resource_type="source", resource_id="paper-1:results"),),
    )
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("read_source", {}),)),
        ModelTurn(content="The inspected results report improved elongation."),
    )
    result = await ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((capability,)),
    ).run_turn(
        context=_context(),
        previous_messages=(),
        user_message="Read the source and summarize the result.",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert len(model.contexts) == 2
    assert capability.executed_arguments == [{}]
    assert all(item.status is ToolResultStatus.SUCCEEDED for item in result.tool_results)
    assert any(message.tool_result and message.tool_result.data.get("content") == capability.result_data["content"]
               for message in model.contexts[-1])
    assert result.messages[-1].content == "The inspected results report improved elongation."


async def test_validated_tool_arguments_are_reused_for_execution() -> None:
    _CountingArguments.validation_count = 0
    capability = _Capability(
        "custom_read",
        ToolRisk.READ,
        _CountingArguments,
    )
    result = await ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(
                    ModelToolCall(
                        name="custom_read",
                        arguments={"question": "read this Source"},
                    ),
                ),
            ),
            ModelTurn(content="The Source was inspected."),
        ),
        capabilities=CapabilityRegistry((capability,)),
    ).run_turn(
        context=_context(),
        previous_messages=(),
        user_message="Read this Source.",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert _CountingArguments.validation_count == 1
    assert capability.executed_arguments == [{"question": "read this Source"}]


async def test_new_sources_may_continue_beyond_six_model_decisions() -> None:
    read = _Capability("get_collection_context", ToolRisk.READ, _QuestionArguments)
    model = _Model(
        *(ModelTurn(tool_calls=(ModelToolCall(
            name=read.spec.name, arguments={"question": f"paper-{index}"}
        ),)) for index in range(7)),
        ModelTurn(content="Seven papers were checked."),
    )
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,))
    ).run_turn(context=_context(), previous_messages=(), user_message="Read seven papers.")
    assert result.status is AgentRunStatus.COMPLETED
    assert len(read.executed_arguments) == 7


async def test_default_limits_allow_long_investigation_with_reported_usage() -> None:
    read = _Capability("get_collection_context", ToolRisk.READ, _QuestionArguments)
    model = _Model(
        *(ModelTurn(tool_calls=(ModelToolCall(
            name=read.spec.name, arguments={"question": f"paper-{index}"},
        ),), usage=ModelUsage(10_000, 100, 10_100)) for index in range(70)),
        ModelTurn(content="The inspected comparisons are ready for review."),
    )
    traces = []
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,))).run_turn(
        context=_context(), previous_messages=(), user_message="Inspect the collection.",
        progress_callback=traces.append,
    )
    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER
    assert len(read.executed_arguments) == 70
    assert traces[-1]["total_tokens"] > 240_000
    assert traces[-1]["remaining_tool_budget"] is None
    assert traces[-1]["remaining_token_budget"] is None
    assert all(0 < timeout <= 180 and output == 16_384 for timeout, output in model.request_limits)


def test_source_coverage_uses_canonical_identity_and_marks_duplicate_batches():
    from application.chat.agent_runner import _RunProgress

    progress = _RunProgress(AgentRunLimits())
    call = ChatToolCall.requested(
        tool_call_id="call-1", session_id="chat-1", assistant_message_id="msg-1",
        position=0, name="inspect_document_sources", arguments={"document_id": "doc-1"},
        risk=ToolRisk.READ,
    )
    result = ChatToolResult(
        tool_call_id="call-1", status="succeeded",
        data={"document": {"document_id": "doc-1"}, "batch_token_budget": 16000, "sources": [{
            "source_kind": "text_window", "source_ref": "block-1", "source_digest": "digest-1",
            "content_truncated": False, "content": "Methods and results",
        }]},
        resource_refs=(ChatResourceRef("source", "doc-1:block-1"),),
    )

    assert progress.source_coverage(call, result) == {
        "complete_source_count": 1, "new_complete_source_count": 1,
        "already_complete_source_count": 0,
    }
    assert progress.observe(call, result) is True
    duplicate = replace(result, data={**result.data, "query": "same passage"})
    assert progress.source_coverage(call, duplicate) == {
        "complete_source_count": 1, "new_complete_source_count": 0,
        "already_complete_source_count": 1,
    }
    assert progress.observe(call, duplicate) is False
    paginated_duplicate = replace(
        result,
        data={**result.data, "offset": 8, "page": 2, "limit": 8, "next_offset": 16},
    )
    assert progress.observe(call, paginated_duplicate) is False
    budget_duplicate = replace(result, data={
        **result.data, "batch_token_budget": 10850,
        "source_coverage": progress.source_coverage(call, result),
    })
    assert progress.observe(call, budget_duplicate) is False
    revised_source = replace(budget_duplicate, data={
        **budget_duplicate.data, "sources": [{
            **result.data["sources"][0], "source_digest": "digest-2",
            "content": "Corrected Methods and results",
        }],
    })
    assert progress.observe(call, revised_source) is True
    assert progress.observe(call, revised_source) is False

    browse_call = replace(call, name="browse_collection_papers")
    browse_result = replace(
        result,
        data={"paper_total": 1, "papers": [{"document_id": "doc-1", "title": "Paper"}]},
        resource_refs=(ChatResourceRef("document", "doc-1"),),
    )
    assert progress.observe(browse_call, browse_result) is True
    assert progress.observe(
        browse_call,
        replace(browse_result, data={**browse_result.data, "query": "same paper", "offset": 1}),
    ) is False


async def test_changing_read_budgets_cannot_keep_duplicate_investigation_running() -> None:
    class SourceRead(_Capability):
        async def execute(self, context, arguments):
            result = await super().execute(context, arguments)
            budget = (9861, 14135, 14992)[len(self.executed_arguments) - 1]
            return replace(result, data={**result.data, "batch_token_budget": budget})

    read = SourceRead(
        "inspect_document_sources", ToolRisk.READ,
        result_data={"document": {"document_id": "doc-1"}, "sources": [{
            "source_kind": "text_window", "source_ref": "tensile-results",
            "source_digest": "digest-1", "content_truncated": False,
            "content": "Elongation varies with the annealing condition and comparator.",
        }]},
        resource_refs=(ChatResourceRef("source", "doc-1:tensile-results"),),
    )
    model = _Model(
        *(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),)) for _ in range(3)),
        ModelTurn(content="The same results were inspected; the correction remains incomplete."),
    )
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,)),
    ).run_turn(
        context=_context(), previous_messages=(),
        user_message="Recheck the annealing results before correcting the comparison. Do not save.",
    )

    assert result.completion_reason is AgentCompletionReason.NO_PROGRESS
    assert len(read.executed_arguments) == 3
    reads = [item for item in result.tool_results if "source_coverage" in item.data]
    assert [item.data["source_coverage"]["new_complete_source_count"] for item in reads] == [1, 0, 0]
    assert "work remains incomplete" in model.contexts[-1][-1].content
    assert not any(call.risk is ToolRisk.WRITE for call in result.tool_calls)


@pytest.mark.parametrize("failed", [False, True])
async def test_identical_observations_finalize_without_losing_results(failed: bool) -> None:
    read = _Capability("get_collection_context", ToolRisk.READ,
                       fail_with=RuntimeError("unavailable") if failed else None)
    model = _Model(*(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),)) for _ in range(3)),
                   ModelTurn(content="Only the inspected scope can be discussed."))
    result = await ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((read,)),
    ).run_turn(context=_context(), previous_messages=(), user_message="Read collection papers.")
    assert result.completion_reason is AgentCompletionReason.NO_PROGRESS
    assert len(result.tool_results) == 4
    assert len(read.executed_arguments) == 3
    assert result.warnings
    assert "work remains incomplete" in model.contexts[-1][-1].content
    assert "action is complete" not in model.contexts[-1][-1].content


async def test_usage_exhaustion_records_unexecuted_intent_then_finalizes() -> None:
    read = _Capability("get_collection_context", ToolRisk.READ)
    result = await ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),), usage=ModelUsage(80, 20, 100)),
                     ModelTurn(content="The paper remains unread.")),
        capabilities=CapabilityRegistry((read,)), limits=AgentRunLimits(max_model_tokens=100),
    ).run_turn(context=_context(), previous_messages=(), user_message="Read collection papers.")
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert read.executed_arguments == []
    assert result.tool_results[-1].error_code == "resource_budget"


async def test_provider_retries_are_visible_in_progress_trace() -> None:
    traces = []
    result = await ResearchAgentRunner(
        model=_Model(
            ModelResponseError("empty", reason="empty_response", retryable=True),
            ModelResponseError("empty", reason="empty_response", retryable=True),
            ModelTurn(content="The inspected scope is reported."),
        ),
        capabilities=CapabilityRegistry(()),
    ).run_turn(
        context=_context(), previous_messages=(),
        user_message="Summarize the inspected scope.", progress_callback=traces.append,
    )
    retries = [item for item in traces if item["phase"] == "model_retry"]
    assert result.status is AgentRunStatus.COMPLETED
    assert [item["retry_attempt"] for item in retries] == [1, 2]
    assert all(item["retry_reason"] == "empty_response" for item in retries)


@pytest.mark.parametrize("tokens", [100, 120])
async def test_usage_exhaustion_preserves_final_text_without_another_request(tokens: int) -> None:
    model = _Model(ModelTurn(content="Only the first paper was inspected.",
                             usage=ModelUsage(80, tokens - 80, tokens)))
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry(()),
        limits=AgentRunLimits(max_model_tokens=100),
    ).run_turn(context=_context(), previous_messages=(), user_message="Summarize the inspected scope.")

    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert result.messages[-1].content == "Only the first paper was inspected."
    assert result.warnings
    assert len(model.contexts) == 1


async def test_query_rewording_without_new_observations_reaches_no_progress() -> None:
    class SourceRead(_Capability):
        async def execute(self, context, arguments):
            result = await super().execute(context, arguments)
            return replace(result, resource_refs=(ChatResourceRef("source", "doc-1:methods-1"),))

    read = SourceRead("test_source", ToolRisk.READ, _QuestionArguments,
                      result_data={"source_ref": "methods-1", "text": "LPBF Ti-6Al-4V."})
    model = _Model(
        *(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name, arguments={"question": query}),))
          for query in ("alloy", "material", "composition")),
        ModelTurn(content="The same Methods passage was inspected; results remain unread."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,))).run_turn(
        context=_context(), previous_messages=(), user_message="Compare the two papers' alloy conditions.",
    )

    assert result.completion_reason is AgentCompletionReason.NO_PROGRESS
    assert len(result.tool_results) == 3
    assert result.warnings


async def test_distinct_empty_searches_do_not_collapse_into_repeated_source_reads() -> None:
    read = _Capability("test_source", ToolRisk.READ, _QuestionArguments, result_data={"matches": []})
    model = _Model(
        *(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name, arguments={"question": query}),))
          for query in ("annealing", "stress relief", "HIP")),
        ModelTurn(content="These searches found no prepared Source; this is not scientific absence."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,))).run_turn(
        context=_context(), previous_messages=(), user_message="Inspect the papers' post-processing conditions.",
    )
    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER


async def test_new_source_pages_and_revised_source_content_remain_progress() -> None:
    class SourceRead(_Capability):
        async def execute(self, context, arguments):
            result = await super().execute(context, arguments)
            return replace(result, data={"source_ref": "methods-1", "text": arguments.question})

    read = SourceRead("test_source", ToolRisk.READ, _QuestionArguments)
    model = _Model(
        *(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name, arguments={"question": page}),))
          for page in ("LPBF Ti-6Al-4V", "Annealed at 800 C", "Corrected: annealed at 900 C")),
        ModelTurn(content="The corrected heat treatment was inspected."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,))).run_turn(
        context=_context(), previous_messages=(), user_message="Compare heat treatments.",
    )
    assert result.completion_reason is AgentCompletionReason.MODEL_ANSWER
    assert len(result.tool_results) == 3


async def test_timed_out_model_is_cancelled_without_starting_finalization() -> None:
    cancelled = asyncio.Event()

    class SlowModel:
        calls = 0

        async def respond(self, *, context, tool_specs, text_delta_callback=None,
                          timeout_seconds=180.0, max_output_tokens=16_384):
            self.calls += 1
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    model = SlowModel()
    deltas = []
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry(()),
        limits=AgentRunLimits(max_elapsed_seconds=0.2),
    ).run_turn(context=_context(), previous_messages=(), user_message="Hello",
               text_delta_callback=deltas.append)

    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "provider_timeout"
    assert model.calls == 1
    assert cancelled.is_set()
    assert deltas == []


async def test_transient_provider_timeout_is_retried_up_to_success() -> None:
    model = _Model(
        TimeoutError("provider request timed out"),
        ModelTurn(content="The provider recovered and returned the answer."),
    )

    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry(()),
    ).run_turn(context=_context(), previous_messages=(), user_message="Hello")

    assert result.status is AgentRunStatus.COMPLETED
    assert result.messages[-1].content == "The provider recovered and returned the answer."
    assert len(model.request_limits) == 2


@pytest.mark.parametrize("status,retryable", [(408, True), (429, True), (503, True), (401, False), (403, False), (400, False), (None, False)])
def test_generic_provider_errors_use_structured_status(status, retryable):
    class APIError(Exception):
        status_code = status

    details = agent_runner_module._provider_failure_details(APIError("private provider request"))
    assert details["retryable"] is retryable
    assert details["http_status"] == status
    assert "private provider request" not in json.dumps(details)


def test_provider_error_cause_and_permanent_quota_are_distinguished():
    import httpx

    class APIError(Exception):
        status_code = None

    error = APIError("private response")
    error.__cause__ = httpx.RemoteProtocolError("private connection")
    assert agent_runner_module._provider_failure_details(error)["retryable"]
    error.status_code = 429
    error.body = {"error": {"code": "insufficient_quota", "message": "private account"}}
    details = agent_runner_module._provider_failure_details(error)
    assert not details["retryable"]
    assert details["reason"] == "quota_exhausted"


@pytest.mark.parametrize("body,retryable", [
    ({"code": "internal_server_error"}, True),
    ({"type": "server_error"}, True),
    ({"error": {"code": "rate_limit_exceeded"}}, True),
    ({"code": "insufficient_quota", "type": "server_error"}, False),
    ({"code": "invalid_api_key"}, False),
    ({"code": ["malformed"]}, False),
    ({"message": "unknown provider error"}, False),
])
def test_stream_api_error_uses_known_structured_codes_without_status(body, retryable):
    import httpx
    from openai import APIError

    error = APIError("private stream response", request=httpx.Request("POST", "https://example.test"), body=body)
    details = agent_runner_module._provider_failure_details(error)
    assert details["retryable"] is retryable
    assert details["http_status"] is None
    assert "private stream response" not in json.dumps(details)


async def test_generic_provider_failure_recovers_after_five_retries_without_repeating_read(monkeypatch, caplog):
    class APIError(Exception):
        status_code = 503

    delays = []

    async def wait(delay):
        delays.append(delay)

    monkeypatch.setattr(agent_runner_module, "sleep", wait)
    read = _Capability("test_source", ToolRisk.READ, result_data={"content": "Known paper result"})
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("test_source", {}),)),
        *(APIError("private request and credential") for _ in range(5)),
        ModelTurn(content="The inspected paper result is retained."),
    )
    events = []
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,))).run_turn(
        context=_context(), previous_messages=(), user_message="Read the paper and explain the result.",
        progress_callback=events.append,
    )
    assert result.status is AgentRunStatus.COMPLETED
    assert len(read.executed_arguments) == 1
    retries = [event for event in events if event["phase"] == "model_retry"]
    assert [event["retry_attempt"] for event in retries] == [1, 2, 3, 4, 5]
    assert all(event["http_status"] == 503 for event in retries)
    assert len(delays) == 5 and all(left < right for left, right in zip(delays, delays[1:]))
    assert "private request and credential" not in caplog.text
    assert "private request and credential" not in json.dumps(events)


async def test_retryable_api_error_stops_after_initial_attempt_and_five_retries(monkeypatch):
    import httpx
    from openai import APIError

    async def wait(delay):
        pass

    monkeypatch.setattr(agent_runner_module, "sleep", wait)
    error = APIError("private response", request=httpx.Request("POST", "https://example.test"),
                     body={"type": "server_error"})
    model = _Model(*(error for _ in range(7)))
    events = []
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(())).run_turn(
        context=_context(), previous_messages=(), user_message="Hello", progress_callback=events.append,
    )
    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "model_unavailable"
    assert len(model.request_limits) == 6
    assert len([event for event in events if event["phase"] == "model_retry"]) == 5
    assert events[-1]["retry_reason"] == "transient_provider_error"


async def test_finalization_uses_remaining_time_and_its_own_output_limit(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr(agent_runner_module, "monotonic", lambda: now[0])
    read = _Capability("test_source", ToolRisk.READ)

    class Model(_Model):
        async def respond(self, **kwargs):
            turn = await super().respond(**kwargs)
            now[0] = 45.0
            return turn

    model = Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),)),
                  ModelTurn(content="Only inspected sources support this answer."))
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,)),
        limits=AgentRunLimits(max_elapsed_seconds=60, max_tool_calls=1,
                             max_finalization_output_tokens=500),
    ).run_turn(context=_context(), previous_messages=(), user_message="Compare the two papers.")

    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert model.request_limits[-1] == (15.0, 500)


async def test_finalization_timeout_cancels_the_only_summary_request() -> None:
    read = _Capability("test_source", ToolRisk.READ)
    cancelled = asyncio.Event()

    class Model(_Model):
        async def respond(self, **kwargs):
            if self.contexts:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await super().respond(**kwargs)

    model = Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),)))
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,)),
        limits=AgentRunLimits(max_tool_calls=1, max_finalization_seconds=0.02),
    ).run_turn(context=_context(), previous_messages=(), user_message="Compare the two papers.")

    assert result.error_code == "final_answer_unavailable"
    assert cancelled.is_set()
    assert result.tool_results[0].status is ToolResultStatus.SUCCEEDED


async def test_read_deadline_preserves_successes_without_starting_a_summary() -> None:
    cancelled = asyncio.Event()

    class SourceRead(_Capability):
        async def execute(self, context, arguments):
            if arguments.question == "paper-b":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await super().execute(context, arguments)

    read = SourceRead("test_source", ToolRisk.READ, _QuestionArguments)
    model = _Model(ModelTurn(tool_calls=tuple(
        ModelToolCall(name=read.spec.name, arguments={"question": paper}) for paper in ("paper-a", "paper-b")
    )))
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,)),
        limits=AgentRunLimits(max_elapsed_seconds=0.02),
    ).run_turn(context=_context(), previous_messages=(), user_message="Compare the two papers.")

    assert result.error_code == "final_answer_unavailable"
    assert cancelled.is_set()
    assert len(model.contexts) == 1
    assert result.tool_results[0].status is ToolResultStatus.SUCCEEDED
    assert result.tool_results[1].error_code == "capability_timeout"


async def test_invalid_response_usage_reduces_the_retry_output_allowance() -> None:
    model = _Model(
        ModelResponseError("empty", reason="empty_response", usage=ModelUsage(20, 10, 30)),
        ModelTurn(content="The comparison remains unresolved.", usage=ModelUsage(40, 30, 70)),
    )
    result = await ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry(()), limits=AgentRunLimits(max_model_tokens=100),
    ).run_turn(context=_context(), previous_messages=(), user_message="Summarize what is known.")

    assert [limit for _, limit in model.request_limits] == [100, 70]
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET


async def test_retries_count_toward_emergency_ceiling_and_finalization_can_fail() -> None:
    result = await ResearchAgentRunner(
        model=_Model(ModelResponseError("empty", reason="empty_response"), RuntimeError("offline")),
        capabilities=CapabilityRegistry(()), limits=AgentRunLimits(emergency_max_model_cycles=1),
    ).run_turn(context=_context(), previous_messages=(), user_message="Hello")
    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "final_answer_unavailable"


@pytest.mark.parametrize("parallel, limit, expected_peak", [(False, 4, 1), (True, 4, 2), (True, 1, 1)])
async def test_read_batch_preserves_intent_order_and_partial_failure(
    parallel: bool, limit: int, expected_peak: int,
) -> None:
    active = peak = 0
    class Read(_Capability):
        async def execute(self, context, arguments):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02 if arguments.question == "paper-1" else 0.001)
            active -= 1
            if arguments.question == "paper-2":
                raise RuntimeError("Source unavailable")
            return await super().execute(context, arguments)
    read = Read("test_source", ToolRisk.READ, _QuestionArguments)
    read.spec = replace(read.spec, parallel_safe=parallel)
    checkpoints = []
    async def checkpoint(messages, calls, results):
        checkpoints.append((messages, calls, results))
    model = _Model(ModelTurn(tool_calls=tuple(ModelToolCall(name=read.spec.name, arguments={"question": f"paper-{i}"}) for i in (1, 2))),
                   ModelTurn(content="Paper 1 was inspected; paper 2 could not be read."))
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,)),
                                      limits=AgentRunLimits(max_parallel_reads=limit)).run_turn(
        context=_context(), previous_messages=(), user_message="Compare the two papers.", checkpoint=checkpoint)
    assert peak == expected_peak
    assert [call.position for call in result.tool_calls] == [0, 1]
    assert [item.status for item in result.tool_results] == [ToolResultStatus.SUCCEEDED, ToolResultStatus.FAILED]
    assert tuple(request.tool_call_id for request in result.messages[1].tool_calls) == tuple(item.tool_call_id for item in result.tool_results)
    assert any(len(calls) == 2 and all(call.status is ToolCallStatus.REQUESTED for call in calls) and not results
               for _, calls, results in checkpoints)


async def test_tool_response_deduplicates_and_bounds_one_model_batch() -> None:
    read = _Capability("test_read", ToolRisk.READ, _QuestionArguments)
    requested = tuple(
        ModelToolCall(name=read.spec.name, arguments={"question": f"paper-{index}"})
        for index in range(40)
        for _ in range(2)
    )
    result = await ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=requested), ModelTurn(content="The bounded batch was inspected.")),
        capabilities=CapabilityRegistry((read,)),
    ).run_turn(context=_context(), previous_messages=(), user_message="Inspect the collection.")

    assert result.status is AgentRunStatus.COMPLETED
    assert len(read.executed_arguments) == 32
    assert len(result.tool_results) == 32
    assert len({item["question"] for item in read.executed_arguments}) == 32
    assert [call.position for call in result.tool_calls] == list(range(32))
    assert [call.tool_call_id for call in result.tool_calls] == [
        item.tool_call_id for item in result.tool_results
    ]


@pytest.mark.parametrize("risk", [ToolRisk.DRAFT, ToolRisk.WRITE])
async def test_mixed_batches_have_no_side_effects(risk: ToolRisk) -> None:
    read = _Capability("test_read", ToolRisk.READ)
    action = _Capability("test_action", risk)
    result = await ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name), ModelToolCall(name=action.spec.name))),
                     ModelTurn(content="The requested actions were not executed.")),
        capabilities=CapabilityRegistry((read, action)),
    ).run_turn(context=_context(), previous_messages=(), user_message="Read and save.")
    assert read.executed_arguments == action.executed_arguments == []
    assert len(result.tool_results) == 2
    assert all(item.error_code == "invalid_tool_batch" for item in result.tool_results)


async def test_insufficient_batch_budget_deduplicates_repeated_call() -> None:
    read = _Capability("test_read", ToolRisk.READ)
    result = await ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),) * 2),
                     ModelTurn(content="Both papers remain unread.")),
        capabilities=CapabilityRegistry((read,)), limits=AgentRunLimits(max_tool_calls=1),
    ).run_turn(context=_context(), previous_messages=(), user_message="Compare two papers.")
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert len(result.tool_results) == 1
    assert read.executed_arguments == [{}]


async def test_unknown_batch_member_prevents_every_read_from_executing() -> None:
    read = _Capability("test_read", ToolRisk.READ)
    result = await ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name), ModelToolCall(name="not_registered"))),
                     ModelTurn(content="Neither read was executed.")),
        capabilities=CapabilityRegistry((read,)),
    ).run_turn(context=_context(), previous_messages=(), user_message="Compare two papers.")

    assert read.executed_arguments == []
    assert len(result.tool_results) == 2
    assert all(item.status is ToolResultStatus.FAILED for item in result.tool_results)


async def test_general_science_discussion_receives_no_capabilities() -> None:
    model = _Model(
        ModelTurn(
            content=(
                "过高能量输入可能提高熔池稳定性和致密化程度，也可能因蒸发、"
                "钥孔不稳定或残余应力引入新的缺陷；这是一般机理解释。"
            )
        )
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (
                _Capability("get_collection_context", ToolRisk.READ),
                _Capability("search_sources", ToolRisk.READ, _QuestionArguments),
                _Capability("create_objective_candidate", ToolRisk.WRITE),
            )
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="为什么 LPBF 中过高能量输入可能同时带来致密化和新的缺陷？先说你的理解，不用查论文。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [()]
    assert result.tool_calls == ()


async def test_correction_request_that_says_do_not_publish_exposes_reads_but_no_writes() -> None:
    model = _Model(ModelTurn(content="我会先回到原始来源核对 HIP 条件。"),
                   discover=("browse_collection_papers", "search_sources", "read_source"))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (
                _Capability("get_collection_context", ToolRisk.READ),
                _Capability("browse_collection_papers", ToolRisk.READ),
                _Capability("search_sources", ToolRisk.READ, _QuestionArguments),
                _Capability("read_source", ToolRisk.READ),
                _Capability("query_published_findings", ToolRisk.READ),
                _Capability("inspect_published_finding", ToolRisk.READ),
                _Capability("inspect_research_process", ToolRisk.READ),
                _Capability("inspect_objective_analysis", ToolRisk.READ),
                _Capability("create_finding_draft", ToolRisk.DRAFT),
                _Capability("create_finding_version", ToolRisk.WRITE),
                _Capability("record_finding_feedback", ToolRisk.WRITE),
                _Capability("curate_finding", ToolRisk.WRITE),
            )
        ),
    )

    await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=(
            "你把第二篇论文的热处理状态看错了，它实际是 HIP。"
            "请重新核对并修订比较结论，先不要发布。"
        ),
    )

    exposed = set(model.tool_spec_names[0])
    assert {"browse_collection_papers", "search_sources", "read_source"}.issubset(
        exposed
    )
    assert exposed.isdisjoint(
        {
            "inspect_research_process",
            "inspect_objective_analysis",
            "create_finding_version",
            "record_finding_feedback",
            "curate_finding",
        }
    )


async def test_literature_screening_receives_only_collection_read_capabilities() -> None:
    model = _Model(ModelTurn(content="我会先根据论文概览形成临时阅读清单。"),
                   discover=("get_collection_context", "browse_collection_papers"))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (
                _Capability("get_collection_context", ToolRisk.READ),
                _Capability("browse_collection_papers", ToolRisk.READ),
                _Capability("search_sources", ToolRisk.READ, _QuestionArguments),
                _Capability("inspect_document_sources", ToolRisk.READ),
                _Capability("read_source", ToolRisk.READ),
                _Capability("inspect_table", ToolRisk.READ),
                _Capability("create_objective_candidate", ToolRisk.WRITE),
                _Capability("create_finding_version", ToolRisk.WRITE),
            )
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="哪些论文适合研究能量输入对孔隙率的影响？先看看标题和摘要。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [
        (
            "get_collection_context",
            "browse_collection_papers",
        )
    ]


async def test_literature_based_opinion_exposes_source_reading_capabilities() -> None:
    browse = _Capability(
        "browse_collection_papers",
        ToolRisk.READ,
        result_data={
            "paper_total": 2,
            "returned_paper_count": 2,
            "next_offset": None,
            "papers": [{"document_id": "paper-1"}, {"document_id": "paper-2"}],
        },
    )
    search = _Capability(
        "search_sources",
        ToolRisk.READ,
        _QuestionArguments,
        result_data={
            "match_total": 1,
            "matches": [
                {
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                }
            ],
        },
    )
    read = _Capability(
        "read_source",
        ToolRisk.READ,
        _QuestionArguments,
        result_data={
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "content_truncated": False,
            "source_digest": "a" * 64,
        },
    )
    model = _Model(
        ModelTurn(content="孔隙率可能随能量输入降低。"),
        ModelTurn(
            tool_calls=(ModelToolCall(name="browse_collection_papers", arguments={}),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="search_sources",
                arguments={"question": "孔隙率"},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="read_source",
                arguments={"question": "results-1"},
            ),)
        ),
        ModelTurn(content="已读取结果原文；目前只能对第一篇论文形成有依据的初步判断。"),
        discover=("browse_collection_papers",),
        source_inspection_required=True,
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (
                _Capability("get_collection_context", ToolRisk.READ),
                browse,
                search,
                read,
            )
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="根据这些论文中关于孔隙率的内容，说说你的判断并提出思路。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert [call.name for call in result.tool_calls] == [
        "discover_research_tools",
        "browse_collection_papers",
        "search_sources",
        "read_source",
    ]
    assert model.tool_spec_names[:4] == [
        ("browse_collection_papers",),
        ("browse_collection_papers",),
        ("search_sources",),
        ("read_source",),
    ]

    explicit_search = intent_policy.capability_names_for_intent(
        "请搜索相关论文然后谈谈判断。",
        has_source_context=False,
        prior_tool_names=set(),
    )
    assert "search_sources" in explicit_search


async def test_literature_based_opinion_fails_if_required_read_is_refused() -> None:
    unsupported_answer = "不读取原文也可以判断能量输入降低了孔隙率。"
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(content=unsupported_answer),
            ModelTurn(content=unsupported_answer),
            discover=("browse_collection_papers",),
        ),
        capabilities=CapabilityRegistry(
            (_Capability("browse_collection_papers", ToolRisk.READ),)
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="根据这些论文谈谈能量输入对孔隙率的影响。",
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "required_research_action_not_completed"
    assert result.messages[-1].content != unsupported_answer
    assert "不能据此判断论文没有证据" in result.messages[-1].content


async def test_evidence_write_requires_a_complete_matching_source_read() -> None:
    read = _Capability(
        "read_source",
        ToolRisk.READ,
        _NoArguments,
        result_data={
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "content_truncated": True,
            "source_digest": "a" * 64,
        },
    )
    write = _Capability("create_evidence_version", ToolRisk.WRITE, _NoArguments)
    model = _Model(
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    name="read_source",
                    arguments={},
                ),
            )
        ),
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    name="create_evidence_version",
                    arguments={},
                ),
            )
        ),
        ModelTurn(content="The source must be read completely before recording Evidence."),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((read, write)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="Read the source and save the Evidence.",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert write.executed_arguments == []
    assert result.tool_results[-1].error_code == "source_read_incomplete"


async def test_continuation_does_not_restore_finding_draft_capabilities() -> None:
    allowed = intent_policy.capability_names_for_intent(
        "继续看一下",
        has_source_context=False,
        prior_tool_names={"query_published_findings"},
    )

    assert "query_published_findings" in allowed
    assert "inspect_published_finding" in allowed
    assert "create_finding_draft" not in allowed
    assert "create_evidence_draft" not in allowed
    assert "derive_objective" not in allowed


async def test_standalone_status_query_does_not_expose_paper_browsing() -> None:
    allowed = intent_policy.capability_names_for_intent(
        "查看当前状态",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "inspect_research_process" in allowed
    assert "get_collection_context" in allowed
    assert "browse_collection_papers" not in allowed


async def test_research_plan_question_does_not_expose_finding_writes() -> None:
    model = _Model(ModelTurn(content="我会先根据现有证据拟定研究方案草案。"),
                   discover=("propose_research_plan",))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            tuple(
                _Capability(
                    name,
                    ToolRisk.READ
                    if name not in intent_policy.WRITE_CAPABILITIES
                    else ToolRisk.WRITE,
                )
                for name in (
                    "get_collection_context",
                    "browse_collection_papers",
                    "query_published_findings",
                    "inspect_published_finding",
                    "inspect_objective_analysis",
                    "assess_objective_quality",
                    "propose_research_plan",
                    "create_research_plan",
                    "create_finding_version",
                    "record_finding_feedback",
                    "curate_finding",
                )
            )
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="目前最大的证据缺口是什么？请提出一个研究方案草案，不要保存。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [
        (
            "get_collection_context",
            "query_published_findings",
            "assess_objective_quality",
        )
    ]


async def test_finding_review_does_not_expose_mutation_capabilities_without_save_request() -> None:
    model = _Model(ModelTurn(content="我会先核对结论、证据和适用边界。"),
                   discover=("get_collection_context", "query_published_findings",
                             "inspect_published_finding", "inspect_objective_analysis",
                             "assess_objective_quality"))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            tuple(
                _Capability(
                    name,
                    ToolRisk.WRITE
                    if name
                    in {
                        "record_finding_feedback",
                        "curate_finding",
                        "create_finding_version",
                    }
                    else ToolRisk.READ,
                )
                for name in (
                    "get_collection_context",
                    "browse_collection_papers",
                    "query_published_findings",
                    "inspect_published_finding",
                    "inspect_objective_analysis",
                    "assess_objective_quality",
                    "record_finding_feedback",
                    "curate_finding",
                    "create_finding_version",
                )
            )
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="查看已经发布的研究结论，解释它的依据和适用边界；先给我审阅意见，不要直接修改。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [
        (
            "get_collection_context",
            "query_published_findings",
            "inspect_published_finding",
            "inspect_objective_analysis",
            "assess_objective_quality",
        )
    ]


async def test_objective_status_question_does_not_expose_derivation() -> None:
    model = _Model(ModelTurn(content="我会先查看现有研究目标和分析状态。"),
                   discover=("get_collection_context", "inspect_research_process",
                             "inspect_objective_analysis"))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            tuple(
                _Capability(name, ToolRisk.READ)
                for name in (
                    "get_collection_context",
                    "browse_collection_papers",
                    "propose_objective_drafts",
                    "preview_research_scope",
                    "derive_objective",
                    "inspect_research_process",
                    "inspect_objective_analysis",
                )
            )
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="当前 collection 中已有研究目标和分析进度吗？请查看状态。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [
        (
            "get_collection_context",
            "inspect_research_process",
            "inspect_objective_analysis",
        )
    ]


async def test_status_question_retries_a_premature_answer_before_each_required_read() -> None:
    collection_context = _Capability(
        "get_collection_context",
        ToolRisk.READ,
        result_data={
            "objectives": [
                {
                    "objective_id": "objective-1",
                    "confirmation_status": "confirmed",
                }
            ]
        },
    )
    process = _Capability("inspect_research_process", ToolRisk.READ)
    analysis = _Capability(
        "inspect_objective_analysis",
        ToolRisk.READ,
        _ObjectiveArguments,
    )
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="get_collection_context",
                arguments={},
            ),)
        ),
        ModelTurn(content="我已经看到了 collection 的状态。"),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_research_process",
                arguments={},
            ),)
        ),
        ModelTurn(content="我已经看到了研究流程的状态。"),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_objective_analysis",
                arguments={"objective_id": "objective-1"},
            ),)
        ),
        ModelTurn(content="现在可以完整说明研究目标和分析进度了。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((collection_context, process, analysis)),
        limits=AgentRunLimits(max_tool_calls=6),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="当前 collection 中已有研究目标和分析进度吗？请查看状态。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert [call.name for call in result.tool_calls] == [
        "discover_research_tools",
        "get_collection_context",
        "inspect_research_process",
        "inspect_objective_analysis",
    ]
    assert process.executed_arguments == [{}]
    assert analysis.executed_arguments == [{"objective_id": "objective-1"}]
    assert model.tool_spec_names.count(("inspect_research_process",)) == 2
    assert model.tool_spec_names.count(("inspect_objective_analysis",)) == 2


async def test_filename_follow_up_keeps_paper_reads_without_exposing_writes() -> None:
    browser = _Capability("browse_collection_papers", ToolRisk.READ)
    search = _Capability("search_sources", ToolRisk.READ, _QuestionArguments)
    writer = _Capability("create_objective_candidate", ToolRisk.WRITE, _QuestionArguments)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="browse_collection_papers", arguments={}),)),
        ModelTurn(content="我先列出了三篇优先阅读的论文。"),
        ModelTurn(content="已把文件名含 residual-stress 的论文加入临时阅读清单。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((browser, search, writer)),
    )

    first = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="哪些论文适合研究孔隙率？",
    )
    second = await runner.run_turn(
        context=_context(),
        previous_messages=first.messages,
        user_message="把文件名里有 residual-stress 的那篇也一起看。",
    )

    assert second.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [
        ("browse_collection_papers",),
        ("browse_collection_papers",),
        (),
    ]
    assert model.all_tool_spec_names[-1] == ("discover_research_tools",)
    assert all("create_objective_candidate" not in names for names in model.tool_spec_names)


async def test_objective_write_is_hidden_until_the_user_requests_persistence() -> None:
    draft_model = _Model(ModelTurn(content="我可以先形成三个可审阅的问题草案。"),
                         discover=("get_collection_context", "browse_collection_papers",
                                   "preview_research_scope", "propose_objective_drafts"))
    capabilities = CapabilityRegistry(
        (
            _Capability("get_collection_context", ToolRisk.READ),
            _Capability("browse_collection_papers", ToolRisk.READ),
            _Capability("preview_research_scope", ToolRisk.READ),
            _Capability("propose_objective_drafts", ToolRisk.DRAFT, _QuestionArguments),
            _Capability("create_objective_candidate", ToolRisk.WRITE, _QuestionArguments),
            _Capability("confirm_objective", ToolRisk.WRITE),
            _Capability("start_objective_analysis", ToolRisk.WRITE),
        )
    )
    draft_runner = ResearchAgentRunner(model=draft_model, capabilities=capabilities)

    await draft_runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="帮我想几个关于能量输入和延性的研究目标。",
    )

    assert draft_model.tool_spec_names == [
        (
            "get_collection_context",
            "browse_collection_papers",
            "preview_research_scope",
            "propose_objective_drafts",
        )
    ]

    save_model = _Model(ModelTurn(content="我会准备保存这个候选目标。"))
    save_runner = ResearchAgentRunner(model=save_model, capabilities=capabilities)
    await save_runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="保存这个研究目标候选。",
    )

    assert "create_objective_candidate" in save_model.tool_spec_names[0]
    assert "confirm_objective" not in save_model.tool_spec_names[0]
    assert "start_objective_analysis" not in save_model.tool_spec_names[0]


async def test_candidate_creation_with_explicit_stop_hides_confirmation_and_analysis() -> None:
    model = _Model(ModelTurn(content="我只会准备候选目标的创建动作。"))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (
                _Capability("get_collection_context", ToolRisk.READ),
                _Capability("propose_objective_drafts", ToolRisk.DRAFT),
                _Capability(
                    "create_objective_candidate",
                    ToolRisk.WRITE,
                    _QuestionArguments,
                ),
                _Capability("confirm_objective", ToolRisk.WRITE),
                _Capability("start_objective_analysis", ToolRisk.WRITE),
            )
        ),
    )

    await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=(
            "这个研究目标草案可以。请创建成研究目标候选，"
            "但先不要确认，也不要启动分析。"
        ),
    )

    exposed = set(model.tool_spec_names[0])
    assert "create_objective_candidate" in exposed
    assert "confirm_objective" not in exposed
    assert "start_objective_analysis" not in exposed


async def test_model_cannot_execute_a_registered_capability_hidden_for_this_turn() -> None:
    writer = _Capability("create_objective_candidate", ToolRisk.WRITE, _QuestionArguments)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="create_objective_candidate",
                arguments={"question": "How does energy input affect porosity?"},
            ),)
        ),
        ModelTurn(content="这只是一般讨论，我不会创建记录。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((writer,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="一般来说，怎样把一个宽泛兴趣收窄成研究问题？不用操作当前文献。",
    )

    assert model.tool_spec_names == [(), ()]
    assert writer.executed_arguments == []
    assert result.tool_results[0].error_code == "capability_unavailable_for_turn"


async def test_runner_forwards_model_text_deltas_before_returning_the_turn() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(ModelTurn(content="逐段回复")),
        capabilities=CapabilityRegistry((capability,)),
    )
    deltas: list[str] = []

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="你好",
        text_delta_callback=deltas.append,
    )

    assert deltas == ["逐段", "回复"]
    assert result.messages[-1].content == "逐段回复"


async def test_read_capability_result_returns_to_the_model_before_final_answer() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),)
            ),
            ModelTurn(content="这批论文主要研究增材制造参数和力学性能。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="这些论文主要研究什么？",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result.tool_calls[1].status is ToolCallStatus.SUCCEEDED
    assert result.tool_results[1].data["collection_id"] == "col-1"
    assert capability.executed_arguments == [{}]
    assert capability.executed_call_ids == [result.tool_calls[1].tool_call_id]
    assert result.tool_results[1].tool_call_id == result.tool_calls[1].tool_call_id


async def test_each_model_tool_decision_gets_a_unique_lens_call_identity() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),)
            ),
            ModelTurn(content="第一轮读取完成。"),
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),)
            ),
            ModelTurn(content="第二轮读取完成。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    first = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="读取当前 collection",
    )
    second = await runner.run_turn(
        context=_context(),
        previous_messages=first.messages,
        user_message="再读取一次",
    )

    call_ids = [first.tool_calls[-1].tool_call_id, second.tool_calls[-1].tool_call_id]
    assert call_ids[0] != call_ids[1]
    assert all(call_id.startswith("call_") for call_id in call_ids)
    assert capability.executed_call_ids == call_ids


async def test_authorization_is_deterministic_and_not_granted_by_prompt_text() -> None:
    assert not evaluate_authorization(ToolRisk.READ).requires_approval
    assert not evaluate_authorization(ToolRisk.DRAFT).requires_approval
    assert evaluate_authorization(ToolRisk.WRITE).requires_approval
    assert not evaluate_authorization(ToolRisk.WRITE).may_execute


async def test_draft_capability_executes_without_write_approval() -> None:
    capability = _Capability(
        "propose_objective_drafts",
        ToolRisk.DRAFT,
        _QuestionArguments,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="propose_objective_drafts",
                    arguments={"question": "energy input and ductility"},
                ),)
            ),
            ModelTurn(content="我整理了一个临时目标草稿。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="帮我整理成研究目标",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[-1].risk is ToolRisk.DRAFT
    assert capability.executed_arguments == [
        {"question": "energy input and ductility"}
    ]


async def test_write_capability_stops_for_approval_without_execution() -> None:
    capability = _Capability(
        "create_objective_candidate",
        ToolRisk.WRITE,
        _QuestionArguments,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                content="我准备保存这个候选目标。",
                tool_calls=(ModelToolCall(
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                ),),
            )
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="保存这个目标",
    )

    assert result.status is AgentRunStatus.APPROVAL_REQUIRED
    assert result.pending_approval is not None
    assert result.pending_approval.status is ToolCallStatus.APPROVAL_REQUIRED
    assert result.pending_approval.arguments_digest
    assert capability.executed_arguments == []


async def test_approved_write_resumes_exact_call_before_returning_to_model() -> None:
    capability = _Capability(
        "create_objective_candidate",
        ToolRisk.WRITE,
        _QuestionArguments,
    )
    runner = ResearchAgentRunner(
        model=_Model(ModelTurn(content="候选目标已保存，等待你确认后再分析。")),
        capabilities=CapabilityRegistry((capability,)),
    )
    pending = ChatToolCall.requested(
        tool_call_id="call-1",
        session_id="chat-1",
        assistant_message_id="msg-2",
        name="create_objective_candidate",
        arguments={"question": "How does energy input affect ductility?"},
        risk=ToolRisk.WRITE,
    ).require_approval()
    approved = pending.approve(
        user_id="user-1",
        arguments_digest=pending.arguments_digest,
        decided_at="2026-08-19T00:01:00+00:00",
    )
    prior_messages = (
        ChatMessage.user(
            message_id="msg-1",
            session_id="chat-1",
            content="保存这个目标",
            created_at="2026-08-19T00:00:00+00:00",
        ),
        ChatMessage.assistant_tool_calls(
            message_id="msg-2",
            session_id="chat-1",
            content="我准备保存这个候选目标。",
            tool_calls=(ChatToolRequest(tool_call_id="call-1", name="create_objective_candidate", arguments=approved.arguments, position=0),),


            created_at="2026-08-19T00:00:30+00:00",
        ),
    )

    result = await runner.resume_claimed_call(
        context=_context(),
        previous_messages=prior_messages,
        claimed_call=approved.start("2026-08-19T00:01:01+00:00"),
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert [message.role for message in result.messages[-2:]] == ["tool", "assistant"]
    assert capability.executed_arguments == [
        {"question": "How does energy input affect ductility?"}
    ]


async def test_failed_approved_write_allows_a_failure_explanation_without_new_reads() -> None:
    writer = _Capability("test_write", ToolRisk.WRITE, fail_with=RuntimeError("stale source"))
    read = _Capability("inspect_document_sources", ToolRisk.READ)
    pending = ChatToolCall.requested(
        tool_call_id="call-1", session_id="chat-1", assistant_message_id="request-1",
        name=writer.spec.name, arguments={}, risk=ToolRisk.WRITE,
    ).require_approval()
    approved = pending.approve(user_id="user-1", arguments_digest=pending.arguments_digest,
                               decided_at="2026-09-08T00:00:01+00:00")
    model = _Model(ModelTurn(content="The Source changed; publication could not complete."))
    messages = (
        ChatMessage.user(message_id="user-1", session_id="chat-1",
                         content="Publish from the inspected Sources.", created_at="2026-09-08T00:00:00+00:00"),
        ChatMessage.assistant_tool_calls(message_id="request-1", session_id="chat-1", content="",
                                         tool_calls=(approved.to_request(),), created_at="2026-09-08T00:00:00+00:00"),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((writer, read))).resume_claimed_call(
        context=_context(), previous_messages=messages, claimed_call=approved.start("2026-09-08T00:00:02+00:00"),
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_results[0].status is ToolResultStatus.FAILED
    assert model.tool_spec_names == [()]
    assert read.executed_arguments == []


async def test_read_then_draft_then_write_stops_at_exact_approval_boundary() -> None:
    reader = _Capability("inspect_published_finding", ToolRisk.READ)
    drafter = _Capability(
        "propose_research_plan",
        ToolRisk.DRAFT,
        _QuestionArguments,
    )
    writer = _Capability(
        "create_research_plan",
        ToolRisk.WRITE,
        _QuestionArguments,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="inspect_published_finding",
                    arguments={},
                ),)
            ),
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="propose_research_plan",
                    arguments={"question": "Test the supported preheating effect."},
                ),)
            ),
            ModelTurn(
                content="The plan draft is ready for your approval.",
                tool_calls=(ModelToolCall(
                    name="create_research_plan",
                    arguments={"question": "Test the supported preheating effect."},
                ),),
            ),
            ModelTurn(content="The approved plan draft has been saved."),
        ),
        capabilities=CapabilityRegistry((reader, drafter, writer)),
    )

    proposed = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="Use the current conclusion to prepare and save a research plan.",
    )

    assert proposed.status is AgentRunStatus.APPROVAL_REQUIRED
    assert [call.status for call in proposed.tool_calls] == [
        ToolCallStatus.SUCCEEDED,
        ToolCallStatus.SUCCEEDED,
        ToolCallStatus.SUCCEEDED,
        ToolCallStatus.APPROVAL_REQUIRED,
    ]
    assert reader.executed_arguments == [{}]
    assert drafter.executed_arguments == [
        {"question": "Test the supported preheating effect."}
    ]
    assert writer.executed_arguments == []

    approved = proposed.pending_approval.approve(
        user_id="user-1",
        arguments_digest=proposed.pending_approval.arguments_digest,
        decided_at="2026-09-06T08:00:00+00:00",
    )
    completed = await runner.resume_claimed_call(
        context=_context(),
        previous_messages=proposed.messages,
        claimed_call=approved.start("2026-08-19T00:01:01+00:00"),
    )

    assert completed.status is AgentRunStatus.COMPLETED
    assert writer.executed_arguments == [
        {"question": "Test the supported preheating effect."}
    ]
    assert completed.messages[-1].content == "The approved plan draft has been saved."


async def test_completed_plan_draft_does_not_leak_into_later_finding_review() -> None:
    """A later user request must select its own write capability."""

    propose = _Capability(
        "propose_research_plan",
        ToolRisk.DRAFT,
        result_data={
            "draft_id": "plan-draft-1",
            "content": "Use matched heat-treatment conditions.",
            "persistence": "transient_chat_result",
        },
    )
    review = _Capability("record_finding_feedback", ToolRisk.WRITE)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="propose_research_plan",
                arguments={},
            ),)
        ),
        ModelTurn(content="方案草案已形成，但尚未保存。"),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="record_finding_feedback",
                arguments={},
            ),)
        ),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((propose, review)),
    )

    first = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="根据证据缺口提出研究方案草案，不要保存。",
    )
    assert first.status is AgentRunStatus.COMPLETED

    second = await runner.run_turn(
        context=_context(),
        previous_messages=first.messages,
        user_message="Record my review that this Finding is source-faithful.",
    )

    assert second.status is AgentRunStatus.APPROVAL_REQUIRED
    assert second.pending_approval is not None
    assert second.pending_approval.name == "record_finding_feedback"
    assert model.tool_spec_names[-1] == ("record_finding_feedback",)
    assert review.executed_arguments == []


async def test_unknown_tool_is_returned_to_the_model_as_a_failed_result() -> None:
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="read_file",
                    arguments={"path": "/etc/passwd"},
                ),)
            ),
            ModelTurn(content="这个工具不可用，我不会访问文件系统。"),
        ),
        capabilities=CapabilityRegistry(
            (_Capability("get_collection_context", ToolRisk.READ),)
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="读取服务器文件",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[0].status is ToolCallStatus.FAILED
    assert result.tool_results[0].error_code == "unknown_capability"
    assert "/etc/passwd" not in result.tool_results[0].error_message


async def test_invalid_arguments_do_not_execute_capability() -> None:
    capability = _Capability(
        "propose_objective_drafts",
        ToolRisk.DRAFT,
        _QuestionArguments,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="propose_objective_drafts",
                    arguments={"unexpected": "value"},
                ),)
            ),
            ModelTurn(content="我还需要一个明确的研究问题。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="帮我整理一下",
    )

    assert result.tool_results[-1].error_code == "invalid_tool_arguments"
    assert capability.executed_arguments == []


async def test_finding_draft_repair_receives_actionable_evidence_role_error() -> None:
    from application.chat.capabilities.finding_authoring import CreateFindingDraftCapability

    arguments = {
        "draft_id": "correction", "objective_id": "obj-1", "source_analysis_version": 6,
        "statement": "The inspected paper reports a condition-dependent trend.",
        "assertion_strength": "descriptive", "parent_finding_id": "finding-1",
        "supporting_evidence_ids": [], "contradicting_evidence_ids": ["evidence-1"],
    }
    corrected = {**arguments, "supporting_evidence_ids": ["evidence-1"], "contradicting_evidence_ids": []}
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="create_finding_draft", arguments=arguments),)),
        ModelTurn(tool_calls=(ModelToolCall(name="create_finding_draft", arguments=corrected),)),
        ModelTurn(content="修订草案已准备，尚未保存。"),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((CreateFindingDraftCapability(),))).run_turn(
        context=_context(), previous_messages=(), user_message="请给 Finding 修订草案，先不要保存或发布。",
    )
    failed = next(item for item in result.tool_results if item.error_code == "invalid_tool_arguments")
    assert "finding_supporting_evidence_required" in failed.error_message
    assert arguments["statement"] not in failed.error_message
    assert any(message.tool_result == failed for message in model.contexts[1])
    assert "assertion_strength" in model.contexts[1][-1].content
    assert "causal, associative, or descriptive" in model.contexts[1][-1].content
    assert result.status is AgentRunStatus.COMPLETED
    assert any(item.data.get("draft") == {**corrected, "context_evidence_ids": [], "condition_boundary_evidence_ids": [],
        "limitations": [], "abstention_reason": None} for item in result.tool_results)


async def test_finding_draft_normalizes_conservative_strength_and_duplicate_evidence() -> None:
    from application.chat.agent_runner import _RunProgress

    runner = ResearchAgentRunner(model=_Model(), capabilities=CapabilityRegistry(()))
    turn = ModelTurn(tool_calls=(ModelToolCall(
        name="create_finding_draft",
        arguments={
            "draft_id": "draft-1",
            "objective_id": "objective-1",
            "source_analysis_version": 1,
            "statement": "The inspected result is condition dependent.",
            "supporting_evidence_ids": ["evidence-1", "evidence-1"],
        },
    ),))
    messages = []
    progress = _RunProgress(runner.limits)
    progress.start_response()
    requested = runner._requested_calls(
        _context(), messages, turn, allowed_names={"create_finding_draft"},
        progress=progress,
    )
    assert requested[0][0].arguments["assertion_strength"] == "descriptive"
    assert requested[0][0].arguments["supporting_evidence_ids"] == ["evidence-1"]


async def test_capability_exception_is_sanitized_before_returning_to_model(caplog) -> None:
    capability = _Capability(
        "get_collection_context",
        ToolRisk.READ,
        fail_with=RuntimeError("database password=do-not-expose"),
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),)
            ),
            ModelTurn(content="暂时无法读取 collection，请稍后重试。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="读取 collection",
    )

    assert result.tool_results[-1].error_code == "capability_execution_failed"
    assert "password" not in result.tool_results[-1].error_message
    assert "do-not-expose" not in result.tool_results[-1].error_message
    assert "do-not-expose" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


async def test_queued_capability_result_returns_to_model_as_a_successful_observation() -> None:
    capability = _Capability(
        "start_objective_analysis",
        ToolRisk.READ,
        result_status=ToolResultStatus.QUEUED,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="start_objective_analysis",
                    arguments={},
                ),)
            ),
            ModelTurn(content="分析任务已启动，你可以稍后查看研究目标结果。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="开始分析",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert result.tool_results[0].status is ToolResultStatus.QUEUED
    assert result.tool_results[0].resource_refs[0].resource_type == "objective_analysis"
    assert result.messages[-1].content.startswith("分析任务已启动")


async def test_resource_budget_stops_repeated_tool_calls() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),)
            ),
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),)
            ),
            ModelTurn(
                content=(
                    "我已读取两次 collection 概览，但仍未完成比较；目前只能给出"
                    "有限判断，建议继续指定要检查的论文。"
                )
            ),
        ),
        capabilities=CapabilityRegistry((capability,)),
        limits=AgentRunLimits(max_tool_calls=3),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="不断读取",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert len(result.tool_calls) == 3
    assert len(capability.executed_arguments) == 2
    assert result.messages[-1].role == "assistant"
    assert "step limit" not in result.messages[-1].content.lower()
    assert "有限判断" in result.messages[-1].content


async def test_resource_budget_final_answer_keeps_the_active_research_request() -> None:
    user_request = (
        "比较这些论文；如果只能读一部分，请说明哪些已读、未读或失败。"
    )
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="get_collection_context",
                arguments={},
            ),)
        ),
        ModelTurn(content="我只比较已读取的论文，并明确剩余范围。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (_Capability("get_collection_context", ToolRisk.READ),)
        ),
        limits=AgentRunLimits(max_tool_calls=2),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=user_request,
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.contexts[-1][-1].role.value == "user"
    assert "ACTIVE RESEARCH REQUEST" in model.contexts[-1][-1].content
    assert user_request in model.contexts[-1][-1].content


async def test_resource_budget_final_answer_has_time_to_summarize_large_trajectory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_timeouts: list[float] = []
    original_wait_for = agent_runner_module.wait_for

    async def recording_wait_for(awaitable, timeout):  # noqa: ANN001
        observed_timeouts.append(timeout)
        return await original_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(agent_runner_module, "wait_for", recording_wait_for)
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),)
            ),
            ModelTurn(content="已整理当前已读取的证据范围。"),
        ),
        capabilities=CapabilityRegistry(
            (_Capability("get_collection_context", ToolRisk.READ),)
        ),
        limits=AgentRunLimits(max_tool_calls=2),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="比较已读取的证据并说明剩余范围。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert 30 < observed_timeouts[-1] <= AgentRunLimits().max_finalization_seconds
    assert observed_timeouts[-1] <= observed_timeouts[0] <= AgentRunLimits().max_request_seconds


async def test_resource_budget_ledger_counts_complete_inspected_source_as_read() -> None:
    browse = _Capability(
        "browse_collection_papers",
        ToolRisk.READ,
        result_data={
            "paper_total": 4,
            "returned_paper_count": 1,
            "next_offset": None,
            "papers": [{"document_id": "paper-1"}],
            "screening_only": True,
        },
    )
    inspect = _Capability(
        "inspect_document_sources",
        ToolRisk.READ,
        result_data={
            "document": {"document_id": "paper-1"},
            "sources": [
                {
                    "source_ref": "source-complete",
                    "content": "Complete canonical abstract.",
                    "content_truncated": False,
                    "source_digest": "digest-complete",
                },
                {
                    "source_ref": "source-truncated",
                    "content": "Bounded preview.",
                    "content_truncated": True,
                    "source_digest": "digest-truncated",
                },
            ],
        },
    )
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="browse_collection_papers",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_document_sources",
                arguments={},
            ),)
        ),
        ModelTurn(content="当前 collection 只有 4 篇；我精读了一个完整来源。"),
        discover=("browse_collection_papers", "inspect_document_sources"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((browse, inspect)),
        limits=AgentRunLimits(max_tool_calls=3),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="先浏览论文，再深入读取相关原文。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    final_instruction = model.contexts[-1][-1].content
    assert "Collection paper total: 4" in final_instruction
    assert "Paper identities screened (1): paper-1" in final_instruction
    assert "Exact paper Sources read (1): paper-1:source-complete" in final_instruction
    assert "source-truncated" not in final_instruction


def test_exact_inspection_uses_the_parent_document_identity() -> None:
    results = {"inspect_document_sources": [{
        "document": {"document_id": "paper-1"},
        "sources": [{"source_kind": "text_window", "source_ref": "methods-1",
                     "source_digest": "a" * 64, "content_truncated": False}],
    }]}

    assert capability_policy.has_successful_exact_source_read(
        results, (("paper-1", "text_window", "methods-1"),),
    )
    assert not capability_policy.has_successful_exact_source_read(
        results, (("paper-2", "text_window", "methods-1"),),
    )


def test_reading_ledger_retains_failed_and_unread_document_scope() -> None:
    calls = [
        ChatToolCall.requested(
            tool_call_id=f"call-{index}", session_id="chat-1",
            assistant_message_id=f"message-{index}", position=0,
            name=name, arguments=arguments, risk=ToolRisk.READ,
        )
        for index, (name, arguments) in enumerate((
            ("browse_collection_papers", {}),
            ("read_source", {"document_id": "paper-1"}),
            ("read_source", {"document_id": "paper-2"}),
        ))
    ]
    results = [
        ChatToolResult(tool_call_id="call-0", status="succeeded", data={
            "paper_total": 3,
            "papers": [{"document_id": f"paper-{i}"} for i in (1, 2, 3)],
        }),
        ChatToolResult(tool_call_id="call-1", status="failed",
                       error_code="source_not_found", error_message="Source unavailable"),
        ChatToolResult(tool_call_id="call-2", status="failed",
                       error_code="resource_budget", error_message="Not executed"),
    ]

    ledger = ResearchAgentRunner._reading_ledger(calls, results)

    assert "Papers with failed exact reads (1): paper-1" in ledger
    assert "Known papers without an exact read (2): paper-2, paper-3" in ledger


async def test_resource_budget_final_answer_keeps_latest_structured_draft() -> None:
    propose = _Capability(
        "propose_research_plan",
        ToolRisk.DRAFT,
        result_data={
            "draft_id": "plan-draft-1",
            "objective_id": "objective-1",
            "title": "Test annealing temperature under the equipment constraint",
            "content": "Keep power at or below 300 W and use four samples per group.",
            "draft_status": "needs_finding_review",
            "source_analysis_version": 6,
            "source_finding_ids": ["finding-1"],
            "source_evidence_ids": ["evidence-1"],
            "persistence": "transient_chat_result",
        },
    )
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="propose_research_plan",
                arguments={},
            ),)
        ),
        ModelTurn(content="研究方案草案已形成，但尚未保存或授权执行。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((propose,)),
        limits=AgentRunLimits(max_tool_calls=2),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="根据证据缺口提出研究方案草案，不要保存。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    final_instruction = model.contexts[-1][-1].content
    assert "COMPLETED STRUCTURED DELIVERABLE" in final_instruction
    assert "plan-draft-1" in final_instruction
    assert "Keep power at or below 300 W" in final_instruction
    assert "transient_chat_result" in final_instruction


async def test_complete_paper_browse_is_not_repeated_during_source_reading() -> None:
    browse = _Capability(
        "browse_collection_papers",
        ToolRisk.READ,
        result_data={
            "paper_total": 4,
            "returned_paper_count": 4,
            "next_offset": None,
            "papers": [{"document_id": "paper-1"}],
            "screening_only": True,
        },
    )
    search = _Capability("search_sources", ToolRisk.READ, _QuestionArguments)
    read = _Capability("read_source", ToolRisk.READ, _QuestionArguments)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="browse_collection_papers",
                arguments={},
            ),)
        ),
        ModelTurn(content="我会继续检查已筛选论文的相关原文。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((browse, search, read)),
    )

    await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="深入阅读这些论文的实验条件和结果。",
    )

    assert "browse_collection_papers" in model.tool_spec_names[0]
    assert "browse_collection_papers" not in model.tool_spec_names[1]
    assert model.all_tool_spec_names[-1] == ("discover_research_tools",)


async def test_comparison_requires_source_search_after_paper_map() -> None:
    browse = _Capability(
        "browse_collection_papers",
        ToolRisk.READ,
        result_data={
            "paper_total": 3,
            "returned_paper_count": 3,
            "next_offset": None,
            "papers": [{"document_id": "paper-1"}],
        },
    )
    search = _Capability(
        "search_sources",
        ToolRisk.READ,
        result_data={
            "match_total": 1,
            "matches": [
                {
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                }
            ],
        },
    )
    read = _Capability(
        "read_source",
        ToolRisk.READ,
        result_data={
            "document_id": "paper-1",
            "source_kind": "text_window",
                "source_ref": "methods-1",
            "content_truncated": False,
            "source_digest": "a" * 64,
        },
    )
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="browse_collection_papers",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="search_sources",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="read_source",
                arguments={},
            ),)
        ),
        ModelTurn(content="已基于精确来源检查论文间的实验条件。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((browse, search, read)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="比较这三篇论文是否支持同一结论，并检查实验条件是否可比。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names[1] == ("search_sources",)
    assert model.tool_spec_names[2] == ("read_source",)
    assert search.executed_arguments == [{}]
    assert read.executed_arguments == [{}]


async def test_finding_revision_keeps_source_discovery_before_required_draft() -> None:
    inspect = _Capability("inspect_published_finding", ToolRisk.READ, _FindingArguments)
    draft = _Capability("create_finding_draft", ToolRisk.DRAFT)
    query = _Capability("query_published_findings", ToolRisk.READ)
    read = _Capability("read_source", ToolRisk.READ)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_published_finding",
                arguments={
                    "objective_id": "objective-1",
                    "finding_id": "finding-1",
                },
            ),)
        ),
        ModelTurn(content="我会形成一份保留温度边界的修订草案。"),
        ModelTurn(tool_calls=(ModelToolCall(name="read_source", arguments={}),)),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="create_finding_draft",
                arguments={},
            ),)
        ),
        ModelTurn(content="修订草案已形成，但尚未修改已发布结论。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((query, inspect, read, draft)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=(
            "查看已发布的研究结论；如果忽略了热处理条件，请提出修订草案，"
            "不要直接修改。"
        ),
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert any("create_finding_draft" in names and "discover_research_tools" in names for names in model.all_tool_spec_names)
    assert "create_finding_draft" in model.tool_spec_names[1]
    assert read.executed_arguments == [{}]
    assert draft.executed_arguments == [{}]


@pytest.mark.parametrize("tokens_spent", [80000, 84109])
async def test_context_preparation_exhausting_allowance_finalizes_without_negative_output(monkeypatch, tokens_spent):
    from application.chat.context_builder import ChatModelContext

    model = _Model(ModelTurn(content="The investigation remains incomplete; no correction was saved."))
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry(()),
                                 limits=AgentRunLimits(max_model_tokens=80000))

    async def prepared(messages, tool_specs, progress, *, active_user_message_id):
        progress.model_tokens = tokens_spent
        return ChatModelContext(messages)

    monkeypatch.setattr(runner, "_prepare_model_context", prepared)
    result = await runner.run_turn(context=_context(), previous_messages=(), user_message="Recheck these papers.")
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert model.request_limits == [(runner.limits.max_request_seconds, runner.limits.max_finalization_output_tokens)]
    assert not result.tool_calls


async def test_finding_recheck_reads_its_linked_source_before_other_navigation() -> None:
    from application.chat.capabilities.document_sources import ReadSourceArguments

    source = {"document_id": "paper-1", "source_kind": "text_window", "source_ref": "results-7"}
    inspect = _Capability("inspect_published_finding", ToolRisk.READ, result_data={
        "finding": {"finding_id": "finding-1"}, "evidence": [{"evidence_id": "evidence-1", **source}],
    })
    read = _Capability("read_source", ToolRisk.READ, ReadSourceArguments, result_data={
        **source, "content_truncated": False, "source_digest": "a" * 64,
        "content": "Elongation increased and then decreased with temperature.",
    })
    draft = _Capability("create_finding_draft", ToolRisk.DRAFT)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("inspect_published_finding", {}),)),
        ModelTurn(tool_calls=(ModelToolCall("read_source", source),)),
        ModelTurn(tool_calls=(ModelToolCall("create_finding_draft", {}),)),
        ModelTurn(content="单篇条件依赖结论的修订草案已形成，其他论文正文仍待核查。"),
        source_inspection_required=True,
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((inspect, read, draft))).run_turn(
        context=_context(), previous_messages=(), user_message="请核对这个 Finding 的原文并给修订草案，先不要保存。",
    )
    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names[1] == ("read_source",)
    # A linked passage does not resolve all of the researcher's source checks.
    assert {"read_source", "create_finding_draft"}.issubset(model.tool_spec_names[2])
    assert [call.name for call in result.tool_calls if call.name != "discover_research_tools"] == [
        "inspect_published_finding", "read_source", "create_finding_draft",
    ]
    assert "results-7" in model.contexts[1][-1].content


async def test_finding_recheck_emits_a_progressive_research_plan() -> None:
    from application.chat.capabilities.document_sources import ReadSourceArguments

    source = {
        "document_id": "paper-1",
        "source_kind": "text_window",
        "source_ref": "results-7",
    }
    inspect = _Capability("inspect_published_finding", ToolRisk.READ, result_data={
        "finding": {"finding_id": "finding-1"},
        "evidence": [{"evidence_id": "evidence-1", **source}],
    })
    read = _Capability(
        "read_source", ToolRisk.READ, ReadSourceArguments,
        result_data={**source, "content_truncated": False, "source_digest": "a" * 64,
                     "content": "The inspected evidence supports the correction."},
    )
    draft = _Capability(
        "create_finding_draft", ToolRisk.DRAFT,
        result_data={"draft": {"draft_id": "draft-1"}, "persistence": "transient_chat_result"},
    )
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("inspect_published_finding", {}),)),
        ModelTurn(tool_calls=(ModelToolCall("read_source", source),)),
        ModelTurn(tool_calls=(ModelToolCall("create_finding_draft", {}),)),
        ModelTurn(content="修订草案已形成，等待审核。"),
    )
    progress_events: list[dict[str, object]] = []
    result = await ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((inspect, read, draft)),
    ).run_turn(
        context=_context(),
        previous_messages=(),
        user_message="请核对这个 Finding 并给出修订草案，先不要保存。",
        progress_callback=progress_events.append,
    )

    assert result.status is AgentRunStatus.COMPLETED
    plans = [event["research_plan"] for event in progress_events if event.get("research_plan")]
    assert plans
    assert plans[0][0] == {"id": "inspect_finding", "status": "in_progress"}
    assert plans[-1][-1] == {"id": "approval", "status": "in_progress"}


@pytest.mark.parametrize("request_publication", [False, True])
async def test_finding_review_can_draft_evidence_correction_before_rebuilding_finding(request_publication) -> None:
    from application.chat.capabilities.document_sources import ReadSourceArguments

    class EvidenceDraftArguments(ReadSourceArguments):
        source_digest: str

    source = {"document_id": "paper-1", "source_kind": "text_window", "source_ref": "results-7"}
    inspect = _Capability("inspect_published_finding", ToolRisk.READ, result_data={
        "finding": {"finding_id": "finding-1"},
        "evidence": [{"evidence_id": "evidence-1", **source,
                      "reported_result": {"direction": "decrease"}}],
    })
    read = _Capability("read_source", ToolRisk.READ, ReadSourceArguments, result_data={
        **source, "content_truncated": False, "source_digest": "a" * 64,
        "content": "Elongation increased and then decreased as annealing temperature increased.",
    })
    evidence_draft = _Capability("create_evidence_draft", ToolRisk.DRAFT, EvidenceDraftArguments)
    finding_draft = _Capability("create_finding_draft", ToolRisk.DRAFT)
    evidence_write = _Capability("create_evidence_version", ToolRisk.WRITE, EvidenceDraftArguments)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall("inspect_published_finding", {}),)),
        ModelTurn(tool_calls=(ModelToolCall("read_source", source),)),
        ModelTurn(tool_calls=(ModelToolCall("create_evidence_draft", {**source, "source_digest": "a" * 64}),)),
        (ModelTurn(tool_calls=(ModelToolCall("create_evidence_version", {**source, "source_digest": "a" * 64}),))
         if request_publication else
         ModelTurn(content="原始依据把先升后降简化成下降。已形成依据修订草案，保存后还需重新综合结论。")),
        discover=("inspect_published_finding", "read_source", "create_finding_draft", "create_evidence_draft"),
        source_inspection_required=True,
    )
    events: list[dict[str, object]] = []
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        inspect, read, evidence_draft, finding_draft,
        evidence_write,
        _Capability("create_finding_version", ToolRisk.WRITE),
        _Capability("curate_finding", ToolRisk.WRITE),
    ))).run_turn(
        context=_context(), previous_messages=(),
        user_message=("请核对这个 Finding 的原文，给出修订草案并保存证据修订为新版本。" if request_publication else
                      "请核对这个 Finding 的原文，先给修订草案，不要保存或发布。"),
        progress_callback=events.append,
    )

    assert result.status is (AgentRunStatus.APPROVAL_REQUIRED if request_publication else AgentRunStatus.COMPLETED)
    expected_calls = [
        "inspect_published_finding", "read_source", "create_evidence_draft",
    ]
    if request_publication:
        expected_calls.append("create_evidence_version")
        assert result.pending_approval.name == "create_evidence_version"
    assert [call.name for call in result.tool_calls if call.name != "discover_research_tools"] == expected_calls
    assert not evidence_write.executed_arguments
    assert not finding_draft.executed_arguments
    plan = next(event["research_plan"] for event in reversed(events) if event.get("research_plan"))
    assert next(item for item in plan if item["id"] == "draft_finding")["status"] == "pending"
    assert plan[-1] == {"id": "approval", "status": "in_progress"}


@pytest.mark.parametrize("write_before_read", [False, True])
async def test_evidence_save_request_requires_real_approval_after_complete_read(write_before_read) -> None:
    from application.chat.capabilities.document_sources import ReadSourceArguments

    class EvidenceWriteArguments(ReadSourceArguments):
        source_digest: str

    source = {"document_id": "paper-1", "source_kind": "text_window", "source_ref": "results-7"}
    read = _Capability("read_source", ToolRisk.READ, ReadSourceArguments, result_data={
        **source, "content_truncated": False, "source_digest": "a" * 64,
        "content": "Elongation increased and then decreased as annealing temperature increased.",
    })
    write = _Capability("create_evidence_version", ToolRisk.WRITE, EvidenceWriteArguments)
    model = _Model(
        *( [ModelTurn(tool_calls=(ModelToolCall("create_evidence_version", {**source, "source_digest": "a" * 64}),))]
           if write_before_read else [] ),
        ModelTurn(tool_calls=(ModelToolCall("read_source", source),)),
        ModelTurn(content="The Evidence correction is ready. Please confirm saving it."),
        ModelTurn(tool_calls=(ModelToolCall("create_evidence_version", {**source, "source_digest": "a" * 64}),)),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read, write))).run_turn(
        context=_context(), previous_messages=(), user_message="Read the Source and save the corrected Evidence as a new version.",
    )
    assert result.status is AgentRunStatus.APPROVAL_REQUIRED
    assert result.pending_approval.name == "create_evidence_version"
    assert not write.executed_arguments
    if write_before_read:
        assert result.tool_results[0].error_code == "source_read_incomplete"
        assert model.tool_spec_names[1] == ("read_source",)


@pytest.mark.parametrize("kind", ["evidence", "finding"])
def test_publication_hint_retains_actual_draft_instead_of_restarting_review(kind) -> None:
    draft = {"draft_id": "reviewed-1", "source_analysis_version": 7,
             "supporting_evidence_ids": ["corrected-evidence-1"], "statement": "Condition-dependent elongation."}
    instruction = capability_policy.stage_instruction(
        ("read_source", "inspect_published_finding", f"create_{kind}_draft", f"create_{kind}_version"),
        [], successful_results={
            "inspect_published_finding": [{"finding": {"finding_id": "parent-1"}}],
            f"create_{kind}_draft": [{"draft": draft, "persistence": "transient_chat_result"}],
        },
    )
    retained = json.loads(instruction.split("\n", 1)[1])
    assert retained == {key: value for key, value in draft.items() if key != "draft_id"}
    assert f"calling create_{kind}_version" in instruction
    assert "call create_finding_draft" not in instruction


async def test_publishing_an_earlier_finding_draft_requires_actual_approval() -> None:
    write = _Capability("create_finding_version", ToolRisk.WRITE)
    model = _Model(
        ModelTurn(content="The earlier draft is ready. Please approve publication."),
        ModelTurn(tool_calls=(ModelToolCall("create_finding_version", {}),)),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((write,))).run_turn(
        context=_context(), previous_messages=(), user_message="Publish the reviewed Finding as a new version.",
    )
    assert result.status is AgentRunStatus.APPROVAL_REQUIRED
    assert result.pending_approval.name == "create_finding_version"
    assert not write.executed_arguments


async def test_exact_finding_inspection_narrows_next_step_to_research_plan_draft() -> None:
    inspect = _Capability("inspect_published_finding", ToolRisk.READ)
    propose = _Capability(
        "propose_research_plan",
        ToolRisk.DRAFT,
        result_data={
            "draft_id": "plan-draft-1",
            "title": "Bounded plan",
            "content": "Use four samples per group.",
            "persistence": "transient_chat_result",
        },
    )
    plans = _Capability("inspect_research_plans", ToolRisk.READ)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_published_finding",
                arguments={},
            ),)
        ),
        ModelTurn(content="我会按约束形成完整的研究方案草案。"),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="propose_research_plan",
                arguments={},
            ),)
        ),
        ModelTurn(content="方案草案已形成，但尚未保存。"),
        discover=("inspect_published_finding", "propose_research_plan"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((inspect, propose, plans)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=(
            "根据证据缺口提出研究方案草案，设备功率上限 300 W，每组最多 4 个"
            "样品，不要保存。"
        ),
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names[1:3] == [
        ("propose_research_plan",),
        ("propose_research_plan",),
    ]
    assert propose.executed_arguments == [{}]
    assert "COMPLETED STRUCTURED DELIVERABLE" in model.contexts[-1][-1].content


async def test_research_plan_progresses_once_through_required_evidence_reads() -> None:
    context = _Capability("get_collection_context", ToolRisk.READ)
    quality = _Capability("assess_objective_quality", ToolRisk.READ)
    query = _Capability(
        "query_published_findings",
        ToolRisk.READ,
        result_data={
            "objectives": [
                {
                    "objective_id": "objective-1",
                    "findings": [{"finding_id": "finding-1"}],
                }
            ]
        },
    )
    inspect = _Capability(
        "inspect_published_finding",
        ToolRisk.READ,
        _FindingArguments,
    )
    propose = _Capability("propose_research_plan", ToolRisk.DRAFT)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="get_collection_context",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="assess_objective_quality",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="query_published_findings",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_published_finding",
                arguments={
                    "objective_id": "objective-1",
                    "finding_id": "finding-1",
                },
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="propose_research_plan",
                arguments={},
            ),)
        ),
        ModelTurn(content="方案草案已形成，但尚未保存或授权执行。"),
        discover=("propose_research_plan",),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((context, query, inspect, quality, propose)),
        limits=AgentRunLimits(max_tool_calls=6),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=(
            "目前最大的证据缺口是什么？如果要验证这个判断，请提出一个研究"
            "方案草案，设备功率上限 300 W，每组最多 4 个样品，不要保存。"
        ),
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [
        (
            "get_collection_context",
            "query_published_findings",
            "assess_objective_quality",
        ),
        ("query_published_findings", "assess_objective_quality"),
        ("query_published_findings",),
        ("inspect_published_finding",),
        ("propose_research_plan",),
        (),
    ]


async def test_research_plan_can_abstain_when_no_published_finding_exists() -> None:
    quality = _Capability("assess_objective_quality", ToolRisk.READ)
    query = _Capability(
        "query_published_findings",
        ToolRisk.READ,
        result_data={
            "finding_count": 0,
            "evidence_count": 0,
            "scientific_absence": True,
            "objectives": [],
        },
    )
    inspect = _Capability("inspect_published_finding", ToolRisk.READ)
    propose = _Capability("propose_research_plan", ToolRisk.DRAFT)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="assess_objective_quality",
                arguments={},
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="query_published_findings",
                arguments={},
            ),)
        ),
        ModelTurn(
            content=(
                "当前没有已发布研究结论可支撑方案；我不会虚构依据，先建议"
                "完成证据分析。"
            )
        ),
        discover=("propose_research_plan",),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((query, inspect, quality, propose)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="根据现有证据缺口提出研究方案草案，不要保存。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names == [
        ("query_published_findings", "assess_objective_quality"),
        ("query_published_findings",),
        (),
    ]
    assert inspect.executed_arguments == []
    assert propose.executed_arguments == []


async def test_source_search_narrows_next_step_to_exact_source_readers() -> None:
    search = _Capability(
        "search_sources",
        ToolRisk.READ,
        result_data={
            "match_total": 1,
            "next_offset": None,
            "matches": [
                {
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "block-methods-7",
                    "source_type": "text",
                    "content_truncated": True,
                }
            ],
        },
    )
    read = _Capability(
        "read_source",
        ToolRisk.READ,
        result_data={
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-methods-7",
            "content_truncated": False,
            "source_digest": "a" * 64,
        },
    )
    inspect = _Capability("inspect_document_sources", ToolRisk.READ)
    table = _Capability("inspect_table", ToolRisk.READ)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(name="search_sources", arguments={}),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(name="read_source", arguments={}),)
        ),
        ModelTurn(content="已读取搜索命中的原文来源。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((search, read, inspect, table)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="搜索热处理方法后，深入读取命中的原文。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert set(model.tool_spec_names[1]) == {
        "read_source",
        "inspect_table",
    }
    assert "paper-1" in model.contexts[1][-1].content
    assert "block-methods-7" in model.contexts[1][-1].content
    assert inspect.executed_arguments == []


async def test_source_search_cannot_be_answered_without_one_exact_reader() -> None:
    search = _Capability(
        "search_sources",
        ToolRisk.READ,
        result_data={
            "matches": [
                {
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "block-methods-7",
                }
            ]
        },
    )
    read = _Capability("read_source", ToolRisk.READ)
    table = _Capability("inspect_table", ToolRisk.READ)
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="search_sources", arguments={}),)),
        ModelTurn(content="可以直接根据搜索结果下结论。"),
        ModelTurn(content="仍然不读取原文。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((search, read, table)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="搜索热处理方法后判断其对孔隙率的影响。",
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "required_research_action_not_completed"
    assert result.messages[-1].content != "可以直接根据搜索结果下结论。"


async def test_source_read_proof_does_not_cross_user_request_boundary() -> None:
    first_search = _Capability(
        "search_sources",
        ToolRisk.READ,
        result_data={
            "matches": [
                {"document_id": "paper-1", "source_kind": "text_window", "source_ref": "block-1"}
            ]
        },
    )
    first_read = _Capability(
        "read_source",
        ToolRisk.READ,
        result_data={
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "content_truncated": False,
            "source_digest": "a" * 64,
        },
    )
    first_model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="search_sources", arguments={}),)),
        ModelTurn(tool_calls=(ModelToolCall(name="read_source", arguments={}),)),
        ModelTurn(content="第一篇已核对。"),
    )
    first_runner = ResearchAgentRunner(
        model=first_model,
        capabilities=CapabilityRegistry((first_search, first_read)),
    )
    first = await first_runner.run_turn(
        context=_context(), previous_messages=(), user_message="搜索并读取 paper-1 的原文。"
    )
    assert first.status is AgentRunStatus.COMPLETED

    second_search = _Capability(
        "search_sources",
        ToolRisk.READ,
        result_data={
            "matches": [
                {"document_id": "paper-2", "source_kind": "text_window", "source_ref": "block-2"}
            ]
        },
    )
    second_read = _Capability("read_source", ToolRisk.READ)
    second_model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="search_sources", arguments={}),)),
        ModelTurn(content="第二篇也可以直接回答。"),
        ModelTurn(content="第二篇仍然没有读取原文。"),
    )
    second_runner = ResearchAgentRunner(
        model=second_model,
        capabilities=CapabilityRegistry((second_search, second_read)),
    )
    second = await second_runner.run_turn(
        context=_context(), previous_messages=first.messages,
        user_message="搜索并读取 paper-2 的原文后再判断。",
    )

    assert second.status is AgentRunStatus.FAILED
    assert second.error_code == "required_research_action_not_completed"
    assert second_model.tool_spec_names[1] == ("read_source",)


def test_research_plan_intent_exposes_inspection_and_revision_capabilities() -> None:
    names = intent_policy.capability_names_for_intent(
        "查看已保存的研究方案并修订后保存",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "inspect_research_plans" in names
    assert "revise_research_plan" in names
    assert "create_research_plan" in names


def test_explanation_does_not_enable_research_plan_capabilities() -> None:
    names = intent_policy.capability_names_for_intent(
        "Please provide an explanation of this system.",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert not {
        "query_published_findings",
        "assess_objective_quality",
        "inspect_research_plans",
        "propose_research_plan",
    }.intersection(names)


def test_generic_method_question_does_not_enable_source_reading() -> None:
    names = intent_policy.capability_names_for_intent(
        "Please explain this method.",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert not {
        "browse_collection_papers",
        "search_sources",
        "read_source",
        "inspect_document_sources",
        "inspect_table",
    }.intersection(names)


def test_paper_method_question_still_enables_source_reading() -> None:
    names = intent_policy.capability_names_for_intent(
        "Read the paper's methods and results.",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "read_source" in names


def test_document_identifier_enables_direct_source_inspection() -> None:
    names = intent_policy.capability_names_for_intent(
        "Inspect the P002 group definitions",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert {
        "search_sources",
        "read_source",
        "inspect_document_sources",
        "inspect_table",
    }.intersection(names)


async def test_document_identifier_request_can_execute_source_read() -> None:
    read = _Capability(
        "read_source",
        ToolRisk.READ,
        _QuestionArguments,
        result_data={
            "document_id": "P002",
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "content_truncated": False,
            "source_digest": "a" * 64,
        },
    )
    model = _Model(
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    name="read_source",
                    arguments={"question": "P002 group definitions"},
                ),
            )
        ),
        ModelTurn(content="P002 的 group definitions 已读取。"),
    )
    result = await ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((read,)),
    ).run_turn(
        context=_context(),
        previous_messages=(),
        user_message="Inspect the P002 group definitions",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert [call.name for call in result.tool_calls] == ["discover_research_tools", "read_source"]
    assert read.executed_arguments == [{"question": "P002 group definitions"}]


def test_generic_plan_question_does_not_enable_research_plan_tools() -> None:
    names = intent_policy.capability_names_for_intent(
        "What is your plan?",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert not {
        "query_published_findings",
        "assess_objective_quality",
        "inspect_research_plans",
        "propose_research_plan",
        "create_research_plan",
    }.intersection(names)


@pytest.mark.parametrize(
    "request_text",
    ["Draft and save a plan", "Revise the saved plan"],
)
def test_actionable_english_plan_request_enables_plan_capabilities(
    request_text: str,
) -> None:
    names = intent_policy.capability_names_for_intent(
        request_text,
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "propose_research_plan" in names
    assert "inspect_research_plans" in names


@pytest.mark.parametrize(
    ("request_text", "capability_name"),
    [
        ("Draft and save a plan", "create_research_plan"),
    ],
)
async def test_actionable_english_plan_request_reaches_write_approval(
    request_text: str,
    capability_name: str,
) -> None:
    write = _Capability(capability_name, ToolRisk.WRITE)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(name=capability_name, arguments={}),)
        )
    )
    result = await ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((write,)),
    ).run_turn(
        context=_context(),
        previous_messages=(),
        user_message=request_text,
    )

    assert result.status is AgentRunStatus.APPROVAL_REQUIRED
    assert model.tool_spec_names == [(capability_name,)]
    assert write.executed_arguments == []


def test_non_mutating_version_request_keeps_explicit_new_version_write() -> None:
    names = intent_policy.capability_names_for_intent(
        "不要修改旧 Finding，请创建一个新版本。",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "create_finding_version" in names


@pytest.mark.parametrize(("request_text", "writes"), [
    ("请把这个 Finding 标为错误，保存错误反馈；不保存修订结论，也不发布新分析。", {"record_finding_feedback"}),
    ("保存 Finding 人工修订，保留原始结果和现有 Evidence；不创建独立新 Finding，不发布新的分析版本。", {"curate_finding"}),
    ("Save feedback for this Finding, but do not save the curation or publish a new analysis.", {"record_finding_feedback"}),
    ("Check the complete table and save the corrected Evidence as a new version.", {"create_evidence_version"}),
    ("Save the human revision of this Finding; do not publish a new Finding.", {"curate_finding"}),
    ("请保存这个 Finding 的修订。", {"create_finding_version"}),
    ("Save the revision of this Finding.", {"create_finding_version"}),
    ("请保存证据修订，保留旧记录。", {"create_evidence_version"}),
    ("保存这个 Finding 的反馈，先不要保存任何内容。", set()),
    ("只读查看 Finding 已保存的错误反馈和人工修订，不要写入。", set()),
    ("Read-only: inspect the saved Finding revision.", set()),
    ("请核对这个已发布 Finding 并给修订草案，先不要保存或发布。", set()),
    ("Review this published Finding; do not save or publish.", set()),
    ("请复核这个 Finding，先不要发布。", set()),
    ("请保存反馈但不保存修订，Finding 原始发布结果保留。", {"record_finding_feedback"}),
])
def test_finding_writes_respect_each_requested_action(request_text, writes) -> None:
    names = intent_policy.capability_names_for_intent(request_text, has_source_context=False, prior_tool_names=set())
    assert names.intersection(intent_policy.WRITE_CAPABILITIES) == writes


def test_failed_curation_gets_canonical_repair_instruction() -> None:
    failed = ChatToolCall.requested(
        tool_call_id="curate-1", session_id="chat-1", assistant_message_id="msg-1",
        name="curate_finding", arguments={}, risk=ToolRisk.WRITE,
    ).fail("invalid_tool_arguments", "2026-09-10T00:00:00Z")
    instruction = capability_policy.stage_instruction(
        ("curate_finding",), [failed], successful_results={}
    )
    assert instruction is not None
    assert "complete top-level object" in instruction
    assert "limitations" in instruction
    assert "value types" in instruction


def test_curation_call_preserves_inspected_identity_and_provenance() -> None:
    from tests.unit.application.test_chat_research_capabilities import _canonical_finding_record

    canonical = _canonical_finding_record()
    inspect_request = ChatToolCall.requested(
        tool_call_id="inspect-1", session_id="chat-1", assistant_message_id="inspect-call",
        name="inspect_published_finding", arguments={}, risk=ToolRisk.READ,
    ).start("2026-09-10T00:00:00Z").succeed("2026-09-10T00:00:01Z").to_request()
    inspect_call = ChatMessage.assistant_tool_calls(
        message_id="inspect-call", session_id="chat-1", content="", tool_calls=(
            inspect_request,
        ), created_at="2026-09-10T00:00:00Z",
    )
    inspected = ChatMessage.from_tool_result(
        message_id="inspect-result", session_id="chat-1", created_at="2026-09-10T00:00:00Z",
        result=ChatToolResult(
            tool_call_id="inspect-1", status=ToolResultStatus.SUCCEEDED,
            data={"finding": canonical},
        ),
    )
    candidate = {
        "objective_id": canonical["objective_id"],
        "analysis_version": canonical["analysis_version"],
        "finding_id": canonical["finding_id"],
        "curated_finding": {
            "statement": "The reported effect is limited to the inspected condition.",
            "limitation": ["Only one paper was checked."],
        },
    }
    repaired = ResearchAgentRunner._complete_curation_shape(
        candidate, [ChatMessage.user(
            message_id="user-1", session_id="chat-1", content="Revise this Finding.",
            created_at="2026-09-10T00:00:00Z",
        ), inspect_call, inspected],
    )
    finding = repaired["curated_finding"]
    assert finding["collection_id"] == canonical["collection_id"]
    assert finding["paper_contributions"] == canonical["paper_contributions"]
    assert finding["limitations"] == ["Only one paper was checked."]
    assert "limitation" not in finding


@pytest.mark.parametrize("name", ["record_finding_feedback", "curate_finding"])
def test_completed_finding_publication_does_not_force_an_additional_review_write(name) -> None:
    results = {"create_finding_version": [{"finding": {"finding_id": "finding-1"}}],
               "inspect_published_finding": [{"finding": {"finding_id": "parent-1"}}]}
    assert capability_policy.required_tool_before_answer((name, "discover_research_tools"), successful_results=results) is None
    assert capability_policy.stage_instruction((name,), [], successful_results=results) is None


@pytest.mark.parametrize("name", ["record_finding_feedback", "curate_finding"])
async def test_review_save_requires_real_approval_instead_of_a_prose_confirmation(name) -> None:
    capability = _Capability(name, ToolRisk.WRITE)
    model = _Model(
        ModelTurn(content="待批准内容，请确认是否保存。"),
        ModelTurn(tool_calls=(ModelToolCall(name=name, arguments={}),)),
    )
    deltas = []
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((
        capability, _Capability("get_collection_context", ToolRisk.READ),
    ))).run_turn(context=_context(), previous_messages=(),
        user_message="请保存 Finding 的" + ("错误反馈。" if name == "record_finding_feedback" else "人工修订。"),
        text_delta_callback=deltas.append)
    assert result.status is AgentRunStatus.APPROVAL_REQUIRED
    assert result.pending_approval is not None and result.pending_approval.name == name
    assert capability.executed_arguments == []
    assert "待批准内容" not in "".join(deltas)


@pytest.mark.parametrize("name", ["record_finding_feedback", "curate_finding"])
async def test_approved_finding_review_reports_persisted_status_without_model_rewrite(name) -> None:
    write = _Capability(name, ToolRisk.WRITE, result_data={
        "note": "Only the inspected condition is supported.",
        "curated_finding": {"statement": "The effect is limited to the inspected condition."},
    })
    pending = ChatToolCall.requested(
        tool_call_id="call-1", session_id="chat-1", assistant_message_id="msg-2",
        name=name, arguments={}, risk=ToolRisk.WRITE,
    ).require_approval()
    claimed = pending.approve(user_id="user-1", arguments_digest=pending.arguments_digest,
                              decided_at="2026-09-10T00:01:00Z").start("2026-09-10T00:01:01Z")
    model = _Model(ModelTurn(content="已保存，等待您的批准。"))
    runner = ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((write,)))
    result = await runner.resume_claimed_call(context=_context(), previous_messages=(ChatMessage.user(
        message_id="msg-1", session_id="chat-1", content="请保存 Finding 修订，等待批准。",
        created_at="2026-09-10T00:00:00Z",
    ),), claimed_call=claimed)
    assert result.status is AgentRunStatus.COMPLETED
    assert result.pending_approval is None
    assert "已保存" in result.messages[-1].content
    assert "等待" not in result.messages[-1].content
    assert model.contexts == []
    assert write.executed_arguments == [{}]


def test_attached_source_context_does_not_force_collection_browse() -> None:
    runner = ResearchAgentRunner(
        model=_Model(ModelTurn(content="可以根据这段来源回答。")),
        capabilities=CapabilityRegistry(
            (
                _Capability("browse_collection_papers", ToolRisk.READ),
                _Capability("search_sources", ToolRisk.READ),
                _Capability("read_source", ToolRisk.READ),
            )
        ),
    )
    message = ChatMessage.user(
        message_id="user-message",
        session_id="chat-1",
        content="根据这些论文中的原文判断这个结果。",
        created_at="2026-01-01T00:00:00+00:00",
        source_contexts=(object(),),  # type: ignore[arg-type]
    )

    names = {
        spec.name
        for spec in capability_policy.select_tool_specs(runner.capabilities, [message], [])
    }

    assert "browse_collection_papers" not in names
    assert names == {"discover_research_tools"}
    assert "read_source" in runner.capabilities.discovery.tools


async def test_research_plan_read_request_requires_inspection_tool() -> None:
    inspect = _Capability(
        "inspect_research_plans",
        ToolRisk.READ,
        _ObjectiveArguments,
        result_data={"objective_id": "objective-1", "plans": []},
    )
    model = _Model(
        ModelTurn(content="已有方案如下。"),
        ModelTurn(content="仍然可以直接回答。"),
        discover=("inspect_research_plans",),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((inspect,)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="查看已保存的研究方案",
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "required_research_action_not_completed"
    assert inspect.executed_arguments == []


@pytest.mark.parametrize("user_request", ["查看已保存的研究方案并修订后保存", "Revise the saved plan"])
async def test_research_plan_revision_reads_existing_plan_before_write(user_request: str) -> None:
    inspect = _Capability(
        "inspect_research_plans",
        ToolRisk.READ,
        _ObjectiveArguments,
        result_data={
            "objective_id": "objective-1",
            "plans": [{"plan_id": "plan-1"}],
        },
    )
    revise = _Capability("revise_research_plan", ToolRisk.WRITE, _RevisionArguments)
    model = _Model(
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    name="inspect_research_plans",
                    arguments={"objective_id": "objective-1"},
                ),
            )
        ),
        ModelTurn(
            tool_calls=(
                ModelToolCall(name="revise_research_plan", arguments={
                    "objective_id": "objective-1", "parent_plan_id": "plan-1",
                }),
            )
        ),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((inspect, revise,
            _Capability("assess_objective_quality", ToolRisk.READ),
            _Capability("query_published_findings", ToolRisk.READ),
            _Capability("propose_research_plan", ToolRisk.DRAFT),
        )),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=user_request,
    )

    assert result.status is AgentRunStatus.APPROVAL_REQUIRED
    assert model.tool_spec_names[:2] == [
        ("inspect_research_plans",),
        ("revise_research_plan",),
    ]


async def test_process_status_requires_canonical_objective_analysis_state() -> None:
    context = _Capability(
        "get_collection_context",
        ToolRisk.READ,
        result_data={
            "objectives": [
                {
                    "objective_id": "objective-confirmed",
                    "confirmation_status": "confirmed",
                    "published_analysis_version": 3,
                }
            ]
        },
    )
    process = _Capability(
        "inspect_research_process",
        ToolRisk.READ,
        result_data={"process": {"status": "ready", "document_count": 2}},
    )
    analysis = _Capability("inspect_objective_analysis", ToolRisk.READ)
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(name="get_collection_context", arguments={}),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(name="inspect_research_process", arguments={}),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(name="inspect_objective_analysis", arguments={}),)
        ),
        ModelTurn(content="文献准备完成，已确认目标的分析状态见上。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((context, process, analysis)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="当前 collection 的研究目标和分析进度是什么？请查看状态。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names[1] == (
        "inspect_research_process",
    )
    assert model.tool_spec_names[2] == ("inspect_objective_analysis",)
    assert "objective-confirmed" in model.contexts[2][-1].content


async def test_finding_inspection_is_bounded_to_query_ids_and_does_not_repeat_failed_id() -> None:
    query = _Capability(
        "query_published_findings",
        ToolRisk.READ,
        result_data={
            "objectives": [
                {
                    "objective_id": "objective-1",
                    "findings": [
                        {"finding_id": "finding-1"},
                        {"finding_id": "finding-2"},
                    ],
                }
            ]
        },
    )
    inspect = _Capability(
        "inspect_published_finding",
        ToolRisk.READ,
        _FindingArguments,
        result_status=ToolResultStatus.FAILED,
    )
    model = _Model(
        ModelTurn(
            tool_calls=(ModelToolCall(name="query_published_findings", arguments={}),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_published_finding",
                arguments={
                    "objective_id": "objective-1",
                    "finding_id": "finding-1",
                },
            ),)
        ),
        ModelTurn(
            tool_calls=(ModelToolCall(
                name="inspect_published_finding",
                arguments={
                    "objective_id": "objective-1",
                    "finding_id": "finding-2",
                },
            ),)
        ),
        ModelTurn(content="两条结论的精确检查均需以实际返回为准。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((query, inspect)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="查看已发布结论的证据缺口并据此判断。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert model.tool_spec_names[1] == ("inspect_published_finding",)
    assert model.tool_spec_names[2] == ("inspect_published_finding",)
    assert inspect.executed_arguments == [
        {"objective_id": "objective-1", "finding_id": "finding-1"},
        {"objective_id": "objective-1", "finding_id": "finding-2"},
    ]
    assert "objective_id=objective-1, finding_id=finding-1" in model.contexts[1][-1].content
    assert "objective_id=objective-1, finding_id=finding-2" in model.contexts[1][-1].content


async def test_invalid_model_response_is_retried_once_without_unavailable_error() -> None:
    runner = ResearchAgentRunner(
        model=_Model(
            ModelResponseError(
                "empty response",
                reason="empty_response",
            ),
            ModelTurn(content="重试后得到有效回答。"),
        ),
        capabilities=CapabilityRegistry(
            (_Capability("get_collection_context", ToolRisk.READ),)
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="你好",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.error_code is None
    assert result.messages[-1].content == "重试后得到有效回答。"


async def test_repeated_invalid_model_response_is_distinguished_from_unavailable() -> None:
    runner = ResearchAgentRunner(
        model=_Model(
            *(ModelResponseError("empty response", reason="empty_response") for _ in range(6)),
        ),
        capabilities=CapabilityRegistry(
            (_Capability("get_collection_context", ToolRisk.READ),)
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="你好",
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "model_response_invalid"
    assert "技术中断" in result.messages[-1].content


async def test_unexpected_model_failure_remains_model_unavailable(caplog) -> None:
    runner = ResearchAgentRunner(
        model=_Model(RuntimeError("provider connection failed")),
        capabilities=CapabilityRegistry(
            (_Capability("get_collection_context", ToolRisk.READ),)
        ),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="你好",
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "model_unavailable"
    assert "provider connection failed" not in caplog.text
    record = next(record for record in caplog.records if "Research Agent model call failed" in record.message)
    assert json.loads(record.message.split("details=", 1)[1]) == {
        "exception_type": "RuntimeError", "http_status": None,
        "retryable": False, "reason": "unclassified_provider_error",
    }
