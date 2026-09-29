"""Frozen, model-facing exports for maintained feedback datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Literal

from domain.feedback.sample_revision import (
    RevisionContent,
    SftRevisionContent,
    content_digest_for,
)


EXPORT_SCHEMA_VERSION = "literature-sft.v1"
ExportFormat = Literal["json", "jsonl", "provenance"]


@dataclass(frozen=True)
class ExportMember:
    """One confirmed immutable revision selected by a preview."""

    sample_id: str
    source_case_id: str
    revision_id: str
    revision_no: int
    content: RevisionContent
    content_digest: str
    input_digest: str
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.sample_id or not self.source_case_id or not self.revision_id:
            raise ValueError("export member identity is required")
        if self.revision_no < 1:
            raise ValueError("export member revision number must be positive")
        if not isinstance(self.content, SftRevisionContent):
            raise ValueError("unsupported export member content")
        if not _is_sha256(self.content_digest) or not _is_sha256(self.input_digest):
            raise ValueError("export member digests must be sha256")
        if not isinstance(self.provenance, dict):
            raise ValueError("export member provenance must be an object")
        if self.content_digest != content_digest_for(self.content):
            raise ValueError("export member content digest does not match content")
        object.__setattr__(self, "provenance", _copy(self.provenance))

    @property
    def row_key(self) -> str:
        return sha256(
            f"{self.sample_id}:{self.revision_id}".encode("utf-8")
        ).hexdigest()

    def to_record(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source_case_id": self.source_case_id,
            "revision_id": self.revision_id,
            "revision_no": self.revision_no,
            "content": self.content.to_record(),
            "content_digest": self.content_digest,
            "input_digest": self.input_digest,
            "provenance": _copy(self.provenance),
            "row_key": self.row_key,
        }


@dataclass(frozen=True)
class ExportIssue:
    sample_id: str
    revision_id: str | None
    code: str
    message: str
    question: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "revision_id": self.revision_id,
            "code": self.code,
            "message": self.message,
            "question": self.question,
        }


@dataclass(frozen=True)
class ExportPreview:
    preview_id: str
    dataset_id: str
    members: tuple[ExportMember, ...]
    issues: tuple[ExportIssue, ...]
    preview_digest: str
    created_at: str
    expires_at: str

    @property
    def requested_count(self) -> int:
        return len(self.members)

    @property
    def exportable_count(self) -> int:
        invalid = {issue.sample_id for issue in self.issues}
        return sum(member.sample_id not in invalid for member in self.members)

    @classmethod
    def build(
        cls,
        *,
        preview_id: str,
        dataset_id: str,
        members: tuple[ExportMember, ...],
        issues: tuple[ExportIssue, ...],
        created_at: str,
        expires_at: str,
    ) -> "ExportPreview":
        digest_basis = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "members": [member.to_record() for member in members],
            "issues": [issue.to_record() for issue in issues],
        }
        return cls(
            preview_id=preview_id,
            dataset_id=dataset_id,
            members=members,
            issues=issues,
            preview_digest=_digest(digest_basis),
            created_at=created_at,
            expires_at=expires_at,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "dataset_id": self.dataset_id,
            "requested_count": self.requested_count,
            "exportable_count": self.exportable_count,
            "issues": [issue.to_record() for issue in self.issues],
            "members": [member.to_record() for member in self.members],
            "preview_digest": self.preview_digest,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class DatasetExport:
    """An immutable published export and its traceability sidecar."""

    export_id: str
    dataset_id: str
    export_no: int
    schema_version: str
    rows: tuple[dict[str, Any], ...]
    provenance: tuple[dict[str, Any], ...]
    members: tuple[ExportMember, ...]
    preview_id: str
    preview_digest: str
    member_digest: str
    content_digest: str
    provenance_digest: str
    manifest_digest: str
    manifest: dict[str, Any]
    created_by: str
    idempotency_key: str
    created_at: str

    def __post_init__(self) -> None:
        if not self.export_id or not self.dataset_id or not self.preview_id:
            raise ValueError("export identity is required")
        if self.export_no < 1:
            raise ValueError("export number must be positive")
        if self.schema_version != EXPORT_SCHEMA_VERSION:
            raise ValueError("unsupported export schema version")
        for digest in (
            self.preview_digest,
            self.member_digest,
            self.content_digest,
            self.provenance_digest,
            self.manifest_digest,
        ):
            if not _is_sha256(digest):
                raise ValueError("export digests must be sha256")
        if len(self.rows) != len(self.provenance) or len(self.rows) != len(self.members):
            raise ValueError("export rows and provenance must have equal length")
        if self.content_digest != content_digest_for_rows(self.rows):
            raise ValueError("export content digest does not match rows")
        if self.provenance_digest != provenance_digest_for_rows(self.provenance):
            raise ValueError("export provenance digest does not match provenance")
        if self.manifest_digest != digest_for_value(self.manifest):
            raise ValueError("export manifest digest does not match manifest")
        object.__setattr__(self, "rows", tuple(_copy(row) for row in self.rows))
        object.__setattr__(self, "provenance", tuple(_copy(row) for row in self.provenance))
        object.__setattr__(self, "manifest", _copy(self.manifest))

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_record(self) -> dict[str, Any]:
        return {
            "export_id": self.export_id,
            "dataset_id": self.dataset_id,
            "export_no": self.export_no,
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "content_digest": self.content_digest,
            "provenance_digest": self.provenance_digest,
            "manifest_digest": self.manifest_digest,
            "manifest": _copy(self.manifest),
            "preview_id": self.preview_id,
            "preview_digest": self.preview_digest,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


def member_digest(members: tuple[ExportMember, ...]) -> str:
    basis = [
        {
            "sample_id": member.sample_id,
            "source_case_id": member.source_case_id,
            "revision_id": member.revision_id,
            "revision_no": member.revision_no,
            "content_digest": member.content_digest,
            "input_digest": member.input_digest,
            "provenance": member.provenance,
        }
        for member in sorted(members, key=lambda item: item.row_key)
    ]
    return _digest(basis)


def content_digest_for_rows(rows: tuple[dict[str, Any], ...]) -> str:
    return sha256(jsonl_bytes_for_rows(rows)).hexdigest()


def jsonl_bytes_for_rows(rows: tuple[dict[str, Any], ...]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for row in rows
    )


def provenance_digest_for_rows(provenance: tuple[dict[str, Any], ...]) -> str:
    return _digest(list(provenance))


def digest_for_value(value: Any) -> str:
    """Return the canonical digest used for persisted export metadata."""

    return _digest(value)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "EXPORT_SCHEMA_VERSION",
    "DatasetExport",
    "ExportFormat",
    "ExportIssue",
    "ExportMember",
    "ExportPreview",
    "content_digest_for_rows",
    "digest_for_value",
    "jsonl_bytes_for_rows",
    "member_digest",
    "provenance_digest_for_rows",
]
