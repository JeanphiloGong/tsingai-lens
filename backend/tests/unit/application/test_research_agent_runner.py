from __future__ import annotations

from domain.chat import ChatToolRequest

from collections import deque
import asyncio
from dataclasses import replace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

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


class _Model:
    def __init__(self, *turns: ModelTurn | Exception) -> None:
        self.turns = deque(turns)
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
        self.contexts.append(messages)
        self.request_limits.append((timeout_seconds, max_output_tokens))
        self.tool_spec_names.append(tuple(item.name for item in tool_specs))
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
            resource_refs=(
                ChatResourceRef(
                    resource_type="objective_analysis",
                    resource_id="objective-1:1",
                ),
            )
            if self.result_status is ToolResultStatus.QUEUED
            else (),
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


@pytest.mark.parametrize("failed", [False, True])
async def test_identical_observations_finalize_without_losing_results(failed: bool) -> None:
    read = _Capability("get_collection_context", ToolRisk.READ,
                       fail_with=RuntimeError("unavailable") if failed else None)
    result = await ResearchAgentRunner(
        model=_Model(*(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),)) for _ in range(3)),
                     ModelTurn(content="Only the inspected scope can be discussed.")),
        capabilities=CapabilityRegistry((read,)),
    ).run_turn(context=_context(), previous_messages=(), user_message="Read collection papers.")
    assert result.completion_reason is AgentCompletionReason.NO_PROGRESS
    assert len(result.tool_results) == len(read.executed_arguments) == 3
    assert result.warnings


async def test_usage_exhaustion_records_unexecuted_intent_then_finalizes() -> None:
    read = _Capability("get_collection_context", ToolRisk.READ)
    result = await ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),), usage=ModelUsage(80, 20, 100)),
                     ModelTurn(content="The paper remains unread.")),
        capabilities=CapabilityRegistry((read,)), limits=AgentRunLimits(max_model_tokens=100),
    ).run_turn(context=_context(), previous_messages=(), user_message="Read collection papers.")
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert read.executed_arguments == []
    assert result.tool_results[0].error_code == "resource_budget"


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
        limits=AgentRunLimits(max_elapsed_seconds=0.02),
    ).run_turn(context=_context(), previous_messages=(), user_message="Hello",
               text_delta_callback=deltas.append)

    assert result.status is AgentRunStatus.FAILED
    assert result.error_code == "provider_timeout"
    assert model.calls == 1
    assert cancelled.is_set()
    assert deltas == []


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


