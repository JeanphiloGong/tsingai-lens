from __future__ import annotations

from pathlib import Path

from config import DATA_DIR
from infra.persistence.file._json import read_json, write_json


class FileTaskRepository:
    """File-backed persistence for task state."""

    backend_name = "file"

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or (DATA_DIR / "tasks")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def task_path(self, task_id: str) -> Path:
        return self.root_dir / f"{task_id}.json"

    def read_task(self, task_id: str) -> dict | None:
        return read_json(self.task_path(task_id), None)

    def write_task(self, task_id: str, payload: dict) -> None:
        write_json(self.task_path(task_id), payload)

    def list_tasks(self) -> list[dict]:
        items: list[dict] = []
        for task_path in sorted(self.root_dir.glob("task_*.json")):
            record = read_json(task_path, None)
            if record is not None:
                items.append(record)
        return items
