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
        documents_path = base_dir / "documents.parquet"
        document_profiles_path = base_dir / "document_profiles.parquet"
        evidence_cards_path = base_dir / "evidence_cards.parquet"
        comparison_rows_path = base_dir / "comparison_rows.parquet"
        sections_path = base_dir / "sections.parquet"
        procedure_blocks_path = base_dir / "procedure_blocks.parquet"
        protocol_steps_path = base_dir / "protocol_steps.parquet"
        graphml_path = base_dir / "graph.graphml"

        documents_generated = documents_path.exists()
        document_profiles_generated = document_profiles_path.exists()
        evidence_cards_generated = evidence_cards_path.exists()
        comparison_rows_generated = comparison_rows_path.exists()
        document_profiles_ready = self._parquet_has_rows(document_profiles_path)
        evidence_cards_ready = self._parquet_has_rows(evidence_cards_path)
        comparison_rows_ready = self._parquet_has_rows(comparison_rows_path)
        graph_generated = (
            document_profiles_generated
            and evidence_cards_generated
            and comparison_rows_generated
        )
        graph_ready = graph_generated and (
            document_profiles_ready or evidence_cards_ready or comparison_rows_ready
        )
        sections_generated = sections_path.exists()
        procedure_blocks_generated = procedure_blocks_path.exists()
        protocol_steps_generated = protocol_steps_path.exists()
        graphml_generated = graphml_path.exists()

        return {
            "collection_id": collection_id,
            "output_path": str(base_dir),
            "documents_generated": documents_generated,
            "documents_ready": self._parquet_has_rows(documents_path),
            "document_profiles_generated": document_profiles_generated,
            "document_profiles_ready": document_profiles_ready,
            "evidence_cards_generated": evidence_cards_generated,
            "evidence_cards_ready": evidence_cards_ready,
            "comparison_rows_generated": comparison_rows_generated,
            "comparison_rows_ready": comparison_rows_ready,
            "graph_generated": graph_generated,
            "graph_ready": graph_ready,
            "sections_generated": sections_generated,
            "sections_ready": self._parquet_has_rows(sections_path),
            "procedure_blocks_generated": procedure_blocks_generated,
            "procedure_blocks_ready": self._parquet_has_rows(procedure_blocks_path),
            "protocol_steps_generated": protocol_steps_generated,
            "protocol_steps_ready": self._parquet_has_rows(protocol_steps_path),
            "graphml_generated": graphml_generated,
            "graphml_ready": graphml_generated,
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
