from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from domain.ports import (
    ArtifactRepository,
    CoreFactRepository,
    SourceArtifactRepository,
)
from domain.source import ArtifactStatusRecord
from infra.persistence.factory import (
    build_artifact_repository,
    build_core_fact_repository,
    build_source_artifact_repository,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactRegistryService:
    """Track which collection-level artifacts are ready for downstream use."""

    def __init__(
        self,
        root_dir: Path | None = None,
        repository: ArtifactRepository | None = None,
        source_artifact_repository: SourceArtifactRepository | None = None,
        core_fact_repository: CoreFactRepository | None = None,
    ) -> None:
        self.repository = repository or build_artifact_repository(root_dir)
        self.root_dir = self.repository.root_dir
        db_path = self.root_dir.parent / "lens.sqlite"
        self.source_artifact_repository = (
            source_artifact_repository or build_source_artifact_repository(db_path)
        )
        self.core_fact_repository = (
            core_fact_repository or build_core_fact_repository(db_path)
        )

    def build_registry(
        self,
        collection_id: str,
        output_dir: str | Path,
        *,
        previous_payload: dict | None = None,
    ) -> dict:
        base_dir = Path(output_dir).expanduser().resolve()
        source_artifacts = self.source_artifact_repository.read_collection_artifacts(
            collection_id
        )
        core_facts = self.core_fact_repository.read_collection_facts(collection_id)
        source_artifacts_generated = not source_artifacts.is_empty()
        payload = ArtifactStatusRecord.build(
            collection_id=collection_id,
            output_path=str(base_dir),
            documents_generated=bool(source_artifacts.documents),
            documents_ready=bool(source_artifacts.documents),
            document_profiles_generated=bool(core_facts.document_profiles),
            document_profiles_ready=bool(core_facts.document_profiles),
            evidence_anchors_generated=core_facts.paper_facts_generated,
            evidence_anchors_ready=bool(core_facts.evidence_anchors),
            method_facts_generated=core_facts.paper_facts_generated,
            method_facts_ready=bool(core_facts.method_facts),
            evidence_cards_generated=core_facts.evidence_cards_generated,
            evidence_cards_ready=core_facts.evidence_cards_ready,
            characterization_observations_generated=core_facts.paper_facts_generated,
            characterization_observations_ready=bool(
                core_facts.characterization_observations
            ),
            structure_features_generated=core_facts.paper_facts_generated,
            structure_features_ready=bool(core_facts.structure_features),
            test_conditions_generated=core_facts.paper_facts_generated,
            test_conditions_ready=bool(core_facts.test_conditions),
            baseline_references_generated=core_facts.paper_facts_generated,
            baseline_references_ready=bool(core_facts.baseline_references),
            sample_variants_generated=core_facts.paper_facts_generated,
            sample_variants_ready=bool(core_facts.sample_variants),
            measurement_results_generated=core_facts.paper_facts_generated,
            measurement_results_ready=bool(core_facts.measurement_results),
            comparable_results_generated=core_facts.comparison_artifacts_generated,
            comparable_results_ready=bool(core_facts.comparable_results),
            collection_comparable_results_generated=(
                core_facts.comparison_artifacts_generated
            ),
            collection_comparable_results_ready=bool(
                core_facts.collection_comparable_results
            ),
            collection_comparable_results_stale=False,
            comparison_rows_generated=core_facts.comparison_artifacts_generated,
            comparison_rows_ready=bool(core_facts.comparison_rows),
            comparison_rows_stale=False,
            graph_stale=False,
            blocks_generated=source_artifacts_generated,
            blocks_ready=bool(source_artifacts.blocks),
            figures_generated=source_artifacts_generated,
            figures_ready=bool(source_artifacts.figures),
            table_rows_generated=source_artifacts_generated,
            table_rows_ready=bool(source_artifacts.table_rows),
            table_cells_generated=source_artifacts_generated,
            table_cells_ready=bool(source_artifacts.table_cells),
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


    def _payload_without_updated_at(self, payload: dict) -> dict:
        return {key: value for key, value in payload.items() if key != "updated_at"}
