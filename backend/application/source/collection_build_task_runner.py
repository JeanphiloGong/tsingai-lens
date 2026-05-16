from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from config import CONFIG_DIR
from infra.source.config.pipeline_mode import IndexingMethod

from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from application.source.collection_service import CollectionService
from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.source.task_service import TaskService
from application.source.artifact_registry_service import ArtifactRegistryService
from utils.logger import bind_request_id, clear_request_id

logger = logging.getLogger(__name__)

_OBJECTIVE_PROGRESS_STAGE_PERCENT = {
    "objective_paper_skim_started": 72,
    "objective_discovery_started": 73,
    "objective_paper_framing_started": 74,
    "objective_evidence_routing_started": 75,
    "objective_evidence_units_started": 76,
    "objective_logic_chains_started": 78,
}
_OBJECTIVE_PROGRESS_UPDATE_INTERVAL = 5

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


class CollectionBuildTaskRunner:
    """App-layer task runner that orchestrates collection build and Core postprocess."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        task_service: TaskService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        document_profile_service: DocumentProfileService | None = None,
        paper_facts_service: PaperFactsService | None = None,
        comparison_service: ComparisonService | None = None,
        research_objective_service: ResearchObjectiveService | None = None,
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

    def _update_task_progress(
        self,
        task_id: str,
        collection_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        record = self.task_service.update_task(task_id, **kwargs)
        logger.info(
            "Build task progress task_id=%s collection_id=%s stage=%s progress_percent=%s status=%s",
            task_id,
            collection_id,
            record.get("current_stage"),
            record.get("progress_percent"),
            record.get("status"),
        )
        return record

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
            self._update_task_progress(
                task_id,
                collection_id,
                current_stage=phase,
                progress_percent=_OBJECTIVE_PROGRESS_STAGE_PERCENT.get(phase, 76),
                progress_detail=progress_detail,
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

    def run_build_task_blocking(
        self,
        task_id: str,
        collection_id: str,
        method: IndexingMethod | str = IndexingMethod.Standard,
        verbose: bool = False,
        additional_context: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        """Run the full build task in a worker thread with its own event loop."""

        return asyncio.run(
            self.run_build_task(
                task_id,
                collection_id,
                method=method,
                verbose=verbose,
                additional_context=additional_context,
                request_id=request_id,
            )
        )

    async def run_build_task(
        self,
        task_id: str,
        collection_id: str,
        method: IndexingMethod | str = IndexingMethod.Standard,
        verbose: bool = False,
        additional_context: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        request_token = bind_request_id(request_id) if request_id else None
        task = self._update_task_progress(
            task_id,
            collection_id,
            status="running",
            current_stage="files_registered",
            progress_percent=5,
            progress_detail={
                "phase": "files_registered",
                "unit": "documents",
                "message": "Registered collection files for processing.",
            },
        )
        if not task.get("started_at"):
            task = self.task_service.update_task(task_id, started_at=task["updated_at"])

        files = self.collection_service.list_files(collection_id)
        if not files:
            self._update_task_progress(
                task_id,
                collection_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                progress_detail={
                    "phase": "failed",
                    "unit": "steps",
                    "message": "Build failed before processing documents.",
                },
                errors=["集合内没有可构建文件"],
                finished_at=self.task_service.get_task(task_id)["updated_at"],
            )
            raise RuntimeError("collection has no files")

        config, output_dir = self._load_collection_config(collection_id)
        self.collection_service.update_collection(collection_id, status="running")
        logger.info(
            "Build task started task_id=%s collection_id=%s method=%s file_count=%s verbose=%s",
            task_id,
            collection_id,
            method,
            len(files),
            verbose,
        )

        try:
            self._update_task_progress(
                task_id,
                collection_id,
                current_stage="source_artifacts_started",
                progress_percent=25,
                progress_detail={
                    "phase": "source_artifacts_started",
                    "unit": "documents",
                    "message": "Parsing source PDFs and tables into source artifacts.",
                },
                output_path=str(output_dir),
            )
            resolved_build_source_artifacts = self._resolve_build_source_artifacts()
            outputs = await resolved_build_source_artifacts(
                config=config,
                method=method or IndexingMethod.Standard,
                additional_context=additional_context,
                verbose=verbose,
            )
            errors = [str(err) for o in outputs for err in (o.errors or [])]
            self._update_task_progress(
                task_id,
                collection_id,
                current_stage="source_artifacts_completed",
                progress_percent=60,
                progress_detail={
                    "phase": "source_artifacts_completed",
                    "unit": "documents",
                    "message": "Source artifacts were generated.",
                },
                output_path=str(output_dir),
                errors=errors,
            )

            if not errors:
                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="document_profiles_started",
                    progress_percent=70,
                    progress_detail={
                        "phase": "document_profiles_started",
                        "unit": "documents",
                        "message": "Building document profiles before objective extraction.",
                    },
                )
                self.document_profile_service.build_document_profiles(collection_id)
                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="research_objectives_started",
                    progress_percent=71,
                    progress_detail={
                        "phase": "research_objectives_started",
                        "unit": "steps",
                        "message": "Starting research-objective-first extraction.",
                    },
                )
                self.research_objective_service.build_research_objectives(
                    collection_id,
                    progress_callback=self._build_objective_progress_callback(
                        task_id,
                        collection_id,
                    ),
                )
                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="paper_facts_started",
                    progress_percent=80,
                    progress_detail={
                        "phase": "paper_facts_started",
                        "unit": "steps",
                        "message": "Projecting extracted evidence into paper facts.",
                    },
                )
                evidence_cards = self.paper_facts_service.build_evidence_cards(collection_id)
                if not evidence_cards:
                    record = self.task_service.get_task(task_id)
                    warnings = list(record.get("warnings", []))
                    warnings.append("未抽取到 evidence cards，collection 暂时只能依赖 document profiles。")
                    self.task_service.update_task(task_id, warnings=warnings)

                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="comparison_rows_started",
                    progress_percent=88,
                    progress_detail={
                        "phase": "comparison_rows_started",
                        "unit": "steps",
                        "message": "Generating collection comparison rows.",
                    },
                )
                try:
                    comparison_rows = self.comparison_service.build_comparison_rows(
                        collection_id
                    )
                except ComparisonRowsNotReadyError:
                    comparison_rows = ()
                if not comparison_rows:
                    record = self.task_service.get_task(task_id)
                    warnings = list(record.get("warnings", []))
                    warnings.append("未生成 comparison rows，当前 collection 还不能直接做结构化比较。")
                    self.task_service.update_task(task_id, warnings=warnings)

            artifacts = self.artifact_registry_service.upsert(collection_id, output_dir)
            final_errors = list(self.task_service.get_task(task_id).get("errors", []))
            status = "completed" if not final_errors else "partial_success"
            self._update_task_progress(
                task_id,
                collection_id,
                status=status,
                current_stage="artifacts_ready",
                progress_percent=100,
                progress_detail={
                    "phase": "artifacts_ready",
                    "unit": "steps",
                    "message": "Build artifacts are ready.",
                },
                output_path=artifacts["output_path"],
                finished_at=self.task_service.get_task(task_id)["updated_at"],
            )
            self.collection_service.update_collection(collection_id, status=status)
            final_record = self.task_service.get_task(task_id)
            logger.info(
                "Build task finished task_id=%s collection_id=%s status=%s warnings=%s errors=%s",
                task_id,
                collection_id,
                status,
                len(final_record.get("warnings", [])),
                len(final_record.get("errors", [])),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Build task failed task_id=%s collection_id=%s",
                task_id,
                collection_id,
            )
            record = self.task_service.get_task(task_id)
            errors = list(record.get("errors", []))
            errors.append(str(exc))
            self._update_task_progress(
                task_id,
                collection_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                progress_detail={
                    "phase": "failed",
                    "unit": "steps",
                    "message": "Build failed before artifacts were ready.",
                },
                errors=errors,
                output_path=str(output_dir),
                finished_at=record["updated_at"],
            )
            self.collection_service.update_collection(collection_id, status="failed")
            raise
        finally:
            if request_token is not None:
                clear_request_id(request_token)

        return self.task_service.get_task(task_id)
