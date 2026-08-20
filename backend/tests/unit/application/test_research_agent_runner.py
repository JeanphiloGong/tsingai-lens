from __future__ import annotations

from collections import deque
from typing import Any

from pydantic import BaseModel, ConfigDict

from application.chat import (
    AgentContext,
    AgentRunStatus,
    CapabilityExecutionContext,
    CapabilityRegistry,
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


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _QuestionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class _Model:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)

    def respond(
        self,
        *,
        messages: tuple,
        tool_specs: tuple[ToolSpec, ...],
    ) -> ModelTurn:
        assert messages
        assert tool_specs
        return self.turns.popleft()


class _Capability:
    def __init__(
        self,
        name: str,
        risk: ToolRisk,
        input_model: type[BaseModel] = _NoArguments,
        *,
        fail_with: Exception | None = None,
        result_status: ToolResultStatus = ToolResultStatus.SUCCEEDED,
    ) -> None:
        self.spec = ToolSpec(
            name=name,
            description=f"Test capability {name}",
            risk=risk,
            input_model=input_model,
        )
        self.fail_with = fail_with
        self.result_status = result_status
        self.executed_arguments: list[dict[str, Any]] = []
        self.executed_call_ids: list[str] = []

    def execute(
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
            data={"arguments": values, "collection_id": context.collection_id},
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


def test_greeting_completes_without_calling_a_tool() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(ModelTurn(content="你好，我可以帮助你分析当前文献集合。")),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="你好",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert [message.role for message in result.messages] == ["user", "assistant"]
    assert result.messages[-1].content.startswith("你好")
    assert result.tool_calls == ()
    assert capability.executed_arguments == []


def test_read_capability_result_returns_to_the_model_before_final_answer() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-1",
                    name="get_collection_context",
                    arguments={},
                )
            ),
            ModelTurn(content="这批论文主要研究增材制造参数和力学性能。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = runner.run_turn(
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
    assert capability.executed_call_ids == ["call-1"]


def test_authorization_is_deterministic_and_not_granted_by_prompt_text() -> None:
    assert not evaluate_authorization(ToolRisk.READ).requires_approval
    assert not evaluate_authorization(ToolRisk.DRAFT).requires_approval
    assert evaluate_authorization(ToolRisk.WRITE).requires_approval
    assert not evaluate_authorization(ToolRisk.WRITE).may_execute


def test_draft_capability_executes_without_write_approval() -> None:
    capability = _Capability(
        "propose_objective_drafts",
        ToolRisk.DRAFT,
        _QuestionArguments,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-1",
                    name="propose_objective_drafts",
                    arguments={"question": "energy input and ductility"},
                )
            ),
            ModelTurn(content="我整理了一个临时目标草稿。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="帮我整理成研究目标",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[0].risk is ToolRisk.DRAFT
    assert capability.executed_arguments == [
        {"question": "energy input and ductility"}
    ]


def test_write_capability_stops_for_approval_without_execution() -> None:
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
                    tool_call_id="call-1",
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                ),
            )
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="保存这个目标",
    )

    assert result.status is AgentRunStatus.APPROVAL_REQUIRED
    assert result.pending_approval is not None
    assert result.pending_approval.status is ToolCallStatus.APPROVAL_REQUIRED
    assert result.pending_approval.arguments_digest
    assert capability.executed_arguments == []


def test_approved_write_resumes_exact_call_before_returning_to_model() -> None:
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

    result = runner.resume_approved_call(
        context=_context(),
        previous_messages=prior_messages,
        approved_call=approved,
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert [message.role for message in result.messages[-2:]] == ["tool", "assistant"]
    assert capability.executed_arguments == [
        {"question": "How does energy input affect ductility?"}
    ]


def test_unknown_tool_is_returned_to_the_model_as_a_failed_result() -> None:
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-unknown",
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

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="读取服务器文件",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[0].status is ToolCallStatus.FAILED
    assert result.tool_results[0].error_code == "unknown_capability"
    assert "/etc/passwd" not in result.tool_results[0].error_message


def test_invalid_arguments_do_not_execute_capability() -> None:
    capability = _Capability(
        "propose_objective_drafts",
        ToolRisk.DRAFT,
        _QuestionArguments,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-invalid",
                    name="propose_objective_drafts",
                    arguments={"unexpected": "value"},
                )
            ),
            ModelTurn(content="我还需要一个明确的研究问题。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="帮我整理一下",
    )

    assert result.tool_results[0].error_code == "invalid_tool_arguments"
    assert capability.executed_arguments == []


def test_capability_exception_is_sanitized_before_returning_to_model() -> None:
    capability = _Capability(
        "get_collection_context",
        ToolRisk.READ,
        fail_with=RuntimeError("database password=do-not-expose"),
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-1",
                    name="get_collection_context",
                    arguments={},
                )
            ),
            ModelTurn(content="暂时无法读取 collection，请稍后重试。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="读取 collection",
    )

    assert result.tool_results[0].error_code == "capability_execution_failed"
    assert "password" not in result.tool_results[0].error_message
    assert "do-not-expose" not in result.tool_results[0].error_message


def test_queued_capability_result_returns_to_model_as_a_successful_observation() -> None:
    capability = _Capability(
        "start_objective_analysis",
        ToolRisk.READ,
        result_status=ToolResultStatus.QUEUED,
    )
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-queued",
                    name="start_objective_analysis",
                    arguments={},
                )
            ),
            ModelTurn(content="分析任务已启动，你可以稍后查看研究目标结果。"),
        ),
        capabilities=CapabilityRegistry((capability,)),
    )

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="开始分析",
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert result.tool_results[0].status is ToolResultStatus.QUEUED
    assert result.tool_results[0].resource_refs[0].resource_type == "objective_analysis"
    assert result.messages[-1].content.startswith("分析任务已启动")


def test_step_limit_stops_repeated_tool_calls() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-1",
                    name="get_collection_context",
                    arguments={},
                )
            ),
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-2",
                    name="get_collection_context",
                    arguments={},
                )
            ),
        ),
        capabilities=CapabilityRegistry((capability,)),
        max_model_steps=2,
    )

    result = runner.run_turn(
        context=_context(),
        previous_messages=(),
        user_message="不断读取",
    )

    assert result.status is AgentRunStatus.STEP_LIMIT_REACHED
    assert len(result.tool_calls) == 2
    assert len(capability.executed_arguments) == 2
    assert result.messages[-1].role == "assistant"
    assert "step limit" in result.messages[-1].content.lower()
