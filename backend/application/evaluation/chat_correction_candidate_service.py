"""Propose owner-reviewed correction candidates from saved Chat evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import inspect
import json
import logging
from functools import partial
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.session_service import ChatSessionService
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
    build_default_structured_response_client,
)
from application.evaluation.chat_correction_review_service import (
    ChatCorrectionReviewService,
)
from application.repositories.chat_correction_candidate_repository import (
    ChatCorrectionCandidateRepository,
)
from domain.chat import ChatMessage
from domain.evaluation import ChatCorrectionCandidate, ChatCorrectionCandidateStatus


logger = logging.getLogger(__name__)

_PROMPT_VERSION = "chat-correction-candidate.v1"
_TASK_TYPE = "chat_correction_candidate"
_MAX_MESSAGES = 24
_MAX_TEXT_CHARS = 60000


class ChatCorrectionCandidateNotFoundError(FileNotFoundError):
    """The candidate is absent or is outside the caller's owned session."""


class ChatCorrectionCandidateUnavailableError(RuntimeError):
    """Candidate persistence or model execution is unavailable."""


class _CandidateProposal(BaseModel):
    """The model may select existing message IDs, but cannot write an answer."""

    model_config = ConfigDict(extra="ignore")

    outcome: Literal["candidate", "ambiguous", "none"]
    original_message_id: str | None = Field(default=None, max_length=128)
    challenge_message_id: str | None = Field(default=None, max_length=128)
    corrected_message_id: str | None = Field(default=None, max_length=128)
    rationale: str = Field(default="", max_length=4000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_keys(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        outcome = payload.get("outcome", payload.get("decision", payload.get("status")))
        if outcome is None:
            if payload.get("candidate") is False:
                outcome = "none"
            elif payload.get("corrected_message_id"):
                outcome = "candidate"
        if isinstance(outcome, str):
            normalized = outcome.strip().lower()
            outcome = {
                "needs_review": "candidate",
                "review": "candidate",
                "proposed": "candidate",
                "no_candidate": "none",
                "no-candidate": "none",
                "uncertain": "ambiguous",
            }.get(normalized, normalized)
        if outcome is not None:
            payload["outcome"] = outcome
        if "rationale" not in payload and "reason" in payload:
            payload["rationale"] = payload["reason"]
        return payload


_SYSTEM_PROMPT = """You inspect one saved research Chat turn for a possible correction.
The input contains only existing user challenges, final assistant messages, event IDs,
and summaries of persisted model calls. Select IDs that already exist in this input.
Never invent a corrected answer, Source, event, or model call. Return `none` when the
user message is an ordinary follow-up or no defensible correction sequence exists.
Return `ambiguous` when more than one existing sequence remains plausible. Return
`candidate` only when one original answer, the challenge, and one corrected final
answer form a likely answer -> challenge -> answer sequence. A candidate is only a
proposal for human inspection; it is not an approval decision.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _message_is_final_answer(message: ChatMessage) -> bool:
    return message.role.value == "assistant" and bool(message.content.strip()) and not message.tool_calls


def _message_is_challenge(message: ChatMessage) -> bool:
    return message.role.value == "user" and bool(message.content.strip())


def _event_ids(messages: tuple[ChatMessage, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for message in messages:
        for value in (message.message_id, message.tool_call_id):
            if value and value not in result:
                result.append(value)
        for request in message.tool_calls:
            if request.tool_call_id not in result:
                result.append(request.tool_call_id)
        if message.tool_result is not None and message.tool_result.tool_call_id not in result:
            result.append(message.tool_result.tool_call_id)
    return tuple(result)


def _call_summary(call: Any) -> dict[str, Any]:
    """Keep P1 metadata while excluding the exact provider request."""

    return {
        "call_id": call.call_id,
        "session_id": call.session_id,
        "trigger_message_id": call.trigger_message_id,
        "response_message_id": call.response_message_id,
        "purpose": str(call.purpose),
        "model": call.model,
        "request_digest": call.request_digest,
        "status": str(call.status),
        "provider_confirmed": bool(call.provider_confirmed),
        "finished_at": call.finished_at,
    }


def _trace_value(client: Any, name: str, default: Any = None) -> Any:
    method = getattr(client, name, None)
    if not callable(method):
        return default
    try:
        value = method()
    except Exception:  # pragma: no cover - diagnostic helpers must not mask the result
        return default
    return value if value is not None else default


def _trace_parts(client: Any) -> tuple[str | None, str | None]:
    trace = _trace_value(client, "peek_last_trace", {}) or {}
    raw = trace.get("raw_output") if isinstance(trace, Mapping) else None
    attempts = trace.get("attempts") if isinstance(trace, Mapping) else ()
    finish_reason = None
    if isinstance(attempts, list) and attempts:
        finish_reason = str(attempts[-1].get("finish_reason") or "").strip() or None
    return (str(raw) if raw else None), finish_reason


def _provider_failure(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    name = type(error).__name__.lower()
    module = type(error).__module__.lower()
    text = str(error).lower()
    if any(token in name for token in ("timeout", "connection", "transport", "apierror", "provider")):
        return True
    if any(token in module for token in ("openai", "httpx", "urllib3")):
        return True
    return any(token in text for token in ("timed out", "connection", "network", "rate limit", "503", "502"))


class ChatCorrectionCandidateService:
    """Run an explicit, owner-scoped proposal pass over one saved session."""

    def __init__(
        self,
        *,
        chat_session_service: ChatSessionService,
        repository: ChatCorrectionCandidateRepository,
        review_service: ChatCorrectionReviewService | None = None,
        response_client: StructuredResponseClient | None = None,
        max_prompt_tokens: int = 24000,
        max_completion_tokens: int = 1200,
        request_timeout_s: float = 90,
    ) -> None:
        self.chat_session_service = chat_session_service
        self.repository = repository
        self.review_service = review_service
        self.response_client = response_client or build_default_structured_response_client()
        self.max_prompt_tokens = max_prompt_tokens
        self.max_completion_tokens = max_completion_tokens
        self.request_timeout_s = request_timeout_s

    async def propose_for_user(
        self,
        session_id: str,
        user_id: str,
        *,
        challenge_message_id: str | None = None,
        answer_message_id: str | None = None,
    ) -> ChatCorrectionCandidate:
        session = await self.chat_session_service.get_session_for_user(session_id, user_id)
        messages = await self.chat_session_service.repository.read_messages(session_id)
        _context, challenge, disputed, candidate_answers, selected_slice = self._select_context(
            messages,
            challenge_message_id=challenge_message_id,
            answer_message_id=answer_message_id,
        )
        calls = await self.chat_session_service.repository.read_model_calls(
            session_id, limit=200, offset=0
        )
        selected_message_ids = {item.message_id for item in selected_slice}
        relevant_calls = tuple(
            call
            for call in calls
            if call.response_message_id in selected_message_ids
            or call.trigger_message_id in selected_message_ids
        )
        event_ids = _event_ids(selected_slice)
        model_call_ids = tuple(call.call_id for call in relevant_calls)
        request, prompt_error = self._build_request(
            session_id=session.session_id,
            challenge=challenge,
            disputed=disputed,
            candidate_answers=candidate_answers,
            event_ids=event_ids,
            calls=relevant_calls,
        )
        candidate_id = f"chat_candidate_{uuid4().hex}"
        now = _now_iso()

        if prompt_error is not None:
            return await self.repository.save_candidate(
                ChatCorrectionCandidate.create(
                    candidate_id=candidate_id,
                    owner_id=user_id,
                    collection_id=session.collection_id,
                    session_id=session.session_id,
                    challenge_message_id=challenge.message_id if challenge else None,
                    answer_message_id=disputed.message_id if disputed else None,
                    event_ids=event_ids,
                    model_call_ids=model_call_ids,
                    status=ChatCorrectionCandidateStatus.INVALID_PROPOSAL,
                    proposal=None,
                    request=request,
                    raw_response=None,
                    finish_reason=None,
                    error_code=prompt_error,
                    created_at=now,
                )
            )

        # A normal first question or follow-up has no answer -> challenge
        # boundary. Persist the explicit abstention without asking the model to
        # infer a correction from unrelated history.
        if challenge is None or disputed is None:
            return await self.repository.save_candidate(
                ChatCorrectionCandidate.create(
                    candidate_id=candidate_id,
                    owner_id=user_id,
                    collection_id=session.collection_id,
                    session_id=session.session_id,
                    challenge_message_id=challenge.message_id if challenge else None,
                    answer_message_id=disputed.message_id if disputed else None,
                    event_ids=event_ids,
                    model_call_ids=model_call_ids,
                    status=ChatCorrectionCandidateStatus.NO_CANDIDATE,
                    proposal=None,
                    request=request,
                    raw_response=None,
                    finish_reason=None,
                    error_code="no_correction_sequence",
                    created_at=now,
                )
            )

        try:
            prompt_tokens = self.response_client.estimate_prompt_tokens(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=request["messages"][1]["content"],
                response_model=_CandidateProposal,
            )
            if prompt_tokens > self.max_prompt_tokens:
                return await self.repository.save_candidate(
                    ChatCorrectionCandidate.create(
                        candidate_id=candidate_id,
                        owner_id=user_id,
                        collection_id=session.collection_id,
                        session_id=session.session_id,
                        challenge_message_id=challenge.message_id if challenge else None,
                        answer_message_id=disputed.message_id if disputed else None,
                        event_ids=event_ids,
                        model_call_ids=model_call_ids,
                        status=ChatCorrectionCandidateStatus.INVALID_PROPOSAL,
                        proposal=None,
                        request={**request, "prompt_tokens": prompt_tokens},
                        raw_response=None,
                        finish_reason=None,
                        error_code="candidate_prompt_overflow",
                        created_at=now,
                    )
                )
        except Exception as exc:
            logger.warning("Unable to estimate correction candidate prompt", exc_info=True)
            return await self.repository.save_candidate(
                ChatCorrectionCandidate.create(
                    candidate_id=candidate_id,
                    owner_id=user_id,
                    collection_id=session.collection_id,
                    session_id=session.session_id,
                    challenge_message_id=challenge.message_id if challenge else None,
                    answer_message_id=disputed.message_id if disputed else None,
                    event_ids=event_ids,
                    model_call_ids=model_call_ids,
                    status=ChatCorrectionCandidateStatus.INVALID_PROPOSAL,
                    proposal=None,
                    request=request,
                    raw_response=None,
                    finish_reason=None,
                    error_code="candidate_prompt_unavailable",
                    created_at=now,
                )
            )

        parsed: Any = None
        raw_response: str | None = None
        finish_reason: str | None = None
        status = ChatCorrectionCandidateStatus.NEEDS_REVIEW
        error_code: str | None = None
        proposal: dict[str, Any] | None = None
        try:
            result = self.response_client.complete(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=request["messages"][1]["content"],
                response_model=_CandidateProposal,
                max_completion_tokens=self.max_completion_tokens,
                force_json_text=True,
                json_completion=partial(
                    self.response_client.complete_json,
                    max_attempts=1,
                    fail_on_output_saturation=True,
                    json_schema_name="chat_correction_candidate",
                ),
                before_request=lambda: self.request_timeout_s,
                task_type=_TASK_TYPE,
                prompt_version=_PROMPT_VERSION,
                fail_on_output_saturation=True,
            )
            if inspect.isawaitable(result):
                result = await result
            parsed = result
            raw_response, finish_reason = _trace_parts(self.response_client)
            proposal = self._proposal_record(parsed)
            if finish_reason == "length":
                status = ChatCorrectionCandidateStatus.INVALID_PROPOSAL
                error_code = "candidate_output_truncated"
            elif proposal["outcome"] == "none":
                status = ChatCorrectionCandidateStatus.NO_CANDIDATE
            elif proposal["outcome"] == "ambiguous":
                status = ChatCorrectionCandidateStatus.AMBIGUOUS
            else:
                self._validate_proposal_shape(
                    proposal,
                    challenge=challenge,
                    disputed=disputed,
                    candidate_answers=candidate_answers,
                    event_ids=event_ids,
                )
                await self.chat_session_service.validate_correction_case_for_user(
                    session_id,
                    user_id,
                    original_message_id=str(proposal["original_message_id"]),
                    feedback_message_id=str(proposal["challenge_message_id"]),
                    corrected_message_id=str(proposal["corrected_message_id"]),
                )
        except StructuredOutputSaturatedError:
            raw_response, finish_reason = _trace_parts(self.response_client)
            status = ChatCorrectionCandidateStatus.INVALID_PROPOSAL
            error_code = "candidate_output_truncated"
        except (ValueError, TypeError) as exc:
            raw_response, finish_reason = _trace_parts(self.response_client)
            status = ChatCorrectionCandidateStatus.INVALID_PROPOSAL
            error_code = "candidate_proposal_invalid"
            logger.info("Correction candidate failed deterministic validation: %s", exc)
        except Exception as exc:  # noqa: BLE001
            raw_response, finish_reason = _trace_parts(self.response_client)
            if _provider_failure(exc):
                status = ChatCorrectionCandidateStatus.PROVIDER_FAILED
                error_code = "candidate_provider_failed"
            else:
                status = ChatCorrectionCandidateStatus.INVALID_PROPOSAL
                error_code = "candidate_response_invalid"
            logger.warning("Correction candidate provider call failed", exc_info=True)

        stored_request = dict(request)
        stored_request["prompt_version"] = _PROMPT_VERSION
        stored_request["response_schema"] = _CandidateProposal.model_json_schema()
        if parsed is not None and hasattr(parsed, "model_dump"):
            stored_request["response_model"] = _CandidateProposal.__name__
        return await self.repository.save_candidate(
            ChatCorrectionCandidate.create(
                candidate_id=candidate_id,
                owner_id=user_id,
                collection_id=session.collection_id,
                session_id=session.session_id,
                challenge_message_id=challenge.message_id if challenge else None,
                answer_message_id=disputed.message_id if disputed else None,
                event_ids=event_ids,
                model_call_ids=model_call_ids,
                status=status,
                proposal=proposal,
                request=stored_request,
                raw_response=raw_response,
                finish_reason=finish_reason,
                error_code=error_code,
                created_at=now,
            )
        )

    async def run_for_user(self, *args: Any, **kwargs: Any) -> ChatCorrectionCandidate:
        """Readable alias for the explicit proposal operation."""

        return await self.propose_for_user(*args, **kwargs)

    async def list_for_user(
        self, session_id: str, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[ChatCorrectionCandidate, ...]:
        await self.chat_session_service.get_session_for_user(session_id, user_id)
        return await self.repository.list_candidates_for_user(
            session_id, user_id, limit=limit, offset=offset
        )

    async def get_for_user(
        self, session_id: str, candidate_id: str, user_id: str
    ) -> ChatCorrectionCandidate | None:
        await self.chat_session_service.get_session_for_user(session_id, user_id)
        return await self.repository.read_candidate_for_user(session_id, candidate_id, user_id)

    async def select_for_user(
        self, session_id: str, candidate_id: str, user_id: str
    ) -> ChatCorrectionCandidate:
        if self.review_service is None:
            raise ChatCorrectionCandidateUnavailableError("correction review storage is unavailable")
        candidate = await self.get_for_user(session_id, candidate_id, user_id)
        if candidate is None:
            raise ChatCorrectionCandidateNotFoundError(candidate_id)
        if candidate.selected_sample_id is not None:
            return candidate
        if not candidate.selectable or candidate.proposal is None:
            raise ValueError("only a needs_review candidate can be selected")
        proposal = candidate.proposal
        original_id = _clean_id(proposal.get("original_message_id"))
        challenge_id = _clean_id(proposal.get("challenge_message_id"))
        corrected_id = _clean_id(proposal.get("corrected_message_id"))
        if not original_id or not challenge_id or not corrected_id:
            raise ValueError("candidate proposal has no complete correction sequence")
        case = await self.chat_session_service.link_correction_case_for_user(
            session_id,
            user_id,
            original_message_id=original_id,
            feedback_message_id=challenge_id,
            corrected_message_id=corrected_id,
        )
        sample = await self.review_service.create_sample_for_user(
            session_id, case.case_id, user_id
        )
        return await self.repository.mark_selected(
            session_id,
            candidate_id,
            user_id,
            case_id=case.case_id,
            sample_id=sample.sample_id,
            updated_at=_now_iso(),
        )

    def _select_context(
        self,
        messages: tuple[ChatMessage, ...],
        *,
        challenge_message_id: str | None,
        answer_message_id: str | None,
    ) -> tuple[
        tuple[dict[str, Any], ...],
        ChatMessage | None,
        ChatMessage | None,
        tuple[ChatMessage, ...],
        tuple[ChatMessage, ...],
    ]:
        by_id = {message.message_id: message for message in messages}
        challenge = by_id.get(_clean_id(challenge_message_id) or "") if challenge_message_id else None
        disputed = by_id.get(_clean_id(answer_message_id) or "") if answer_message_id else None
        if challenge is not None and not _message_is_challenge(challenge):
            raise ValueError("candidate challenge must be a non-empty user message")
        if disputed is not None and not _message_is_final_answer(disputed):
            raise ValueError("candidate answer must be a final assistant message")
        if challenge is None:
            for index in range(len(messages) - 1, -1, -1):
                if _message_is_challenge(messages[index]) and any(
                    _message_is_final_answer(item) for item in messages[:index]
                ):
                    challenge = messages[index]
                    break
        if challenge is not None:
            challenge_index = messages.index(challenge)
            if disputed is None:
                disputed = next(
                    (
                        messages[index]
                        for index in range(challenge_index - 1, -1, -1)
                        if _message_is_final_answer(messages[index])
                    ),
                    None,
                )
            if disputed is not None and messages.index(disputed) >= challenge_index:
                raise ValueError("candidate answer must precede the challenge")
        if challenge is None or disputed is None:
            return (), challenge, disputed, (), ()
        challenge_index = messages.index(challenge)
        disputed_index = messages.index(disputed)
        after = messages[challenge_index + 1 :]
        candidate_answers: list[ChatMessage] = []
        for message in after:
            if message.role.value == "user":
                break
            if _message_is_final_answer(message):
                candidate_answers.append(message)
        end_index = messages.index(candidate_answers[-1]) + 1 if candidate_answers else challenge_index + 1
        start_index = max(0, disputed_index)
        selected_slice = messages[start_index:end_index]
        if len(selected_slice) > _MAX_MESSAGES:
            selected_slice = selected_slice[-_MAX_MESSAGES:]
        context = tuple(
            {
                "message_id": message.message_id,
                "role": message.role.value,
                "content": message.content,
            }
            for message in selected_slice
            if _message_is_final_answer(message) or message.message_id == challenge.message_id
        )
        return context, challenge, disputed, tuple(candidate_answers), tuple(selected_slice)

    def _build_request(
        self,
        *,
        session_id: str,
        challenge: ChatMessage | None,
        disputed: ChatMessage | None,
        candidate_answers: tuple[ChatMessage, ...],
        event_ids: tuple[str, ...],
        calls: tuple[Any, ...],
    ) -> tuple[dict[str, Any], str | None]:
        context = {
            "session_id": session_id,
            "challenge": (
                {"message_id": challenge.message_id, "content": challenge.content}
                if challenge is not None
                else None
            ),
            "disputed_answer": (
                {"message_id": disputed.message_id, "content": disputed.content}
                if disputed is not None
                else None
            ),
            "possible_corrected_answers": [
                {"message_id": item.message_id, "content": item.content}
                for item in candidate_answers
            ],
            "event_ids": list(event_ids),
            "model_calls": [_call_summary(call) for call in calls],
        }
        prompt = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(prompt) > _MAX_TEXT_CHARS:
            return {
                "model": getattr(self.response_client, "model", "unknown"),
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }, "candidate_context_overflow"
        return {
            "model": getattr(self.response_client, "model", "unknown"),
            "temperature": 0,
            "max_completion_tokens": self.max_completion_tokens,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }, None

    @staticmethod
    def _proposal_record(parsed: Any) -> dict[str, Any]:
        if isinstance(parsed, _CandidateProposal):
            return parsed.model_dump(mode="json")
        if isinstance(parsed, Mapping):
            return _CandidateProposal.model_validate(parsed).model_dump(mode="json")
        if hasattr(parsed, "model_dump"):
            return _CandidateProposal.model_validate(parsed.model_dump()).model_dump(mode="json")
        raise ValueError("provider returned an unsupported candidate proposal")

    @staticmethod
    def _validate_proposal_shape(
        proposal: Mapping[str, Any],
        *,
        challenge: ChatMessage | None,
        disputed: ChatMessage | None,
        candidate_answers: tuple[ChatMessage, ...],
        event_ids: tuple[str, ...],
    ) -> None:
        original_id = _clean_id(proposal.get("original_message_id"))
        challenge_id = _clean_id(proposal.get("challenge_message_id"))
        corrected_id = _clean_id(proposal.get("corrected_message_id"))
        if not original_id or not challenge_id or not corrected_id:
            raise ValueError("candidate proposal must reference three existing messages")
        if challenge is None or disputed is None or challenge_id != challenge.message_id:
            raise ValueError("candidate proposal references the wrong challenge")
        if original_id != disputed.message_id:
            raise ValueError("candidate proposal references the wrong disputed answer")
        if corrected_id not in {item.message_id for item in candidate_answers}:
            raise ValueError("candidate proposal references an unavailable corrected answer")
        if any(value not in event_ids for value in (original_id, challenge_id, corrected_id)):
            raise ValueError("candidate proposal references an unavailable event")


__all__ = [
    "ChatCorrectionCandidateNotFoundError",
    "ChatCorrectionCandidateService",
    "ChatCorrectionCandidateUnavailableError",
]
