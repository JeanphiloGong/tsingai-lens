from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactRegistryService:
    """Track which collection-level artifacts are ready for downstream use."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or (DATA_DIR / "collections")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _artifact_path(self, collection_id: str) -> Path:
        return self.root_dir / collection_id / "artifacts.json"

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def _read(self, path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def build_registry(self, collection_id: str, output_dir: str | Path) -> dict:
        base_dir = Path(output_dir).expanduser().resolve()
        return {
            "collection_id": collection_id,
            "output_path": str(base_dir),
            "documents_ready": (base_dir / "documents.parquet").exists(),
            "graph_ready": (base_dir / "entities.parquet").exists()
            and (base_dir / "relationships.parquet").exists(),
            "sections_ready": (base_dir / "sections.parquet").exists(),
            "procedure_blocks_ready": (base_dir / "procedure_blocks.parquet").exists(),
            "protocol_steps_ready": (base_dir / "protocol_steps.parquet").exists(),
            "graphml_ready": (base_dir / "graph.graphml").exists(),
            "updated_at": _now_iso(),
        }

    def upsert(self, collection_id: str, output_dir: str | Path) -> dict:
        payload = self.build_registry(collection_id, output_dir)
        self._write(self._artifact_path(collection_id), payload)
        return payload

    def get(self, collection_id: str) -> dict:
        payload = self._read(self._artifact_path(collection_id), None)
        if payload is None:
            raise FileNotFoundError(f"artifact registry not found: {collection_id}")
        return payload
