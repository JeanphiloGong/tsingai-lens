"""Build executable reference or rubric samples for evaluation datasets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from application.feedback.sample_builder_support import (
    question_from_snapshot,
    readable_sources,
    snapshot_digest,
)
from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.dataset import Dataset
from domain.feedback.dataset_sample import DatasetSample
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.sample_revision import EvaluationRevisionContent, EvaluationMode


@dataclass(frozen=True)
class EvaluationBuildCandidate:
    content: EvaluationRevisionContent
    provenance: dict[str, Any]


@dataclass(frozen=True)
class EvaluationBuildNeedsInput:
    missing_reasons: tuple[str, ...]


class EvaluationSampleBuilder:
    model_name = "deterministic-evidence-evaluation-v1"

    async def build(
        self,
        *,
        dataset: Dataset,
        sample: DatasetSample,
        case: FeedbackCase,
        annotation: FeedbackAnnotation | None,
    ) -> EvaluationBuildCandidate | EvaluationBuildNeedsInput:
        snapshot = dict(case.context_snapshot or {})
        question = question_from_snapshot(snapshot)
        if not question:
            return EvaluationBuildNeedsInput(("question_missing",))
        sources, source_provenance = readable_sources(snapshot, annotation)
        mode = _mode(snapshot)
        if mode is None:
            return EvaluationBuildNeedsInput(("evaluation_mode_invalid",))
        criteria = _criteria(snapshot)
        reference = _reference(snapshot)
        missing: list[str] = []
        if not sources:
            missing.append("readable_evidence_missing")
        if not criteria:
            missing.append("evaluation_criteria_missing")
        if mode == "reference" and not reference:
            missing.append("evaluation_reference_missing")
        if missing:
            return EvaluationBuildNeedsInput(tuple(missing))

        messages = ({"role": "user", "content": question},)
        context = tuple(sources)
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
            "source_refs": [item["source_ref"] for item in source_provenance if item.get("source_ref")],
            "evidence_records": source_provenance,
            "evaluation_mode": mode,
            "input_snapshot_digest": snapshot_digest(snapshot),
        }
        return EvaluationBuildCandidate(content=content, provenance=provenance)


def validate_evaluation(value: Mapping[str, Any]) -> EvaluationRevisionContent:
    criteria = tuple(
        str(item).strip()
        for item in value.get("criteria", ())
        if str(item).strip()
    )
    mode = str(value.get("evaluation_mode") or "reference")
    if not criteria:
        raise ValueError("evaluation_criteria_or_reference_missing")
    if mode == "reference" and not str(value.get("reference") or "").strip():
        raise ValueError("evaluation_reference_missing")
    if mode not in {"reference", "rubric"}:
        raise ValueError("evaluation_mode_invalid")
    return EvaluationRevisionContent.from_mapping({**dict(value), "criteria": criteria})


def _mode(snapshot: Mapping[str, Any]) -> EvaluationMode | None:
    value = str(snapshot.get("evaluation_mode") or "reference").strip().lower()
    if value not in {"reference", "rubric"}:
        return None
    return value  # type: ignore[return-value]


def _criteria(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    values = snapshot.get("evaluation_criteria", snapshot.get("criteria", ()))
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _reference(snapshot: Mapping[str, Any]) -> str:
    for key in ("evaluation_reference", "reference", "reference_answer", "candidate_target"):
        value = str(snapshot.get(key) or "").strip()
        if value:
            return value
    return ""


__all__ = [
    "EvaluationBuildCandidate",
    "EvaluationBuildNeedsInput",
    "EvaluationSampleBuilder",
    "validate_evaluation",
]
