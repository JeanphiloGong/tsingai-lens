"""Atomic PostgreSQL writes for automatic experiment analysis graphs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.experiment_analysis_repository import (
    ExperimentAnalysisWrite,
    StoredExperimentAnalysis,
)
from infra.persistence.postgres.comparison_group_repository import _add_group
from infra.persistence.postgres.experiment_finding_repository import _add_finding
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord
from infra.persistence.postgres.objective_experiment_selection_repository import (
    _add_selection,
)
from infra.persistence.postgres.paper_experiment_repository import _add_revision


class PostgresExperimentAnalysisRepository:
    """Commit the graph behind one automatic analysis in one transaction."""

    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def write_graph(
        self,
        graph: ExperimentAnalysisWrite,
    ) -> StoredExperimentAnalysis:
        async with self.session_factory.begin() as session:
            analysis = await session.scalar(
                select(ObjectiveAnalysisRecord)
                .where(
                    ObjectiveAnalysisRecord.collection_id == graph.collection_id,
                    ObjectiveAnalysisRecord.objective_id == graph.objective_id,
                    ObjectiveAnalysisRecord.analysis_version == graph.analysis_version,
                )
                .with_for_update()
            )
            if analysis is None:
                raise ValueError("experiment analysis snapshot was not found")

            revisions = tuple(
                [
                    await _add_revision(
                        session,
                        revision,
                        created_by=graph.created_by,
                    )
                    for revision in graph.revisions
                ]
            )
            revision_ids = {
                (
                    item.revision.experiment_id,
                    item.revision.experiment_version,
                ): item.revision_id
                for item in revisions
            }
            selections = tuple(
                [
                    await _add_selection(
                        session,
                        graph.collection_id,
                        selection,
                        revision_id=revision_ids[
                            (selection.experiment_id, selection.experiment_version)
                        ],
                    )
                    for selection in graph.selections
                ]
            )
            groups = tuple(
                [
                    await _add_group(session, graph.collection_id, group)
                    for group in graph.groups
                ]
            )
            findings = tuple(
                [await _add_finding(session, finding) for finding in graph.findings]
            )
            return StoredExperimentAnalysis(
                revisions=revisions,
                selections=selections,
                groups=groups,
                findings=findings,
            )


__all__ = ["PostgresExperimentAnalysisRepository"]
