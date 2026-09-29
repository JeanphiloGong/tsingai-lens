from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.feedback.preference_sample_builder import (
    PreferenceBuildCandidate,
    PreferenceBuildNeedsInput,
    PreferenceSampleBuilder,
    validate_preference,
)
from domain.feedback import Dataset, DatasetSample, FeedbackCase


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


def test_validation_rejects_different_inputs_and_treats_label_as_explicit() -> None:
    with pytest.raises(ValueError, match="preference_inputs_differ"):
        validate_preference({"input_digest_a": "a", "input_digest_b": "b"})
