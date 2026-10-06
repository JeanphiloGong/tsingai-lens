"""Choose the scientific record owner for a fixed Objective analysis."""

from __future__ import annotations

from typing import Any


def is_experiment_backed_analysis(analysis: Any) -> bool:
    """Return whether an analysis publishes through PaperExperiment records."""

    return bool(
        analysis is not None
        and getattr(analysis, "uses_experiment_records", False)
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
