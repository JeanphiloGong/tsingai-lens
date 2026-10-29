"""Auditable capability calls, approvals, and structured results."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
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






def tool_arguments_digest(arguments: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        arguments,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()




@dataclass(frozen=True)
class ChatToolResult:
    tool_call_id: str
    status: ToolResultStatus
    data: Mapping[str, Any] = field(default_factory=dict)
    resource_refs: tuple[ChatResourceRef, ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.status is ToolResultStatus.FAILED:
            if not self.error_code:
                raise ValueError("failed tool result requires error_code")
            if not self.error_message:
                raise ValueError("failed tool result requires error_message")
        elif self.error_code is not None or self.error_message is not None:
            raise ValueError("successful tool result cannot contain an error")
        if self.status is ToolResultStatus.QUEUED and not self.resource_refs:
            raise ValueError("queued tool result requires a resource reference")

    def for_call(self, tool_call_id: str) -> "ChatToolResult":
        return replace(self, tool_call_id=tool_call_id)

@dataclass(frozen=True)
class ChatToolCall:
    tool_call_id: str
    session_id: str
    assistant_message_id: str
    name: str
    arguments: Mapping[str, Any]
    arguments_digest: str
    risk: ToolRisk
    position: int = 0
    status: ToolCallStatus = ToolCallStatus.REQUESTED
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    decision_user_id: str | None = None
    decision_arguments_digest: str | None = None
    decided_at: str | None = None
    decision_basis: str = "explicit"
    authorization_revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.position, int) or isinstance(self.position, bool) or self.position < 0:
            raise ValueError("tool call position must be a non-negative integer")
        if self.decision_basis not in {"explicit", "scope_grant"}:
            raise ValueError("invalid decision basis")
        if self.decision_basis == "scope_grant" and (
            self.authorization_revision is None or self.authorization_revision < 1
            or not self.decision_user_id
        ):
            raise ValueError("scope grant requires its revision and authorizing user")
        if self.arguments_digest != tool_arguments_digest(self.arguments):
            raise ValueError("tool call arguments digest does not match arguments")
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
        position: int = 0,
    ) -> "ChatToolCall":
        copied_arguments = deepcopy(arguments)
        return cls(
            tool_call_id=tool_call_id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            name=name,
            arguments=copied_arguments,
            arguments_digest=tool_arguments_digest(copied_arguments),
            risk=risk,
            position=position,
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
            decision_user_id=user_id,
            decision_arguments_digest=arguments_digest,
            decided_at=decided_at,
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
        decision_time = decided_at
        return replace(
            self,
            status=ToolCallStatus.REJECTED,
            decision_user_id=user_id,
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
            started_at=started_at,
        )

    def succeed(self, finished_at: str) -> "ChatToolCall":
        if self.status is not ToolCallStatus.RUNNING:
            raise ValueError(f"cannot succeed tool call in status {self.status.value}")
        return replace(
            self,
            status=ToolCallStatus.SUCCEEDED,
            finished_at=finished_at,
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
            error_code=error_code,
            finished_at=finished_at,
        )

__all__ = [
    "ChatToolCall",
    "ChatToolResult",
    "ToolCallStatus",
    "ToolResultStatus",
    "ToolRisk",
    "tool_arguments_digest",
]
