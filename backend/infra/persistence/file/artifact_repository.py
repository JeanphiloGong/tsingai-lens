from __future__ import annotations

from pathlib import Path

from config import DATA_DIR
from infra.persistence.file._json import read_json, write_json


class FileArtifactRepository:
    """File-backed persistence for collection artifact readiness."""

    backend_name = "file"

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or (DATA_DIR / "collections")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def artifact_path(self, collection_id: str) -> Path:
        return self.root_dir / collection_id / "artifacts.json"

    def read(self, collection_id: str) -> dict | None:
        return read_json(self.artifact_path(collection_id), None)

    def write(self, collection_id: str, payload: dict) -> None:
        write_json(self.artifact_path(collection_id), payload)
