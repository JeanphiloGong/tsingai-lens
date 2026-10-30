"""Choose the scientific record owner for a fixed Objective analysis."""

from __future__ import annotations

from repositories.objective_repository import ObjectiveAnalysis, ObjectiveRepository

from .experiment_compatibility_projection import ExperimentCompatibilityProjection


def is_experiment_backed_analysis(analysis: ObjectiveAnalysis | None) -> bool:
    """Return whether an analysis publishes through PaperExperiment records."""

    return (
        analysis is not None
        and analysis.origin == "system_generated"
        and analysis.scientific_record_source == "experiment_graph"
    )


async def should_read_experiment_projection(
    *,
    objective_repository: ObjectiveRepository,
    experiment_projection: ExperimentCompatibilityProjection | None,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> bool:
    """Select the projection only for automatic experiment-backed versions.

    Authored and hybrid versions retain their immutable authored snapshots, even
    when the runtime has a PaperExperiment projection available.
    """

    if experiment_projection is None:
        return False
    analysis = await objective_repository.read_analysis(
        collection_id, objective_id, analysis_version
    )
    return analysis is None or is_experiment_backed_analysis(analysis)


__all__ = [
    "is_experiment_backed_analysis",
    "should_read_experiment_projection",
]
