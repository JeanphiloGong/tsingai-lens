"""Evidence and input helpers shared by task-specific sample builders."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Annotated, Any, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.sample_revision import strip_internal_references


class SftSampleModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    target: Annotated[str, Field(min_length=1, max_length=100000)] | None = None
    missing_reasons: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_candidate(self) -> "SftSampleModelOutput":
        if not self.missing_reasons and self.target is None:
            raise ValueError("sample_generation_target_missing")
        return self


class PreferenceSampleModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    response_a: Annotated[str, Field(min_length=1, max_length=100000)] | None = None
    response_b: Annotated[str, Field(min_length=1, max_length=100000)] | None = None
    suggested_preference: Literal["a", "b", "tie", "unclear"] | None = None
    rationale: Annotated[str, Field(min_length=1, max_length=100000)] | None = None
    missing_reasons: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_assessment(self) -> "PreferenceSampleModelOutput":
        if not self.missing_reasons and (
            self.suggested_preference is None or self.rationale is None
        ):
            raise ValueError("sample_generation_preference_assessment_missing")
        return self


class EvaluationSampleModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    reference: Annotated[str, Field(max_length=100000)] | None = None
    criteria: list[Annotated[str, Field(min_length=1, max_length=100000)]] | None = Field(default=None, min_length=1, max_length=100)
    missing_reasons: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_criteria(self) -> "EvaluationSampleModelOutput":
        if not self.missing_reasons and self.criteria is None:
            raise ValueError("sample_generation_evaluation_criteria_missing")
        return self


class SampleContentGenerator(Protocol):
    model_name: str

    async def generate(
        self, *, task_type: str, question: str, context: tuple[dict[str, str], ...],
        snapshot: Mapping[str, Any], construction_spec: Mapping[str, Any],
        review_note: str | None = None,
    ) -> SftSampleModelOutput | PreferenceSampleModelOutput | EvaluationSampleModelOutput: ...


def question_from_snapshot(snapshot: Mapping[str, Any]) -> str:
    return strip_internal_references(snapshot.get("question"))


def messages_from_snapshot(snapshot: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Use the conversation captured before the answer under review."""
    return tuple(
        {"role": item["role"], "content": strip_internal_references(item["content"])}
        for item in snapshot["messages"]
    )


def readable_sources(
    snapshot: Mapping[str, Any], annotation: FeedbackAnnotation | None
) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, Any], ...]]:
    """Return readable model text plus the private source records that support it."""

    model_sources: list[dict[str, str]] = []
    provenance: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    supported_refs = set(annotation.support_source_refs) if annotation is not None else set()
    candidates = [
        (raw, "successful_source_tool_result")
        for raw in snapshot.get("inspected_sources") or ()
    ]
    candidates.extend(
        (raw, "human_annotation_selected_context")
        for raw in snapshot.get("requested_scope") or ()
        if raw.get("source_ref") in supported_refs
        and raw.get("origin") == "user_selected_context"
    )
    for raw, audit_basis in candidates:
        title = strip_internal_references(raw.get("document_title"))
        text = strip_internal_references(raw.get("quote"))
        if not title or not text:
            continue
        key = (title, text)
        if key in seen:
            continue
        seen.add(key)
        model_sources.append({"document_title": title, "text": text})
        provenance.append(
            {
                "document_id": raw.get("document_id"),
                "source_kind": raw.get("source_kind"),
                "source_ref": raw.get("source_ref"),
                "source_digest": raw.get("source_digest"),
                "document_title": title,
                "page": raw.get("page"),
                "heading_path": raw.get("heading_path"),
                "quote": text,
                "audit_basis": audit_basis,
            }
        )
    return tuple(model_sources), tuple(provenance)


def snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def input_digest(messages: tuple[dict[str, str], ...], context: tuple[dict[str, str], ...]) -> str:
    encoded = json.dumps(
        {"messages": messages, "context": context},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = [
    "input_digest",
    "question_from_snapshot",
    "readable_sources",
    "snapshot_digest",
]
