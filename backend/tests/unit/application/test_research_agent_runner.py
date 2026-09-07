from __future__ import annotations

from collections import deque
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from application.chat import (
    AgentContext,
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


class _Model:
    def __init__(self, *turns: ModelTurn | Exception) -> None:
        self.turns = deque(turns)
        self.tool_spec_names: list[tuple[str, ...]] = []
        self.contexts: list[tuple[ChatMessage, ...]] = []

    def respond(
        self,
        *,
        messages: tuple,
        tool_specs: tuple[ToolSpec, ...],
        text_delta_callback=None,  # noqa: ANN001
    ) -> ModelTurn:
        assert messages
        self.contexts.append(messages)
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
            "inspect_published_finding",
            "assess_objective_quality",
            "propose_research_plan",
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
            "browse_collection_papers",
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


async def test_filename_follow_up_keeps_paper_reads_without_exposing_writes() -> None:
    browser = _Capability("browse_collection_papers", ToolRisk.READ)
    search = _Capability("search_sources", ToolRisk.READ, _QuestionArguments)
    writer = _Capability("create_objective_candidate", ToolRisk.WRITE, _QuestionArguments)
    model = _Model(
        ModelTurn(tool_call=ModelToolCall(name="browse_collection_papers", arguments={})),
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


async def test_model_cannot_execute_a_registered_capability_hidden_for_this_turn() -> None:
    writer = _Capability("create_objective_candidate", ToolRisk.WRITE, _QuestionArguments)
    model = _Model(
        ModelTurn(
            tool_call=ModelToolCall(
                name="create_objective_candidate",
                arguments={"question": "How does energy input affect porosity?"},
            )
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
                tool_call=ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                )
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
                tool_call=ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                )
            ),
            ModelTurn(content="第一轮读取完成。"),
            ModelTurn(
                tool_call=ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                )
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
                tool_call=ModelToolCall(
                    name="propose_objective_drafts",
                    arguments={"question": "energy input and ductility"},
                )
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
                tool_call=ModelToolCall(
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                ),
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
        ChatMessage.assistant_tool_call(
            message_id="msg-2",
            session_id="chat-1",
            content="我准备保存这个候选目标。",
            tool_call_id="call-1",
            tool_name="create_objective_candidate",
            tool_arguments=approved.arguments,
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
                tool_call=ModelToolCall(
                    name="inspect_published_finding",
                    arguments={},
                )
            ),
            ModelTurn(
                tool_call=ModelToolCall(
                    name="propose_research_plan",
                    arguments={"question": "Test the supported preheating effect."},
                )
            ),
            ModelTurn(
                content="The plan draft is ready for your approval.",
                tool_call=ModelToolCall(
                    name="create_research_plan",
                    arguments={"question": "Test the supported preheating effect."},
                ),
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


async def test_unknown_tool_is_returned_to_the_model_as_a_failed_result() -> None:
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    name="read_file",
                    arguments={"path": "/etc/passwd"},
                )
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
                tool_call=ModelToolCall(
                    name="propose_objective_drafts",
                    arguments={"unexpected": "value"},
                )
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
                tool_call=ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                )
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
                tool_call=ModelToolCall(
                    name="start_objective_analysis",
                    arguments={},
                )
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


async def test_step_limit_stops_repeated_tool_calls() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                )
            ),
            ModelTurn(
                tool_call=ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                )
            ),
            ModelTurn(
                content=(
                    "我已读取两次 collection 概览，但仍未完成比较；目前只能给出"
                    "有限判断，建议继续指定要检查的论文。"
                )
            ),
        ),
        capabilities=CapabilityRegistry((capability,)),
        max_model_steps=2,
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="不断读取",
    )

    assert result.status is AgentRunStatus.STEP_LIMIT_REACHED
    assert len(result.tool_calls) == 2
    assert len(capability.executed_arguments) == 2
    assert result.messages[-1].role == "assistant"
    assert "step limit" not in result.messages[-1].content.lower()
    assert "有限判断" in result.messages[-1].content


async def test_step_limit_final_answer_keeps_the_active_research_request() -> None:
    user_request = (
        "比较这些论文；如果只能读一部分，请说明哪些已读、未读或失败。"
    )
    model = _Model(
        ModelTurn(
            tool_call=ModelToolCall(
                name="get_collection_context",
                arguments={},
            )
        ),
        ModelTurn(content="我只比较已读取的论文，并明确剩余范围。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry(
            (_Capability("get_collection_context", ToolRisk.READ),)
        ),
        max_model_steps=1,
    )

    result = await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=user_request,
    )

    assert result.status is AgentRunStatus.STEP_LIMIT_REACHED
    assert model.contexts[-1][-1].role.value == "user"
    assert "ACTIVE RESEARCH REQUEST" in model.contexts[-1][-1].content
    assert user_request in model.contexts[-1][-1].content


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
            tool_call=ModelToolCall(
                name="browse_collection_papers",
                arguments={},
            )
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


async def test_exact_finding_inspection_narrows_next_step_to_requested_draft() -> None:
    inspect = _Capability("inspect_published_finding", ToolRisk.READ)
    draft = _Capability("create_finding_draft", ToolRisk.DRAFT)
    query = _Capability("query_published_findings", ToolRisk.READ)
    model = _Model(
        ModelTurn(
            tool_call=ModelToolCall(
                name="inspect_published_finding",
                arguments={},
            )
        ),
        ModelTurn(content="我会形成一份保留温度边界的修订草案。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((query, inspect, draft)),
    )

    await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=(
            "查看已发布的研究结论；如果忽略了热处理条件，请提出修订草案，"
            "不要直接修改。"
        ),
    )

    assert model.tool_spec_names[1] == ("create_finding_draft",)


async def test_exact_finding_inspection_narrows_next_step_to_research_plan_draft() -> None:
    inspect = _Capability("inspect_published_finding", ToolRisk.READ)
    propose = _Capability("propose_research_plan", ToolRisk.DRAFT)
    plans = _Capability("inspect_research_plans", ToolRisk.READ)
    model = _Model(
        ModelTurn(
            tool_call=ModelToolCall(
                name="inspect_published_finding",
                arguments={},
            )
        ),
        ModelTurn(content="我会按约束形成完整的研究方案草案。"),
    )
    runner = ResearchAgentRunner(
        model=model,
        capabilities=CapabilityRegistry((inspect, propose, plans)),
    )

    await runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message=(
            "根据证据缺口提出研究方案草案，设备功率上限 300 W，每组最多 4 个"
            "样品，不要保存。"
        ),
    )

    assert model.tool_spec_names[1] == ("propose_research_plan",)


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
