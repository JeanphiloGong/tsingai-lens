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
from application.chat import capability_policy
from application.chat.model import ChatModel, ModelResponseError, ModelTurn, ModelUsage
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
        capability_policy.validate_claimed_call(context, claimed_call)
        messages = list(previous_messages)
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
                    tool_specs = capability_policy.select_tool_specs(
                        self.capabilities,
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
                    logger.warning(
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
            logger.warning(
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
        *,
        arguments: BaseModel | None = None,
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
