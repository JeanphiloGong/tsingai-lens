"""Bounded model/capability/result loop for one Research Agent turn."""

from __future__ import annotations

from asyncio import Semaphore, gather, wait_for
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import logging
from math import isfinite
import re
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from application.chat.capabilities import (
    AgentContext,
    CapabilityExecutionContext,
    CapabilityRegistry,
    ToolSpec,
)
from application.chat.context_builder import ChatContextBuilder, ChatModelContext
from application.chat.model import ChatModel, ModelResponseError, ModelTurn, ModelUsage
from domain.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatSourceContext,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolResultStatus,
    ToolRisk,
)
from utils.logger import get_request_id


logger = logging.getLogger(__name__)

_TrajectoryCheckpoint = Callable[
    [
        tuple[ChatMessage, ...],
        tuple[ChatToolCall, ...],
        tuple[ChatToolResult, ...],
    ],
    Awaitable[None],
]

_REQUIRED_ACTION_FAILURE_MESSAGE = (
    "I could not complete the required source-backed research action, so I will "
    "not present an unsupported result. Please retry or narrow the request."
)
_MODEL_RESPONSE_RETRY_LIMIT = 1
_REQUIRED_ACTION_RETRY_LIMIT = 1
_FINAL_ANSWER_INSTRUCTION = (
    "The bounded research-reading budget is now exhausted. Give the researcher "
    "the best useful final answer supported by the completed trajectory. State "
    "what was inspected, what remains unread or failed, the scientific "
    "uncertainty, and one practical next step. Do not request another tool and "
    "do not mention internal budgets, tool schemas, or hidden reasoning. A paper "
    "identity survey or a search match is not an exact Source read. Do not claim "
    "that a paper was read unless the reading ledger below records an exact Source. "
    "If the researcher requested more papers than the collection contains, state "
    "the actual collection total and do not invent missing or unread papers."
)
_INCOMPLETE_SCOPE_WARNING = (
    "The answer covers only inspected Sources; unread or failed work remains unresolved."
)

_COLLECTION_READ_CAPABILITIES = {
    "get_collection_context",
    "browse_collection_papers",
}
_SOURCE_READ_CAPABILITIES = {
    *_COLLECTION_READ_CAPABILITIES,
    "search_sources",
    "inspect_document_sources",
    "read_source",
    "inspect_table",
}
_SOURCE_GROUNDED_CAPABILITIES = {
    *_COLLECTION_READ_CAPABILITIES,
    "search_sources",
    "read_source",
    "inspect_table",
}
_PROCESS_CAPABILITIES = {
    "get_collection_context",
    "inspect_research_process",
    "inspect_objective_analysis",
}
_OBJECTIVE_CAPABILITIES = {
    "get_collection_context",
    "browse_collection_papers",
    "preview_research_scope",
    "propose_objective_drafts",
}
_FINDING_CAPABILITIES = {
    *_SOURCE_READ_CAPABILITIES,
    "query_published_findings",
    "inspect_published_finding",
    "inspect_objective_analysis",
    "assess_objective_quality",
    "create_finding_draft",
    "create_evidence_draft",
    "derive_objective",
}
_FINDING_READ_CAPABILITIES = {
    "get_collection_context",
    "query_published_findings",
    "inspect_published_finding",
    "inspect_objective_analysis",
    "assess_objective_quality",
}
_RESEARCH_PLAN_CAPABILITIES = {
    "get_collection_context",
    "query_published_findings",
    "inspect_published_finding",
    "assess_objective_quality",
    "inspect_research_plans",
    "propose_research_plan",
}
_RESEARCH_PLAN_READ_CAPABILITIES = {
    "get_collection_context",
    "query_published_findings",
    "inspect_published_finding",
    "assess_objective_quality",
    "inspect_research_plans",
}
_WRITE_CAPABILITIES = {
    "start_research_process",
    "create_objective_candidate",
    "confirm_objective",
    "start_objective_analysis",
    "record_finding_feedback",
    "curate_finding",
    "create_finding_version",
    "create_evidence_version",
    "publish_agent_objective_analysis",
    "create_research_plan",
    "revise_research_plan",
}
_KNOWN_CAPABILITIES = {
    *_SOURCE_READ_CAPABILITIES,
    *_PROCESS_CAPABILITIES,
    *_OBJECTIVE_CAPABILITIES,
    *_FINDING_CAPABILITIES,
    *_RESEARCH_PLAN_CAPABILITIES,
    *_WRITE_CAPABILITIES,
}

_NO_TOOL_PHRASES = (
    "不用查",
    "不要查",
    "无需查",
    "不查论文",
    "不用检索",
    "不要检索",
    "不用操作",
    "不要操作",
    "without searching",
    "do not search",
    "don't search",
    "without tools",
)
_NO_WRITE_PHRASES = (
    "不要保存",
    "不保存",
    "先不要保存",
    "不要直接修改",
    "不要修改",
    "不要发布",
    "不发布",
    "先不要发布",
    "without saving",
    "do not save",
    "don't save",
    "without modifying",
    "do not modify",
    "don't modify",
    "without publishing",
    "do not publish",
    "don't publish",
)
_PAPER_TERMS = (
    "论文",
    "文献",
    "collection",
    "paper",
    "摘要",
    "标题",
    "文件名",
    "作者",
    "article",
    "literature",
    "source",
    "表格",
    "图注",
    "阅读",
    "读取",
)
_COMPARISON_TERMS = (
    "比较",
    "是否都支持",
    "可比",
    "compare",
    "supports",
    "support",
    "comparable",
)
_SOURCE_GROUNDED_TERMS = (
    "根据这些论文",
    "根据论文",
    "基于这些论文",
    "基于论文",
    "文献中",
    "文献依据",
    "论文依据",
    "原文依据",
    "搜索相关论文",
    "检索相关论文",
    "搜索论文",
    "检索论文",
    "说说你的看法",
    "谈谈你的看法",
    "谈谈看法",
    "你的判断",
    "谈谈判断",
    "给出判断",
    "提出思路",
    "给出思路",
    "研究启发",
    "based on these papers",
    "based on the papers",
    "from the literature",
    "literature-based",
    "literature based",
    "what do you think",
)
_SOURCE_DETAIL_TERMS = (
    "原文",
    "正文",
    "来源",
    "来源证据",
    "数值",
    "数据",
    "实验条件",
    "测试条件",
    "表格",
    "图注",
    "方法",
    "结果",
    "方法部分",
    "结果部分",
    "深入",
    "精读",
    "核对",
    "验证数字",
    "逐段",
    "表 ",
    "图 ",
    "一起看",
    "evidence",
    "method",
    "result",
    "table",
    "figure",
    "inspect",
    "read",
    "check",
)
_OBJECTIVE_TERMS = (
    "研究目标",
    "研究问题",
    "目标",
    "目标草稿",
    "问题草稿",
    "候选目标",
    "objective",
    "research question",
    "follow-up question",
    "propose a focused question",
    "propose a research question",
    "draft a question",
    "suggest research questions",
    "派生",
    "推导",
    "derive",
    "derive the next",
)
_FINDING_TERMS = (
    "结论",
    "证据",
    "finding",
    "evidence",
    "conclusion",
    "reviewed evidence",
    "conclusion",
    "quality",
    "gap",
    "gaps",
    "支持",
    "反例",
    "依据",
    "证据缺口",
    "冲突",
    "相反",
    "不一致",
    "候选机制",
    "一篇论文",
    "另一篇",
)
_FINDING_RECORD_TERMS = (
    "已发布",
    "研究结论",
    "已有分析",
    "分析结果",
    "证据缺口",
    "依据",
    "published finding",
    "published conclusion",
    "existing analysis",
    "quality ledger",
    "evidence gap",
)
_PLAN_TERMS = (
    "研究方案",
    "实验方案",
    "实验设计",
    "下一步实验",
    "怎么验证",
    "如何验证",
    "research plan",
    "experiment plan",
    "experimental plan",
    "follow-up experiment",
    "follow up experiment",
)
_PLAN_READ_TERMS = (
    "查看",
    "读取",
    "列出",
    "当前方案",
    "已有方案",
    "已保存的方案",
    "saved plan",
    "existing plan",
    "list plans",
    "inspect plan",
)
_PROCESS_TERMS = (
    "当前状态",
    "目前状态",
    "现在的状态",
    "current status",
    "当前情况",
    "现在怎么样",
    "进度",
    "论文处理状态",
    "文档处理状态",
    "任务处理状态",
    "collection 处理状态",
    "分析状态",
    "研究状态",
    "目标状态",
    "任务状态",
    "collection 状态",
    "objective 状态",
    "处理到",
    "处理完",
    "为什么失败",
    "失败原因",
    "处理失败",
    "为什么慢",
    "哪里了",
    "progress",
    "how far",
    "process status",
    "processing status",
    "analysis status",
    "collection status",
    "objective status",
    "task status",
    "why failed",
    "analysis failed",
    "processing failed",
    "start understanding",
    "理解这些论文",
    "准备这些论文",
    "form research questions",
)
_PERSIST_TERMS = (
    "保存",
    "创建",
    "记录",
    "写入",
    "发布",
    "persist",
    "save",
    "create",
    "record",
    "publish",
)
_REVIEW_ACTION_TERMS = (
    "mark",
    "review",
    "correct",
    "overclaim",
    "partly correct",
    "部分正确",
    "标记",
    "复核",
    "纠正",
    "质疑",
)


