from __future__ import annotations

import logging
from asyncio import (
    CancelledError,
    Task,
    create_task,
    get_running_loop,
    run_coroutine_threadsafe,
)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from infra.source.config.pipeline_mode import IndexingMethod
from infra.source.config.source_runtime_config import (
    CacheConfig,
    InputConfig,
    InputStorageConfig,
    SourceRuntimeConfig,
    StorageConfig,
)

from application.core.document_profiles.service import (
    DocumentProfileService,
)
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from application.pipeline.collection_build.config import CollectionBuildPipelineConfig
from application.pipeline.collection_build.context import (
    CollectionBuildContext,
    SourceArtifactBuilder,
)
from application.pipeline.collection_build.definitions import (
    ARTIFACT_REGISTRY,
    COLLECTION_BUILD_NODE_DEFINITIONS,
    DOCUMENT_PROFILES,
    OBJECTIVE_CANDIDATES,
    SOURCE_ARTIFACTS,
    dependency_graph_for_mode,
)
from application.pipeline.collection_build import nodes
from application.pipeline.collection_build.runner import CollectionBuildPipelineRunner
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from domain.pipeline import PipelineNodeStatus, PipelineRun, PipelineRunStatus
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
}
_OBJECTIVE_PROGRESS_PUBLIC_STAGE = {
    "objective_paper_skim_started": "objective_paper_skim_started",
    "objective_discovery_started": "objective_discovery_started",
    "objective_discovery_batch_finished": "objective_discovery_started",
}
_OBJECTIVE_PROGRESS_UPDATE_INTERVAL = 5


