"""Immutable manifests for source-backed Chat correction datasets."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Mapping

from domain.evaluation.chat_correction_sample import canonical_json, sample_digest


class ChatCorrectionDatasetSplit(StrEnum):
    TRAIN = "train"
    EVAL = "eval"


class ChatCorrectionDatasetExclusionReason(StrEnum):
    INVALID_SAMPLE = "invalid_sample"
    STALE = "stale"
    WITHDRAWN = "withdrawn"
    INSUFFICIENT = "insufficient"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    MISSING_SOURCE = "missing_source"
    MISSING_PAPER_FAMILY = "missing_paper_family"
    PARTITION_CONFLICT = "partition_conflict"
    CONFLICTING_ASSIGNMENT = "conflicting_assignment"


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


def _digest(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    if len(text) != 64:
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    try:
        int(text, 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a SHA-256 hex digest") from exc
    return text


def _copy_json(value: Any, field_name: str) -> Any:
    copied = deepcopy(value)
    try:
        canonical_json(copied)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc
    return copied


@dataclass(frozen=True)
class ChatCorrectionDatasetSelection:
    """One owner-authorized sample and its requested partition."""

    session_id: str
    sample_id: str
    split: ChatCorrectionDatasetSplit | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _required_text(self.session_id, "session_id"))
        object.__setattr__(self, "sample_id", _required_text(self.sample_id, "sample_id"))
        object.__setattr__(self, "split", ChatCorrectionDatasetSplit(self.split))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionDatasetSelection":
        return cls(
            session_id=str(payload.get("session_id") or ""),
            sample_id=str(payload.get("sample_id") or ""),
            split=str(payload.get("split") or ""),
        )

    def to_record(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "sample_id": self.sample_id,
            "split": self.split.value,
        }


@dataclass(frozen=True)
class ChatCorrectionDatasetRow:
    """One accepted, source-backed correction sample in a frozen manifest."""

    row_id: str
    sample_id: str
    case_id: str
    session_id: str
    collection_id: str
    model_call_id: str
    input: dict[str, Any]
    observations: tuple[dict[str, Any], ...]
    target: str
    review_id: str
    review_digest: str
    source_refs: tuple[dict[str, Any], ...]
    paper_families: tuple[dict[str, str], ...]
    session_tree_id: str
    split: ChatCorrectionDatasetSplit | str
    content_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "row_id",
            "sample_id",
            "case_id",
            "session_id",
            "collection_id",
            "model_call_id",
            "target",
            "review_id",
            "session_tree_id",
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        object.__setattr__(self, "review_digest", _digest(self.review_digest, "review_digest"))
        object.__setattr__(self, "content_digest", _digest(self.content_digest, "content_digest"))
        object.__setattr__(self, "split", ChatCorrectionDatasetSplit(self.split))
        copied_input = _copy_json(dict(self.input), "input")
        copied_observations = tuple(_copy_json(dict(item), "observations") for item in self.observations)
        copied_sources = tuple(_copy_json(dict(item), "source_refs") for item in self.source_refs)
        copied_families = tuple(
            {
                "document_id": _required_text(item.get("document_id"), "paper_families.document_id"),
                "family_id": _required_text(item.get("family_id"), "paper_families.family_id"),
            }
            for item in self.paper_families
        )
        object.__setattr__(self, "input", copied_input)
        object.__setattr__(self, "observations", copied_observations)
        object.__setattr__(self, "source_refs", copied_sources)
        object.__setattr__(self, "paper_families", copied_families)
        if self.content_digest != sample_digest(self.content_for_digest()):
            raise ValueError("content_digest does not match the dataset row content")

    def content_for_digest(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "case_id": self.case_id,
            "session_id": self.session_id,
            "collection_id": self.collection_id,
            "model_call_id": self.model_call_id,
            "input": self.input,
            "observations": list(self.observations),
            "target": self.target,
            "review_id": self.review_id,
            "review_digest": self.review_digest,
            "source_refs": list(self.source_refs),
            "paper_families": list(self.paper_families),
            "session_tree_id": self.session_tree_id,
            "split": self.split.value,
        }

    def to_record(self) -> dict[str, Any]:
        return {
            **self.content_for_digest(),
            "row_id": self.row_id,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionDatasetRow":
        return cls(
            row_id=str(payload.get("row_id") or ""),
            sample_id=str(payload.get("sample_id") or ""),
            case_id=str(payload.get("case_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            collection_id=str(payload.get("collection_id") or ""),
            model_call_id=str(payload.get("model_call_id") or ""),
            input=dict(payload.get("input") or {}),
            observations=tuple(dict(item) for item in payload.get("observations") or ()),
            target=str(payload.get("target") or ""),
            review_id=str(payload.get("review_id") or ""),
            review_digest=str(payload.get("review_digest") or ""),
            source_refs=tuple(dict(item) for item in payload.get("source_refs") or ()),
            paper_families=tuple(dict(item) for item in payload.get("paper_families") or ()),
            session_tree_id=str(payload.get("session_tree_id") or ""),
            split=str(payload.get("split") or ""),
            content_digest=str(payload.get("content_digest") or ""),
        )


@dataclass(frozen=True)
class ChatCorrectionDatasetExclusion:
    sample_id: str
    session_id: str
    case_id: str | None
    reason: ChatCorrectionDatasetExclusionReason | str
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _required_text(self.sample_id, "sample_id"))
        object.__setattr__(self, "session_id", _required_text(self.session_id, "session_id"))
        object.__setattr__(self, "case_id", str(self.case_id).strip() if self.case_id else None)
        object.__setattr__(self, "reason", ChatCorrectionDatasetExclusionReason(self.reason))
        object.__setattr__(self, "detail", _required_text(self.detail, "detail"))

    def to_record(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "session_id": self.session_id,
            "case_id": self.case_id,
            "reason": self.reason.value,
            "detail": self.detail,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionDatasetExclusion":
        return cls(
            sample_id=str(payload.get("sample_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            case_id=payload.get("case_id"),
            reason=str(payload.get("reason") or ""),
            detail=str(payload.get("detail") or ""),
        )


@dataclass(frozen=True)
class ChatCorrectionDatasetManifest:
    """A reproducible immutable export and its exclusion report."""

    dataset_id: str
    owner_id: str
    collection_id: str
    provenance: dict[str, Any]
    rows: tuple[ChatCorrectionDatasetRow, ...]
    exclusions: tuple[ChatCorrectionDatasetExclusion, ...]
    digest: str
    created_at: str
    schema_version: str = "chat-correction-dataset.v1"

    def __post_init__(self) -> None:
        for field_name in ("dataset_id", "owner_id", "collection_id", "schema_version"):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        object.__setattr__(self, "provenance", _copy_json(dict(self.provenance), "provenance"))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "exclusions", tuple(self.exclusions))
        object.__setattr__(self, "digest", _digest(self.digest, "digest"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        if self.digest != self.compute_digest():
            raise ValueError("dataset digest does not match the manifest")
        row_ids = [row.row_id for row in self.rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("dataset row IDs must be unique")

    def content_for_digest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "owner_id": self.owner_id,
            "collection_id": self.collection_id,
            "provenance": self.provenance,
            "rows": [row.to_record() for row in sorted(self.rows, key=lambda item: item.sample_id)],
            "exclusions": [
                item.to_record()
                for item in sorted(self.exclusions, key=lambda item: (item.sample_id, item.reason.value, item.detail))
            ],
        }

    def compute_digest(self) -> str:
        return sample_digest(self.content_for_digest())

    @property
    def provenance_digest(self) -> str:
        return sample_digest(self.provenance)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def excluded_count(self) -> int:
        return len(self.exclusions)

    def validate_digest(self) -> bool:
        return self.digest == self.compute_digest()

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "owner_id": self.owner_id,
            "collection_id": self.collection_id,
            "provenance": deepcopy(self.provenance),
            "provenance_digest": self.provenance_digest,
            "rows": [row.to_record() for row in self.rows],
            "exclusions": [item.to_record() for item in self.exclusions],
            "digest": self.digest,
            "created_at": self.created_at,
            "row_count": self.row_count,
            "excluded_count": self.excluded_count,
        }

    @classmethod
    def create(
        cls,
        *,
        owner_id: str,
        collection_id: str,
        provenance: Mapping[str, Any],
        rows: tuple[ChatCorrectionDatasetRow, ...],
        exclusions: tuple[ChatCorrectionDatasetExclusion, ...],
        created_at: str,
    ) -> "ChatCorrectionDatasetManifest":
        content = {
            "schema_version": "chat-correction-dataset.v1",
            "owner_id": owner_id,
            "collection_id": collection_id,
            "provenance": dict(provenance),
            "rows": [row.to_record() for row in sorted(rows, key=lambda item: item.sample_id)],
            "exclusions": [
                item.to_record()
                for item in sorted(exclusions, key=lambda item: (item.sample_id, item.reason.value, item.detail))
            ],
        }
        digest = sample_digest(content)
        return cls(
            dataset_id=f"chat_dataset_{digest[:40]}",
            owner_id=owner_id,
            collection_id=collection_id,
            provenance=dict(provenance),
            rows=rows,
            exclusions=exclusions,
            digest=digest,
            created_at=created_at,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatCorrectionDatasetManifest":
        return cls(
            dataset_id=str(payload.get("dataset_id") or ""),
            owner_id=str(payload.get("owner_id") or ""),
            collection_id=str(payload.get("collection_id") or ""),
            provenance=dict(payload.get("provenance") or {}),
            rows=tuple(ChatCorrectionDatasetRow.from_mapping(item) for item in payload.get("rows") or ()),
            exclusions=tuple(
                ChatCorrectionDatasetExclusion.from_mapping(item)
                for item in payload.get("exclusions") or ()
            ),
            digest=str(payload.get("digest") or ""),
            created_at=str(payload.get("created_at") or ""),
            schema_version=str(payload.get("schema_version") or "chat-correction-dataset.v1"),
        )


__all__ = [
    "ChatCorrectionDatasetExclusion",
    "ChatCorrectionDatasetExclusionReason",
    "ChatCorrectionDatasetManifest",
    "ChatCorrectionDatasetRow",
    "ChatCorrectionDatasetSelection",
    "ChatCorrectionDatasetSplit",
]
