"""Immutable task-specific content revisions for feedback dataset samples."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Literal, TypeAlias


SFT_SCHEMA_VERSION = "literature-sft.v1"
PREFERENCE_SCHEMA_VERSION = "literature-preference.v1"
EVALUATION_SCHEMA_VERSION = "literature-evaluation.v1"
RevisionAuthorKind = Literal["worker", "human"]
PreferenceChoice = Literal["a", "b", "tie", "unclear"]
EvaluationMode = Literal["reference", "rubric"]

# Model-facing rows contain readable paper text, while source/message identities
# belong to revision provenance. Providers can copy an identity from the
# question despite the prompt prohibiting it, so enforce the boundary here.
_INTERNAL_REFERENCE = re.compile(
    r"(?i)(?:`?(?:blk|tbl)_doc_[a-z0-9_]+`?|`?(?:doc|msg|call|case|session|feedback|source_ref|analysis|job)_[a-z0-9_-]+`?)"
)
_SOURCE_CITATION = re.compile(
    r"(?i)[(（]\s*(?:source|来源)\s*[:：]?\s*`?(?:blk|tbl)_doc_[a-z0-9_]+`?\s*[)）]"
)


def strip_internal_references(value: str | None) -> str:
    """Remove internal identities from text exported to a model."""

    text = (value or "").strip()
    text = _SOURCE_CITATION.sub("", text)
    text = _INTERNAL_REFERENCE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([，。；：、,.])", r"\1", text)
    return text.strip()


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
        if not any(item["role"] == "user" for item in self.messages):
            raise ValueError("SFT content requires a user message")
        if not self.target.strip():
            raise ValueError("SFT content requires a target")


@dataclass(frozen=True)
class PreferenceRevisionContent:
    """Two responses to one fixed input and a separately recorded label."""

    schema_version: Literal["literature-preference.v1"]
    messages: tuple[dict[str, str], ...]
    context: tuple[dict[str, str], ...]
    response_a: str
    response_b: str
    suggested_preference: PreferenceChoice | None
    rationale: str
    evidence: tuple[dict[str, str], ...]
    human_preference: PreferenceChoice | None = None

    def __post_init__(self) -> None:
        if not any(item["role"] == "user" for item in self.messages):
            raise ValueError("preference content requires a user message")
        if not self.response_a.strip() or not self.response_b.strip():
            raise ValueError("preference content requires both responses")
        if self.response_a == self.response_b:
            raise ValueError("preference responses must differ")


@dataclass(frozen=True)
class EvaluationRevisionContent:
    """A test input with a reference answer or an explicit rubric."""

    schema_version: Literal["literature-evaluation.v1"]
    messages: tuple[dict[str, str], ...]
    context: tuple[dict[str, str], ...]
    reference: str
    criteria: tuple[str, ...]
    evaluation_mode: EvaluationMode
    evidence: tuple[dict[str, str], ...]

    def __post_init__(self) -> None:
        if not any(item["role"] == "user" for item in self.messages):
            raise ValueError("evaluation content requires a user message")
        if not self.criteria:
            raise ValueError("evaluation content requires criteria")
        if self.evaluation_mode == "reference" and not self.reference.strip():
            raise ValueError("reference evaluation requires a reference answer")


RevisionContent: TypeAlias = SftRevisionContent | PreferenceRevisionContent | EvaluationRevisionContent


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
        if self.construction_spec_version < 1:
            raise ValueError("construction spec version must be positive")
        if not _is_sha256(self.content_digest) or not _is_sha256(self.input_digest):
            raise ValueError("revision digests must be sha256")
        if self.content_digest != content_digest_for(self.content):
            raise ValueError("revision content digest does not match content")
        object.__setattr__(self, "content", deepcopy(self.content))
        object.__setattr__(self, "provenance", deepcopy(self.provenance))

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


def content_digest_for(content: RevisionContent) -> str:
    content_value = content
    if isinstance(content_value, SftRevisionContent):
        payload = {
            "schema_version": content_value.schema_version,
            "messages": [dict(item) for item in content_value.messages],
            "context": [dict(item) for item in content_value.context],
            "evidence": [dict(item) for item in content_value.evidence],
            "target": content_value.target,
        }
    elif isinstance(content_value, PreferenceRevisionContent):
        payload = {
            "schema_version": content_value.schema_version,
            "messages": [dict(item) for item in content_value.messages],
            "context": [dict(item) for item in content_value.context],
            "evidence": [dict(item) for item in content_value.evidence],
            "response_a": content_value.response_a,
            "response_b": content_value.response_b,
            "suggested_preference": content_value.suggested_preference,
            "rationale": content_value.rationale,
            "human_preference": content_value.human_preference,
        }
    else:
        payload = {
            "schema_version": content_value.schema_version,
            "messages": [dict(item) for item in content_value.messages],
            "context": [dict(item) for item in content_value.context],
            "evidence": [dict(item) for item in content_value.evidence],
            "reference": content_value.reference,
            "criteria": list(content_value.criteria),
            "evaluation_mode": content_value.evaluation_mode,
        }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationMode",
    "EvaluationRevisionContent",
    "PREFERENCE_SCHEMA_VERSION",
    "PreferenceChoice",
    "PreferenceRevisionContent",
    "RevisionAuthorKind",
    "RevisionContent",
    "SFT_SCHEMA_VERSION",
    "SampleRevision",
    "SftRevisionContent",
    "content_digest_for",
]
