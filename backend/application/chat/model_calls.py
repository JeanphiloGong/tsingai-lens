"""Provider-call observation contracts shared by the Chat runtime and storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol


ModelCallPurpose = Literal["decision", "compaction", "finalization"]
ModelCallStatus = Literal[
    "recorded",
    "provider_succeeded",
    "provider_failed",
    "response_invalid",
    "cancelled",
]


@dataclass(frozen=True)
class ModelCallInput:
    session_id: str
    trigger_message_id: str | None
    response_message_id: str | None
    purpose: ModelCallPurpose
    request: Mapping[str, Any]


@dataclass(frozen=True)
class ModelCallOutcome:
    status: ModelCallStatus
    finished_at: str
    error_code: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ModelCallObserver(Protocol):
    async def start(self, call: ModelCallInput) -> str: ...

    async def finish(self, call_id: str, outcome: ModelCallOutcome) -> None: ...


__all__ = [
    "ModelCallInput",
    "ModelCallObserver",
    "ModelCallOutcome",
    "ModelCallPurpose",
    "ModelCallStatus",
]