class CollectionBuildPreconditionError(ValueError):
    """Raised before task creation when a collection cannot be processed."""


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
        self._active_build_tasks: set[Task[dict]] = set()

    async def queue_build(
        self,
        collection_id: str,
        *,
        mode: IndexingMethod | str = IndexingMethod.Standard,
        verbose: bool = False,
        additional_context: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict:
        await self.collection_service.get_collection(collection_id)
        if not await self.collection_service.list_files(collection_id):
            raise CollectionBuildPreconditionError(
                "The collection contains no files available for building"
            )
        task = await self.task_service.create_task(
            collection_id=collection_id,
            task_type="build",
            mode=str(mode),
        )
        logger.info(
            "Queued build task task_id=%s collection_id=%s mode=%s verbose=%s",
            task["task_id"],
            collection_id,
            task["mode"],
            verbose,
        )
        background_task = create_task(
            self.run_task(
                task["task_id"],
                collection_id,
                verbose=verbose,
                additional_context=additional_context,
                request_id=request_id,
            )
        )
        self._active_build_tasks.add(background_task)
        background_task.add_done_callback(self._active_build_tasks.discard)
        background_task.add_done_callback(self._log_unexpected_build_failure)
        return task

    @staticmethod
    def _log_unexpected_build_failure(task: Task[dict]) -> None:
        try:
            task.result()
        except CancelledError:
            logger.info("Build task cancelled during backend shutdown")
        except Exception:  # noqa: BLE001
            logger.exception("Build task crashed after scheduling")

    def _resolve_build_source_artifacts(self) -> SourceArtifactBuilder:
        global build_source_artifacts
        if build_source_artifacts is None:
            from infra.source.runtime.build_source_artifacts import (
                build_source_artifacts as resolved_build_source_artifacts,
            )

            build_source_artifacts = resolved_build_source_artifacts
        return cast(SourceArtifactBuilder, build_source_artifacts)

    def _build_pipeline_config(
        self,
        collection_id: str,
        *,
        mode: IndexingMethod | str = IndexingMethod.Standard,
        verbose: bool = False,
        source_additional_context: dict[str, Any] | None = None,
    ) -> CollectionBuildPipelineConfig:
        paths = self.collection_service.get_paths(collection_id)
        return CollectionBuildPipelineConfig(
            source=SourceRuntimeConfig(
                root_dir=str(paths.collection_dir),
                input=InputConfig(
                    storage=InputStorageConfig(base_dir=str(paths.input_dir)),
                    file_type="document",
                    encoding="utf-8",
                    file_pattern=r".*\.(txt|pdf)$",
                ),
                output=StorageConfig(base_dir=str(paths.output_dir)),
                cache=CacheConfig(base_dir="../cache"),
            ),
            mode=mode or IndexingMethod.Standard,
            verbose=verbose,
            source_additional_context=source_additional_context,
        )

    async def run_task(
        self,
        task_id: str,
        collection_id: str,
        verbose: bool = False,
        additional_context: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        request_token = bind_request_id(request_id) if request_id else None
        try:
            build = await self.task_service.repository.read_build(task_id)
            if build is None or build.collection_id != collection_id:
                raise RuntimeError(f"build not found for task: {task_id}")
            task = await self.task_service.get_task(task_id)
            config = self._build_pipeline_config(
                collection_id,
                mode=build.mode,
                verbose=verbose,
                source_additional_context=additional_context,
            )
            output_dir = Path(config.source.output.base_dir)
            await self.collection_service.update_collection(
                collection_id, status="running"
            )

            context = CollectionBuildContext(
                task_id=task_id,
                build_id=build.build_id,
                collection_id=collection_id,
                task_service=self.task_service,
                collection_service=self.collection_service,
                artifact_registry_service=self.artifact_registry_service,
                source_artifact_repository=self.source_artifact_repository,
                document_profile_service=self.document_profile_service,
                research_objective_service=self.research_objective_service,
                build_source_artifacts=self._resolve_build_source_artifacts(),
                objective_progress_callback=self._build_objective_progress_callback(
                    task_id,
                    collection_id,
                ),
            )
            pipeline_run = PipelineRun.create(
                pipeline_name="collection_build",
                mode=build.mode,
                run_id=task_id,
                scope_type="collection",
                scope_id=collection_id,
                node_dependencies=dependency_graph_for_mode(build.mode),
                created_at=str(task["created_at"]),
                output_build_id=build.build_id,
            )
            pipeline_run = await self._build_runner().run(
                context,
                config,
                pipeline_run,
            )
            final_status = self._resolve_final_status(context, pipeline_run)
            pipeline_run = pipeline_run.finish(
                PipelineRunStatus(final_status),
                datetime.now(timezone.utc).isoformat(),
            )
            artifacts = context.state.get("artifacts")
            output_path = (
                artifacts.get("output_path")
                if isinstance(artifacts, dict)
                else str(output_dir)
            )
            final_task = await self.task_service.finish_task(
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
                pipeline_run=pipeline_run,
            )
            logger.info(
                "Build task progress task_id=%s collection_id=%s stage=%s progress_percent=%s status=%s",
                task_id,
                collection_id,
                final_task.get("current_stage"),
                final_task.get("progress_percent"),
                final_task.get("status"),
            )
            await self.collection_service.update_collection(
                collection_id, status=final_status
            )
            return await self.task_service.get_task(task_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Build task failed task_id=%s collection_id=%s",
                task_id,
                collection_id,
            )
            record = await self.task_service.get_task(task_id)
            errors = list(record.get("errors", []))
            if str(exc) not in errors:
                errors.append(str(exc))
            await self.task_service.finish_task(
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
            await self.collection_service.update_collection(
                collection_id, status="failed"
            )
            raise
        finally:
            if request_token is not None:
                clear_request_id(request_token)

    def _build_runner(self) -> CollectionBuildPipelineRunner:
        return CollectionBuildPipelineRunner(
            {
                SOURCE_ARTIFACTS: nodes.build_source_artifacts,
                ARTIFACT_REGISTRY: nodes.register_artifacts,
                DOCUMENT_PROFILES: nodes.build_document_profiles,
                OBJECTIVE_CANDIDATES: nodes.discover_and_replace_objective_candidates,
            },
            definitions=COLLECTION_BUILD_NODE_DEFINITIONS,
        )

    def _resolve_final_status(
        self,
        context: CollectionBuildContext,
        pipeline_run: PipelineRun,
    ) -> str:
        if (
            pipeline_run.node(SOURCE_ARTIFACTS).status
            is not PipelineNodeStatus.SUCCEEDED
        ):
            return "failed"
        if pipeline_run.errors:
            return "partial_success"
        failed_source_document_count = pipeline_run.node(
            SOURCE_ARTIFACTS
        ).output_summary.get("source_failed_document_count", 0)
        if (
            isinstance(failed_source_document_count, int)
            and failed_source_document_count > 0
        ):
            return "partial_success"
        failed_source_unit_count = pipeline_run.node(
            OBJECTIVE_CANDIDATES
        ).output_summary.get("extraction_failed_source_unit_count", 0)
        if isinstance(failed_source_unit_count, int) and failed_source_unit_count > 0:
            return "partial_success"
        return "completed"

    def _build_objective_progress_callback(self, task_id: str, collection_id: str):
        loop = get_running_loop()
        last_update: dict[str, tuple[str, int | None, int | None, int | None]] = {
            "value": ("", None, None, None),
        }

        def callback(progress_detail: dict[str, Any]) -> None:
            phase = str(progress_detail.get("phase") or "").strip()
            if not phase:
                return
            current = self._safe_int(progress_detail.get("current"))
            total = self._safe_int(progress_detail.get("total"))
            window_position = self._safe_int(
                progress_detail.get("active_window_position")
            )
            previous_phase, previous_current, previous_total, previous_window = (
                last_update["value"]
            )
            should_update = (
                phase != previous_phase
                or total != previous_total
                or window_position != previous_window
                or current is None
                or total is None
                or current == 1
                or current >= total
                or previous_current is None
                or current - previous_current >= _OBJECTIVE_PROGRESS_UPDATE_INTERVAL
            )
            if not should_update:
                return
            last_update["value"] = (phase, current, total, window_position)
            public_stage = _OBJECTIVE_PROGRESS_PUBLIC_STAGE.get(
                phase,
                "objective_discovery_started",
            )
            record = run_coroutine_threadsafe(
                self.task_service.update_task(
                    task_id,
                    current_stage=public_stage,
                    progress_percent=_OBJECTIVE_PROGRESS_STAGE_PERCENT.get(
                        public_stage,
                        76,
                    ),
                    progress_detail=progress_detail,
                ),
                loop,
            ).result()
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
