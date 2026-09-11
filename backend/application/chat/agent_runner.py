"""Bounded model/capability/result loop for one Research Agent turn."""

from __future__ import annotations

from asyncio import Semaphore, gather, wait_for
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import logging
from math import isfinite
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from application.chat.capabilities import (
    AgentContext,
    CapabilityExecutionContext,
    CapabilityRegistry,
    ToolSpec,
)
from application.chat.context_builder import ChatContextBuilder, ChatModelContext
from application.chat import capability_policy, intent_policy
from application.chat.model import ChatModel, ModelResponseError, ModelTurn, ModelUsage, ResearchClaimReview
from application.chat.model import (
    RESEARCH_AGENT_SYSTEM_PROMPT, RESEARCH_REVIEW_SYSTEM_PROMPT,
    RESEARCH_COMPACTION_SYSTEM_PROMPT, ResearchWorkingCheck, ResearchWorkingNotes,
)
from application.core.structured_extraction.json_support import extract_json_object
from domain.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatSourceContext,
    ChatToolCall,
    ChatToolResult,
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

_MODEL_RESPONSE_RETRY_LIMIT = 5
_REQUIRED_ACTION_RETRY_LIMIT = 1
_MAX_TOOL_CALLS_PER_RESPONSE = 32
_RESEARCH_DRAFT_TOOLS = frozenset({
    "propose_objective_drafts", "preview_research_scope", "propose_research_plan",
    "create_finding_draft",
})
_RESEARCH_OBSERVATION_TOOLS = frozenset({
    "read_source", "inspect_table", "inspect_document_sources",
    "inspect_published_finding", "inspect_objective_evidence", "inspect_research_plans",
    *_RESEARCH_DRAFT_TOOLS,
})


