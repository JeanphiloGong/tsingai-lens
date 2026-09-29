"""Build conservative, evidence-backed SFT candidates from feedback cases."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Protocol

from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.dataset import Dataset
from domain.feedback.dataset_sample import DatasetSample
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.sample_revision import SftRevisionContent


class SampleBuildInputError(ValueError):
    """The source case cannot produce a truthful candidate yet."""


@dataclass(frozen=True)
class SftBuildCandidate:
    content: SftRevisionContent
    provenance: dict[str, Any]


@dataclass(frozen=True)
class SftBuildNeedsInput:
    missing_reasons: tuple[str, ...]


class SftSampleBuilderProtocol(Protocol):
    async def build(
        self,
        *,
        dataset: Dataset,
        sample: DatasetSample,
        case: FeedbackCase,
        annotation: FeedbackAnnotation | None,
    ) -> SftBuildCandidate | SftBuildNeedsInput: ...


class SftSampleBuilder:
    """Turn already persisted evidence coverage into a model-readable sample.

    This first implementation is deterministic.  A provider-backed candidate
    generator can implement the same protocol later, but it must still use
    the fixed evidence records and return a candidate for human confirmation.
    """

    model_name = "deterministic-evidence-candidate-v1"

    async def build(
        self,
        *,
        dataset: Dataset,
        sample: DatasetSample,
        case: FeedbackCase,
        annotation: FeedbackAnnotation | None,
    ) -> SftBuildCandidate | SftBuildNeedsInput:
        snapshot = dict(case.context_snapshot or {})
        question = str(snapshot.get("question") or "").strip()
        if not question:
            return SftBuildNeedsInput(("question_missing",))

        readable_sources, source_provenance = _readable_sources(snapshot, annotation)
        missing: list[str] = []
        if not readable_sources:
            missing.append("readable_evidence_missing")

        target, target_origin = _candidate_target(snapshot, annotation)
        if not target:
            missing.append("candidate_target_missing")
        if missing:
            return SftBuildNeedsInput(tuple(missing))

        content = SftRevisionContent(
            schema_version="literature-sft.v1",
            messages=({"role": "user", "content": question},),
            context=tuple(readable_sources),
            target=target,
            evidence=tuple(readable_sources),
        )
        provenance = {
            "builder": self.model_name,
            "collection_id": dataset.collection_id,
            "dataset_id": dataset.dataset_id,
            "source_case_id": case.case_id,
            "session_id": case.session_id,
            "anchor_message_id": case.anchor_message_id,
            "source_signal_ids": list(case.source_signal_ids),
            "analysis_result_ids": list(case.analysis_result_ids),
            "signal_analysis_result_ids": list(case.signal_analysis_result_ids),
            "tool_failure_analysis_result_ids": list(case.tool_failure_analysis_result_ids),
            "original_answer": str(snapshot.get("answer") or ""),
            "source_refs": [item["source_ref"] for item in source_provenance if item.get("source_ref")],
            "evidence_records": source_provenance,
            "target_origin": target_origin,
            "input_snapshot_digest": _snapshot_digest(snapshot),
        }
        return SftBuildCandidate(content=content, provenance=provenance)


def _candidate_target(
    snapshot: Mapping[str, Any], annotation: FeedbackAnnotation | None
) -> tuple[str, str]:
    if annotation is not None and annotation.target:
        return annotation.target.strip(), "human_annotation"
    for origin, value in (
        ("case_candidate", snapshot.get("candidate_target")),
        ("analysis_candidate", (snapshot.get("analysis") or {}).get("suggested_target")),
        ("corrected_message", snapshot.get("corrected_answer")),
    ):
        target = str(value or "").strip()
        if target:
            return target, origin
    return "", "missing"


def _readable_sources(
    snapshot: Mapping[str, Any], annotation: FeedbackAnnotation | None
) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, Any], ...]]:
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


def _snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = [
    "SampleBuildInputError",
    "SftBuildCandidate",
    "SftBuildNeedsInput",
    "SftSampleBuilder",
    "SftSampleBuilderProtocol",
]
