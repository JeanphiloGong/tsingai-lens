"""PostgreSQL repository for experiment finding."""

from __future__ import annotations

from typing import (
    Any,
    Mapping,
)

from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    FINDING_ASSERTION_STRENGTHS,
    FINDING_ORIGINS,
    FINDING_SYNTHESIS_STATUSES,
    Finding,
    FindingMechanismRelation,
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
from infra.persistence.postgres.models.comparison_group import (
    ComparisonGroupMemberRow,
    ComparisonGroupRow,
)
from infra.persistence.postgres.models.experiment_finding import (
    ExperimentFindingRow,
    FindingComparisonGroupRow,
    FindingSelectionRow,
)
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord
from infra.persistence.postgres.models.objective_experiment_selection import (
    ObjectiveExperimentSelectionRow,
)
from infra.persistence.postgres.transaction import database_session_scope
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ExperimentFindingRepository:
    """Write and read Findings whose scientific inputs are explicit selections."""

    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_finding(
        self,
        finding: Finding,
        *,
        transaction: AsyncSession | None = None,
    ) -> Finding:
        async with database_session_scope(
            self.session_factory, transaction, write=True
        ) as session:
            return await _add_finding(session, finding)

    async def read_finding(
        self,
        collection_id: str,
        finding_id: str,
        *,
        transaction: AsyncSession | None = None,
    ) -> Finding | None:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            row = await session.scalar(
                select(ExperimentFindingRow).where(
                    ExperimentFindingRow.collection_id == collection_id,
                    ExperimentFindingRow.finding_id == finding_id,
                )
            )
            return await _finding_record(session, row) if row is not None else None

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        transaction: AsyncSession | None = None,
    ) -> tuple[Finding, ...]:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            rows = tuple(
                await session.scalars(
                    select(ExperimentFindingRow)
                    .where(
                        ExperimentFindingRow.collection_id == collection_id,
                        ExperimentFindingRow.objective_id == objective_id,
                        ExperimentFindingRow.analysis_version == analysis_version,
                    )
                    .order_by(ExperimentFindingRow.display_rank, ExperimentFindingRow.finding_id)
                )
            )
            records: list[Finding] = []
            for row in rows:
                records.append(await _finding_record(session, row))
            return tuple(records)


async def _add_finding(
    session: AsyncSession,
    finding: Finding,
) -> Finding:
    if not finding.selection_ids:
        raise ValueError("experiment-backed Finding requires selections")
    if finding.paper_contributions:
        raise ValueError("experiment-backed Finding cannot copy legacy evidence")

    existing = await session.scalar(
        select(ExperimentFindingRow).where(
            ExperimentFindingRow.finding_id == finding.finding_id
        )
    )
    if existing is not None:
        restored = await _finding_record(session, existing)
        if restored == finding:
            return restored
        raise ValueError("finding identity already exists")

    selections, groups = await _validate_context(session, finding)
    row = ExperimentFindingRow(
        finding_id=finding.finding_id,
        collection_id=finding.collection_id,
        objective_id=finding.objective_id,
        analysis_version=finding.analysis_version,
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
        origin=finding.origin,
        source_analysis_version=finding.source_analysis_version,
        parent_finding_id=finding.parent_finding_id,
        created_by_user_id=finding.created_by_user_id,
        created_by_tool_call_id=finding.created_by_tool_call_id,
        created_at=finding.created_at,
        warnings_json=list(finding.warnings),
    )
    session.add(row)
    session.add_all(
        FindingSelectionRow(
            finding_id=finding.finding_id,
            selection_id=selection.selection_id,
        )
        for selection in selections
    )
    session.add_all(
        FindingComparisonGroupRow(
            finding_id=finding.finding_id,
            group_id=group.group_id,
        )
        for group in groups
    )
    await session.flush()
    return finding


