"""Evidence and input helpers shared by task-specific sample builders."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from domain.feedback.annotation import FeedbackAnnotation


def question_from_snapshot(snapshot: Mapping[str, Any]) -> str:
    return str(snapshot.get("question") or "").strip()


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
        title = str(raw.get("document_title") or raw.get("title") or "").strip()
        text = str(raw.get("quote") or raw.get("text") or raw.get("content") or "").strip()
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
