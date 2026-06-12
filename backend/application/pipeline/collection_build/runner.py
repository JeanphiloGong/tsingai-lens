from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from typing import Any

from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build.definitions import (
    COLLECTION_BUILD_NODE_DEFINITIONS,
    CollectionBuildNodeDefinition,
    NodeFunction,
)
from application.pipeline.collection_build.progress import (
    build_progress_detail,
    collect_node_errors,
    collect_node_warnings,
)
from application.pipeline.collection_build.state import build_initial_node_states, now_iso

logger = logging.getLogger(__name__)


class CollectionBuildPipelineRunner:
    """Run collection build nodes from explicit dependency definitions."""

    def __init__(
        self,
        node_functions: Mapping[str, NodeFunction],
        definitions: tuple[CollectionBuildNodeDefinition, ...] = COLLECTION_BUILD_NODE_DEFINITIONS,
    ) -> None:
        self.definitions = definitions
        self.node_functions = dict(node_functions)

    async def run(self, context: CollectionBuildContext) -> dict[str, Any]:
        node_states = build_initial_node_states(
            tuple(definition.node_id for definition in self.definitions)
        )
        self._persist_node_states(context, node_states)

        for definition in self.definitions:
            self._ensure_wait_for_terminal(definition, node_states)
            if self._dependency_failed(definition, node_states):
                self._mark_skipped(context, definition, node_states)
                continue
            self._mark_running(context, definition, node_states)
            try:
                result = self.node_functions[definition.node_id](context)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:  # noqa: BLE001
                self._mark_failed(context, definition, node_states, exc)
                logger.exception(
                    "Collection build pipeline node failed task_id=%s collection_id=%s node=%s",
                    context.task_id,
                    context.collection_id,
                    definition.node_id,
                )
                continue
            self._mark_succeeded(context, definition, node_states, result)

        return {
            "pipeline_nodes": node_states,
            "errors": collect_node_errors(node_states),
            "warnings": collect_node_warnings(node_states),
        }

    def _dependency_failed(
        self,
        definition: CollectionBuildNodeDefinition,
        node_states: dict[str, dict[str, Any]],
    ) -> bool:
        return any(
            node_states[dependency]["status"] in {"failed", "skipped"}
            for dependency in definition.depends_on
        )

    def _ensure_wait_for_terminal(
        self,
        definition: CollectionBuildNodeDefinition,
        node_states: dict[str, dict[str, Any]],
    ) -> None:
        non_terminal = [
            node_id
            for node_id in definition.wait_for
            if node_states[node_id]["status"] in {"queued", "pending", "running"}
        ]
        if non_terminal:
            raise RuntimeError(
                f"node {definition.node_id} wait_for is not terminal: "
                f"{', '.join(non_terminal)}"
            )

    def _persist_node_states(
        self,
        context: CollectionBuildContext,
        node_states: dict[str, dict[str, Any]],
    ) -> None:
        context.task_service.update_task(
            context.task_id,
            pipeline_nodes=node_states,
        )

    def _update_task_for_node(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        node_states: dict[str, dict[str, Any]],
        **fields: Any,
    ) -> None:
        record = context.task_service.update_task(
            context.task_id,
            current_stage=fields.pop("current_stage", definition.node_id),
            progress_percent=fields.pop("progress_percent", definition.progress_percent),
            progress_detail=fields.pop("progress_detail", build_progress_detail(definition)),
            pipeline_nodes=node_states,
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
        node_states: dict[str, dict[str, Any]],
    ) -> None:
        state = node_states[definition.node_id]
        state["status"] = "running"
        state["started_at"] = now_iso()
        self._update_task_for_node(
            context,
            definition,
            node_states,
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

    def _mark_succeeded(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        node_states: dict[str, dict[str, Any]],
        result: Any,
    ) -> None:
        state = node_states[definition.node_id]
        state["status"] = "succeeded"
        state["finished_at"] = now_iso()
        if isinstance(result, dict):
            state["warnings"] = list(result.get("warnings", []))
            context.state[definition.node_id] = result
        self._update_task_for_node(
            context,
            definition,
            node_states,
            current_stage=definition.completed_stage,
            progress_detail=build_progress_detail(definition),
            errors=collect_node_errors(node_states),
            warnings=collect_node_warnings(node_states),
        )

    def _mark_failed(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        node_states: dict[str, dict[str, Any]],
        exc: Exception,
    ) -> None:
        state = node_states[definition.node_id]
        state["status"] = "failed"
        state["finished_at"] = now_iso()
        state["errors"] = [str(exc)]
        self._update_task_for_node(
            context,
            definition,
            node_states,
            current_stage="failed",
            progress_detail=build_progress_detail(
                definition,
                phase="failed",
                message=str(exc),
            ),
            errors=collect_node_errors(node_states),
            warnings=collect_node_warnings(node_states),
        )

    def _mark_skipped(
        self,
        context: CollectionBuildContext,
        definition: CollectionBuildNodeDefinition,
        node_states: dict[str, dict[str, Any]],
    ) -> None:
        failed_dependency = next(
            dependency
            for dependency in definition.depends_on
            if node_states[dependency]["status"] in {"failed", "skipped"}
        )
        state = node_states[definition.node_id]
        state["status"] = "skipped"
        state["finished_at"] = now_iso()
        state["skip_reason"] = f"dependency_failed: {failed_dependency}"
        self._persist_node_states(context, node_states)
