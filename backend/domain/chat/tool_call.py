"""Auditable capability calls, approvals, and structured results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Mapping

from domain.chat.resource_ref import ChatResourceRef


class ToolRisk(StrEnum):
    UNKNOWN = "unknown"
    READ = "read"
    DRAFT = "draft"
    WRITE = "write"


class ToolCallStatus(StrEnum):
    REQUESTED = "requested"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class ToolResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    QUEUED = "queued"
    FAILED = "failed"


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _arguments(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = deepcopy(dict(value))
    try:
        json.dumps(copied, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("tool arguments must be JSON serializable") from exc
    return copied


def tool_arguments_digest(arguments: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _arguments(arguments),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _timestamp(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    return text


@dataclass(frozen=True)
class ChatToolResult:
    tool_call_id: str
    status: ToolResultStatus | str
    data: Mapping[str, Any] = field(default_factory=dict)
    resource_refs: tuple[ChatResourceRef, ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tool_call_id", _required_text(self.tool_call_id, "tool_call_id")
        )
        object.__setattr__(self, "status", ToolResultStatus(self.status))
        object.__setattr__(self, "data", deepcopy(dict(self.data)))
        object.__setattr__(self, "resource_refs", tuple(self.resource_refs))
        object.__setattr__(
            self,
            "warnings",
            tuple(str(item).strip() for item in self.warnings if str(item).strip()),
        )
        if self.status is ToolResultStatus.FAILED:
            if not str(self.error_code or "").strip():
                raise ValueError("failed tool result requires error_code")
            if not str(self.error_message or "").strip():
                raise ValueError("failed tool result requires error_message")
        elif self.error_code is not None or self.error_message is not None:
            raise ValueError("successful tool result cannot contain an error")
        if self.status is ToolResultStatus.QUEUED and not self.resource_refs:
            raise ValueError("queued tool result requires a resource reference")

    def for_call(self, tool_call_id: str) -> "ChatToolResult":
        return replace(self, tool_call_id=tool_call_id)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatToolResult":
        return cls(
            tool_call_id=str(payload.get("tool_call_id") or ""),
            status=str(payload.get("status") or ""),
            data=(
                dict(payload["data"])
                if isinstance(payload.get("data"), Mapping)
                else {}
            ),
            resource_refs=tuple(
                ChatResourceRef.from_mapping(item)
                for item in payload.get("resource_refs") or ()
                if isinstance(item, Mapping)
            ),
            warnings=tuple(str(item) for item in payload.get("warnings") or ()),
            error_code=(
                str(payload["error_code"])
                if payload.get("error_code") is not None
                else None
            ),
            error_message=(
                str(payload["error_message"])
                if payload.get("error_message") is not None
                else None
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "status": self.status.value,
            "data": deepcopy(dict(self.data)),
            "resource_refs": [item.to_record() for item in self.resource_refs],
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class ChatToolCall:
    tool_call_id: str
    session_id: str
    assistant_message_id: str
    name: str
    arguments: Mapping[str, Any]
    arguments_digest: str
    risk: ToolRisk | str
    status: ToolCallStatus | str = ToolCallStatus.REQUESTED
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    decision_user_id: str | None = None
    decision_arguments_digest: str | None = None
    decided_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "tool_call_id",
            "session_id",
            "assistant_message_id",
            "name",
        ):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        copied_arguments = _arguments(self.arguments)
        object.__setattr__(self, "arguments", copied_arguments)
        if self.arguments_digest != tool_arguments_digest(copied_arguments):
            raise ValueError("tool call arguments digest does not match arguments")
        object.__setattr__(self, "risk", ToolRisk(self.risk))
        object.__setattr__(self, "status", ToolCallStatus(self.status))
        if (
            self.status is ToolCallStatus.APPROVAL_REQUIRED
            and self.risk is not ToolRisk.WRITE
        ):
            raise ValueError("only write tool calls can require approval")
        decision_values = (
            self.decision_user_id,
            self.decision_arguments_digest,
            self.decided_at,
        )
        if any(value is not None for value in decision_values) and not all(
            value is not None for value in decision_values
        ):
            raise ValueError("tool call decision fields must be recorded together")
        if self.decision_arguments_digest is not None and (
            self.decision_arguments_digest != self.arguments_digest
        ):
            raise ValueError("tool call decision arguments digest does not match arguments")
        if self.status is ToolCallStatus.APPROVED:
            if self.risk is not ToolRisk.WRITE or not all(decision_values):
                raise ValueError("approved write tool call requires an exact user decision")
        if self.status is ToolCallStatus.RUNNING and not self.started_at:
            raise ValueError("running tool call requires started_at")
        if (
            self.risk is ToolRisk.WRITE
            and self.status in {ToolCallStatus.RUNNING, ToolCallStatus.SUCCEEDED}
            and not all(decision_values)
        ):
            raise ValueError("write tool call cannot execute without approval")
        if self.status is ToolCallStatus.SUCCEEDED and (
            not self.started_at or not self.finished_at
        ):
            raise ValueError("invalid tool call transition: requested -> succeeded")
        if self.status in {ToolCallStatus.FAILED, ToolCallStatus.REJECTED}:
            if not self.finished_at or not self.error_code:
                raise ValueError("terminal tool call requires finished_at and error_code")

    @classmethod
    def requested(
        cls,
        *,
        tool_call_id: str,
        session_id: str,
        assistant_message_id: str,
        name: str,
        arguments: Mapping[str, Any],
        risk: ToolRisk,
    ) -> "ChatToolCall":
        copied_arguments = _arguments(arguments)
        return cls(
            tool_call_id=tool_call_id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            name=name,
            arguments=copied_arguments,
            arguments_digest=tool_arguments_digest(copied_arguments),
            risk=risk,
        )

    def require_approval(self) -> "ChatToolCall":
        if self.status is not ToolCallStatus.REQUESTED or self.risk is not ToolRisk.WRITE:
            raise ValueError("only a requested write tool call can require approval")
        return replace(self, status=ToolCallStatus.APPROVAL_REQUIRED)

    def approve(
        self,
        *,
        user_id: str,
        arguments_digest: str,
        decided_at: str,
    ) -> "ChatToolCall":
        if self.status is not ToolCallStatus.APPROVAL_REQUIRED:
            raise ValueError(f"cannot approve tool call in status {self.status.value}")
        if arguments_digest != self.arguments_digest:
            raise ValueError("approval arguments digest does not match stored arguments")
        return replace(
            self,
            status=ToolCallStatus.APPROVED,
            decision_user_id=_required_text(user_id, "user_id"),
            decision_arguments_digest=arguments_digest,
            decided_at=_timestamp(decided_at, "decided_at"),
        )

    def reject(
        self,
        *,
        user_id: str,
        arguments_digest: str,
        decided_at: str,
    ) -> "ChatToolCall":
        if self.status is not ToolCallStatus.APPROVAL_REQUIRED:
            raise ValueError(f"cannot reject tool call in status {self.status.value}")
        if arguments_digest != self.arguments_digest:
            raise ValueError("rejection arguments digest does not match stored arguments")
        decision_time = _timestamp(decided_at, "decided_at")
        return replace(
            self,
            status=ToolCallStatus.REJECTED,
            decision_user_id=_required_text(user_id, "user_id"),
            decision_arguments_digest=arguments_digest,
            decided_at=decision_time,
            finished_at=decision_time,
            error_code="user_rejected",
        )

    def start(self, started_at: str) -> "ChatToolCall":
        expected_status = (
            ToolCallStatus.APPROVED
            if self.risk is ToolRisk.WRITE
            else ToolCallStatus.REQUESTED
        )
        if self.status is not expected_status:
            raise ValueError(f"cannot start tool call in status {self.status.value}")
        return replace(
            self,
            status=ToolCallStatus.RUNNING,
            started_at=_required_text(started_at, "started_at"),
        )

    def succeed(self, finished_at: str) -> "ChatToolCall":
        if self.status is not ToolCallStatus.RUNNING:
            raise ValueError(f"cannot succeed tool call in status {self.status.value}")
        return replace(
            self,
            status=ToolCallStatus.SUCCEEDED,
            finished_at=_required_text(finished_at, "finished_at"),
        )

    def fail(self, error_code: str, finished_at: str) -> "ChatToolCall":
        if self.status not in {
            ToolCallStatus.REQUESTED,
            ToolCallStatus.APPROVED,
            ToolCallStatus.RUNNING,
        }:
            raise ValueError(f"cannot fail tool call in status {self.status.value}")
        return replace(
            self,
            status=ToolCallStatus.FAILED,
            error_code=_required_text(error_code, "error_code"),
            finished_at=_required_text(finished_at, "finished_at"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatToolCall":
        return cls(
            tool_call_id=str(payload.get("tool_call_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            assistant_message_id=str(payload.get("assistant_message_id") or ""),
            name=str(payload.get("name") or ""),
            arguments=(
                dict(payload["arguments"])
                if isinstance(payload.get("arguments"), Mapping)
                else {}
            ),
            arguments_digest=str(payload.get("arguments_digest") or ""),
            risk=str(payload.get("risk") or ToolRisk.UNKNOWN.value),
            status=str(payload.get("status") or ToolCallStatus.REQUESTED.value),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            error_code=payload.get("error_code"),
            decision_user_id=payload.get("decision_user_id"),
            decision_arguments_digest=payload.get("decision_arguments_digest"),
            decided_at=payload.get("decided_at"),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "session_id": self.session_id,
            "assistant_message_id": self.assistant_message_id,
            "name": self.name,
            "arguments": deepcopy(dict(self.arguments)),
            "arguments_digest": self.arguments_digest,
            "risk": self.risk.value,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_code": self.error_code,
            "decision_user_id": self.decision_user_id,
            "decision_arguments_digest": self.decision_arguments_digest,
            "decided_at": self.decided_at,
        }


__all__ = [
    "ChatToolCall",
    "ChatToolResult",
    "ToolCallStatus",
    "ToolResultStatus",
    "ToolRisk",
    "tool_arguments_digest",
]
