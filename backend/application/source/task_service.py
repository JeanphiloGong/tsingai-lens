from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from domain.pipeline import (
    ExecutionStats,
    ExecutionTimestamps,
    PipelineRun,
    PipelineRunStatus,
)
from domain.ports import BuildRepository
from domain.source import BuildStageRecord, TaskRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    """Application operations over durable task and collection-build state."""

    def __init__(self, repository: BuildRepository) -> None:
        self.repository = repository

    def create_task(
        self,
        collection_id: str,
        task_type: str = "build",
        *,
        mode: str = "standard",
    ) -> dict:
        task_id = f"task_{uuid4().hex[:12]}"
        now = _now_iso()
        record = TaskRecord(
            task_id=task_id,
            collection_id=str(collection_id),
            task_type=str(task_type),
            status="queued",
            current_stage="queued",
            progress_percent=0,
            progress_detail=None,
            output_path=None,
            errors=(),
            warnings=(),
            created_at=now,
            updated_at=now,
            started_at=None,
            finished_at=None,
        )
        build = self.repository.add_task(
            record,
            build_id=f"build_{uuid4().hex[:12]}",
            mode=str(mode).strip(),
        )
        return {**record.to_record(), "mode": build.mode}

    def get_task(self, task_id: str) -> dict:
        record = self.repository.read_task(task_id)
        if record is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        return self._project_task(record)

    def list_tasks(
        self,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        return [
            self._project_task(record)
            for record in self.repository.list_tasks(
                collection_id=collection_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        ]

    def update_task(self, task_id: str, **fields: Any) -> dict:
        stored = self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        pipeline_run = fields.pop("pipeline_run", None)
        if pipeline_run is not None and not isinstance(pipeline_run, PipelineRun):
            raise TypeError("pipeline_run must be a PipelineRun")
        now = _now_iso()
        payload = {**stored.to_record(), **fields, "updated_at": now}
        if not stored.started_at and fields.get("status") == "running":
            payload["started_at"] = (
                pipeline_run.timestamps.started_at
                if pipeline_run is not None
                else now
            )
        record = TaskRecord.from_mapping(payload)
        stages = (
            self._build_stages(task_id, pipeline_run)
            if pipeline_run is not None
            else None
        )
        if not self.repository.update_task(record, stages=stages):
            raise FileNotFoundError(f"task not found: {task_id}")
        return self._project_task(record, stages=stages)

    def finish_task(self, task_id: str, *, status: str, **fields: Any) -> dict:
        stored = self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        pipeline_run = fields.pop("pipeline_run", None)
        if pipeline_run is not None:
            if not isinstance(pipeline_run, PipelineRun):
                raise TypeError("pipeline_run must be a PipelineRun")
            if pipeline_run.run_id != task_id:
                raise ValueError("pipeline run belongs to another task")
            fields.setdefault("errors", list(pipeline_run.errors))
            fields.setdefault("warnings", list(pipeline_run.warnings))
            fields.setdefault("started_at", pipeline_run.timestamps.started_at)
            fields.setdefault("finished_at", pipeline_run.timestamps.finished_at)
        now = _now_iso()
        successful = status in {"completed", "partial_success"}
        record = TaskRecord.from_mapping(
            {
                **stored.to_record(),
                **fields,
                "status": status,
                "current_stage": fields.get(
                    "current_stage",
                    "artifacts_ready" if successful else "failed",
                ),
                "progress_percent": fields.get("progress_percent", 100),
                "updated_at": now,
                "finished_at": fields.get("finished_at", now),
            }
        )
        self.repository.finish_build(
            record,
            build_status="succeeded" if successful else "failed",
            activate=successful,
        )
        return self._project_task(record)

    def append_error(self, task_id: str, error: str) -> dict:
        stored = self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        return self.update_task(task_id, errors=[*stored.errors, str(error)])

    def _build_stages(
        self,
        task_id: str,
        pipeline_run: PipelineRun,
    ) -> tuple[BuildStageRecord, ...]:
        build = self.repository.read_build(task_id)
        if build is None:
            raise RuntimeError(f"build not found for task: {task_id}")
        if pipeline_run.run_id != task_id:
            raise ValueError("pipeline run belongs to another task")
        if pipeline_run.output_build_id != build.build_id:
            raise ValueError("pipeline run output belongs to another build")
        if pipeline_run.mode != build.mode:
            raise ValueError("pipeline run mode belongs to another build mode")
        if pipeline_run.scope_type != "collection":
            raise ValueError("collection build requires collection scope")
        if pipeline_run.scope_id != build.collection_id:
            raise ValueError("pipeline run belongs to another collection")
        return tuple(
            BuildStageRecord(
                stage_id=(
                    f"stage_{uuid5(NAMESPACE_URL, f'{build.build_id}:{node.name}').hex[:24]}"
                ),
                build_id=build.build_id,
                stage_order=stage_order,
                node=node,
            )
            for stage_order, node in enumerate(pipeline_run.nodes)
        )

    def read_pipeline_run(self, task_id: str) -> PipelineRun:
        task = self.repository.read_task(task_id)
        if task is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        build = self.repository.read_build(task_id)
        if build is None:
            raise RuntimeError(f"build not found for task: {task_id}")
        nodes = tuple(stage.node for stage in self.repository.list_stages(task_id))
        timestamps = ExecutionTimestamps(
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
        )
        return PipelineRun(
            pipeline_name=(
                "collection_build" if task.task_type == "build" else task.task_type
            ),
            mode=build.mode,
            run_id=task.task_id,
            scope_type="collection",
            scope_id=task.collection_id,
            status=PipelineRunStatus(task.status),
            nodes=nodes,
            errors=task.errors,
            warnings=task.warnings,
            stats=ExecutionStats.aggregate(
                (node.stats for node in nodes),
                duration_ms=timestamps.duration_ms(),
            ),
            timestamps=timestamps,
            output_build_id=build.build_id,
        )

    def _project_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[BuildStageRecord, ...] | None = None,
    ) -> dict:
        payload = record.to_record()
        resolved_stages = (
            stages
            if stages is not None
            else self.repository.list_stages(record.task_id)
        )
        if resolved_stages:
            payload["pipeline_nodes"] = {
                stage.node.name: stage.to_pipeline_state() for stage in resolved_stages
            }
        return payload


__all__ = ["TaskService"]
