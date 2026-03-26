from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import CONFIG_DIR
from retrieval.config.enums import IndexingMethod
from services.artifact_registry_service import ArtifactRegistryService
from services.collection_service import CollectionService
from services.protocol_pipeline_service import build_protocol_artifacts
from services.task_service import TaskService

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised indirectly in runtime, patched in tests
    from retrieval.api.index import build_index  # type: ignore
except Exception:  # noqa: BLE001
    build_index = None

try:  # pragma: no cover - exercised indirectly in runtime, patched in tests
    from retrieval.config.load_config import load_config  # type: ignore
except Exception:  # noqa: BLE001
    load_config = None


class IndexTaskRunner:
    """App-layer task runner that orchestrates GraphRAG and protocol postprocess."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        task_service: TaskService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.task_service = task_service or TaskService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )

    def _resolve_load_config(self):
        global load_config
        if load_config is None:
            from retrieval.config.load_config import load_config as resolved_load_config

            load_config = resolved_load_config
        return load_config

    def _resolve_build_index(self):
        global build_index
        if build_index is None:
            from retrieval.api.index import build_index as resolved_build_index

            build_index = resolved_build_index
        return build_index

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

    async def run_index_task(
        self,
        task_id: str,
        collection_id: str,
        method: IndexingMethod | str = IndexingMethod.Standard,
        is_update_run: bool = False,
        verbose: bool = False,
        additional_context: dict | None = None,
    ) -> dict:
        task = self.task_service.update_task(
            task_id,
            status="running",
            current_stage="files_registered",
            progress_percent=5,
        )
        if not task.get("started_at"):
            task = self.task_service.update_task(task_id, started_at=task["updated_at"])

        files = self.collection_service.list_files(collection_id)
        if not files:
            self.task_service.update_task(
                task_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                errors=["集合内没有可索引文件"],
                finished_at=self.task_service.get_task(task_id)["updated_at"],
            )
            raise RuntimeError("collection has no files")

        config, output_dir = self._load_collection_config(collection_id)
        self.collection_service.update_collection(collection_id, status="running")

        try:
            self.task_service.update_task(
                task_id,
                current_stage="graphrag_index_started",
                progress_percent=25,
                output_path=str(output_dir),
            )
            resolved_build_index = self._resolve_build_index()
            outputs = await resolved_build_index(
                config=config,
                method=method or IndexingMethod.Standard,
                is_update_run=is_update_run,
                additional_context=additional_context,
                verbose=verbose,
            )
            errors = [str(err) for o in outputs for err in (o.errors or [])]
            self.task_service.update_task(
                task_id,
                current_stage="graphrag_index_completed",
                progress_percent=60,
                output_path=str(output_dir),
                errors=errors,
            )

            if not errors:
                self.task_service.update_task(
                    task_id,
                    current_stage="protocol_artifacts_started",
                    progress_percent=75,
                )
                build_protocol_artifacts(output_dir)

            artifacts = self.artifact_registry_service.upsert(collection_id, output_dir)
            final_errors = list(self.task_service.get_task(task_id).get("errors", []))
            status = "completed" if not final_errors else "partial_success"
            self.task_service.update_task(
                task_id,
                status=status,
                current_stage="artifacts_ready",
                progress_percent=100,
                output_path=artifacts["output_path"],
                finished_at=self.task_service.get_task(task_id)["updated_at"],
            )
            self.collection_service.update_collection(collection_id, status=status)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Index task failed task_id=%s collection_id=%s",
                task_id,
                collection_id,
            )
            record = self.task_service.get_task(task_id)
            errors = list(record.get("errors", []))
            errors.append(str(exc))
            self.task_service.update_task(
                task_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                errors=errors,
                output_path=str(output_dir),
                finished_at=record["updated_at"],
            )
            self.collection_service.update_collection(collection_id, status="failed")
            raise

        return self.task_service.get_task(task_id)
