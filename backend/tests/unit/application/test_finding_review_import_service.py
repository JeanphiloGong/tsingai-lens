from __future__ import annotations

from typing import Any

import pytest

from application.evaluation.finding_review_import_service import (
    FindingReviewImportService,
)
from domain.core import Finding

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FeedbackService:
    def __init__(self) -> None:
        self.feedback_calls: list[dict[str, Any]] = []
        self.curation_calls: list[dict[str, Any]] = []
        self.export_calls: list[dict[str, str]] = []
        self.validation_calls: list[dict[str, Any]] = []

    async def export_dataset(self, *, collection_id: str, objective_id: str) -> dict:
        self.export_calls.append(
            {"collection_id": collection_id, "objective_id": objective_id}
        )
        return {
            "items": [
                {
                    "analysis_version": 3,
                    "finding_id": "finding-density",
                    "system_prediction": _finding(),
                    "evidence": [
                        {"evidence_id": "evidence-result"},
                        {"evidence_id": "evidence-condition"},
                    ],
                }
            ]
        }

    async def record_feedback(self, **payload: Any) -> None:
        self.feedback_calls.append(payload)

    async def record_curation(self, **payload: Any) -> None:
        self.curation_calls.append(payload)

    async def validate_curation(self, **payload: Any) -> Finding:
        self.validation_calls.append(payload)
        candidate = Finding.from_mapping(payload["curated_finding"])
        if candidate.to_record() != payload["curated_finding"]:
            raise ValueError(
                "curated_finding must use the complete canonical Finding contract"
            )
        if candidate.key != (
            payload["collection_id"],
            payload["objective_id"],
            payload["analysis_version"],
            payload["finding_id"],
        ):
            raise ValueError("curation cannot change the published Finding identity")
        return candidate

def _identity(**extra: Any) -> dict[str, Any]:
    return {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 3,
        "finding_id": "finding-density",
        **extra,
    }


def _finding() -> dict[str, Any]:
    return {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 3,
        "finding_id": "finding-density",
        "statement": "Within this paper, higher VED coincided with higher density.",
        "factors": ["volumetric energy density"],
        "outcome": "relative density",
        "direction": "increase",
        "assertion_strength": "associative",
        "attribution_scope": "association_only",
        "synthesis_status": "insufficient_confirmation",
        "certainty": 0.5,
        "display_rank": 0,
        "mechanisms": [],
        "scientific_context": {
            "material": [{"name": "alloy", "value": "316L", "unit": None}],
            "sample": [],
            "process": [],
            "test": [],
        },
        "limitations": ["Only one paper directly supports this result."],
        "paper_contributions": [
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-result"],
                "contradicting_evidence_ids": [],
                "context_evidence_ids": ["evidence-condition"],
                "condition_boundary_evidence_ids": [],
            }
        ],
        "origin": "system_generated",
        "source_analysis_version": None,
        "parent_finding_id": None,
        "created_by_user_id": None,
        "created_by_tool_call_id": None,
        "created_at": None,
    }


async def test_import_accepts_canonical_finding_identity() -> None:
    feedback = _FeedbackService()
    result = await FindingReviewImportService(feedback).import_rows(
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


async def test_import_rejects_stale_analysis_version() -> None:
    feedback = _FeedbackService()
    result = await FindingReviewImportService(feedback).import_rows(
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


async def test_import_rejects_unknown_finding() -> None:
    feedback = _FeedbackService()
    result = await FindingReviewImportService(feedback).import_rows(
        rows=[_identity(action="reject", finding_id="missing", issue_type="overclaim")],
        reviewer="expert-1",
    )

    assert result["status"] == "fail"
    assert feedback.feedback_calls == []


async def test_import_applies_curation_with_version_local_evidence() -> None:
    feedback = _FeedbackService()
    result = await FindingReviewImportService(feedback).import_rows(
        rows=[
            _identity(
                action="correct",
                curated_finding=_finding(),
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
            "curated_finding": _finding(),
            "note": None,
            "reviewer": "expert-1",
        }
    ]
    assert feedback.validation_calls == [
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 3,
            "finding_id": "finding-density",
            "curated_finding": _finding(),
        }
    ]


async def test_import_dry_run_rejects_noncanonical_curated_finding() -> None:
    feedback = _FeedbackService()
    malformed = _finding()
    malformed.pop("scientific_context")

    result = await FindingReviewImportService(feedback).import_rows(
        rows=[_identity(action="correct", curated_finding=malformed)],
        reviewer="expert-1",
        dry_run=True,
    )

    assert result["status"] == "fail"
    assert "complete canonical Finding contract" in result["errors"][0]["message"]
    assert feedback.curation_calls == []


async def test_import_dry_run_rejects_cross_identity_curated_finding() -> None:
    feedback = _FeedbackService()
    cross_identity = _finding()
    cross_identity["objective_id"] = "objective-other"

    result = await FindingReviewImportService(feedback).import_rows(
        rows=[_identity(action="correct", curated_finding=cross_identity)],
        reviewer="expert-1",
        dry_run=True,
    )

    assert result["status"] == "fail"
    assert "cannot change the published Finding identity" in result["errors"][0]["message"]
    assert feedback.curation_calls == []


async def test_import_dry_run_rejects_invalid_curated_status() -> None:
    feedback = _FeedbackService()

    result = await FindingReviewImportService(feedback).import_rows(
        rows=[
            _identity(
                action="correct",
                curated_status="bogus",
                curated_finding=_finding(),
            )
        ],
        reviewer="expert-1",
        dry_run=True,
    )

    assert result["status"] == "fail"
    assert result["errors"] == [
        {"line": 1, "message": "correct requires a valid curated_status"}
    ]
    assert feedback.curation_calls == []


async def test_import_rejects_retired_review_jsonl_aliases() -> None:
    feedback = _FeedbackService()

    result = await FindingReviewImportService(feedback).import_rows(
        rows=[_identity(expert_action="accept", expert_note="legacy")],
        reviewer="expert-1",
        dry_run=True,
    )

    assert result["status"] == "fail"
    assert result["errors"] == [
        {
            "line": 1,
            "message": "expert_action and expert_note are not review JSONL fields",
        }
    ]
    assert feedback.export_calls == []


async def test_import_rejects_claim_identity_instead_of_ignoring_it() -> None:
    feedback = _FeedbackService()
    result = await FindingReviewImportService(feedback).import_rows(
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
