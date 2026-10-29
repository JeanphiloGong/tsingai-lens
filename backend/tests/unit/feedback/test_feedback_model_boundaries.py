import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from domain.feedback import Dataset, FeedbackCase
from repositories.feedback_dataset_repository import FeedbackDatasetRepository
from repositories.feedback_dataset_sample_repository import (
    source_digest_for_case,
)


def test_dataset_storage_timestamps_do_not_enter_domain_or_construction_rules(monkeypatch) -> None:
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
    monkeypatch.setattr("repositories.feedback_dataset_repository.AsyncSessionLocal", sessions)
    repository = FeedbackDatasetRepository()
    asyncio.run(repository.create(dataset))
    stored = asyncio.run(repository.read_record(dataset.dataset_id))

    assert stored.dataset == dataset
    assert not hasattr(dataset, "created_at")
    assert not hasattr(dataset, "updated_at")
    assert stored.created_at == sessions.row.created_at
    assert stored.updated_at == sessions.row.updated_at
    assert stored.created_at.tzinfo is not None
    assert dataset.construction_spec == {"language": "en"}




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
