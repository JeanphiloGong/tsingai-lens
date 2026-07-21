from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from infra.source.config.pipeline_mode import IndexingMethod
from infra.source.config.source_runtime_config import (
    CacheConfig,
    InputConfig,
    InputStorageConfig,
    SourceRuntimeConfig,
    StorageConfig,
)

from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build.definitions import (
    ARTIFACT_REGISTRY,
    DOCUMENT_PROFILES,
    FILES_REGISTERED,
    FINALIZE,
    OBJECTIVE_CANDIDATES,
    SOURCE_ARTIFACTS,
)
from application.pipeline.collection_build.nodes import (
    artifact_registry,
    document_profiles,
    files_registered,
    finalize,
    objective_candidates,
    source_artifacts,
)
from application.pipeline.collection_build.runner import CollectionBuildPipelineRunner
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from domain.ports import SourceArtifactRepository
from utils.logger import bind_request_id, clear_request_id

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised indirectly in runtime, patched in tests
    from infra.source.runtime.build_source_artifacts import (  # type: ignore
        build_source_artifacts,
    )
except Exception:  # noqa: BLE001
    build_source_artifacts = None

_OBJECTIVE_PROGRESS_STAGE_PERCENT = {
    "objective_paper_skim_started": 72,
    "objective_discovery_started": 73,
    "objective_paper_framing_started": 74,
    "objective_evidence_routing_started": 75,
    "objective_evidence_units_started": 76,
    "objective_logic_chains_started": 78,
}
_OBJECTIVE_PROGRESS_UPDATE_INTERVAL = 5


