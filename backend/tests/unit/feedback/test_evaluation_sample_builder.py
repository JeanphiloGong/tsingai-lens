from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.feedback.evaluation_sample_builder import (
    EvaluationBuildCandidate,
    EvaluationBuildNeedsInput,
    EvaluationSampleBuilder,
    validate_evaluation,
)
from domain.feedback import Dataset, DatasetSample, FeedbackCase


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _dataset() -> Dataset:
    now = datetime.now(timezone.utc)
    return Dataset("fdset-evaluation", "collection-1", "评测", "evaluation", {}, 1, "user-1", now, now)


def _sample() -> DatasetSample:
    return DatasetSample.pending(
        sample_id="sample-1", dataset_id="fdset-evaluation", source_case_id="case-1",
        source_digest="a" * 64, active_job_id="job-1", now="2026-09-29T00:00:00+00:00"
    )


def _case(snapshot: dict) -> FeedbackCase:
    return FeedbackCase(
        case_id="case-1", collection_id="collection-1", session_id="session-1",
        anchor_message_id="answer-1", source_signal_ids=(), analysis_result_ids=(),
        context_snapshot=snapshot, status="needs_annotation",
        created_at="2026-09-29T00:00:00+00:00", updated_at="2026-09-29T00:00:00+00:00"
    )


async def test_builder_creates_reference_evaluation() -> None:
    result = await EvaluationSampleBuilder().build(
        dataset=_dataset(), sample=_sample(), annotation=None,
        case=_case({
            "question": "比较 A、B。",
            "evaluation_reference": "B 有预热。",
            "evaluation_criteria": ["指出 B 的预热条件", "引用图注证据"],
            "inspected_sources": [{"document_title": "B", "source_ref": "source-b", "quote": "图注原文"}],
        }),
    )
    assert isinstance(result, EvaluationBuildCandidate)
    assert result.content.evaluation_mode == "reference"
    assert result.content.criteria == ("指出 B 的预热条件", "引用图注证据")


async def test_builder_requires_executable_criteria() -> None:
    result = await EvaluationSampleBuilder().build(
        dataset=_dataset(), sample=_sample(), annotation=None,
        case=_case({
            "question": "比较 A、B。",
            "evaluation_reference": "B 有预热。",
            "inspected_sources": [{"document_title": "B", "quote": "图注原文"}],
        }),
    )
    assert isinstance(result, EvaluationBuildNeedsInput)
    assert result.missing_reasons == ("evaluation_criteria_missing",)


async def test_builder_rejects_unknown_evaluation_mode() -> None:
    result = await EvaluationSampleBuilder().build(
        dataset=_dataset(), sample=_sample(), annotation=None,
        case=_case({
            "question": "比较 A、B。",
            "evaluation_reference": "B 有预热。",
            "evaluation_criteria": ["指出 B 的预热条件"],
            "evaluation_mode": "unsupported-mode",
            "inspected_sources": [{"document_title": "B", "quote": "图注原文"}],
        }),
    )
    assert isinstance(result, EvaluationBuildNeedsInput)
    assert result.missing_reasons == ("evaluation_mode_invalid",)


def test_rubric_does_not_require_unique_reference() -> None:
    content = validate_evaluation({
        "schema_version": "literature-evaluation.v1",
        "messages": [{"role": "user", "content": "问题"}],
        "context": [{"document_title": "文献", "text": "原文"}],
        "reference": "",
        "criteria": ["必须引用证据"],
        "evaluation_mode": "rubric",
        "evidence": [{"document_title": "文献", "text": "原文"}],
    })
    assert content.evaluation_mode == "rubric"


async def test_builder_generates_reference_and_executable_criteria() -> None:
    class Generator:
        model_name = "test-grounded-model"

        async def generate(self, **inputs):
            assert inputs["task_type"] == "evaluation"
            return {"reference": "B was preheated at 200 C.",
                    "criteria": ["Identifies B's 200 C preheating", "Does not invent A's condition"]}

    result = await EvaluationSampleBuilder(generator=Generator()).build(
        dataset=_dataset(), sample=_sample(), annotation=None,
        case=_case({"question": "Compare A and B's preheating.",
                    "inspected_sources": [{"document_title": "B", "quote": "Preheated at 200 C."}]}),
    )
    assert isinstance(result, EvaluationBuildCandidate)
    assert result.content.reference == "B was preheated at 200 C."
    assert len(result.content.criteria) == 2
