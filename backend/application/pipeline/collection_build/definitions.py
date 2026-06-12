from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final

from application.pipeline.collection_build.context import CollectionBuildContext


NodeFunction = Callable[[CollectionBuildContext], object]


@dataclass(frozen=True)
class CollectionBuildNodeDefinition:
    node_id: str
    depends_on: tuple[str, ...]
    progress_percent: int
    message: str
    running_stage: str
    completed_stage: str
    running_progress_percent: int | None = None
    wait_for: tuple[str, ...] = ()


FILES_REGISTERED: Final = "files_registered"
SOURCE_ARTIFACTS: Final = "source_artifacts"
ARTIFACT_REGISTRY: Final = "artifact_registry"
DOCUMENT_PROFILES: Final = "document_profiles"
RESEARCH_OBJECTIVES: Final = "research_objectives"
PAPER_FACTS: Final = "paper_facts"
COMPARISON_ROWS: Final = "comparison_rows"
FINALIZE: Final = "finalize"


COLLECTION_BUILD_NODE_DEFINITIONS: Final[tuple[CollectionBuildNodeDefinition, ...]] = (
    CollectionBuildNodeDefinition(
        node_id=FILES_REGISTERED,
        depends_on=(),
        progress_percent=5,
        message="Registered collection files for processing.",
        running_stage="files_registered",
        completed_stage="files_registered",
    ),
    CollectionBuildNodeDefinition(
        node_id=SOURCE_ARTIFACTS,
        depends_on=(FILES_REGISTERED,),
        progress_percent=60,
        message="Source artifacts were generated.",
        running_stage="source_artifacts_started",
        completed_stage="source_artifacts_completed",
        running_progress_percent=25,
    ),
    CollectionBuildNodeDefinition(
        node_id=DOCUMENT_PROFILES,
        depends_on=(SOURCE_ARTIFACTS,),
        progress_percent=70,
        message="Built document profiles.",
        running_stage="document_profiles_started",
        completed_stage="document_profiles_started",
    ),
    CollectionBuildNodeDefinition(
        node_id=RESEARCH_OBJECTIVES,
        depends_on=(DOCUMENT_PROFILES,),
        progress_percent=71,
        message="Built research objectives.",
        running_stage="research_objectives_started",
        completed_stage="research_objectives_started",
    ),
    CollectionBuildNodeDefinition(
        node_id=PAPER_FACTS,
        depends_on=(RESEARCH_OBJECTIVES,),
        progress_percent=80,
        message="Projected extracted evidence into paper facts.",
        running_stage="paper_facts_started",
        completed_stage="paper_facts_started",
    ),
    CollectionBuildNodeDefinition(
        node_id=COMPARISON_ROWS,
        depends_on=(PAPER_FACTS,),
        progress_percent=88,
        message="Generated collection comparison rows.",
        running_stage="comparison_rows_started",
        completed_stage="comparison_rows_started",
    ),
    CollectionBuildNodeDefinition(
        node_id=ARTIFACT_REGISTRY,
        depends_on=(SOURCE_ARTIFACTS,),
        progress_percent=98,
        message="Registered available build artifacts.",
        running_stage="source_artifacts_completed",
        completed_stage="source_artifacts_completed",
    ),
    CollectionBuildNodeDefinition(
        node_id=FINALIZE,
        depends_on=(ARTIFACT_REGISTRY,),
        progress_percent=100,
        message="Finalized collection build state.",
        running_stage="artifacts_ready",
        completed_stage="artifacts_ready",
        wait_for=(
            DOCUMENT_PROFILES,
            RESEARCH_OBJECTIVES,
            PAPER_FACTS,
            COMPARISON_ROWS,
        ),
    ),
)
