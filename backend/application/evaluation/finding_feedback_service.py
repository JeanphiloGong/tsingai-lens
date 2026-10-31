"""Record human feedback and curation for published Findings."""

from __future__ import annotations

from datetime import datetime, timezone

from application.source import collection_service
from domain.core.finding import Finding
from domain.evaluation import FindingCuration, FindingFeedback
from domain.evaluation.records import FindingFeedbackDecisionError
from exceptions import RequestInvalidException


from repositories.finding_review_repository import FindingReviewRepo


from application.evaluation.finding_snapshot_service import (
    _require_published_finding,
    _finding_evidence,
    _list_contributions,
    _stable_id,
)


async def record_feedback(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
    review_status: str,
    issue_type: str,
    note: str | None = None,
    reviewer: str | None = None,
) -> FindingFeedback:
    await collection_service.get_collection_for_user(collection_id, user_id)
    created_at = _now_iso()
    try:
        feedback = FindingFeedback(
            feedback_id=_stable_id(
                "feedback",
                collection_id,
                objective_id,
                str(analysis_version),
                finding_id,
                review_status,
                issue_type,
                note or "",
                reviewer or "",
                created_at,
            ),
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
            review_status=review_status,
            issue_type=issue_type,
            note=note,
            reviewer=reviewer,
            created_at=created_at,
        )
    except FindingFeedbackDecisionError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "finding_feedback_invalid"}
        ) from exc

    await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    return await FindingReviewRepo.upsert_feedback(feedback)


async def list_feedback(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
) -> tuple[FindingFeedback, ...]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    return await FindingReviewRepo.list_feedback(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )


async def record_curation(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
    curated_status: str,
    curated_finding: Finding,
    note: str | None = None,
    reviewer: str | None = None,
) -> FindingCuration:
    candidate = await validate_curation(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        curated_finding=curated_finding,
        user_id=user_id,
    )
    updated_at = _now_iso()
    curation = FindingCuration(
        curation_id=_stable_id(
            "curation",
            collection_id,
            objective_id,
            str(analysis_version),
            finding_id,
        ),
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        curated_status=curated_status,
        curated_finding=candidate,
        note=note,
        reviewer=reviewer,
        updated_at=updated_at,
    )
    return await FindingReviewRepo.upsert_curation(curation)


async def validate_curation(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
    curated_finding: Finding,
) -> Finding:
    await collection_service.get_collection_for_user(collection_id, user_id)
    published = await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    candidate = curated_finding
    if candidate.key != published.key:
        raise RequestInvalidException(
            "Curation cannot change the published Finding identity.",
            data={"code": "curation_identity_changed"},
        )
    if tuple(
        (item.document_id, item.analysis_status)
        for item in candidate.paper_contributions
    ) != tuple(
        (item.document_id, item.analysis_status)
        for item in published.paper_contributions
    ):
        raise RequestInvalidException(
            "Curation cannot change Objective paper coverage.",
            data={"code": "curation_coverage_changed"},
        )

    evidence = await _finding_evidence(published)
    contributions = await _list_contributions(
        collection_id, objective_id, analysis_version
    )
    try:
        candidate.validate_sources(evidence, contributions)
    except ValueError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "curation_sources_invalid"}
        ) from exc
    return candidate


async def list_curations(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
) -> tuple[FindingCuration, ...]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    return await FindingReviewRepo.list_curations(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
