from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from application.core.document_profiles.service import (
    DocumentProfileService,
)
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from domain.ports import SourceArtifactRepository
from infra.source.runtime.typing.pipeline_run_result import PipelineRunResult


SourceArtifactBuilder = Callable[..., Awaitable[list[PipelineRunResult]]]
ObjectiveProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class CollectionBuildContext:
    task_id: str
    build_id: str
    collection_id: str
    task_service: TaskService
    collection_service: CollectionService
    artifact_registry_service: ArtifactRegistryService
    source_artifact_repository: SourceArtifactRepository
    document_profile_service: DocumentProfileService
    research_objective_service: ResearchObjectiveService
    build_source_artifacts: SourceArtifactBuilder
    objective_progress_callback: ObjectiveProgressCallback | None = None
    state: dict[str, Any] = field(default_factory=dict)
