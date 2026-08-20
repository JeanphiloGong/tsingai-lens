"""Durable identity and ownership for one Chat session."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping


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
class ChatSession:
    session_id: str
    user_id: str
    collection_id: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in ("session_id", "user_id", "collection_id"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        created_at = _timestamp(self.created_at, "created_at")
        updated_at = _timestamp(self.updated_at, "updated_at")
        if datetime.fromisoformat(updated_at.replace("Z", "+00:00")) < datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        ):
            raise ValueError("updated_at cannot be before created_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        user_id: str,
        collection_id: str,
        created_at: str,
    ) -> "ChatSession":
        return cls(
            session_id=session_id,
            user_id=user_id,
            collection_id=collection_id,
            created_at=created_at,
            updated_at=created_at,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatSession":
        return cls(
            session_id=str(payload.get("session_id") or ""),
            user_id=str(payload.get("user_id") or ""),
            collection_id=str(payload.get("collection_id") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )

    def update(
        self,
        *,
        user_id: str,
        collection_id: str,
        updated_at: str,
    ) -> "ChatSession":
        if user_id != self.user_id or collection_id != self.collection_id:
            raise ValueError("session identity cannot be reassigned")
        return replace(self, updated_at=updated_at)

    def to_record(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "collection_id": self.collection_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


__all__ = ["ChatSession"]
