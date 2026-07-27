from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.ports import (
    BuildRepository,
    ComparisonRepository,
    PaperFactRepository,
    SourceArtifactRepository,
)
from domain.source import ArtifactStatusRecord, ArtifactVersionRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_ARTIFACT_FIELDS = (
    ("documents", "documents_generated", "documents_ready", None),
    (
        "document_profiles",
        "document_profiles_generated",
        "document_profiles_ready",
        None,
    ),
    (
        "evidence_anchors",
        "evidence_anchors_generated",
        "evidence_anchors_ready",
        None,
    ),
    ("method_facts", "method_facts_generated", "method_facts_ready", None),
    (
        "evidence_cards",
        "evidence_cards_generated",
        "evidence_cards_ready",
        None,
    ),
    (
        "characterization_observations",
        "characterization_observations_generated",
        "characterization_observations_ready",
        None,
    ),
    (
        "structure_features",
        "structure_features_generated",
        "structure_features_ready",
        None,
    ),
    (
        "test_conditions",
        "test_conditions_generated",
        "test_conditions_ready",
        None,
    ),
    (
        "baseline_references",
        "baseline_references_generated",
        "baseline_references_ready",
        None,
    ),
    (
        "sample_variants",
        "sample_variants_generated",
        "sample_variants_ready",
        None,
    ),
    (
        "measurement_results",
        "measurement_results_generated",
        "measurement_results_ready",
        None,
    ),
    (
        "comparable_results",
        "comparable_results_generated",
        "comparable_results_ready",
        None,
    ),
    (
        "collection_comparable_results",
        "collection_comparable_results_generated",
        "collection_comparable_results_ready",
        "collection_comparable_results_stale",
    ),
    (
        "comparison_rows",
        "comparison_rows_generated",
        "comparison_rows_ready",
        "comparison_rows_stale",
    ),
    ("blocks", "blocks_generated", "blocks_ready", None),
    ("figures", "figures_generated", "figures_ready", None),
    ("table_rows", "table_rows_generated", "table_rows_ready", None),
    ("table_cells", "table_cells_generated", "table_cells_ready", None),
)


