"""Dataset sample identity, build state, and job identity."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Literal


DATASET_SAMPLE_BUILD_JOB_TYPE = "dataset_sample_build"
DATASET_SAMPLE_BUILD_PAYLOAD_VERSION = 1

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


def sample_action_digest(
    *, action: SampleAction, expected_revision_id: str | None, reason: str | None
) -> str:
    payload = {
        "action": action,
        "expected_revision_id": expected_revision_id,
        "reason": (reason or "").strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


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


def source_digest_for_case(case_record: dict[str, Any]) -> str:
    encoded = json.dumps(
        case_record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def sample_build_idempotency_key(
    *,
    sample_id: str,
    generation: int,
    spec_version: int,
    source_digest: str,
) -> str:
    if generation < 1 or spec_version < 1 or not _is_sha256(source_digest):
        raise ValueError("invalid sample build identity")
    return ":".join(
        (
            DATASET_SAMPLE_BUILD_JOB_TYPE,
            sample_id,
            str(generation),
            str(spec_version),
            source_digest,
        )
    )


def build_job_payload(
    *,
    dataset_id: str,
    sample_id: str,
    generation: int,
    spec_version: int,
    source_digest: str,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "sample_id": sample_id,
        "generation": generation,
        "spec_version": spec_version,
        "source_digest": source_digest,
    }


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "DATASET_SAMPLE_BUILD_JOB_TYPE",
    "DATASET_SAMPLE_BUILD_PAYLOAD_VERSION",
    "DatasetSample",
    "DatasetSampleStatus",
    "SampleAction",
    "build_job_payload",
    "ensure_action_allowed",
    "sample_action_digest",
    "sample_build_idempotency_key",
    "source_digest_for_case",
]
