"""Dataset sample identity, confirmation rules, and allowed actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

DatasetSampleStatus = Literal[
    "pending",
    "building",
    "needs_confirmation",
    "needs_input",
    "confirmed",
    "discarded",
    "build_failed",
]
SampleAction = Literal["rebuild", "retry", "discard", "restore"]

_ALLOWED_ACTIONS: dict[DatasetSampleStatus, frozenset[SampleAction]] = {
    "pending": frozenset({"discard"}),
    "building": frozenset({"discard"}),
    "needs_confirmation": frozenset({"rebuild", "discard"}),
    "needs_input": frozenset({"rebuild", "discard"}),
    "build_failed": frozenset({"retry", "discard"}),
    "confirmed": frozenset({"rebuild", "discard"}),
    "discarded": frozenset({"restore"}),
}


def ensure_action_allowed(status: DatasetSampleStatus, action: SampleAction) -> None:
    if action not in _ALLOWED_ACTIONS.get(status, frozenset()):
        raise ValueError("sample_action_not_allowed")


@dataclass(frozen=True)
class DatasetSample:
    """Public identity shared by all task-specific revision contents."""

    sample_id: str
    dataset_id: str
    source_case_id: str
    status: DatasetSampleStatus
    current_revision_id: str | None
    confirmed_revision_id: str | None
    generation: int
    source_digest: str
    active_job_id: str | None
    missing_reasons: tuple[str, ...]
    created_at: str
    updated_at: str
    confirmed_by: str | None = None
    confirmed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.sample_id or not self.dataset_id or not self.source_case_id:
            raise ValueError("dataset sample identity is required")
        if self.status not in {
            "pending",
            "building",
            "needs_confirmation",
            "needs_input",
            "confirmed",
            "discarded",
            "build_failed",
        }:
            raise ValueError("invalid dataset sample status")
        if self.generation < 1:
            raise ValueError("sample generation must be positive")
        if not _is_sha256(self.source_digest):
            raise ValueError("sample source digest must be sha256")
        if self.status in {"pending", "building"} and not self.active_job_id:
            raise ValueError("building sample must reference its active job")
        if self.confirmed_revision_id and not self.current_revision_id:
            raise ValueError("confirmed revision requires a current revision")
        if self.confirmed_revision_id and (not self.confirmed_by or not self.confirmed_at):
            raise ValueError("confirmed revision requires confirmation audit")
        if self.status == "confirmed" and not self.confirmed_revision_id:
            raise ValueError("confirmed sample requires a confirmed revision")
        if self.status != "confirmed" and (self.confirmed_by or self.confirmed_at):
            raise ValueError("unconfirmed sample cannot have confirmation audit")
        reasons = tuple(dict.fromkeys(str(item).strip() for item in self.missing_reasons if str(item).strip()))
        object.__setattr__(self, "missing_reasons", reasons)

    @classmethod
    def pending(
        cls,
        *,
        sample_id: str,
        dataset_id: str,
        source_case_id: str,
        source_digest: str,
        active_job_id: str,
        now: str,
    ) -> "DatasetSample":
        return cls(
            sample_id=sample_id,
            dataset_id=dataset_id,
            source_case_id=source_case_id,
            status="pending",
            current_revision_id=None,
            confirmed_revision_id=None,
            generation=1,
            source_digest=source_digest,
            active_job_id=active_job_id,
            missing_reasons=(),
            created_at=now,
            updated_at=now,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "dataset_id": self.dataset_id,
            "source_case_id": self.source_case_id,
            "status": self.status,
            "current_revision_id": self.current_revision_id,
            "confirmed_revision_id": self.confirmed_revision_id,
            "generation": self.generation,
            "source_digest": self.source_digest,
            "active_job_id": self.active_job_id,
            "missing_reasons": list(self.missing_reasons),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
        }


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "DatasetSample",
    "DatasetSampleStatus",
    "SampleAction",
    "ensure_action_allowed",
]