class CollectionBuildPipelineService:
    """Application service for collection build task pipeline execution."""

    def __init__(
        self,
        collection_service: CollectionService,
        task_service: TaskService,
        artifact_registry_service: ArtifactRegistryService,
        source_artifact_repository: SourceArtifactRepository,
        document_profile_service: DocumentProfileService,
        research_objective_service: ResearchObjectiveService,
    ) -> None:
        self.collection_service = collection_service
        self.task_service = task_service
        self.artifact_registry_service = artifact_registry_service
        self.source_artifact_repository = source_artifact_repository
        self.document_profile_service = document_profile_service
        self.research_objective_service = research_objective_service

    def _resolve_build_source_artifacts(self):
        global build_source_artifacts
        if build_source_artifacts is None:
            from infra.source.runtime.build_source_artifacts import (
                build_source_artifacts as resolved_build_source_artifacts,
            )

            build_source_artifacts = resolved_build_source_artifacts
        return build_source_artifacts

    def _build_collection_config(
        self,
        collection_id: str,
    ) -> tuple[SourceRuntimeConfig, Path]:
        paths = self.collection_service.get_paths(collection_id)
        config = SourceRuntimeConfig(
            root_dir=str(paths.collection_dir),
            input=InputConfig(
                storage=InputStorageConfig(base_dir=str(paths.input_dir)),
                file_type="document",
                encoding="utf-8",
                file_pattern=r".*\.(txt|pdf)$",
            ),
            output=StorageConfig(base_dir=str(paths.output_dir)),
            cache=CacheConfig(base_dir="../cache"),
        )
        return config, paths.output_dir

    def run_task_blocking(
        self,
        task_id: str,
        collection_id: str,
        method: IndexingMethod | str = IndexingMethod.Standard,
        verbose: bool = False,
        additional_context: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        return asyncio.run(
            self.run_task(
                task_id,
                collection_id,
                method=method,
                verbose=verbose,
                additional_context=additional_context,
                request_id=request_id,
            )
        )

    async def run_task(
        self,
        task_id: str,
        collection_id: str,
        method: IndexingMethod | str = IndexingMethod.Standard,
        verbose: bool = False,
        additional_context: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        request_token = bind_request_id(request_id) if request_id else None
        try:
            config, output_dir = self._build_collection_config(collection_id)
            self.collection_service.update_collection(collection_id, status="running")
            task = self.task_service.get_task(task_id)
            build = self.task_service.repository.read_build(task_id)
            if build is None or build.collection_id != collection_id:
                raise RuntimeError(f"build not found for task: {task_id}")
            if not task.get("started_at"):
                self.task_service.update_task(task_id, started_at=task["updated_at"])

            context = CollectionBuildContext(
                task_id=task_id,
                build_id=build.build_id,
                collection_id=collection_id,
                task_service=self.task_service,
                collection_service=self.collection_service,
                artifact_registry_service=self.artifact_registry_service,
                source_artifact_repository=self.source_artifact_repository,
                config=config,
                output_dir=output_dir,
                method=method or IndexingMethod.Standard,
                verbose=verbose,
                additional_context=additional_context,
                services={
                    "build_source_artifacts": self._resolve_build_source_artifacts(),
                    "document_profile_service": self.document_profile_service,
                    "research_objective_service": self.research_objective_service,
                    "objective_progress_callback": self._build_objective_progress_callback(
                        task_id,
                        collection_id,
                    ),
                },
            )
            result = await self._build_runner().run(context)
            final_status = self._resolve_final_status(context, result)
            artifacts = context.state.get("artifacts")
            output_path = (
                artifacts.get("output_path")
                if isinstance(artifacts, dict)
                else str(output_dir)
            )
            self.task_service.finish_task(
                task_id,
                status=final_status,
                current_stage="artifacts_ready"
                if final_status != "failed"
                else "failed",
                progress_percent=100,
                progress_detail={
                    "phase": "artifacts_ready"
                    if final_status != "failed"
                    else "failed",
                    "unit": "steps",
                    "message": (
                        "Build artifacts are ready."
                        if final_status != "failed"
                        else "Build failed before artifacts were ready."
                    ),
                },
                output_path=output_path,
                errors=result["errors"],
                warnings=result["warnings"],
            )
            self.collection_service.update_collection(
                collection_id, status=final_status
            )
            return self.task_service.get_task(task_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Build task failed task_id=%s collection_id=%s",
                task_id,
                collection_id,
            )
            record = self.task_service.get_task(task_id)
            errors = list(record.get("errors", []))
            if str(exc) not in errors:
                errors.append(str(exc))
            self.task_service.finish_task(
                task_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                progress_detail={
                    "phase": "failed",
                    "unit": "steps",
                    "message": "Build failed before artifacts were ready.",
                },
                errors=errors,
            )
            self.collection_service.update_collection(collection_id, status="failed")
            raise
        finally:
            if request_token is not None:
                clear_request_id(request_token)

    def _build_runner(self) -> CollectionBuildPipelineRunner:
        return CollectionBuildPipelineRunner(
            {
                FILES_REGISTERED: files_registered.run,
                SOURCE_ARTIFACTS: source_artifacts.run,
                ARTIFACT_REGISTRY: artifact_registry.run,
                DOCUMENT_PROFILES: document_profiles.run,
                OBJECTIVE_CANDIDATES: objective_candidates.run,
                FINALIZE: finalize.run,
            }
        )

    def _resolve_final_status(
        self, context: CollectionBuildContext, result: dict
    ) -> str:
        if context.state.get("final_status"):
            return str(context.state["final_status"])
        node_states = result.get("pipeline_nodes", {})
        if node_states.get(FILES_REGISTERED, {}).get("status") != "succeeded":
            return "failed"
        if node_states.get(SOURCE_ARTIFACTS, {}).get("status") != "succeeded":
            return "failed"
        if result.get("errors"):
            return "partial_success"
        return "completed"

    def _build_objective_progress_callback(self, task_id: str, collection_id: str):
        last_update: dict[str, tuple[str, int | None, int | None]] = {
            "value": ("", None, None),
        }

        def callback(progress_detail: dict[str, Any]) -> None:
            phase = str(progress_detail.get("phase") or "").strip()
            if not phase:
                return
            current = self._safe_int(progress_detail.get("current"))
            total = self._safe_int(progress_detail.get("total"))
            previous_phase, previous_current, previous_total = last_update["value"]
            should_update = (
                phase != previous_phase
                or total != previous_total
                or current is None
                or total is None
                or current == 1
                or current >= total
                or previous_current is None
                or current - previous_current >= _OBJECTIVE_PROGRESS_UPDATE_INTERVAL
            )
            if not should_update:
                return
            last_update["value"] = (phase, current, total)
            record = self.task_service.update_task(
                task_id,
                current_stage=phase,
                progress_percent=_OBJECTIVE_PROGRESS_STAGE_PERCENT.get(phase, 76),
                progress_detail=progress_detail,
            )
            logger.info(
                "Build task progress task_id=%s collection_id=%s stage=%s progress_percent=%s status=%s",
                task_id,
                collection_id,
                record.get("current_stage"),
                record.get("progress_percent"),
                record.get("status"),
            )

        return callback

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
