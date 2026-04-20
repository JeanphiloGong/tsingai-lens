from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.ports import TaskRepository
from infra.persistence.factory import build_task_repository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    """File-backed task registry for collection processing tasks."""

    def __init__(
        self,
        root_dir: Path | None = None,
        repository: TaskRepository | None = None,
    ) -> None:
        self.repository = repository or build_task_repository(root_dir)
        self.root_dir = self.repository.root_dir

    def create_task(self, collection_id: str, task_type: str = "index") -> dict:
        task_id = f"task_{uuid4().hex[:12]}"
        now = _now_iso()
        record = {
            "task_id": task_id,
            "collection_id": collection_id,
            "task_type": task_type,
            "status": "queued",
            "current_stage": "queued",
            "progress_percent": 0,
            "output_path": None,
            "errors": [],
            "warnings": [],
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        self.repository.write_task(task_id, record)
        return record

    def get_task(self, task_id: str) -> dict:
        record = self.repository.read_task(task_id)
        if record is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        return dict(record)

    def list_tasks(
        self,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        tasks: list[dict] = []
        for record in self.repository.list_tasks():
            record = dict(record)
            if collection_id and record.get("collection_id") != collection_id:
                continue
            if status and record.get("status") != status:
                continue
            tasks.append(record)
        tasks.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        if offset > 0:
            tasks = tasks[offset:]
        if limit is not None:
            return tasks[:limit]
        return tasks

    def update_task(self, task_id: str, **fields) -> dict:
        stored = self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        record = dict(stored)
        record.update(fields)
        record["updated_at"] = _now_iso()
        self.repository.write_task(task_id, record)
        return dict(record)

    def append_error(self, task_id: str, error: str) -> dict:
        stored = self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        record = dict(stored)
        record.setdefault("errors", []).append(error)
        record["updated_at"] = _now_iso()
        self.repository.write_task(task_id, record)
        return dict(record)
