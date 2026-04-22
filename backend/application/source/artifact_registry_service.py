from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    evaluate_collection_reassessment_reasons,
)
from domain.ports import ArtifactRepository
from domain.source import ArtifactStatusRecord
from infra.persistence.factory import build_artifact_repository
from infra.persistence.backbone_codec import restore_frame_from_storage


_COMPARABLE_RESULT_JSON_COLUMNS = (
    "binding",
    "normalized_context",
    "axis",
    "value",
    "evidence",
)
_COLLECTION_COMPARABLE_RESULT_JSON_COLUMNS = ("assessment", "reassessment_triggers")


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

    def build_registry(
        self,
        collection_id: str,
        output_dir: str | Path,
        *,
        previous_payload: dict | None = None,
    ) -> dict:
        base_dir = Path(output_dir).expanduser().resolve()
        documents_path = base_dir / "documents.parquet"
        document_profiles_path = base_dir / "document_profiles.parquet"
        evidence_anchors_path = base_dir / "evidence_anchors.parquet"
        method_facts_path = base_dir / "method_facts.parquet"
        evidence_cards_path = base_dir / "evidence_cards.parquet"
        characterization_observations_path = base_dir / "characterization_observations.parquet"
        structure_features_path = base_dir / "structure_features.parquet"
        test_conditions_path = base_dir / "test_conditions.parquet"
        baseline_references_path = base_dir / "baseline_references.parquet"
        sample_variants_path = base_dir / "sample_variants.parquet"
        measurement_results_path = base_dir / "measurement_results.parquet"
        comparable_results_path = base_dir / "comparable_results.parquet"
        collection_comparable_results_path = (
            base_dir / "collection_comparable_results.parquet"
        )
        comparison_rows_path = base_dir / "comparison_rows.parquet"
        blocks_path = base_dir / "blocks.parquet"
        figures_path = base_dir / "figures.parquet"
        table_rows_path = base_dir / "table_rows.parquet"
        table_cells_path = base_dir / "table_cells.parquet"
        procedure_blocks_path = base_dir / "procedure_blocks.parquet"
        protocol_steps_path = base_dir / "protocol_steps.parquet"
        collection_scope_stale = self._collection_scope_artifacts_stale(
            collection_id=collection_id,
            comparable_results_path=comparable_results_path,
            collection_comparable_results_path=collection_comparable_results_path,
        )
        payload = ArtifactStatusRecord.build(
            collection_id=collection_id,
            output_path=str(base_dir),
            documents_generated=documents_path.exists(),
            documents_ready=self._parquet_has_rows(documents_path),
            document_profiles_generated=document_profiles_path.exists(),
            document_profiles_ready=self._parquet_has_rows(document_profiles_path),
            evidence_anchors_generated=evidence_anchors_path.exists(),
            evidence_anchors_ready=self._parquet_has_rows(evidence_anchors_path),
            method_facts_generated=method_facts_path.exists(),
            method_facts_ready=self._parquet_has_rows(method_facts_path),
            evidence_cards_generated=evidence_cards_path.exists(),
            evidence_cards_ready=self._parquet_has_rows(evidence_cards_path),
            characterization_observations_generated=characterization_observations_path.exists(),
            characterization_observations_ready=self._parquet_has_rows(
                characterization_observations_path
            ),
            structure_features_generated=structure_features_path.exists(),
            structure_features_ready=self._parquet_has_rows(structure_features_path),
            test_conditions_generated=test_conditions_path.exists(),
            test_conditions_ready=self._parquet_has_rows(test_conditions_path),
            baseline_references_generated=baseline_references_path.exists(),
            baseline_references_ready=self._parquet_has_rows(baseline_references_path),
            sample_variants_generated=sample_variants_path.exists(),
            sample_variants_ready=self._parquet_has_rows(sample_variants_path),
            measurement_results_generated=measurement_results_path.exists(),
            measurement_results_ready=self._parquet_has_rows(measurement_results_path),
            comparable_results_generated=comparable_results_path.exists(),
            comparable_results_ready=self._parquet_has_rows(comparable_results_path),
            collection_comparable_results_generated=collection_comparable_results_path.exists(),
            collection_comparable_results_ready=self._parquet_has_rows(
                collection_comparable_results_path
            ),
            collection_comparable_results_stale=collection_scope_stale,
            comparison_rows_generated=comparison_rows_path.exists(),
            comparison_rows_ready=self._parquet_has_rows(comparison_rows_path),
            comparison_rows_stale=collection_scope_stale and comparison_rows_path.exists(),
            graph_stale=collection_scope_stale,
            blocks_generated=blocks_path.exists(),
            blocks_ready=self._parquet_has_rows(blocks_path),
            figures_generated=figures_path.exists(),
            figures_ready=self._parquet_has_rows(figures_path),
            table_rows_generated=table_rows_path.exists(),
            table_rows_ready=self._parquet_has_rows(table_rows_path),
            table_cells_generated=table_cells_path.exists(),
            table_cells_ready=self._parquet_has_rows(table_cells_path),
            procedure_blocks_generated=procedure_blocks_path.exists(),
            procedure_blocks_ready=self._parquet_has_rows(procedure_blocks_path),
            protocol_steps_generated=protocol_steps_path.exists(),
            protocol_steps_ready=self._parquet_has_rows(protocol_steps_path),
            updated_at=_now_iso(),
        ).to_record()
        if previous_payload is None:
            return payload
        normalized_previous = ArtifactStatusRecord.from_mapping(
            previous_payload,
            collection_id=collection_id,
        ).to_record()
        if self._payload_without_updated_at(normalized_previous) == self._payload_without_updated_at(
            payload
        ):
            payload["updated_at"] = normalized_previous["updated_at"]
        return payload

    def _parquet_has_rows(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            frame = pd.read_parquet(path)
        except Exception:  # noqa: BLE001
            return False
        return not frame.empty

    def upsert(self, collection_id: str, output_dir: str | Path) -> dict:
        previous_payload = self.repository.read(collection_id)
        payload = self.build_registry(
            collection_id,
            output_dir,
            previous_payload=previous_payload,
        )
        self.repository.write(collection_id, payload)
        return payload

    def get(self, collection_id: str) -> dict:
        payload = self.repository.read(collection_id)
        if payload is None:
            raise FileNotFoundError(f"artifact registry not found: {collection_id}")
        normalized = ArtifactStatusRecord.from_mapping(
            payload,
            collection_id=collection_id,
        ).to_record()
        output_path = normalized.get("output_path")
        if output_path:
            normalized = self.build_registry(
                collection_id,
                output_path,
                previous_payload=normalized,
            )
        if normalized != payload:
            self.repository.write(collection_id, normalized)
        return normalized

    def _collection_scope_artifacts_stale(
        self,
        *,
        collection_id: str,
        comparable_results_path: Path,
        collection_comparable_results_path: Path,
    ) -> bool:
        if not comparable_results_path.exists() or not collection_comparable_results_path.exists():
            return False
        try:
            comparable_results = restore_frame_from_storage(
                pd.read_parquet(comparable_results_path),
                _COMPARABLE_RESULT_JSON_COLUMNS,
            )
            collection_comparable_results = restore_frame_from_storage(
                pd.read_parquet(collection_comparable_results_path),
                _COLLECTION_COMPARABLE_RESULT_JSON_COLUMNS,
            )
        except Exception:  # noqa: BLE001
            return False
        if comparable_results.empty or collection_comparable_results.empty:
            return False

        comparable_records: list[ComparableResult] = []
        for _, row in comparable_results.iterrows():
            comparable_record = ComparableResult.from_mapping(dict(row))
            if comparable_record.comparable_result_id:
                comparable_records.append(comparable_record)
        scoped_records = [
            CollectionComparableResult.from_mapping(dict(row))
            for _, row in collection_comparable_results.iterrows()
        ]
        scoped_records_by_result_id = {
            record.comparable_result_id: record
            for record in scoped_records
            if record.collection_id == collection_id and record.comparable_result_id
        }
        comparable_result_ids = {
            record.comparable_result_id for record in comparable_records if record.comparable_result_id
        }
        if comparable_result_ids != set(scoped_records_by_result_id):
            return True
        for comparable_record in comparable_records:
            scoped_record = scoped_records_by_result_id.get(
                comparable_record.comparable_result_id
            )
            if scoped_record is None:
                return True
            if evaluate_collection_reassessment_reasons(scoped_record, comparable_record):
                return True
        return False

    def _payload_without_updated_at(self, payload: dict) -> dict:
        return {key: value for key, value in payload.items() if key != "updated_at"}
