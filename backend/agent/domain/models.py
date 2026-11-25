"""Immutable Agent execution models and transition rules."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from hashlib import sha256
from typing import Literal


TaskStatus = Literal[
    "accepted",
    "running",
    "approval_required",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
]
OperationStatus = Literal[
    "requested",
    "approval_required",
    "approved",
    "running",
    "succeeded",
    "failed",
    "rejected",
    "needs_reconciliation",
]
StepStatus = Literal["pending", "running", "completed", "blocked"]
Decision = Literal["approved", "rejected"]
ModelCallStatus = Literal["started", "succeeded", "failed"]


def digest_arguments(arguments: dict[str, object]) -> str:
    encoded = json.dumps(
        arguments,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    conversation_id: str
    trigger_message_id: str | None
    status: TaskStatus
    checkpoint_revision: int = 0

    def transition(self, status: TaskStatus) -> AgentTask:
        allowed: dict[TaskStatus, set[TaskStatus]] = {
            "accepted": {"running", "cancelled"},
            "running": {
                "approval_required",
                "completed",
                "failed",
                "interrupted",
                "cancelled",
            },
            "approval_required": {"running", "failed", "cancelled"},
            "interrupted": {"running", "failed", "cancelled"},
            "completed": set(),
            "failed": set(),
            "cancelled": set(),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"invalid Task transition: {self.status} -> {status}")
        return replace(self, status=status)

    def checkpoint(self, revision: int) -> AgentTask:
        if revision != self.checkpoint_revision + 1:
            raise ValueError("checkpoint revision must increase by one")
        return replace(self, checkpoint_revision=revision)


@dataclass(frozen=True)
class Operation:
    operation_id: str
    task_id: str
    name: str
    arguments_digest: str
    status: OperationStatus
    arguments: dict[str, object] = field(default_factory=dict)
    decision_basis: str = "registry"
    tool_call_id: str | None = None
    decision_arguments_digest: str | None = None
    result: dict[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None
    assistant_message_id: str | None = None

    def decide(self, decision: Decision, arguments_digest: str) -> Operation:
        if self.status != "approval_required":
            raise ValueError("operation is not waiting for approval")
        if arguments_digest != self.arguments_digest:
            raise ValueError("operation arguments digest mismatch")
        return replace(
            self,
            status="approved" if decision == "approved" else "rejected",
            decision_arguments_digest=arguments_digest,
        )

    def retry_identity(self) -> str:
        return self.operation_id

    def reconcile(self) -> Operation:
        if self.status not in {"running", "failed"}:
            raise ValueError("only an uncertain execution can be reconciled")
        return replace(self, status="needs_reconciliation")


@dataclass(frozen=True)
class TaskStep:
    step_id: str
    task_id: str
    sequence: int
    name: str
    status: StepStatus
    checkpoint: dict[str, object]


@dataclass(frozen=True)
class ModelCall:
    model_call_id: str
    task_id: str
    sequence: int
    request_digest: str
    status: ModelCallStatus


__all__ = [
    "AgentTask",
    "Decision",
    "ModelCall",
    "ModelCallStatus",
    "Operation",
    "OperationStatus",
    "StepStatus",
    "TaskStatus",
    "TaskStep",
    "digest_arguments",
]