class ArtifactRegistryService:
    """Track which collection-level artifacts are ready for downstream use."""

    def __init__(
        self,
        repository: BuildRepository,
        source_artifact_repository: SourceArtifactRepository,
        paper_fact_repository: PaperFactRepository,
        comparison_repository: ComparisonRepository,
    ) -> None:
        self.repository = repository
        self.source_artifact_repository = source_artifact_repository
        self.paper_fact_repository = paper_fact_repository
        self.comparison_repository = comparison_repository

    def build_registry(
        self,
        collection_id: str,
        output_dir: str | Path,
        *,
        build_id: str | None = None,
    ) -> dict:
        base_dir = Path(output_dir).expanduser().resolve()
        source_artifacts = (
            self.source_artifact_repository.read_collection_artifacts(
                collection_id,
                build_id=build_id,
            )
            if build_id is not None
            else self.source_artifact_repository.read_collection_artifacts(
                collection_id
            )
        )
        paper_facts = self.paper_fact_repository.read(
            collection_id,
            build_id=build_id,
        )
        comparison_facts = self.comparison_repository.read(
            collection_id,
            build_id=build_id,
        )
        evidence_cards_generated = paper_facts.paper_facts_generated
        evidence_cards_ready = paper_facts.evidence_cards_ready
        comparison_rows_ready = bool(
            comparison_facts.comparable_results
            and any(
                result.included
                for result in comparison_facts.collection_comparable_results
            )
        )
        source_artifacts_generated = not source_artifacts.is_empty()
        payload = ArtifactStatusRecord.build(
            collection_id=collection_id,
            output_path=str(base_dir),
            documents_generated=bool(source_artifacts.documents),
            documents_ready=bool(source_artifacts.documents),
            document_profiles_generated=bool(paper_facts.document_profiles),
            document_profiles_ready=bool(paper_facts.document_profiles),
            evidence_anchors_generated=paper_facts.paper_facts_generated,
            evidence_anchors_ready=bool(paper_facts.evidence_anchors),
            method_facts_generated=paper_facts.paper_facts_generated,
            method_facts_ready=bool(paper_facts.method_facts),
            evidence_cards_generated=evidence_cards_generated,
            evidence_cards_ready=evidence_cards_ready,
            characterization_observations_generated=paper_facts.paper_facts_generated,
            characterization_observations_ready=bool(
                paper_facts.characterization_observations
            ),
            structure_features_generated=paper_facts.paper_facts_generated,
            structure_features_ready=bool(paper_facts.structure_features),
            test_conditions_generated=paper_facts.paper_facts_generated,
            test_conditions_ready=bool(paper_facts.test_conditions),
            baseline_references_generated=paper_facts.paper_facts_generated,
            baseline_references_ready=bool(paper_facts.baseline_references),
            sample_variants_generated=paper_facts.paper_facts_generated,
            sample_variants_ready=bool(paper_facts.sample_variants),
            measurement_results_generated=paper_facts.paper_facts_generated,
            measurement_results_ready=bool(paper_facts.measurement_results),
            comparable_results_generated=comparison_facts.comparison_artifacts_generated,
            comparable_results_ready=bool(comparison_facts.comparable_results),
            collection_comparable_results_generated=(
                comparison_facts.comparison_artifacts_generated
            ),
            collection_comparable_results_ready=bool(
                comparison_facts.collection_comparable_results
            ),
            collection_comparable_results_stale=False,
            comparison_rows_generated=comparison_facts.comparison_artifacts_generated,
            comparison_rows_ready=comparison_rows_ready,
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
        return payload

    def register(
        self,
        task_id: str,
        collection_id: str,
        output_dir: str | Path,
        *,
        build_id: str | None = None,
    ) -> dict:
        stage = next(
            (
                item
                for item in self.repository.list_stages(task_id)
                if item.stage_kind == "artifact_registry"
            ),
            None,
        )
        if stage is None:
            raise RuntimeError(f"artifact_registry stage not found for task: {task_id}")
        payload = self.build_registry(collection_id, output_dir, build_id=build_id)
        records = tuple(
            ArtifactVersionRecord(
                artifact_version_id=f"artifact_{uuid4().hex[:20]}",
                build_stage_id=stage.stage_id,
                artifact_kind=artifact_kind,
                schema_version=1,
                content_version=1,
                status=(
                    "stale"
                    if stale_field is not None and payload[stale_field]
                    else "ready"
                    if payload[ready_field]
                    else "generated"
                ),
                object_id=None,
                details={},
                created_at=payload["updated_at"],
            )
            for artifact_kind, generated_field, ready_field, stale_field in _ARTIFACT_FIELDS
            if payload[generated_field]
        )
        self.repository.add_artifact_versions(task_id, records)
        return payload

    def get_for_task(self, task_id: str) -> dict:
        task = self.repository.read_task(task_id)
        if task is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        versions = self.repository.list_artifact_versions(task_id)
        if not versions:
            raise FileNotFoundError(f"artifact registry not found for task: {task_id}")
        payload: dict = {
            "collection_id": task.collection_id,
            "output_path": task.output_path or "",
            "updated_at": max(version.created_at for version in versions),
        }
        fields_by_kind = {item[0]: item[1:] for item in _ARTIFACT_FIELDS}
        for version in versions:
            fields = fields_by_kind.get(version.artifact_kind)
            if fields is None:
                continue
            generated_field, ready_field, stale_field = fields
            payload[generated_field] = True
            payload[ready_field] = version.status == "ready"
            if stale_field is not None:
                payload[stale_field] = version.status == "stale"
        return ArtifactStatusRecord.from_mapping(
            payload,
            collection_id=task.collection_id,
        ).to_record()
