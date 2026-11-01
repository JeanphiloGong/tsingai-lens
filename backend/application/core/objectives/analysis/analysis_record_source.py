"""Choose the scientific record owner for a fixed Objective analysis."""

from __future__ import annotations

from exceptions import ResourceConflictException, ResourceNotFoundException
from repositories.objective_repository import ObjectiveAnalysis, ObjectiveRepo


def is_experiment_backed_analysis(analysis: ObjectiveAnalysis | None) -> bool:
    """Return whether an analysis publishes through PaperExperiment records."""

    return (
        analysis is not None
        and analysis.origin == "system_generated"
        and analysis.scientific_record_source == "experiment_graph"
    )


async def should_read_experiment_projection(
    *,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> bool:
    """Select the projection only for automatic experiment-backed versions.

    Authored and hybrid versions retain their immutable authored snapshots.
    Selection follows the completed saved version, independent of runtime wiring.
    """

    analysis = await ObjectiveRepo.read_analysis(
        collection_id, objective_id, analysis_version
    )
    if analysis is None:
        raise ResourceNotFoundException(
            "Analysis snapshot not found.",
            data={
                "code": "analysis_snapshot_not_found",
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": analysis_version,
            },
        )
    if analysis.status != "succeeded":
        raise ResourceConflictException(
            "Analysis snapshot is not completed.",
            data={
                "code": "analysis_snapshot_not_completed",
                "analysis_version": analysis_version,
            },
        )
    return is_experiment_backed_analysis(analysis)


__all__ = [
    "is_experiment_backed_analysis",
    "should_read_experiment_projection",
]
