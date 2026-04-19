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
        characterization_observations_path = base_dir / "characterization_observations.parquet"
        structure_features_path = base_dir / "structure_features.parquet"
        test_conditions_path = base_dir / "test_conditions.parquet"
        baseline_references_path = base_dir / "baseline_references.parquet"
        sample_variants_path = base_dir / "sample_variants.parquet"
        measurement_results_path = base_dir / "measurement_results.parquet"
        comparison_rows_path = base_dir / "comparison_rows.parquet"
        sections_path = base_dir / "sections.parquet"
        table_cells_path = base_dir / "table_cells.parquet"
        procedure_blocks_path = base_dir / "procedure_blocks.parquet"
        protocol_steps_path = base_dir / "protocol_steps.parquet"
        graphml_path = base_dir / "graph.graphml"

        documents_generated = documents_path.exists()
        document_profiles_generated = document_profiles_path.exists()
        evidence_cards_generated = evidence_cards_path.exists()
        characterization_observations_generated = characterization_observations_path.exists()
        structure_features_generated = structure_features_path.exists()
        test_conditions_generated = test_conditions_path.exists()
        baseline_references_generated = baseline_references_path.exists()
        sample_variants_generated = sample_variants_path.exists()
        measurement_results_generated = measurement_results_path.exists()
        comparison_rows_generated = comparison_rows_path.exists()
        document_profiles_ready = self._parquet_has_rows(document_profiles_path)
        evidence_cards_ready = self._parquet_has_rows(evidence_cards_path)
        characterization_observations_ready = self._parquet_has_rows(
            characterization_observations_path
        )
        structure_features_ready = self._parquet_has_rows(structure_features_path)
        test_conditions_ready = self._parquet_has_rows(test_conditions_path)
        baseline_references_ready = self._parquet_has_rows(baseline_references_path)
        sample_variants_ready = self._parquet_has_rows(sample_variants_path)
        measurement_results_ready = self._parquet_has_rows(measurement_results_path)
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
        table_cells_generated = table_cells_path.exists()
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
            "characterization_observations_generated": characterization_observations_generated,
            "characterization_observations_ready": characterization_observations_ready,
            "structure_features_generated": structure_features_generated,
            "structure_features_ready": structure_features_ready,
            "test_conditions_generated": test_conditions_generated,
            "test_conditions_ready": test_conditions_ready,
            "baseline_references_generated": baseline_references_generated,
            "baseline_references_ready": baseline_references_ready,
            "sample_variants_generated": sample_variants_generated,
            "sample_variants_ready": sample_variants_ready,
            "measurement_results_generated": measurement_results_generated,
            "measurement_results_ready": measurement_results_ready,
            "comparison_rows_generated": comparison_rows_generated,
            "comparison_rows_ready": comparison_rows_ready,
            "graph_generated": graph_generated,
            "graph_ready": graph_ready,
            "sections_generated": sections_generated,
            "sections_ready": self._parquet_has_rows(sections_path),
            "table_cells_generated": table_cells_generated,
            "table_cells_ready": self._parquet_has_rows(table_cells_path),
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
