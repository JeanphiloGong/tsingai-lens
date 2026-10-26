"""Bounded model/capability/result loop for one Research Agent turn."""

from __future__ import annotations

import json
import logging
import traceback
from asyncio import Semaphore, gather, sleep, wait_for
from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from email.utils import parsedate_to_datetime
from hashlib import sha256
from math import isfinite
from random import uniform
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from application.chat import capability_policy
from application.chat.capabilities import (
    AgentContext,
    CapabilityExecutionContext,
    CapabilityRegistry,
    ToolSpec,
)
from application.chat.context_builder import ChatContextBuilder, ChatModelContext
from application.chat.capabilities.execution_plan import UpdateExecutionPlanToolRequest
from application.chat.inline_citations import format_inline_citations
from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentDraftValidationError,
)
from application.core.objectives.paper_experiment_authoring_service import (
    PaperExperimentAuthoringError,
)
from application.chat.model import (
    RESEARCH_AGENT_SYSTEM_PROMPT,
    RESEARCH_COMPACTION_SYSTEM_PROMPT,
    ChatModel,
    ModelResponseError,
    ModelTurn,
    ModelUsage,
    ResearchWorkingCheckModelOutput,
    ResearchWorkingNotesModelOutput,
)
from application.core.structured_extraction.json_support import extract_json_object
from repositories.chat_repository import ModelCallObserver
from domain.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatSourceContext,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolPermissionMode,
    ToolResultStatus,
    ToolRisk,
)
from utils.logger import get_request_id

logger = logging.getLogger(__name__)

_ACTIONABLE_CAPABILITY_EXCEPTIONS = (
    ValueError,
    FileNotFoundError,
    LookupError,
    PermissionError,
)
_SENSITIVE_ERROR_MARKERS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "bearer",
)


def _safe_capability_error_message(exc: BaseException) -> str:
    """Keep domain validation details while hiding arbitrary internal errors."""
    if not isinstance(exc, _ACTIONABLE_CAPABILITY_EXCEPTIONS):
        return "The capability raised an internal error. Review the request and retry."
    detail = " ".join(str(exc).split())[:500]
    if not detail or any(marker in detail.casefold() for marker in _SENSITIVE_ERROR_MARKERS):
        return "The capability rejected the request. Review the arguments and retry."
    return detail

_TrajectoryCheckpoint = Callable[
    [
        tuple[ChatMessage, ...],
        tuple[ChatToolCall, ...],
        tuple[ChatToolResult, ...],
    ],
    Awaitable[None],
]

_MAX_TOOL_CALLS_PER_RESPONSE = 32
# Token estimates use a local tokenizer while the provider counts its own
# serialized request. Keep a small provider-side margin so compaction cannot
# fill the entire advertised window before output tokens and framing are added.
_CONTEXT_SAFETY_MARGIN_TOKENS = 4_096
_MAX_CONTEXT_RECOVERIES = 2
_CONTEXT_SHRINK_RATIO = 0.8
# A long trajectory can contain one protocol unit per Source page plus large
# structured write results. Sending each omitted unit to the model for a
# runtime summary makes recovery compete with the actual research request.
# Keep model-authored notes for short histories and use the bounded archive
# record for longer histories; exact Sources remain available through the
# deterministic prior-reading projection.
_MAX_MODEL_COMPACTION_UNITS = 8
_MIN_REMAINING_SECONDS_FOR_MODEL_COMPACTION = 120.0
_WORKING_NOTES_LOSS_NOTICE = (
    "Some archived details are omitted or truncated in these notes. "
    "Full records remain in the trajectory; reopen exact Sources for missing details."
)
_SAFE_DIAGNOSTIC_EXCEPTION_TYPES = (
    AttributeError,
    IndexError,
    KeyError,
)
_MAX_SAFE_EXCEPTION_MESSAGE_LENGTH = 240


def _exception_text(exc: BaseException) -> str:
    try:
        return " ".join(str(exc).split())
    except Exception:  # noqa: BLE001
        return ""


def _safe_exception_message(exc: BaseException) -> str | None:
    """Keep a short structural error hint without provider or credential text."""
    if not isinstance(exc, _SAFE_DIAGNOSTIC_EXCEPTION_TYPES):
        return None
    message = _exception_text(exc)
    normalized = message.casefold()
    if (
        not message
        or any(marker in normalized for marker in _SENSITIVE_ERROR_MARKERS)
        or "http://" in normalized
        or "https://" in normalized
    ):
        return None
    return message[:_MAX_SAFE_EXCEPTION_MESSAGE_LENGTH]


def _failure_site(exc: BaseException) -> str | None:
    if exc.__traceback__ is None:
        return None
    frame = traceback.extract_tb(exc.__traceback__)[-1]
    filename = frame.filename.rsplit("/", 1)[-1]
    return f"{filename}:{frame.lineno}:{frame.name}"


def _provider_failure_details(exc: BaseException) -> dict[str, Any]:
    """Classify failures with bounded diagnostics and no provider bodies."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and all(current is not item for item in chain):
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    status = None
    retry_after_seconds: float | None = None
    codes: set[str] = set()
    has_code_field = False
    names = {base.__name__ for item in chain for base in type(item).__mro__}
    for item in chain:
        value = getattr(item, "status_code", None)
        if value is None:
            value = getattr(getattr(item, "response", None), "status_code", None)
        if status is None and type(value) is int and 100 <= value <= 599:
            status = value
        headers = getattr(getattr(item, "response", None), "headers", None)
        if headers is None:
            headers = getattr(item, "headers", None)
        if isinstance(headers, Mapping):
            raw_retry_after = headers.get("retry-after") or headers.get("Retry-After")
            try:
                parsed_retry_after = float(raw_retry_after)
            except (TypeError, ValueError):
                try:
                    parsed_retry_after = max(0.0, (parsedate_to_datetime(str(raw_retry_after)) - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    parsed_retry_after = None
            if parsed_retry_after is not None and isfinite(parsed_retry_after) and parsed_retry_after >= 0:
                retry_after_seconds = parsed_retry_after
        body = getattr(item, "body", None)
        error = body.get("error", body) if isinstance(body, Mapping) else {}
        if isinstance(error, Mapping):
            has_code_field = has_code_field or error.get("code") is not None
            codes.update(value for key in ("code", "type")
                         if isinstance(value := error.get(key), str))
    timeout = bool(names.intersection({"TimeoutError", "TimeoutException", "APITimeoutError"}))
    transport = timeout or bool(names.intersection({
        "ConnectionError", "TransportError", "APIConnectionError",
    }))
    if codes.intersection({"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached"}):
        retryable, reason = False, "quota_exhausted"
    elif status is not None:
        retryable = status in {408, 429} or status >= 500
        reason = "provider_timeout" if status == 408 else "http_status"
    elif transport:
        retryable, reason = True, "provider_timeout" if timeout else "transport_error"
    elif codes.intersection({"rate_limit_exceeded", "server_error", "internal_server_error",
                             "overloaded_error", "temporarily_unavailable"}):
        retryable, reason = True, "transient_provider_error"
    else:
        # Some compatible providers emit an SDK APIError inside a successful
        # HTTP stream without a status or code. Bound its retry as a transport
        # failure; never apply this rule to arbitrary application exceptions.
        retryable, reason = (
            (True, "transient_provider_error")
            if any(base.__name__ == "APIError" and base.__module__.startswith("openai")
                   for item in chain for base in type(item).__mro__) and not has_code_field
            else (False, "unclassified_provider_error")
        )
    raw_message = _exception_text(exc)
    fingerprint = sha256(
        f"{type(exc).__name__}\x00{raw_message}".encode("utf-8", "replace")
    ).hexdigest()[:16]
    return {
        "exception_type": type(exc).__name__,
        "exception_chain": [type(item).__name__ for item in chain],
        "failure_site": _failure_site(exc),
        "message": _safe_exception_message(exc),
        "message_fingerprint": fingerprint,
        "http_status": status,
        "retry_after_seconds": retry_after_seconds,
        "retryable": retryable,
        "reason": reason,
    }
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
_SUCCESSFUL_WRITE_RESPONSE_UNAVAILABLE_WARNING = (
    "The approved action completed, but the detailed response was unavailable; "
    "the saved result remains authoritative."
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


class ResearchExecutionStatus(StrEnum):
    """Observable runtime disposition of one research request."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    SCIENTIFIC_REFUSAL = "scientific_refusal"
    PERMISSION_DENIED = "permission_denied"
    STALLED = "stalled"
    TECHNICAL_FAILURE = "technical_failure"
    RESOURCE_LIMITED = "resource_limited"


def _is_permission_failure(reason: str | None) -> bool:
    normalized = str(reason or "").strip().lower()
    # A user rejection is a completed decision in the conversation. It must
    # remain in the trajectory for audit and recovery, but it is not a runtime
    # failure when the assistant can acknowledge it and continue. Explicit
    # permission blocks are still terminal failures.
    return normalized == "tool_permission_denied" or normalized.startswith("permission_")


def _permission_denial_code(results: Iterable[ChatToolResult]) -> str | None:
    """Return the first persisted permission block in the active trajectory."""
    for result in results:
        if result.status is ToolResultStatus.FAILED and _is_permission_failure(result.error_code):
            return result.error_code
    return None


def _research_plan_status(
    *,
    run_status: AgentRunStatus | None,
    completion_reason: AgentCompletionReason | None,
    pending_approval: bool,
    model_status: ResearchExecutionStatus,
    error_code: str | None = None,
) -> ResearchExecutionStatus:
    if run_status is AgentRunStatus.FAILED:
        if _is_permission_failure(error_code):
            return ResearchExecutionStatus.PERMISSION_DENIED
        return ResearchExecutionStatus.TECHNICAL_FAILURE
    if pending_approval:
        return ResearchExecutionStatus.AWAITING_APPROVAL
    if completion_reason in {
        AgentCompletionReason.RESOURCE_BUDGET,
        AgentCompletionReason.EMERGENCY_CEILING,
        AgentCompletionReason.NO_PROGRESS,
    }:
        if completion_reason is AgentCompletionReason.NO_PROGRESS:
            return ResearchExecutionStatus.STALLED
        return ResearchExecutionStatus.RESOURCE_LIMITED
    if completion_reason is AgentCompletionReason.MODEL_ANSWER and model_status is ResearchExecutionStatus.IN_PROGRESS:
        return ResearchExecutionStatus.COMPLETED
    return model_status


