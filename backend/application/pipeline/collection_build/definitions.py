from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, Final

from application.pipeline.collection_build.config import CollectionBuildPipelineConfig
from application.pipeline.collection_build.context import CollectionBuildContext
from infra.source.config.pipeline_mode import IndexingMethod


NodeFunction = Callable[
    [CollectionBuildContext, CollectionBuildPipelineConfig],
    object,
]


@dataclass(frozen=True)
class CollectionBuildNodeDefinition:
    node_id: str
    progress_percent: int
    message: str
    running_stage: str
    completed_stage: str
    running_progress_percent: int | None = None


SOURCE_ARTIFACTS: Final = "source_artifacts"
ARTIFACT_REGISTRY: Final = "artifact_registry"
DOCUMENT_PROFILES: Final = "document_profiles"
OBJECTIVE_CANDIDATES: Final = "objective_candidates"
COLLECTION_BUILD_NODE_DEFINITIONS: Final[tuple[CollectionBuildNodeDefinition, ...]] = (
    CollectionBuildNodeDefinition(
        node_id=SOURCE_ARTIFACTS,
        progress_percent=60,
        message="Source artifacts were generated.",
        running_stage="source_artifacts_started",
        completed_stage="source_artifacts_completed",
        running_progress_percent=25,
    ),
    CollectionBuildNodeDefinition(
        node_id=DOCUMENT_PROFILES,
        progress_percent=70,
        message="Built document profiles.",
        running_stage="document_profiles_started",
        completed_stage="document_profiles_completed",
    ),
    CollectionBuildNodeDefinition(
        node_id=OBJECTIVE_CANDIDATES,
        progress_percent=71,
        message="Built research objective candidates.",
        running_stage="objective_candidates_started",
        completed_stage="objective_candidates_completed",
    ),
    CollectionBuildNodeDefinition(
        node_id=ARTIFACT_REGISTRY,
        progress_percent=98,
        message="Registered available build artifacts.",
        running_stage="source_artifacts_completed",
        completed_stage="source_artifacts_completed",
    ),
)


_COLLECTION_BUILD_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    SOURCE_ARTIFACTS: (),
    DOCUMENT_PROFILES: (SOURCE_ARTIFACTS,),
    OBJECTIVE_CANDIDATES: (DOCUMENT_PROFILES,),
    ARTIFACT_REGISTRY: (SOURCE_ARTIFACTS,),
}


COLLECTION_BUILD_MODE_GRAPHS: Final[
    Mapping[str, Mapping[str, tuple[str, ...]]]
] = {
    IndexingMethod.Standard.value: _COLLECTION_BUILD_DEPENDENCIES,
    IndexingMethod.Fast.value: _COLLECTION_BUILD_DEPENDENCIES,
}


def dependency_graph_for_mode(mode: IndexingMethod | str) -> Mapping[str, tuple[str, ...]]:
    mode_name = mode.value if isinstance(mode, IndexingMethod) else str(mode).strip()
    try:
        return COLLECTION_BUILD_MODE_GRAPHS[mode_name]
    except KeyError as exc:
        raise ValueError(f"unknown collection build mode: {mode_name}") from exc
