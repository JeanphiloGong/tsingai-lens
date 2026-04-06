from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path

from config import DATA_DIR


class MemoryTaskRepository:
    """Memory-backed persistence for task state."""

    backend_name = "memory"

    def __init__(self, root_dir: Path | None = None) -> None:
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if root_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="lens-tasks-")
            root_dir = Path(self._temp_dir.name)
        self.root_dir = Path(root_dir or (DATA_DIR / "tasks")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, dict] = {}

    def read_task(self, task_id: str) -> dict | None:
        payload = self._tasks.get(task_id)
        return deepcopy(payload) if payload is not None else None

    def write_task(self, task_id: str, payload: dict) -> None:
        self._tasks[task_id] = deepcopy(payload)

    def list_tasks(self) -> list[dict]:
        return [deepcopy(record) for _, record in sorted(self._tasks.items())]
