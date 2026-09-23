"""Auditable model proposals for source-backed Chat correction cases."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Mapping

from domain.evaluation.chat_correction_sample import canonical_json, sample_digest


class ChatCorrectionCandidateStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    AMBIGUOUS = "ambiguous"
    NO_CANDIDATE = "no_candidate"
    INVALID_PROPOSAL = "invalid_proposal"
    PROVIDER_FAILED = "provider_failed"


def _text(value: Any, field_name: str, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _timestamp(value: Any, field_name: str) -> str:
    text = _text(value, field_name)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    return text


def _digest(value: Any, field_name: str) -> str:
    text = _text(value, field_name).lower()
    if len(text) != 64:
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    try:
        int(text, 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a SHA-256 hex digest") from exc
    return text


def _json_copy(value: Any, field_name: str) -> Any:
    copied = deepcopy(value)
    try:
        canonical_json(copied)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc
    return copied


def _ordered_ids(values: Any, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a list of IDs")
    result: list[str] = []
    for value in values:
        item = _text(value, field_name)
        if item not in result:
            result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class ChatCorrectionCandidate:
    """One persisted proposal attempt and its explicit selection state."""

    candidate_id: str
    owner_id: str
    collection_id: str
    session_id: str
    challenge_message_id: str | None
    answer_message_id: str | None
    event_ids: tuple[str, ...]
    model_call_ids: tuple[str, ...]
    status: ChatCorrectionCandidateStatus | str
    proposal: dict[str, Any] | None
    request: dict[str, Any]
    raw_response: str | None
    finish_reason: str | None
    error_code: str | None
    selected_case_id: str | None
    selected_sample_id: str | None
    digest: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "owner_id",
            "collection_id",
            "session_id",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        for field_name in ("challenge_message_id", "answer_message_id", "selected_case_id", "selected_sample_id"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, _text(value, field_name, required=False) or None)
        object.__setattr__(self, "event_ids", _ordered_ids(self.event_ids, "event_id"))
        object.__setattr__(self, "model_call_ids", _ordered_ids(self.model_call_ids, "model_call_id"))
        object.__setattr__(self, "status", ChatCorrectionCandidateStatus(self.status))
        proposal = None if self.proposal is None else _json_copy(dict(self.proposal), "proposal")
        object.__setattr__(self, "proposal", proposal)
        object.__setattr__(self, "request", _json_copy(dict(self.request), "request"))
        raw_response = None if self.raw_response is None else str(self.raw_response)
        object.__setattr__(self, "raw_response", raw_response)
        finish_reason = _text(self.finish_reason, "finish_reason", required=False) or None
        error_code = _text(self.error_code, "error_code", required=False) or None
        object.__setattr__(self, "finish_reason", finish_reason)
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "digest", _digest(self.digest, "digest"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at, "updated_at"))
        if datetime.fromisoformat(self.updated_at.replace("Z", "+00:00")) < datetime.fromisoformat(
            self.created_at.replace("Z", "+00:00")
        ):
            raise ValueError("updated_at cannot be before created_at")
        if self.selected_sample_id and not self.selected_case_id:
            raise ValueError("a selected sample requires a selected correction case")
        if self.digest != self.compute_digest():
            raise ValueError("candidate digest does not match its content")

    def content_for_digest(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "owner_id": self.owner_id,
            "collection_id": self.collection_id,
            "session_id": self.session_id,
            "challenge_message_id": self.challenge_message_id,
            "answer_message_id": self.answer_message_id,
            "event_ids": list(self.event_ids),
            "model_call_ids": list(self.model_call_ids),
            "status": self.status.value,
            "proposal": deepcopy(self.proposal),
            "request": deepcopy(self.request),
            "raw_response": self.raw_response,
            "finish_reason": self.finish_reason,
            "error_code": self.error_code,
            "selected_case_id": self.selected_case_id,
            "selected_sample_id": self.selected_sample_id,
        }

    def compute_digest(self) -> str:
        return sample_digest(self.content_for_digest())

    def validate_digest(self) -> bool:
        return self.digest == self.compute_digest()

    @property
    def selectable(self) -> bool:
        return self.status is ChatCorrectionCandidateStatus.NEEDS_REVIEW and self.proposal is not None

    def with_selection(
        self,
        *,
        case_id: str,
        sample_id: str,
        updated_at: str,
    ) -> "ChatCorrectionCandidate":
        content = self.content_for_digest()
        content["selected_case_id"] = case_id
        content["selected_sample_id"] = sample_id
        return replace(
            self,
            selected_case_id=case_id,
            selected_sample_id=sample_id,
            updated_at=updated_at,
            digest=sample_digest(content),
        )

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        owner_id: str,
        collection_id: str,
        session_id: str,
        challenge_message_id: str | None,
        answer_message_id: str | None,
        event_ids: tuple[str, ...],
        model_call_ids: tuple[str, ...],
        status: ChatCorrectionCandidateStatus | str,
        proposal: Mapping[str, Any] | None,
        request: Mapping[str, Any],
        raw_response: str | None,
        finish_reason: str | None,
        error_code: str | None,
        created_at: str,
    ) -> "ChatCorrectionCandidate":
        content = {
            "candidate_id": candidate_id,
            "owner_id": owner_id,
            "collection_id": collection_id,
            "session_id": session_id,
            "challenge_message_id": challenge_message_id,
            "answer_message_id": answer_message_id,
            "event_ids": list(event_ids),
            "model_call_ids": list(model_call_ids),
            "status": ChatCorrectionCandidateStatus(status).value,
            "proposal": deepcopy(dict(proposal)) if proposal is not None else None,
            "request": deepcopy(dict(request)),
            "raw_response": raw_response,
            "finish_reason": finish_reason,
            "error_code": error_code,
            "selected_case_id": None,
            "selected_sample_id": None,
        }
        return cls(
            **content,
            digest=sample_digest(content),
            created_at=created_at,
            updated_at=created_at,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            **self.content_for_digest(),
            "digest": self.digest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionCandidate":
        return cls(
            candidate_id=str(payload.get("candidate_id") or ""),
            owner_id=str(payload.get("owner_id") or ""),
            collection_id=str(payload.get("collection_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            challenge_message_id=payload.get("challenge_message_id"),
            answer_message_id=payload.get("answer_message_id"),
            event_ids=tuple(str(item) for item in payload.get("event_ids") or ()),
            model_call_ids=tuple(str(item) for item in payload.get("model_call_ids") or ()),
            status=str(payload.get("status") or ""),
            proposal=dict(payload["proposal"]) if isinstance(payload.get("proposal"), Mapping) else None,
            request=dict(payload.get("request") or {}),
            raw_response=payload.get("raw_response"),
            finish_reason=payload.get("finish_reason"),
            error_code=payload.get("error_code"),
            selected_case_id=payload.get("selected_case_id"),
            selected_sample_id=payload.get("selected_sample_id"),
            digest=str(payload.get("digest") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


__all__ = ["ChatCorrectionCandidate", "ChatCorrectionCandidateStatus"]