def _mentions_terms(text: str, terms: tuple[str, ...]) -> bool:
    """Match English intent words without matching them inside another word."""
    normalized_text = text.casefold()
    for term in terms:
        normalized = term.casefold().strip()
        if not normalized:
            continue
        if re.search(r"[a-z0-9]", normalized):
            pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
            if re.search(pattern, normalized_text):
                return True
        elif normalized in normalized_text:
            return True
    return False


def _has_explicit_immutable_write(text: str) -> bool:
    return _mentions_terms(
        text,
        ("新版本", "new version", "immutable version"),
    ) and _mentions_terms(
        text,
        ("保存", "创建", "记录", "写入", "save", "create", "record", "persist"),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRunStatus(StrEnum):
    COMPLETED = "completed"
    APPROVAL_REQUIRED = "approval_required"
    FAILED = "failed"

class AgentCompletionReason(StrEnum):
    MODEL_ANSWER = "model_answer"
    RESOURCE_BUDGET = "resource_budget"
    NO_PROGRESS = "no_progress"
    EMERGENCY_CEILING = "emergency_ceiling"


@dataclass(frozen=True)
class AgentRunLimits:
    max_elapsed_seconds: float = 300.0
    max_tool_calls: int = 24
    max_model_tokens: int = 160_000
    max_consecutive_no_progress: int = 2
    emergency_max_model_cycles: int = 64
    max_parallel_reads: int = 4
    max_model_output_tokens: int = 16_384
    max_finalization_seconds: float = 300.0
    max_finalization_output_tokens: int = 8_192

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
            if not name.endswith("_seconds") and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")


@dataclass
class _RunProgress:
    limits: AgentRunLimits
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    started_at: float = field(default_factory=lambda: monotonic())
    model_cycles: int = 0
    model_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    unreported_model_calls: int = 0
    executed_tool_calls: int = 0
    seen_observations: set[str] = field(default_factory=set)
    consecutive_no_progress: int = 0
    resource_refs: set[tuple[str, str]] = field(default_factory=set)

    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.max_elapsed_seconds - (monotonic() - self.started_at))

    def stop_before_model(self) -> AgentCompletionReason | None:
        if self.model_cycles >= self.limits.emergency_max_model_cycles:
            return AgentCompletionReason.EMERGENCY_CEILING
        if (self.remaining_seconds() <= 0
                or self.model_tokens >= self.limits.max_model_tokens
                or self.executed_tool_calls >= self.limits.max_tool_calls):
            return AgentCompletionReason.RESOURCE_BUDGET
        if self.consecutive_no_progress >= self.limits.max_consecutive_no_progress:
            return AgentCompletionReason.NO_PROGRESS
        return None

    def record_model_usage(self, usage: ModelUsage | None) -> None:
        if usage is not None:
            self.model_tokens += usage.total_tokens
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
        else:
            self.unreported_model_calls += 1

    def observe(self, call: ChatToolCall, result: ChatToolResult) -> None:
        data = dict(result.data)
        has_source_observation = (
            result.status is ToolResultStatus.SUCCEEDED
            and any(ref.resource_type == "source" for ref in result.resource_refs)
        )
        # Source navigation echoes the query; changing its wording is not new content.
        if has_source_observation and call.name in {"search_sources", "inspect_document_sources", "inspect_table"}:
            data.pop("query", None)
        payload = {
            "tool": call.name,
            "status": result.status.value, "data": data,
            "resource_refs": sorted(
                (ref.resource_type, ref.resource_id, ref.href or "")
                for ref in result.resource_refs
            ),
            "error_code": result.error_code,
            "warnings": result.warnings,
        }
        if not has_source_observation:
            # Distinct failed or empty searches must keep their requested scope.
            payload["arguments"] = dict(call.arguments)
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.seen_observations.add(digest)
        self.resource_refs.update((ref.resource_type, ref.resource_id) for ref in result.resource_refs)

    def trace(self, context: AgentContext, *, phase: str, capability_names: tuple[str, ...] = (),
              requested_count: int = 0, new_resources: int = 0,
              termination_reason: str | None = None, final_answer: bool = False) -> None:
        payload = {
            "session_id": context.session_id, "request_id": get_request_id(), "phase": phase,
            "cycle_index": self.model_cycles, "selected_capability_names": capability_names,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "total_tokens": self.model_tokens, "unreported_model_calls": self.unreported_model_calls,
            "requested_tool_count": requested_count, "executed_tool_count": self.executed_tool_calls,
            "new_resource_reference_count": new_resources,
            "observation_digest_changed": self.consecutive_no_progress == 0,
            "elapsed_ms": round((monotonic() - self.started_at) * 1000),
            "remaining_tool_budget": max(0, self.limits.max_tool_calls - self.executed_tool_calls),
            "remaining_token_budget": max(0, self.limits.max_model_tokens - self.model_tokens),
            "termination_reason": termination_reason, "final_answer_present": final_answer,
        }
        logger.info("Research Agent cycle %s", json.dumps(payload, separators=(",", ":")))
        if self.progress_callback is not None:
            self.progress_callback(payload)


@dataclass(frozen=True)
class AgentRunResult:
    status: AgentRunStatus
    messages: tuple[ChatMessage, ...]
    tool_calls: tuple[ChatToolCall, ...] = ()
    tool_results: tuple[ChatToolResult, ...] = ()
    completion_reason: AgentCompletionReason | None = None
    warnings: tuple[str, ...] = ()
    pending_approval: ChatToolCall | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status is AgentRunStatus.COMPLETED:
            if self.completion_reason is None or self.error_code is not None:
                raise ValueError("completed run requires a reason and no error code")
        elif self.completion_reason is not None:
            raise ValueError("only completed runs have a completion reason")

