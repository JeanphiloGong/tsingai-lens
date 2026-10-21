from __future__ import annotations

import pytest

from domain.core import Finding, ObjectiveEvidence
from domain.evaluation import FindingCuration, FindingFeedback
from application.evaluation.record_projection import finding_curation_from_record, finding_feedback_from_record
from infra.persistence.postgres.models.experiment_finding import ExperimentFindingRow
from infra.persistence.postgres.finding_review_repository import (
    PostgresFindingReviewRepository,
)
from tests.integration.persistence.test_postgres_objective_lifecycle import (
    COLLECTION_ID,
    OBJECTIVE_ID,
    _contribution,
    _queue_and_claim,
)


pytest_plugins = ("tests.integration.persistence.test_postgres_objective_lifecycle",)
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.filterwarnings("error:DELETE statement has a cartesian product"),
]


def _analysis_evidence(version: int) -> tuple[ObjectiveEvidence, ...]:
    return tuple(ObjectiveEvidence.from_mapping({
        "collection_id": COLLECTION_ID, "objective_id": OBJECTIVE_ID,
        "analysis_version": version, "document_id": document_id,
        "evidence_id": f"evidence-{document_id}", "source_kind": "text_window",
        "source_ref": f"block-{document_id}", "page_numbers": [2],
        "source_excerpt": "Laser power increased from 100 W to 150 W.",
        "evidence_role": "direct_result", "selection_status": "extracted",
        "selection_reason": "Reports the variable and measured result.",
        "changed_variables": [{"name": "laser power", "baseline_value": 100, "target_value": 150, "unit": "W"}],
        "comparison": {"baseline_label": "100 W", "target_label": "150 W", "axis_names": ["laser power"], "comparable": True},
        "reported_result": {
            "outcome": "tensile strength", "baseline_value": 900, "target_value": 950,
            "value": 950, "unit": "MPa", "direction": "increase",
            "result_text": "Tensile strength increased from 900 to 950 MPa.",
        },
        "attribution_scope": "isolated_effect", "resolution_status": "resolved", "confidence": 0.9,
    }) for document_id in ("doc_a", "doc_b"))


def _finding(version: int) -> Finding:
    return Finding.from_mapping({
        "collection_id": COLLECTION_ID, "objective_id": OBJECTIVE_ID,
        "analysis_version": version, "finding_id": "finding-strength",
        "statement": "Higher laser power was associated with higher tensile strength under the reported conditions.",
        "factors": ["laser power"], "outcome": "tensile strength", "direction": "increase",
        "assertion_strength": "associative", "attribution_scope": "isolated_effect",
        "synthesis_status": "agreement", "certainty": 0.75, "display_rank": 0,
        "limitations": ["Only the reported process windows are comparable."],
        "paper_contributions": [{
            "document_id": document_id, "analysis_status": "analyzed",
            "supporting_evidence_ids": [f"evidence-{document_id}"],
        } for document_id in ("doc_a", "doc_b")],
    })


async def _publish_next_analysis(objective_repository):
    _, analysis = await _queue_and_claim(objective_repository)
    version = analysis.analysis_version
    await objective_repository.publish_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        version,
        contributions=tuple(_contribution(version, document_id) for document_id in ("doc_a", "doc_b")),
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
        finding_feedback_from_record(
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
        finding_curation_from_record(
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
        finding_feedback_from_record(
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
