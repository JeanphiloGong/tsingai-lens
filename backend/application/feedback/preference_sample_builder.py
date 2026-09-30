"""Build same-input response pairs for preference datasets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from application.feedback.sample_builder_support import (
    SampleContentGenerator,
    generation_missing_reasons,
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
    SampleRevision,
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
    """Build and revise two comparable answers under a fixed review input."""

    model_name = "deterministic-evidence-preference-v1"

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
        previous_revision: SampleRevision | None = None,
    ) -> PreferenceBuildCandidate | PreferenceBuildNeedsInput:
        snapshot = dict(case.context_snapshot or {})
        question = question_from_snapshot(snapshot)
        sources, source_provenance = readable_sources(snapshot, annotation)
        messages = ({"role": "user", "content": question},)
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
        corrected_question = strip_internal_references(snapshot.get("corrected_question"))
        assessment = snapshot.get("pairing_assessment")
        relation = assessment.get("task_relation") if isinstance(assessment, Mapping) else None
        reviewing_previous = (
            bool(review_note)
            and previous_revision is not None
            and previous_revision.input_digest == sample.source_digest
            and previous_revision.construction_spec_version == dataset.spec_version
        )
        if reviewing_previous:
            if not isinstance(previous_revision.content, PreferenceRevisionContent):
                raise ValueError("sample_generation_preference_revision_invalid")
            previous = previous_revision.content
            messages, sources = previous.messages, previous.context
            question = next(item["content"] for item in messages if item["role"] == "user")
            response_a, response_b = previous.response_a, previous.response_b
            source_provenance = tuple(previous_revision.provenance.get("evidence_records") or ())
        if not question:
            return PreferenceBuildNeedsInput(("question_missing",))
        human_review_input = reviewing_previous and previous_revision.author_kind == "human"
        missing: list[str] = []
        if not sources:
            missing.append("readable_evidence_missing")
        if not human_review_input and corrected_question and corrected_question != question:
            missing.append("preference_inputs_differ")
        if not human_review_input and snapshot.get("corrected_answer"):
            if relation == "different_task":
                missing.append("preference_inputs_differ")
            elif relation != "same_task":
                missing.append("preference_task_scope_unverified")
        if not human_review_input and (snapshot.get("input_digest_a") or snapshot.get("input_digest_b")) and (
            snapshot.get("input_digest_a") != snapshot.get("input_digest_b")
        ):
            missing.append("preference_inputs_differ")
        if not response_a:
            missing.append("preference_response_a_missing")
        if not response_b:
            missing.append("preference_response_b_missing")
        if response_a and response_b and response_a == response_b:
            missing.append("preference_responses_identical")
        if missing:
            return PreferenceBuildNeedsInput(tuple(dict.fromkeys(missing)))

        generated = False
        suggested = _preference_choice(snapshot)
        rationale = _rationale(snapshot)
        if reviewing_previous:
            suggested, rationale = previous.suggested_preference, previous.rationale
        if self.generator is not None and review_note and sources:
            value = await self.generator.generate(
                task_type="preference",
                question=question,
                context=sources,
                snapshot={
                    **snapshot,
                    "response_a": response_a,
                    "response_b": response_b,
                    "messages": messages,
                    "suggested_preference": suggested,
                    "rationale": rationale,
                },
                construction_spec=dataset.construction_spec,
                review_note=review_note,
            )
            reasons = generation_missing_reasons(value)
            if reasons:
                return PreferenceBuildNeedsInput(reasons)
            if any(not isinstance(value.get(key), str) for key in ("response_a", "response_b", "rationale")):
                raise ValueError("sample_generation_preference_responses_invalid")
            response_a = strip_internal_references(value.get("response_a"))
            response_b = strip_internal_references(value.get("response_b"))
            if not response_a or not response_b:
                raise ValueError("sample_generation_preference_responses_invalid")
            if response_a == response_b:
                raise ValueError("sample_generation_preference_responses_identical")
            suggested = _choice_from_value(value.get("suggested_preference"))
            rationale = strip_internal_references(value.get("rationale"))
            generated = True
        elif review_note:
            return PreferenceBuildNeedsInput(("preference_rebuild_generator_unavailable",))

        context = tuple(sources)
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
            "builder": self.generator.model_name if generated else self.model_name,
            "collection_id": dataset.collection_id,
            "dataset_id": dataset.dataset_id,
            "source_case_id": case.case_id,
            "session_id": case.session_id,
            "anchor_message_id": case.anchor_message_id,
            "corrected_message_id": snapshot.get("corrected_message_id"),
            "pairing_basis": snapshot.get("pairing_basis", "same_case_review_input"),
            "pairing_assessment": assessment,
            "candidate_origin": "model_rebuild" if generated else "persisted_answers",
            "reviewed_revision_id": previous_revision.revision_id if reviewing_previous else None,
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
            **({"review_note": review_note} if review_note else {}),
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


def _choice_from_value(value: Any) -> PreferenceChoice | None:
    if value is None:
        return None
    choice = str(value).strip().lower()
    if choice not in {"a", "b", "tie", "unclear"}:
        raise ValueError("sample_generation_preference_choice_invalid")
    return choice  # type: ignore[return-value]


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
