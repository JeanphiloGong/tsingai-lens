from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.feedback.sft_sample_builder import (
    SftBuildCandidate,
    SftBuildNeedsInput,
    SftSampleBuilder,
)
from domain.feedback import Dataset, DatasetSample, FeedbackCase


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _dataset() -> Dataset:
    now = datetime.now(timezone.utc)
    return Dataset(
        dataset_id="fdset-1",
        collection_id="collection-1",
        name="SFT",
        task_type="sft",
        construction_spec={"language": "zh-CN"},
        spec_version=1,
        created_by="user-1",
        created_at=now,
        updated_at=now,
    )


def _sample() -> DatasetSample:
    return DatasetSample.pending(
        sample_id="sample-1",
        dataset_id="fdset-1",
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
        source_signal_ids=("signal-1",),
        analysis_result_ids=("analysis-1",),
        context_snapshot=snapshot,
        status="needs_annotation",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


async def test_builder_keeps_ids_out_of_model_content_and_retains_provenance() -> None:
    result = await SftSampleBuilder().build(
        dataset=_dataset(),
        sample=_sample(),
        case=_case(
            {
                "question": "比较 A、B 的预热条件。",
                "answer": "B 没有预热。",
                "candidate_target": "文献 B 的图注显示存在预热条件。",
                "inspected_sources": [
                    {
                        "document_id": "doc-b",
                        "document_title": "文献 B",
                        "source_ref": "blk-b-1",
                        "page": 8,
                        "heading_path": "Results > Figure 3",
                        "quote": "预热温度为 200 °C。",
                    }
                ],
            }
        ),
        annotation=None,
    )

    assert isinstance(result, SftBuildCandidate)
    assert result.content.context == (
        {"document_title": "文献 B", "text": "预热温度为 200 °C。"},
    )
    assert result.content.evidence == result.content.context
    assert "source_ref" not in result.content.context[0]
    assert result.provenance["source_refs"] == ["blk-b-1"]
    assert result.provenance["evidence_records"][0]["heading_path"] == "Results > Figure 3"


async def test_builder_does_not_invent_target_or_evidence() -> None:
    result = await SftSampleBuilder().build(
        dataset=_dataset(),
        sample=_sample(),
        case=_case(
            {
                "question": "比较 A、B。",
                "answer": "原回答",
                "inspected_sources": [
                    {"document_id": "doc-b", "source_ref": "blk-b-1"}
                ],
            }
        ),
        annotation=None,
    )

    assert isinstance(result, SftBuildNeedsInput)
    assert result.missing_reasons == (
        "readable_evidence_missing",
        "candidate_target_missing",
    )
