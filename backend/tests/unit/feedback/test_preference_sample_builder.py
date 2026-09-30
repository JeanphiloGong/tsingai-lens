from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.feedback.preference_sample_builder import (
    PreferenceBuildCandidate,
    PreferenceBuildNeedsInput,
    PreferenceSampleBuilder,
    validate_preference,
)
from domain.feedback import Dataset, DatasetSample, FeedbackCase, SampleRevision, PreferenceRevisionContent


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _dataset() -> Dataset:
    now = datetime.now(timezone.utc)
    return Dataset("fdset-preference", "collection-1", "偏好", "preference", {}, 1, "user-1", now, now)


def _sample() -> DatasetSample:
    return DatasetSample.pending(
        sample_id="sample-1",
        dataset_id="fdset-preference",
        source_case_id="case-1",
        source_digest="a" * 64,
        active_job_id="job-1",
        now="2026-09-29T00:00:00+00:00",
    )


def _case(snapshot: dict) -> FeedbackCase:
    return FeedbackCase(
        case_id="case-1",
        collection_id="collection-1",
        session_id="session-1",
        anchor_message_id="answer-1",
        source_signal_ids=(),
        analysis_result_ids=(),
        context_snapshot=snapshot,
        status="needs_annotation",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


async def test_builder_creates_same_input_pair_without_selecting_for_human() -> None:
    result = await PreferenceSampleBuilder().build(
        dataset=_dataset(),
        sample=_sample(),
        case=_case(
            {
                "question": "比较 A、B 的预热条件。",
                "original_answer": "回答 A",
                "candidate_target": "回答 B",
                "suggested_preference": "b",
                "inspected_sources": [
                    {"document_title": "文献 B", "source_ref": "source-b", "quote": "图注原文"}
                ],
            }
        ),
        annotation=None,
    )

    assert isinstance(result, PreferenceBuildCandidate)
    assert result.content.human_preference is None
    assert result.content.suggested_preference == "b"
    assert result.provenance["input_digest_a"] == result.provenance["input_digest_b"]
    assert "source_ref" not in result.content.context[0]


async def test_builder_rejects_missing_or_identical_pair() -> None:
    result = await PreferenceSampleBuilder().build(
        dataset=_dataset(),
        sample=_sample(),
        case=_case({
            "question": "比较 A、B。",
            "original_answer": "同一答案",
            "candidate_target": "同一答案",
            "inspected_sources": [{"document_title": "A", "quote": "证据"}],
        }),
        annotation=None,
    )
    assert isinstance(result, PreferenceBuildNeedsInput)
    assert result.missing_reasons == ("preference_responses_identical",)


async def test_builder_rejects_pair_for_a_changed_question() -> None:
    result = await PreferenceSampleBuilder().build(
        dataset=_dataset(), sample=_sample(), annotation=None,
        case=_case({
            "question": "比较 A、B。", "corrected_question": "只总结 B。",
            "answer": "A、B 的比较。", "corrected_answer": "B 的总结。",
            "pairing_assessment": {"task_relation": "different_task"},
            "inspected_sources": [{"document_title": "B", "quote": "证据"}],
        }),
    )
    assert isinstance(result, PreferenceBuildNeedsInput)
    assert result.missing_reasons == ("preference_inputs_differ",)


async def test_rebuild_uses_review_note_to_revise_pair() -> None:
    class Generator:
        model_name = "review-model"

        async def generate(self, **inputs):
            assert inputs["task_type"] == "preference"
            assert inputs["review_note"] == "修正 B 的温度并保留比较边界。"
            assert inputs["snapshot"]["response_a"] == "B 没有预热。"
            return {
                "response_a": "B 没有预热。", "response_b": "B 预热到 200 C；A 未报告。",
                "suggested_preference": "b", "rationale": "B 的温度与原文一致。",
                "missing_reasons": [],
            }

    result = await PreferenceSampleBuilder(generator=Generator()).build(
        dataset=_dataset(), sample=_sample(), annotation=None,
        review_note="修正 B 的温度并保留比较边界。",
        case=_case({
            "question": "比较 A、B 的预热条件。", "answer": "B 没有预热。",
            "corrected_answer": "B 预热到 300 C。",
            "pairing_assessment": {"task_relation": "same_task"},
            "inspected_sources": [{"document_title": "B", "quote": "Preheated at 200 C."}],
        }),
    )
    assert isinstance(result, PreferenceBuildCandidate)
    assert result.content.response_b == "B 预热到 200 C；A 未报告。"
    assert result.content.human_preference is None
    assert result.provenance["builder"] == "review-model"
    assert result.provenance["review_note"] == "修正 B 的温度并保留比较边界。"


@pytest.mark.parametrize("choice", ["response_b", "b_preferred", True])
async def test_rebuild_rejects_invalid_generated_preference(choice) -> None:
    class Generator:
        model_name = "review-model"

        async def generate(self, **inputs):
            return {
                "response_a": "B had no preheating.", "response_b": "B was preheated at 200 C.",
                "suggested_preference": choice, "rationale": "B agrees with the source.",
            }

    with pytest.raises(ValueError, match="sample_generation_preference_choice_invalid"):
        await PreferenceSampleBuilder(generator=Generator()).build(
            dataset=_dataset(), sample=_sample(), annotation=None,
            review_note="Correct B's temperature.", case=_case({
                "question": "Compare A and B's preheating.", "answer": "B had no preheating.",
                "candidate_target": "B was preheated at 300 C.",
                "inspected_sources": [{"document_title": "B", "quote": "Preheated at 200 C."}],
            }),
        )


def test_validation_rejects_different_inputs_and_treats_label_as_explicit() -> None:
    with pytest.raises(ValueError, match="preference_inputs_differ"):
        validate_preference({"input_digest_a": "a", "input_digest_b": "b"})


@pytest.mark.parametrize("extra,reason", [
    ({"input_digest_a": "a", "input_digest_b": "b", "pairing_assessment": {"task_relation": "same_task"}}, "preference_inputs_differ"),
    ({"pairing_assessment": {"task_relation": "uncertain"}}, "preference_task_scope_unverified"),
    ({}, "preference_task_scope_unverified"),
])
@pytest.mark.parametrize("has_previous", [False, True])
async def test_builder_does_not_invent_matching_input_digests(extra, reason, has_previous):
    previous = SampleRevision.build_worker(
        revision_id="previous-revision", sample_id="sample-1", revision_no=1,
        content=PreferenceRevisionContent.from_mapping({
            "schema_version": "literature-preference.v1",
            "messages": [{"role": "user", "content": "比较 A、B。"}],
            "context": [{"document_title": "B", "text": "证据"}],
            "evidence": [{"document_title": "B", "text": "证据"}],
            "response_a": "回答 A", "response_b": "回答 B",
        }), input_digest="a" * 64, construction_spec_version=1, provenance={},
        created_at="2026-09-29T00:00:00+00:00", job_id="old-job",
    ) if has_previous else None
    result = await PreferenceSampleBuilder().build(
        dataset=_dataset(), sample=_sample(), annotation=None,
        previous_revision=previous, review_note="核对同一任务。" if has_previous else None,
        case=_case({
            "question": "比较 A、B。", "answer": "回答 A", "corrected_answer": "回答 B",
            "inspected_sources": [{"document_title": "B", "quote": "证据"}], **extra,
        }),
    )
    assert isinstance(result, PreferenceBuildNeedsInput)
    assert reason in result.missing_reasons


@pytest.mark.parametrize("input_digest,spec_version", [("b" * 64, 1), ("a" * 64, 2)])
async def test_rebuild_uses_current_evidence_when_previous_revision_is_stale(input_digest, spec_version):
    previous = SampleRevision.build_worker(
        revision_id="old-revision", sample_id="sample-1", revision_no=1,
        content=PreferenceRevisionContent.from_mapping({
            "schema_version": "literature-preference.v1",
            "messages": [{"role": "user", "content": "旧问题"}],
            "context": [{"document_title": "B", "text": "旧证据"}],
            "evidence": [{"document_title": "B", "text": "旧证据"}],
            "response_a": "旧回答 A", "response_b": "旧回答 B",
        }), input_digest=input_digest, construction_spec_version=spec_version,
        provenance={}, created_at="2026-09-29T00:00:00+00:00", job_id="old-job",
    )

    class Generator:
        model_name = "review-model"

        async def generate(self, **inputs):
            assert inputs["question"] == "当前问题"
            assert inputs["context"] == ({"document_title": "B", "text": "新证据"},)
            assert inputs["snapshot"]["response_a"] == "当前回答 A"
            return {"response_a": "当前回答 A", "response_b": "基于新证据的回答 B",
                "suggested_preference": "b", "rationale": "参考新证据。"}

    result = await PreferenceSampleBuilder(generator=Generator()).build(
        dataset=_dataset(), sample=_sample(), annotation=None, previous_revision=previous,
        review_note="重新核对证据。", case=_case({
            "question": "当前问题", "answer": "当前回答 A", "candidate_target": "当前回答 B",
            "inspected_sources": [{"document_title": "B", "quote": "新证据"}],
        }),
    )
    assert isinstance(result, PreferenceBuildCandidate)
    assert result.provenance["reviewed_revision_id"] is None
    assert result.content.context[0]["text"] == "新证据"
