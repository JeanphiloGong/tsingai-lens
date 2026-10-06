"""Build conservative, evidence-backed SFT candidates from feedback cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.dataset import Dataset
from domain.feedback.dataset_sample import DatasetSample
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.sample_revision import SftRevisionContent, strip_internal_references
from application.feedback.sample_builder_support import (
    question_from_snapshot,
    readable_sources,
    snapshot_digest,
    SampleContentGenerator,
    generation_missing_reasons,
)


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
        review_note: str | None = None,
    ) -> SftBuildCandidate | SftBuildNeedsInput: ...


class SftSampleBuilder:
    """Use persisted corrections or generate a grounded candidate for review."""

    model_name = "deterministic-evidence-candidate-v1"

    def __init__(self, *, generator: SampleContentGenerator | None = None) -> None:
        self.generator = generator

    async def build(
        self,
        *,
        dataset: Dataset,
        sample: DatasetSample,
        case: FeedbackCase,
        annotation: FeedbackAnnotation | None,
        review_note: str | None = None,
    ) -> SftBuildCandidate | SftBuildNeedsInput:
        snapshot = dict(case.context_snapshot or {})
        question = question_from_snapshot(snapshot)
        if not question:
            return SftBuildNeedsInput(("question_missing",))

        readable_sources_value, source_provenance = readable_sources(snapshot, annotation)
        missing: list[str] = []
        if not readable_sources_value:
            missing.append("readable_evidence_missing")

        target, target_origin = _candidate_target(snapshot, annotation)
        generated = False
        if readable_sources_value and self.generator is not None and (not target or review_note):
            value = await self.generator.generate(
                task_type="sft", question=question, context=readable_sources_value,
                snapshot=snapshot, construction_spec=dataset.construction_spec, review_note=review_note,
            )
            reasons = generation_missing_reasons(value)
            if reasons:
                return SftBuildNeedsInput(reasons)
            if not isinstance(value.get("target"), str) or not value["target"].strip():
                raise ValueError("sample_generation_target_invalid")
            target, target_origin = value["target"].strip(), "model_candidate"
            generated = True
        if not target:
            missing.append("candidate_target_missing")
        if missing:
            return SftBuildNeedsInput(tuple(missing))

        content = SftRevisionContent(
            schema_version="literature-sft.v1",
            messages=({"role": "user", "content": question},),
            context=tuple(readable_sources_value),
            target=target,
            evidence=tuple(readable_sources_value),
        )
        provenance = {
            "builder": self.generator.model_name if generated else self.model_name,
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
            "input_snapshot_digest": snapshot_digest(snapshot),
        }
        return SftBuildCandidate(content=content, provenance=provenance)


def _candidate_target(
    snapshot: Mapping[str, Any], annotation: FeedbackAnnotation | None
) -> tuple[str, str]:
    if annotation is not None and annotation.target:
        return strip_internal_references(annotation.target), "human_annotation"
    for origin, value in (
        ("case_candidate", snapshot.get("candidate_target")),
        ("analysis_candidate", (snapshot.get("analysis") or {}).get("suggested_target")),
        ("corrected_message", snapshot.get("corrected_answer")),
    ):
        target = strip_internal_references(value)
        if target:
            return target, origin
    return "", "missing"


__all__ = [
    "SampleBuildInputError",
    "SftBuildCandidate",
    "SftBuildNeedsInput",
    "SftSampleBuilder",
    "SftSampleBuilderProtocol",
]
