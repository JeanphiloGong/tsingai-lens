"""Build same-input response pairs for preference datasets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from application.feedback.sample_builder_support import (
    input_digest,
    question_from_snapshot,
    readable_sources,
    snapshot_digest,
)
from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.dataset import Dataset
from domain.feedback.dataset_sample import DatasetSample
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.sample_revision import (
    PreferenceRevisionContent,
    PreferenceChoice,
    strip_internal_references,
)


@dataclass(frozen=True)
class PreferenceBuildCandidate:
    content: PreferenceRevisionContent
    provenance: dict[str, Any]


@dataclass(frozen=True)
class PreferenceBuildNeedsInput:
    missing_reasons: tuple[str, ...]


class PreferenceSampleBuilder:
    """Use two existing answers only when they share the same input."""

    model_name = "deterministic-evidence-preference-v1"

    async def build(
        self,
        *,
        dataset: Dataset,
        sample: DatasetSample,
        case: FeedbackCase,
        annotation: FeedbackAnnotation | None,
        review_note: str | None = None,
    ) -> PreferenceBuildCandidate | PreferenceBuildNeedsInput:
        snapshot = dict(case.context_snapshot or {})
        question = question_from_snapshot(snapshot)
        if not question:
            return PreferenceBuildNeedsInput(("question_missing",))
        sources, source_provenance = readable_sources(snapshot, annotation)
        response_a = strip_internal_references(_first_text(
            snapshot,
            "response_a",
            "original_answer",
            "answer",
        ))
        response_b = strip_internal_references(_first_text(
            snapshot,
            "response_b",
            "corrected_answer",
            "candidate_target",
        ))
        missing: list[str] = []
        if not sources:
            missing.append("readable_evidence_missing")
        if not response_a:
            missing.append("preference_response_a_missing")
        if not response_b:
            missing.append("preference_response_b_missing")
        if response_a and response_b and response_a == response_b:
            missing.append("preference_responses_identical")
        if missing:
            return PreferenceBuildNeedsInput(tuple(missing))

        messages = ({"role": "user", "content": question},)
        context = tuple(sources)
        suggested = _preference_choice(snapshot)
        rationale = _rationale(snapshot)
        content = PreferenceRevisionContent(
            schema_version="literature-preference.v1",
            messages=messages,
            context=context,
            response_a=response_a,
            response_b=response_b,
            suggested_preference=suggested,
            rationale=rationale,
            evidence=context,
            human_preference=None,
        )
        shared_input_digest = input_digest(messages, context)
        provenance = {
            "builder": self.model_name,
            "collection_id": dataset.collection_id,
            "dataset_id": dataset.dataset_id,
            "source_case_id": case.case_id,
            "session_id": case.session_id,
            "anchor_message_id": case.anchor_message_id,
            "corrected_message_id": snapshot.get("corrected_message_id"),
            "pairing_basis": snapshot.get("pairing_basis", "same_case_review_input"),
            "source_signal_ids": list(case.source_signal_ids),
            "analysis_result_ids": list(case.analysis_result_ids),
            "signal_analysis_result_ids": list(case.signal_analysis_result_ids),
            "tool_failure_analysis_result_ids": list(case.tool_failure_analysis_result_ids),
            "source_refs": [item["source_ref"] for item in source_provenance if item.get("source_ref")],
            "evidence_records": source_provenance,
            "input_digest_a": shared_input_digest,
            "input_digest_b": shared_input_digest,
            "suggested_preference": suggested,
            "suggested_rationale": rationale,
            "input_snapshot_digest": snapshot_digest(snapshot),
        }
        return PreferenceBuildCandidate(content=content, provenance=provenance)


def validate_preference(value: Mapping[str, Any]) -> PreferenceRevisionContent:
    """Validate a pair before it is accepted at a builder or HTTP boundary."""

    if value.get("input_digest_a") != value.get("input_digest_b"):
        raise ValueError("preference_inputs_differ")
    response_a = strip_internal_references(value.get("response_a"))
    response_b = strip_internal_references(value.get("response_b"))
    if not response_a or not response_b:
        raise ValueError("preference_response_missing")
    if response_a == response_b:
        raise ValueError("preference_responses_identical")
    return PreferenceRevisionContent.from_mapping(value)


def _first_text(snapshot: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(snapshot.get(key) or "").strip()
        if value:
            return strip_internal_references(value)
    return ""


def _preference_choice(snapshot: Mapping[str, Any]) -> PreferenceChoice | None:
    analysis = snapshot.get("analysis")
    values = (
        snapshot.get("suggested_preference"),
        snapshot.get("preference"),
        analysis.get("suggested_preference") if isinstance(analysis, Mapping) else None,
    )
    for value in values:
        choice = str(value or "").strip().lower()
        if choice in {"a", "b", "tie", "unclear"}:
            return choice  # type: ignore[return-value]
    return None


def _rationale(snapshot: Mapping[str, Any]) -> str:
    analysis = snapshot.get("analysis")
    values = (
        snapshot.get("rationale"),
        snapshot.get("suggested_reason"),
        analysis.get("rationale") if isinstance(analysis, Mapping) else None,
        analysis.get("reason") if isinstance(analysis, Mapping) else None,
    )
    return next((strip_internal_references(value) for value in values if str(value or "").strip()), "")


__all__ = [
    "PreferenceBuildCandidate",
    "PreferenceBuildNeedsInput",
    "PreferenceSampleBuilder",
    "validate_preference",
]
