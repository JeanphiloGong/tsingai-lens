from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from application.pipeline.collection_build.config import CollectionBuildPipelineConfig
from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build.definitions import (
    COLLECTION_BUILD_NODE_DEFINITIONS,
    CollectionBuildNodeDefinition,
    NodeFunction,
)
from application.pipeline.collection_build.progress import (
    build_progress_detail,
)
from domain.pipeline import (
    ExecutionStats,
    PipelineNodeStatus,
    PipelineRun,
    PipelineRunStatus,
)
from infra.llm.usage import capture_llm_usage

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectionBuildPipelineRunner:
    """Execute the dependency graph carried by a collection pipeline run."""

    def __init__(
        self,
        node_functions: Mapping[str, NodeFunction],
        definitions: tuple[CollectionBuildNodeDefinition, ...] = COLLECTION_BUILD_NODE_DEFINITIONS,
    ) -> None:
        self.definitions = definitions
        self.node_functions = dict(node_functions)

    async def run(
        self,
        context: CollectionBuildContext,
        config: CollectionBuildPipelineConfig,
        pipeline_run: PipelineRun,
    ) -> PipelineRun:
        definitions_by_name = {
            definition.node_id: definition for definition in self.definitions
        }
        missing_definitions = {
            node.name for node in pipeline_run.nodes if node.name not in definitions_by_name
        }
        missing_functions = {
            node.name for node in pipeline_run.nodes if node.name not in self.node_functions
        }
        if missing_definitions or missing_functions:
            missing = sorted(missing_definitions | missing_functions)
            raise ValueError("pipeline nodes are not executable: " + ", ".join(missing))
        self._persist_run(context, pipeline_run)

        while any(node.status is PipelineNodeStatus.QUEUED for node in pipeline_run.nodes):
            progressed = False
            for node in pipeline_run.nodes:
                if node.status is not PipelineNodeStatus.QUEUED:
                    continue
                dependencies = tuple(
                    pipeline_run.node(name) for name in node.dependencies
                )
                if any(
                    dependency.status
                    in {PipelineNodeStatus.FAILED, PipelineNodeStatus.SKIPPED}
                    for dependency in dependencies
                ):
                    pipeline_run = self._mark_skipped(context, node.name, pipeline_run)
                    progressed = True
                    continue
                if not all(
                    dependency.status is PipelineNodeStatus.SUCCEEDED
                    for dependency in dependencies
                ):
                    continue

                definition = definitions_by_name[node.name]
                pipeline_run = self._mark_running(context, definition, pipeline_run)
                with capture_llm_usage() as usage:
                    try:
                        result = self.node_functions[node.name](context, config)
                        if inspect.isawaitable(result):
                            result = await result
                    except Exception as exc:  # noqa: BLE001
                        pipeline_run = self._mark_failed(
                            context,
                            definition,
                            pipeline_run,
                            exc,
                            stats=usage.execution_stats(),
                        )
                        logger.exception(
                            "Collection build pipeline node failed task_id=%s collection_id=%s node=%s",
                            context.task_id,
                            context.collection_id,
                            node.name,
                        )
                    else:
                        pipeline_run = self._mark_succeeded(
                            context,
                            definition,
                            pipeline_run,
                            result,
                            stats=usage.execution_stats(),
                        )
                progressed = True

            if not progressed:
                queued = sorted(
                    node.name
                    for node in pipeline_run.nodes
                    if node.status is PipelineNodeStatus.QUEUED
                )
                raise RuntimeError(
                    "pipeline has no executable nodes: " + ", ".join(queued)
                )

        return pipeline_run

    def _persist_run(
        self,
        context: CollectionBuildContext,
        pipeline_run: PipelineRun,
    ) -> None:
        context.task_service.update_task(
            context.task_id,
            pipeline_run=pipeline_run,
        )

    def _update_task_for_node(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        pipeline_run: PipelineRun,
        **fields: Any,
    ) -> None:
        record = context.task_service.update_task(
            context.task_id,
            current_stage=fields.pop("current_stage", definition.node_id),
            progress_percent=fields.pop("progress_percent", definition.progress_percent),
            progress_detail=fields.pop("progress_detail", build_progress_detail(definition)),
            pipeline_run=pipeline_run,
            **fields,
        )
        logger.info(
            "Build task progress task_id=%s collection_id=%s stage=%s progress_percent=%s status=%s",
            context.task_id,
            context.collection_id,
            record.get("current_stage"),
            record.get("progress_percent"),
            record.get("status"),
        )

    def _mark_running(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        pipeline_run: PipelineRun,
    ) -> PipelineRun:
        started_at = _now_iso()
        if pipeline_run.status is PipelineRunStatus.QUEUED:
            pipeline_run = pipeline_run.start(started_at)
        pipeline_run = pipeline_run.with_node(
            pipeline_run.node(definition.node_id).start(started_at)
        )
        self._update_task_for_node(
            context,
            definition,
            pipeline_run,
            status="running",
            current_stage=definition.running_stage,
            progress_percent=(
                definition.running_progress_percent
                if definition.running_progress_percent is not None
                else definition.progress_percent
            ),
            progress_detail=build_progress_detail(
                definition,
                phase=definition.running_stage,
            ),
        )
        return pipeline_run

    def _mark_succeeded(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        pipeline_run: PipelineRun,
        result: Any,
        *,
        stats: ExecutionStats,
    ) -> PipelineRun:
        output_summary: dict[str, Any] = {}
        warnings: tuple[str, ...] = ()
        if isinstance(result, Mapping):
            warnings = tuple(str(item) for item in result.get("warnings") or ())
            output_summary = {
                str(key): value
                for key, value in result.items()
                if key != "warnings"
            }
        pipeline_run = pipeline_run.with_node(
            pipeline_run.node(definition.node_id).succeed(
                _now_iso(),
                output_summary=output_summary,
                warnings=warnings,
                stats=stats,
            )
        )
        self._update_task_for_node(
            context,
            definition,
            pipeline_run,
            current_stage=definition.completed_stage,
            progress_detail=build_progress_detail(definition),
            errors=list(pipeline_run.errors),
            warnings=list(pipeline_run.warnings),
        )
        return pipeline_run

    def _mark_failed(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        pipeline_run: PipelineRun,
        exc: Exception,
        *,
        stats: ExecutionStats,
    ) -> PipelineRun:
        pipeline_run = pipeline_run.with_node(
            pipeline_run.node(definition.node_id).fail(
                str(exc),
                _now_iso(),
                stats=stats,
            )
        )
        self._update_task_for_node(
            context,
            definition,
            pipeline_run,
            current_stage="failed",
            progress_detail=build_progress_detail(
                definition,
                phase="failed",
                message=str(exc),
            ),
            errors=list(pipeline_run.errors),
            warnings=list(pipeline_run.warnings),
        )
        return pipeline_run

    def _mark_skipped(
        self,
        context: CollectionBuildContext,
        node_name: str,
        pipeline_run: PipelineRun,
    ) -> PipelineRun:
        pipeline_run = pipeline_run.with_node(
            pipeline_run.node(node_name).skip(finished_at=_now_iso())
        )
        self._persist_run(context, pipeline_run)
        return pipeline_run
