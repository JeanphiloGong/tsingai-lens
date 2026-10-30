"""PostgreSQL repository for comparison group."""

from __future__ import annotations

from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from infra.persistence.postgres.models.comparison_group import (
    ComparisonGroupMemberRow,
    ComparisonGroupRow,
)
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord
from infra.persistence.postgres.models.objective_experiment_selection import (
    ObjectiveExperimentSelectionRow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ComparisonGroupRepository:
    backend_name = "postgresql"

    async def add_group(
        self,
        db: AsyncSession,
        collection_id: str,
        group: ComparisonGroup,
    ) -> ComparisonGroup:
        existing = await db.scalar(
            select(ComparisonGroupRow).where(
                ComparisonGroupRow.group_id == group.group_id,
                ComparisonGroupRow.collection_id == collection_id,
            )
        )
        if existing is not None:
            restored = await load_comparison_group(db, existing)
            if restored == group:
                return restored
            raise ValueError("comparison group identity already exists")
        await _validate_group_context(db, collection_id, group)
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
        db.add(row)
        await db.flush()
        db.add_all(
            ComparisonGroupMemberRow(
                group_id=group.group_id,
                selection_id=item.selection_id,
                role=item.role,
                comparability=item.comparability,
                reason=item.reason,
            )
            for item in group.members
        )
        await db.flush()
        return group

    async def read_group(
        self,
        db: AsyncSession,
        collection_id: str,
        group_id: str,
    ) -> ComparisonGroup | None:
        row = await db.scalar(
            select(ComparisonGroupRow).where(
                ComparisonGroupRow.collection_id == collection_id,
                ComparisonGroupRow.group_id == group_id,
            )
        )
        return await load_comparison_group(db, row) if row is not None else None

    async def list_groups(
        self,
        db: AsyncSession,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[ComparisonGroup, ...]:
        rows = tuple(
            await db.scalars(
                select(ComparisonGroupRow)
                .where(
                    ComparisonGroupRow.collection_id == collection_id,
                    ComparisonGroupRow.objective_id == objective_id,
                    ComparisonGroupRow.analysis_version == analysis_version,
                )
                .order_by(ComparisonGroupRow.group_id)
            )
        )
        return tuple([await load_comparison_group(db, row) for row in rows])


async def _validate_group_context(
    db: AsyncSession,
    collection_id: str,
    group: ComparisonGroup,
) -> None:
    analysis = await db.scalar(
        select(ObjectiveAnalysisRecord).where(
            ObjectiveAnalysisRecord.collection_id == collection_id,
            ObjectiveAnalysisRecord.objective_id == group.objective_id,
            ObjectiveAnalysisRecord.analysis_version == group.analysis_version,
        )
    )
    if analysis is None:
        raise ValueError("comparison group analysis snapshot was not found")
    selection_rows = tuple(
        await db.scalars(
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
    group.validate_experiment_members(
        {selection_id: row.experiment_id for selection_id, row in by_id.items()}
    )


async def load_comparison_group(
    db: AsyncSession,
    row: ComparisonGroupRow,
) -> ComparisonGroup:
    members = tuple(
        await db.scalars(
            select(ComparisonGroupMemberRow)
            .where(ComparisonGroupMemberRow.group_id == row.group_id)
            .order_by(ComparisonGroupMemberRow.id)
        )
    )
    return ComparisonGroup(
        group_id=row.group_id,
        objective_id=row.objective_id,
        analysis_version=row.analysis_version,
        outcome=row.outcome,
        comparison_target=row.comparison_target,
        comparison_basis=tuple(row.comparison_basis_json),
        members=tuple(
            ComparisonGroupMember(
                selection_id=item.selection_id,
                role=item.role,
                comparability=item.comparability,
                reason=item.reason,
            )
            for item in members
        ),
        normalizations=tuple(row.normalizations_json),
        status=row.status,
        limitations=tuple(row.limitations_json),
    )


__all__ = ["ComparisonGroupRepository"]


ComparisonGroupRepo = ComparisonGroupRepository()
