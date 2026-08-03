from __future__ import annotations

from domain.evaluation import (
    FindingCuration,
    FindingFeedback,
)
from domain.goal import ExperimentPlanRecord


def test_experiment_plan_record_has_only_objective_identity() -> None:
    plan = ExperimentPlanRecord.from_mapping(
        {
            "plan_id": "plan-1",
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "title": "Validation plan",
            "content": "Compare two processing conditions.",
            "status": "draft",
            "created_at": "2026-07-20T00:00:00+00:00",
            "updated_at": "2026-07-20T00:00:00+00:00",
        }
    )

    assert plan.objective_id == "objective-1"
    assert plan.to_record()["objective_id"] == "objective-1"
    assert "goal_id" not in plan.to_record()


def test_review_records_have_only_objective_identity() -> None:
    feedback = FindingFeedback.from_mapping(
        {
            "feedback_id": "feedback-1",
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "finding_id": "finding-1",
            "review_status": "correct",
            "issue_type": "none",
            "created_at": "2026-07-20T00:00:00+00:00",
        }
    )
    curation = FindingCuration.from_mapping(
        {
            "curation_id": "curation-1",
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "finding_id": "finding-1",
            "curated_status": "supported",
            "curated_finding": {
                "collection_id": "collection-1",
                "objective_id": "objective-1",
                "analysis_version": 1,
                "finding_id": "finding-1",
                "statement": "The reviewed finding.",
                "factors": ["temperature"],
                "outcome": "strength",
                "direction": "increase",
                "assertion_strength": "associative",
                "attribution_scope": "isolated_effect",
                "synthesis_status": "insufficient_confirmation",
                "certainty": 0.5,
                "display_rank": 0,
                "mechanisms": [],
                "scientific_context": {
                    "material": [],
                    "sample": [],
                    "process": [],
                    "test": [],
                },
                "limitations": ["One directly contributing paper."],
                "paper_contributions": [
                    {
                        "document_id": "paper-1",
                        "analysis_status": "analyzed",
                        "supporting_evidence_ids": ["evidence-1"],
                        "contradicting_evidence_ids": [],
                        "context_evidence_ids": [],
                        "condition_boundary_evidence_ids": [],
                    }
                ],
            },
            "updated_at": "2026-07-20T00:00:00+00:00",
        }
    )

    for record in (feedback.to_record(), curation.to_record()):
        assert record["objective_id"] == "objective-1"
        assert "scope_type" not in record
        assert "scope_id" not in record
        assert "claim_id" not in record
