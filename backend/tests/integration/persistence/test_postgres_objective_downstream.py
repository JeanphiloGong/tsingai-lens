from __future__ import annotations

from domain.evaluation import FindingCuration, FindingFeedback
from infra.persistence.postgres.finding_review_repository import (
    PostgresFindingReviewRepository,
)
from tests.integration.persistence.test_postgres_objectives import (
    _analysis_contributions,
    _analysis_evidence,
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
        contributions=_analysis_contributions(1),
        evidence_records=_analysis_evidence(1),
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
                "curated_finding": {
                    **_finding(1).to_record(),
                    "statement": (
                        "Temperature is associated with strength in this paper."
                    ),
                },
                "updated_at": "2026-07-22T00:00:00+00:00",
            }
        )
    )

    assert feedback.analysis_version == 1
    assert curation.curated_finding.supporting_evidence_ids == (
        "evidence-support-1",
        "evidence-support-2",
    )
    assert reviews.list_feedback(
        "col_source", "objective-1", 1, "finding-1"
    ) == (feedback,)
    assert reviews.list_curations(
        "col_source", "objective-1", 1, "finding-1"
    ) == (curation,)


def test_finding_and_contribution_ids_are_isolated_by_analysis_version(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    objectives = _prepare_candidate(source_repository, builds)
    _, first_analysis = _queue_and_claim(objectives)
    objectives.publish_analysis(
        "col_source",
        "objective-1",
        first_analysis.analysis_version,
        contributions=_analysis_contributions(1),
        evidence_records=_analysis_evidence(1),
        findings=(_finding(1),),
    )
    _, queued = objectives.queue_analysis(
        "col_source",
        "objective-1",
        pipeline_version="test.v2",
        model_name="test-model",
        prompt_versions={"finding": "v2"},
    )
    second_analysis = objectives.claim_analysis(
        "col_source", "objective-1", queued.analysis_version
    )
    assert second_analysis is not None
    objectives.publish_analysis(
        "col_source",
        "objective-1",
        second_analysis.analysis_version,
        contributions=_analysis_contributions(2),
        evidence_records=_analysis_evidence(2),
        findings=(_finding(2),),
    )

    first_finding = objectives.read_finding(
        "col_source", "objective-1", 1, "finding-1"
    )
    second_finding = objectives.read_finding(
        "col_source", "objective-1", 2, "finding-1"
    )

    assert first_finding is not None
    assert second_finding is not None
    assert first_finding.analysis_version == 1
    assert second_finding.analysis_version == 2
    assert objectives.list_contributions("col_source", "objective-1", 1) == tuple(
        sorted(_analysis_contributions(1), key=lambda item: item.document_id)
    )
    assert objectives.list_contributions("col_source", "objective-1", 2) == tuple(
        sorted(_analysis_contributions(2), key=lambda item: item.document_id)
    )
