from __future__ import annotations

from typing import Any

from application.evaluation.finding_review_import_service import (
    FindingReviewImportService,
)


class _FeedbackService:
    def __init__(self) -> None:
        self.feedback_calls: list[dict[str, Any]] = []
        self.curation_calls: list[dict[str, Any]] = []
        self.export_calls: list[dict[str, str]] = []

    def export_dataset(self, *, collection_id: str, objective_id: str) -> dict:
        self.export_calls.append(
            {"collection_id": collection_id, "objective_id": objective_id}
        )
        return {
            "items": [
                {
                    "analysis_version": 3,
                    "finding_id": "finding-density",
                    "evidence": [
                        {"evidence_id": "evidence-result"},
                        {"evidence_id": "evidence-condition"},
                    ],
                }
            ]
        }

    def record_feedback(self, **payload: Any) -> None:
        self.feedback_calls.append(payload)

    def record_curation(self, **payload: Any) -> None:
        self.curation_calls.append(payload)


def _identity(**extra: Any) -> dict[str, Any]:
    return {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 3,
        "finding_id": "finding-density",
        **extra,
    }


def test_import_accepts_canonical_finding_identity() -> None:
    feedback = _FeedbackService()
    result = FindingReviewImportService(feedback).import_rows(
        rows=[_identity(action="accept", note="Evidence and statement agree.")],
        reviewer="expert-1",
    )

    assert result["status"] == "pass"
    assert result["written_count"] == 1
    assert feedback.export_calls == [
        {"collection_id": "col-1", "objective_id": "objective-1"}
    ]
    assert feedback.feedback_calls == [
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 3,
            "finding_id": "finding-density",
            "review_status": "correct",
            "issue_type": "none",
            "note": "Evidence and statement agree.",
            "reviewer": "expert-1",
        }
    ]


def test_import_rejects_stale_analysis_version() -> None:
    feedback = _FeedbackService()
    result = FindingReviewImportService(feedback).import_rows(
        rows=[_identity(action="accept", analysis_version=2)],
        reviewer="expert-1",
    )

    assert result["status"] == "fail"
    assert result["written_count"] == 0
    assert result["errors"] == [
        {
            "line": 1,
            "message": "Finding version is not present in the current dataset",
        }
    ]
    assert feedback.feedback_calls == []


def test_import_rejects_unknown_finding() -> None:
    feedback = _FeedbackService()
    result = FindingReviewImportService(feedback).import_rows(
        rows=[_identity(action="reject", finding_id="missing", issue_type="overclaim")],
        reviewer="expert-1",
    )

    assert result["status"] == "fail"
    assert feedback.feedback_calls == []


def test_import_applies_curation_with_version_local_evidence() -> None:
    feedback = _FeedbackService()
    result = FindingReviewImportService(feedback).import_rows(
        rows=[
            _identity(
                action="correct",
                suggested_target={
                    "statement": "Within this paper, higher VED coincided with higher density.",
                    "status": "limited",
                    "variables": ["volumetric energy density"],
                    "outcomes": ["relative density"],
                    "evidence_ids": ["evidence-result", "evidence-condition"],
                },
            )
        ],
        reviewer="expert-1",
    )

    assert result["status"] == "pass"
    assert result["written_count"] == 1
    assert feedback.curation_calls == [
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 3,
            "finding_id": "finding-density",
            "curated_status": "limited",
            "curated_statement": (
                "Within this paper, higher VED coincided with higher density."
            ),
            "curated_evidence_ids": ["evidence-result", "evidence-condition"],
            "curated_support_grade": None,
            "curated_review_status": None,
            "curated_variables": ["volumetric energy density"],
            "curated_mediators": [],
            "curated_outcomes": ["relative density"],
            "curated_direction": None,
            "curated_scope_summary": None,
            "note": None,
            "reviewer": "expert-1",
        }
    ]


def test_import_rejects_claim_identity_instead_of_ignoring_it() -> None:
    feedback = _FeedbackService()
    result = FindingReviewImportService(feedback).import_rows(
        rows=[_identity(action="accept", claim_id="legacy-claim")],
        reviewer="expert-1",
    )

    assert result["status"] == "fail"
    assert result["errors"] == [
        {
            "line": 1,
            "message": "claim_id is not part of the Finding review contract",
        }
    ]
    assert feedback.export_calls == []
    assert feedback.feedback_calls == []
