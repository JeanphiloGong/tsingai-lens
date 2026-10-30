"""PostgreSQL repository for objective experiment selection."""

from __future__ import annotations

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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class ObjectiveExperimentSelectionRepository:
    backend_name = "postgresql"

    async def add_selection(
        self,
        db: AsyncSession,
        collection_id: str,
        selection: ObjectiveExperimentSelection,
        *,
        revision_id: int,
    ) -> ObjectiveExperimentSelection:
        return await _add_selection(
            db,
            collection_id,
            selection,
            revision_id=revision_id,
        )

    async def read_selection(
        self,
        db: AsyncSession,
        collection_id: str,
        selection_id: str,
    ) -> ObjectiveExperimentSelection | None:
        row = await db.scalar(
            select(ObjectiveExperimentSelectionRow).where(
                ObjectiveExperimentSelectionRow.collection_id == collection_id,
                ObjectiveExperimentSelectionRow.selection_id == selection_id,
            )
        )
        return await load_experiment_selection(db, row) if row is not None else None

    async def list_selections(
        self,
        db: AsyncSession,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[ObjectiveExperimentSelection, ...]:
        rows = tuple(
            await db.scalars(
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
        return tuple([await load_experiment_selection(db, row) for row in rows])


async def _add_selection(
    db: AsyncSession,
    collection_id: str,
    selection: ObjectiveExperimentSelection,
    *,
    revision_id: int,
) -> ObjectiveExperimentSelection:
    if not collection_id.strip():
        raise ValueError("selection requires collection scope")
    if selection.objective_id == "":
        raise ValueError("selection requires objective")
    existing = await db.scalar(
        select(ObjectiveExperimentSelectionRow).where(
            ObjectiveExperimentSelectionRow.selection_id == selection.selection_id,
            ObjectiveExperimentSelectionRow.collection_id == collection_id,
        )
    )
    if existing is not None:
        restored = await load_experiment_selection(db, existing)
        if restored == selection:
            return restored
        raise ValueError("selection identity already belongs to another record")

    await _validate_analysis(db, collection_id, selection)
    revision = await db.get(PaperExperimentRow, revision_id)
    if revision is None:
        raise ValueError("selection experiment revision was not found")
    if (
        revision.experiment_id != selection.experiment_id
        or revision.experiment_version != selection.experiment_version
    ):
        raise ValueError("selection experiment identity and revision disagree")

    measurements = tuple(
        await db.scalars(
            select(ExperimentMeasurementResultRow).where(
                ExperimentMeasurementResultRow.paper_experiment_id == revision_id,
                ExperimentMeasurementResultRow.measurement_key.in_(
                    selection.measurement_keys
                ),
            )
        )
    )
    comparisons = tuple(
        await db.scalars(
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
    measurements_by_key = {item.measurement_key: item for item in measurements}
    comparisons_by_key = {item.comparison_key: item for item in comparisons}

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
    db.add(row)
    db.add_all(
        SelectionMeasurementRow(
            selection_id=selection.selection_id,
            revision_id=revision_id,
            measurement_id=measurements_by_key[key].id,
            measurement_key=key,
        )
        for key in selection.measurement_keys
    )
    db.add_all(
        SelectionComparisonRow(
            selection_id=selection.selection_id,
            revision_id=revision_id,
            comparison_id=comparisons_by_key[key].id,
            comparison_key=key,
        )
        for key in selection.comparison_keys
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ValueError("selection links failed validation") from exc
    return selection


async def _validate_analysis(
    db: AsyncSession,
    collection_id: str,
    selection: ObjectiveExperimentSelection,
) -> None:
    row = await db.scalar(
        select(ObjectiveAnalysisRecord).where(
            ObjectiveAnalysisRecord.collection_id == collection_id,
            ObjectiveAnalysisRecord.objective_id == selection.objective_id,
            ObjectiveAnalysisRecord.analysis_version == selection.analysis_version,
        )
    )
    if row is None:
        raise ValueError("selection analysis snapshot was not found")


async def load_experiment_selection(
    db: AsyncSession,
    row: ObjectiveExperimentSelectionRow,
) -> ObjectiveExperimentSelection:
    measurement_keys = tuple(
        await db.scalars(
            select(SelectionMeasurementRow.measurement_key)
            .where(SelectionMeasurementRow.selection_id == row.selection_id)
            .order_by(SelectionMeasurementRow.id)
        )
    )
    comparison_keys = tuple(
        await db.scalars(
            select(SelectionComparisonRow.comparison_key)
            .where(SelectionComparisonRow.selection_id == row.selection_id)
            .order_by(SelectionComparisonRow.id)
        )
    )
    return ObjectiveExperimentSelection(
        selection_id=row.selection_id,
        objective_id=row.objective_id,
        analysis_version=row.analysis_version,
        experiment_id=row.experiment_id,
        experiment_version=row.experiment_version,
        outcome=row.outcome,
        measurement_keys=measurement_keys,
        comparison_keys=comparison_keys,
        missing_context=tuple(row.missing_context_json),
        reasons=tuple(row.reasons_json),
    )


__all__ = ["ObjectiveExperimentSelectionRepository"]


ObjectiveExperimentSelectionRepo = ObjectiveExperimentSelectionRepository()
