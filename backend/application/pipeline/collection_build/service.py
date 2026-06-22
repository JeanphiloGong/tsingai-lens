from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from config import CONFIG_DIR
from infra.source.config.pipeline_mode import IndexingMethod

from application.core.comparison_service import ComparisonService
from application.core.research_view_aggregation_service import ResearchViewAggregationService
from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build.definitions import (
    ARTIFACT_REGISTRY,
    COMPARISON_ROWS,
    DOCUMENT_PROFILES,
    FILES_REGISTERED,
    FINALIZE,
    PAPER_FACTS,
    RESEARCH_OBJECTIVES,
    RESEARCH_UNDERSTANDINGS,
    SOURCE_ARTIFACTS,
)
from application.pipeline.collection_build.nodes import (
    artifact_registry,
    comparison_rows,
    document_profiles,
    files_registered,
    finalize,
    paper_facts,
    research_objectives,
    research_understandings,
    source_artifacts,
)
from application.pipeline.collection_build.runner import CollectionBuildPipelineRunner
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from utils.logger import bind_request_id, clear_request_id

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised indirectly in runtime, patched in tests
    from infra.source.runtime.build_source_artifacts import (  # type: ignore
        build_source_artifacts,
    )
except Exception:  # noqa: BLE001
    build_source_artifacts = None

try:  # pragma: no cover - exercised indirectly in runtime, patched in tests
    from infra.source.config.load_config import load_config  # type: ignore
except Exception:  # noqa: BLE001
    load_config = None


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
        collection_service: CollectionService | None = None,
        task_service: TaskService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        document_profile_service: DocumentProfileService | None = None,
        paper_facts_service: PaperFactsService | None = None,
        comparison_service: ComparisonService | None = None,
        research_objective_service: ResearchObjectiveService | None = None,
        research_view_aggregation_service: ResearchViewAggregationService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.task_service = task_service or TaskService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
            document_profile_service=self.document_profile_service,
        )
        self.research_objective_service = (
            research_objective_service
            or ResearchObjectiveService(
                collection_service=self.collection_service,
                document_profile_service=self.document_profile_service,
            )
        )
        self.comparison_service = comparison_service or ComparisonService(
            collection_service=self.collection_service,
        )
        self.research_view_aggregation_service = (
            research_view_aggregation_service
            or ResearchViewAggregationService(
                collection_service=self.collection_service,
                document_profile_service=self.document_profile_service,
                paper_facts_service=self.paper_facts_service,
                comparison_service=self.comparison_service,
            )
        )

    def _resolve_load_config(self):
        global load_config
        if load_config is None:
            from infra.source.config.load_config import load_config as resolved_load_config

            load_config = resolved_load_config
        return load_config

    def _resolve_build_source_artifacts(self):
        global build_source_artifacts
        if build_source_artifacts is None:
            from infra.source.runtime.build_source_artifacts import (
                build_source_artifacts as resolved_build_source_artifacts,
            )

            build_source_artifacts = resolved_build_source_artifacts
        return build_source_artifacts

    def _load_collection_config(self, collection_id: str) -> tuple[Any, Path]:
        default_config = CONFIG_DIR / "default.yaml"
        if not default_config.is_file():
            raise FileNotFoundError(
                "默认配置不存在，请在 backend/data/configs 下提供 default.yaml"
            )

        resolved_load_config = self._resolve_load_config()
        config = resolved_load_config(default_config.parent, config_filepath=default_config)
        paths = self.collection_service.get_paths(collection_id)
        config.input.storage.base_dir = str(paths.input_dir)
        config.output.base_dir = str(paths.output_dir)
        config.root_dir = str(paths.collection_dir)
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
            config, output_dir = self._load_collection_config(collection_id)
            self.collection_service.update_collection(collection_id, status="running")
            task = self.task_service.get_task(task_id)
            if not task.get("started_at"):
                self.task_service.update_task(task_id, started_at=task["updated_at"])

            context = CollectionBuildContext(
                task_id=task_id,
                collection_id=collection_id,
                task_service=self.task_service,
                collection_service=self.collection_service,
                artifact_registry_service=self.artifact_registry_service,
                config=config,
                output_dir=output_dir,
                method=method or IndexingMethod.Standard,
                verbose=verbose,
                additional_context=additional_context,
                services={
                    "build_source_artifacts": self._resolve_build_source_artifacts(),
                    "document_profile_service": self.document_profile_service,
                    "research_objective_service": self.research_objective_service,
                    "paper_facts_service": self.paper_facts_service,
                    "comparison_service": self.comparison_service,
                    "research_view_aggregation_service": self.research_view_aggregation_service,
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
            self.task_service.update_task(
                task_id,
                status=final_status,
                current_stage="artifacts_ready" if final_status != "failed" else "failed",
                progress_percent=100,
                progress_detail={
                    "phase": "artifacts_ready" if final_status != "failed" else "failed",
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
                finished_at=self.task_service.get_task(task_id)["updated_at"],
            )
            self.collection_service.update_collection(collection_id, status=final_status)
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
            self.task_service.update_task(
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
                finished_at=record["updated_at"],
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
                RESEARCH_OBJECTIVES: research_objectives.run,
                PAPER_FACTS: paper_facts.run,
                COMPARISON_ROWS: comparison_rows.run,
                RESEARCH_UNDERSTANDINGS: research_understandings.run,
                FINALIZE: finalize.run,
            }
        )

    def _resolve_final_status(self, context: CollectionBuildContext, result: dict) -> str:
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
