"""Build executable reference or rubric samples for evaluation datasets."""

from __future__ import annotations


from dataclasses import dataclass
from typing import Any

from application.feedback.sample_builder_support import (
    question_from_snapshot,
    messages_from_snapshot,
    readable_sources,
    snapshot_digest,
    SampleContentGenerator,
)
from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.dataset import Dataset
from domain.feedback.dataset_sample import DatasetSample
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.sample_revision import (
    EvaluationRevisionContent,
    strip_internal_references,
)


@dataclass(frozen=True)
class EvaluationBuildCandidate:
    content: EvaluationRevisionContent
    provenance: dict[str, Any]


@dataclass(frozen=True)
class EvaluationBuildNeedsInput:
    missing_reasons: tuple[str, ...]


class EvaluationSampleBuilder:
    model_name = "deterministic-evidence-evaluation-v1"

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
    ) -> EvaluationBuildCandidate | EvaluationBuildNeedsInput:
        snapshot = case.context_snapshot
        question = question_from_snapshot(snapshot)
        if not question:
            return EvaluationBuildNeedsInput(("question_missing",))
        sources, source_provenance = readable_sources(snapshot, annotation)
        mode = snapshot.get("evaluation_mode", "reference")
        if mode not in {"reference", "rubric"}:
            return EvaluationBuildNeedsInput(("evaluation_mode_invalid",))
        criteria = tuple(
            strip_internal_references(item) for item in snapshot.get("evaluation_criteria", ())
        )
        reference = strip_internal_references(
            snapshot.get("evaluation_reference") or snapshot.get("candidate_target")
            or snapshot.get("corrected_answer")
        )
        generated = False
        if self.generator is not None and (not criteria or (mode == "reference" and not reference) or review_note):
            value = await self.generator.generate(
                task_type="evaluation", question=question, context=sources, snapshot=snapshot,
                construction_spec=dataset.construction_spec, review_note=review_note,
            )
            reasons = tuple(value.missing_reasons)
            if reasons:
                return EvaluationBuildNeedsInput(reasons)
            criteria = tuple(value.criteria)
            reference = value.reference or ""
            generated = True
        missing: list[str] = []
        if not criteria:
            missing.append("evaluation_criteria_missing")
        if mode == "reference" and not reference:
            missing.append("evaluation_reference_missing")
        if missing:
            return EvaluationBuildNeedsInput(tuple(missing))

        messages = messages_from_snapshot(snapshot)
        context = sources
        content = EvaluationRevisionContent(
            schema_version="literature-evaluation.v1",
            messages=messages,
            context=context,
            reference=reference,
            criteria=criteria,
            evaluation_mode=mode,
            evidence=context,
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
            "source_refs": [item["source_ref"] for item in source_provenance if item.get("source_ref")],
            "evidence_records": source_provenance,
            "evaluation_mode": mode,
            "input_snapshot_digest": snapshot_digest(snapshot),
        }
        return EvaluationBuildCandidate(content=content, provenance=provenance)


__all__ = [
    "EvaluationBuildCandidate",
    "EvaluationBuildNeedsInput",
    "EvaluationSampleBuilder",
]
