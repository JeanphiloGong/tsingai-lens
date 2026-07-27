from __future__ import annotations

from domain.evaluation import FindingCuration, FindingFeedback
from infra.persistence.postgres.finding_review_repository import (
    PostgresFindingReviewRepository,
)
from tests.integration.persistence.test_postgres_objectives import (
    _contribution,
    _evidence,
    _finding,
    _prepare_candidate,
    _queue_and_claim,
)


pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)


def test_finding_review_round_trips_versioned_identity(source_repositories) -> None:
    source_repository, builds = source_repositories
    objectives = _prepare_candidate(source_repository, builds)
    _, analysis = _queue_and_claim(objectives)
    objectives.publish_analysis(
        "col_source",
        "objective-1",
        analysis.analysis_version,
        contributions=(_contribution(1),),
        evidence_records=(_evidence(1),),
        findings=(_finding(1),),
    )
    reviews = PostgresFindingReviewRepository(source_repository.session_factory)

    feedback = reviews.upsert_feedback(
        FindingFeedback.from_mapping(
            {
                "feedback_id": "feedback-1",
                "collection_id": "col_source",
                "objective_id": "objective-1",
                "analysis_version": 1,
                "finding_id": "finding-1",
                "review_status": "correct",
                "issue_type": "none",
                "reviewer": "expert-1",
                "created_at": "2026-07-22T00:00:00+00:00",
            }
        )
    )
    curation = reviews.upsert_curation(
        FindingCuration.from_mapping(
            {
                "curation_id": "curation-1",
                "collection_id": "col_source",
                "objective_id": "objective-1",
                "analysis_version": 1,
                "finding_id": "finding-1",
                "curated_status": "limited",
                "curated_statement": "Temperature is associated with strength in this paper.",
                "curated_variables": ["temperature"],
                "curated_outcomes": ["strength"],
                "curated_evidence_ids": ["evidence-1"],
                "updated_at": "2026-07-22T00:00:00+00:00",
            }
        )
    )

    assert feedback.analysis_version == 1
    assert curation.curated_evidence_ids == ("evidence-1",)
    assert reviews.list_feedback(
        "col_source", "objective-1", 1, "finding-1"
    ) == (feedback,)
    assert reviews.list_curations(
        "col_source", "objective-1", 1, "finding-1"
    ) == (curation,)
