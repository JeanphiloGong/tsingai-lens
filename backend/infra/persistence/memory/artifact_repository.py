from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path

from config import DATA_DIR


class MemoryArtifactRepository:
    """Memory-backed persistence for collection artifact readiness."""

    backend_name = "memory"

    def __init__(self, root_dir: Path | None = None) -> None:
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if root_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="lens-artifacts-")
            root_dir = Path(self._temp_dir.name)
        self.root_dir = Path(root_dir or (DATA_DIR / "collections")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts: dict[str, dict] = {}

    def read(self, collection_id: str) -> dict | None:
        payload = self._artifacts.get(collection_id)
        return deepcopy(payload) if payload is not None else None

    def write(self, collection_id: str, payload: dict) -> None:
        self._artifacts[collection_id] = deepcopy(payload)
