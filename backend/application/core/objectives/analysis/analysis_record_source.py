"""Choose the scientific record owner for a fixed Objective analysis."""

from __future__ import annotations

from typing import Any

from repositories.objective_repository import ObjectiveAnalysis


def is_experiment_backed_analysis(analysis: ObjectiveAnalysis | None) -> bool:
    """Return whether an analysis publishes through PaperExperiment records."""

    return (
        analysis is not None
        and analysis.origin == "system_generated"
        and analysis.scientific_record_source == "experiment_graph"
    )


async def should_read_experiment_projection(
    *,
    objective_repository: Any,
    experiment_projection: Any,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> bool:
    """Select the projection only for automatic experiment-backed versions.

    Authored and hybrid versions retain their immutable authored snapshots, even
    when the runtime has a PaperExperiment projection available.  A repository
    test double that cannot expose analysis metadata is treated as a native
    projection caller; the production repository always exposes ``read_analysis``.
    """

    if experiment_projection is None:
        return False
    reader = getattr(objective_repository, "read_analysis", None)
    if not callable(reader):
        return True
    analysis = await reader(collection_id, objective_id, analysis_version)
    return analysis is None or is_experiment_backed_analysis(analysis)


__all__ = [
    "is_experiment_backed_analysis",
    "should_read_experiment_projection",
]