def _is_retryable_provider_exception(exc: BaseException) -> bool:
    """Recognize transient provider failures without inspecting exception text."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    exception_name = type(exc).__name__.lower()
    return any(
        marker in exception_name
        for marker in (
            "timeout", "connection", "ratelimit", "rate_limit", "serviceunavailable",
            "internalserver", "badgateway", "gatewaytimeout", "temporarilyunavailable",
            "overloaded",
        )
    )
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
    max_elapsed_seconds: float | None = None
    max_tool_calls: int | None = None
    max_model_tokens: int | None = None
    max_consecutive_no_progress: int = 2
    emergency_max_model_cycles: int | None = None
    max_request_seconds: float = 180.0
    max_context_tokens: int = 65_536
    max_parallel_reads: int = 4
    max_model_output_tokens: int = 16_384
    max_finalization_seconds: float = 300.0
    max_finalization_output_tokens: int = 8_192

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if value is None and name in {
                "max_elapsed_seconds", "max_tool_calls", "max_model_tokens", "emergency_max_model_cycles",
            }:
                continue
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
            if not name.endswith("_seconds") and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")


@dataclass
class _RunProgress:
    limits: AgentRunLimits
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    response_started_callback: Callable[[str, str], None] | None = None
    response_message_id: str = ""
    response_created_at: str = ""
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
    working_summary: str = ""
    compacted_message_ids: set[str] = field(default_factory=set)
    read_batch_tokens: int = 12_000
    compaction_attempts: int = 0
    complete_source_identities: set[tuple[str, str, str, str]] = field(default_factory=set)
    research_plan: list[dict[str, str]] = field(default_factory=list)

    def initialize_research_plan(self, request: str) -> None:
        """Create a visible plan only for multi-step Finding review requests."""
        normalized = request.casefold()
        review_terms = ("finding", "结论", "证据")
        draft_terms = ("修订草案", "结论草案", "draft finding", "finding draft")
        if not any(term in normalized for term in review_terms) or not any(
            term in normalized for term in draft_terms
        ):
            return
        self.research_plan = [
            {"id": "inspect_finding", "status": "in_progress"},
            {"id": "inspect_sources", "status": "pending"},
            {"id": "validate_claim", "status": "pending"},
            {"id": "draft_finding", "status": "pending"},
            {"id": "approval", "status": "pending"},
        ]

    def update_research_plan(self, tool_name: str, status: ToolResultStatus) -> None:
        if not self.research_plan or status is not ToolResultStatus.SUCCEEDED:
            return
        transitions = {
            "inspect_published_finding": ("inspect_finding", "inspect_sources"),
            "inspect_document_sources": ("inspect_sources", "validate_claim"),
            "read_source": ("inspect_sources", "validate_claim"),
            "inspect_table": ("inspect_sources", "validate_claim"),
            "create_finding_draft": ("validate_claim", "approval"),
        }
        transition = transitions.get(tool_name)
        if transition is None:
            return
        current, next_step = transition
        if tool_name == "create_finding_draft":
            for item in self.research_plan:
                if item["id"] in {"validate_claim", "draft_finding"}:
                    item["status"] = "completed"
            next_step = "approval"
        current_item = next((item for item in self.research_plan if item["id"] == current), None)
        if current_item is not None:
            current_item["status"] = "completed"
        next_item = next((item for item in self.research_plan if item["id"] == next_step), None)
        if next_item is not None and next_item["status"] == "pending":
            next_item["status"] = "in_progress"

    def start_response(self) -> None:
        self.response_message_id = f"msg_{uuid4().hex[:16]}"
        self.response_created_at = _now_iso()
        if self.response_started_callback is not None:
            self.response_started_callback(self.response_message_id, self.response_created_at)

    def remaining_seconds(self) -> float:
        if self.limits.max_elapsed_seconds is None:
            return self.limits.max_request_seconds
        return min(self.limits.max_request_seconds, max(
            0.0, self.limits.max_elapsed_seconds - (monotonic() - self.started_at),
        ))

    def model_allowance_exhausted(self) -> bool:
        return (
            self.limits.max_model_tokens is not None and self.model_tokens >= self.limits.max_model_tokens
        ) or (
            self.limits.emergency_max_model_cycles is not None
            and self.model_cycles >= self.limits.emergency_max_model_cycles
        )

    def stop_before_model(self) -> AgentCompletionReason | None:
        if (self.limits.emergency_max_model_cycles is not None
                and self.model_cycles >= self.limits.emergency_max_model_cycles):
            return AgentCompletionReason.EMERGENCY_CEILING
        if (self.remaining_seconds() <= 0
                or self.model_allowance_exhausted()
                or (self.limits.max_tool_calls is not None
                    and self.executed_tool_calls >= self.limits.max_tool_calls)):
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

    def observe(self, call: ChatToolCall, result: ChatToolResult) -> bool:
        data = dict(result.data)
        has_source_observation = (
            result.status is ToolResultStatus.SUCCEEDED
            and any(ref.resource_type == "source" for ref in result.resource_refs)
        )
        previous_resource_refs = set(self.resource_refs)
        # Source navigation echoes the query; changing its wording is not new content.
        if has_source_observation and call.name in {"search_sources", "inspect_document_sources", "inspect_table"}:
            data.pop("query", None)
        if has_source_observation and call.name == "inspect_document_sources":
            # Offset/page/limit describe how the batch was requested, not what
            # was read. Excluding them keeps a replayed batch from looking new
            # when the model varies pagination arguments without changing the
            # returned Source records.
            for key in ("offset", "page", "limit", "next_offset"):
                data.pop(key, None)
        normalized_paper_list = call.name == "browse_collection_papers" and (
            data.get("papers") or data.get("paper_total")
        )
        if normalized_paper_list:
            # A paper list is progress only when its returned identities or
            # metadata change. Search wording and pagination controls alone do
            # not justify another model cycle over the same list.
            for key in ("query", "offset", "page", "limit", "next_offset"):
                data.pop(key, None)
        # Coverage is runtime metadata added after this observation and must not
        # make an otherwise identical batch look like new source content.
        data.pop("source_coverage", None)
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
        if not has_source_observation and not normalized_paper_list:
            # Distinct failed or empty searches must keep their requested scope.
            payload["arguments"] = dict(call.arguments)
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        previous = len(self.seen_observations)
        self.seen_observations.add(digest)
        self.resource_refs.update((ref.resource_type, ref.resource_id) for ref in result.resource_refs)
        completed = capability_policy.complete_source_reads({call.name: [result.data]})
        new_sources = completed - self.complete_source_identities
        self.complete_source_identities.update(completed)
        new_resource_refs = self.resource_refs - previous_resource_refs
        observation_changed = len(self.seen_observations) > previous
        if not has_source_observation:
            if normalized_paper_list:
                return bool(new_resource_refs)
            return observation_changed
        # A canonical Source can be incomplete while its current page still
        # contributes new evidence. The normalized observation digest handles
        # page and table-row progress, while complete identities suppress
        # repeated full reads.
        has_canonical_identity = bool(completed) or any(
            isinstance(item, Mapping)
            and all(str(item.get(key) or "").strip() for key in
                    ("document_id", "source_kind", "source_ref", "source_digest"))
            for item in (result.data, *(result.data.get("sources") or ()))
            if isinstance(result.data, Mapping)
        )
        if has_canonical_identity:
            return bool(new_sources) or observation_changed
        # Older/custom read capabilities may expose only a resource reference.
        # Preserve their progress semantics without weakening canonical dedupe.
        return bool(new_resource_refs) or observation_changed

    def source_coverage(self, call: ChatToolCall, result: ChatToolResult) -> dict[str, int]:
        completed = capability_policy.complete_source_reads({call.name: [result.data]})
        new_sources = completed - self.complete_source_identities
        return {
            "complete_source_count": len(completed),
            "new_complete_source_count": len(new_sources),
            "already_complete_source_count": len(completed & self.complete_source_identities),
        }

    def trace(self, context: AgentContext, *, phase: str, capability_names: tuple[str, ...] = (),
              requested_count: int = 0, new_resources: int = 0,
              termination_reason: str | None = None, final_answer: bool = False,
              retry_attempt: int | None = None, retry_reason: str | None = None) -> None:
        payload = {
            "session_id": context.session_id, "request_id": get_request_id(), "phase": phase,
            "cycle_index": self.model_cycles, "selected_capability_names": capability_names,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "total_tokens": self.model_tokens, "unreported_model_calls": self.unreported_model_calls,
            "requested_tool_count": requested_count, "executed_tool_count": self.executed_tool_calls,
            "new_resource_reference_count": new_resources,
            "observation_digest_changed": self.consecutive_no_progress == 0,
            "elapsed_ms": round((monotonic() - self.started_at) * 1000),
            "remaining_tool_budget": (max(0, self.limits.max_tool_calls - self.executed_tool_calls)
                                      if self.limits.max_tool_calls is not None else None),
            "remaining_token_budget": (max(0, self.limits.max_model_tokens - self.model_tokens)
                                       if self.limits.max_model_tokens is not None else None),
            "research_plan": [dict(item) for item in self.research_plan] if self.research_plan else None,
            "termination_reason": termination_reason, "final_answer_present": final_answer,
            "retry_attempt": retry_attempt, "retry_reason": retry_reason,
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
        response_started_callback: Callable[[str, str], None] | None = None,
    ) -> AgentRunResult:
        progress = _RunProgress(self.limits, progress_callback=progress_callback,
                                response_started_callback=response_started_callback)
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
        progress.initialize_research_plan(user_message)
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
        response_started_callback: Callable[[str, str], None] | None = None,
    ) -> AgentRunResult:
        progress = _RunProgress(self.limits, progress_callback=progress_callback,
                                response_started_callback=response_started_callback)
        capability_policy.validate_claimed_call(context, claimed_call)
        messages = list(previous_messages)
        progress.initialize_research_plan(self._active_user_request(messages))
        inherited_completed_writes = capability_policy.completed_write_names(messages)
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
            error, validated_arguments = capability_policy.validate_batch(
                self.capabilities,
                ((claimed_call, handler),), messages
            )
            if not error:
                progress.executed_tool_calls += 1
            call, result = (
                self._failure(claimed_call, *error) if error
                else await self._execute_one(
                    context,
                    claimed_call,
                    handler,
                    arguments=validated_arguments.get(claimed_call.tool_call_id),
                )
            )
        calls[-1] = call
        results.append(result)
        messages.append(self._result_message(context, result))
        await self._checkpoint(checkpoint, messages, calls, results)
        if result.status is ToolResultStatus.SUCCEEDED and call.name in {"record_finding_feedback", "curate_finding"}:
            # These writes finish an exact approved review. Report the persisted
            # result directly; a model continuation cannot redefine its status.
            progress.start_response()
            chinese = any("\u4e00" <= char <= "\u9fff" for char in self._active_user_request(messages))
            if call.name == "record_finding_feedback":
                content = "此结论的反馈已保存。" if chinese else "Feedback for this conclusion has been saved."
            else:
                content = ("此结论的人工修订已保存，原发布结论保持不变。" if chinese
                           else "The human revision has been saved. The published conclusion is preserved.")
                content += "\n\n" + str(result.data.get("curated_finding", {}).get("statement", ""))
            if result.data.get("note"):
                content += "\n\n" + ("记录原因：" if chinese else "Recorded reason: ") + str(result.data["note"])
            messages.append(self._assistant(context, content, progress))
            await self._checkpoint(checkpoint, messages, calls, results)
            if text_delta_callback is not None:
                text_delta_callback(content)
            progress.trace(context, phase="terminal", termination_reason="model_answer", final_answer=True)
            return self._result(AgentRunStatus.COMPLETED, messages, calls, results,
                                completion_reason=AgentCompletionReason.MODEL_ANSWER)
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
                progress.start_response()
                try:
                    tool_specs = capability_policy.select_tool_specs(
                        self.capabilities,
                        messages,
                        calls,
                        inherited_completed_writes=inherited_completed_writes,
                    )
                    tool_names = tuple(spec.name for spec in tool_specs)
                    if not tool_specs and results:
                        latest = results[-1]
                        latest_call = next((call for call in reversed(calls)
                                            if call.tool_call_id == latest.tool_call_id), None)
                        if (
                            latest_call is not None and latest_call.name == "create_finding_draft"
                            and latest.status is ToolResultStatus.SUCCEEDED
                            and isinstance(latest.data.get("draft"), Mapping)
                            and latest.data.get("persistence") == "transient_chat_result"
                        ):
                            chinese = any("\u4e00" <= char <= "\u9fff" for char in self._active_user_request(messages))
                            content = ("结论草案已生成，尚未保存或发布。" if chinese else
                                       "The Finding draft is ready and has not been saved or published.")
                            messages.append(self._assistant(context, content, progress))
                            await self._checkpoint(checkpoint, messages, calls, results)
                            if text_delta_callback is not None:
                                text_delta_callback(content)
                            progress.trace(context, phase="terminal", termination_reason="model_answer", final_answer=True)
                            return self._result(AgentRunStatus.COMPLETED, messages, calls, results,
                                                completion_reason=AgentCompletionReason.MODEL_ANSWER)
                        if (
                            latest_call is not None and latest_call.name == "propose_research_plan"
                            and latest.status is ToolResultStatus.SUCCEEDED
                            and latest.data.get("draft_status") in {"ready_for_researcher_review", "needs_finding_review"}
                            and isinstance(latest.data.get("content"), str) and latest.data["content"].strip()
                        ):
                            # The arguments were reviewed before execution; the capability
                            # already rendered the complete draft and its source basis.
                            chinese = any("\u4e00" <= char <= "\u9fff" for char in self._active_user_request(messages))
                            lead = "研究方案草案已生成，尚未保存。" if chinese else "The research-plan draft is ready and has not been saved."
                            if latest.data["draft_status"] == "needs_finding_review":
                                lead += "所引用的研究结论仍需研究者审阅。" if chinese else " Its supporting conclusions still require researcher review."
                            content = f"{lead}\n\n{latest.data['content']}"
                            messages.append(self._assistant(context, content, progress))
                            await self._checkpoint(checkpoint, messages, calls, results)
                            if text_delta_callback is not None:
                                text_delta_callback(content)
                            progress.trace(context, phase="terminal", termination_reason="model_answer", final_answer=True)
                            return self._result(AgentRunStatus.COMPLETED, messages, calls, results,
                                                completion_reason=AgentCompletionReason.MODEL_ANSWER)
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
                        "Research Agent capabilities selected step=%d max_steps=%s "
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
                        stage_content = capability_policy.stage_instruction(
                            tool_names,
                            calls,
                            successful_results=capability_policy.active_successful_results_by_name(messages),
                        )
                        if stage_content is not None:
                            stage_instruction = ChatMessage.user(
                                message_id=self._message_id(),
                                session_id=context.session_id,
                                content=stage_content,
                                created_at=_now_iso(),
                            )
                            decision_messages = (*decision_messages, stage_instruction)
                    if (
                        required_action_instruction is None
                        and stage_instruction is None
                        and not tool_specs
                        and (
                            self._latest_structured_deliverable(results) is not None
                            or any(result.data.get("draft_status") == "abstained" for result in results)
                        )
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
                        replace(
                            await self._prepare_model_context(
                                decision_messages, tool_specs, progress, active_user_message_id=next(
                                    message.message_id for message in reversed(messages) if message.role is ChatMessageRole.USER
                                ),
                            ),
                            require_tool_call=capability_policy.required_tool_before_answer(
                                tool_names,
                                successful_results=capability_policy.active_successful_results_by_name(messages),
                            ) is not None,
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
                        progress.trace(
                            context,
                            phase="model_retry",
                            retry_attempt=response_retries,
                            retry_reason=exc.reason,
                        )
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
                            self._failure_answer(messages, calls, results, review_reason=exc.reason),
                            progress,
                        )
                    )
                    await self._checkpoint(checkpoint, messages, calls, results)
                    progress.trace(context, phase="terminal", termination_reason="model_response_invalid")
                    return self._result(
                        AgentRunStatus.FAILED,
                        messages,
                        calls,
                        results,
                        exc.reason if exc.reason.startswith("research_") else "model_response_invalid",
                    )
                except Exception as exc:  # noqa: BLE001
                    model_name = str(
                        getattr(self.model, "model", None)
                        or type(self.model).__name__
                    )
                    retryable_provider = _is_retryable_provider_exception(exc)
                    logger.warning(
                        "Research Agent model call failed model=%s "
                        "exception_type=%s retryable=%s",
                        model_name,
                        type(exc).__name__,
                        retryable_provider,
                    )
                    if (
                        retryable_provider
                        and response_retries < _MODEL_RESPONSE_RETRY_LIMIT
                        and progress.remaining_seconds() > 0
                    ):
                        response_retries += 1
                        progress.trace(
                            context,
                            phase="model_retry",
                            retry_attempt=response_retries,
                            retry_reason=type(exc).__name__.lower(),
                        )
                        logger.info(
                            "Retrying Research Agent provider response model=%s "
                            "attempt=%d",
                            model_name,
                            response_retries + 1,
                        )
                        continue
                    provider_timeout = "timeout" in type(exc).__name__.lower()
                    messages.append(
                        self._assistant(
                            context,
                            self._failure_answer(messages, calls, results),
                            progress,
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
                required_tool = capability_policy.required_tool_before_answer(
                    tool_names,
                    successful_results=capability_policy.active_successful_results_by_name(messages),
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
                        self._assistant(context, self._failure_answer(messages, calls, results), progress)
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
                messages.append(self._assistant(context, turn.content, progress))
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
                progress=progress,
            )
            batch_start = len(calls)
            calls.extend(call for call, _ in requested)
            await self._checkpoint(checkpoint, messages, calls, results)
            stop_reason = progress.stop_before_model()
            if (self.limits.max_tool_calls is not None
                    and progress.executed_tool_calls + len(requested) > self.limits.max_tool_calls):
                stop_reason = AgentCompletionReason.RESOURCE_BUDGET
            if stop_reason:
                error = ("resource_budget", "These Sources or actions remain uninspected or unexecuted in this turn.")
                validated_arguments = {}
            else:
                error, validated_arguments = capability_policy.validate_batch(self.capabilities, requested, messages)
            if error:
                completed = tuple(self._failure(call, *error) for call, _ in requested)
            elif len(requested) == 1 and capability_policy.evaluate_authorization(requested[0][0].risk).requires_approval:
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
                completed = await self._execute_read_batch(
                    context,
                    requested,
                    progress,
                    validated_arguments=validated_arguments,
                )
            old_resource_count = len(progress.resource_refs)
            prior_no_progress = progress.consecutive_no_progress
            progress_increased = False
            for index, (call, capability_result) in enumerate(completed):
                calls[batch_start + index] = call
                if capability_result.status is ToolResultStatus.SUCCEEDED and call.name in {
                    "read_source", "inspect_table", "inspect_document_sources",
                }:
                    coverage = progress.source_coverage(call, capability_result)
                    capability_result = replace(capability_result, data={
                        **dict(capability_result.data), "source_coverage": coverage,
                    })
                progress.update_research_plan(call.name, capability_result.status)
                results.append(capability_result)
                messages.append(self._result_message(context, capability_result))
                progress_increased = progress.observe(call, capability_result) or progress_increased
            progress.consecutive_no_progress = (
                prior_no_progress + 1 if not progress_increased else 0
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
        check_research: bool = True,
    ) -> ModelTurn:
        timeout = progress.remaining_seconds()
        output_limit = self.limits.max_model_output_tokens
        if self.limits.max_model_tokens is not None:
            output_limit = min(output_limit, self.limits.max_model_tokens - progress.model_tokens)
        if finalizing:
            timeout = min(timeout, self.limits.max_finalization_seconds)
            output_limit = self.limits.max_finalization_output_tokens
        if model_context.compacting:
            output_limit = min(output_limit, 8192)
        if timeout <= 0:
            raise TimeoutError("research turn deadline reached")
        model_context = replace(model_context, max_context_tokens=self.limits.max_context_tokens)
        prompt = (RESEARCH_COMPACTION_SYSTEM_PROMPT if model_context.compacting else
                  RESEARCH_REVIEW_SYSTEM_PROMPT if model_context.research_review is not None else RESEARCH_AGENT_SYSTEM_PROMPT)
        request_tokens = self.context_builder.estimate_tokens({
            "messages": model_context.provider_messages(prompt),
            "tools": [spec.model_schema() for spec in tool_specs],
        })
        if request_tokens + output_limit + 1024 > self.limits.max_context_tokens:
            raise ModelResponseError("Model request exceeds its context window.",
                                     reason="context_window_exceeded", retryable=False)
        if check_research:
            progress.read_batch_tokens = max(1024, min(16_000,
                self.limits.max_context_tokens - request_tokens - output_limit - 4096))
        arguments: dict[str, Any] = {
            "context": model_context,
            "tool_specs": tool_specs,
            "timeout_seconds": timeout,
            "max_output_tokens": output_limit,
        }
        names_by_id = {
            call.tool_call_id: call.name
            for message in model_context.messages for call in message.tool_calls
        }
        research_context = bool(model_context.working_summary) or any(
            message.source_contexts or (
                message.tool_result is not None
                and names_by_id.get(message.tool_call_id) in _RESEARCH_OBSERVATION_TOOLS
            )
            for message in model_context.messages
        )
        buffer_answer = model_context.require_tool_call or (check_research and (
            research_context or any(spec.name in _RESEARCH_DRAFT_TOOLS for spec in tool_specs)
        ))
        if text_delta_callback is not None:
            # A response rejected for skipping a required read must not appear
            # in the browser as a completed research answer.
            arguments["text_delta_callback"] = (
                (lambda _delta: None) if buffer_answer else text_delta_callback
            )
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
        if check_research and (
            (not turn.tool_calls and research_context and not model_context.require_tool_call)
            or any(call.name in _RESEARCH_DRAFT_TOOLS for call in turn.tool_calls)
        ):
            finish_only = finalizing or (not turn.tool_calls and progress.stop_before_model() is not None)
            turn = await self._review_research_turn(
                turn, model_context, () if finish_only else tool_specs, progress, text_delta_callback,
                finalizing=finish_only,
            )
        if buffer_answer and turn.tool_calls:
            # Tool activity has its own UI; unreviewed scientific narration must
            # not enter the conversation through a read-call preamble.
            turn = replace(turn, content="")
        if buffer_answer and not model_context.require_tool_call and text_delta_callback and turn.content:
            text_delta_callback(turn.content)
        return turn

    async def _prepare_model_context(
        self, messages: tuple[ChatMessage, ...], tool_specs: tuple[ToolSpec, ...],
        progress: _RunProgress, *, active_user_message_id: str,
    ) -> ChatModelContext:
        """Compact old operations into provisional notes; the durable trajectory stays intact."""
        overhead = self.context_builder.estimate_tokens({
            "messages": ChatModelContext(()).provider_messages(RESEARCH_AGENT_SYSTEM_PROMPT),
            "tools": [spec.model_schema() for spec in tool_specs],
        })
        input_budget = self.limits.max_context_tokens - self.limits.max_model_output_tokens - overhead - 2048
        if tool_specs:
            input_budget -= min(16_000, max(0, input_budget // 3))
        available = tuple(message for message in messages if message.message_id not in progress.compacted_message_ids)
        view = self.context_builder.for_model(
            available, active_user_message_id=active_user_message_id,
            max_input_tokens=input_budget, working_summary=progress.working_summary,
        )
        kept = {message.message_id for message in view.messages}
        omitted = tuple(message for message in available if message.message_id not in kept)
        active = next(message for message in messages if message.message_id == active_user_message_id)
        units = list(self.context_builder._protocol_units(omitted))
        while units:
            if progress.compaction_attempts >= 3:
                if progress.working_summary:
                    logger.warning(
                        "Research context compaction degraded to recent context after retries"
                    )
                    return replace(view, max_context_tokens=self.limits.max_context_tokens)
                raise ModelResponseError("Research context could not be compacted without repeated retries.",
                                         reason="context_compaction_unavailable", retryable=False)
            batch: list[ChatMessage] = []
            for unit in units:
                candidate = ChatModelContext((active, *batch, *unit), compacting=True,
                                             working_summary=progress.working_summary)
                tokens = self.context_builder.estimate_tokens(candidate.provider_messages(RESEARCH_COMPACTION_SYSTEM_PROMPT))
                if tokens + 8192 + 2048 > self.limits.max_context_tokens:
                    break
                batch.extend(unit)
            if not batch:
                raise ModelResponseError("One research observation exceeds the context window.",
                                         reason="context_window_exceeded", retryable=False)
            progress.trace(AgentContext(active.session_id, "", ""), phase="context_compaction")
            compaction_messages = (active, *batch)
            progress.compaction_attempts += 1
            for attempt in range(2):
                try:
                    compacted = await self._respond(
                        ChatModelContext(compaction_messages, compacting=True, working_summary=progress.working_summary),
                        (), progress, None, check_research=False,
                    )
                    if compacted.tool_calls:
                        raise ValueError("compaction cannot request tools")
                    notes = ResearchWorkingNotes.model_validate_json(extract_json_object(compacted.content))
                    allowed_ids = progress.compacted_message_ids | {message.message_id for message in (active, *batch)}
                    if any(set(check.basis_message_ids) - allowed_ids for check in notes.checks):
                        raise ValueError("working note cites an unobserved message")
                    summary = self._bounded_working_notes(
                        notes, max_tokens=min(6000, input_budget // 3),
                    ).model_dump_json()
                    break
                except ValueError:
                    if attempt:
                        if progress.working_summary:
                            logger.warning(
                                "Research context compaction returned invalid notes; keeping prior notes"
                            )
                            return replace(view, max_context_tokens=self.limits.max_context_tokens)
                        raise ModelResponseError("Research working notes could not be preserved.",
                                                 reason="context_compaction_unavailable", retryable=False) from None
                    compaction_messages = (*compaction_messages, ChatMessage.user(
                        message_id=self._message_id(), session_id=active.session_id, created_at=_now_iso(),
                        content="Return concise JSON matching OUTPUT_SCHEMA exactly: scope is a string; "
                        "next_actions is an array of strings, not objects. All basis_message_ids must "
                        "come from the supplied records or prior notes. Preserve scientific uncertainty; "
                        "format repair does not verify a claim. Use at most 3000 tokens.",
                    ))
                except ModelResponseError:
                    if progress.working_summary:
                        logger.warning(
                            "Research context compaction request failed; keeping prior notes"
                        )
                        return replace(view, max_context_tokens=self.limits.max_context_tokens)
                    raise
            else:
                raise ModelResponseError("Research working notes could not be preserved.",
                                         reason="context_compaction_unavailable", retryable=False)
            # A successful compaction closes this failure streak. The counter
            # guards consecutive failed attempts, not the lifetime of a long
            # investigation; otherwise later evidence would be forced into a
            # stale recent-only view after three successful compactions.
            progress.compaction_attempts = 0
            progress.working_summary = summary
            progress.compacted_message_ids.update(message.message_id for message in batch)
            units = [unit for unit in units if unit[0].message_id not in progress.compacted_message_ids]
        view = self.context_builder.for_model(
            tuple(message for message in messages if message.message_id not in progress.compacted_message_ids),
            active_user_message_id=active_user_message_id, max_input_tokens=input_budget,
            working_summary=progress.working_summary,
        )
        # Lineage is derived from the complete archived history, not model notes.
        retained = {message.message_id for message in view.messages}
        remaining = tuple(message for message in messages if message.message_id not in progress.compacted_message_ids)
        if any(unit[0].message_id not in retained for unit in self.context_builder._protocol_units(remaining)):
            return await self._prepare_model_context(messages, tool_specs, progress,
                                                     active_user_message_id=active_user_message_id)
        return replace(view, max_context_tokens=self.limits.max_context_tokens)

    def _bounded_working_notes(
        self, notes: ResearchWorkingNotes, *, max_tokens: int,
    ) -> ResearchWorkingNotes:
        """Keep validated navigation notes within their reserved context space."""
        checks = [ResearchWorkingCheck(
            statement=check.statement[:600],
            conditions=check.conditions[:400],
            basis_message_ids=check.basis_message_ids[:8],
            unresolved=check.unresolved[:400],
        ) for check in notes.checks]
        next_actions = [str(action)[:400] for action in notes.next_actions[:8]]
        candidate = ResearchWorkingNotes(
            scope=notes.scope[:1000], checks=checks, next_actions=next_actions,
        )
        while checks and self.context_builder.estimate_tokens(candidate.model_dump_json()) > max_tokens:
            checks.pop()
            candidate = ResearchWorkingNotes(
                scope=candidate.scope, checks=checks, next_actions=next_actions,
            )
        while next_actions and self.context_builder.estimate_tokens(candidate.model_dump_json()) > max_tokens:
            next_actions.pop()
            candidate = ResearchWorkingNotes(
                scope=candidate.scope, checks=checks, next_actions=next_actions,
            )
        if self.context_builder.estimate_tokens(candidate.model_dump_json()) > max_tokens:
            candidate = ResearchWorkingNotes(
                scope=candidate.scope[:400], checks=[], next_actions=[],
            )
        return candidate

    async def _review_research_turn(
        self,
        turn: ModelTurn,
        model_context: ChatModelContext,
        tool_specs: tuple[ToolSpec, ...],
        progress: _RunProgress,
        text_delta_callback: Callable[[str], None] | None,
        *,
        finalizing: bool = False,
    ) -> ModelTurn:
        """Check observable scientific claims and allow one bounded correction."""
        active = next((message for message in model_context.messages
                       if message.message_id == model_context.active_user_message_id), None)
        if active is None:
            active = next(message for message in reversed(model_context.messages)
                          if message.role is ChatMessageRole.USER)
        names = {call.tool_call_id: call.name for message in model_context.messages for call in message.tool_calls}
        coverage = (
            "Only the supplied user constraints and observations are available. "
            "These are selected collection records and passages, not a systematic external "
            "literature search. Omitted, unread, unreported and failed are different states. "
            "Historical references without their text cannot establish a new paper claim."
        )
        if finalizing:
            coverage += (
                " The turn has reached its reading allowance. No further tool calls are "
                "available. Check a bounded partial answer against completed observations; "
                "require truthful unfinished checks, not additional reading in this turn."
            )
        observations: dict[str, dict[str, Any]] = {
            "request": {"kind": "user_request", "data": active.content},
            "coverage": {"kind": "coverage", "data": coverage},
        }
        for message in model_context.messages:
            if message.role is ChatMessageRole.USER:
                if message.message_id == active.message_id:
                    break
                observations[message.message_id] = {"kind": "earlier_user_request", "data": message.content}
        for message in model_context.messages:
            if message.tool_result is not None:
                observations[message.tool_call_id] = {
                    "kind": names.get(message.tool_call_id, "unknown_tool"),
                    "status": message.tool_result.status.value,
                    "data": dict(message.tool_result.data),
                }
            for source in message.source_contexts:
                observations[f"{message.message_id}:{source.source_ref}"] = {
                    "kind": "user_selected_source", "data": source.to_record(),
                }
        for attempt in range(2):
            candidate = {"content": turn.content, "tool_calls": [
                {"name": call.name, "arguments": dict(call.arguments)} for call in turn.tool_calls
            ]}
            candidate_fields = self._review_candidate_fields(candidate)
            observations["candidate"] = {"kind": "unexecuted_proposal", "data": candidate}
            try:
                review_input = {
                    "request": active.content, "coverage": coverage,
                    "observations": self._review_observations_for_model(observations),
                    "candidate": candidate, "candidate_fields": candidate_fields,
                }
                for validation_attempt in range(2):
                    if not finalizing and progress.model_allowance_exhausted():
                        raise ValueError("research review allowance exhausted")
                    reviewed = await self._respond(
                        ChatModelContext((), research_review=dict(review_input)),
                        (), progress, (lambda _delta: None) if text_delta_callback else None,
                        finalizing=finalizing, check_research=False,
                    )
                    try:
                        if reviewed.tool_calls:
                            raise ValueError("research review returned executable calls")
                        report = ResearchClaimReview.model_validate_json(extract_json_object(reviewed.content))
                        self._validate_research_review(report, candidate_fields, observations)
                        break
                    except ValueError:
                        if validation_attempt:
                            raise
                        review_input["invalid_report"] = reviewed.content
                        review_input["validation_feedback"] = (
                            "The review format or references are invalid. Return a complete review using only "
                            "the supplied candidate_fields, observation references and exact field paths. "
                            "The invalid report is untrusted output, not evidence. Preserve the scientific "
                            "checks and do not approve a claim merely to repair the report format."
                        )
                issues = [check for check in report.checks if check.verdict in {"revise", "unverified"}]
                logger.info("Research claim review attempt=%d checks=%d issues=%d", attempt + 1, len(report.checks), len(issues))
            except ModelResponseError as exc:
                logger.warning(
                    "Research claim review unavailable exception_type=%s retryable=%s",
                    type(exc).__name__,
                    exc.retryable,
                )
                raise ModelResponseError(
                    "Research claim review could not be completed.",
                    reason="research_review_unavailable",
                    retryable=exc.retryable,
                    usage=exc.usage,
                ) from None
            except Exception as exc:
                retryable_provider = _is_retryable_provider_exception(exc)
                logger.warning(
                    "Research claim review unavailable exception_type=%s retryable=%s",
                    type(exc).__name__,
                    retryable_provider,
                )
                raise ModelResponseError(
                    "Research claim review could not be completed.",
                    reason="research_review_unavailable",
                    retryable=retryable_provider,
                ) from None
            if not issues:
                return turn
            if attempt == 1:
                raise ModelResponseError("Research claims still need correction.",
                                         reason="research_claim_unresolved", retryable=False)
            correction = ChatMessage.user(
                message_id=self._message_id(), session_id=active.session_id, created_at=_now_iso(),
                content=(
                    "The proposed answer or draft has not been accepted or executed. Correct the "
                    "specific research checks below using the original request and observations. "
                    "Preserve the requested deliverable. "
                    + ("The reading allowance is exhausted. Return a corrected partial answer using "
                       "only completed observations and name unfinished checks. " if finalizing else
                    "If a check requires more available Source "
                    "content, return the necessary read or discovery calls now; the main research "
                    "loop will execute them and then finish the deliverable. Otherwise return the "
                    "complete corrected answer or draft arguments. ")
                    + "Do not narrate this internal review. Uncertain claims can "
                    "remain explicitly unresolved; do not invent evidence to make the check pass.\n"
                    + json.dumps({"candidate": candidate, "checks": [
                        {**check.model_dump(), "claim": candidate_fields[check.candidate_path], "basis": [
                            {**basis.model_dump(), "quote": self._review_candidate_fields(
                                observations[basis.reference]["data"],
                            )[basis.field_path]}
                            for basis in check.basis
                        ]}
                        for check in issues
                    ]}, ensure_ascii=False)
                ),
            )
            try:
                if not finalizing and progress.model_allowance_exhausted():
                    raise ValueError("research correction allowance exhausted")
                repair_context = await self._prepare_model_context(
                    (*model_context.messages, correction), tool_specs, progress,
                    active_user_message_id=active.message_id,
                )
                expected_drafts = {call.name for call in turn.tool_calls if call.name in _RESEARCH_DRAFT_TOOLS}
                turn = await self._respond(
                    replace(repair_context, require_tool_call=model_context.require_tool_call or bool(expected_drafts)),
                    tool_specs, progress, (lambda _delta: None) if text_delta_callback else None,
                    finalizing=finalizing, check_research=False,
                )
                if turn.tool_calls and all(
                    call.name in intent_policy.SOURCE_READ_CAPABILITIES | {"discover_research_tools"}
                    and any(spec.name == call.name and spec.risk is ToolRisk.READ for spec in tool_specs)
                    for call in turn.tool_calls
                ):
                    return replace(turn, content="")
                if expected_drafts and {call.name for call in turn.tool_calls} != expected_drafts:
                    raise ValueError("research correction must retain the requested draft action")
            except ModelResponseError as exc:
                logger.warning(
                    "Research claim correction unavailable exception_type=%s retryable=%s",
                    type(exc).__name__,
                    exc.retryable,
                )
                raise ModelResponseError(
                    "Research claim correction could not be completed.",
                    reason="research_review_unavailable",
                    retryable=exc.retryable,
                    usage=exc.usage,
                ) from None
            except Exception as exc:
                retryable_provider = _is_retryable_provider_exception(exc)
                logger.warning(
                    "Research claim correction unavailable exception_type=%s retryable=%s",
                    type(exc).__name__,
                    retryable_provider,
                )
                raise ModelResponseError(
                    "Research claim correction could not be completed.",
                    reason="research_review_unavailable",
                    retryable=retryable_provider,
                ) from None
        raise AssertionError("research review loop did not terminate")

    @staticmethod
    def _validate_research_review(
        report: ResearchClaimReview,
        candidate_fields: Mapping[str, str],
        observations: Mapping[str, Mapping[str, Any]],
    ) -> None:
        for check in report.checks:
            if check.verdict != "not_applicable" and check.candidate_path not in candidate_fields:
                raise ValueError("review target is not in the candidate")
            if check.verdict != "not_applicable" and not any(
                basis.reference in observations
                and observations[basis.reference]["kind"] != "unexecuted_proposal"
                for basis in check.basis
            ):
                raise ValueError("research candidate cannot support itself")
            for basis in check.basis:
                observed = observations.get(basis.reference)
                if observed is None or basis.field_path not in ResearchAgentRunner._review_candidate_fields(observed["data"]):
                    raise ValueError("research review basis is not an observed field")

    @staticmethod
    def _review_observations_for_model(observations: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        remaining = 60_000
        for ref, observed in observations.items():
            fields = ResearchAgentRunner._review_candidate_fields(observed["data"])
            bounded: dict[str, str] = {}
            for path, value in fields.items():
                if remaining <= 0:
                    break
                # Source excerpts can be much larger than the claim being
                # checked. Keep enough leading text to identify the evidence,
                # while reserving room for other Sources and lineage fields.
                text = value if len(value) <= 6_000 else value[:6_000] + "...[truncated for review]"
                text = text[:remaining]
                bounded[path] = text
                remaining -= len(text)
            rendered.append({
                "reference": ref, "kind": observed["kind"], "status": observed.get("status"),
                "fields": bounded,
            })
            if remaining <= 0:
                break
        return rendered

    @staticmethod
    def _review_candidate_fields(value: Any, path: str = "") -> dict[str, str]:
        if isinstance(value, str):
            return {path: value}
        if value is None or isinstance(value, (bool, int, float)):
            return {path: json.dumps(value)}
        if isinstance(value, (Mapping, list, tuple)) and not value:
            return {path: json.dumps(value)}
        children = value.items() if isinstance(value, Mapping) else enumerate(value) if isinstance(value, (list, tuple)) else ()
        container = ({path: json.dumps(value, ensure_ascii=False)} if isinstance(value, (list, tuple))
                     and all(item is None or isinstance(item, (str, bool, int, float)) for item in value) else {})
        return container | {
            ref: text for key, child in children
            for ref, text in ResearchAgentRunner._review_candidate_fields(
                child, f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}",
            ).items()
        }

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
            budget_exhausted=reason in {
                AgentCompletionReason.RESOURCE_BUDGET,
                AgentCompletionReason.EMERGENCY_CEILING,
            },
        )
        logger.info(
            "Research Agent final answer reason=%s tools=none", reason.value,
        )
        progress.start_response()
        try:
            turn = await self._respond(
                await self._prepare_model_context(
                    (*messages, instruction), (), progress, active_user_message_id=next(
                        message.message_id for message in reversed(messages) if message.role is ChatMessageRole.USER
                    ),
                ),
                (), progress, text_delta_callback, finalizing=True,
            )
            if turn.tool_calls or not turn.content:
                raise ValueError("final answer must be answer-only")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Research Agent final answer failed exception_type=%s",
                type(exc).__name__,
            )
            messages.append(self._assistant(context, self._failure_answer(
                messages, calls, results, review_reason=exc.reason if isinstance(exc, ModelResponseError) else "",
            ), progress))
            progress.trace(context, phase="finalize", termination_reason="final_answer_unavailable")
            await self._checkpoint(checkpoint, messages, calls, results)
            return self._result(AgentRunStatus.FAILED, messages, calls, results, "final_answer_unavailable")
        messages.append(self._assistant(context, turn.content, progress))
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
        last_user = max((index for index, message in enumerate(messages) if message.role is ChatMessageRole.USER), default=0)
        prior_messages = messages[:last_user]
        prior_names = {
            request.tool_call_id: request.name
            for message in prior_messages for request in message.tool_calls
        }
        prior_reads = capability_policy.complete_source_reads({
            name: [
                message.tool_result.data for message in prior_messages
                if message.tool_result is not None
                and message.tool_result.status is ToolResultStatus.SUCCEEDED
                and prior_names.get(message.tool_call_id) == name
            ]
            for name in ("read_source", "inspect_table", "inspect_document_sources")
        })
        prior_reading = "\n".join(
            f"- document_id={document_id}, kind={kind}, source_ref={ref}, digest={digest}"
            for document_id, kind, ref, digest in sorted(prior_reads)[:30]
        ) or "No complete Source read is recorded in earlier requests."
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
        if next((result.data.get("draft_status") for result in reversed(results) if result.data.get("draft_status")), None) == "abstained":
            lead = (
                "No reviewable draft was produced. Explain the unresolved support gap from "
                "the last result and which information would permit a new attempt. Do not "
                "claim the draft is ready, saved, or about to be resubmitted. No further "
                "action is available in this turn."
            )
        return ChatMessage.user(
            message_id=self._message_id(),
            session_id=context.session_id,
            content=(
                f"{lead}\n\n"
                "ACTIVE RESEARCH REQUEST (answer this request; do not restart "
                f"onboarding):\n{active_request}\n\n"
                "CURRENT REQUEST READING LEDGER (this request only, not the whole conversation):\n"
                f"{self._reading_ledger(calls, results)}\n\n"
                "EARLIER REQUESTS: COMPLETE SOURCES INSPECTED\n"
                f"{prior_reading}\n"
                "Zero new reads does not erase earlier reading. Use earlier Source content still "
                "present in the trajectory for the requested synthesis; distinguish historical "
                "inspection from current validation. A reference alone cannot recover omitted "
                "content or authorize a new Evidence write."
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
        progress: _RunProgress,
    ) -> tuple[tuple[ChatToolCall, Any], ...]:
        assistant_message_id = progress.response_message_id
        requested = []
        seen_requests: set[tuple[str, str]] = set()
        for position, model_call in enumerate(turn.tool_calls):
            arguments = dict(model_call.arguments)
            if model_call.name == "curate_finding":
                arguments = self._complete_curation_shape(arguments, messages)
            if model_call.name == "create_finding_draft":
                # Drafts are transient and researcher-reviewed. Models often omit
                # this conservative classification even though the schema marks it
                # conditional (abstentions must omit it). Normalize that one safe
                # omission before validation; published Finding writes remain strict.
                if (
                    arguments.get("statement")
                    and not arguments.get("abstention_reason")
                    and not arguments.get("assertion_strength")
                ):
                    arguments["assertion_strength"] = "descriptive"
                for field_name in (
                    "supporting_evidence_ids", "contradicting_evidence_ids",
                    "context_evidence_ids", "condition_boundary_evidence_ids",
                ):
                    values = arguments.get(field_name)
                    if isinstance(values, list) and all(isinstance(value, str) for value in values):
                        arguments[field_name] = list(dict.fromkeys(values))
            request_key = (
                model_call.name,
                json.dumps(arguments, sort_keys=True, separators=(",", ":")),
            )
            if request_key in seen_requests:
                continue
            if len(requested) >= _MAX_TOOL_CALLS_PER_RESPONSE:
                logger.warning(
                    "Research Agent tool batch truncated requested=%d retained=%d limit=%d",
                    len(turn.tool_calls), len(requested), _MAX_TOOL_CALLS_PER_RESPONSE,
                )
                break
            seen_requests.add(request_key)
            registered = self.capabilities.get(model_call.name)
            call = ChatToolCall.requested(
                tool_call_id=self._tool_call_id(), session_id=context.session_id,
                assistant_message_id=assistant_message_id, position=position,
                name=model_call.name, arguments=arguments,
                risk=registered.spec.risk if registered else ToolRisk.UNKNOWN,
            )
            requested.append((call, registered if model_call.name in allowed_names else None))
        messages.append(
            ChatMessage.assistant_tool_calls(
                message_id=assistant_message_id,
                session_id=context.session_id,
                content=turn.content,
                tool_calls=tuple(call.to_request() for call, _ in requested),
                created_at=progress.response_created_at,
            )
        )
        return tuple(requested)

    @staticmethod
    def _complete_curation_shape(
        arguments: dict[str, Any], messages: list[ChatMessage],
    ) -> dict[str, Any]:
        """Preserve the canonical Finding envelope after it was read.

        Curation may revise the researcher's requested statement and limitations,
        but identity, lineage, evidence bindings, and context serialization come
        from the exact Finding inspection. This prevents a model from losing
        provenance while still leaving scientific text subject to normal
        validation and approval.
        """
        # Curation commonly follows a separate feedback/approval turn. Keep the
        # exact Finding inspection from the full trajectory available; active
        # turn scoping would discard it before the second approval.
        inspected = capability_policy._successful_results_by_name(messages).get(
            "inspect_published_finding", ()
        )
        canonical = next(
            (result.get("finding") for result in reversed(inspected)
             if isinstance(result.get("finding"), Mapping)
             and str(result["finding"].get("objective_id") or "") == str(arguments.get("objective_id") or "")
             and str(result["finding"].get("finding_id") or "") == str(arguments.get("finding_id") or "")
             and str(result["finding"].get("analysis_version") or "") == str(arguments.get("analysis_version") or "")),
            None,
        )
        candidate = dict(arguments.get("curated_finding") or {})
        if not canonical or not candidate:
            return arguments
        # A common model typo is singular ``limitation``. It is a structural
        # alias only; no scientific value is synthesized.
        if "limitations" not in candidate and "limitation" in candidate:
            candidate["limitations"] = candidate.pop("limitation")
        editable = {"statement", "limitations", "certainty", "direction",
                    "assertion_strength", "attribution_scope", "synthesis_status",
                    "factors", "outcome"}
        for key, value in canonical.items():
            if key not in editable or key not in candidate:
                candidate[key] = value
        return {**arguments, "curated_finding": candidate}


    async def _execute_read_batch(
        self,
        context,
        requested,
        progress,
        *,
        validated_arguments: Mapping[str, BaseModel],
    ):
        semaphore = Semaphore(self.limits.max_parallel_reads)

        async def bounded(call, handler):
            async with semaphore:
                try:
                    return await wait_for(
                        self._execute_one(
                            context,
                            call,
                            handler,
                            arguments=validated_arguments.get(call.tool_call_id),
                            max_result_tokens=max(512, progress.read_batch_tokens // len(requested)),
                        ),
                        timeout=progress.remaining_seconds(),
                    )
                except TimeoutError:
                    return self._failure(call, "capability_timeout", "The Source or action could not be completed in this turn.")

        if all(handler.spec.parallel_safe for _, handler in requested):
            return tuple(await gather(*(bounded(call, handler) for call, handler in requested)))
        return tuple([await bounded(call, handler) for call, handler in requested])


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
    def _failure_answer(
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        review_reason: str = "",
    ) -> str:
        chinese = any("\u4e00" <= char <= "\u9fff" for char in ResearchAgentRunner._active_user_request(messages))
        lead = (
            "本轮回答未能完成，已取得的结果已保留。这是技术中断，不能据此判断论文没有证据。可以继续核对未完成的部分。"
            if chinese else
            "This turn could not be completed. Obtained results were preserved; the technical "
            "interruption does not establish an absence of scientific evidence. You can continue the unfinished review."
        )
        if review_reason in {"research_claim_unresolved", "research_review_unavailable"}:
            lead = (
                "本轮内容尚未通过来源范围与测量指标核对，暂不返回未经确认的结论或新草案。已取得的阅读结果已保留；这不代表论文没有相关证据。"
                if chinese else
                "The proposed content has not passed the source-scope and measurement checks, "
                "so no unchecked conclusion or new draft is returned. Obtained reading results "
                "were preserved; this does not establish an absence of evidence."
            )
        if not any(call.name in {"browse_collection_papers", "read_source", "inspect_table", "inspect_document_sources", "search_sources"} for call in calls):
            return lead
        ledger = ResearchAgentRunner._reading_ledger(calls, results, chinese=chinese)
        return f"{lead}\n\n{ledger}"

    @staticmethod
    def _reading_ledger(
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        chinese: bool = False,
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
        successful_reads: dict[str, list[Mapping[str, Any]]] = {}
        for result in results:
            call = calls_by_id.get(result.tool_call_id)
            name = call.name if call else None
            if result.status is ToolResultStatus.FAILED:
                document_id = str(result.data.get("document_id") or
                                  (call.arguments.get("document_id") if call else "") or "").strip()
                if document_id and result.error_code not in {"resource_budget", "invalid_tool_batch", "capability_unavailable_for_turn"}:
                    failed_documents.add(document_id)
                continue
            if result.status is not ToolResultStatus.SUCCEEDED:
                continue
            if name in {"read_source", "inspect_table", "inspect_document_sources"}:
                successful_reads.setdefault(name, []).append(result.data)
            if name == "browse_collection_papers":
                paper_total = result.data.get("paper_total")
                if isinstance(paper_total, int) and paper_total >= 0 and not result.data.get("query"):
                    collection_paper_totals.add(paper_total)
                screened_documents.update(
                    str(item.get("document_id") or "").strip()
                    for item in result.data.get("papers") or ()
                    if isinstance(item, Mapping)
                )
        for document_id, _kind, source_ref, _digest in capability_policy.complete_source_reads(successful_reads):
            exact_sources.add(f"{document_id}:{source_ref}")
            read_documents.add(document_id)

        def display(values: set[str]) -> str:
            return ", ".join(sorted(value for value in values if value)[:30]) or ("无" if chinese else "none")

        paper_total = (
            str(max(collection_paper_totals)) if collection_paper_totals else ("尚未核实" if chinese else "unknown")
        )
        unread_documents = (screened_documents | requested_documents) - read_documents - failed_documents
        if chinese:
            return (
                f"论文总数: {paper_total}\n"
                f"已浏览论文信息 ({len(screened_documents)}): {display(screened_documents)}\n"
                f"已完整读取的原文片段 ({len(exact_sources)}): {display(exact_sources)}\n"
                f"原文读取曾失败的论文 ({len(failed_documents)}): {display(failed_documents)}\n"
                f"尚未完成原文读取的论文 ({len(unread_documents)}): {display(unread_documents)}"
            )
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
        *,
        arguments: BaseModel | None = None,
        max_result_tokens: int = 12_000,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        if arguments is None:
            try:
                arguments = handler.spec.input_model.model_validate(call.arguments)
            except ValidationError:
                return ResearchAgentRunner._failure(
                    call,
                    "invalid_tool_arguments",
                    "The research capability arguments are invalid.",
                )
        try:
            execution_context = replace(CapabilityExecutionContext.for_call(context, call.tool_call_id),
                                        max_result_tokens=max_result_tokens)
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
    def _assistant(context: AgentContext, content: str, progress: _RunProgress) -> ChatMessage:
        return ChatMessage.assistant(
            message_id=progress.response_message_id,
            session_id=context.session_id,
            content=content,
            created_at=progress.response_created_at,
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
