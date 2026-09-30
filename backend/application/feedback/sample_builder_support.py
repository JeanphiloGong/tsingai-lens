"""Evidence and input helpers shared by task-specific sample builders."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Protocol

from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.sample_revision import strip_internal_references


class SampleContentGenerator(Protocol):
    model_name: str

    async def generate(
        self, *, task_type: str, question: str, context: tuple[dict[str, str], ...],
        snapshot: Mapping[str, Any], construction_spec: Mapping[str, Any],
        review_note: str | None = None,
    ) -> dict[str, Any]: ...


def generation_missing_reasons(value: Mapping[str, Any]) -> tuple[str, ...]:
    reasons = value.get("missing_reasons", [])
    if not isinstance(reasons, list) or any(not isinstance(item, str) or not item.strip() for item in reasons):
        raise ValueError("sample_generation_invalid_missing_reasons")
    return tuple(dict.fromkeys(item.strip()[:500] for item in reasons))


def question_from_snapshot(snapshot: Mapping[str, Any]) -> str:
    return strip_internal_references(snapshot.get("question"))


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
        if isinstance(raw, Mapping)
        and str(raw.get("source_ref") or raw.get("table_ref") or "") in supported_refs
        and raw.get("origin") == "user_selected_context"
    )
    for raw, audit_basis in candidates:
        if not isinstance(raw, Mapping):
            continue
        title = strip_internal_references(raw.get("document_title") or raw.get("title"))
        text = strip_internal_references(raw.get("quote") or raw.get("text") or raw.get("content"))
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
                "source_ref": raw.get("source_ref") or raw.get("table_ref"),
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
        dict(snapshot),
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