class ResearchAgentRunner:
    def __init__(
        self,
        *,
        model: ChatModel,
        capabilities: CapabilityRegistry,
        context_builder: ChatContextBuilder | None = None,
        limits: AgentRunLimits | None = None,
    ) -> None:
        self.model = model
        self.capabilities = capabilities
        self.context_builder = context_builder or ChatContextBuilder()
        self.limits = limits or AgentRunLimits()

    async def run_turn(
        self,
        *,
        context: AgentContext,
        previous_messages: tuple[ChatMessage, ...],
        user_message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentRunResult:
        progress = _RunProgress(self.limits, progress_callback=progress_callback)
        messages = [
            *previous_messages,
            ChatMessage.user(
                message_id=self._message_id(),
                session_id=context.session_id,
                content=user_message,
                created_at=_now_iso(),
                source_contexts=source_contexts,
            ),
        ]
        calls: list[ChatToolCall] = []
        results: list[ChatToolResult] = []
        await self._checkpoint(checkpoint, messages, calls, results)
        return await self._continue(
            context,
            messages,
            calls,
            results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
            inherited_completed_writes=set(),
            progress=progress,
        )

    async def resume_claimed_call(
        self,
        *,
        context: AgentContext,
        previous_messages: tuple[ChatMessage, ...],
        claimed_call: ChatToolCall,
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentRunResult:
        progress = _RunProgress(self.limits, progress_callback=progress_callback)
        self._validate_claimed_call(context, claimed_call)
        messages = list(previous_messages)
        inherited_completed_writes = self._completed_write_names(messages)
        calls = [claimed_call]
        results: list[ChatToolResult] = []
        handler = self.capabilities.get(claimed_call.name)
        if handler is None or handler.spec.risk is not ToolRisk.WRITE:
            call, result = self._failure(
                claimed_call,
                "capability_unavailable",
                "The approved research capability is not available.",
            )
        else:
            error = self._batch_error(((claimed_call, handler),), messages)
            if not error:
                progress.executed_tool_calls += 1
            call, result = (
                self._failure(claimed_call, *error) if error
                else await self._execute_one(context, claimed_call, handler)
            )
        calls[-1] = call
        results.append(result)
        messages.append(self._result_message(context, result))
        await self._checkpoint(checkpoint, messages, calls, results)
        return await self._continue(
            context,
            messages,
            calls,
            results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
            inherited_completed_writes=inherited_completed_writes,
            progress=progress,
        )

    async def _continue(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        checkpoint: _TrajectoryCheckpoint | None,
        text_delta_callback: Callable[[str], None] | None,
        inherited_completed_writes: set[str],
        progress: _RunProgress,
    ) -> AgentRunResult:
        while True:
            stop_reason = progress.stop_before_model()
            if stop_reason is not None:
                return await self._finalize_with_current_evidence(
                    stop_reason, progress, context, messages, calls, results,
                    checkpoint=checkpoint, text_delta_callback=text_delta_callback,
                )
            response_retries = 0
            required_action_retries = 0
            required_action_instruction: ChatMessage | None = None
            while True:
                stop_reason = progress.stop_before_model()
                if stop_reason is not None:
                    return await self._finalize_with_current_evidence(
                        stop_reason, progress, context, messages, calls, results,
                        checkpoint=checkpoint, text_delta_callback=text_delta_callback,
                    )
                try:
                    tool_specs = self._tool_specs_for_decision(
                        messages,
                        calls,
                        inherited_completed_writes=inherited_completed_writes,
                    )
                    tool_names = tuple(spec.name for spec in tool_specs)
                    schema_chars = sum(
                        len(
                            json.dumps(
                                spec.model_schema(),
                                ensure_ascii=True,
                                separators=(",", ":"),
                            )
                        )
                        for spec in tool_specs
                    )
                    logger.info(
                        "Research Agent capabilities selected step=%d max_steps=%d "
                        "tool_count=%d schema_chars=%d tools=%s",
                        progress.model_cycles + 1,
                        self.limits.emergency_max_model_cycles,
                        len(tool_specs),
                        schema_chars,
                        ",".join(tool_names) or "none",
                    )
                    decision_messages = tuple(messages)
                    stage_instruction: ChatMessage | None = None
                    if required_action_instruction is not None:
                        decision_messages = (*decision_messages, required_action_instruction)
                    else:
                        stage_instruction = self._stage_instruction(
                            context,
                            tool_names,
                            calls,
                            successful_results=self._active_successful_results_by_name(messages),
                        )
                        if stage_instruction is not None:
                            decision_messages = (*decision_messages, stage_instruction)
                    if (
                        required_action_instruction is None
                        and stage_instruction is None
                        and not tool_specs
                        and self._latest_structured_deliverable(results) is not None
                    ):
                        decision_messages = (
                            *decision_messages,
                            self._answer_instruction(
                                context,
                                messages,
                                calls,
                                results,
                                budget_exhausted=False,
                            ),
                        )
                    turn = await self._respond(
                        self.context_builder.for_model(
                            decision_messages, active_user_message_id=next(
                                message.message_id for message in reversed(messages) if message.role is ChatMessageRole.USER
                            ),
                        ),
                        tool_specs, progress, text_delta_callback,
                    )
                    progress.trace(context, phase="model", capability_names=tool_names,
                                   requested_count=len(turn.tool_calls))
                except ModelResponseError as exc:
                    model_name = str(
                        getattr(self.model, "model", None)
                        or type(self.model).__name__
                    )
                    logger.warning(
                        "Research Agent model response invalid model=%s reason=%s "
                        "retryable=%s partial_content=%s",
                        model_name,
                        exc.reason,
                        exc.retryable,
                        exc.partial_content,
                    )
                    if (
                        exc.retryable
                        and not exc.partial_content
                        and response_retries < _MODEL_RESPONSE_RETRY_LIMIT
                    ):
                        response_retries += 1
                        logger.info(
                            "Retrying Research Agent model response model=%s "
                            "attempt=%d",
                            model_name,
                            response_retries + 1,
                        )
                        continue
                    messages.append(
                        self._assistant(
                            context,
                            "The research model returned an invalid response for "
                            "this turn. Please retry.",
                        )
                    )
                    await self._checkpoint(checkpoint, messages, calls, results)
                    progress.trace(context, phase="terminal", termination_reason="model_response_invalid")
                    return self._result(
                        AgentRunStatus.FAILED,
                        messages,
                        calls,
                        results,
                        "model_response_invalid",
                    )
                except Exception as exc:  # noqa: BLE001
                    model_name = str(
                        getattr(self.model, "model", None)
                        or type(self.model).__name__
                    )
                    logger.exception(
                        "Research Agent model call failed model=%s "
                        "exception_type=%s",
                        model_name,
                        type(exc).__name__,
                    )
                    provider_timeout = "timeout" in type(exc).__name__.lower()
                    messages.append(
                        self._assistant(
                            context,
                            (
                                "The research model timed out for this turn; "
                                "inspected results were preserved."
                            )
                            if provider_timeout
                            else "The research model is unavailable for this turn.",
                        )
                    )
                    await self._checkpoint(checkpoint, messages, calls, results)
                    progress.trace(
                        context,
                        phase="terminal",
                        termination_reason=(
                            "provider_timeout" if provider_timeout else "model_unavailable"
                        ),
                    )
                    return self._result(
                        AgentRunStatus.FAILED,
                        messages,
                        calls,
                        results,
                        "provider_timeout" if provider_timeout else "model_unavailable",
                    )
                required_tool = self._required_tool_before_answer(
                    tool_names,
                    successful_results=self._active_successful_results_by_name(messages),
                )
                if (
                    not turn.tool_calls
                    and required_tool is not None
                    and required_action_retries < _REQUIRED_ACTION_RETRY_LIMIT
                ):
                    required_action_retries += 1
                    required_action_instruction = ChatMessage.user(
                        message_id=self._message_id(),
                        session_id=context.session_id,
                        content=(
                            "The active researcher explicitly requested a structured "
                            "research deliverable. Do not answer yet. Use the prior "
                            "research results and call the required research "
                            f"action, `{required_tool}`, now."
                        ),
                        created_at=_now_iso(),
                    )
                    logger.info(
                        "Research Agent retrying premature answer required_tool=%s",
                        required_tool,
                    )
                    continue
                if not turn.tool_calls and required_tool is not None:
                    logger.warning(
                        "Research Agent required action not completed tool=%s",
                        required_tool,
                    )
                    messages.append(
                        self._assistant(context, _REQUIRED_ACTION_FAILURE_MESSAGE)
                    )
                    await self._checkpoint(checkpoint, messages, calls, results)
                    progress.trace(context, phase="terminal", termination_reason="required_research_action_not_completed")
                    return self._result(
                        AgentRunStatus.FAILED,
                        messages,
                        calls,
                        results,
                        "required_research_action_not_completed",
                    )
                break

            if not turn.tool_calls:
                reason = progress.stop_before_model() or AgentCompletionReason.MODEL_ANSWER
                messages.append(self._assistant(context, turn.content))
                await self._checkpoint(checkpoint, messages, calls, results)
                progress.trace(context, phase="terminal", termination_reason=reason.value, final_answer=True)
                return self._result(
                    AgentRunStatus.COMPLETED, messages, calls, results,
                    completion_reason=reason,
                    warnings=(_INCOMPLETE_SCOPE_WARNING,) if reason is not AgentCompletionReason.MODEL_ANSWER else (),
                )

            requested = self._requested_calls(
                context,
                messages,
                turn,
                allowed_names=set(tool_names),
            )
            batch_start = len(calls)
            calls.extend(call for call, _ in requested)
            await self._checkpoint(checkpoint, messages, calls, results)
            stop_reason = progress.stop_before_model()
            if progress.executed_tool_calls + len(requested) > self.limits.max_tool_calls:
                stop_reason = AgentCompletionReason.RESOURCE_BUDGET
            error = self._batch_error(requested, messages)
            if stop_reason:
                error = ("resource_budget", "These Sources or actions remain uninspected or unexecuted in this turn.")
            if error:
                completed = tuple(self._failure(call, *error) for call, _ in requested)
            elif len(requested) == 1 and requested[0][0].risk is ToolRisk.WRITE:
                pending = requested[0][0].require_approval()
                calls[-1] = pending
                await self._checkpoint(checkpoint, messages, calls, results)
                progress.trace(context, phase="terminal", termination_reason="approval_required")
                return AgentRunResult(
                    status=AgentRunStatus.APPROVAL_REQUIRED,
                    messages=tuple(messages), tool_calls=tuple(calls),
                    tool_results=tuple(results), pending_approval=pending,
                )
            else:
                requested = tuple((call.start(_now_iso()), handler) for call, handler in requested)
                calls[batch_start:] = [call for call, _ in requested]
                await self._checkpoint(checkpoint, messages, calls, results)
                progress.executed_tool_calls += len(requested)
                completed = await self._execute_read_batch(context, requested, progress)
            old_observation_count = len(progress.seen_observations)
            old_resource_count = len(progress.resource_refs)
            prior_no_progress = progress.consecutive_no_progress
            for index, (call, capability_result) in enumerate(completed):
                calls[batch_start + index] = call
                results.append(capability_result)
                messages.append(self._result_message(context, capability_result))
                progress.observe(call, capability_result)
            progress.consecutive_no_progress = (
                prior_no_progress + 1 if len(progress.seen_observations) == old_observation_count else 0
            )
            await self._checkpoint(checkpoint, messages, calls, results)
            progress.trace(context, phase="tools", capability_names=tool_names, requested_count=len(requested),
                           new_resources=len(progress.resource_refs) - old_resource_count,
                           termination_reason=stop_reason.value if stop_reason else None)
            if stop_reason:
                return await self._finalize_with_current_evidence(
                    stop_reason, progress, context, messages, calls, results,
                    checkpoint=checkpoint, text_delta_callback=text_delta_callback,
                )

    async def _respond(
        self,
        model_context: ChatModelContext,
        tool_specs: tuple[ToolSpec, ...],
        progress: _RunProgress,
        text_delta_callback: Callable[[str], None] | None,
        *,
        finalizing: bool = False,
    ) -> ModelTurn:
        timeout = progress.remaining_seconds()
        output_limit = min(
            self.limits.max_model_output_tokens,
            self.limits.max_model_tokens - progress.model_tokens,
        )
        if finalizing:
            timeout = min(timeout, self.limits.max_finalization_seconds)
            output_limit = self.limits.max_finalization_output_tokens
        if timeout <= 0:
            raise TimeoutError("research turn deadline reached")
        arguments: dict[str, Any] = {
            "context": model_context,
            "tool_specs": tool_specs,
            "timeout_seconds": timeout,
            "max_output_tokens": output_limit,
        }
        if text_delta_callback is not None:
            arguments["text_delta_callback"] = text_delta_callback
        progress.model_cycles += 1
        try:
            turn = await wait_for(self.model.respond(**arguments), timeout=timeout)
        except ModelResponseError as exc:
            progress.record_model_usage(exc.usage)
            raise
        except BaseException:
            # Cancellation may prevent the provider's usage trailer from arriving.
            progress.record_model_usage(None)
            raise
        progress.record_model_usage(turn.usage)
        return turn

    async def _finalize_with_current_evidence(
        self,
        reason: AgentCompletionReason,
        progress: _RunProgress,
        context: AgentContext,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        checkpoint: _TrajectoryCheckpoint | None,
        text_delta_callback: Callable[[str], None] | None,
    ) -> AgentRunResult:
        """Give the model one answer-only turn after tool decisions are spent."""

        instruction = self._answer_instruction(
            context,
            messages,
            calls,
            results,
            budget_exhausted=True,
        )
        logger.info(
            "Research Agent final answer reason=%s tools=none", reason.value,
        )
        try:
            turn = await self._respond(
                self.context_builder.for_model(
                    (*messages, instruction), active_user_message_id=next(
                        message.message_id for message in reversed(messages) if message.role is ChatMessageRole.USER
                    ),
                ),
                (), progress, text_delta_callback, finalizing=True,
            )
            if turn.tool_calls or not turn.content:
                raise ValueError("final answer must be answer-only")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Research Agent final answer failed exception_type=%s",
                type(exc).__name__,
            )
            messages.append(self._assistant(context, "The inspected results were preserved, but a final answer could not be completed. Please retry."))
            progress.trace(context, phase="finalize", termination_reason="final_answer_unavailable")
            await self._checkpoint(checkpoint, messages, calls, results)
            return self._result(AgentRunStatus.FAILED, messages, calls, results, "final_answer_unavailable")
        messages.append(self._assistant(context, turn.content))
        progress.trace(context, phase="finalize", termination_reason=reason.value, final_answer=True)
        await self._checkpoint(checkpoint, messages, calls, results)
        return self._result(
            AgentRunStatus.COMPLETED, messages, calls, results,
            completion_reason=reason,
            warnings=(_INCOMPLETE_SCOPE_WARNING,),
        )

    def _answer_instruction(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        budget_exhausted: bool,
    ) -> ChatMessage:
        active_request = self._active_user_request(messages)
        structured_deliverable = self._latest_structured_deliverable(results)
        deliverable_section = (
            "\n\nCOMPLETED STRUCTURED DELIVERABLE "
            "(return this result; it is not an exact paper Source read):\n"
            f"{structured_deliverable}"
            if structured_deliverable is not None
            else ""
        )
        lead = (
            _FINAL_ANSWER_INSTRUCTION
            if budget_exhausted
            else (
                "The requested structured research action is complete. Give the "
                "researcher the useful final answer from the completed trajectory. "
                "Do not request another tool and do not restart onboarding."
            )
        )
        return ChatMessage.user(
            message_id=self._message_id(),
            session_id=context.session_id,
            content=(
                f"{lead}\n\n"
                "ACTIVE RESEARCH REQUEST (answer this request; do not restart "
                f"onboarding):\n{active_request}\n\n"
                f"READING LEDGER:\n{self._reading_ledger(calls, results)}"
                f"{deliverable_section}"
            ),
            created_at=_now_iso(),
        )

    def _requested_calls(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        turn: Any,
        *,
        allowed_names: set[str],
    ) -> tuple[tuple[ChatToolCall, Any], ...]:
        assistant_message_id = self._message_id()
        requested = []
        for position, model_call in enumerate(turn.tool_calls):
            registered = self.capabilities.get(model_call.name)
            call = ChatToolCall.requested(
                tool_call_id=self._tool_call_id(), session_id=context.session_id,
                assistant_message_id=assistant_message_id, position=position,
                name=model_call.name, arguments=model_call.arguments,
                risk=registered.spec.risk if registered else ToolRisk.UNKNOWN,
            )
            requested.append((call, registered if model_call.name in allowed_names else None))
        messages.append(
            ChatMessage.assistant_tool_calls(
                message_id=assistant_message_id,
                session_id=context.session_id,
                content=turn.content,
                tool_calls=tuple(call.to_request() for call, _ in requested),
                created_at=_now_iso(),
            )
        )
        return tuple(requested)

    def _batch_error(self, requested, messages) -> tuple[str, str] | None:
        successful_results = self._active_successful_results_by_name(messages)
        for call, handler in requested:
            if handler is None:
                code = "capability_unavailable_for_turn" if self.capabilities.get(call.name) else "unknown_capability"
                return code, "The requested research capability is not available."
            if call.risk is ToolRisk.UNKNOWN:
                return "capability_not_authorized", "The research capability is not authorized."
            try:
                handler.spec.input_model.model_validate(call.arguments)
            except ValidationError as exc:
                details = "; ".join(
                    f"{'.'.join(str(part) for part in error['loc']) or 'arguments'} ({error['type']})"
                    for error in exc.errors(include_input=False, include_url=False)[:8]
                )
                return "invalid_tool_arguments", f"Invalid research capability arguments: {details}."
            if call.name == "inspect_published_finding":
                allowed = self._published_finding_candidates(successful_results)
                finding = (str(call.arguments.get("objective_id") or "").strip(), str(call.arguments.get("finding_id") or "").strip())
                if allowed and finding not in allowed:
                    return "finding_reference_not_in_query", "Inspect a Finding identifier returned by the preceding query."
        if len(requested) > 1 and any(call.risk is not ToolRisk.READ for call, _ in requested):
            return "invalid_tool_batch", "Draft and write actions must be requested individually."
        for call, _handler in requested:
            if call.name not in {"create_evidence_draft", "create_evidence_version"}:
                continue
            source_identity = (
                str(call.arguments.get("document_id") or "").strip(),
                str(call.arguments.get("source_kind") or "").strip(),
                str(call.arguments.get("source_ref") or "").strip(),
            )
            if not self._has_successful_exact_source_read(
                successful_results,
                (source_identity,),
            ):
                return (
                    "source_read_incomplete",
                    "Read the complete canonical Source before recording Evidence.",
                )
        return None

    async def _execute_read_batch(self, context, requested, progress):
        semaphore = Semaphore(self.limits.max_parallel_reads)

        async def bounded(call, handler):
            async with semaphore:
                try:
                    return await wait_for(self._execute_one(context, call, handler), timeout=progress.remaining_seconds())
                except TimeoutError:
                    return self._failure(call, "capability_timeout", "The Source or action could not be completed in this turn.")

        if all(handler.spec.parallel_safe for _, handler in requested):
            return tuple(await gather(*(bounded(call, handler) for call, handler in requested)))
        return tuple([await bounded(call, handler) for call, handler in requested])

    def _tool_specs_for_decision(
        self,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        *,
        inherited_completed_writes: set[str] | None = None,
    ) -> tuple[Any, ...]:
        if any(
            call.risk is ToolRisk.WRITE and call.status is ToolCallStatus.FAILED
            and call.decision_user_id is not None
            for call in calls
        ):
            # A failed approved action needs an explanation before a new decision.
            return ()
        specs = self.capabilities.specs
        registered_names = {spec.name for spec in specs}
        if not registered_names.intersection(_KNOWN_CAPABILITIES):
            return specs

        latest_user = next(
            (
                message
                for message in reversed(messages)
                if message.role is ChatMessageRole.USER
            ),
            None,
        )
        user_text = str(latest_user.content if latest_user is not None else "").casefold()
        successful_results = self._active_successful_results_by_name(messages)
        if _mentions_terms(user_text, _NO_TOOL_PHRASES):
            allowed_names: set[str] = set()
        else:
            allowed_names = self._capability_names_for_intent(
                user_text,
                has_source_context=bool(
                    latest_user is not None and latest_user.source_contexts
                ),
                prior_tool_names={
                    request.name
                    for message in messages
                    for request in message.tool_calls
                },
            )

        completed_browse = any(
            result.get("returned_paper_count", 0) > 0
            and result.get("next_offset") is None
            for result in successful_results.get("browse_collection_papers", ())
        )
        source_grounded_intent = _mentions_terms(user_text, _SOURCE_GROUNDED_TERMS)
        has_attached_source_context = bool(
            latest_user is not None and latest_user.source_contexts
        )
        if source_grounded_intent and not successful_results.get(
            "browse_collection_papers"
        ) and not has_attached_source_context:
            allowed_names.intersection_update({"browse_collection_papers"})
        elif source_grounded_intent and has_attached_source_context:
            # The caller already supplied a canonical Source context; do not
            # force a redundant collection survey before discussing it.
            allowed_names.discard("browse_collection_papers")
        if completed_browse:
            allowed_names.discard("browse_collection_papers")
            allowed_names.discard("get_collection_context")

        # A source search is a navigation step. Once it returns matches, the
        # next scientific action must read one of those exact Sources rather
        # than broadening the search or inspecting arbitrary pages.
        source_candidates = self._source_search_candidates(successful_results)
        if source_candidates and not self._has_successful_exact_source_read(
            successful_results, source_candidates
        ):
            allowed_names.intersection_update(
                {"read_source", "inspect_table", "inspect_document_sources"}
            )

        # A cross-paper comparison or support claim needs source-backed facts,
        # not only the paper map. Once the map is complete, require a focused
        # Source search before allowing the model to answer or choose a broad
        # inspection path.
        comparison_intent = _mentions_terms(user_text, _COMPARISON_TERMS)
        if (
            (comparison_intent or source_grounded_intent)
            and successful_results.get("browse_collection_papers")
            and not successful_results.get("search_sources")
            and not self._has_successful_exact_source_read(
                successful_results, source_candidates
            )
        ):
            allowed_names.intersection_update({"search_sources"})

        # Process status is only a paper-preparation view. If the collection
        # has a confirmed Objective, its canonical analysis state is the next
        # required read before the Agent reports progress to the researcher.
        if (
            successful_results.get("get_collection_context")
            and _mentions_terms(user_text, _PROCESS_TERMS)
            and not successful_results.get("inspect_research_process")
        ):
            allowed_names.intersection_update({"inspect_research_process"})
        confirmed_objective_ids = self._confirmed_objective_ids(successful_results)
        if (
            successful_results.get("inspect_research_process")
            and confirmed_objective_ids
            and not successful_results.get("inspect_objective_analysis")
        ):
            allowed_names.intersection_update({"inspect_objective_analysis"})

        # A published Finding summary is only a navigation result. Any
        # collection-level conclusion review must inspect one exact Finding
        # returned by that query before the model can judge its basis.
        finding_candidates = self._published_finding_candidates(successful_results)
        if (
            successful_results.get("query_published_findings")
            and finding_candidates
            and not successful_results.get("inspect_published_finding")
            and not _mentions_terms(user_text, _PLAN_TERMS)
        ):
            remaining_candidates = tuple(
                candidate
                for candidate in finding_candidates
                if candidate not in self._failed_finding_candidates(calls)
            )
            allowed_names.intersection_update(
                {"inspect_published_finding"} if remaining_candidates else set()
            )

        inspected_finding = bool(
            successful_results.get("inspect_published_finding")
        )
        persist_requested = _mentions_terms(user_text, _PERSIST_TERMS) and (
            not _mentions_terms(user_text, _NO_WRITE_PHRASES)
            or _has_explicit_immutable_write(user_text)
        )
        proposed_plan = bool(successful_results.get("propose_research_plan"))
        proposed_plan_this_turn = any(
            call.name == "propose_research_plan"
            and call.status is ToolCallStatus.SUCCEEDED
            for call in calls
        )
        finding_draft_this_turn = any(
            call.name == "create_finding_draft"
            and call.status is ToolCallStatus.SUCCEEDED
            for call in calls
        )
        # A completed plan proposal belongs to the request that asked for it.
        # Do not let an older turn force its write capability onto a later,
        # unrelated review or reading request in the same Chat trajectory.
        plan_revision_requested = _mentions_terms(
            user_text, ("修改", "修订", "调整", "revise", "update")
        )
        plan_read_requested = _mentions_terms(user_text, _PLAN_READ_TERMS)
        if (
            plan_read_requested
            and _mentions_terms(user_text, _PLAN_TERMS)
            and not persist_requested
            and not plan_revision_requested
        ):
            allowed_names = {"inspect_research_plans"}
        elif proposed_plan_this_turn:
            latest_plan = successful_results["propose_research_plan"][-1]
            plan_calls = [call for call in calls if call.name == "propose_research_plan"]
            # An unlinked citation is a correctable draft input, not a finished plan.
            correctable_basis = (
                latest_plan.get("draft_status") == "abstained"
                and bool(latest_plan.get("missing_evidence_ids"))
                and bool(latest_plan.get("available_evidence_ids"))
                and not any(latest_plan.get(key) for key in (
                    "missing_finding_ids", "rejected_finding_ids", "failed_evidence_ids",
                ))
                and (
                    len(plan_calls) == 1
                    or (len(plan_calls) == 2 and plan_calls[-1].error_code == "invalid_tool_arguments")
                )
            )
            if correctable_basis:
                allowed_names = {"propose_research_plan"}
            elif persist_requested:
                allowed_names = {
                    "revise_research_plan"
                    if plan_revision_requested
                    else "create_research_plan"
                }
            else:
                allowed_names = set()
        elif finding_draft_this_turn:
            allowed_names = set()
        elif proposed_plan and _mentions_terms(user_text, _PLAN_TERMS) and persist_requested:
            allowed_names = {
                "revise_research_plan"
                if plan_revision_requested
                else "create_research_plan"
            }
        elif (
            plan_read_requested
            and plan_revision_requested
            and persist_requested
            and not successful_results.get("inspect_research_plans")
            and "inspect_research_plans" in registered_names
            and _mentions_terms(user_text, _PLAN_TERMS)
        ):
            allowed_names = {"inspect_research_plans"}
        elif plan_revision_requested and persist_requested and _mentions_terms(
            user_text, _PLAN_TERMS
        ):
            allowed_names = {"revise_research_plan"}
        elif inspected_finding and _mentions_terms(
            user_text,
            ("结论草案", "修订草案", "finding draft", "draft finding"),
        ):
            allowed_names = {"create_finding_draft"}
        elif inspected_finding and _mentions_terms(user_text, _PLAN_TERMS):
            allowed_names = {"propose_research_plan"}
        elif _mentions_terms(user_text, _PLAN_TERMS):
            assessed_quality = bool(
                successful_results.get("assess_objective_quality")
            )
            queried_findings = bool(
                successful_results.get("query_published_findings")
            )
            finding_available = any(
                objective.get("findings")
                for result in successful_results.get(
                    "query_published_findings", ()
                )
                for objective in result.get("objectives") or ()
                if isinstance(objective, Mapping)
            )
            plan_prerequisites = {
                "assess_objective_quality",
                "query_published_findings",
            }
            if plan_prerequisites.issubset(registered_names):
                allowed_names.discard("create_research_plan")
                allowed_names.discard("propose_research_plan")
                allowed_names.discard("inspect_published_finding")
                if successful_results.get("get_collection_context"):
                    allowed_names.discard("get_collection_context")
                if assessed_quality:
                    allowed_names.discard("assess_objective_quality")
                if queried_findings:
                    allowed_names.discard("query_published_findings")
                if assessed_quality and queried_findings:
                    finding_candidates = self._published_finding_candidates(
                        successful_results
                    )
                    failed_finding_candidates = self._failed_finding_candidates(calls)
                    remaining_candidates = tuple(
                        candidate
                        for candidate in finding_candidates
                        if candidate not in failed_finding_candidates
                    )
                    allowed_names = (
                        {"inspect_published_finding"}
                        if remaining_candidates
                        else set()
                    )

        # Prevent an approved write from being repeated within this bounded
        # model continuation. A later user message starts a new decision turn
        # and may legitimately create another immutable version with the same
        # capability name.
        completed_writes = {
            call.name
            for call in calls
            if call.name in _WRITE_CAPABILITIES
            and call.status is ToolCallStatus.SUCCEEDED
        }
        completed_writes.update(inherited_completed_writes or ())
        allowed_names.difference_update(completed_writes)
        return tuple(spec for spec in specs if spec.name in allowed_names)

    @staticmethod
    def _required_tool_before_answer(
        tool_names: tuple[str, ...],
        *,
        successful_results: Mapping[str, list[Mapping[str, Any]]] | None = None,
    ) -> str | None:
        reader_names = {"read_source", "inspect_table"}
        source_reader_names = {*reader_names, "inspect_document_sources"}
        if (
            set(tool_names)
            and set(tool_names).issubset(source_reader_names)
            and (
                set(tool_names).issubset(reader_names)
                or (successful_results is not None and successful_results.get("search_sources"))
            )
        ):
            if successful_results is not None and ResearchAgentRunner._has_successful_exact_source_read(
                successful_results,
                ResearchAgentRunner._source_search_candidates(successful_results),
            ):
                return None
            return next((name for name in tool_names if name in source_reader_names), None)
        if len(tool_names) != 1:
            return None
        required_tool = tool_names[0]
        if required_tool in {
            "browse_collection_papers",
            "search_sources",
            "read_source",
            "inspect_table",
            "inspect_research_process",
            "inspect_objective_analysis",
            "inspect_published_finding",
            "inspect_research_plans",
            "create_finding_draft",
            "propose_research_plan",
        }:
            if successful_results is not None and successful_results.get(required_tool):
                return None
            return required_tool
        return None

    @staticmethod
    def _source_search_candidates(
        successful_results: Mapping[str, list[Mapping[str, Any]]],
    ) -> tuple[tuple[str, str, str], ...]:
        candidates: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for result in successful_results.get("search_sources", ()):
            for item in result.get("matches") or ():
                if not isinstance(item, Mapping):
                    continue
                candidate = (
                    str(item.get("document_id") or "").strip(),
                    str(item.get("source_kind") or "").strip(),
                    str(item.get("source_ref") or "").strip(),
                )
                if all(candidate) and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
        return tuple(candidates[:12])

    @staticmethod
    def _has_successful_exact_source_read(
        successful_results: Mapping[str, list[Mapping[str, Any]]],
        candidates: tuple[tuple[str, str, str], ...] = (),
    ) -> bool:
        candidate_set = set(candidates)

        def matches(
            item: Mapping[str, Any], *, table: bool = False, parent_document_id: str = "",
        ) -> bool:
            document_id = str(parent_document_id or item.get("document_id") or "").strip()
            source_ref = str(item.get("source_ref") or item.get("table_ref") or "").strip()
            source_kind = str(item.get("source_kind") or ("table" if table else "")).strip()
            identity = (document_id, source_kind, source_ref)
            return (
                bool(document_id and source_ref and item.get("source_digest"))
                and item.get("content_truncated") is False
                and (not candidate_set or identity in candidate_set)
            )

        if any(matches(item) for item in successful_results.get("read_source", ())):
            return True
        if any(matches(item, table=True) for item in successful_results.get("inspect_table", ())):
            return True
        for result in successful_results.get("inspect_document_sources", ()):
            document = result.get("document")
            if not isinstance(document, Mapping):
                continue
            if any(
                matches(item, parent_document_id=str(document.get("document_id") or ""))
                for item in result.get("sources") or () if isinstance(item, Mapping)
            ):
                return True
        return False

    @staticmethod
    def _confirmed_objective_ids(
        successful_results: Mapping[str, list[Mapping[str, Any]]],
    ) -> tuple[str, ...]:
        ids: list[str] = []
        for result in successful_results.get("get_collection_context", ()):
            for item in result.get("objectives") or ():
                if not isinstance(item, Mapping):
                    continue
                objective_id = str(item.get("objective_id") or "").strip()
                if (
                    objective_id
                    and (
                        str(item.get("confirmation_status") or "") == "confirmed"
                        or item.get("published_analysis_version") is not None
                    )
                    and objective_id not in ids
                ):
                    ids.append(objective_id)
        return tuple(ids[:12])

    @staticmethod
    def _published_finding_candidates(
        successful_results: Mapping[str, list[Mapping[str, Any]]],
    ) -> tuple[tuple[str, str], ...]:
        candidates: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for result in successful_results.get("query_published_findings", ()):
            for objective in result.get("objectives") or ():
                if not isinstance(objective, Mapping):
                    continue
                objective_id = str(objective.get("objective_id") or "").strip()
                for finding in objective.get("findings") or ():
                    if not isinstance(finding, Mapping):
                        continue
                    finding_id = str(finding.get("finding_id") or "").strip()
                    candidate = (objective_id, finding_id)
                    if all(candidate) and candidate not in seen:
                        seen.add(candidate)
                        candidates.append(candidate)
        return tuple(candidates[:24])

    @staticmethod
    def _failed_finding_candidates(
        calls: list[ChatToolCall],
    ) -> set[tuple[str, str]]:
        failed: set[tuple[str, str]] = set()
        for call in calls:
            if call.name != "inspect_published_finding" or call.status is not ToolCallStatus.FAILED:
                continue
            objective_id = str(call.arguments.get("objective_id") or "").strip()
            finding_id = str(call.arguments.get("finding_id") or "").strip()
            if objective_id and finding_id:
                failed.add((objective_id, finding_id))
        return failed

    def _stage_instruction(
        self,
        context: AgentContext,
        tool_names: tuple[str, ...],
        calls: list[ChatToolCall],
        *,
        successful_results: Mapping[str, list[Mapping[str, Any]]],
    ) -> ChatMessage | None:
        content: str | None = None
        source_candidates = self._source_search_candidates(successful_results)
        if (
            source_candidates
            and tool_names
            and set(tool_names).issubset({"read_source", "inspect_table"})
        ):
            content = (
                "The prior Source search returned the following exact reading "
                "candidates. Read one of these records now; do not call a broad "
                "page inspection and do not invent identifiers:\n"
                + "\n".join(
                    f"- document_id={document_id}, source_kind={source_kind}, "
                    f"source_ref={source_ref}"
                    for document_id, source_kind, source_ref in source_candidates
                )
            )
        elif tool_names == ("inspect_objective_analysis",):
            objective_ids = self._confirmed_objective_ids(successful_results)
            if objective_ids:
                content = (
                    "The preparation status is already known. Read the canonical "
                    "analysis state for one confirmed Objective before answering. "
                    "Use exactly one of these Objective IDs:\n"
                    + "\n".join(f"- objective_id={item}" for item in objective_ids)
                )
        elif tool_names == ("inspect_published_finding",):
            candidates = tuple(
                candidate
                for candidate in self._published_finding_candidates(successful_results)
                if candidate not in self._failed_finding_candidates(calls)
            )
            if candidates:
                content = (
                    "Inspect one exact published Finding returned by the prior "
                    "query. Use only these allowed (objective_id, finding_id) pairs; "
                    "do not invent Finding IDs:\n"
                    + "\n".join(
                        f"- objective_id={objective_id}, finding_id={finding_id}"
                        for objective_id, finding_id in candidates
                    )
                )
        if content is None:
            return None
        return ChatMessage.user(
            message_id=self._message_id(),
            session_id=context.session_id,
            content=content,
            created_at=_now_iso(),
        )

    @staticmethod
    def _completed_write_names(messages: list[ChatMessage]) -> set[str]:
        """Find writes completed before an approval continuation resumed.

        A fresh user message starts a new intent turn, so its call list is empty
        and these names are intentionally not carried over by ``run_turn``.
        Approval resumption has no new user message, though, and must preserve
        the same trajectory's write boundary while the model chooses its next
        read or draft step.
        """
        names_by_call_id = {
            request.tool_call_id: request.name
            for message in messages
            for request in message.tool_calls
        }
        return {
            name
            for message in messages
            if message.role is ChatMessageRole.TOOL
            and message.tool_result is not None
            and message.tool_result.status
            in {ToolResultStatus.SUCCEEDED, ToolResultStatus.QUEUED}
            for name in (names_by_call_id.get(message.tool_call_id),)
            if name in _WRITE_CAPABILITIES
        }

    @staticmethod
    def _capability_names_for_intent(
        user_text: str,
        *,
        has_source_context: bool,
        prior_tool_names: set[str | None],
    ) -> set[str]:
        def mentions(terms: tuple[str, ...]) -> bool:
            return _mentions_terms(user_text, terms)

        allowed: set[str] = set()
        # Generic English words such as "method" or "result" also occur in
        # ordinary technical conversation. They only indicate Source reading
        # when the request carries a research anchor (or an attached Source).
        research_anchor = mentions(
            (
                "论文",
                "文献",
                "collection",
                "paper",
                "papers",
                "摘要",
                "标题",
                "article",
                "literature",
                "source",
                "原文",
                "来源",
                "表格",
                "table",
                "figure",
                "evidence",
                "实验",
                "research",
            )
        )
        generic_source_detail = mentions(
            ("method", "methods", "result", "results", "read", "inspect", "check")
        )
        paper_intent = mentions(_PAPER_TERMS) and (
            has_source_context or research_anchor
        )
        source_intent = mentions(_SOURCE_DETAIL_TERMS) and (
            has_source_context or research_anchor or not generic_source_detail
        )
        objective_intent = mentions(_OBJECTIVE_TERMS) or "整理" in user_text
        finding_intent = mentions(_FINDING_TERMS)
        finding_record_intent = mentions(_FINDING_RECORD_TERMS)
        plan_intent = mentions(_PLAN_TERMS)
        process_intent = mentions(_PROCESS_TERMS)
        source_grounded_intent = mentions(_SOURCE_GROUNDED_TERMS)

        if paper_intent:
            allowed.update(_COLLECTION_READ_CAPABILITIES)
        if has_source_context or source_intent:
            allowed.update(_SOURCE_READ_CAPABILITIES)
        if paper_intent and source_grounded_intent:
            allowed.update(_SOURCE_GROUNDED_CAPABILITIES)
        if objective_intent:
            allowed.update(_OBJECTIVE_CAPABILITIES)
            if mentions(
                (
                    "派生",
                    "推导",
                    "从证据缺口形成",
                    "从结论形成下一",
                    "下一轮研究目标",
                    "derive",
                    "derive objective",
                    "derive a new objective",
                )
            ):
                allowed.add("derive_objective")
        if plan_intent:
            allowed.update(_RESEARCH_PLAN_CAPABILITIES)
        elif finding_intent:
            # Reviewing a conclusion is a read first. Draft and mutation
            # capabilities are added only by their explicit action branches
            # below, so a question about a gap cannot expose write schemas.
            paper_comparison = paper_intent and _mentions_terms(
                user_text, ("冲突", "相反", "不一致", "候选机制")
            )
            if finding_record_intent:
                allowed.update(_FINDING_READ_CAPABILITIES)
            if has_source_context or source_intent or paper_comparison:
                allowed.update(_SOURCE_READ_CAPABILITIES)
        if process_intent:
            allowed.update(_PROCESS_CAPABILITIES)

        continuation_intent = mentions(
            ("继续", "再看", "再读", "追加", "排除", "一起看", "continue", "also")
        )
        if continuation_intent:
            for tool_name in prior_tool_names:
                if tool_name in _SOURCE_READ_CAPABILITIES:
                    allowed.update(_SOURCE_READ_CAPABILITIES)
                elif tool_name in _OBJECTIVE_CAPABILITIES:
                    allowed.update(_OBJECTIVE_CAPABILITIES)
                elif tool_name in _FINDING_CAPABILITIES:
                    allowed.update(_FINDING_READ_CAPABILITIES)
                elif tool_name in _RESEARCH_PLAN_CAPABILITIES:
                    allowed.update(_RESEARCH_PLAN_READ_CAPABILITIES)
                elif tool_name in _PROCESS_CAPABILITIES:
                    allowed.update(_PROCESS_CAPABILITIES)

        persist_intent = mentions(_PERSIST_TERMS) and (
            not mentions(_NO_WRITE_PHRASES)
            or _has_explicit_immutable_write(user_text)
        )
        if persist_intent and objective_intent:
            allowed.add("create_objective_candidate")
        confirm_requested = mentions(
            (
                "确认目标",
                "确认这个目标",
                "confirm objective",
                "confirm the reviewed question",
                "confirm this question",
            )
        ) and not mentions(
            (
                "不要确认",
                "不确认",
                "先不要确认",
                "without confirming",
                "do not confirm",
                "don't confirm",
            )
        )
        if confirm_requested:
            allowed.add("confirm_objective")
        analysis_explicitly_deferred = mentions(
            (
                "不要启动分析",
                "不启动分析",
                "先不要启动分析",
                "without starting analysis",
                "do not start analysis",
                "don't start analysis",
            )
        )
        if (
            mentions(("开始分析", "启动分析", "分析这个目标", "start analysis"))
            and not analysis_explicitly_deferred
        ):
            allowed.update(_PROCESS_CAPABILITIES)
            allowed.add("start_objective_analysis")
        if not analysis_explicitly_deferred and mentions(
            (
                "analyze this",
                "分析这个研究问题",
                "分析这个目标",
                "开始分析",
                "启动分析",
            )
        ):
            allowed.add("start_objective_analysis")
        if mentions(
            (
                "start understanding",
                "开始理解",
                "开始了解",
                "form research questions",
            )
        ):
            allowed.add("start_research_process")
        if mentions(("准备论文", "处理论文", "重新处理", "重试论文", "prepare papers")):
            allowed.add("start_research_process")
        if persist_intent and plan_intent:
            allowed.add("create_research_plan")
        if plan_intent and mentions(("修改", "修订", "调整", "revise", "update")):
            allowed.add("revise_research_plan")
        if finding_intent and persist_intent:
            allowed.update(
                {
                    "record_finding_feedback",
                    "curate_finding",
                    "create_finding_version",
                }
            )
        if finding_intent and mentions(
            ("结论草案", "修订草案", "finding draft", "draft finding")
        ):
            allowed.add("create_finding_draft")
        if finding_intent and mentions(_REVIEW_ACTION_TERMS):
            allowed.add("record_finding_feedback")
        evidence_write_intent = mentions(
            (
                "记录证据",
                "保存证据",
                "修订证据",
                "record evidence",
                "save evidence",
                "revise evidence",
                "correct evidence",
                "update evidence",
            )
        ) or (persist_intent and "evidence" in user_text)
        if evidence_write_intent:
            allowed.add("create_evidence_version")
        if mentions(("发布分析", "保存分析")) or (
            mentions(("publish",)) and mentions(("analysis",))
        ):
            allowed.add("publish_agent_objective_analysis")
        return allowed

    @staticmethod
    def _successful_results_by_name(
        messages: list[ChatMessage],
    ) -> dict[str, list[Mapping[str, Any]]]:
        names_by_call_id = {
            request.tool_call_id: request.name
            for message in messages
            for request in message.tool_calls
        }
        results: dict[str, list[Mapping[str, Any]]] = {}
        for message in messages:
            if (
                message.role is not ChatMessageRole.TOOL
                or message.tool_result is None
                or message.tool_result.status
                not in {ToolResultStatus.SUCCEEDED, ToolResultStatus.QUEUED}
            ):
                continue
            name = names_by_call_id.get(message.tool_call_id)
            if name:
                results.setdefault(name, []).append(message.tool_result.data)
        return results

    @staticmethod
    def _active_successful_results_by_name(
        messages: list[ChatMessage],
    ) -> dict[str, list[Mapping[str, Any]]]:
        """Return successful reads belonging to the latest user request."""
        last_user_index = max(
            (
                index
                for index, message in enumerate(messages)
                if message.role is ChatMessageRole.USER
            ),
            default=-1,
        )
        return ResearchAgentRunner._successful_results_by_name(messages[last_user_index:])

    @staticmethod
    def _active_user_request(messages: list[ChatMessage]) -> str:
        return next(
            (
                message.content
                for message in reversed(messages)
                if message.role is ChatMessageRole.USER
            ),
            "Answer the researcher's current request.",
        )[:4_000]

    @staticmethod
    def _reading_ledger(
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
    ) -> str:
        calls_by_id = {call.tool_call_id: call for call in calls}
        collection_paper_totals: set[int] = set()
        screened_documents: set[str] = set()
        requested_documents = {
            str(call.arguments["document_id"])
            for call in calls if call.arguments.get("document_id")
        }
        read_documents: set[str] = set()
        exact_sources: set[str] = set()
        failed_documents: set[str] = set()
        for result in results:
            call = calls_by_id.get(result.tool_call_id)
            name = call.name if call else None
            if result.status is ToolResultStatus.FAILED:
                document_id = str(result.data.get("document_id") or
                                  (call.arguments.get("document_id") if call else "") or "").strip()
                if document_id and result.error_code not in {"resource_budget", "invalid_tool_batch", "capability_unavailable_for_turn"}:
                    failed_documents.add(document_id)
                continue
            if name == "browse_collection_papers":
                paper_total = result.data.get("paper_total")
                if isinstance(paper_total, int) and paper_total >= 0:
                    collection_paper_totals.add(paper_total)
                screened_documents.update(
                    str(item.get("document_id") or "").strip()
                    for item in result.data.get("papers") or ()
                    if isinstance(item, Mapping)
                )
            if name == "inspect_document_sources":
                document = result.data.get("document")
                document_id = str(
                    document.get("document_id")
                    if isinstance(document, Mapping)
                    else ""
                ).strip()
                if document_id:
                    inspected = {
                        f"{document_id}:{source_ref}"
                        for item in result.data.get("sources") or ()
                        if isinstance(item, Mapping)
                        and item.get("content_truncated") is False
                        and item.get("source_digest")
                        and (source_ref := str(item.get("source_ref") or "").strip())
                    }
                    exact_sources.update(inspected)
                    if inspected:
                        read_documents.add(document_id)
            if name in {"read_source", "inspect_table"}:
                document_id = str(result.data.get("document_id") or "").strip()
                source_ref = str(
                    result.data.get("source_ref")
                    or result.data.get("table_ref")
                    or ""
                ).strip()
                if document_id and source_ref and result.data.get("source_digest"):
                    exact_sources.add(f"{document_id}:{source_ref}")
                    read_documents.add(document_id)

        def display(values: set[str]) -> str:
            return ", ".join(sorted(value for value in values if value)[:30]) or "none"

        paper_total = (
            str(max(collection_paper_totals)) if collection_paper_totals else "unknown"
        )
        unread_documents = (screened_documents | requested_documents) - read_documents - failed_documents
        return (
            f"Collection paper total: {paper_total}\n"
            f"Paper identities screened ({len(screened_documents)}): "
            f"{display(screened_documents)}\n"
            f"Exact paper Sources read ({len(exact_sources)}): "
            f"{display(exact_sources)}\n"
            f"Papers with failed exact reads ({len(failed_documents)}): "
            f"{display(failed_documents)}\n"
            f"Known papers without an exact read ({len(unread_documents)}): "
            f"{display(unread_documents)}"
        )

    @staticmethod
    def _latest_structured_deliverable(
        results: list[ChatToolResult],
    ) -> str | None:
        for result in reversed(results):
            if result.status is not ToolResultStatus.SUCCEEDED:
                continue
            data = result.data
            if not data.get("draft_id"):
                continue
            summary: dict[str, Any] = {}
            for key in (
                "draft_id",
                "objective_id",
                "title",
                "draft_status",
                "source_analysis_version",
                "source_finding_ids",
                "source_evidence_ids",
                "persistence",
            ):
                value = data.get(key)
                if value not in (None, "", [], (), {}):
                    summary[key] = value
            content = str(data.get("content") or "").strip()
            if content:
                summary["content"] = content[:6_000]
            if result.warnings:
                summary["warnings"] = list(result.warnings[:8])
            return json.dumps(
                summary,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return None

    async def _execute_one(
        self,
        context: AgentContext,
        call: ChatToolCall,
        handler: Any,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        try:
            arguments = handler.spec.input_model.model_validate(call.arguments)
        except ValidationError:
            return ResearchAgentRunner._failure(
                call,
                "invalid_tool_arguments",
                "The research capability arguments are invalid.",
            )
        try:
            execution_context = CapabilityExecutionContext.for_call(
                context,
                call.tool_call_id,
            )
            result = (await handler.execute(execution_context, arguments)).for_call(
                call.tool_call_id
            )
            call = (
                call.fail(result.error_code or "capability_failed", _now_iso())
                if result.status is ToolResultStatus.FAILED
                else call.succeed(_now_iso())
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Research capability failed tool=%s exception_type=%s",
                call.name,
                type(exc).__name__,
            )
            call, result = ResearchAgentRunner._failure(
                call,
                "capability_execution_failed",
                "The research capability could not be completed.",
            )
        return call, result

    @staticmethod
    def _validate_claimed_call(context: AgentContext, call: ChatToolCall) -> None:
        if call.session_id != context.session_id:
            raise ValueError("approved tool call belongs to another session")
        if call.status is not ToolCallStatus.RUNNING:
            raise ValueError("tool call is not claimed for execution")
        if call.decision_user_id != context.user_id:
            raise ValueError("tool call was approved by another user")

    @staticmethod
    def _failure(
        call: ChatToolCall,
        code: str,
        message: str,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        return call.fail(code, _now_iso()), ChatToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolResultStatus.FAILED,
            error_code=code,
            error_message=message,
        )

    @staticmethod
    def _assistant(context: AgentContext, content: str) -> ChatMessage:
        return ChatMessage.assistant(
            message_id=ResearchAgentRunner._message_id(),
            session_id=context.session_id,
            content=content,
            created_at=_now_iso(),
        )

    @staticmethod
    def _result_message(
        context: AgentContext,
        result: ChatToolResult,
    ) -> ChatMessage:
        return ChatMessage.from_tool_result(
            message_id=ResearchAgentRunner._message_id(),
            session_id=context.session_id,
            result=result,
            created_at=_now_iso(),
        )

    @staticmethod
    def _result(
        status: AgentRunStatus,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        error_code: str | None = None,
        *,
        completion_reason: AgentCompletionReason | None = None,
        warnings: tuple[str, ...] = (),
    ) -> AgentRunResult:
        return AgentRunResult(
            status=status,
            messages=tuple(messages),
            tool_calls=tuple(calls),
            tool_results=tuple(results),
            error_code=error_code,
            completion_reason=completion_reason,
            warnings=warnings,
        )

    @staticmethod
    async def _checkpoint(
        checkpoint: _TrajectoryCheckpoint | None,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
    ) -> None:
        if checkpoint is not None:
            await checkpoint(tuple(messages), tuple(calls), tuple(results))

    @staticmethod
    def _message_id() -> str:
        return f"msg_{uuid4().hex[:16]}"

    @staticmethod
    def _tool_call_id() -> str:
        return f"call_{uuid4().hex[:16]}"


__all__ = [
    "AgentRunResult",
    "AgentRunStatus",
    "AgentCompletionReason",
    "AgentRunLimits",
    "ResearchAgentRunner",
]
