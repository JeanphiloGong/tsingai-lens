"""Explicit links between a Chat answer, a user challenge, and a correction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping


class ChatCorrectionCaseStatus(StrEnum):
    LINKED = "linked"
    UNRESOLVED = "unresolved"


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _timestamp(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    return text


@dataclass(frozen=True)
class ChatCorrectionCase:
    """A durable reference to one explicitly selected correction sequence.

    The case owns no copy of the conversation. Its message and model-call IDs
    point back to the append-only Chat trajectory and the exact P1 captures.
    """

    case_id: str
    session_id: str
    original_message_id: str
    feedback_message_id: str
    corrected_message_id: str | None
    original_model_call_id: str
    corrected_model_call_id: str | None
    status: ChatCorrectionCaseStatus | str
    trace_digest: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "case_id",
            "session_id",
            "original_message_id",
            "feedback_message_id",
            "original_model_call_id",
            "trace_digest",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        for field_name in ("corrected_message_id", "corrected_model_call_id"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, value.strip() if isinstance(value, str) and value.strip() else None)
        status = ChatCorrectionCaseStatus(self.status)
        object.__setattr__(self, "status", status)
        if len(self.trace_digest) != 64:
            raise ValueError("trace_digest must be a SHA-256 hex digest")
        try:
            int(self.trace_digest, 16)
        except ValueError as exc:
            raise ValueError("trace_digest must be a SHA-256 hex digest") from exc
        if status is ChatCorrectionCaseStatus.LINKED:
            if not self.corrected_message_id or not self.corrected_model_call_id:
                raise ValueError("linked correction cases require a corrected answer")
        elif self.corrected_message_id or self.corrected_model_call_id:
            raise ValueError("unresolved correction cases cannot carry a correction")
        created_at = _timestamp(self.created_at, "created_at")
        updated_at = _timestamp(self.updated_at, "updated_at")
        if datetime.fromisoformat(updated_at.replace("Z", "+00:00")) < datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        ):
            raise ValueError("updated_at cannot be before created_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)

    @property
    def model_call_ids(self) -> tuple[str, ...]:
        return tuple(
            call_id
            for call_id in (self.original_model_call_id, self.corrected_model_call_id)
            if call_id
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionCase":
        return cls(
            case_id=str(payload.get("case_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            original_message_id=str(payload.get("original_message_id") or ""),
            feedback_message_id=str(payload.get("feedback_message_id") or ""),
            corrected_message_id=payload.get("corrected_message_id"),
            original_model_call_id=str(payload.get("original_model_call_id") or ""),
            corrected_model_call_id=payload.get("corrected_model_call_id"),
            status=str(payload.get("status") or ""),
            trace_digest=str(payload.get("trace_digest") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "original_message_id": self.original_message_id,
            "feedback_message_id": self.feedback_message_id,
            "corrected_message_id": self.corrected_message_id,
            "original_model_call_id": self.original_model_call_id,
            "corrected_model_call_id": self.corrected_model_call_id,
            "status": self.status.value,
            "trace_digest": self.trace_digest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


__all__ = ["ChatCorrectionCase", "ChatCorrectionCaseStatus"]
