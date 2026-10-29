"""Build same-input response pairs for preference datasets."""

from __future__ import annotations


from dataclasses import dataclass
from typing import Any

from application.feedback.sample_builder_support import (
    SampleContentGenerator,
    input_digest,
    question_from_snapshot,
    messages_from_snapshot,
    readable_sources,
    snapshot_digest,
)
from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.dataset import Dataset
from domain.feedback.dataset_sample import DatasetSample
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.sample_revision import (
    PreferenceRevisionContent,
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
        snapshot = case.context_snapshot
        question = question_from_snapshot(snapshot)
        sources, source_provenance = readable_sources(snapshot, annotation)
        messages = messages_from_snapshot(snapshot)
        response_a = strip_internal_references(snapshot.get("answer"))
        response_b = strip_internal_references(
            snapshot.get("corrected_answer") or snapshot.get("candidate_target")
        )
        corrected_question = strip_internal_references(snapshot.get("corrected_question"))
        assessment = snapshot.get("pairing_assessment")
        relation = assessment["task_relation"] if assessment is not None else None
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
        suggested = snapshot.get("suggested_preference")
        rationale = strip_internal_references(snapshot.get("rationale"))
        if reviewing_previous:
            suggested, rationale = previous.suggested_preference, previous.rationale
        if self.generator is not None:
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
            reasons = tuple(value.missing_reasons)
            if reasons:
                return PreferenceBuildNeedsInput(reasons)
            if review_note:
                response_a, response_b = value.response_a, value.response_b
            suggested, rationale = value.suggested_preference, value.rationale
            generated = True
        elif review_note:
            return PreferenceBuildNeedsInput(("preference_rebuild_generator_unavailable",))
        elif suggested is None or not rationale:
            return PreferenceBuildNeedsInput(("preference_assessment_generator_unavailable",))

        context = sources
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
            "candidate_origin": (
                "model_rebuild" if generated and review_note
                else "model_assessment" if generated else "persisted_answers"
            ),
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


__all__ = [
    "PreferenceBuildCandidate",
    "PreferenceBuildNeedsInput",
    "PreferenceSampleBuilder",
]
