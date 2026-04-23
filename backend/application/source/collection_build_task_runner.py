from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import CONFIG_DIR
from infra.source.config.pipeline_mode import IndexingMethod

from application.core.comparison_service import ComparisonService
from application.source.collection_service import CollectionService
from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.source.task_service import TaskService
from application.derived.protocol.pipeline_service import build_protocol_artifacts
from application.source.artifact_registry_service import ArtifactRegistryService
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
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.task_service = task_service or TaskService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
            document_profile_service=self.document_profile_service,
        )
        self.comparison_service = comparison_service or ComparisonService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
            paper_facts_service=self.paper_facts_service,
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
                output_path=str(output_dir),
                errors=errors,
            )

            if not errors:
                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="document_profiles_started",
                    progress_percent=70,
                )
                document_profiles = self.document_profile_service.build_document_profiles(
                    collection_id,
                    output_dir,
                )
                protocol_candidate_count = self.document_profile_service.count_protocol_suitable(
                    document_profiles
                )
                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="paper_facts_started",
                    progress_percent=76,
                )
                evidence_cards = self.paper_facts_service.build_evidence_cards(
                    collection_id,
                    output_dir,
                )
                if evidence_cards.empty:
                    record = self.task_service.get_task(task_id)
                    warnings = list(record.get("warnings", []))
                    warnings.append("未抽取到 evidence cards，collection 暂时只能依赖 document profiles。")
                    self.task_service.update_task(task_id, warnings=warnings)

                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="comparison_rows_started",
                    progress_percent=82,
                )
                comparison_rows = self.comparison_service.build_comparison_rows(
                    collection_id,
                    output_dir,
                )
                if comparison_rows.empty:
                    record = self.task_service.get_task(task_id)
                    warnings = list(record.get("warnings", []))
                    warnings.append("未生成 comparison rows，当前 collection 还不能直接做结构化比较。")
                    self.task_service.update_task(task_id, warnings=warnings)

                self._update_task_progress(
                    task_id,
                    collection_id,
                    current_stage="protocol_artifacts_started",
                    progress_percent=88,
                )
                if protocol_candidate_count > 0:
                    build_protocol_artifacts(output_dir)
                else:
                    record = self.task_service.get_task(task_id)
                    warnings = list(record.get("warnings", []))
                    warnings.append("未检测到适合 protocol 提取的文档，已跳过 protocol artifacts。")
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
