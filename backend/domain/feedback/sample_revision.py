"""Immutable task-specific content revisions for feedback dataset samples."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Literal, Mapping


SFT_SCHEMA_VERSION = "literature-sft.v1"
RevisionAuthorKind = Literal["worker", "human"]

_MESSAGE_ROLES = frozenset({"system", "user", "assistant"})
_MODEL_CONTENT_KEYS = frozenset({"document_title", "text"})
_INTERNAL_CONTENT_KEYS = frozenset(
    {
        "case_id",
        "dataset_id",
        "message_id",
        "session_id",
        "source_ref",
        "source_refs",
        "locator",
        "page",
        "heading_path",
        "block_id",
    }
)


@dataclass(frozen=True)
class SftRevisionContent:
    """Model-readable SFT input and a candidate target.

    Source and message identities deliberately do not appear in ``context`` or
    ``evidence``.  They belong to the revision provenance stored by the
    workbench and exported separately from the training file.
    """

    schema_version: Literal["literature-sft.v1"]
    messages: tuple[dict[str, str], ...]
    context: tuple[dict[str, str], ...]
    target: str
    evidence: tuple[dict[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != SFT_SCHEMA_VERSION:
            raise ValueError("unsupported SFT schema version")
        messages = tuple(_message(item) for item in self.messages)
        if not messages or not any(item["role"] == "user" for item in messages):
            raise ValueError("SFT content requires a user message")
        context = tuple(_model_text(item) for item in self.context)
        evidence = tuple(_model_text(item) for item in self.evidence)
        if not context:
            raise ValueError("SFT content requires readable context")
        if not evidence:
            raise ValueError("SFT content requires readable evidence")
        target = str(self.target or "").strip()
        if not target:
            raise ValueError("SFT content requires a target")
        if len(target) > 100_000:
            raise ValueError("SFT target is too long")
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "target", target)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SftRevisionContent":
        if not isinstance(value, Mapping):
            raise ValueError("SFT content must be an object")
        return cls(
            schema_version=str(value.get("schema_version") or ""),  # type: ignore[arg-type]
            messages=tuple(value.get("messages") or ()),
            context=tuple(value.get("context") or ()),
            target=str(value.get("target") or ""),
            evidence=tuple(value.get("evidence") or ()),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "messages": [dict(item) for item in self.messages],
            "context": [dict(item) for item in self.context],
            "target": self.target,
            "evidence": [dict(item) for item in self.evidence],
        }


RevisionContent = SftRevisionContent


@dataclass(frozen=True)
class SampleRevision:
    """An immutable worker or human version of one dataset sample."""

    revision_id: str
    sample_id: str
    revision_no: int
    author_kind: RevisionAuthorKind
    content: RevisionContent
    content_digest: str
    input_digest: str
    construction_spec_version: int
    provenance: dict[str, Any]
    created_at: str
    created_by: str | None = None
    job_id: str | None = None

    def __post_init__(self) -> None:
        if not self.revision_id or not self.sample_id:
            raise ValueError("revision identity is required")
        if self.revision_no < 1:
            raise ValueError("revision number must be positive")
        if self.author_kind not in {"worker", "human"}:
            raise ValueError("invalid revision author kind")
        if self.construction_spec_version < 1:
            raise ValueError("construction spec version must be positive")
        if not _is_sha256(self.content_digest) or not _is_sha256(self.input_digest):
            raise ValueError("revision digests must be sha256")
        if self.content_digest != content_digest_for(self.content):
            raise ValueError("revision content digest does not match content")
        if not isinstance(self.provenance, dict):
            raise ValueError("revision provenance must be an object")
        object.__setattr__(self, "provenance", _copy_mapping(self.provenance))

    @classmethod
    def build_worker(
        cls,
        *,
        revision_id: str,
        sample_id: str,
        revision_no: int,
        content: RevisionContent,
        input_digest: str,
        construction_spec_version: int,
        provenance: dict[str, Any],
        created_at: str,
        job_id: str,
    ) -> "SampleRevision":
        return cls(
            revision_id=revision_id,
            sample_id=sample_id,
            revision_no=revision_no,
            author_kind="worker",
            content=content,
            content_digest=content_digest_for(content),
            input_digest=input_digest,
            construction_spec_version=construction_spec_version,
            provenance=provenance,
            created_at=created_at,
            job_id=job_id,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "sample_id": self.sample_id,
            "revision_no": self.revision_no,
            "author_kind": self.author_kind,
            "content": self.content.to_record(),
            "content_digest": self.content_digest,
            "input_digest": self.input_digest,
            "construction_spec_version": self.construction_spec_version,
            "provenance": _copy_mapping(self.provenance),
            "created_at": self.created_at,
            "created_by": self.created_by,
            "job_id": self.job_id,
        }


def content_digest_for(content: RevisionContent) -> str:
    payload = content.to_record()
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def parse_revision_content(value: Mapping[str, Any]) -> RevisionContent:
    schema_version = str(value.get("schema_version") or "")
    if schema_version == SFT_SCHEMA_VERSION:
        return SftRevisionContent.from_mapping(value)
    raise ValueError("unsupported sample revision schema")


def _message(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("SFT messages must be objects")
    keys = set(value)
    if keys - {"role", "content"}:
        raise ValueError("SFT message contains unsupported fields")
    role = str(value.get("role") or "").strip()
    content = str(value.get("content") or "").strip()
    if role not in _MESSAGE_ROLES or not content:
        raise ValueError("SFT messages require a valid role and content")
    return {"role": role, "content": content}


def _model_text(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("SFT context/evidence items must be objects")
    keys = {str(key) for key in value}
    if keys & _INTERNAL_CONTENT_KEYS:
        raise ValueError("SFT model content cannot contain provenance fields")
    if keys - _MODEL_CONTENT_KEYS:
        raise ValueError("SFT context/evidence contains unsupported fields")
    title = str(value.get("document_title") or "").strip()
    text = str(value.get("text") or "").strip()
    if not title or not text:
        raise ValueError("SFT context/evidence requires a title and text")
    return {"document_title": title, "text": text}


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False))


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "RevisionAuthorKind",
    "RevisionContent",
    "SFT_SCHEMA_VERSION",
    "SampleRevision",
    "SftRevisionContent",
    "content_digest_for",
    "parse_revision_content",
]