async def test_insufficient_batch_budget_rejects_every_call() -> None:
    read = _Capability("test_read", ToolRisk.READ)
    result = await ResearchAgentRunner(
        model=_Model(ModelTurn(tool_calls=(ModelToolCall(name=read.spec.name),) * 2),
                     ModelTurn(content="Both papers remain unread.")),
        capabilities=CapabilityRegistry((read,)), limits=AgentRunLimits(max_tool_calls=1),
    ).run_turn(context=_context(), previous_messages=(), user_message="Compare two papers.")
    assert result.completion_reason is AgentCompletionReason.RESOURCE_BUDGET
    assert len(result.tool_results) == 2
    assert read.executed_arguments == []


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
    model = _Model(ModelTurn(content="我会先回到原始来源核对 HIP 条件。"))
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
    model = _Model(ModelTurn(content="我会先根据论文概览形成临时阅读清单。"))
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

    explicit_search = ResearchAgentRunner._capability_names_for_intent(
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
    assert "will not present an unsupported" in result.messages[-1].content


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
    allowed = ResearchAgentRunner._capability_names_for_intent(
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
    allowed = ResearchAgentRunner._capability_names_for_intent(
        "查看当前状态",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "inspect_research_process" in allowed
    assert "get_collection_context" in allowed
    assert "browse_collection_papers" not in allowed


async def test_research_plan_question_does_not_expose_finding_writes() -> None:
    model = _Model(ModelTurn(content="我会先根据现有证据拟定研究方案草案。"))
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            tuple(
                _Capability(
                    name,
                    ToolRisk.READ
                    if name != "create_research_plan"
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
    model = _Model(ModelTurn(content="我会先核对结论、证据和适用边界。"))
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
    model = _Model(ModelTurn(content="我会先查看现有研究目标和分析状态。"))
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
            "browse_collection_papers",
            "propose_objective_drafts",
            "preview_research_scope",
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
        ("browse_collection_papers", "search_sources"),
    ]
    assert all("create_objective_candidate" not in names for names in model.tool_spec_names)


async def test_objective_write_is_hidden_until_the_user_requests_persistence() -> None:
    draft_model = _Model(ModelTurn(content="我可以先形成三个可审阅的问题草案。"))
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
    ]
    assert result.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert result.tool_results[0].data["collection_id"] == "col-1"
    assert capability.executed_arguments == [{}]
    assert capability.executed_call_ids == [result.tool_calls[0].tool_call_id]
    assert result.tool_results[0].tool_call_id == result.tool_calls[0].tool_call_id


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

    call_ids = [first.tool_calls[0].tool_call_id, second.tool_calls[0].tool_call_id]
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
    assert result.tool_calls[0].risk is ToolRisk.DRAFT
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

    assert result.tool_results[0].error_code == "invalid_tool_arguments"
    assert capability.executed_arguments == []


async def test_capability_exception_is_sanitized_before_returning_to_model() -> None:
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

    assert result.tool_results[0].error_code == "capability_execution_failed"
    assert "password" not in result.tool_results[0].error_message
    assert "do-not-expose" not in result.tool_results[0].error_message


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
        limits=AgentRunLimits(max_tool_calls=2),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="不断读取",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert len(result.tool_calls) == 2
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
        limits=AgentRunLimits(max_tool_calls=1),
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
        limits=AgentRunLimits(max_tool_calls=1),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="比较已读取的证据并说明剩余范围。",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert 30 < observed_timeouts[-1] <= observed_timeouts[0] <= 300


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
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((browse, inspect)),
        limits=AgentRunLimits(max_tool_calls=2),
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

    assert ResearchAgentRunner._has_successful_exact_source_read(
        results, (("paper-1", "text_window", "methods-1"),),
    )
    assert not ResearchAgentRunner._has_successful_exact_source_read(
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
        limits=AgentRunLimits(max_tool_calls=1),
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
    assert set(model.tool_spec_names[1]) == {"search_sources", "read_source"}


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


async def test_exact_finding_inspection_narrows_next_step_to_requested_draft() -> None:
    inspect = _Capability("inspect_published_finding", ToolRisk.READ, _FindingArguments)
    draft = _Capability("create_finding_draft", ToolRisk.DRAFT)
    query = _Capability("query_published_findings", ToolRisk.READ)
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
        capabilities=CapabilityRegistry((query, inspect, draft)),
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
    assert model.tool_spec_names[1] == ("create_finding_draft",)
    assert draft.executed_arguments == [{}]


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
        "inspect_document_sources",
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
    names = ResearchAgentRunner._capability_names_for_intent(
        "查看已保存的研究方案并修订后保存",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "inspect_research_plans" in names
    assert "revise_research_plan" in names
    assert "create_research_plan" in names


def test_explanation_does_not_enable_research_plan_capabilities() -> None:
    names = ResearchAgentRunner._capability_names_for_intent(
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
    names = ResearchAgentRunner._capability_names_for_intent(
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
    names = ResearchAgentRunner._capability_names_for_intent(
        "Read the paper's methods and results.",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "read_source" in names


def test_generic_plan_question_does_not_enable_research_plan_tools() -> None:
    names = ResearchAgentRunner._capability_names_for_intent(
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


def test_non_mutating_version_request_keeps_explicit_new_version_write() -> None:
    names = ResearchAgentRunner._capability_names_for_intent(
        "不要修改旧 Finding，请创建一个新版本。",
        has_source_context=False,
        prior_tool_names=set(),
    )

    assert "create_finding_version" in names


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
        for spec in runner._tool_specs_for_decision([message], [])
    }

    assert "browse_collection_papers" not in names
    assert "read_source" in names


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


async def test_research_plan_revision_reads_existing_plan_before_write() -> None:
    inspect = _Capability(
        "inspect_research_plans",
        ToolRisk.READ,
        _ObjectiveArguments,
        result_data={
            "objective_id": "objective-1",
            "plans": [{"plan_id": "plan-1"}],
        },
    )
    revise = _Capability("revise_research_plan", ToolRisk.WRITE)
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
                ModelToolCall(name="revise_research_plan", arguments={}),
            )
        ),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((inspect, revise)),
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="查看已保存的研究方案并修订后保存",
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
            ModelResponseError("empty response", reason="empty_response"),
            ModelResponseError("empty response", reason="empty_response"),
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
    assert "invalid response" in result.messages[-1].content


async def test_unexpected_model_failure_remains_model_unavailable() -> None:
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
