"""Bounded model/capability/result loop for one Research Agent turn."""

from __future__ import annotations

from asyncio import to_thread
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
import logging
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from application.chat.authorization import evaluate_authorization
from application.chat.capabilities import (
    AgentContext,
    CapabilityExecutionContext,
    CapabilityRegistry,
)
from application.chat.context_builder import ChatContextBuilder
from application.chat.model import ChatModel, ModelResponseError
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


logger = logging.getLogger(__name__)

_TrajectoryCheckpoint = Callable[
    [
        tuple[ChatMessage, ...],
        tuple[ChatToolCall, ...],
        tuple[ChatToolResult, ...],
    ],
    Awaitable[None],
]

_STEP_LIMIT_MESSAGE = (
    "I reached the Research Agent step limit before completing this request. "
    "Please narrow the question or continue in a new message."
)
_MODEL_RESPONSE_RETRY_LIMIT = 1
_FINAL_ANSWER_INSTRUCTION = (
    "The bounded research-reading budget is now exhausted. Give the researcher "
    "the best useful final answer supported by the completed trajectory. State "
    "what was inspected, what remains unread or failed, the scientific "
    "uncertainty, and one practical next step. Do not request another tool and "
    "do not mention internal budgets, tool schemas, or hidden reasoning. A paper "
    "identity survey or a search match is not an exact Source read. Do not claim "
    "that a paper was read unless the reading ledger below records an exact Source."
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
_PROCESS_CAPABILITIES = {
    "get_collection_context",
    "browse_collection_papers",
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
    "propose_research_plan",
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
    "without saving",
    "do not save",
    "don't save",
    "without modifying",
    "do not modify",
    "don't modify",
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
    "查看",
    "看看",
    "阅读",
    "读取",
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
    "plan",
)
_PROCESS_TERMS = (
    "进度",
    "状态",
    "处理到",
    "处理完",
    "为什么失败",
    "失败原因",
    "处理失败",
    "为什么慢",
    "哪里了",
    "progress",
    "status",
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRunStatus(StrEnum):
    COMPLETED = "completed"
    APPROVAL_REQUIRED = "approval_required"
    STEP_LIMIT_REACHED = "step_limit_reached"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentRunResult:
    status: AgentRunStatus
    messages: tuple[ChatMessage, ...]
    tool_calls: tuple[ChatToolCall, ...] = ()
    tool_results: tuple[ChatToolResult, ...] = ()
    pending_approval: ChatToolCall | None = None
    error_code: str | None = None


class ResearchAgentRunner:
    def __init__(
        self,
        *,
        model: ChatModel,
        capabilities: CapabilityRegistry,
        context_builder: ChatContextBuilder | None = None,
        max_model_steps: int = 6,
    ) -> None:
        if max_model_steps < 1:
            raise ValueError("max_model_steps must be positive")
        self.model = model
        self.capabilities = capabilities
        self.context_builder = context_builder or ChatContextBuilder()
        self.max_model_steps = max_model_steps

    async def run_turn(
        self,
        *,
        context: AgentContext,
        previous_messages: tuple[ChatMessage, ...],
        user_message: str,
        source_contexts: tuple[ChatSourceContext, ...] = (),
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
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
        )

    async def resume_claimed_call(
        self,
        *,
        context: AgentContext,
        previous_messages: tuple[ChatMessage, ...],
        claimed_call: ChatToolCall,
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
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
            call, result = await self._validate_and_execute(
                context,
                claimed_call,
                handler,
                messages=messages,
                calls=calls,
                results=results,
                checkpoint=checkpoint,
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
    ) -> AgentRunResult:
        for step_index in range(1, self.max_model_steps + 1):
            response_retries = 0
            while True:
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
                        step_index,
                        self.max_model_steps,
                        len(tool_specs),
                        schema_chars,
                        ",".join(tool_names) or "none",
                    )
                    model_arguments: dict[str, Any] = {
                        "messages": self.context_builder.for_model(tuple(messages)),
                        "tool_specs": tool_specs,
                    }
                    if text_delta_callback is not None:
                        model_arguments["text_delta_callback"] = text_delta_callback
                    turn = await to_thread(
                        self.model.respond,
                        **model_arguments,
                    )
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
                        exc_info=True,
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
                    logger.warning(
                        "Research Agent model call failed model=%s "
                        "exception_type=%s message=%s",
                        model_name,
                        type(exc).__name__,
                        str(exc)[:240],
                        exc_info=True,
                    )
                    messages.append(
                        self._assistant(
                            context,
                            "The research model is unavailable for this turn.",
                        )
                    )
                    await self._checkpoint(checkpoint, messages, calls, results)
                    return self._result(
                        AgentRunStatus.FAILED,
                        messages,
                        calls,
                        results,
                        "model_unavailable",
                    )
                break

            if turn.tool_call is None:
                messages.append(self._assistant(context, turn.content))
                await self._checkpoint(checkpoint, messages, calls, results)
                return self._result(AgentRunStatus.COMPLETED, messages, calls, results)

            call, handler = self._requested_call(
                context,
                messages,
                turn,
                allowed_names=set(tool_names),
            )
            calls.append(call)
            await self._checkpoint(checkpoint, messages, calls, results)
            if handler is None:
                registered_handler = self.capabilities.get(call.name)
                call, capability_result = self._failure(
                    call,
                    (
                        "capability_unavailable_for_turn"
                        if registered_handler is not None
                        else "unknown_capability"
                    ),
                    (
                        "The requested research capability is not available for "
                        "this research step."
                        if registered_handler is not None
                        else "The requested research capability is not available."
                    ),
                )
            else:
                decision = evaluate_authorization(call.risk)
                if decision.requires_approval:
                    pending = call.require_approval()
                    calls[-1] = pending
                    await self._checkpoint(checkpoint, messages, calls, results)
                    return AgentRunResult(
                        status=AgentRunStatus.APPROVAL_REQUIRED,
                        messages=tuple(messages),
                        tool_calls=tuple(calls),
                        tool_results=tuple(results),
                        pending_approval=pending,
                    )
                if not decision.may_execute:
                    call, capability_result = self._failure(
                        call,
                        "capability_not_authorized",
                        "The research capability is not authorized.",
                    )
                else:
                    call, capability_result = await self._validate_and_execute(
                        context,
                        call,
                        handler,
                        messages=messages,
                        calls=calls,
                        results=results,
                        checkpoint=checkpoint,
                    )
            calls[-1] = call
            results.append(capability_result)
            messages.append(self._result_message(context, capability_result))
            await self._checkpoint(checkpoint, messages, calls, results)

        final_answer = await self._final_answer_after_limit(
            context,
            messages,
            calls,
            results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
        )
        if not final_answer:
            messages.append(self._assistant(context, _STEP_LIMIT_MESSAGE))
        await self._checkpoint(checkpoint, messages, calls, results)
        return self._result(
            AgentRunStatus.STEP_LIMIT_REACHED,
            messages,
            calls,
            results,
            "agent_step_limit_reached",
        )

    async def _final_answer_after_limit(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        checkpoint: _TrajectoryCheckpoint | None,
        text_delta_callback: Callable[[str], None] | None,
    ) -> bool:
        """Give the model one answer-only turn after tool decisions are spent."""

        active_request = self._active_user_request(messages)
        instruction = ChatMessage.user(
            message_id=self._message_id(),
            session_id=context.session_id,
            content=(
                f"{_FINAL_ANSWER_INSTRUCTION}\n\n"
                "ACTIVE RESEARCH REQUEST (answer this request; do not restart "
                f"onboarding):\n{active_request}\n\n"
                f"READING LEDGER:\n{self._reading_ledger(calls, results)}"
            ),
            created_at=_now_iso(),
        )
        model_arguments: dict[str, Any] = {
            "messages": self.context_builder.for_model(
                tuple([*messages, instruction])
            ),
            "tool_specs": (),
        }
        if text_delta_callback is not None:
            model_arguments["text_delta_callback"] = text_delta_callback
        logger.info(
            "Research Agent final answer turn step_limit=%d tools=none",
            self.max_model_steps,
        )
        try:
            turn = await to_thread(self.model.respond, **model_arguments)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Research Agent final answer failed exception_type=%s message=%s",
                type(exc).__name__,
                str(exc)[:240],
                exc_info=True,
            )
            return False
        if turn.tool_call is not None or not turn.content:
            logger.warning(
                "Research Agent final answer was not answer-only has_tool_call=%s",
                turn.tool_call is not None,
            )
            return False
        messages.append(self._assistant(context, turn.content))
        await self._checkpoint(checkpoint, messages, calls, results)
        return True

    def _requested_call(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        turn: Any,
        *,
        allowed_names: set[str],
    ) -> tuple[ChatToolCall, Any]:
        model_call = turn.tool_call
        assistant_message_id = self._message_id()
        tool_call_id = self._tool_call_id()
        messages.append(
            ChatMessage.assistant_tool_call(
                message_id=assistant_message_id,
                session_id=context.session_id,
                content=turn.content,
                tool_call_id=tool_call_id,
                tool_name=model_call.name,
                tool_arguments=model_call.arguments,
                created_at=_now_iso(),
            )
        )
        registered_handler = self.capabilities.get(model_call.name)
        handler = (
            registered_handler if model_call.name in allowed_names else None
        )
        return ChatToolCall.requested(
            tool_call_id=tool_call_id,
            session_id=context.session_id,
            assistant_message_id=assistant_message_id,
            name=model_call.name,
            arguments=model_call.arguments,
            risk=(
                registered_handler.spec.risk
                if registered_handler is not None
                else ToolRisk.UNKNOWN
            ),
        ), handler

    def _tool_specs_for_decision(
        self,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        *,
        inherited_completed_writes: set[str] | None = None,
    ) -> tuple[Any, ...]:
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
        successful_results = self._successful_results_by_name(messages)
        if any(phrase in user_text for phrase in _NO_TOOL_PHRASES):
            allowed_names: set[str] = set()
        else:
            allowed_names = self._capability_names_for_intent(
                user_text,
                has_source_context=bool(
                    latest_user is not None and latest_user.source_contexts
                ),
                prior_tool_names={
                    message.tool_name
                    for message in messages
                    if message.role is ChatMessageRole.ASSISTANT
                    and message.tool_call_id
                    and message.tool_name
                },
            )

        completed_browse = any(
            result.get("returned_paper_count", 0) > 0
            and result.get("next_offset") is None
            for result in successful_results.get("browse_collection_papers", ())
        )
        if completed_browse:
            allowed_names.discard("browse_collection_papers")
            allowed_names.discard("get_collection_context")

        inspected_finding = bool(
            successful_results.get("inspect_published_finding")
        )
        persist_requested = any(term in user_text for term in _PERSIST_TERMS) and not any(
            phrase in user_text for phrase in _NO_WRITE_PHRASES
        )
        proposed_plan = bool(successful_results.get("propose_research_plan"))
        if proposed_plan:
            allowed_names = (
                {"create_research_plan"} if persist_requested else set()
            )
        elif inspected_finding and any(
            phrase in user_text
            for phrase in ("结论草案", "修订草案", "finding draft", "draft finding")
        ):
            allowed_names = {"create_finding_draft"}
        elif inspected_finding and any(term in user_text for term in _PLAN_TERMS):
            allowed_names = {"propose_research_plan"}

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
    def _completed_write_names(messages: list[ChatMessage]) -> set[str]:
        """Find writes completed before an approval continuation resumed.

        A fresh user message starts a new intent turn, so its call list is empty
        and these names are intentionally not carried over by ``run_turn``.
        Approval resumption has no new user message, though, and must preserve
        the same trajectory's write boundary while the model chooses its next
        read or draft step.
        """
        names_by_call_id = {
            message.tool_call_id: message.tool_name
            for message in messages
            if message.role is ChatMessageRole.ASSISTANT
            and message.tool_call_id
            and message.tool_name
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
            return any(term in user_text for term in terms)

        allowed: set[str] = set()
        paper_intent = mentions(_PAPER_TERMS)
        source_intent = mentions(_SOURCE_DETAIL_TERMS)
        objective_intent = mentions(_OBJECTIVE_TERMS) or "整理" in user_text
        finding_intent = mentions(_FINDING_TERMS)
        finding_record_intent = mentions(_FINDING_RECORD_TERMS)
        plan_intent = mentions(_PLAN_TERMS)
        process_intent = mentions(_PROCESS_TERMS)

        if paper_intent:
            allowed.update(_COLLECTION_READ_CAPABILITIES)
        if has_source_context or source_intent:
            allowed.update(_SOURCE_READ_CAPABILITIES)
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
            paper_comparison = paper_intent and any(
                term in user_text
                for term in ("冲突", "相反", "不一致", "候选机制")
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
                    allowed.update(_FINDING_CAPABILITIES)
                elif tool_name in _RESEARCH_PLAN_CAPABILITIES:
                    allowed.update(_RESEARCH_PLAN_CAPABILITIES)

        persist_intent = mentions(_PERSIST_TERMS) and not any(
            phrase in user_text for phrase in _NO_WRITE_PHRASES
        )
        if persist_intent and objective_intent:
            allowed.add("create_objective_candidate")
        if mentions(
            (
                "确认目标",
                "确认这个目标",
                "confirm objective",
                "confirm the reviewed question",
                "confirm this question",
            )
        ):
            allowed.add("confirm_objective")
        if mentions(("开始分析", "启动分析", "分析这个目标", "start analysis")):
            allowed.update(_PROCESS_CAPABILITIES)
            allowed.add("start_objective_analysis")
        if mentions(
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
            "publish" in user_text and "analysis" in user_text
        ):
            allowed.add("publish_agent_objective_analysis")
        return allowed

    @staticmethod
    def _successful_results_by_name(
        messages: list[ChatMessage],
    ) -> dict[str, list[Mapping[str, Any]]]:
        names_by_call_id = {
            message.tool_call_id: message.tool_name
            for message in messages
            if message.role is ChatMessageRole.ASSISTANT
            and message.tool_call_id
            and message.tool_name
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
        names_by_call_id = {call.tool_call_id: call.name for call in calls}
        screened_documents: set[str] = set()
        exact_sources: set[str] = set()
        failed_documents: set[str] = set()
        for result in results:
            name = names_by_call_id.get(result.tool_call_id)
            if result.status is ToolResultStatus.FAILED:
                document_id = str(result.data.get("document_id") or "").strip()
                if document_id:
                    failed_documents.add(document_id)
                continue
            if name == "browse_collection_papers":
                screened_documents.update(
                    str(item.get("document_id") or "").strip()
                    for item in result.data.get("papers") or ()
                    if isinstance(item, Mapping)
                )
            if name in {"read_source", "inspect_table"}:
                document_id = str(result.data.get("document_id") or "").strip()
                source_ref = str(
                    result.data.get("source_ref")
                    or result.data.get("table_ref")
                    or ""
                ).strip()
                if document_id and source_ref:
                    exact_sources.add(f"{document_id}:{source_ref}")

        def display(values: set[str]) -> str:
            return ", ".join(sorted(value for value in values if value)[:30]) or "none"

        return (
            f"Paper identities screened: {display(screened_documents)}\n"
            f"Exact paper Sources read: {display(exact_sources)}\n"
            f"Papers with failed exact reads: {display(failed_documents)}"
        )

    async def _validate_and_execute(
        self,
        context: AgentContext,
        call: ChatToolCall,
        handler: Any,
        *,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        checkpoint: _TrajectoryCheckpoint | None,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        try:
            arguments = handler.spec.input_model.model_validate(call.arguments)
        except ValidationError:
            return ResearchAgentRunner._failure(
                call,
                "invalid_tool_arguments",
                "The research capability arguments are invalid.",
            )
        if call.status is not ToolCallStatus.RUNNING:
            call = call.start(_now_iso())
            calls[-1] = call
            await self._checkpoint(checkpoint, messages, calls, results)
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
            logger.warning(
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
    ) -> AgentRunResult:
        return AgentRunResult(
            status=status,
            messages=tuple(messages),
            tool_calls=tuple(calls),
            tool_results=tuple(results),
            error_code=error_code,
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
    "ResearchAgentRunner",
]
