from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config import DATA_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    """File-backed task registry for collection processing tasks."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or (DATA_DIR / "tasks")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.root_dir / f"{task_id}.json"

    def _read(self, path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

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
        self._write(self._task_path(task_id), record)
        return record

    def get_task(self, task_id: str) -> dict:
        record = self._read(self._task_path(task_id), None)
        if record is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        return record

    def update_task(self, task_id: str, **fields) -> dict:
        record = self.get_task(task_id)
        record.update(fields)
        record["updated_at"] = _now_iso()
        self._write(self._task_path(task_id), record)
        return record

    def append_error(self, task_id: str, error: str) -> dict:
        record = self.get_task(task_id)
        record.setdefault("errors", []).append(error)
        record["updated_at"] = _now_iso()
        self._write(self._task_path(task_id), record)
        return record