async def _validate_context(
    session: AsyncSession,
    finding: Finding,
) -> tuple[tuple[ObjectiveExperimentSelectionRow, ...], tuple[ComparisonGroupRow, ...]]:
    analysis = await session.scalar(
        select(ObjectiveAnalysisRecord).where(
            ObjectiveAnalysisRecord.collection_id == finding.collection_id,
            ObjectiveAnalysisRecord.objective_id == finding.objective_id,
            ObjectiveAnalysisRecord.analysis_version == finding.analysis_version,
        )
    )
    if analysis is None:
        raise ValueError("finding analysis snapshot was not found")

    selection_rows = tuple(
        await session.scalars(
            select(ObjectiveExperimentSelectionRow).where(
                ObjectiveExperimentSelectionRow.collection_id == finding.collection_id,
                ObjectiveExperimentSelectionRow.selection_id.in_(finding.selection_ids),
            )
        )
    )
    by_selection_id = {row.selection_id: row for row in selection_rows}
    if len(by_selection_id) != len(finding.selection_ids):
        raise ValueError("finding references an unknown selection")
    if any(
        row.objective_id != finding.objective_id
        or row.analysis_version != finding.analysis_version
        or row.outcome != finding.outcome
        for row in selection_rows
    ):
        raise ValueError("finding selections do not share analysis and outcome")

    group_rows: tuple[ComparisonGroupRow, ...] = ()
    if finding.comparison_group_ids:
        group_rows = tuple(
            await session.scalars(
                select(ComparisonGroupRow).where(
                    ComparisonGroupRow.collection_id == finding.collection_id,
                    ComparisonGroupRow.group_id.in_(finding.comparison_group_ids),
                )
            )
        )
        by_group_id = {row.group_id: row for row in group_rows}
        if len(by_group_id) != len(finding.comparison_group_ids):
            raise ValueError("finding references an unknown comparison group")
        if any(
            row.objective_id != finding.objective_id
            or row.analysis_version != finding.analysis_version
            or row.outcome != finding.outcome
            for row in group_rows
        ):
            raise ValueError("finding groups do not share analysis and outcome")

    experiment_ids = {row.experiment_id for row in selection_rows}
    if len(experiment_ids) > 1 and not finding.comparison_group_ids:
        raise ValueError("cross-paper Finding requires a comparison group")
    if len(experiment_ids) == 1 and finding.synthesis_status == "agreement":
        raise ValueError("agreement Finding requires independent experiment selections")
    if len(experiment_ids) == 1 and finding.synthesis_status != "single_study":
        raise ValueError("one experiment selection must be marked single_study")
    if len(experiment_ids) > 1 and finding.synthesis_status == "single_study":
        raise ValueError("multiple experiment selections cannot be single_study")

    if group_rows:
        group_members = tuple(
            await session.scalars(
                select(ComparisonGroupMemberRow).where(
                    ComparisonGroupMemberRow.group_id.in_(finding.comparison_group_ids)
                )
            )
        )
        member_ids = {item.selection_id for item in group_members}
        if not set(finding.selection_ids) <= member_ids:
            raise ValueError("finding selection is not a member of its comparison group")

    return selection_rows, group_rows


async def _finding_record(
    session: AsyncSession,
    row: ExperimentFindingRow,
) -> Finding:
    selection_rows = tuple(
        await session.scalars(
            select(FindingSelectionRow)
            .where(FindingSelectionRow.finding_id == row.finding_id)
            .order_by(FindingSelectionRow.selection_id)
        )
    )
    group_rows = tuple(
        await session.scalars(
            select(FindingComparisonGroupRow)
            .where(FindingComparisonGroupRow.finding_id == row.finding_id)
            .order_by(FindingComparisonGroupRow.group_id)
        )
    )
    return Finding(
        collection_id=finding_text(row.collection_id) or "",
        objective_id=finding_text(row.objective_id) or "",
        analysis_version=finding_positive_int(row.analysis_version),
        finding_id=finding_text(row.finding_id)
        or finding_stable_id(
            "finding",
            row.objective_id,
            row.analysis_version,
            finding_strings(list(row.factors_json)),
            finding_text(row.outcome) or "",
            None,
        ),
        statement=finding_text(row.statement) or "",
        factors=finding_strings(list(row.factors_json)),
        outcome=finding_text(row.outcome) or "",
        direction=finding_choice(
            row.direction, SCIENTIFIC_RESULT_DIRECTIONS, "unknown"
        ),
        assertion_strength=finding_choice(
            row.assertion_strength, FINDING_ASSERTION_STRENGTHS, "descriptive"
        ),
        attribution_scope=finding_choice(
            row.attribution_scope,
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        synthesis_status=finding_choice(
            row.synthesis_status,
            FINDING_SYNTHESIS_STATUSES,
            "insufficient_confirmation",
        ),
        certainty=finding_certainty(row.certainty),
        display_rank=finding_non_negative_int(row.display_rank),
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
                            list(row.mechanisms_json)
                            if isinstance(list(row.mechanisms_json), (list, tuple))
                            else ()
                        )
                        if isinstance(item, Mapping)
                    )
                )
            )
        ),
        scientific_context=_stored_scientific_context(row.scientific_context_json),
        limitations=finding_strings(list(row.limitations_json)),
        paper_contributions=(),
        origin=finding_choice(row.origin, FINDING_ORIGINS, "system_generated"),
        source_analysis_version=finding_positive_int(row.source_analysis_version)
        or None,
        parent_finding_id=finding_text(row.parent_finding_id),
        created_by_user_id=finding_text(row.created_by_user_id),
        created_by_tool_call_id=finding_text(row.created_by_tool_call_id),
        created_at=finding_datetime_or_none(row.created_at),
        warnings=finding_strings(list(row.warnings_json)),
        selection_ids=finding_strings([item.selection_id for item in selection_rows]),
        comparison_group_ids=finding_strings([item.group_id for item in group_rows]),
    )


__all__ = ['ExperimentFindingRepository']


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
