"""PostgreSQL repository for finding review."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import (
    Any,
    Mapping,
)

from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    FINDING_ASSERTION_STRENGTHS,
    FINDING_ORIGINS,
    FINDING_SYNTHESIS_STATUSES,
    PAPER_CONTRIBUTION_STATUSES,
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
)
from domain.core.finding import _certainty as finding_certainty
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _datetime_or_none as finding_datetime_or_none
from domain.core.finding import _non_negative_int as finding_non_negative_int
from domain.core.finding import _positive_int as finding_positive_int
from domain.core.finding import _stable_id as finding_stable_id
from domain.core.finding import _strings as finding_strings
from domain.core.finding import _text as finding_text
from domain.core.scientific_fact import (
    SCIENTIFIC_CONTEXT_SCOPES,
    SCIENTIFIC_RESULT_DIRECTIONS,
    ScientificAttribute,
    ScientificContext,
)
from domain.core.scientific_fact import _choice as scientific_choice
from domain.core.scientific_fact import _scientific_scalar as scientific_scalar
from domain.core.scientific_fact import _terms as scientific_terms
from domain.core.scientific_fact import _text as scientific_text
from domain.evaluation.records import (
    FindingCuration,
    FindingFeedback,
    _normalize_mapping,
    _normalize_text,
)
from infra.persistence.postgres.models.evaluation import (
    FindingCurationRecord,
    FindingFeedbackRecord,
)
from infra.persistence.postgres.models.experiment_finding import ExperimentFindingRow
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FindingReviewRepository:
    backend_name = "postgresql"

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    async def upsert_feedback(
        self, feedback: FindingFeedback
    ) -> FindingFeedback:
        async with self.session_factory.begin() as session:
            await _require_finding(session, feedback)
            existing = await session.get(
                FindingFeedbackRecord, feedback.feedback_id
            )
            if existing is not None and _feedback_key(existing) != _feedback_key(
                feedback
            ):
                raise ValueError("feedback identity cannot be reassigned")
            row = existing or FindingFeedbackRecord(feedback_id=feedback.feedback_id)
            row.collection_id = feedback.collection_id
            row.objective_id = feedback.objective_id
            row.analysis_version = feedback.analysis_version
            row.finding_id = feedback.finding_id
            row.review_status = feedback.review_status
            row.issue_type = feedback.issue_type
            row.note = feedback.note
            row.reviewer = feedback.reviewer
            row.created_at = _datetime(feedback.created_at)
            if existing is None:
                session.add(row)
            await session.flush()
            return _feedback(row)

    async def list_feedback(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingFeedback, ...]:
        async with self.session_factory() as session:
            statement = select(FindingFeedbackRecord).where(
                FindingFeedbackRecord.collection_id == collection_id
            )
            if objective_id is not None:
                statement = statement.where(
                    FindingFeedbackRecord.objective_id == objective_id
                )
            if analysis_version is not None:
                statement = statement.where(
                    FindingFeedbackRecord.analysis_version == analysis_version
                )
            if finding_id is not None:
                statement = statement.where(
                    FindingFeedbackRecord.finding_id == finding_id
                )
            rows = await session.scalars(
                statement.order_by(
                    FindingFeedbackRecord.created_at,
                    FindingFeedbackRecord.feedback_id,
                )
            )
            return tuple(_feedback(row) for row in rows)

    async def upsert_curation(
        self, curation: FindingCuration
    ) -> FindingCuration:
        async with self.session_factory.begin() as session:
            await _require_finding(session, curation)
            existing = await session.get(
                FindingCurationRecord, curation.curation_id
            )
            if existing is not None and _curation_key(existing) != _curation_key(
                curation
            ):
                raise ValueError("curation identity cannot be reassigned")
            row = existing or FindingCurationRecord(curation_id=curation.curation_id)
            row.collection_id = curation.collection_id
            row.objective_id = curation.objective_id
            row.analysis_version = curation.analysis_version
            row.finding_id = curation.finding_id
            row.curated_status = curation.curated_status
            row.curated_finding = curation.curated_finding.to_record()
            row.note = curation.note
            row.reviewer = curation.reviewer
            row.updated_at = _datetime(curation.updated_at)
            if existing is None:
                session.add(row)
            await session.flush()
            return _curation(row)

    async def list_curations(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingCuration, ...]:
        async with self.session_factory() as session:
            statement = select(FindingCurationRecord).where(
                FindingCurationRecord.collection_id == collection_id
            )
            if objective_id is not None:
                statement = statement.where(
                    FindingCurationRecord.objective_id == objective_id
                )
            if analysis_version is not None:
                statement = statement.where(
                    FindingCurationRecord.analysis_version == analysis_version
                )
            if finding_id is not None:
                statement = statement.where(
                    FindingCurationRecord.finding_id == finding_id
                )
            rows = await session.scalars(
                statement.order_by(
                    FindingCurationRecord.updated_at,
                    FindingCurationRecord.curation_id,
                )
            )
            return tuple(_curation(row) for row in rows)


def _feedback_key(value) -> tuple[str, str, int, str]:
    return (
        value.collection_id,
        value.objective_id,
        value.analysis_version,
        value.finding_id,
    )


def _curation_key(value) -> tuple[str, str, int, str]:
    return (
        value.collection_id,
        value.objective_id,
        value.analysis_version,
        value.finding_id,
    )


def _feedback(row: FindingFeedbackRecord) -> FindingFeedback:
    return finding_feedback_from_record(
        {
            "feedback_id": row.feedback_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "analysis_version": row.analysis_version,
            "finding_id": row.finding_id,
            "review_status": row.review_status,
            "issue_type": row.issue_type,
            "note": row.note,
            "reviewer": row.reviewer,
            "created_at": _isoformat(row.created_at),
        }
    )


def _curation(row: FindingCurationRecord) -> FindingCuration:
    return finding_curation_from_record(
        {
            "curation_id": row.curation_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "analysis_version": row.analysis_version,
            "finding_id": row.finding_id,
            "curated_status": row.curated_status,
            "curated_finding": dict(row.curated_finding),
            "note": row.note,
            "reviewer": row.reviewer,
            "updated_at": _isoformat(row.updated_at),
        }
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


async def _require_finding(session: AsyncSession, value: object) -> None:
    row = await session.get(
        ObjectiveAnalysisRecord,
        (
            value.collection_id,
            value.objective_id,
            value.analysis_version,
        ),
    )
    authored_finding = row is not None and any(
        item.get("finding_id") == value.finding_id
        for item in (row.payload or {}).get("findings", ())
    )
    experiment_finding = await session.scalar(
        select(ExperimentFindingRow).where(
            ExperimentFindingRow.collection_id == value.collection_id,
            ExperimentFindingRow.objective_id == value.objective_id,
            ExperimentFindingRow.analysis_version == value.analysis_version,
            ExperimentFindingRow.finding_id == value.finding_id,
        )
    )
    if row is None or (not authored_finding and experiment_finding is None):
        raise ValueError(
            "finding does not exist in the requested objective analysis: "
            f"{value.collection_id}/{value.objective_id}/"
            f"{value.analysis_version}/{value.finding_id}"
        )


__all__ = ['FindingReviewRepository']


def finding_feedback_from_record(payload: Mapping[str, Any]) -> FindingFeedback:
    return FindingFeedback(
        feedback_id=_normalize_text(payload.get("feedback_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        objective_id=_normalize_text(payload.get("objective_id")) or "",
        analysis_version=int(payload.get("analysis_version") or 0),
        finding_id=_normalize_text(payload.get("finding_id")) or "",
        review_status=(_normalize_text(payload.get("review_status")) or "").lower(),
        issue_type=(_normalize_text(payload.get("issue_type")) or "").lower(),
        note=_normalize_text(payload.get("note")), reviewer=_normalize_text(payload.get("reviewer")),
        created_at=_normalize_text(payload.get("created_at")) or "",
    )


def finding_feedback_record(value: FindingFeedback) -> dict[str, Any]:
    return {"feedback_id": value.feedback_id, "collection_id": value.collection_id,
            "objective_id": value.objective_id, "analysis_version": value.analysis_version,
            "finding_id": value.finding_id, "review_status": value.review_status,
            "issue_type": value.issue_type, "note": value.note, "reviewer": value.reviewer,
            "created_at": value.created_at}


def finding_curation_from_record(payload: Mapping[str, Any]) -> FindingCuration:
    return FindingCuration(
        curation_id=_normalize_text(payload.get("curation_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        objective_id=_normalize_text(payload.get("objective_id")) or "",
        analysis_version=int(payload.get("analysis_version") or 0),
        finding_id=_normalize_text(payload.get("finding_id")) or "",
        curated_status=(_normalize_text(payload.get("curated_status")) or "").lower(),
        curated_finding=Finding(
            collection_id=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get("collection_id")
            )
            or "",
            objective_id=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get("objective_id")
            )
            or "",
            analysis_version=finding_positive_int(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "analysis_version"
                )
            ),
            finding_id=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get("finding_id")
            )
            or finding_stable_id(
                "finding",
                _normalize_mapping(payload.get("curated_finding")).get("objective_id"),
                _normalize_mapping(payload.get("curated_finding")).get(
                    "analysis_version"
                ),
                finding_strings(
                    _normalize_mapping(payload.get("curated_finding")).get("factors")
                ),
                finding_text(
                    _normalize_mapping(payload.get("curated_finding")).get("outcome")
                )
                or "",
                _normalize_mapping(payload.get("curated_finding")).get(
                    "supporting_evidence_ids"
                ),
            ),
            statement=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get("statement")
            )
            or "",
            factors=finding_strings(
                _normalize_mapping(payload.get("curated_finding")).get("factors")
            ),
            outcome=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get("outcome")
            )
            or "",
            direction=finding_choice(
                _normalize_mapping(payload.get("curated_finding")).get("direction"),
                SCIENTIFIC_RESULT_DIRECTIONS,
                "unknown",
            ),
            assertion_strength=finding_choice(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "assertion_strength"
                ),
                FINDING_ASSERTION_STRENGTHS,
                "descriptive",
            ),
            attribution_scope=finding_choice(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "attribution_scope"
                ),
                EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
                "descriptive_only",
            ),
            synthesis_status=finding_choice(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "synthesis_status"
                ),
                FINDING_SYNTHESIS_STATUSES,
                "insufficient_confirmation",
            ),
            certainty=finding_certainty(
                _normalize_mapping(payload.get("curated_finding")).get("certainty")
            ),
            display_rank=finding_non_negative_int(
                _normalize_mapping(payload.get("curated_finding")).get("display_rank")
            ),
            mechanisms=tuple(
                (
                    FindingMechanismRelation(
                        source_term=finding_text(item.get("source_term")) or "",
                        relation_type=finding_text(item.get("relation_type")) or "",
                        target_term=finding_text(item.get("target_term")) or "",
                        direction=finding_text(item.get("direction")),
                        assertion_strength=finding_choice(
                            item.get("assertion_strength"),
                            FINDING_ASSERTION_STRENGTHS,
                            "descriptive",
                        ),
                        supporting_evidence_ids=finding_strings(
                            item.get("supporting_evidence_ids")
                        ),
                    )
                    for item in tuple(
                        (
                            dict(item)
                            for item in (
                                _normalize_mapping(payload.get("curated_finding")).get(
                                    "mechanisms"
                                )
                                if isinstance(
                                    _normalize_mapping(
                                        payload.get("curated_finding")
                                    ).get("mechanisms"),
                                    (list, tuple),
                                )
                                else ()
                            )
                            if isinstance(item, Mapping)
                        )
                    )
                )
            ),
            scientific_context=_stored_scientific_context(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "scientific_context"
                )
            ),
            limitations=finding_strings(
                _normalize_mapping(payload.get("curated_finding")).get("limitations")
            ),
            paper_contributions=tuple(
                (
                    FindingPaperContribution(
                        document_id=finding_text(item.get("document_id")) or "",
                        analysis_status=finding_choice(
                            item.get("analysis_status"),
                            PAPER_CONTRIBUTION_STATUSES,
                            "pending",
                        ),
                        supporting_evidence_ids=finding_strings(
                            item.get("supporting_evidence_ids")
                        ),
                        contradicting_evidence_ids=finding_strings(
                            item.get("contradicting_evidence_ids")
                        ),
                        context_evidence_ids=finding_strings(
                            item.get("context_evidence_ids")
                        ),
                        condition_boundary_evidence_ids=finding_strings(
                            item.get("condition_boundary_evidence_ids")
                        ),
                    )
                    for item in tuple(
                        (
                            dict(item)
                            for item in (
                                _normalize_mapping(payload.get("curated_finding")).get(
                                    "paper_contributions"
                                )
                                if isinstance(
                                    _normalize_mapping(
                                        payload.get("curated_finding")
                                    ).get("paper_contributions"),
                                    (list, tuple),
                                )
                                else ()
                            )
                            if isinstance(item, Mapping)
                        )
                    )
                )
            ),
            origin=finding_choice(
                _normalize_mapping(payload.get("curated_finding")).get("origin"),
                FINDING_ORIGINS,
                "system_generated",
            ),
            source_analysis_version=finding_positive_int(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "source_analysis_version"
                )
            )
            or None,
            parent_finding_id=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "parent_finding_id"
                )
            ),
            created_by_user_id=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "created_by_user_id"
                )
            ),
            created_by_tool_call_id=finding_text(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "created_by_tool_call_id"
                )
            ),
            created_at=finding_datetime_or_none(
                _normalize_mapping(payload.get("curated_finding")).get("created_at")
            ),
            warnings=finding_strings(
                _normalize_mapping(payload.get("curated_finding")).get("warnings")
            ),
            selection_ids=finding_strings(
                _normalize_mapping(payload.get("curated_finding")).get("selection_ids")
            ),
            comparison_group_ids=finding_strings(
                _normalize_mapping(payload.get("curated_finding")).get(
                    "comparison_group_ids"
                )
            ),
        ),
        note=_normalize_text(payload.get("note")),
        reviewer=_normalize_text(payload.get("reviewer")),
        updated_at=_normalize_text(payload.get("updated_at")) or "",
    )


def finding_curation_record(value: FindingCuration) -> dict[str, Any]:
    return {"curation_id": value.curation_id, "collection_id": value.collection_id,
            "objective_id": value.objective_id, "analysis_version": value.analysis_version,
            "finding_id": value.finding_id, "curated_status": value.curated_status,
            "curated_finding": value.curated_finding.to_record(), "note": value.note,
            "reviewer": value.reviewer, "updated_at": value.updated_at}


def _context_attributes(records: Any) -> tuple[ScientificAttribute, ...]:
    return tuple(
        ScientificAttribute(
            name=scientific_text(item.get("name")) or "",
            value=(
                scientific_scalar(item.get("value"))
                if scientific_scalar(item.get("value")) is not None
                else ""
            ),
            unit=scientific_text(item.get("unit")),
            context_scope=scientific_choice(
                item.get("context_scope"), SCIENTIFIC_CONTEXT_SCOPES, "unknown"
            ),
            applies_to_outcomes=scientific_terms(item.get("applies_to_outcomes")),
        )
        for item in (records if isinstance(records, (list, tuple)) else ())
        if isinstance(item, Mapping)
    )


def _stored_scientific_context(value: Any) -> ScientificContext:
    if not isinstance(value, Mapping):
        return ScientificContext()
    return ScientificContext(
        material=_context_attributes(value.get("material")),
        sample=_context_attributes(value.get("sample")),
        process=_context_attributes(value.get("process")),
        test=_context_attributes(value.get("test")),
    )
