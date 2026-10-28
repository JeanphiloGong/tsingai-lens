"""PostgreSQL repository for finding review."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from domain.core.finding import Finding, FindingMechanismRelation, FindingPaperContribution
from domain.core.finding import _stable_id as finding_stable_id
from domain.core.scientific_fact import ScientificAttribute, ScientificContext
from domain.evaluation.records import FindingCuration, FindingFeedback, _normalize_text
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
            return replace(
                feedback,
                note=_normalize_text(row.note),
                reviewer=_normalize_text(row.reviewer),
                created_at=_isoformat(row.created_at),
            )

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
            return tuple(
                FindingFeedback(
                    feedback_id=row.feedback_id,
                    collection_id=row.collection_id,
                    objective_id=row.objective_id,
                    analysis_version=row.analysis_version,
                    finding_id=row.finding_id,
                    review_status=row.review_status,
                    issue_type=row.issue_type,
                    note=_normalize_text(row.note),
                    reviewer=_normalize_text(row.reviewer),
                    created_at=_isoformat(row.created_at),
                )
                for row in rows
            )

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
            finding = curation.curated_finding
            scientific_context = {}
            for scope, attributes in (
                ("material", finding.scientific_context.material),
                ("sample", finding.scientific_context.sample),
                ("process", finding.scientific_context.process),
                ("test", finding.scientific_context.test),
            ):
                scientific_context[scope] = [
                    {
                        "name": attribute.name,
                        "value": attribute.value,
                        "unit": attribute.unit,
                        **({"context_scope": attribute.context_scope} if attribute.context_scope != "unknown" else {}),
                        **({"applies_to_outcomes": list(attribute.applies_to_outcomes)} if attribute.applies_to_outcomes else {}),
                    }
                    for attribute in attributes
                ]
            row.curated_finding = {
                "collection_id": finding.collection_id,
                "objective_id": finding.objective_id,
                "analysis_version": finding.analysis_version,
                "finding_id": finding.finding_id,
                "statement": finding.statement,
                "factors": list(finding.factors),
                "outcome": finding.outcome,
                "direction": finding.direction,
                "assertion_strength": finding.assertion_strength,
                "attribution_scope": finding.attribution_scope,
                "synthesis_status": finding.synthesis_status,
                "certainty": finding.certainty,
                "display_rank": finding.display_rank,
                "mechanisms": [
                    {
                        "source_term": mechanism.source_term,
                        "relation_type": mechanism.relation_type,
                        "target_term": mechanism.target_term,
                        "direction": mechanism.direction,
                        "assertion_strength": mechanism.assertion_strength,
                        "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
                    }
                    for mechanism in finding.mechanisms
                ],
                "scientific_context": scientific_context,
                "limitations": list(finding.limitations),
                "paper_contributions": [
                    {
                        "document_id": contribution.document_id,
                        "analysis_status": contribution.analysis_status,
                        "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                        "contradicting_evidence_ids": list(
                            contribution.contradicting_evidence_ids
                        ),
                        "context_evidence_ids": list(contribution.context_evidence_ids),
                        "condition_boundary_evidence_ids": list(
                            contribution.condition_boundary_evidence_ids
                        ),
                    }
                    for contribution in finding.paper_contributions
                ],
                "origin": finding.origin,
                "source_analysis_version": finding.source_analysis_version,
                "parent_finding_id": finding.parent_finding_id,
                "created_by_user_id": finding.created_by_user_id,
                "created_by_tool_call_id": finding.created_by_tool_call_id,
                "created_at": finding.created_at.isoformat() if finding.created_at else None,
                **({"selection_ids": list(finding.selection_ids)} if finding.selection_ids else {}),
                **(
                    {"comparison_group_ids": list(finding.comparison_group_ids)}
                    if finding.comparison_group_ids
                    else {}
                ),
                **({"warnings": list(finding.warnings)} if finding.warnings else {}),
            }
            row.note = curation.note
            row.reviewer = curation.reviewer
            row.updated_at = _datetime(curation.updated_at)
            if existing is None:
                session.add(row)
            await session.flush()
            return replace(
                curation,
                curated_finding=replace(finding, certainty=round(finding.certainty, 2)),
                note=_normalize_text(row.note),
                reviewer=_normalize_text(row.reviewer),
                updated_at=_isoformat(row.updated_at),
            )

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
            records = []
            for row in rows:
                stored = row.curated_finding
                context = stored.get("scientific_context") or {}
                attributes_by_scope = {}
                for scope in ("material", "sample", "process", "test"):
                    attributes_by_scope[scope] = tuple(
                        ScientificAttribute(
                            name=item["name"],
                            value=item["value"],
                            unit=item.get("unit"),
                            context_scope=item.get("context_scope", "unknown"),
                            applies_to_outcomes=tuple(item.get("applies_to_outcomes", ())),
                        )
                        for item in context.get(scope, ())
                    )
                finding = Finding(
                    collection_id=stored["collection_id"],
                    objective_id=stored["objective_id"],
                    analysis_version=stored["analysis_version"],
                    finding_id=stored.get("finding_id") or finding_stable_id(
                        "finding", stored["objective_id"], stored["analysis_version"],
                        tuple(stored["factors"]), stored["outcome"],
                        stored.get("supporting_evidence_ids"),
                    ),
                    statement=stored["statement"],
                    factors=tuple(stored["factors"]),
                    outcome=stored["outcome"],
                    direction=stored["direction"],
                    assertion_strength=stored["assertion_strength"],
                    attribution_scope=stored["attribution_scope"],
                    synthesis_status=stored["synthesis_status"],
                    certainty=round(stored["certainty"], 2),
                    display_rank=stored["display_rank"],
                    mechanisms=tuple(
                        FindingMechanismRelation(
                            source_term=item["source_term"],
                            relation_type=item["relation_type"],
                            target_term=item["target_term"],
                            direction=item.get("direction"),
                            assertion_strength=item["assertion_strength"],
                            supporting_evidence_ids=tuple(item.get("supporting_evidence_ids", ())),
                        )
                        for item in stored.get("mechanisms", ())
                    ),
                    scientific_context=ScientificContext(
                        material=attributes_by_scope["material"],
                        sample=attributes_by_scope["sample"],
                        process=attributes_by_scope["process"],
                        test=attributes_by_scope["test"],
                    ),
                    limitations=tuple(stored.get("limitations", ())),
                    paper_contributions=tuple(
                        FindingPaperContribution(
                            document_id=item["document_id"],
                            analysis_status=item["analysis_status"],
                            supporting_evidence_ids=tuple(item.get("supporting_evidence_ids", ())),
                            contradicting_evidence_ids=tuple(item.get("contradicting_evidence_ids", ())),
                            context_evidence_ids=tuple(item.get("context_evidence_ids", ())),
                            condition_boundary_evidence_ids=tuple(item.get("condition_boundary_evidence_ids", ())),
                        )
                        for item in stored.get("paper_contributions", ())
                    ),
                    origin=stored.get("origin", "system_generated"),
                    source_analysis_version=stored.get("source_analysis_version"),
                    parent_finding_id=stored.get("parent_finding_id"),
                    created_by_user_id=stored.get("created_by_user_id"),
                    created_by_tool_call_id=stored.get("created_by_tool_call_id"),
                    created_at=_finding_creation_time(stored.get("created_at")),
                    warnings=tuple(stored.get("warnings", ())),
                    selection_ids=tuple(stored.get("selection_ids", ())),
                    comparison_group_ids=tuple(stored.get("comparison_group_ids", ())),
                )
                records.append(FindingCuration(
                    curation_id=row.curation_id,
                    collection_id=row.collection_id,
                    objective_id=row.objective_id,
                    analysis_version=row.analysis_version,
                    finding_id=row.finding_id,
                    curated_status=row.curated_status,
                    curated_finding=finding,
                    note=_normalize_text(row.note),
                    reviewer=_normalize_text(row.reviewer),
                    updated_at=_isoformat(row.updated_at),
                ))
            return tuple(records)


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


def _finding_creation_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = (str(value).strip() or None) if value is not None else None
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid Finding creation time") from exc
