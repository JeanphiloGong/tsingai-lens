"""Immutable, source-aware snapshots used to review Chat corrections."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Mapping


class ChatCorrectionReviewDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    INSUFFICIENT = "insufficient"
    WITHDRAW = "withdraw"


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


def canonical_json(value: Any) -> str:
    """Return the one JSON representation used for sample provenance."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("correction sample content must be JSON serializable") from exc


def sample_digest(payload: Mapping[str, Any]) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChatCorrectionSample:
    """A frozen view of the exact input, observations, target, and sources."""

    sample_id: str
    case_id: str
    session_id: str
    collection_id: str
    model_call_id: str
    input: dict[str, Any]
    observations: tuple[dict[str, Any], ...]
    target: str
    source_refs: tuple[dict[str, Any], ...]
    digest: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "sample_id",
            "case_id",
            "session_id",
            "collection_id",
            "model_call_id",
            "target",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        copied_input = deepcopy(dict(self.input))
        copied_observations = tuple(deepcopy(dict(item)) for item in self.observations)
        copied_sources = tuple(deepcopy(dict(item)) for item in self.source_refs)
        canonical_json(copied_input)
        canonical_json(copied_observations)
        canonical_json(copied_sources)
        object.__setattr__(self, "input", copied_input)
        object.__setattr__(self, "observations", copied_observations)
        object.__setattr__(self, "source_refs", copied_sources)
        digest = _text(self.digest, "digest").lower()
        if len(digest) != 64:
            raise ValueError("digest must be a SHA-256 hex digest")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("digest must be a SHA-256 hex digest") from exc
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at, "updated_at"))
        if datetime.fromisoformat(self.updated_at.replace("Z", "+00:00")) < datetime.fromisoformat(
            self.created_at.replace("Z", "+00:00")
        ):
            raise ValueError("updated_at cannot be before created_at")

    @property
    def message_ids(self) -> tuple[str, ...]:
        values: list[str] = []
        for observation in self.observations:
            message_id = str(observation.get("message_id") or "").strip()
            if message_id and message_id not in values:
                values.append(message_id)
        return tuple(values)

    def content_for_digest(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "collection_id": self.collection_id,
            "model_call_id": self.model_call_id,
            "input": self.input,
            "observations": list(self.observations),
            "target": self.target,
            "source_refs": list(self.source_refs),
        }

    def validate_digest(self) -> bool:
        return sample_digest(self.content_for_digest()) == self.digest

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionSample":
        return cls(
            sample_id=str(payload.get("sample_id") or ""),
            case_id=str(payload.get("case_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            collection_id=str(payload.get("collection_id") or ""),
            model_call_id=str(payload.get("model_call_id") or ""),
            input=dict(payload.get("input") or {}),
            observations=tuple(dict(item) for item in payload.get("observations") or ()),
            target=str(payload.get("target") or ""),
            source_refs=tuple(dict(item) for item in payload.get("source_refs") or ()),
            digest=str(payload.get("digest") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "case_id": self.case_id,
            "session_id": self.session_id,
            "collection_id": self.collection_id,
            "model_call_id": self.model_call_id,
            "input": deepcopy(self.input),
            "observations": [deepcopy(item) for item in self.observations],
            "target": self.target,
            "source_refs": [deepcopy(item) for item in self.source_refs],
            "digest": self.digest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ChatCorrectionReview:
    """One append-only human decision over a sample digest."""

    review_id: str
    sample_id: str
    session_id: str
    sample_digest: str
    decision: ChatCorrectionReviewDecision | str
    reviewer_id: str
    reason: str | None
    support_message_ids: tuple[str, ...]
    seq: int
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("review_id", "sample_id", "session_id", "sample_digest", "reviewer_id"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        digest = self.sample_digest.lower()
        if len(digest) != 64:
            raise ValueError("sample_digest must be a SHA-256 hex digest")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("sample_digest must be a SHA-256 hex digest") from exc
        object.__setattr__(self, "sample_digest", digest)
        object.__setattr__(self, "decision", ChatCorrectionReviewDecision(self.decision))
        if not isinstance(self.seq, int) or isinstance(self.seq, bool) or self.seq < 0:
            raise ValueError("review sequence must be a non-negative integer")
        reason = _text(self.reason, "reason", required=False) or None
        object.__setattr__(self, "reason", reason)
        support = tuple(dict.fromkeys(_text(item, "support_message_id") for item in self.support_message_ids))
        object.__setattr__(self, "support_message_ids", support)
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionReview":
        return cls(
            review_id=str(payload.get("review_id") or ""),
            sample_id=str(payload.get("sample_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            sample_digest=str(payload.get("sample_digest") or ""),
            decision=str(payload.get("decision") or ""),
            reviewer_id=str(payload.get("reviewer_id") or ""),
            reason=payload.get("reason"),
            support_message_ids=tuple(str(item) for item in payload.get("support_message_ids") or ()),
            seq=int(payload.get("seq") or 0),
            created_at=str(payload.get("created_at") or ""),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "sample_id": self.sample_id,
            "session_id": self.session_id,
            "sample_digest": self.sample_digest,
            "decision": self.decision.value,
            "reviewer_id": self.reviewer_id,
            "reason": self.reason,
            "support_message_ids": list(self.support_message_ids),
            "seq": self.seq,
            "created_at": self.created_at,
        }


__all__ = [
    "ChatCorrectionReview",
    "ChatCorrectionReviewDecision",
    "ChatCorrectionSample",
    "canonical_json",
    "sample_digest",
]
