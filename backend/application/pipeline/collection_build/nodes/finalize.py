from __future__ import annotations

from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build.definitions import SOURCE_ARTIFACTS


def run(context: CollectionBuildContext) -> dict:
    task = context.task_service.get_task(context.task_id)
    node_states = task.get("pipeline_nodes", {})
    source_status = node_states.get(SOURCE_ARTIFACTS, {}).get("status")
    if source_status != "succeeded":
        status = "failed"
    elif any(state.get("status") == "failed" for state in node_states.values()):
        status = "partial_success"
    else:
        status = "completed"
    output_path = None
    artifacts = context.state.get("artifacts")
    if isinstance(artifacts, dict):
        output_path = artifacts.get("output_path")
    context.state["final_status"] = status
    return {"status": status, "output_path": output_path}
