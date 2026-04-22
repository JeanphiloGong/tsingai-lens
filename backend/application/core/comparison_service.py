from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from application.core.comparison_assembly import (
    COLLECTION_COMPARABLE_RESULT_COLUMNS,
    ComparableResultAssembler,
    ComparisonInputFrames,
    ComparisonSemanticTables,
)
from application.core.comparison_projection import ComparisonRowProjector
from application.core.semantic_build.core_semantic_version import (
    core_semantic_rebuild_required,
    write_core_semantic_manifest,
)
from application.source.collection_service import CollectionService
from application.core.semantic_build.paper_facts_service import PaperFactsNotReadyError, PaperFactsService
from application.source.artifact_registry_service import ArtifactRegistryService
from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    evaluate_collection_reassessment_reasons,
)
from infra.persistence.backbone_codec import (
    prepare_frame_for_storage,
    restore_frame_from_storage,
)

logger = logging.getLogger(__name__)


_COMPARABLE_RESULTS_FILE = "comparable_results.parquet"
_COLLECTION_COMPARABLE_RESULTS_FILE = "collection_comparable_results.parquet"
_COMPARISON_ROWS_FILE = "comparison_rows.parquet"
_SAMPLE_VARIANTS_FILE = "sample_variants.parquet"
_MEASUREMENT_RESULTS_FILE = "measurement_results.parquet"
_TEST_CONDITIONS_FILE = "test_conditions.parquet"
_BASELINE_REFERENCES_FILE = "baseline_references.parquet"
_SAMPLE_VARIANT_JSON_COLUMNS = (
    "host_material_system",
    "process_context",
    "profile_payload",
    "structure_feature_ids",
    "source_anchor_ids",
)
_MEASUREMENT_RESULT_JSON_COLUMNS = (
    "value_payload",
    "structure_feature_ids",
    "characterization_observation_ids",
    "evidence_anchor_ids",
)
_TEST_CONDITION_JSON_COLUMNS = (
    "condition_payload",
    "missing_fields",
    "evidence_anchor_ids",
)
_BASELINE_REFERENCE_JSON_COLUMNS = ("evidence_anchor_ids",)
_COMPARABLE_RESULT_JSON_COLUMNS = (
    "binding",
    "normalized_context",
    "axis",
    "value",
    "evidence",
)
_COLLECTION_COMPARABLE_RESULT_JSON_COLUMNS = ("assessment", "reassessment_triggers")
_COMPARISON_JSON_COLUMNS = (
    "supporting_evidence_ids",
    "supporting_anchor_ids",
    "characterization_observation_ids",
    "structure_feature_ids",
    "comparability_warnings",
    "comparability_basis",
    "missing_critical_context",
)


class ComparisonRowsNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve comparison rows."""

    def __init__(self, collection_id: str, output_dir: Path) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"comparison rows not ready: {collection_id}")


class ComparisonRowNotFoundError(FileNotFoundError):
    """Raised when one comparison row is missing from a collection."""

    def __init__(self, collection_id: str, row_id: str) -> None:
        self.collection_id = collection_id
        self.row_id = row_id
        super().__init__(f"comparison row not found: {collection_id}/{row_id}")


class ComparisonService:
    """Generate and serve collection-scoped comparison artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        paper_facts_service: PaperFactsService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )
        self.comparable_result_assembler = ComparableResultAssembler()
        self.comparison_row_projector = ComparisonRowProjector()

    def list_comparison_rows(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
    ) -> dict[str, Any]:
        rows = self.read_comparison_rows(collection_id)
        rows = self._filter_rows(
            rows,
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
        )
        items = [
            self._serialize_row(item)
            for _, item in rows.iloc[offset : offset + limit].iterrows()
        ]
        return {
            "collection_id": collection_id,
            "total": len(rows),
            "count": len(items),
            "items": items,
        }

    def get_comparison_row(
        self,
        collection_id: str,
        row_id: str,
    ) -> dict[str, Any]:
        rows = self.read_comparison_rows(collection_id)
        matched = rows[rows["row_id"].astype(str) == str(row_id)]
        if matched.empty:
            raise ComparisonRowNotFoundError(collection_id, row_id)
        return self._serialize_row(matched.iloc[0])

    def read_comparison_rows(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        # `comparison_rows.parquet` is a materialized projection cache; semantic truth lives
        # in comparable results plus collection-scoped assessments.
        semantic_tables = self._read_semantic_comparison_artifacts(
            collection_id,
            output_dir,
        )
        rows = self.comparison_row_projector.project_rows_from_semantic_artifacts(
            collection_id=collection_id,
            comparable_results=semantic_tables.comparable_results,
            scoped_results=semantic_tables.collection_comparable_results,
        )
        self._materialize_row_cache_if_missing(collection_id, output_dir, rows)
        return rows

    def read_comparable_results(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        semantic_tables = self._read_semantic_comparison_artifacts(
            collection_id,
            output_dir,
        )
        return semantic_tables.comparable_results

    def read_collection_comparable_results(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        semantic_tables = self._read_semantic_comparison_artifacts(
            collection_id,
            output_dir,
        )
        return semantic_tables.collection_comparable_results

    def inspect_document_comparison_semantics(
        self,
        collection_id: str,
        source_document_id: str,
        *,
        include_row_projections: bool = False,
    ) -> dict[str, Any]:
        output_dir = self._resolve_output_dir(collection_id)
        semantic_tables = self._read_semantic_comparison_artifacts(
            collection_id,
            output_dir,
        )
        document_id = self._safe_text(source_document_id) or ""
        comparable_results = semantic_tables.comparable_results
        document_results = comparable_results[
            comparable_results["source_document_id"].apply(
                lambda value: self._safe_text(value) == document_id
            )
        ].copy()
        if document_results.empty:
            return {
                "collection_id": collection_id,
                "source_document_id": document_id,
                "total": 0,
                "count": 0,
                "items": [],
            }

        comparable_records = [
            ComparableResult.from_mapping(dict(row))
            for _, row in document_results.iterrows()
        ]
        comparable_result_ids = {
            record.comparable_result_id
            for record in comparable_records
            if record.comparable_result_id
        }
        scoped_results = semantic_tables.collection_comparable_results.iloc[0:0].copy()
        scoped_records_by_result_id: dict[str, list[CollectionComparableResult]] = {}
        sort_order_by_result_id: dict[str, int] = {}
        if comparable_result_ids:
            scoped_results = semantic_tables.collection_comparable_results[
                semantic_tables.collection_comparable_results["comparable_result_id"].apply(
                    lambda value: self._safe_text(value) in comparable_result_ids
                )
            ].copy()
            for _, row in scoped_results.iterrows():
                scoped_record = CollectionComparableResult.from_mapping(dict(row))
                if self._safe_text(scoped_record.collection_id) != collection_id:
                    continue
                scoped_records_by_result_id.setdefault(
                    scoped_record.comparable_result_id,
                    [],
                ).append(scoped_record)
                if scoped_record.sort_order is None:
                    continue
                existing_sort_order = sort_order_by_result_id.get(
                    scoped_record.comparable_result_id
                )
                sort_order_by_result_id[scoped_record.comparable_result_id] = (
                    scoped_record.sort_order
                    if existing_sort_order is None
                    else min(existing_sort_order, scoped_record.sort_order)
                )

        projected_rows_by_result_id: dict[str, list[dict[str, Any]]] = {}
        if include_row_projections:
            projected_rows = self.comparison_row_projector.project_rows_from_semantic_artifacts(
                collection_id=collection_id,
                comparable_results=document_results,
                scoped_results=scoped_results,
            )
            for _, row in projected_rows.iterrows():
                row_record = ComparisonRowRecord.from_mapping(dict(row))
                projected_rows_by_result_id.setdefault(
                    row_record.comparable_result_id,
                    [],
                ).append(self._serialize_row_record(row_record))

        comparable_records.sort(
            key=lambda record: (
                sort_order_by_result_id.get(record.comparable_result_id, 1_000_000_000),
                record.comparable_result_id,
            )
        )
        items: list[dict[str, Any]] = []
        for record in comparable_records:
            item = self._serialize_comparable_result(record)
            scoped_records = scoped_records_by_result_id.get(record.comparable_result_id, [])
            item["collection_overlays"] = [
                self._serialize_collection_comparable_result(scoped_record)
                for scoped_record in sorted(
                    scoped_records,
                    key=lambda scoped_record: (
                        1_000_000_000
                        if scoped_record.sort_order is None
                        else scoped_record.sort_order,
                        scoped_record.comparable_result_id,
                    ),
                )
            ]
            if include_row_projections:
                item["projected_rows"] = projected_rows_by_result_id.get(
                    record.comparable_result_id,
                    [],
                )
            items.append(item)
        return {
            "collection_id": collection_id,
            "source_document_id": document_id,
            "total": len(items),
            "count": len(items),
            "items": items,
        }

    def _read_semantic_comparison_artifacts(
        self,
        collection_id: str,
        output_dir: Path,
    ) -> ComparisonSemanticTables:
        self._ensure_semantic_comparison_artifacts_ready(collection_id, output_dir)
        comparable_results = restore_frame_from_storage(
            pd.read_parquet(output_dir / _COMPARABLE_RESULTS_FILE),
            _COMPARABLE_RESULT_JSON_COLUMNS,
        )
        scoped_results = restore_frame_from_storage(
            pd.read_parquet(output_dir / _COLLECTION_COMPARABLE_RESULTS_FILE),
            _COLLECTION_COMPARABLE_RESULT_JSON_COLUMNS,
        )
        semantic_tables = ComparisonSemanticTables(
            comparable_results=self.comparable_result_assembler.normalize_comparable_results_table(
                comparable_results
            ),
            collection_comparable_results=self.comparable_result_assembler.normalize_collection_comparable_results_table(
                scoped_results
            ),
        )
        return self._refresh_scope_artifacts_if_stale(
            collection_id=collection_id,
            output_dir=output_dir,
            semantic_tables=semantic_tables,
        )

    def _ensure_semantic_comparison_artifacts_ready(
        self,
        collection_id: str,
        output_dir: Path,
    ) -> None:
        documents_path = output_dir / "documents.parquet"
        comparable_results_path = output_dir / _COMPARABLE_RESULTS_FILE
        scoped_results_path = output_dir / _COLLECTION_COMPARABLE_RESULTS_FILE
        semantic_artifacts_missing = (
            not comparable_results_path.is_file() or not scoped_results_path.is_file()
        )
        if core_semantic_rebuild_required(output_dir) and documents_path.is_file():
            self.build_comparison_rows(collection_id, output_dir)
            return
        if semantic_artifacts_missing and documents_path.is_file():
            self.build_comparison_rows(collection_id, output_dir)
            return
        if semantic_artifacts_missing:
            raise ComparisonRowsNotReadyError(collection_id, output_dir)

    def _materialize_row_cache_if_missing(
        self,
        collection_id: str,
        output_dir: Path,
        rows: pd.DataFrame,
    ) -> None:
        path = output_dir / _COMPARISON_ROWS_FILE
        if path.is_file():
            return
        prepare_frame_for_storage(
            self.comparison_row_projector.normalize_rows_table(rows, collection_id),
            _COMPARISON_JSON_COLUMNS,
        ).to_parquet(path, index=False)
        self.artifact_registry_service.upsert(collection_id, output_dir)

    def _refresh_scope_artifacts_if_stale(
        self,
        *,
        collection_id: str,
        output_dir: Path,
        semantic_tables: ComparisonSemanticTables,
    ) -> ComparisonSemanticTables:
        comparable_results = semantic_tables.comparable_results
        scoped_results = semantic_tables.collection_comparable_results
        if comparable_results.empty:
            return semantic_tables

        comparable_records = [
            ComparableResult.from_mapping(dict(row))
            for _, row in comparable_results.iterrows()
        ]
        scoped_records_by_result_id = {
            record.comparable_result_id: record
            for record in (
                CollectionComparableResult.from_mapping(dict(row))
                for _, row in scoped_results.iterrows()
            )
            if self._safe_text(record.collection_id) == collection_id
            and self._safe_text(record.comparable_result_id)
        }
        comparable_result_ids = {
            record.comparable_result_id
            for record in comparable_records
            if self._safe_text(record.comparable_result_id)
        }
        if comparable_result_ids != set(scoped_records_by_result_id):
            logger.info(
                "Comparison scope artifact refresh triggered by membership drift collection_id=%s comparable_results=%s scoped_results=%s",
                collection_id,
                len(comparable_result_ids),
                len(scoped_records_by_result_id),
            )
            return self._rebuild_scope_and_row_artifacts(
                collection_id=collection_id,
                output_dir=output_dir,
                comparable_records=comparable_records,
                comparable_results=comparable_results,
                scoped_records_by_result_id=scoped_records_by_result_id,
            )
        for comparable_record in comparable_records:
            scoped_record = scoped_records_by_result_id.get(comparable_record.comparable_result_id)
            if scoped_record is None:
                return self._rebuild_scope_and_row_artifacts(
                    collection_id=collection_id,
                    output_dir=output_dir,
                    comparable_records=comparable_records,
                    comparable_results=comparable_results,
                    scoped_records_by_result_id=scoped_records_by_result_id,
                )
            reassessment_reasons = evaluate_collection_reassessment_reasons(
                scoped_record,
                comparable_record,
            )
            if reassessment_reasons:
                logger.info(
                    "Comparison scope artifact refresh triggered collection_id=%s comparable_result_id=%s reasons=%s",
                    collection_id,
                    comparable_record.comparable_result_id,
                    ",".join(reassessment_reasons),
                )
                return self._rebuild_scope_and_row_artifacts(
                    collection_id=collection_id,
                    output_dir=output_dir,
                    comparable_records=comparable_records,
                    comparable_results=comparable_results,
                    scoped_records_by_result_id=scoped_records_by_result_id,
                )
        return semantic_tables

    def _rebuild_scope_and_row_artifacts(
        self,
        *,
        collection_id: str,
        output_dir: Path,
        comparable_records: list[ComparableResult],
        comparable_results: pd.DataFrame,
        scoped_records_by_result_id: dict[str, CollectionComparableResult],
    ) -> ComparisonSemanticTables:
        refreshed_scoped_records: list[CollectionComparableResult] = []
        next_generated_sort_order = (
            max(
                (
                    scoped_record.sort_order
                    for scoped_record in scoped_records_by_result_id.values()
                    if scoped_record.sort_order is not None
                ),
                default=-1,
            )
            + 1
        )
        for comparable_record in comparable_records:
            existing_scoped_record = scoped_records_by_result_id.get(
                comparable_record.comparable_result_id
            )
            effective_sort_order = (
                existing_scoped_record.sort_order
                if existing_scoped_record is not None
                and existing_scoped_record.sort_order is not None
                else next_generated_sort_order
            )
            if (
                existing_scoped_record is None
                or existing_scoped_record.sort_order is None
            ):
                next_generated_sort_order += 1
            refreshed_scoped_record = self.comparable_result_assembler.build_collection_comparable_result(
                collection_id=collection_id,
                comparable_result=comparable_record,
                sort_order=effective_sort_order,
            )
            if existing_scoped_record is not None:
                refreshed_scoped_record = CollectionComparableResult(
                    collection_id=refreshed_scoped_record.collection_id,
                    comparable_result_id=refreshed_scoped_record.comparable_result_id,
                    assessment=refreshed_scoped_record.assessment,
                    epistemic_status=refreshed_scoped_record.epistemic_status,
                    included=existing_scoped_record.included,
                    sort_order=effective_sort_order,
                    policy_family=refreshed_scoped_record.policy_family,
                    policy_version=refreshed_scoped_record.policy_version,
                    comparable_result_normalization_version=(
                        refreshed_scoped_record.comparable_result_normalization_version
                    ),
                    assessment_input_fingerprint=(
                        refreshed_scoped_record.assessment_input_fingerprint
                    ),
                    reassessment_triggers=refreshed_scoped_record.reassessment_triggers,
                )
            refreshed_scoped_records.append(refreshed_scoped_record)

        refreshed_scoped_results = self.comparable_result_assembler.normalize_collection_comparable_results_table(
            pd.DataFrame(
                [record.to_record() for record in refreshed_scoped_records],
                columns=COLLECTION_COMPARABLE_RESULT_COLUMNS,
            )
        )
        row_table = self.comparison_row_projector.project_rows_from_semantic_artifacts(
            collection_id=collection_id,
            comparable_results=comparable_results,
            scoped_results=refreshed_scoped_results,
        )
        prepare_frame_for_storage(
            refreshed_scoped_results,
            _COLLECTION_COMPARABLE_RESULT_JSON_COLUMNS,
        ).to_parquet(output_dir / _COLLECTION_COMPARABLE_RESULTS_FILE, index=False)
        prepare_frame_for_storage(
            row_table,
            _COMPARISON_JSON_COLUMNS,
        ).to_parquet(output_dir / _COMPARISON_ROWS_FILE, index=False)
        write_core_semantic_manifest(output_dir)
        self.artifact_registry_service.upsert(collection_id, output_dir)
        return ComparisonSemanticTables(
            comparable_results=comparable_results,
            collection_comparable_results=refreshed_scoped_results,
        )

    def build_comparison_rows(
        self,
        collection_id: str,
        output_dir: str | Path | None = None,
    ) -> pd.DataFrame:
        base_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else self._resolve_output_dir(collection_id)
        )
        frames = self._load_comparison_inputs(collection_id, base_dir)
        logger.info(
            "Comparison assembly started collection_id=%s measurement_results=%s sample_variants=%s test_conditions=%s baselines=%s",
            collection_id,
            len(frames.measurement_results),
            len(frames.sample_variants),
            len(frames.test_conditions),
            len(frames.baseline_references),
        )
        if frames.measurement_results.empty:
            logger.warning(
                "Comparison assembly skipped due to empty measurement_results collection_id=%s",
                collection_id,
            )

        semantic_tables = self.comparable_result_assembler.assemble_semantic_tables(
            collection_id=collection_id,
            frames=frames,
        )
        row_table = self.comparison_row_projector.project_rows_from_semantic_artifacts(
            collection_id=collection_id,
            comparable_results=semantic_tables.comparable_results,
            scoped_results=semantic_tables.collection_comparable_results,
        )
        if frames.measurement_results.empty:
            logger.warning(
                "Comparison assembly produced zero rows because upstream measurement_results were empty collection_id=%s",
                collection_id,
            )
        elif row_table.empty:
            logger.warning(
                "Comparison assembly produced zero rows after filtering collection_id=%s measurement_results=%s",
                collection_id,
                len(frames.measurement_results),
            )
        self._write_comparison_artifacts(
            collection_id=collection_id,
            base_dir=base_dir,
            semantic_tables=semantic_tables,
            row_table=row_table,
        )
        logger.info(
            "Comparison assembly finished collection_id=%s comparable_results=%s collection_comparable_results=%s comparison_rows=%s",
            collection_id,
            len(semantic_tables.comparable_results),
            len(semantic_tables.collection_comparable_results),
            len(row_table),
        )
        return row_table

    def _load_comparison_inputs(
        self,
        collection_id: str,
        base_dir: Path,
    ) -> ComparisonInputFrames:
        required = (
            _SAMPLE_VARIANTS_FILE,
            _MEASUREMENT_RESULTS_FILE,
            _TEST_CONDITIONS_FILE,
            _BASELINE_REFERENCES_FILE,
        )
        if any(not (base_dir / name).is_file() for name in required):
            try:
                self.paper_facts_service.build_paper_facts(collection_id, base_dir)
            except PaperFactsNotReadyError as exc:
                raise ComparisonRowsNotReadyError(collection_id, exc.output_dir) from exc

        missing = [name for name in required if not (base_dir / name).is_file()]
        if missing:
            raise ComparisonRowsNotReadyError(collection_id, base_dir)

        return ComparisonInputFrames(
            sample_variants=restore_frame_from_storage(
                pd.read_parquet(base_dir / _SAMPLE_VARIANTS_FILE),
                _SAMPLE_VARIANT_JSON_COLUMNS,
            ),
            measurement_results=restore_frame_from_storage(
                pd.read_parquet(base_dir / _MEASUREMENT_RESULTS_FILE),
                _MEASUREMENT_RESULT_JSON_COLUMNS,
            ),
            test_conditions=restore_frame_from_storage(
                pd.read_parquet(base_dir / _TEST_CONDITIONS_FILE),
                _TEST_CONDITION_JSON_COLUMNS,
            ),
            baseline_references=restore_frame_from_storage(
                pd.read_parquet(base_dir / _BASELINE_REFERENCES_FILE),
                _BASELINE_REFERENCE_JSON_COLUMNS,
            ),
        )

    def _write_comparison_artifacts(
        self,
        *,
        collection_id: str,
        base_dir: Path,
        semantic_tables: ComparisonSemanticTables,
        row_table: pd.DataFrame,
    ) -> None:
        base_dir.mkdir(parents=True, exist_ok=True)
        prepare_frame_for_storage(
            semantic_tables.comparable_results,
            _COMPARABLE_RESULT_JSON_COLUMNS,
        ).to_parquet(base_dir / _COMPARABLE_RESULTS_FILE, index=False)
        prepare_frame_for_storage(
            semantic_tables.collection_comparable_results,
            _COLLECTION_COMPARABLE_RESULT_JSON_COLUMNS,
        ).to_parquet(base_dir / _COLLECTION_COMPARABLE_RESULTS_FILE, index=False)
        prepare_frame_for_storage(
            row_table,
            _COMPARISON_JSON_COLUMNS,
        ).to_parquet(base_dir / _COMPARISON_ROWS_FILE, index=False)
        write_core_semantic_manifest(base_dir)
        self.artifact_registry_service.upsert(collection_id, base_dir)

    def _resolve_output_dir(self, collection_id: str) -> Path:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            artifacts = None
        if artifacts and artifacts.get("output_path"):
            return Path(str(artifacts["output_path"])).expanduser().resolve()
        return self.collection_service.get_paths(collection_id).output_dir.resolve()

    def _filter_rows(
        self,
        rows: pd.DataFrame,
        *,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
    ) -> pd.DataFrame:
        filtered = rows
        filters = {
            "material_system_normalized": self._safe_text(material_system_normalized),
            "property_normalized": self._safe_text(property_normalized),
            "test_condition_normalized": self._safe_text(test_condition_normalized),
            "baseline_normalized": self._safe_text(baseline_normalized),
        }
        for column, expected in filters.items():
            if not expected:
                continue
            filtered = filtered[
                filtered[column].apply(lambda value: self._safe_text(value) == expected)
            ]
        return filtered

    def _serialize_row(self, row: pd.Series) -> dict[str, Any]:
        return self._serialize_row_record(ComparisonRowRecord.from_mapping(dict(row)))

    def _serialize_row_record(self, record: ComparisonRowRecord) -> dict[str, Any]:
        missing_critical_context = list(record.missing_critical_context)
        return {
            "row_id": record.row_id,
            "collection_id": record.collection_id,
            "source_document_id": record.source_document_id,
            "display": {
                "material_system_normalized": record.material_system_normalized,
                "process_normalized": record.process_normalized,
                "variant_id": record.variant_id,
                "variant_label": record.variant_label,
                "variable_axis": record.variable_axis,
                "variable_value": record.variable_value,
                "property_normalized": record.property_normalized,
                "result_type": record.result_type,
                "result_summary": record.result_summary,
                "value": record.value,
                "unit": record.unit,
                "test_condition_normalized": record.test_condition_normalized,
                "baseline_reference": record.baseline_reference,
                "baseline_normalized": record.baseline_normalized,
            },
            "evidence_bundle": {
                "result_source_type": record.result_source_type,
                "supporting_evidence_ids": list(record.supporting_evidence_ids),
                "supporting_anchor_ids": list(record.supporting_anchor_ids),
                "characterization_observation_ids": list(
                    record.characterization_observation_ids
                ),
                "structure_feature_ids": list(record.structure_feature_ids),
            },
            "assessment": {
                "comparability_status": record.comparability_status,
                "comparability_warnings": list(record.comparability_warnings),
                "comparability_basis": list(record.comparability_basis),
                "requires_expert_review": record.requires_expert_review,
                "assessment_epistemic_status": record.assessment_epistemic_status,
            },
            "uncertainty": {
                "missing_critical_context": missing_critical_context,
                "unresolved_fields": missing_critical_context,
                "unresolved_baseline_link": "baseline_reference" in missing_critical_context,
                "unresolved_condition_link": "test_condition" in missing_critical_context,
            },
        }

    def _serialize_comparable_result(self, record: ComparableResult) -> dict[str, Any]:
        return record.to_record()

    def _serialize_collection_comparable_result(
        self,
        record: CollectionComparableResult,
    ) -> dict[str, Any]:
        return record.to_record()

    def _safe_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None


__all__ = [
    "ComparisonRowNotFoundError",
    "ComparisonRowsNotReadyError",
    "ComparisonService",
]
