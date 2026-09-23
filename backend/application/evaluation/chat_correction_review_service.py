"""Build and review source-backed samples from the durable Chat trajectory."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable
from uuid import uuid4

from application.chat.session_service import ChatSessionNotFoundError, ChatSessionService
from application.repositories.chat_correction_review_repository import (
    ChatCorrectionReviewRepository,
)
from domain.chat import ChatCorrectionCaseStatus, ChatMessage, ChatMessageRole
from domain.evaluation import (
    ChatCorrectionReview,
    ChatCorrectionReviewDecision,
    ChatCorrectionSample,
    sample_digest,
)


class ChatCorrectionSampleNotFoundError(FileNotFoundError):
    pass


class ChatCorrectionReviewStaleError(ValueError):
    """The stored sample no longer represents the current Chat evidence."""


class ChatCorrectionReviewService:
    def __init__(
        self,
        *,
        chat_session_service: ChatSessionService,
        repository: ChatCorrectionReviewRepository,
    ) -> None:
        self.chat_session_service = chat_session_service
        self.repository = repository

    async def create_sample_for_user(
        self, session_id: str, case_id: str, user_id: str
    ) -> ChatCorrectionSample:
        session = await self.chat_session_service.get_session_for_user(session_id, user_id)
        case = await self.chat_session_service.repository.read_correction_case(session_id, case_id)
        if case is None:
            raise ChatCorrectionSampleNotFoundError(f"correction case not found: {case_id}")
        sample = await self._rebuild_sample(session, case)
        existing = await self.repository.read_sample(session_id, sample.sample_id)
        if existing is not None:
            if existing.digest != sample.digest:
                raise ChatCorrectionReviewStaleError(
                    "stored correction sample no longer matches the Chat trajectory"
                )
            return existing
        return await self.repository.save_sample(sample)

    async def get_sample_for_user(
        self, session_id: str, sample_id: str, user_id: str
    ) -> ChatCorrectionSample | None:
        await self.chat_session_service.get_session_for_user(session_id, user_id)
        return await self.repository.read_sample(session_id, sample_id)

    async def list_samples_for_user(
        self, session_id: str, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[ChatCorrectionSample, ...]:
        await self.chat_session_service.get_session_for_user(session_id, user_id)
        return await self.repository.list_samples(session_id, limit=limit, offset=offset)

    async def list_reviews_for_user(
        self, session_id: str, sample_id: str, user_id: str
    ) -> tuple[ChatCorrectionReview, ...]:
        await self.chat_session_service.get_session_for_user(session_id, user_id)
        sample = await self.repository.read_sample(session_id, sample_id)
        if sample is None:
            raise ChatCorrectionSampleNotFoundError(f"correction sample not found: {sample_id}")
        return await self.repository.list_reviews(session_id, sample_id)

    async def current_sample_for_user(
        self, session_id: str, sample_id: str, user_id: str
    ) -> ChatCorrectionSample:
        """Rebuild a stored sample from the current owned Chat trajectory.

        Dataset freezing uses this public boundary so it can distinguish a
        stale snapshot from the immutable bytes that were originally stored.
        """

        session = await self.chat_session_service.get_session_for_user(session_id, user_id)
        sample = await self.repository.read_sample(session_id, sample_id)
        if sample is None:
            raise ChatCorrectionSampleNotFoundError(f"correction sample not found: {sample_id}")
        case = await self.chat_session_service.repository.read_correction_case(
            session_id, sample.case_id
        )
        if case is None:
            raise ChatCorrectionReviewStaleError("the correction case was removed")
        return await self._rebuild_sample(session, case)

    async def effective_review_for_user(
        self, session_id: str, sample_id: str, user_id: str
    ) -> ChatCorrectionReview | None:
        await self.chat_session_service.get_session_for_user(session_id, user_id)
        sample = await self.repository.read_sample(session_id, sample_id)
        if sample is None:
            raise ChatCorrectionSampleNotFoundError(f"correction sample not found: {sample_id}")
        return _effective_review(await self.repository.list_reviews(session_id, sample_id))

    async def review_sample_for_user(
        self,
        session_id: str,
        sample_id: str,
        user_id: str,
        *,
        decision: str,
        reason: str | None = None,
        support_message_ids: Iterable[str] = (),
    ) -> ChatCorrectionReview:
        session = await self.chat_session_service.get_session_for_user(session_id, user_id)
        sample = await self.repository.read_sample(session_id, sample_id)
        if sample is None:
            raise ChatCorrectionSampleNotFoundError(f"correction sample not found: {sample_id}")
        if not sample.validate_digest():
            raise ChatCorrectionReviewStaleError("stored correction sample digest is invalid")
        case = await self.chat_session_service.repository.read_correction_case(
            session_id, sample.case_id
        )
        if case is None:
            raise ChatCorrectionReviewStaleError("the correction case was removed")
        current = await self._rebuild_sample(session, case)
        if current.digest != sample.digest:
            raise ChatCorrectionReviewStaleError(
                "the Chat input, target, or source references changed after this sample was saved"
            )
        try:
            selected = ChatCorrectionReviewDecision(decision)
        except ValueError as exc:
            raise ValueError("unsupported correction review decision") from exc
        normalized_support = tuple(dict.fromkeys(str(item).strip() for item in support_message_ids if str(item).strip()))
        invalid_support = set(normalized_support) - set(current.message_ids)
        if selected is not ChatCorrectionReviewDecision.WITHDRAW and not normalized_support:
            raise ValueError("a correction review requires supporting Chat messages")
        if invalid_support:
            raise ValueError("support messages must belong to the sampled Chat trace")
        normalized_reason = str(reason or "").strip() or None
        if selected in {
            ChatCorrectionReviewDecision.REJECT,
            ChatCorrectionReviewDecision.INSUFFICIENT,
            ChatCorrectionReviewDecision.WITHDRAW,
        } and not normalized_reason:
            raise ValueError("this correction review decision requires a reason")
        if selected is ChatCorrectionReviewDecision.ACCEPT:
            if not current.target.strip():
                raise ValueError("accepted correction samples require a target")
            if not current.source_refs:
                raise ValueError("accepted correction samples require Source references")
        history = await self.repository.list_reviews(session_id, sample_id)
        if any(item.decision is ChatCorrectionReviewDecision.WITHDRAW for item in history):
            raise ValueError("a withdrawn correction sample cannot receive another decision")
        review = ChatCorrectionReview(
            review_id=f"chat_review_{uuid4().hex[:40]}",
            sample_id=sample.sample_id,
            session_id=session_id,
            sample_digest=sample.digest,
            decision=selected,
            reviewer_id=user_id,
            reason=normalized_reason,
            support_message_ids=normalized_support,
            seq=0,
            created_at=_now_iso(),
        )
        return await self.repository.append_review(review)

    async def status_for_user(
        self, session_id: str, sample_id: str, user_id: str
    ) -> dict[str, Any]:
        await self.chat_session_service.get_session_for_user(session_id, user_id)
        sample = await self.repository.read_sample(session_id, sample_id)
        if sample is None:
            raise ChatCorrectionSampleNotFoundError(f"correction sample not found: {sample_id}")
        case = await self.chat_session_service.repository.read_correction_case(session_id, sample.case_id)
        if case is None:
            return {"state": "stale", "latest": None, "sample_digest": sample.digest}
        try:
            current = await self._rebuild_sample(
                await self.chat_session_service.get_session_for_user(session_id, user_id), case
            )
        except (ValueError, FileNotFoundError):
            current = None
        history = await self.repository.list_reviews(session_id, sample_id)
        latest = _effective_review(history)
        if current is None or current.digest != sample.digest or not sample.validate_digest():
            state = "stale"
        elif latest is None:
            state = "pending"
        else:
            state = latest.decision.value
        return {
            "state": state,
            "sample_digest": sample.digest,
            "latest": latest.to_record() if latest is not None else None,
        }

    async def _rebuild_sample(self, session: Any, case: Any) -> ChatCorrectionSample:
        if case.status is not ChatCorrectionCaseStatus.LINKED or not case.corrected_message_id:
            raise ValueError("only linked correction cases can become review samples")
        messages = await self.chat_session_service.repository.read_messages(session.session_id)
        by_id = {message.message_id: message for message in messages}
        original = by_id.get(case.original_message_id)
        feedback = by_id.get(case.feedback_message_id)
        corrected = by_id.get(case.corrected_message_id)
        if original is None or feedback is None or corrected is None:
            raise ChatCorrectionReviewStaleError("correction case messages are no longer available")
        if corrected.role is not ChatMessageRole.ASSISTANT or not corrected.content.strip() or corrected.tool_calls:
            raise ValueError("correction target must be a final assistant answer")
        call = await self.chat_session_service.repository.read_model_call(
            session.session_id, case.corrected_model_call_id or ""
        )
        if call is None or call.status != "provider_succeeded" or not call.provider_confirmed:
            raise ValueError("correction target has no successful model input")
        positions = {message.message_id: index for index, message in enumerate(messages)}
        try:
            start = positions[original.message_id]
            end = positions[corrected.message_id]
        except KeyError as exc:
            raise ChatCorrectionReviewStaleError("correction messages are not in the current trajectory") from exc
        if start >= end:
            raise ValueError("correction target must follow the challenge")
        observations = tuple(_observation(message) for message in messages[start : end + 1])
        source_refs = _source_refs(messages[start : end + 1])
        content = {
            "case_id": case.case_id,
            "session_id": session.session_id,
            "collection_id": session.collection_id,
            "model_call_id": call.call_id,
            "input": deepcopy(call.request),
            "observations": list(observations),
            "target": corrected.content,
            "source_refs": list(source_refs),
        }
        digest = sample_digest(content)
        sample_id = "chat_sample_" + sha256(case.case_id.encode("utf-8")).hexdigest()[:40]
        now = _now_iso()
        return ChatCorrectionSample(
            sample_id=sample_id,
            case_id=case.case_id,
            session_id=session.session_id,
            collection_id=session.collection_id,
            model_call_id=call.call_id,
            input=deepcopy(call.request),
            observations=observations,
            target=corrected.content,
            source_refs=source_refs,
            digest=digest,
            created_at=now,
            updated_at=now,
        )


def _observation(message: ChatMessage) -> dict[str, Any]:
    if message.role is ChatMessageRole.TOOL:
        return {
            "kind": "tool_observation",
            "message_id": message.message_id,
            "tool_call_id": message.tool_call_id,
            "result": message.tool_result.to_record() if message.tool_result else None,
        }
    if message.role is ChatMessageRole.ASSISTANT and message.tool_calls:
        return {
            "kind": "tool_request",
            "message_id": message.message_id,
            "tool_calls": [item.to_record() for item in message.tool_calls],
            "content": message.content,
        }
    return {
        "kind": "message",
        "message_id": message.message_id,
        "role": message.role.value,
        "content": message.content,
    }


def _source_refs(messages: Iterable[ChatMessage]) -> tuple[dict[str, Any], ...]:
    values: dict[str, dict[str, Any]] = {}
    for message in messages:
        for context in message.source_contexts:
            record = {"kind": "message_source", **context.to_record()}
            values[json.dumps(record, sort_keys=True, separators=(",", ":"))] = record
        if message.tool_result is not None:
            for resource in message.tool_result.resource_refs:
                record = {"kind": "tool_resource", **resource.to_record()}
                values[json.dumps(record, sort_keys=True, separators=(",", ":"))] = record
    return tuple(values[key] for key in sorted(values))


def _effective_review(
    reviews: Iterable[ChatCorrectionReview],
) -> ChatCorrectionReview | None:
    ordered = sorted(reviews, key=lambda item: (item.seq, item.created_at, item.review_id))
    withdrawals = [item for item in ordered if item.decision is ChatCorrectionReviewDecision.WITHDRAW]
    if withdrawals:
        return withdrawals[-1]
    return ordered[-1] if ordered else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ChatCorrectionReviewService",
    "ChatCorrectionReviewStaleError",
    "ChatCorrectionSampleNotFoundError",
]