@dataclass(frozen=True)
class ResearchExecutionPlan:
    """The latest explicit model plan, with a separate runtime interruption."""

    plan_id: str
    version: int
    request: str
    status: ResearchExecutionStatus
    steps: tuple[Mapping[str, Any], ...]
    model_status: ResearchExecutionStatus
    explanation: str
    blocking_reason: str | None = None

    @classmethod
    def from_messages(
        cls,
        *,
        messages: tuple[ChatMessage, ...],
        run_status: AgentRunStatus | None = None,
        completion_reason: AgentCompletionReason | None = None,
        error_code: str | None = None,
        pending_approval: ChatToolCall | None = None,
    ) -> "ResearchExecutionPlan | None":
        active_index = next((i for i in range(len(messages) - 1, -1, -1)
                             if messages[i].role is ChatMessageRole.USER), None)
        if active_index is None:
            return None
        active = messages[active_index:]
        plan_call_ids = {
            call.tool_call_id for message in active for call in message.tool_calls
            if call.name == "update_execution_plan"
        }
        latest = next((message.tool_result for message in reversed(active)
                       if message.tool_result is not None
                       and message.tool_result.tool_call_id in plan_call_ids
                       and message.tool_result.status is ToolResultStatus.SUCCEEDED), None)
        if latest is None:
            return None
        plan_version = sum(
            1 for message in active
            if message.tool_result is not None
            and message.tool_result.tool_call_id in plan_call_ids
            and message.tool_result.status is ToolResultStatus.SUCCEEDED
        )
        try:
            update = UpdateExecutionPlanToolRequest.model_validate(latest.data)
            model_status = ResearchExecutionStatus(update.status)
        except (ValidationError, TypeError, ValueError):
            return cls(
                plan_id=sha256(f"{active[0].session_id}\x00{active[0].message_id}".encode()).hexdigest()[:20],
                version=plan_version,
                request=active[0].content[:4_000],
                status=ResearchExecutionStatus.TECHNICAL_FAILURE,
                steps=(),
                model_status=ResearchExecutionStatus.TECHNICAL_FAILURE,
                explanation="The saved execution plan could not be restored.",
                blocking_reason="invalid_execution_plan",
            )
        plan = cls(
            plan_id=sha256(f"{active[0].session_id}\x00{active[0].message_id}".encode()).hexdigest()[:20],
            # Reads and approvals do not replace the model-authored plan.
            version=plan_version,
            request=active[0].content[:4_000],
            status=model_status,
            steps=tuple(step.model_dump() for step in update.steps),
            model_status=model_status,
            explanation=update.explanation,
            blocking_reason=(update.explanation if model_status in {
                ResearchExecutionStatus.WAITING_FOR_CLARIFICATION,
                ResearchExecutionStatus.SCIENTIFIC_REFUSAL,
            } else None),
        )
        return plan.with_runtime_status(_research_plan_status(
            run_status=run_status, completion_reason=completion_reason,
            pending_approval=pending_approval is not None,
            model_status=model_status, error_code=error_code,
        ), error_code)

    def with_runtime_status(
        self, status: ResearchExecutionStatus, reason: str | None = None,
    ) -> "ResearchExecutionPlan":
        if status is self.status:
            return self
        return replace(
            # Runtime dispositions are derived views. Their version must stay
            # tied to the durable trajectory so approval and failure recovery
            # cannot recreate an older snapshot with a larger version.
            self, status=status,
            blocking_reason=(
                reason if status in {
                    ResearchExecutionStatus.TECHNICAL_FAILURE,
                    ResearchExecutionStatus.PERMISSION_DENIED,
                }
                else self.blocking_reason if status in {
                    ResearchExecutionStatus.WAITING_FOR_CLARIFICATION,
                    ResearchExecutionStatus.SCIENTIFIC_REFUSAL,
                }
                else None
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_version": self.version,
            "request": self.request,
            "status": self.status.value,
            "model_status": self.model_status.value,
            "explanation": self.explanation,
            "steps": [dict(step) for step in self.steps],
            "blocking_reason": self.blocking_reason,
        }


@dataclass(frozen=True)
class AgentRunLimits:
    # Production defaults keep a research request resumable even when the
    # deployment does not provide environment overrides. Tests and operators
    # can still opt out explicitly with None through the application config.
    # Keep one foreground request below the common browser/proxy patience
    # window. A continuation starts from the durable snapshot when more work
    # is needed, so a long study does not require one unbounded request.
    max_elapsed_seconds: float | None = 300.0
    max_tool_calls: int | None = 96
    max_model_tokens: int | None = 1_000_000
    max_consecutive_no_progress: int = 2
    emergency_max_model_cycles: int | None = 64
    max_model_retries: int = 5
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
    restored_elapsed_seconds: float = 0.0
    model_cycles: int = 0
    model_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    unreported_model_calls: int = 0
    retry_count: int = 0
    requested_tool_calls: int = 0
    executed_tool_calls: int = 0
    seen_observations: set[str] = field(default_factory=set)
    consecutive_no_progress: int = 0
    resource_refs: set[tuple[str, str]] = field(default_factory=set)
    working_summary: str = ""
    compacted_message_ids: set[str] = field(default_factory=set)
    read_batch_tokens: int = 12_000
    compaction_attempts: int = 0
    context_token_limit: int = 0
    context_recovery_attempts: int = 0
    complete_source_identities: set[tuple[str, str, str, str]] = field(default_factory=set)
    model_call_observer: ModelCallObserver | None = None
    model_call_session_id: str | None = None
    execution_plan: ResearchExecutionPlan | None = None
    plan_update_available: bool = True
    active_user_message_id: str | None = None

    def refresh_execution_plan(
        self,
        messages: list[ChatMessage],
    ) -> None:
        self.execution_plan = ResearchExecutionPlan.from_messages(messages=tuple(messages))

    def accept_plan_update(self, result: ChatToolResult) -> bool:
        """Allow one changed plan between observations without clearing a stall."""
        if result.status is not ToolResultStatus.SUCCEEDED or not self.plan_update_available:
            return False
        candidate_steps = tuple(dict(step) for step in result.data.get("steps", ()))
        if self.execution_plan is not None and (
            self.execution_plan.steps == candidate_steps
            and self.execution_plan.model_status.value == result.data["status"]
        ):
            return False
        self.plan_update_available = False
        return True

    def start_response(self) -> None:
        self.response_message_id = f"msg_{uuid4().hex[:16]}"
        self.response_created_at = _now_iso()
        if self.response_started_callback is not None:
            self.response_started_callback(self.response_message_id, self.response_created_at)

    def remaining_seconds(self) -> float:
        elapsed = self.restored_elapsed_seconds + max(0.0, monotonic() - self.started_at)
        if self.limits.max_elapsed_seconds is None:
            return float("inf")
        return max(0.0, self.limits.max_elapsed_seconds - elapsed)

    def restore_persisted_progress(self, payload: Mapping[str, Any] | None) -> None:
        """Continue one research request with its persisted runtime budget."""
        if not payload:
            return
        def number(name: str, default: float = 0.0) -> float:
            value = payload.get(name, default)
            return value if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isfinite(float(value))
            ) else default

        elapsed_ms = max(0.0, number("elapsed_ms"))
        self.started_at = monotonic()
        self.restored_elapsed_seconds = elapsed_ms / 1000.0
        for name in (
            "model_cycles", "model_tokens", "prompt_tokens", "completion_tokens",
            "unreported_model_calls", "retry_count", "context_token_limit", "context_recovery_attempts",
        ):
            setattr(self, name, max(0, int(number(name))))
        # A continuation is a new runtime slice.  A failed compaction must not
        # poison approval recovery or the explicit Continue action; the
        # current slice still has the durable trajectory and can compact it
        # again (or use the deterministic record fallback below).
        self.compaction_attempts = 0
        # Progress snapshots use the public trace field names, while the
        # runner keeps separate internal counter names. Restore the latter
        # explicitly so an approval continuation cannot regain spent budget.
        self.requested_tool_calls = max(
            0, int(number("requested_tool_count"))
        )
        self.executed_tool_calls = max(
            0, int(number("executed_tool_count"))
        )
        self.model_tokens = max(0, int(number("total_tokens", self.model_tokens)))
        checkpoint = payload.get("context_checkpoint")
        if isinstance(checkpoint, Mapping) and isinstance(checkpoint.get("working_summary"), str):
            self.working_summary = checkpoint["working_summary"]
            self.compacted_message_ids = {
                item for item in checkpoint.get("compacted_message_ids", ()) if isinstance(item, str)
            }

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
            # Pagination and the context-dependent token budget describe the
            # request, not new Source content in the returned batch.
            for key in ("offset", "page", "limit", "next_offset", "batch_token_budget"):
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
        if call.name == "propose_paper_experiment_draft" and data.get("draft_digest"):
            # IDs and timestamps distinguish stored drafts, not scientific progress.
            for key in ("draft_id", "draft_created_at"):
                data.pop(key, None)
        payload = {
            "tool": call.name,
            "status": result.status.value, "data": data,
            "resource_refs": sorted(
                (ref.resource_type, ref.resource_id, ref.href or "")
                for ref in result.resource_refs
                if not (call.name == "propose_paper_experiment_draft" and ref.resource_type == "paper_experiment_draft")
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
              new_resources: int = 0,
              termination_reason: str | None = None, final_answer: bool = False,
              run_status: AgentRunStatus | None = None,
              completion_reason: AgentCompletionReason | None = None,
              retry_attempt: int | None = None, retry_reason: str | None = None,
              http_status: int | None = None, retry_delay_ms: int | None = None) -> None:
        if self.execution_plan is not None and (run_status is not None or completion_reason is not None):
            self.execution_plan = self.execution_plan.with_runtime_status(
                _research_plan_status(
                    run_status=run_status,
                    completion_reason=completion_reason,
                    pending_approval=run_status is AgentRunStatus.APPROVAL_REQUIRED,
                    model_status=self.execution_plan.model_status,
                    error_code=termination_reason if run_status is AgentRunStatus.FAILED else None,
                ),
                termination_reason,
            )
        execution_plan_record = (
            self.execution_plan.to_record() if self.execution_plan is not None else None
        )
        log_payload = {
            "session_id": context.session_id, "request_id": get_request_id(), "phase": phase,
            "cycle_index": self.model_cycles, "selected_capability_names": capability_names,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "total_tokens": self.model_tokens, "unreported_model_calls": self.unreported_model_calls,
            "retry_count": self.retry_count,
            "requested_tool_count": self.requested_tool_calls,
            "executed_tool_count": self.executed_tool_calls,
            "new_resource_reference_count": new_resources,
            "observation_digest_changed": self.consecutive_no_progress == 0,
            "elapsed_ms": round((self.restored_elapsed_seconds + max(0.0, monotonic() - self.started_at)) * 1000),
            "model_cycles": self.model_cycles,
            "remaining_tool_budget": (max(0, self.limits.max_tool_calls - self.executed_tool_calls)
                                      if self.limits.max_tool_calls is not None else None),
            "remaining_token_budget": (max(0, self.limits.max_model_tokens - self.model_tokens)
                                       if self.limits.max_model_tokens is not None else None),
            "remaining_retry_budget": max(0, self.limits.max_model_retries - self.retry_count),
            "termination_reason": termination_reason, "final_answer_present": final_answer,
            "retry_attempt": retry_attempt, "retry_reason": retry_reason,
            "context_token_limit": self.context_token_limit,
            "context_recovery_attempts": self.context_recovery_attempts,
            "http_status": http_status, "retry_delay_ms": retry_delay_ms,
            "execution_plan": (
                {
                    "plan_id": self.execution_plan.plan_id,
                    "plan_version": self.execution_plan.version,
                    "status": self.execution_plan.status.value,
                    "model_status": self.execution_plan.model_status.value,
                    "step_count": len(self.execution_plan.steps),
                }
                if self.execution_plan is not None else None
            ),
        }
        logger.info("Research Agent cycle %s", json.dumps(log_payload, separators=(",", ":")))
        if self.progress_callback is not None:
            self.progress_callback({
                **log_payload, "execution_plan": execution_plan_record,
                "context_checkpoint": {
                    "working_summary": self.working_summary,
                    "compacted_message_ids": sorted(self.compacted_message_ids),
                    "user_message_id": self.active_user_message_id,
                },
            })


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
    execution_plan: Mapping[str, Any] | None = field(init=False)

    def __post_init__(self) -> None:
        if self.status is AgentRunStatus.COMPLETED:
            if self.completion_reason is None or self.error_code is not None:
                raise ValueError("completed run requires a reason and no error code")
        elif self.completion_reason is not None:
            raise ValueError("only completed runs have a completion reason")
        plan = ResearchExecutionPlan.from_messages(
            messages=self.messages,
            run_status=self.status,
            completion_reason=self.completion_reason,
            error_code=self.error_code,
            pending_approval=self.pending_approval,
        )
        object.__setattr__(self, "execution_plan", plan.to_record() if plan is not None else None)

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
        permission_mode: ToolPermissionMode | str = ToolPermissionMode.CONFIRM,
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        response_started_callback: Callable[[str, str], None] | None = None,
        model_call_observer: ModelCallObserver | None = None,
        context_checkpoint: Mapping[str, Any] | None = None,
    ) -> AgentRunResult:
        # Normalize the caller policy before creating any trajectory state. A
        # direct application caller must not leave a partial turn when it
        # supplies an unsupported mode; HTTP callers are already schema-bound.
        permission_mode = ToolPermissionMode(permission_mode)
        progress = _RunProgress(
            self.limits,
            progress_callback=progress_callback,
            response_started_callback=response_started_callback,
            model_call_observer=model_call_observer,
            model_call_session_id=context.session_id,
        )
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
        active_user_message_id = messages[-1].message_id
        progress.active_user_message_id = active_user_message_id
        if (
            context_checkpoint
            and context_checkpoint.get("user_message_id") == active_user_message_id
            and set(context_checkpoint.get("compacted_message_ids", ())).issubset(
                message.message_id for message in previous_messages
            )
        ):
            progress.restore_persisted_progress({"context_checkpoint": context_checkpoint})
        calls: list[ChatToolCall] = []
        results: list[ChatToolResult] = []
        progress.refresh_execution_plan(messages)
        await self._checkpoint(checkpoint, messages, calls, results)
        return await self._continue(
            context,
            messages,
            calls,
            results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
            permission_mode=permission_mode,
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
        model_call_observer: ModelCallObserver | None = None,
        continuation_progress: Mapping[str, Any] | None = None,
    ) -> AgentRunResult:
        progress = _RunProgress(
            self.limits,
            progress_callback=progress_callback,
            response_started_callback=response_started_callback,
            model_call_observer=model_call_observer,
            model_call_session_id=context.session_id,
        )
        progress.restore_persisted_progress(continuation_progress)
        requested_count, executed_count = self._active_turn_action_counts(previous_messages)
        progress.requested_tool_calls = max(progress.requested_tool_calls, requested_count)
        progress.executed_tool_calls = max(progress.executed_tool_calls, executed_count)
        claimed_call_was_persisted = any(
            request.tool_call_id == claimed_call.tool_call_id
            for message in previous_messages
            for request in message.tool_calls
        )
        if not claimed_call_was_persisted:
            progress.requested_tool_calls += 1
        capability_policy.validate_claimed_call(context, claimed_call)
        messages = list(previous_messages)
        progress.active_user_message_id = next(
            (message.message_id for message in reversed(messages)
             if message.role is ChatMessageRole.USER),
            None,
        )
        progress.refresh_execution_plan(messages)
        calls, results = self._reconstruct_active_trajectory(
            messages,
            exclude_tool_call_id=claimed_call.tool_call_id,
        )
        calls.append(claimed_call)
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
            if (
                not error
                and self.limits.max_tool_calls is not None
                and progress.executed_tool_calls >= self.limits.max_tool_calls
            ):
                error = (
                    "resource_budget",
                    "The approved research action exceeds the remaining tool budget.",
                )
            if not error:
                progress.executed_tool_calls += 1
            call, result = (
                self._failure(claimed_call, *error) if error
                else await self._execute_approved_call(
                    context,
                    claimed_call,
                    handler,
                    progress=progress,
                    arguments=validated_arguments.get(claimed_call.tool_call_id),
                )
            )
        calls[-1] = call
        results.append(result)
        messages.append(self._result_message(context, result))
        progress.refresh_execution_plan(messages)
        await self._checkpoint(checkpoint, messages, calls, results)
        return await self._continue(
            context,
            messages,
            calls,
            results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
            permission_mode=ToolPermissionMode.CONFIRM,
            progress=progress,
        )

    async def resume_after_tool_result(
        self,
        *,
        context: AgentContext,
        previous_messages: tuple[ChatMessage, ...],
        calls: tuple[ChatToolCall, ...],
        results: tuple[ChatToolResult, ...],
        tool_call: ChatToolCall,
        tool_result: ChatToolResult,
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        response_started_callback: Callable[[str, str], None] | None = None,
        model_call_observer: ModelCallObserver | None = None,
        continuation_progress: Mapping[str, Any] | None = None,
        permission_mode: ToolPermissionMode | str = ToolPermissionMode.CONFIRM,
    ) -> AgentRunResult:
        """Continue the same request after a non-executing tool decision."""
        progress = _RunProgress(
            self.limits,
            progress_callback=progress_callback,
            response_started_callback=response_started_callback,
            model_call_observer=model_call_observer,
            model_call_session_id=context.session_id,
        )
        progress.restore_persisted_progress(continuation_progress)
        messages = list(previous_messages)
        progress.active_user_message_id = next(
            (message.message_id for message in reversed(messages)
             if message.role is ChatMessageRole.USER),
            None,
        )
        requested_count, executed_count = self._active_turn_action_counts(previous_messages)
        progress.requested_tool_calls = max(progress.requested_tool_calls, requested_count)
        progress.executed_tool_calls = max(progress.executed_tool_calls, executed_count)
        next_calls = list(calls)
        next_results = list(results)
        if not any(call.tool_call_id == tool_call.tool_call_id for call in next_calls):
            next_calls.append(tool_call)
        if not any(item.tool_call_id == tool_result.tool_call_id for item in next_results):
            next_results.append(tool_result)
        messages.append(self._result_message(context, tool_result))
        progress.refresh_execution_plan(messages)
        await self._checkpoint(checkpoint, messages, next_calls, next_results)
        return await self._continue(
            context,
            messages,
            next_calls,
            next_results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
            permission_mode=ToolPermissionMode(permission_mode),
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
        permission_mode: ToolPermissionMode | str,
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
            non_streaming_retry = False
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
                        permission_mode=permission_mode,
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
                        "Research Agent capabilities selected step=%d max_steps=%s "
                        "tool_count=%d schema_chars=%d tools=%s",
                        progress.model_cycles + 1,
                        self.limits.emergency_max_model_cycles,
                        len(tool_specs),
                        schema_chars,
                        ",".join(tool_names) or "none",
                    )
                    decision_messages = tuple(messages)
                    stage_content = capability_policy.stage_instruction(
                        tool_names,
                        calls,
                        successful_results=capability_policy.active_successful_results_by_name(messages),
                        prior_experiment_draft=next(iter(reversed(
                            capability_policy._successful_results_by_name(messages).get("propose_paper_experiment_draft", ())
                        )), None),
                    )
                    if stage_content is not None:
                        decision_messages = (*decision_messages, ChatMessage.user(
                            message_id=self._message_id(),
                            session_id=context.session_id,
                            content=stage_content,
                            created_at=_now_iso(),
                        ))
                    if (
                        stage_content is None
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
                    turn = await self._model_turn(
                        decision_messages, tool_specs, progress,
                        None if non_streaming_retry else text_delta_callback,
                        active_user_message_id=next(
                            message.message_id for message in reversed(messages) if message.role is ChatMessageRole.USER
                        ),
                    )
                except ModelResponseError as exc:
                    if exc.reason == "model_allowance_exhausted":
                        return await self._finalize_with_current_evidence(
                            AgentCompletionReason.RESOURCE_BUDGET, progress, context, messages, calls, results,
                            checkpoint=checkpoint, text_delta_callback=text_delta_callback,
                        )
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
                        and progress.retry_count < self.limits.max_model_retries
                        and progress.remaining_seconds() > 0
                    ):
                        response_retries += 1
                        progress.retry_count += 1
                        if exc.reason in {"invalid_stream", "stream_tool_arguments_missing"}:
                            non_streaming_retry = True
                        delay = min(0.5 * 2 ** (response_retries - 1) * uniform(0.9, 1.1),
                                    progress.remaining_seconds())
                        progress.trace(
                            context,
                            phase="model_retry",
                            retry_attempt=response_retries,
                            retry_reason=exc.reason,
                            retry_delay_ms=round(delay * 1000),
                        )
                        logger.info(
                            "Retrying Research Agent model response model=%s "
                            "attempt=%d",
                            model_name,
                            response_retries + 1,
                        )
                        await sleep(delay)
                        continue
                    write_completion = await self._complete_after_successful_write_response_failure(
                        context,
                        messages,
                        calls,
                        results,
                        progress,
                        checkpoint=checkpoint,
                        phase="terminal",
                        technical_reason=exc.reason,
                    )
                    if write_completion is not None:
                        return write_completion
                    messages.append(
                        self._assistant(
                            context,
                            self._failure_answer(messages, calls, results),
                            progress,
                            messages=messages,
                            calls=calls,
                            results=results,
                        )
                    )
                    await self._checkpoint(checkpoint, messages, calls, results)
                    error_code = _permission_denial_code(results) or (
                        exc.reason if exc.reason.startswith(("research_", "context_"))
                        else "model_response_invalid"
                    )
                    progress.trace(context, phase="terminal", termination_reason=error_code,
                                   run_status=AgentRunStatus.FAILED)
                    return self._result(
                        AgentRunStatus.FAILED,
                        messages,
                        calls,
                        results,
                        error_code,
                    )
                except Exception as exc:  # noqa: BLE001
                    if progress.remaining_seconds() <= 0:
                        return await self._finalize_with_current_evidence(
                            AgentCompletionReason.RESOURCE_BUDGET, progress, context, messages, calls, results,
                            checkpoint=checkpoint, text_delta_callback=text_delta_callback,
                        )
                    model_name = str(
                        getattr(self.model, "model", None)
                        or type(self.model).__name__
                    )
                    failure = _provider_failure_details(exc)
                    logger.warning(
                        "Research Agent model call failed model=%s details=%s",
                        model_name, json.dumps(failure, separators=(",", ":")),
                    )
                    if (
                        failure["retryable"]
                        and progress.retry_count < self.limits.max_model_retries
                        and progress.remaining_seconds() > 0
                    ):
                        response_retries += 1
                        progress.retry_count += 1
                        # A provider can reject only the SSE transport while
                        # accepting the same request as a normal completion.
                        # Retry once without streaming before consuming the
                        # remaining provider budget.
                        non_streaming_retry = True
                        retry_after = failure.get("retry_after_seconds")
                        backoff = 0.5 * 2 ** (response_retries - 1) * uniform(0.9, 1.1)
                        delay = min(max(backoff, float(retry_after or 0.0)), progress.remaining_seconds())
                        progress.trace(
                            context,
                            phase="model_retry",
                            retry_attempt=response_retries,
                            retry_reason=failure["reason"], http_status=failure["http_status"],
                            retry_delay_ms=round(delay * 1000),
                        )
                        logger.info(
                            "Retrying Research Agent provider response model=%s "
                            "attempt=%d",
                            model_name,
                            response_retries + 1,
                        )
                        await sleep(delay)
                        continue
                    write_completion = await self._complete_after_successful_write_response_failure(
                        context,
                        messages,
                        calls,
                        results,
                        progress,
                        checkpoint=checkpoint,
                        phase="terminal",
                        technical_reason=failure["reason"],
                    )
                    if write_completion is not None:
                        return write_completion
                    provider_timeout = failure["reason"] == "provider_timeout"
                    messages.append(
                        self._assistant(
                            context,
                            self._failure_answer(messages, calls, results),
                            progress,
                            messages=messages,
                            calls=calls,
                            results=results,
                        )
                    )
                    await self._checkpoint(checkpoint, messages, calls, results)
                    progress.trace(
                        context,
                        phase="terminal",
                        run_status=AgentRunStatus.FAILED,
                        termination_reason=(
                            "provider_timeout" if provider_timeout else "model_unavailable"
                        ),
                        retry_reason=failure["reason"], http_status=failure["http_status"],
                    )
                    return self._result(
                        AgentRunStatus.FAILED,
                        messages,
                        calls,
                        results,
                        _permission_denial_code(results)
                        or ("provider_timeout" if provider_timeout else "model_unavailable"),
                    )
                break

            if not turn.tool_calls:
                progress.trace(context, phase="model", capability_names=tool_names)
                reason = progress.stop_before_model() or AgentCompletionReason.MODEL_ANSWER
                messages.append(
                    self._assistant(
                        context,
                        turn.content,
                        progress,
                        messages=messages,
                        calls=calls,
                        results=results,
                    )
                )
                await self._checkpoint(checkpoint, messages, calls, results)
                permission_error = _permission_denial_code(results)
                terminal_status = AgentRunStatus.FAILED if permission_error else AgentRunStatus.COMPLETED
                progress.trace(
                    context,
                    phase="terminal",
                    termination_reason=permission_error or reason.value,
                    final_answer=True,
                    run_status=terminal_status,
                    completion_reason=reason if terminal_status is AgentRunStatus.COMPLETED else None,
                )
                return self._result(
                    terminal_status, messages, calls, results,
                    error_code=permission_error,
                    completion_reason=reason if terminal_status is AgentRunStatus.COMPLETED else None,
                    warnings=(_INCOMPLETE_SCOPE_WARNING,) if reason is not AgentCompletionReason.MODEL_ANSWER else (),
                )

            requested = self._requested_calls(
                context,
                messages,
                turn,
                allowed_names=set(tool_names),
                progress=progress,
                completed_calls=calls,
                completed_results=results,
            )
            # A provider can repeat the exact write it just observed as
            # completed after an approval continuation.  The request ledger
            # filters that duplicate using the completed call's arguments. If
            # there is no new action left, close the turn from the saved result
            # instead of asking for a second approval.
            if turn.tool_calls and not requested:
                if turn.content:
                    await self._checkpoint(checkpoint, messages, calls, results)
                    progress.trace(
                        context,
                        phase="terminal",
                        termination_reason=AgentCompletionReason.MODEL_ANSWER.value,
                        final_answer=True,
                        run_status=AgentRunStatus.COMPLETED,
                        completion_reason=AgentCompletionReason.MODEL_ANSWER,
                    )
                    return self._result(
                        AgentRunStatus.COMPLETED,
                        messages,
                        calls,
                        results,
                        completion_reason=AgentCompletionReason.MODEL_ANSWER,
                    )
                return await self._finalize_with_current_evidence(
                    AgentCompletionReason.MODEL_ANSWER,
                    progress,
                    context,
                    messages,
                    calls,
                    results,
                    checkpoint=checkpoint,
                    text_delta_callback=text_delta_callback,
                )
            progress.requested_tool_calls += len(requested)
            progress.trace(context, phase="model", capability_names=tool_names)
            batch_start = len(calls)
            calls.extend(call for call, _ in requested)
            await self._checkpoint(checkpoint, messages, calls, results)
            stop_reason = progress.stop_before_model()
            budget_limited_batch = (
                self.limits.max_tool_calls is not None
                and progress.executed_tool_calls + len(requested) > self.limits.max_tool_calls
            )
            if budget_limited_batch:
                stop_reason = AgentCompletionReason.RESOURCE_BUDGET
            independent_reads = bool(requested) and all(
                call.risk is ToolRisk.READ for call, _ in requested
            )
            completed_by_id: dict[str, tuple[ChatToolCall, ChatToolResult]] = {}
            runnable = list(requested)
            validated_arguments: dict[str, BaseModel] = {}
            error: tuple[str, str] | None = None

            can_execute_partial_read_batch = (
                independent_reads
                and (
                    stop_reason is None
                    or (budget_limited_batch and stop_reason is AgentCompletionReason.RESOURCE_BUDGET)
                )
            )
            if can_execute_partial_read_batch:
                # Validate each read independently. A malformed request should
                # become its own observation while valid reads continue.
                runnable = []
                for call, handler in requested:
                    call_error, call_arguments = capability_policy.validate_batch(
                        self.capabilities,
                        ((call, handler),),
                        messages,
                        permission_mode=permission_mode,
                    )
                    if call_error:
                        completed_by_id[call.tool_call_id] = self._failure(call, *call_error)
                    else:
                        runnable.append((call, handler))
                        validated_arguments.update(call_arguments)
            elif stop_reason:
                error = (
                    "resource_budget",
                    "These Sources or actions remain uninspected or unexecuted in this turn.",
                )
                validated_arguments = {}
            else:
                error, validated_arguments = capability_policy.validate_batch(
                    self.capabilities,
                    requested,
                    messages,
                    permission_mode=permission_mode,
                )

            # Validate the requested capability first so specific contract
            # failures (for example an explicitly deferred Finding or an
            # uninspected research-plan parent) remain actionable. The plan
            # gate applies only when the capability call itself is valid.
            if (
                error is None
                and progress.execution_plan is None
                and self._requires_execution_plan(calls[:batch_start], requested)
            ):
                error = (
                    "execution_plan_required",
                    "Submit an execution plan before saving the result of this multi-step research request.",
                )

            if error:
                completed = tuple(self._failure(call, *error) for call, _ in requested)
            elif can_execute_partial_read_batch:
                if self.limits.max_tool_calls is not None:
                    remaining = max(0, self.limits.max_tool_calls - progress.executed_tool_calls)
                    runnable, deferred = runnable[:remaining], runnable[remaining:]
                else:
                    deferred = []
                for call, _handler in deferred:
                    completed_by_id[call.tool_call_id] = self._failure(
                        call,
                        "resource_budget",
                        "This read was deferred because the remaining tool budget could not execute the full batch.",
                    )
                started = []
                for call, handler in runnable:
                    started_call = call.start(_now_iso())
                    calls[batch_start + next(
                        index for index, (requested_call, _) in enumerate(requested)
                        if requested_call.tool_call_id == call.tool_call_id
                    )] = started_call
                    started.append((started_call, handler))
                if started:
                    await self._checkpoint(checkpoint, messages, calls, results)
                    progress.executed_tool_calls += len(started)
                    executed = await self._execute_read_batch(
                        context,
                        tuple(started),
                        progress,
                        validated_arguments=validated_arguments,
                    )
                    completed_by_id.update({call.tool_call_id: (call, result) for call, result in executed})
                completed = tuple(
                    completed_by_id[call.tool_call_id]
                    for call, _handler in requested
                )
            elif len(requested) == 1 and capability_policy.evaluate_authorization(requested[0][0].risk).requires_approval:
                pending = requested[0][0].require_approval()
                calls[-1] = pending
                progress.refresh_execution_plan(messages)
                await self._checkpoint(checkpoint, messages, calls, results)
                progress.trace(context, phase="terminal", termination_reason="approval_required",
                               run_status=AgentRunStatus.APPROVAL_REQUIRED)
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
            plan_update_accepted = False
            for index, (call, capability_result) in enumerate(completed):
                calls[batch_start + index] = call
                if capability_result.status is ToolResultStatus.SUCCEEDED and call.name in {
                    "read_source", "inspect_table", "inspect_document_sources",
                }:
                    coverage = progress.source_coverage(call, capability_result)
                    capability_result = replace(capability_result, data={
                        **dict(capability_result.data), "source_coverage": coverage,
                    })
                results.append(capability_result)
                messages.append(self._result_message(context, capability_result))
                if call.name == "update_execution_plan":
                    plan_update_accepted = progress.accept_plan_update(capability_result) or plan_update_accepted
                else:
                    progress_increased = progress.observe(call, capability_result) or progress_increased
            progress.refresh_execution_plan(messages)
            if progress_increased:
                progress.consecutive_no_progress = 0
                progress.plan_update_available = True
            elif not plan_update_accepted:
                progress.consecutive_no_progress = prior_no_progress + 1
            await self._checkpoint(checkpoint, messages, calls, results)
            progress.trace(context, phase="tools", capability_names=tool_names,
                           new_resources=len(progress.resource_refs) - old_resource_count,
                           completion_reason=stop_reason,
                           termination_reason=stop_reason.value if stop_reason else None)
            if stop_reason:
                return await self._finalize_with_current_evidence(
                    stop_reason, progress, context, messages, calls, results,
                    checkpoint=checkpoint, text_delta_callback=text_delta_callback,
                )

    async def _model_turn(
        self, messages: tuple[ChatMessage, ...], tool_specs: tuple[ToolSpec, ...],
        progress: _RunProgress, text_delta_callback: Callable[[str], None] | None,
        *, active_user_message_id: str, finalizing: bool = False,
    ) -> ModelTurn:
        """Build and send one decision, shrinking only rejected context without replaying tools."""
        rejected: tuple[int, ModelResponseError] | None = None
        while True:
            model_context = await self._prepare_model_context(
                messages, tool_specs, progress, active_user_message_id=active_user_message_id,
            )
            request_tokens = self.context_builder.estimate_tokens({
                "messages": model_context.provider_messages(RESEARCH_AGENT_SYSTEM_PROMPT),
                "tools": [spec.model_schema() for spec in tool_specs],
            })
            # A smaller configured window is not enough: the actual payload must shrink.
            if rejected is not None and request_tokens >= rejected[0]:
                raise rejected[1]
            try:
                return await self._respond(model_context, tool_specs, progress, text_delta_callback,
                                           finalizing=finalizing)
            except ModelResponseError as exc:
                if (exc.reason != "context_window_exceeded" or exc.partial_content
                        or progress.context_recovery_attempts >= _MAX_CONTEXT_RECOVERIES
                        or progress.retry_count >= self.limits.max_model_retries
                        or progress.remaining_seconds() <= 0
                        or (not finalizing and progress.stop_before_model() is not None)):
                    raise
                previous_limit = self._effective_context_tokens(progress)
                reduced_limit = int(previous_limit * _CONTEXT_SHRINK_RATIO)
                if reduced_limit <= self.limits.max_model_output_tokens + 2048:
                    raise
                progress.context_token_limit = reduced_limit
                progress.context_recovery_attempts += 1
                progress.retry_count += 1
                rejected = request_tokens, exc
                logger.info(
                    "Research context recovery attempt=%d previous_limit=%d context_limit=%d rejected_input_tokens=%d",
                    progress.context_recovery_attempts, previous_limit, reduced_limit, request_tokens,
                )
                progress.trace(AgentContext(messages[0].session_id, "", ""), phase="context_recovery",
                               retry_attempt=progress.context_recovery_attempts, retry_reason=exc.reason)

    async def _respond(
        self,
        model_context: ChatModelContext,
        tool_specs: tuple[ToolSpec, ...],
        progress: _RunProgress,
        text_delta_callback: Callable[[str], None] | None,
        *,
        finalizing: bool = False,
    ) -> ModelTurn:
        timeout = min(progress.remaining_seconds(), self.limits.max_request_seconds)
        output_limit = self.limits.max_model_output_tokens
        if self.limits.max_model_tokens is not None:
            output_limit = min(output_limit, self.limits.max_model_tokens - progress.model_tokens)
        if finalizing:
            timeout = min(timeout, self.limits.max_finalization_seconds)
            output_limit = self.limits.max_finalization_output_tokens
        if output_limit <= 0:
            raise ModelResponseError("The configured model allowance is exhausted.",
                                     reason="model_allowance_exhausted", retryable=False)
        if model_context.compacting:
            output_limit = min(output_limit, 8192)
        if timeout <= 0:
            raise TimeoutError("research turn deadline reached")
        purpose = "compaction" if model_context.compacting else (
            "finalization" if finalizing else "decision"
        )
        model_context = replace(
            model_context,
            max_context_tokens=self._effective_context_tokens(progress),
            model_call_observer=progress.model_call_observer,
            model_call_purpose=purpose,
            model_call_response_message_id=(
                None if purpose == "compaction" else progress.response_message_id
            ),
            model_call_session_id=progress.model_call_session_id,
        )
        prompt = RESEARCH_COMPACTION_SYSTEM_PROMPT if model_context.compacting else RESEARCH_AGENT_SYSTEM_PROMPT
        request_tokens = self.context_builder.estimate_tokens({
            "messages": model_context.provider_messages(prompt),
            "tools": [spec.model_schema() for spec in tool_specs],
        })
        if not model_context.compacting:
            progress.read_batch_tokens = max(1024, min(16_000,
                model_context.max_context_tokens - request_tokens - output_limit - 4096))
        arguments: dict[str, Any] = {
            "context": model_context,
            "tool_specs": tool_specs,
            "timeout_seconds": timeout,
            "max_output_tokens": output_limit,
        }
        if text_delta_callback is not None:
            # A response rejected for skipping a required read must not appear
            # in the browser as a completed research answer.
            arguments["text_delta_callback"] = (
                (lambda _delta: None) if model_context.require_tool_call else text_delta_callback
            )
        progress.model_cycles += 1
        visible_content = False
        if "text_delta_callback" in arguments:
            callback = arguments["text_delta_callback"]
            def observe_delta(delta: str) -> None:
                nonlocal visible_content
                visible_content = visible_content or bool(delta)
                callback(delta)
            arguments["text_delta_callback"] = observe_delta
        try:
            turn = await wait_for(self.model.respond(**arguments), timeout=timeout)
        except ModelResponseError as exc:
            progress.record_model_usage(exc.usage)
            exc.partial_content = exc.partial_content or visible_content
            raise
        except BaseException as exc:
            # Cancellation may prevent the provider's usage trailer from arriving.
            progress.record_model_usage(None)
            if isinstance(exc, Exception) and visible_content:
                raise ModelResponseError("The model stream was interrupted after visible content.",
                                         reason="interrupted_stream", partial_content=True, retryable=False) from exc
            raise
        progress.record_model_usage(turn.usage)
        if model_context.require_tool_call and turn.tool_calls:
            turn = replace(turn, content="")
        return turn

    async def _prepare_model_context(
        self, messages: tuple[ChatMessage, ...], tool_specs: tuple[ToolSpec, ...],
        progress: _RunProgress, *, active_user_message_id: str,
    ) -> ChatModelContext:
        """Compact old operations into provisional notes; the durable trajectory stays intact."""
        execution_plan = progress.execution_plan.to_record() if progress.execution_plan else None
        context_limit = self._effective_context_tokens(progress)
        input_budget = self.context_builder.input_budget(
            context_limit=context_limit, output_limit=self.limits.max_model_output_tokens,
            system_prompt=RESEARCH_AGENT_SYSTEM_PROMPT,
            tool_schemas=[spec.model_schema() for spec in tool_specs], execution_plan=execution_plan,
        )
        prior_reading = self._prior_source_reading(
            messages, active_user_message_id=active_user_message_id,
            max_tokens=min(4500, max(256, input_budget // 8)),
        )
        if prior_reading:
            input_budget -= self.context_builder.estimate_tokens(prior_reading) + 200
        if progress.working_summary:
            progress.working_summary = self._bounded_working_notes(
                ResearchWorkingNotesModelOutput.model_validate_json(progress.working_summary),
                max_tokens=min(6000, input_budget // 3),
            ).model_dump_json()
        active = next(message for message in messages if message.message_id == active_user_message_id)
        while True:
            available = tuple(message for message in messages
                              if message.message_id not in progress.compacted_message_ids)
            try:
                view = self.context_builder.for_model(
                    available, active_user_message_id=active_user_message_id,
                    max_input_tokens=input_budget, working_summary=progress.working_summary,
                )
            except ValueError as exc:
                raise ModelResponseError("Pinned research context exceeds the context window.",
                                         reason="context_window_exceeded", retryable=False) from exc
            retained = {message.message_id for message in view.messages}
            units = [unit for unit in self.context_builder._protocol_units(available)
                     if unit[0].message_id not in retained]
            if not units:
                return replace(view, max_context_tokens=context_limit,
                               prior_reading_summary=prior_reading, execution_plan=execution_plan)
            if progress.compaction_attempts >= 3:
                raise ModelResponseError("Research context could not be compacted without repeated retries.",
                                         reason="context_compaction_unavailable", retryable=False)
            notes_budget = min(6000, input_budget // 3)
            if (
                len(units) > _MAX_MODEL_COMPACTION_UNITS
                or bool(progress.compacted_message_ids)
                or progress.remaining_seconds() <= _MIN_REMAINING_SECONDS_FOR_MODEL_COMPACTION
            ):
                batch = [message for unit in units for message in unit]
                summary = self._fallback_working_notes(
                    active, batch, max_tokens=notes_budget, working_summary=progress.working_summary,
                ).model_dump_json()
            else:
                try:
                    batch = self.context_builder.compaction_batch(
                        active, units, context_limit=context_limit,
                        system_prompt=RESEARCH_COMPACTION_SYSTEM_PROMPT,
                        working_summary=progress.working_summary, execution_plan=execution_plan,
                    )
                except ValueError as exc:
                    raise ModelResponseError(str(exc), reason="context_window_exceeded", retryable=False) from exc
                summary = await self._compact_working_notes(
                    active, batch, progress, notes_budget=notes_budget, execution_plan=execution_plan,
                )
            # Publish notes and retired IDs together, only after building the replacement.
            progress.working_summary = summary
            progress.compacted_message_ids.update(message.message_id for message in batch)
            progress.compaction_attempts = 0
            progress.trace(AgentContext(active.session_id, "", ""), phase="context_compaction")

    async def _compact_working_notes(
        self, active: ChatMessage, batch: list[ChatMessage], progress: _RunProgress,
        *, notes_budget: int, execution_plan: Mapping[str, Any] | None,
    ) -> str:
        progress.trace(AgentContext(active.session_id, "", ""), phase="context_compaction")
        compaction_messages = (active, *batch)
        progress.compaction_attempts += 1
        summary = None
        try:
            compacted = await self._respond(
                ChatModelContext(compaction_messages, compacting=True, working_summary=progress.working_summary,
                                 execution_plan=execution_plan,
                                 active_user_message_id=active.message_id),
                (), progress, None,
            )
            if compacted.tool_calls:
                raise ValueError("compaction cannot request tools")
            notes = ResearchWorkingNotesModelOutput.model_validate_json(extract_json_object(compacted.content))
            allowed_ids = progress.compacted_message_ids | {message.message_id for message in (active, *batch)}
            if any(set(check.basis_message_ids) - allowed_ids for check in notes.checks):
                raise ValueError("working note cites an unobserved message")
            if progress.working_summary:
                previous = ResearchWorkingNotesModelOutput.model_validate_json(progress.working_summary)
                covered = {identity for check in notes.checks for identity in check.basis_message_ids}
                retained = [check for check in previous.checks if not set(check.basis_message_ids) <= covered]
                if retained:
                    combined = [*retained, *notes.checks]
                    if len(combined) > 16:
                        combined = [*retained[:8], *notes.checks[-8:]]
                        notes.next_actions = [_WORKING_NOTES_LOSS_NOTICE, *notes.next_actions[:7]]
                    notes.checks = combined
            summary = self._bounded_working_notes(
                notes, max_tokens=notes_budget,
            ).model_dump_json()
        except (ModelResponseError, ValueError) as exc:
            if isinstance(exc, ModelResponseError) and exc.reason not in {
                "context_window_exceeded", "output_token_limit", "empty_response",
                "invalid_response_shape", "reasoning_only_response", "invalid_stream",
            }:
                raise
            # Working notes are runtime memory, not scientific evidence.
            # If the provider cannot produce the optional JSON, retain a
            # bounded, message-ID-backed record instead of turning a
            # formatting/provider issue into a terminal research failure.
            logger.warning(
                "Research context compaction fell back to archived records reason=%s",
                getattr(exc, "reason", type(exc).__name__),
            )
            summary = self._fallback_working_notes(
                active, batch, max_tokens=notes_budget, working_summary=progress.working_summary,
            ).model_dump_json()
        return summary

    def _effective_context_tokens(self, progress: _RunProgress | None = None) -> int:
        configured = max(1_024, self.limits.max_context_tokens - _CONTEXT_SAFETY_MARGIN_TOKENS)
        return min(configured, progress.context_token_limit) if progress and progress.context_token_limit else configured

    def _prior_source_reading(
        self, messages: tuple[ChatMessage, ...] | list[ChatMessage], *,
        active_user_message_id: str, max_tokens: int,
    ) -> str:
        """Retain bounded reading facts across turns without granting current write authority."""
        active_index = next(index for index, message in enumerate(messages)
                            if message.message_id == active_user_message_id)
        prior = messages[:active_index]
        names = {call.tool_call_id: call.name for message in prior for call in message.tool_calls}
        results: dict[str, list[Mapping[str, Any]]] = {}
        sources = []
        for message in prior:
            result = message.tool_result
            name = names.get(message.tool_call_id)
            if (result is None or result.status is not ToolResultStatus.SUCCEEDED
                    or name not in {"read_source", "inspect_table", "inspect_document_sources"}):
                continue
            results.setdefault(name, []).append(result.data)
            if name == "inspect_document_sources":
                document_id = str(result.data.get("document", {}).get("document_id") or "")
                sources.extend({**source, "document_id": document_id} for source in result.data.get("sources", ())
                               if isinstance(source, Mapping))
            elif name == "inspect_table":
                sources.append({**result.data, "source_kind": "table", "source_ref": result.data.get("table_ref")})
            else:
                sources.append(result.data)
        completed = capability_policy.complete_source_reads(results)
        if not completed:
            return ""
        documents: dict[str, dict[tuple[str, ...], dict[str, Any]]] = {}
        for source in reversed(sources):
            identity = tuple(str(source.get(key) or "") for key in
                             ("document_id", "source_kind", "source_ref", "source_digest"))
            if identity not in completed:
                continue
            record = {key: source[key] for key in ("source_label", "source_kind", "source_ref", "source_digest", "page", "heading_path", "content_offset")
                      if isinstance(source.get(key), (str, int))}
            content = source.get("content")
            if isinstance(content, str) and content:
                record.update(excerpt=content[:1600], excerpt_truncated=len(content) > 1600)
            documents.setdefault(identity[0], {}).setdefault(identity, record)
        payload: dict[str, Any] = {"papers": [], "omitted_paper_count": len(documents)}

        def fits() -> bool:
            return self.context_builder.estimate_tokens(payload) <= max_tokens

        queues = []
        for document_id, records in documents.items():
            paper = {"document_id": document_id, "complete_source_count": len(records),
                     "sources": [], "omitted_source_count": len(records)}
            payload["papers"].append(paper)
            payload["omitted_paper_count"] -= 1
            if not fits():
                payload["papers"].pop()
                payload["omitted_paper_count"] += 1
                break
            # Recent metadata tails must not displace the longer passages already read.
            queues.append((paper, sorted(records.values(),
                                        key=lambda record: len(record.get("excerpt", "")), reverse=True)))
        # Allocate excerpts across papers before adding more passages from one paper.
        for index in range(max((len(records) for _, records in queues), default=0)):
            for paper, records in queues:
                if index >= len(records):
                    continue
                record = dict(records[index])
                paper["sources"].append(record)
                paper["omitted_source_count"] -= 1
                if not fits():
                    record.pop("excerpt", None)
                    record.pop("excerpt_truncated", None)
                if not fits():
                    paper["sources"].pop()
                    paper["omitted_source_count"] += 1
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _bounded_working_notes(
        self, notes: ResearchWorkingNotesModelOutput, *, max_tokens: int,
    ) -> ResearchWorkingNotesModelOutput:
        """Keep validated navigation notes within their reserved context space."""
        candidate = notes.model_copy(deep=True)
        if self.context_builder.estimate_tokens(candidate.model_dump_json()) <= max_tokens:
            return candidate
        candidate.next_actions = [
            _WORKING_NOTES_LOSS_NOTICE,
            *[action for action in candidate.next_actions if action != _WORKING_NOTES_LOSS_NOTICE][:7],
        ]
        # Retain early context and the latest observation while removing middle records.
        while self.context_builder.estimate_tokens(candidate.model_dump_json()) > max_tokens:
            if candidate.checks:
                candidate.checks.pop(len(candidate.checks) // 2)
            elif len(candidate.next_actions) > 1:
                candidate.next_actions.pop()
            elif len(candidate.scope) > 80:
                candidate.scope = candidate.scope[:len(candidate.scope) // 2] + " [truncated]"
            else:
                raise ModelResponseError("Working notes cannot fit the context budget.",
                                         reason="context_window_exceeded", retryable=False)
        return candidate

    def _fallback_working_notes(
        self, active: ChatMessage, batch: list[ChatMessage], *, max_tokens: int,
        working_summary: str = "",
    ) -> ResearchWorkingNotesModelOutput:
        """Merge existing notes with explicitly lossy excerpts, without inferring evidence."""
        previous = (ResearchWorkingNotesModelOutput.model_validate_json(working_summary)
                    if working_summary else None)
        checks: list[ResearchWorkingCheckModelOutput] = []
        # Prefer recent results over call envelopes; their IDs retain the source of each excerpt.
        for message in reversed(batch):
            if message.tool_result is not None:
                record = json.dumps(message.tool_result.data, ensure_ascii=False,
                                    separators=(",", ":"), default=str)
                excerpt = record[:480] + (" [truncated]" if len(record) > 480 else "")
                statement = f"Archived tool result {message.tool_result.tool_call_id}: {excerpt}"
            elif message.role is ChatMessageRole.USER:
                statement = "Earlier researcher request: " + message.content[:480]
            else:
                continue
            checks.append(ResearchWorkingCheckModelOutput(
                statement=statement[:1200],
                conditions="Raw runtime record; this is not a scientific conclusion or authorization.",
                basis_message_ids=[message.message_id],
                unresolved="Verify missing details against the canonical Source before relying on this excerpt.",
            ))
            if len(checks) == 8:
                break
        checks.reverse()
        prior_checks = sorted(previous.checks, key=lambda check: not bool(check.unresolved)) if previous else []
        actions = [action for action in previous.next_actions if action != _WORKING_NOTES_LOSS_NOTICE] if previous else []
        return self._bounded_working_notes(
            ResearchWorkingNotesModelOutput(
                scope=previous.scope if previous else (active.content[:1000] or "Continue the current research request."),
                checks=[*prior_checks[:8], *checks],
                next_actions=[_WORKING_NOTES_LOSS_NOTICE, *actions[:7]],
            ),
            max_tokens=max_tokens,
        )

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
            if progress.remaining_seconds() <= 0:
                raise TimeoutError("research turn deadline reached")
            turn = await self._model_turn(
                (*messages, instruction), (), progress, text_delta_callback, finalizing=True,
                active_user_message_id=next(
                    message.message_id for message in reversed(messages) if message.role is ChatMessageRole.USER
                ),
            )
            if turn.tool_calls or not turn.content:
                raise ValueError("final answer must be answer-only")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Research Agent final answer failed exception_type=%s",
                type(exc).__name__,
            )
            if progress.remaining_seconds() > 0:
                write_completion = await self._complete_after_successful_write_response_failure(
                    context, messages, calls, results, progress, checkpoint=checkpoint,
                    phase="finalize", technical_reason="final_answer_unavailable",
                )
                if write_completion is not None:
                    return write_completion
            messages.append(
                self._assistant(
                    context,
                    self._failure_answer(
                        messages,
                        calls,
                        results,
                        resource_limited=reason in {
                            AgentCompletionReason.RESOURCE_BUDGET,
                            AgentCompletionReason.EMERGENCY_CEILING,
                        },
                    ),
                    progress,
                    messages=messages,
                    calls=calls,
                    results=results,
                )
            )
            permission_error = _permission_denial_code(results)
            deadline_reached = progress.remaining_seconds() <= 0
            progress.trace(
                context, phase="finalize",
                termination_reason=permission_error or (reason.value if deadline_reached else "final_answer_unavailable"),
                run_status=AgentRunStatus.FAILED if permission_error or not deadline_reached else AgentRunStatus.COMPLETED,
                completion_reason=reason if not permission_error and deadline_reached else None,
            )
            await self._checkpoint(checkpoint, messages, calls, results)
            if permission_error or not deadline_reached:
                return self._result(
                    AgentRunStatus.FAILED,
                    messages,
                    calls,
                    results,
                    permission_error or "final_answer_unavailable",
                )
            return self._result(
                AgentRunStatus.COMPLETED, messages, calls, results,
                completion_reason=reason, warnings=(_INCOMPLETE_SCOPE_WARNING,),
            )
        messages.append(
            self._assistant(
                context,
                turn.content,
                progress,
                messages=messages,
                calls=calls,
                results=results,
            )
        )
        permission_error = _permission_denial_code(results)
        terminal_status = AgentRunStatus.FAILED if permission_error else AgentRunStatus.COMPLETED
        progress.trace(
            context,
            phase="finalize",
            termination_reason=permission_error or reason.value,
            final_answer=True,
            run_status=terminal_status,
            completion_reason=reason if terminal_status is AgentRunStatus.COMPLETED else None,
        )
        await self._checkpoint(checkpoint, messages, calls, results)
        return self._result(
            terminal_status, messages, calls, results,
            error_code=permission_error,
            completion_reason=reason if terminal_status is AgentRunStatus.COMPLETED else None,
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
        prior_reading = self._prior_source_reading(
            messages, active_user_message_id=messages[last_user].message_id, max_tokens=1500,
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
            ) if structured_deliverable is not None else (
                "Reading stopped because repeated operations made no new progress. "
                "The requested research work remains incomplete. Report completed "
                "observations and unfinished checks without claiming the deliverable "
                "is complete or a resource budget was exhausted. Do not request another tool."
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
                "content or authorize a new experiment or Finding write."
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
        completed_calls: tuple[ChatToolCall, ...] | list[ChatToolCall] = (),
        completed_results: tuple[ChatToolResult, ...] | list[ChatToolResult] = (),
    ) -> tuple[tuple[ChatToolCall, Any], ...]:
        assistant_message_id = progress.response_message_id
        requested = []
        seen_requests: set[tuple[str, str]] = set()
        completed_write_requests = self._completed_write_request_keys(
            messages,
            calls=completed_calls,
            results=completed_results,
        )
        for model_call in turn.tool_calls:
            arguments = dict(model_call.arguments)
            if model_call.name == "curate_finding":
                arguments = self._complete_curation_shape(arguments, messages)
            if model_call.name == "create_finding_draft":
                # Structural cleanup is deterministic; scientific classifications
                # must remain the model's explicit decision or a validation error.
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
            if (model_call.name, request_key[1]) in completed_write_requests:
                logger.info(
                    "Research Agent skipped duplicate completed write tool=%s",
                    model_call.name,
                )
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
                assistant_message_id=assistant_message_id, position=len(requested),
                name=model_call.name, arguments=arguments,
                risk=registered.spec.risk if registered else ToolRisk.UNKNOWN,
            )
            requested.append((call, registered if model_call.name in allowed_names else None))
        if requested or turn.content:
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

    def _completed_write_request_keys(
        self,
        messages: list[ChatMessage],
        *,
        calls: tuple[ChatToolCall, ...] | list[ChatToolCall] = (),
        results: tuple[ChatToolResult, ...] | list[ChatToolResult] = (),
    ) -> set[tuple[str, str]]:
        """Return completed write identities for the active user request.

        The identity is the capability name plus its canonical argument JSON.
        Previous user requests are excluded so a later explicit save can still
        create a new version. Approval continuations also pass their in-memory
        call/result ledger because the durable trajectory can briefly contain a
        tool result without the assistant request that produced it. This is
        runtime idempotency, not language intent classification.
        """
        last_user_index = max(
            (
                index
                for index, message in enumerate(messages)
                if message.role is ChatMessageRole.USER
            ),
            default=-1,
        )
        active = messages[last_user_index:]
        requests = {
            request.tool_call_id: request
            for message in active
            if message.role is ChatMessageRole.ASSISTANT
            for request in message.tool_calls
        }
        completed: set[tuple[str, str]] = set()
        for message in active:
            result = message.tool_result
            request = requests.get(message.tool_call_id)
            if (
                result is None
                or result.status is not ToolResultStatus.SUCCEEDED
                or request is None
            ):
                continue
            handler = self.capabilities.get(request.name)
            if handler is None or handler.spec.risk is not ToolRisk.WRITE:
                continue
            completed.add(
                (
                    request.name,
                    json.dumps(
                        request.arguments,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ),
                )
            )
        call_by_id = {call.tool_call_id: call for call in calls}
        for result in results:
            if result.status is not ToolResultStatus.SUCCEEDED:
                continue
            call = call_by_id.get(result.tool_call_id)
            if call is None or call.risk is not ToolRisk.WRITE:
                continue
            completed.add(
                (
                    call.name,
                    json.dumps(
                        call.arguments,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ),
                )
            )
        return completed

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
                        timeout=min(progress.remaining_seconds(), self.limits.max_request_seconds),
                    )
                except TimeoutError:
                    return self._failure(call, "capability_timeout", "The Source or action could not be completed in this turn.")

        if all(handler.spec.parallel_safe for _, handler in requested):
            return tuple(await gather(*(bounded(call, handler) for call, handler in requested)))
        return tuple([await bounded(call, handler) for call, handler in requested])


    @staticmethod
    def _active_turn_action_counts(
        messages: tuple[ChatMessage, ...] | list[ChatMessage],
    ) -> tuple[int, int]:
        last_user_index = max(
            (
                index
                for index, message in enumerate(messages)
                if message.role is ChatMessageRole.USER
            ),
            default=len(messages),
        )
        active = messages[last_user_index:]
        requested_ids = {
            request.tool_call_id
            for message in active
            for request in message.tool_calls
        }
        completed_ids = {
            message.tool_result.tool_call_id
            for message in active
            if message.tool_result is not None
        }
        return len(requested_ids), len(requested_ids & completed_ids)

    def _requires_execution_plan(
        self,
        calls: list[ChatToolCall],
        requested: tuple[tuple[ChatToolCall, Any], ...],
    ) -> bool:
        """Require a model plan before a multi-stage write reaches approval.

        A direct save is one atomic user action and remains eligible for the
        normal exact approval flow. Once the same request has already taken a
        research action, a later write is a multi-stage deliverable: the model
        must make that remaining work observable before it can be approved.
        Control capabilities themselves are excluded through the registry so
        discovery and plan updates do not count as scientific actions.
        """
        if len(requested) != 1 or requested[0][0].risk is not ToolRisk.WRITE:
            return False
        control_names = {
            self.capabilities.discovery.spec.name,
            self.capabilities.execution_plan.spec.name,
        }
        prior_actions = [
            call for call in calls
            if call.name not in control_names
            and call.risk in {ToolRisk.READ, ToolRisk.DRAFT, ToolRisk.WRITE}
        ]
        return bool(prior_actions)

    def _reconstruct_active_trajectory(
        self,
        messages: tuple[ChatMessage, ...] | list[ChatMessage],
        *,
        exclude_tool_call_id: str | None = None,
    ) -> tuple[list[ChatToolCall], list[ChatToolResult]]:
        """Restore the current request's calls and results before approval resume.

        The persisted chat messages carry tool requests and results. Approval
        metadata is copied into each request while loading the durable call, so
        every historical write keeps its own decision identity during a later
        approval continuation.
        """
        last_user_index = max(
            (
                index
                for index, message in enumerate(messages)
                if message.role is ChatMessageRole.USER
            ),
            default=0,
        )
        active = messages[last_user_index:]
        result_events = {
            message.tool_call_id: (message.tool_result, message.created_at)
            for message in active
            if message.tool_result is not None and message.tool_call_id
        }
        calls: list[ChatToolCall] = []
        seen_ids: set[str] = set()
        for message in active:
            if message.role is not ChatMessageRole.ASSISTANT:
                continue
            for request in message.tool_calls:
                if request.tool_call_id == exclude_tool_call_id or request.tool_call_id in seen_ids:
                    continue
                seen_ids.add(request.tool_call_id)
                handler = self.capabilities.get(request.name)
                risk = handler.spec.risk if handler is not None else ToolRisk.UNKNOWN
                call = ChatToolCall.requested(
                    tool_call_id=request.tool_call_id,
                    session_id=message.session_id,
                    assistant_message_id=message.message_id,
                    name=request.name,
                    arguments=request.arguments,
                    risk=risk,
                    position=request.position,
                )
                event = result_events.get(request.tool_call_id)
                if event is not None:
                    result, finished_at = event
                    if result.status is ToolResultStatus.FAILED:
                        call = call.fail(result.error_code or "capability_failed", finished_at)
                    else:
                        if risk is ToolRisk.WRITE:
                            if not all((
                                request.decision_user_id,
                                request.decision_arguments_digest,
                                request.decided_at,
                            )):
                                # A legacy or malformed trajectory cannot be
                                # safely reconstructed as an executed write.
                                # Keep the durable result row intact and leave
                                # this call out of the in-memory write ledger.
                                continue
                            call = replace(
                                call,
                                status=ToolCallStatus.APPROVED,
                                decision_user_id=request.decision_user_id,
                                decision_arguments_digest=request.decision_arguments_digest,
                                decided_at=request.decided_at,
                                decision_basis=request.decision_basis,
                                authorization_revision=request.authorization_revision,
                            )
                        call = call.start(finished_at).succeed(finished_at)
                calls.append(call)
        results = [
            result
            for message in active
            if message.tool_result is not None
            and message.tool_call_id != exclude_tool_call_id
            for result in (message.tool_result,)
        ]
        return calls, results


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

    async def _complete_after_successful_write_response_failure(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        progress: _RunProgress,
        *,
        checkpoint: _TrajectoryCheckpoint | None,
        phase: str,
        technical_reason: str,
    ) -> AgentRunResult | None:
        successful_result_ids = {
            result.tool_call_id
            for result in results
            if result.status is ToolResultStatus.SUCCEEDED
        }
        if not any(
            call.risk is ToolRisk.WRITE
            and call.status is ToolCallStatus.SUCCEEDED
            and call.tool_call_id in successful_result_ids
            for call in calls
        ):
            return None

        # A later permission block means the turn is incomplete even when an
        # earlier write succeeded. Let the normal failure path preserve the
        # blocking reason instead of claiming that the saved write completed
        # the whole request.
        if _permission_denial_code(results) is not None:
            return None

        chinese = any(
            "\u4e00" <= char <= "\u9fff"
            for char in self._active_user_request(messages)
        )
        content = (
            "已批准的操作已完成并保存。详细回复暂时无法生成；请以已保存的结果为准。"
            if chinese
            else "The approved action completed and was saved. The detailed response is "
            "unavailable; the saved result remains authoritative."
        )
        messages.append(
            self._assistant(
                context,
                content,
                progress,
                messages=messages,
                calls=calls,
                results=results,
            )
        )
        await self._checkpoint(checkpoint, messages, calls, results)
        progress.trace(
            context,
            phase=phase,
            termination_reason="write_completed_response_unavailable",
            run_status=AgentRunStatus.FAILED,
            final_answer=True,
            retry_reason=technical_reason,
        )
        return self._result(
            AgentRunStatus.FAILED,
            messages,
            calls,
            results,
            error_code=technical_reason,
            warnings=(_SUCCESSFUL_WRITE_RESPONSE_UNAVAILABLE_WARNING,),
        )

    @staticmethod
    def _failure_answer(
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        resource_limited: bool = False,
    ) -> str:
        chinese = any("\u4e00" <= char <= "\u9fff" for char in ResearchAgentRunner._active_user_request(messages))
        if resource_limited:
            lead = (
                "本轮达到运行资源上限，已取得的结果已保留。不能据此判断论文没有证据，可以继续核对未完成的部分。"
                if chinese else
                "This turn reached its runtime resource limit. Obtained results were preserved; "
                "this does not establish an absence of scientific evidence. You can continue the unfinished review."
            )
        else:
            lead = (
                "本轮回答未能完成，已取得的结果已保留。这是技术中断，不能据此判断论文没有证据。可以继续核对未完成的部分。"
                if chinese else
                "This turn could not be completed. Obtained results were preserved; the technical "
                "interruption does not establish an absence of scientific evidence. You can continue the unfinished review."
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
        read_tool_names = {
            "read_source", "inspect_table", "inspect_document_sources", "search_sources",
        }
        collection_paper_totals: set[int] = set()
        screened_documents: set[str] = set()
        requested_documents = {
            str(call.arguments["document_id"])
            for call in calls
            if call.name in read_tool_names and call.arguments.get("document_id")
        }
        read_documents: set[str] = set()
        exact_sources: set[str] = set()
        failed_documents: set[str] = set()
        read_argument_errors: set[str] = set()
        action_argument_errors: set[str] = set()
        failed_writes: set[str] = set()
        permission_denials: set[str] = set()
        successful_reads: dict[str, list[Mapping[str, Any]]] = {}
        for result in results:
            call = calls_by_id.get(result.tool_call_id)
            name = call.name if call else None
            if result.status is ToolResultStatus.FAILED:
                document_id = str(result.data.get("document_id") or
                                  (call.arguments.get("document_id") if call else "") or "").strip()
                error_code = str(result.error_code or "")
                label = f"{name or 'unknown'}:{document_id or 'arguments'}"
                if error_code == "invalid_tool_arguments":
                    if name in read_tool_names:
                        read_argument_errors.add(label)
                    else:
                        action_argument_errors.add(label)
                elif error_code.startswith("permission_") or error_code in {
                    "tool_permission_denied", "user_rejected",
                }:
                    permission_denials.add(label)
                elif call is not None and call.risk is ToolRisk.WRITE:
                    failed_writes.add(label)
                elif name in read_tool_names and error_code not in {
                    "resource_budget", "invalid_tool_batch", "capability_unavailable_for_turn",
                } and document_id:
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
                f"原文读取参数错误 ({len(read_argument_errors)}): {display(read_argument_errors)}\n"
                f"研究操作参数错误 ({len(action_argument_errors)}): {display(action_argument_errors)}\n"
                f"写入操作失败 ({len(failed_writes)}): {display(failed_writes)}\n"
                f"权限拒绝 ({len(permission_denials)}): {display(permission_denials)}\n"
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
            f"Source read argument errors ({len(read_argument_errors)}): "
            f"{display(read_argument_errors)}\n"
            f"Research action argument errors ({len(action_argument_errors)}): "
            f"{display(action_argument_errors)}\n"
            f"Failed write operations ({len(failed_writes)}): "
            f"{display(failed_writes)}\n"
            f"Permission denials ({len(permission_denials)}): "
            f"{display(permission_denials)}\n"
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
        except PaperExperimentDraftValidationError as exc:
            logger.warning(
                "Research capability rejected draft tool=%s validation_path=%s",
                call.name,
                exc.validation_path or "unknown",
            )
            data = {
                "validation_path": exc.validation_path,
                "repair_hint": (
                    "Keep the full source-supported draft. Each comparison must "
                    "reference measurements for one outcome only; split different "
                    "outcomes into separate comparisons and resubmit the complete draft."
                ),
            }
            call, result = ResearchAgentRunner._failure(
                call,
                exc.error_code,
                _safe_capability_error_message(exc),
                data=data,
            )
        except PaperExperimentAuthoringError as exc:
            logger.warning(
                "Research PaperExperiment authoring prerequisite failed tool=%s error_code=%s",
                call.name,
                exc.error_code,
            )
            call, result = ResearchAgentRunner._failure(
                call,
                exc.error_code,
                _safe_capability_error_message(exc),
                data={"recoverable": True},
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
                "The research capability could not be completed: "
                + _safe_capability_error_message(exc),
            )
        return call, result

    async def _execute_approved_call(
        self,
        context: AgentContext,
        call: ChatToolCall,
        handler: Any,
        *,
        progress: _RunProgress,
        arguments: BaseModel | None = None,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        """Run an approved write under the same request deadline as reads."""
        try:
            return await wait_for(
                self._execute_one(
                    context,
                    call,
                    handler,
                    arguments=arguments,
                ),
                timeout=min(progress.remaining_seconds(), self.limits.max_request_seconds),
            )
        except TimeoutError:
            return self._failure(
                call,
                "capability_timeout",
                "The approved research action could not be completed in this turn.",
            )


    @staticmethod
    def _failure(
        call: ChatToolCall,
        code: str,
        message: str,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        return call.fail(code, _now_iso()), ChatToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolResultStatus.FAILED,
            data=dict(data or {}),
            error_code=code,
            error_message=message,
        )

    @staticmethod
    def _assistant(
        context: AgentContext,
        content: str,
        progress: _RunProgress,
        *,
        messages: list[ChatMessage] | tuple[ChatMessage, ...] = (),
        calls: list[ChatToolCall] | tuple[ChatToolCall, ...] = (),
        results: list[ChatToolResult] | tuple[ChatToolResult, ...] = (),
    ) -> ChatMessage:
        return ChatMessage.assistant(
            message_id=progress.response_message_id,
            session_id=context.session_id,
            content=format_inline_citations(
                content,
                calls=calls,
                results=results,
                messages=messages,
            ),
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
