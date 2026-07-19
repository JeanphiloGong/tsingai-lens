from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from domain.ports import BuildRepository
from domain.source import BuildStageRecord, TaskRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    """Application operations over durable task and collection-build state."""

    def __init__(self, repository: BuildRepository) -> None:
        self.repository = repository

    def create_task(self, collection_id: str, task_type: str = "build") -> dict:
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
        self.repository.add_task(record, build_id=f"build_{uuid4().hex[:12]}")
        return record.to_record()

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
        pipeline_nodes = fields.pop("pipeline_nodes", None)
        now = _now_iso()
        payload = {**stored.to_record(), **fields, "updated_at": now}
        if fields.get("status") == "running" and not stored.started_at:
            payload["started_at"] = now
        record = TaskRecord.from_mapping(payload)
        stages = (
            self._build_stages(task_id, pipeline_nodes)
            if isinstance(pipeline_nodes, Mapping)
            else None
        )
        if not self.repository.update_task(record, stages=stages):
            raise FileNotFoundError(f"task not found: {task_id}")
        return self._project_task(record, stages=stages)

    def finish_task(self, task_id: str, *, status: str, **fields: Any) -> dict:
        stored = self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
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
        pipeline_nodes: Mapping[str, Any],
    ) -> tuple[BuildStageRecord, ...]:
        build = self.repository.read_build(task_id)
        if build is None:
            raise RuntimeError(f"build not found for task: {task_id}")
        stages: list[BuildStageRecord] = []
        for stage_order, (stage_kind, raw_state) in enumerate(pipeline_nodes.items()):
            state = dict(raw_state) if isinstance(raw_state, Mapping) else {}
            stage_id = f"stage_{uuid5(NAMESPACE_URL, f'{build.build_id}:{stage_kind}:1').hex[:24]}"
            stages.append(
                BuildStageRecord(
                    stage_id=stage_id,
                    build_id=build.build_id,
                    stage_kind=str(stage_kind),
                    stage_version=1,
                    stage_order=stage_order,
                    status=str(state.get("status") or "queued"),
                    started_at=(
                        str(state["started_at"])
                        if state.get("started_at") is not None
                        else None
                    ),
                    finished_at=(
                        str(state["finished_at"])
                        if state.get("finished_at") is not None
                        else None
                    ),
                    errors=tuple(str(item) for item in state.get("errors") or ()),
                    warnings=tuple(str(item) for item in state.get("warnings") or ()),
                    skip_reason=(
                        str(state["skip_reason"])
                        if state.get("skip_reason") is not None
                        else None
                    ),
                )
            )
        return tuple(stages)

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
                stage.stage_kind: stage.to_pipeline_state() for stage in resolved_stages
            }
        return payload


__all__ = ["TaskService"]
