from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from domain.ports import ArtifactRepository
from infra.persistence.factory import build_artifact_repository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactRegistryService:
    """Track which collection-level artifacts are ready for downstream use."""

    def __init__(
        self,
        root_dir: Path | None = None,
        repository: ArtifactRepository | None = None,
    ) -> None:
        self.repository = repository or build_artifact_repository(root_dir)
        self.root_dir = self.repository.root_dir

    def build_registry(self, collection_id: str, output_dir: str | Path) -> dict:
        base_dir = Path(output_dir).expanduser().resolve()
        return {
            "collection_id": collection_id,
            "output_path": str(base_dir),
            "documents_ready": (base_dir / "documents.parquet").exists(),
            "document_profiles_ready": self._parquet_has_rows(
                base_dir / "document_profiles.parquet"
            ),
            "evidence_cards_ready": self._parquet_has_rows(
                base_dir / "evidence_cards.parquet"
            ),
            "comparison_rows_ready": self._parquet_has_rows(
                base_dir / "comparison_rows.parquet"
            ),
            "graph_ready": (base_dir / "entities.parquet").exists()
            and (base_dir / "relationships.parquet").exists(),
            "sections_ready": (base_dir / "sections.parquet").exists(),
            "procedure_blocks_ready": (base_dir / "procedure_blocks.parquet").exists(),
            "protocol_steps_ready": (base_dir / "protocol_steps.parquet").exists(),
            "graphml_ready": (base_dir / "graph.graphml").exists(),
            "updated_at": _now_iso(),
        }

    def _parquet_has_rows(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            frame = pd.read_parquet(path)
        except Exception:  # noqa: BLE001
            return False
        return not frame.empty

    def upsert(self, collection_id: str, output_dir: str | Path) -> dict:
        payload = self.build_registry(collection_id, output_dir)
        self.repository.write(collection_id, payload)
        return payload

    def get(self, collection_id: str) -> dict:
        payload = self.repository.read(collection_id)
        if payload is None:
            raise FileNotFoundError(f"artifact registry not found: {collection_id}")
        return payload
