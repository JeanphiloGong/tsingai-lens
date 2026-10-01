from dataclasses import asdict
from datetime import datetime, timezone

from application.repositories.feedback_dataset_sample_repository import (
    source_digest_for_case,
)
from domain.feedback import Dataset, EvidenceCoverage, FeedbackCase
from infra.persistence.postgres.feedback_dataset_repository import (
    _row_values,
    _to_record,
)
from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetRow


def test_dataset_storage_timestamps_do_not_enter_domain_or_construction_rules() -> None:
    dataset = Dataset(
        "ds-1", "col-1", "Preheating", "sft", {"language": "en"}, 1, "user-1"
    )
    values = _row_values(dataset)
    stored = _to_record(FeedbackDatasetRow(**values))

    assert stored.dataset == dataset
    assert not hasattr(dataset, "created_at")
    assert not hasattr(dataset, "updated_at")
    assert stored.created_at == values["created_at"]
    assert stored.updated_at == values["updated_at"]
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
    original_digest = source_digest_for_case(case.to_record())
    quote["quote"] = "Changed outside the workbench."
    returned_record = case.to_record()
    returned_record["context_snapshot"]["inspected_sources"][0][
        "quote"
    ] = "Changed by a reader."

    assert (
        case.context_snapshot["inspected_sources"][0]["quote"] == "Preheated at 200 C."
    )
    assert source_digest_for_case(case.to_record()) == original_digest


def test_coverage_preserves_nested_source_evidence_when_input_is_reused() -> None:
    source = {"document_id": "paper-b", "evidence": {"quote": "Preheated at 200 C."}}
    coverage = EvidenceCoverage(inspected_sources=(source,), coverage_status="partial")
    source["evidence"]["quote"] = "Reused by another analysis."
    response = asdict(coverage)
    response["inspected_sources"][0]["evidence"]["quote"] = "Changed by a consumer."

    assert coverage.inspected_sources[0]["evidence"]["quote"] == "Preheated at 200 C."
