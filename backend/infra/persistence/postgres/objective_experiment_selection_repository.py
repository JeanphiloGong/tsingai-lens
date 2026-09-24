"""PostgreSQL persistence for explicit Objective experiment selections."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from application.repositories.transaction import RepositoryTransaction
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord
from infra.persistence.postgres.models.objective_experiment_selection import (
    ObjectiveExperimentSelectionRow,
    SelectionComparisonRow,
    SelectionMeasurementRow,
)
from infra.persistence.postgres.models.paper_experiment import (
    ExperimentComparisonRow,
    ExperimentMeasurementResultRow,
    PaperExperimentRow,
)
from infra.persistence.postgres.transaction import database_session_scope


class PostgresObjectiveExperimentSelectionRepository(
    ObjectiveExperimentSelectionRepository
):
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_selection(
        self,
        collection_id: str,
        selection: ObjectiveExperimentSelection,
        *,
        revision_id: int,
        transaction: RepositoryTransaction | None = None,
    ) -> ObjectiveExperimentSelection:
        async with database_session_scope(
            self.session_factory, transaction, write=True
        ) as session:
            return await _add_selection(
                session,
                collection_id,
                selection,
                revision_id=revision_id,
            )

    async def read_selection(
        self,
        collection_id: str,
        selection_id: str,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> ObjectiveExperimentSelection | None:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            row = await session.scalar(
                select(ObjectiveExperimentSelectionRow).where(
                    ObjectiveExperimentSelectionRow.collection_id == collection_id,
                    ObjectiveExperimentSelectionRow.selection_id == selection_id,
                )
            )
            return await _selection_record(session, row) if row is not None else None

    async def list_selections(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> tuple[ObjectiveExperimentSelection, ...]:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectiveExperimentSelectionRow)
                    .where(
                        ObjectiveExperimentSelectionRow.collection_id == collection_id,
                        ObjectiveExperimentSelectionRow.objective_id == objective_id,
                        ObjectiveExperimentSelectionRow.analysis_version
                        == analysis_version,
                    )
                    .order_by(ObjectiveExperimentSelectionRow.selection_id)
                )
            )
            return tuple(
                [await _selection_record(session, row) for row in rows]
            )


async def _add_selection(
    session: AsyncSession,
    collection_id: str,
    selection: ObjectiveExperimentSelection,
    *,
    revision_id: int,
) -> ObjectiveExperimentSelection:
    if not collection_id.strip():
        raise ValueError("selection requires collection scope")
    if selection.objective_id == "":
        raise ValueError("selection requires objective")
    existing = await session.scalar(
        select(ObjectiveExperimentSelectionRow).where(
            ObjectiveExperimentSelectionRow.selection_id == selection.selection_id,
            ObjectiveExperimentSelectionRow.collection_id == collection_id,
        )
    )
    if existing is not None:
        restored = await _selection_record(session, existing)
        if restored == selection:
            return restored
        raise ValueError("selection identity already belongs to another record")

    await _validate_analysis(session, collection_id, selection)
    revision = await session.get(PaperExperimentRow, revision_id)
    if revision is None:
        raise ValueError("selection experiment revision was not found")
    if (
        revision.experiment_id != selection.experiment_id
        or revision.experiment_version != selection.experiment_version
    ):
        raise ValueError("selection experiment identity and revision disagree")

    measurements = tuple(
        await session.scalars(
            select(ExperimentMeasurementResultRow).where(
                ExperimentMeasurementResultRow.paper_experiment_id == revision_id,
                ExperimentMeasurementResultRow.measurement_key.in_(
                    selection.measurement_keys
                ),
            )
        )
    )
    comparisons = tuple(
        await session.scalars(
            select(ExperimentComparisonRow).where(
                ExperimentComparisonRow.paper_experiment_id == revision_id,
                ExperimentComparisonRow.comparison_key.in_(selection.comparison_keys),
            )
        )
    )
    if len(measurements) != len(selection.measurement_keys):
        raise ValueError("selection references an unknown measurement")
    if len(comparisons) != len(selection.comparison_keys):
        raise ValueError("selection references an unknown comparison")
    if any(item.outcome != selection.outcome for item in measurements):
        raise ValueError("selection measurements use another outcome")
    if any(item.outcome != selection.outcome for item in comparisons):
        raise ValueError("selection comparisons use another outcome")

    row = ObjectiveExperimentSelectionRow(
        selection_id=selection.selection_id,
        collection_id=collection_id,
        objective_id=selection.objective_id,
        analysis_version=selection.analysis_version,
        experiment_id=selection.experiment_id,
        experiment_version=selection.experiment_version,
        revision_id=revision_id,
        outcome=selection.outcome,
        missing_context_json=list(selection.missing_context),
        reasons_json=list(selection.reasons),
    )
    session.add(row)
    session.add_all(
        SelectionMeasurementRow(
            selection_id=selection.selection_id,
            revision_id=revision_id,
            measurement_id=item.id,
            measurement_key=item.measurement_key,
        )
        for item in measurements
    )
    session.add_all(
        SelectionComparisonRow(
            selection_id=selection.selection_id,
            revision_id=revision_id,
            comparison_id=item.id,
            comparison_key=item.comparison_key,
        )
        for item in comparisons
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ValueError("selection links failed validation") from exc
    return selection


async def _validate_analysis(
    session: AsyncSession,
    collection_id: str,
    selection: ObjectiveExperimentSelection,
) -> None:
    row = await session.scalar(
        select(ObjectiveAnalysisRecord).where(
            ObjectiveAnalysisRecord.collection_id == collection_id,
            ObjectiveAnalysisRecord.objective_id == selection.objective_id,
            ObjectiveAnalysisRecord.analysis_version == selection.analysis_version,
        )
    )
    if row is None:
        raise ValueError("selection analysis snapshot was not found")


async def _selection_record(
    session: AsyncSession,
    row: ObjectiveExperimentSelectionRow,
) -> ObjectiveExperimentSelection:
    measurement_keys = tuple(
        await session.scalars(
            select(SelectionMeasurementRow.measurement_key)
            .where(SelectionMeasurementRow.selection_id == row.selection_id)
            .order_by(SelectionMeasurementRow.id)
        )
    )
    comparison_keys = tuple(
        await session.scalars(
            select(SelectionComparisonRow.comparison_key)
            .where(SelectionComparisonRow.selection_id == row.selection_id)
            .order_by(SelectionComparisonRow.id)
        )
    )
    return ObjectiveExperimentSelection.from_mapping(
        {
            "selection_id": row.selection_id,
            "objective_id": row.objective_id,
            "analysis_version": row.analysis_version,
            "experiment_id": row.experiment_id,
            "experiment_version": row.experiment_version,
            "outcome": row.outcome,
            "measurement_keys": list(measurement_keys),
            "comparison_keys": list(comparison_keys),
            "missing_context": list(row.missing_context_json),
            "reasons": list(row.reasons_json),
        }
    )


__all__ = ["PostgresObjectiveExperimentSelectionRepository"]
