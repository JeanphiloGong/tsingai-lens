from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from application.pipeline.collection_build.state import build_initial_node_states, now_iso
from application.pipeline.goal_analysis.context import GoalAnalysisContext
from application.pipeline.goal_analysis.definitions import (
    GOAL_ANALYSIS_NODE_DEFINITIONS,
    GoalAnalysisNodeDefinition,
    NodeFunction,
)


class GoalAnalysisPipelineRunner:
    """Run confirmed-goal analysis nodes in dependency order."""

    def __init__(
        self,
        node_functions: Mapping[str, NodeFunction],
        definitions: tuple[GoalAnalysisNodeDefinition, ...] = GOAL_ANALYSIS_NODE_DEFINITIONS,
    ) -> None:
        self.definitions = definitions
        self.node_functions = dict(node_functions)

    async def run(self, context: GoalAnalysisContext) -> dict[str, Any]:
        node_states = build_initial_node_states(
            tuple(definition.node_id for definition in self.definitions)
        )
        for definition in self.definitions:
            if self._dependency_failed(definition, node_states):
                self._mark_skipped(definition, node_states)
                continue
            node_states[definition.node_id]["status"] = "running"
            node_states[definition.node_id]["started_at"] = now_iso()
            try:
                result = self.node_functions[definition.node_id](context)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:  # noqa: BLE001
                node_states[definition.node_id]["status"] = "failed"
                node_states[definition.node_id]["finished_at"] = now_iso()
                node_states[definition.node_id]["errors"] = [str(exc)]
                continue
            node_states[definition.node_id]["status"] = "succeeded"
            node_states[definition.node_id]["finished_at"] = now_iso()
            if isinstance(result, dict):
                node_states[definition.node_id]["warnings"] = list(
                    result.get("warnings", [])
                )
                context.state[definition.node_id] = result
        return {
            "pipeline_nodes": node_states,
            "errors": self._collect(node_states, "errors"),
            "warnings": self._collect(node_states, "warnings"),
        }

    def _dependency_failed(
        self,
        definition: GoalAnalysisNodeDefinition,
        node_states: dict[str, dict[str, Any]],
    ) -> bool:
        return any(
            node_states[dependency]["status"] in {"failed", "skipped"}
            for dependency in definition.depends_on
        )

    def _mark_skipped(
        self,
        definition: GoalAnalysisNodeDefinition,
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

    def _collect(
        self,
        node_states: dict[str, dict[str, Any]],
        field: str,
    ) -> list[str]:
        collected: list[str] = []
        for node_id, state in node_states.items():
            for value in state.get(field, []):
                collected.append(f"{node_id}: {value}")
        return collected
