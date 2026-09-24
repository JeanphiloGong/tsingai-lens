from __future__ import annotations

import pytest

from domain.evaluation import FindingCuration, FindingFeedback
from infra.persistence.postgres.models.experiment_finding import ExperimentFindingRow
from infra.persistence.postgres.finding_review_repository import (
    PostgresFindingReviewRepository,
)
from tests.integration.persistence.test_postgres_objectives import (
    COLLECTION_ID,
    OBJECTIVE_ID,
    _analysis_contributions,
    _analysis_evidence,
    _finding,
    _queue_and_claim,
)


pytest_plugins = ("tests.integration.persistence.test_postgres_objectives",)
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.filterwarnings("error:DELETE statement has a cartesian product"),
]


async def _publish_next_analysis(objective_repository):
    _, analysis = await _queue_and_claim(objective_repository)
    version = analysis.analysis_version
    await objective_repository.publish_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        version,
        contributions=_analysis_contributions(version),
        evidence_records=_analysis_evidence(version),
        findings=(_finding(version),),
    )
    return analysis


async def test_finding_review_round_trips_published_analysis_identity(
    objective_repository,
) -> None:
    analysis = await _publish_next_analysis(objective_repository)
    reviews = PostgresFindingReviewRepository(objective_repository.session_factory)
    finding = _finding(analysis.analysis_version)

    feedback = await reviews.upsert_feedback(
        FindingFeedback.from_mapping(
            {
                "feedback_id": "feedback-1",
                "collection_id": COLLECTION_ID,
                "objective_id": OBJECTIVE_ID,
                "analysis_version": analysis.analysis_version,
                "finding_id": finding.finding_id,
                "review_status": "correct",
                "issue_type": "none",
                "reviewer": "expert-1",
                "created_at": "2026-08-27T00:00:00+00:00",
            }
        )
    )
    curation = await reviews.upsert_curation(
        FindingCuration.from_mapping(
            {
                "curation_id": "curation-1",
                "collection_id": COLLECTION_ID,
                "objective_id": OBJECTIVE_ID,
                "analysis_version": analysis.analysis_version,
                "finding_id": finding.finding_id,
                "curated_status": "limited",
                "curated_finding": {
                    **finding.to_record(),
                    "statement": (
                        "Higher laser power was associated with strength only "
                        "within the reported process windows."
                    ),
                },
                "updated_at": "2026-08-27T00:00:00+00:00",
            }
        )
    )

    assert await reviews.list_feedback(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
        finding.finding_id,
    ) == (feedback,)
    assert await reviews.list_curations(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
        finding.finding_id,
    ) == (curation,)


async def test_finding_review_accepts_experiment_backed_finding_row(
    objective_repository,
) -> None:
    analysis = await _publish_next_analysis(objective_repository)
    finding = _finding(analysis.analysis_version)
    async with objective_repository.session_factory.begin() as session:
        session.add(
            ExperimentFindingRow(
                finding_id=finding.finding_id,
                collection_id=COLLECTION_ID,
                objective_id=OBJECTIVE_ID,
                analysis_version=analysis.analysis_version,
                statement=finding.statement,
                factors_json=list(finding.factors),
                outcome=finding.outcome,
                direction=finding.direction,
                assertion_strength=finding.assertion_strength,
                attribution_scope=finding.attribution_scope,
                synthesis_status=finding.synthesis_status,
                certainty=finding.certainty,
                display_rank=finding.display_rank,
                mechanisms_json=[item.to_record() for item in finding.mechanisms],
                scientific_context_json=finding.scientific_context.to_record(),
                limitations_json=list(finding.limitations),
                origin="system_generated",
                source_analysis_version=None,
                parent_finding_id=None,
                created_by_user_id=None,
                created_by_tool_call_id=None,
                created_at=None,
                warnings_json=list(finding.warnings),
            )
        )

    reviews = PostgresFindingReviewRepository(objective_repository.session_factory)
    feedback = await reviews.upsert_feedback(
        FindingFeedback.from_mapping(
            {
                "feedback_id": "experiment-feedback-1",
                "collection_id": COLLECTION_ID,
                "objective_id": OBJECTIVE_ID,
                "analysis_version": analysis.analysis_version,
                "finding_id": finding.finding_id,
                "review_status": "correct",
                "issue_type": "none",
                "reviewer": "experiment-reviewer",
                "created_at": "2026-08-27T00:00:00+00:00",
            }
        )
    )
    assert feedback.finding_id == finding.finding_id


async def test_publishing_new_analysis_preserves_prior_version_artifacts(
    objective_repository,
) -> None:
    first = await _publish_next_analysis(objective_repository)
    second = await _publish_next_analysis(objective_repository)

    first_evidence, first_total = await objective_repository.list_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        first.analysis_version,
    )
    second_evidence, second_total = await objective_repository.list_evidence(
        COLLECTION_ID,
        OBJECTIVE_ID,
        second.analysis_version,
    )
    first_finding = await objective_repository.read_finding(
        COLLECTION_ID,
        OBJECTIVE_ID,
        first.analysis_version,
        "finding-strength",
    )
    second_finding = await objective_repository.read_finding(
        COLLECTION_ID,
        OBJECTIVE_ID,
        second.analysis_version,
        "finding-strength",
    )

    assert first_total == 2
    assert second_total == 2
    assert first_evidence == _analysis_evidence(first.analysis_version)
    assert second_evidence == _analysis_evidence(second.analysis_version)
    assert first_finding == _finding(first.analysis_version)
    assert second_finding == _finding(second.analysis_version)
