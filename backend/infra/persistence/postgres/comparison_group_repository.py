"""PostgreSQL persistence for optional ComparisonGroups."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.comparison_group_repository import ComparisonGroupRepository
from domain.core.comparison_group import ComparisonGroup
from infra.persistence.postgres.models.comparison_group import (
    ComparisonGroupMemberRow,
    ComparisonGroupRow,
)
from infra.persistence.postgres.models.objective_experiment_selection import (
    ObjectiveExperimentSelectionRow,
)
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord


class PostgresComparisonGroupRepository(ComparisonGroupRepository):
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_group(
        self,
        collection_id: str,
        group: ComparisonGroup,
    ) -> ComparisonGroup:
        async with self.session_factory.begin() as session:
            existing = await session.scalar(
                select(ComparisonGroupRow).where(
                    ComparisonGroupRow.group_id == group.group_id,
                    ComparisonGroupRow.collection_id == collection_id,
                )
            )
            if existing is not None:
                restored = await _group_record(session, existing)
                if restored == group:
                    return restored
                raise ValueError("comparison group identity already exists")
            await _validate_group_context(session, collection_id, group)
            row = ComparisonGroupRow(
                group_id=group.group_id,
                collection_id=collection_id,
                objective_id=group.objective_id,
                analysis_version=group.analysis_version,
                outcome=group.outcome,
                comparison_target=group.comparison_target,
                comparison_basis_json=list(group.comparison_basis),
                normalizations_json=[dict(item) for item in group.normalizations],
                status=group.status,
                limitations_json=list(group.limitations),
            )
            session.add(row)
            session.add_all(
                ComparisonGroupMemberRow(
                    group_id=group.group_id,
                    selection_id=item.selection_id,
                    role=item.role,
                    comparability=item.comparability,
                    reason=item.reason,
                )
                for item in group.members
            )
            await session.flush()
            return group

    async def read_group(
        self,
        collection_id: str,
        group_id: str,
    ) -> ComparisonGroup | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(ComparisonGroupRow).where(
                    ComparisonGroupRow.collection_id == collection_id,
                    ComparisonGroupRow.group_id == group_id,
                )
            )
            return await _group_record(session, row) if row is not None else None

    async def list_groups(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[ComparisonGroup, ...]:
        async with self.session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ComparisonGroupRow)
                    .where(
                        ComparisonGroupRow.collection_id == collection_id,
                        ComparisonGroupRow.objective_id == objective_id,
                        ComparisonGroupRow.analysis_version == analysis_version,
                    )
                    .order_by(ComparisonGroupRow.group_id)
                )
            )
            return tuple([await _group_record(session, row) for row in rows])


async def _validate_group_context(
    session: AsyncSession,
    collection_id: str,
    group: ComparisonGroup,
) -> None:
    analysis = await session.scalar(
        select(ObjectiveAnalysisRecord).where(
            ObjectiveAnalysisRecord.collection_id == collection_id,
            ObjectiveAnalysisRecord.objective_id == group.objective_id,
            ObjectiveAnalysisRecord.analysis_version == group.analysis_version,
        )
    )
    if analysis is None:
        raise ValueError("comparison group analysis snapshot was not found")
    if len(group.members) < 2:
        raise ValueError("cross-paper comparison group requires at least two selections")
    selection_rows = tuple(
        await session.scalars(
            select(ObjectiveExperimentSelectionRow).where(
                ObjectiveExperimentSelectionRow.collection_id == collection_id,
                ObjectiveExperimentSelectionRow.selection_id.in_(
                    item.selection_id for item in group.members
                ),
            )
        )
    )
    by_id = {row.selection_id: row for row in selection_rows}
    if len(by_id) != len(group.members):
        raise ValueError("comparison group references an unknown selection")
    if any(
        row.objective_id != group.objective_id
        or row.analysis_version != group.analysis_version
        or row.outcome != group.outcome
        for row in selection_rows
    ):
        raise ValueError("comparison group members do not share analysis and outcome")
    included = [
        by_id[item.selection_id]
        for item in group.members
        if item.role == "included"
    ]
    if len(included) < 2 or len({row.experiment_id for row in included}) < 2:
        raise ValueError("comparison group requires included selections from multiple experiments")


async def _group_record(
    session: AsyncSession,
    row: ComparisonGroupRow,
) -> ComparisonGroup:
    members = tuple(
        await session.scalars(
            select(ComparisonGroupMemberRow)
            .where(ComparisonGroupMemberRow.group_id == row.group_id)
            .order_by(ComparisonGroupMemberRow.id)
        )
    )
    return ComparisonGroup.from_mapping(
        {
            "group_id": row.group_id,
            "objective_id": row.objective_id,
            "analysis_version": row.analysis_version,
            "outcome": row.outcome,
            "comparison_target": row.comparison_target,
            "comparison_basis": list(row.comparison_basis_json),
            "members": [
                {
                    "selection_id": item.selection_id,
                    "role": item.role,
                    "comparability": item.comparability,
                    "reason": item.reason,
                }
                for item in members
            ],
            "normalizations": list(row.normalizations_json),
            "status": row.status,
            "limitations": list(row.limitations_json),
        }
    )


__all__ = ["PostgresComparisonGroupRepository"]
