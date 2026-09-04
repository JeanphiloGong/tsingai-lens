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

    def respond(
        self,
        *,
        messages: tuple,
        tool_specs: tuple[ToolSpec, ...],
        text_delta_callback=None,  # noqa: ANN001
    ) -> ModelTurn:
        assert messages
        assert tool_specs
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


async def test_greeting_completes_without_calling_a_tool() -> None:
    capability = _Capability("get_collection_context", ToolRisk.READ)
    runner = ResearchAgentRunner(
        model=_Model(ModelTurn(content="你好，我可以帮助你分析当前文献集合。")),
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

    result = await runner.resume_approved_call(
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
    assert "step limit" in result.messages[-1].content.lower()


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
