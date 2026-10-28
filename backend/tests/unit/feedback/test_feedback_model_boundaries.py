import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone

from domain.feedback import Dataset, EvidenceCoverage, FeedbackCase
from repositories.feedback_dataset_repository import FeedbackDatasetRepository
from repositories.feedback_dataset_sample_repository import (
    source_digest_for_case,
)


def test_dataset_storage_timestamps_do_not_enter_domain_or_construction_rules() -> None:
    dataset = Dataset(
        "ds-1", "col-1", "Preheating", "sft", {"language": "en"}, 1, "user-1"
    )
    class Sessions:
        def __call__(self): return self
        def begin(self): return self
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def add(self, row): self.row = row
        async def flush(self): pass
        async def get(self, *args): return self.row

    sessions = Sessions()
    repository = FeedbackDatasetRepository(sessions)
    asyncio.run(repository.create(dataset))
    stored = asyncio.run(repository.read_record(dataset.dataset_id))

    assert stored.dataset == dataset
    assert not hasattr(dataset, "created_at")
    assert not hasattr(dataset, "updated_at")
    assert stored.created_at == sessions.row.created_at
    assert stored.updated_at == sessions.row.updated_at
    assert stored.created_at.tzinfo is not None
    assert dataset.construction_spec == {"language": "en"}


def test_reading_or_mutating_supplied_evidence_does_not_change_case_digest() -> None:
    quote = {"document_title": "Paper B", "quote": "Preheated at 200 C."}
    snapshot = {
        "question": "Compare preheating in A and B.",
        "inspected_sources": [quote],
    }
    now = datetime.now(timezone.utc).isoformat()
    case = FeedbackCase(
        case_id="case-1",
        collection_id="col-1",
        session_id="session-1",
        anchor_message_id="answer-1",
        source_signal_ids=(),
        analysis_result_ids=(),
        context_snapshot=snapshot,
        status="needs_annotation",
        created_at=now,
        updated_at=now,
    )
    original_digest = source_digest_for_case(case)
    quote["quote"] = "Changed outside the workbench."
    returned_record = asdict(case)
    returned_record["context_snapshot"]["inspected_sources"][0][
        "quote"
    ] = "Changed by a reader."

    assert (
        case.context_snapshot["inspected_sources"][0]["quote"] == "Preheated at 200 C."
    )
    assert source_digest_for_case(case) == original_digest


def test_case_digest_ignores_workflow_timestamps_and_status() -> None:
    now = datetime.now(timezone.utc).isoformat()
    case = FeedbackCase(
        case_id="case-1",
        collection_id="col-1",
        session_id="session-1",
        anchor_message_id="answer-1",
        source_signal_ids=("signal-1",),
        analysis_result_ids=("analysis-1",),
        context_snapshot={"question": "Compare A and B."},
        status="needs_annotation",
        created_at=now,
        updated_at=now,
    )
    changed_workflow = replace(case, status="accepted", updated_at="2026-10-01T01:00:00+00:00")

    assert source_digest_for_case(changed_workflow) == source_digest_for_case(case)
    assert source_digest_for_case(
        replace(case, context_snapshot={"question": "A different question."})
    ) != source_digest_for_case(case)


def test_coverage_preserves_nested_source_evidence_when_input_is_reused() -> None:
    source = {"document_id": "paper-b", "evidence": {"quote": "Preheated at 200 C."}}
    coverage = EvidenceCoverage(inspected_sources=(source,), coverage_status="partial")
    source["evidence"]["quote"] = "Reused by another analysis."
    response = asdict(coverage)
    response["inspected_sources"][0]["evidence"]["quote"] = "Changed by a consumer."

    assert coverage.inspected_sources[0]["evidence"]["quote"] == "Preheated at 200 C."
