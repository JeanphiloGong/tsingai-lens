from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd

from application.core.comparison_assembly import (
    COLLECTION_COMPARABLE_RESULT_COLUMNS,
    ComparableResultAssembler,
    ComparisonInputFrames,
    ComparisonSemanticTables,
)
from application.core.comparison_projection import (
    ComparisonProjectionTables,
    ComparisonRowProjector,
)
from application.core.semantic_build.core_semantic_version import (
    CURRENT_CORE_SEMANTIC_VERSION,
    core_semantic_rebuild_required,
    write_core_semantic_manifest,
)
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
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
_CHARACTERIZATION_OBSERVATIONS_FILE = "characterization_observations.parquet"
_STRUCTURE_FEATURES_FILE = "structure_features.parquet"
_SAMPLE_VARIANT_JSON_COLUMNS = (
    "host_material_system",
    "variable_value",
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
_CHARACTERIZATION_OBSERVATION_JSON_COLUMNS = (
    "condition_context",
    "evidence_anchor_ids",
)
_STRUCTURE_FEATURE_JSON_COLUMNS = ("source_observation_ids",)
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
_CORPUS_COMPARABLE_RESULTS_CACHE_DIR = "_core_cache"
_CORPUS_COMPARABLE_RESULTS_CACHE_FILE = "corpus_comparable_results_cache.parquet"
_CORPUS_COMPARABLE_RESULTS_CACHE_META_FILE = "corpus_comparable_results_cache_meta.json"
_CORPUS_COMPARABLE_RESULTS_CACHE_SCHEMA_VERSION = 1
_CORPUS_COMPARABLE_RESULTS_CACHE_JSON_COLUMNS = (
    "binding",
    "normalized_context",
    "axis",
    "value",
    "evidence",
    "observed_collection_ids",
    "collection_overlays",
)
_PROCESS_STATE_KEYS = (
    "laser_power_w",
    "scan_speed_mm_s",
    "layer_thickness_um",
    "hatch_spacing_um",
    "spot_size_um",
    "energy_density_j_mm3",
    "energy_density_origin",
    "scan_strategy",
    "build_orientation",
    "preheat_temperature_c",
    "shielding_gas",
    "oxygen_level_ppm",
    "powder_size_distribution_um",
    "post_treatment_summary",
)
_SERIES_AXIS_UNITS = {
    "test_temperature_c": "C",
    "strain_rate_s-1": "s^-1",
    "hold_time": "s",
    "frequency_hz": "Hz",
    "test_condition": None,
}
_TEST_SERIES_AXIS_CANDIDATES = (
    "test_temperature_c",
    "strain_rate_s-1",
    "hold_time",
    "frequency_hz",
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


class ComparableResultNotFoundError(FileNotFoundError):
    """Raised when one corpus comparable result cannot be found."""

    def __init__(
        self,
        comparable_result_id: str,
        *,
        collection_id: str | None = None,
    ) -> None:
        self.comparable_result_id = comparable_result_id
        self.collection_id = collection_id
        scope = f"{collection_id}/" if collection_id else ""
        super().__init__(f"comparable result not found: {scope}{comparable_result_id}")


class ResultNotFoundError(FileNotFoundError):
    """Raised when one collection-facing result projection cannot be found."""

    def __init__(self, collection_id: str, result_id: str) -> None:
        self.collection_id = collection_id
        self.result_id = result_id
        super().__init__(f"result not found: {collection_id}/{result_id}")


class ComparisonService:
    """Generate and serve collection-scoped comparison artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        paper_facts_service: PaperFactsService | None = None,
        document_profile_service: DocumentProfileService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
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

    def list_corpus_comparable_results(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
        source_document_id: str | None = None,
        collection_id: str | None = None,
    ) -> dict[str, Any]:
        items = self._collect_corpus_comparable_result_items(
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
            source_document_id=source_document_id,
            collection_id=collection_id,
        )
        paged_items = items[offset : offset + limit]
        return {
            "collection_id": self._safe_text(collection_id),
            "total": len(items),
            "count": len(paged_items),
            "items": paged_items,
        }

    def get_corpus_comparable_result(
        self,
        comparable_result_id: str,
        *,
        collection_id: str | None = None,
    ) -> dict[str, Any]:
        comparable_result_key = self._safe_text(comparable_result_id) or ""
        items = self._collect_corpus_comparable_result_items(
            collection_id=collection_id,
            comparable_result_id=comparable_result_key,
        )
        if not items:
            raise ComparableResultNotFoundError(
                comparable_result_key,
                collection_id=self._safe_text(collection_id),
            )
        return items[0]

    def list_collection_results(
        self,
        collection_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
        comparability_status: str | None = None,
        source_document_id: str | None = None,
    ) -> dict[str, Any]:
        items = self._collect_collection_result_items(
            collection_id,
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
            comparability_status=comparability_status,
            source_document_id=source_document_id,
        )
        paged_items = items[offset : offset + limit]
        return {
            "collection_id": collection_id,
            "total": len(items),
            "count": len(paged_items),
            "items": paged_items,
        }

    def get_collection_result(
        self,
        collection_id: str,
        result_id: str,
    ) -> dict[str, Any]:
        result_key = self._safe_text(result_id) or ""
        all_records = self._collect_collection_result_records(collection_id)
        matching_records = [
            item
            for item in all_records
            if self._safe_text(item[1].comparable_result_id) == result_key
        ]
        if not matching_records:
            raise ResultNotFoundError(collection_id, result_key)
        scoped_record, comparable_record, document_payload = matching_records[0]
        output_dir = self._resolve_output_dir(collection_id)
        projection_context = self._load_optional_projection_context(output_dir)
        return self._serialize_collection_result_detail(
            collection_id,
            comparable_record,
            scoped_record,
            document_payload=document_payload,
            projection_context=projection_context,
            sibling_records=all_records,
        )

    def read_comparison_rows(self, collection_id: str) -> pd.DataFrame:
        return self.read_comparison_projection(
            collection_id,
            materialize_row_cache=True,
        ).comparison_rows

    def read_comparison_projection(
        self,
        collection_id: str,
        *,
        materialize_row_cache: bool = False,
    ) -> ComparisonProjectionTables:
        output_dir = self._resolve_output_dir(collection_id)
        semantic_tables = self._read_semantic_comparison_artifacts(
            collection_id,
            output_dir,
        )
        rows = self.comparison_row_projector.project_rows_from_semantic_artifacts(
            collection_id=collection_id,
            comparable_results=semantic_tables.comparable_results,
            scoped_results=semantic_tables.collection_comparable_results,
        )
        if materialize_row_cache:
            self._materialize_row_cache_if_missing(collection_id, output_dir, rows)
        return ComparisonProjectionTables(
            comparable_results=semantic_tables.comparable_results,
            collection_comparable_results=semantic_tables.collection_comparable_results,
            comparison_rows=rows,
        )

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
        include_grouped_projections: bool = False,
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
            payload = {
                "collection_id": collection_id,
                "source_document_id": document_id,
                "total": 0,
                "count": 0,
                "items": [],
            }
            if include_grouped_projections:
                payload["variant_dossiers"] = []
            return payload

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
        payload = {
            "collection_id": collection_id,
            "source_document_id": document_id,
            "total": len(items),
            "count": len(items),
            "items": items,
        }
        if include_grouped_projections:
            projection_context = self._load_optional_projection_context(output_dir)
            payload["variant_dossiers"] = self._build_variant_dossiers(
                collection_id=collection_id,
                comparable_records=comparable_records,
                scoped_records_by_result_id=scoped_records_by_result_id,
                projection_context=projection_context,
            )
        return payload

    def _collect_collection_result_items(
        self,
        collection_id: str,
        *,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
        comparability_status: str | None = None,
        source_document_id: str | None = None,
        result_id: str | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for scoped_record, comparable_record, document_payload in self._collect_collection_result_records(
            collection_id,
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
            comparability_status=comparability_status,
            source_document_id=source_document_id,
            result_id=result_id,
        ):
            items.append(
                self._serialize_collection_result_list_item(
                    comparable_record,
                    scoped_record,
                    document_payload=document_payload,
                )
            )
        return items

    def _collect_collection_result_records(
        self,
        collection_id: str,
        *,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
        comparability_status: str | None = None,
        source_document_id: str | None = None,
        result_id: str | None = None,
    ) -> list[tuple[CollectionComparableResult, ComparableResult, dict[str, Any] | None]]:
        output_dir = self._resolve_output_dir(collection_id)
        semantic_tables = self._read_semantic_comparison_artifacts(collection_id, output_dir)
        comparable_lookup = {
            record.comparable_result_id: record
            for record in (
                ComparableResult.from_mapping(dict(row))
                for _, row in semantic_tables.comparable_results.iterrows()
            )
            if self._safe_text(record.comparable_result_id)
        }
        document_lookup = self._load_document_profile_lookup(collection_id)
        records: list[tuple[CollectionComparableResult, ComparableResult, dict[str, Any] | None]] = []
        for _, row in semantic_tables.collection_comparable_results.iterrows():
            scoped_record = CollectionComparableResult.from_mapping(dict(row))
            if self._safe_text(scoped_record.collection_id) != collection_id or not scoped_record.included:
                continue
            comparable_record = comparable_lookup.get(scoped_record.comparable_result_id)
            if comparable_record is None:
                continue
            if not self._collection_result_matches_filters(
                comparable_record,
                scoped_record,
                material_system_normalized=material_system_normalized,
                property_normalized=property_normalized,
                test_condition_normalized=test_condition_normalized,
                baseline_normalized=baseline_normalized,
                comparability_status=comparability_status,
                source_document_id=source_document_id,
                result_id=result_id,
            ):
                continue
            records.append(
                (
                    scoped_record,
                    comparable_record,
                    document_lookup.get(comparable_record.source_document_id),
                )
            )
        records.sort(
            key=lambda item: (
                1_000_000_000 if item[0].sort_order is None else item[0].sort_order,
                item[1].comparable_result_id,
            )
        )
        return records

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
        self._invalidate_corpus_comparable_results_cache()
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
        self._invalidate_corpus_comparable_results_cache()
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

    def _collect_corpus_comparable_result_items(
        self,
        *,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
        source_document_id: str | None = None,
        collection_id: str | None = None,
        comparable_result_id: str | None = None,
    ) -> list[dict[str, Any]]:
        scoped_collection_id = self._safe_text(collection_id)
        if scoped_collection_id:
            items = self._scan_corpus_comparable_result_items(collection_id=scoped_collection_id)
        else:
            items = self._load_or_rebuild_corpus_comparable_results_cache()
        return self._filter_corpus_comparable_result_items(
            items,
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
            source_document_id=source_document_id,
            comparable_result_id=comparable_result_id,
        )

    def _scan_corpus_comparable_result_items(
        self,
        *,
        collection_id: str | None = None,
    ) -> list[dict[str, Any]]:
        collection_ids = self._list_corpus_collection_ids(collection_id)
        base_records_by_result_id: dict[str, ComparableResult] = {}
        observed_collection_ids_by_result_id: dict[str, set[str]] = {}
        scoped_records_by_result_id: dict[str, dict[str, CollectionComparableResult]] = {}

        for current_collection_id in collection_ids:
            try:
                semantic_tables = self._read_semantic_comparison_artifacts(
                    current_collection_id,
                    self._resolve_output_dir(current_collection_id),
                )
            except ComparisonRowsNotReadyError:
                if collection_id:
                    raise
                continue
            comparable_records = [
                ComparableResult.from_mapping(dict(row))
                for _, row in semantic_tables.comparable_results.iterrows()
            ]
            matching_result_ids = {
                record.comparable_result_id
                for record in comparable_records
                if record.comparable_result_id
            }
            if not comparable_records:
                continue
            for record in comparable_records:
                if not record.comparable_result_id:
                    continue
                base_records_by_result_id.setdefault(record.comparable_result_id, record)
                observed_collection_ids_by_result_id.setdefault(
                    record.comparable_result_id,
                    set(),
                ).add(current_collection_id)
            for _, row in semantic_tables.collection_comparable_results.iterrows():
                scoped_record = CollectionComparableResult.from_mapping(dict(row))
                if scoped_record.collection_id != current_collection_id:
                    continue
                if scoped_record.comparable_result_id not in matching_result_ids:
                    continue
                scoped_records_by_result_id.setdefault(
                    scoped_record.comparable_result_id,
                    {},
                )[current_collection_id] = scoped_record

        items: list[dict[str, Any]] = []
        for result_id in sorted(base_records_by_result_id):
            record = base_records_by_result_id[result_id]
            observed_collection_ids = sorted(
                observed_collection_ids_by_result_id.get(result_id, set())
            )
            collection_overlays = sorted(
                scoped_records_by_result_id.get(result_id, {}).values(),
                key=lambda scoped_record: (
                    scoped_record.collection_id,
                    1_000_000_000
                    if scoped_record.sort_order is None
                    else scoped_record.sort_order,
                    scoped_record.comparable_result_id,
                ),
            )
            items.append(
                self._serialize_corpus_comparable_result(
                    record,
                    observed_collection_ids=observed_collection_ids,
                    collection_overlays=collection_overlays,
                )
            )
        return items

    def _load_or_rebuild_corpus_comparable_results_cache(self) -> list[dict[str, Any]]:
        cache_table_path, cache_meta_path = self._resolve_corpus_comparable_results_cache_paths()
        current_snapshot = self._build_corpus_comparable_results_cache_snapshot()
        if cache_table_path.is_file() and cache_meta_path.is_file():
            try:
                cache_meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
                if self._corpus_comparable_results_cache_is_current(
                    cache_meta,
                    current_snapshot,
                ):
                    cached_frame = restore_frame_from_storage(
                        pd.read_parquet(cache_table_path),
                        _CORPUS_COMPARABLE_RESULTS_CACHE_JSON_COLUMNS,
                    )
                    return [
                        dict(row)
                        for _, row in cached_frame.iterrows()
                    ]
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Corpus comparable-result cache read failed; rebuilding cache path=%s",
                    cache_table_path,
                )
        items = self._scan_corpus_comparable_result_items()
        self._write_corpus_comparable_results_cache(
            items=items,
            collection_snapshot=current_snapshot,
        )
        return items

    def _filter_corpus_comparable_result_items(
        self,
        items: list[dict[str, Any]],
        *,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
        source_document_id: str | None = None,
        comparable_result_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filtered_items: list[dict[str, Any]] = []
        expected_material_system = self._safe_text(material_system_normalized)
        expected_property = self._safe_text(property_normalized)
        expected_test_condition = self._safe_text(test_condition_normalized)
        expected_baseline = self._safe_text(baseline_normalized)
        expected_source_document_id = self._safe_text(source_document_id)
        expected_comparable_result_id = self._safe_text(comparable_result_id)

        for item in items:
            normalized_context = item.get("normalized_context") or {}
            value = item.get("value") or {}
            if expected_material_system and self._safe_text(
                normalized_context.get("material_system_normalized")
            ) != expected_material_system:
                continue
            if expected_property and self._safe_text(
                value.get("property_normalized")
            ) != expected_property:
                continue
            if expected_test_condition and self._safe_text(
                normalized_context.get("test_condition_normalized")
            ) != expected_test_condition:
                continue
            if expected_baseline and self._safe_text(
                normalized_context.get("baseline_normalized")
            ) != expected_baseline:
                continue
            if expected_source_document_id and self._safe_text(
                item.get("source_document_id")
            ) != expected_source_document_id:
                continue
            if expected_comparable_result_id and self._safe_text(
                item.get("comparable_result_id")
            ) != expected_comparable_result_id:
                continue
            filtered_items.append(item)
        return filtered_items

    def _collection_result_matches_filters(
        self,
        comparable_record: ComparableResult,
        scoped_record: CollectionComparableResult,
        *,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
        comparability_status: str | None = None,
        source_document_id: str | None = None,
        result_id: str | None = None,
    ) -> bool:
        expected_material_system = self._safe_text(material_system_normalized)
        expected_property = self._safe_text(property_normalized)
        expected_test_condition = self._safe_text(test_condition_normalized)
        expected_baseline = self._safe_text(baseline_normalized)
        expected_comparability = self._safe_text(comparability_status)
        expected_source_document_id = self._safe_text(source_document_id)
        expected_result_id = self._safe_text(result_id)

        if expected_material_system and (
            self._safe_text(comparable_record.normalized_context.material_system_normalized)
            != expected_material_system
        ):
            return False
        if expected_property and (
            self._safe_text(comparable_record.value.property_normalized) != expected_property
        ):
            return False
        if expected_test_condition and (
            self._safe_text(comparable_record.normalized_context.test_condition_normalized)
            != expected_test_condition
        ):
            return False
        if expected_baseline and (
            self._safe_text(comparable_record.normalized_context.baseline_normalized)
            != expected_baseline
        ):
            return False
        if expected_comparability and (
            self._safe_text(scoped_record.assessment.comparability_status)
            != expected_comparability
        ):
            return False
        if expected_source_document_id and (
            self._safe_text(comparable_record.source_document_id) != expected_source_document_id
        ):
            return False
        if expected_result_id and (
            self._safe_text(comparable_record.comparable_result_id) != expected_result_id
        ):
            return False
        return True

    def _list_corpus_collection_ids(self, collection_id: str | None) -> list[str]:
        if collection_id:
            self.collection_service.get_collection(collection_id)
            return [collection_id]
        collection_ids: list[str] = []
        for record in self.collection_service.list_collections():
            current_collection_id = self._safe_text(record.get("collection_id"))
            if current_collection_id:
                collection_ids.append(current_collection_id)
        return collection_ids

    def _resolve_corpus_comparable_results_cache_paths(self) -> tuple[Path, Path]:
        cache_dir = self.collection_service.root_dir / _CORPUS_COMPARABLE_RESULTS_CACHE_DIR
        return (
            cache_dir / _CORPUS_COMPARABLE_RESULTS_CACHE_FILE,
            cache_dir / _CORPUS_COMPARABLE_RESULTS_CACHE_META_FILE,
        )

    def _build_corpus_comparable_results_cache_snapshot(self) -> dict[str, dict[str, int | None]]:
        snapshot: dict[str, dict[str, int | None]] = {}
        for collection_id in self._list_corpus_collection_ids(None):
            output_dir = self.collection_service.get_paths(collection_id).output_dir.resolve()
            documents_path = output_dir / "documents.parquet"
            comparable_results_path = output_dir / _COMPARABLE_RESULTS_FILE
            scoped_results_path = output_dir / _COLLECTION_COMPARABLE_RESULTS_FILE
            if not (
                documents_path.is_file()
                or comparable_results_path.is_file()
                or scoped_results_path.is_file()
            ):
                continue
            snapshot[collection_id] = {
                "documents_mtime_ns": self._path_mtime_ns(documents_path),
                "comparable_results_mtime_ns": self._path_mtime_ns(comparable_results_path),
                "collection_comparable_results_mtime_ns": self._path_mtime_ns(
                    scoped_results_path
                ),
            }
        return snapshot

    def _corpus_comparable_results_cache_is_current(
        self,
        cache_meta: dict[str, Any],
        current_snapshot: dict[str, dict[str, int | None]],
    ) -> bool:
        if cache_meta.get("schema_version") != _CORPUS_COMPARABLE_RESULTS_CACHE_SCHEMA_VERSION:
            return False
        if cache_meta.get("core_semantic_version") != CURRENT_CORE_SEMANTIC_VERSION:
            return False
        return cache_meta.get("collection_snapshot") == current_snapshot

    def _write_corpus_comparable_results_cache(
        self,
        *,
        items: list[dict[str, Any]],
        collection_snapshot: dict[str, dict[str, int | None]],
    ) -> None:
        cache_table_path, cache_meta_path = self._resolve_corpus_comparable_results_cache_paths()
        cache_table_path.parent.mkdir(parents=True, exist_ok=True)
        prepare_frame_for_storage(
            pd.DataFrame(items),
            _CORPUS_COMPARABLE_RESULTS_CACHE_JSON_COLUMNS,
        ).to_parquet(cache_table_path, index=False)
        cache_meta_path.write_text(
            json.dumps(
                {
                    "schema_version": _CORPUS_COMPARABLE_RESULTS_CACHE_SCHEMA_VERSION,
                    "core_semantic_version": CURRENT_CORE_SEMANTIC_VERSION,
                    "collection_snapshot": collection_snapshot,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _invalidate_corpus_comparable_results_cache(self) -> None:
        cache_table_path, cache_meta_path = self._resolve_corpus_comparable_results_cache_paths()
        for path in (cache_table_path, cache_meta_path):
            if path.is_file():
                path.unlink()

    def _path_mtime_ns(self, path: Path) -> int | None:
        if not path.is_file():
            return None
        return path.stat().st_mtime_ns

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
            "result_id": record.comparable_result_id,
            "collection_id": record.collection_id,
            "source_document_id": record.source_document_id,
            "supporting_evidence_ids": list(record.supporting_evidence_ids),
            "material_system_normalized": record.material_system_normalized,
            "process_normalized": record.process_normalized,
            "property_normalized": record.property_normalized,
            "baseline_normalized": record.baseline_normalized,
            "test_condition_normalized": record.test_condition_normalized,
            "comparability_status": record.comparability_status,
            "comparability_warnings": list(record.comparability_warnings),
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

    def _load_optional_projection_context(self, output_dir: Path) -> dict[str, Any]:
        sample_variants = self._read_optional_semantic_frame(
            output_dir / _SAMPLE_VARIANTS_FILE,
            _SAMPLE_VARIANT_JSON_COLUMNS,
        )
        measurement_results = self._read_optional_semantic_frame(
            output_dir / _MEASUREMENT_RESULTS_FILE,
            _MEASUREMENT_RESULT_JSON_COLUMNS,
        )
        test_conditions = self._read_optional_semantic_frame(
            output_dir / _TEST_CONDITIONS_FILE,
            _TEST_CONDITION_JSON_COLUMNS,
        )
        baseline_references = self._read_optional_semantic_frame(
            output_dir / _BASELINE_REFERENCES_FILE,
            _BASELINE_REFERENCE_JSON_COLUMNS,
        )
        characterization_observations = self._read_optional_semantic_frame(
            output_dir / _CHARACTERIZATION_OBSERVATIONS_FILE,
            _CHARACTERIZATION_OBSERVATION_JSON_COLUMNS,
        )
        structure_features = self._read_optional_semantic_frame(
            output_dir / _STRUCTURE_FEATURES_FILE,
            _STRUCTURE_FEATURE_JSON_COLUMNS,
        )
        return {
            "sample_variants_by_id": self._index_frame_by_text(
                sample_variants,
                "variant_id",
            ),
            "measurement_results_by_id": self._index_frame_by_text(
                measurement_results,
                "result_id",
            ),
            "test_conditions_by_id": self._index_frame_by_text(
                test_conditions,
                "test_condition_id",
            ),
            "baseline_references_by_id": self._index_frame_by_text(
                baseline_references,
                "baseline_id",
            ),
            "characterization_observations_by_id": self._index_frame_by_text(
                characterization_observations,
                "observation_id",
            ),
            "structure_features_by_id": self._index_frame_by_text(
                structure_features,
                "feature_id",
            ),
        }

    def _read_optional_semantic_frame(
        self,
        path: Path,
        json_columns: tuple[str, ...],
    ) -> pd.DataFrame:
        if not path.is_file():
            return pd.DataFrame()
        return restore_frame_from_storage(pd.read_parquet(path), json_columns)

    def _index_frame_by_text(
        self,
        frame: pd.DataFrame,
        key: str,
    ) -> dict[str, dict[str, Any]]:
        if frame.empty or key not in frame.columns:
            return {}
        lookup: dict[str, dict[str, Any]] = {}
        for _, row in frame.iterrows():
            row_payload = dict(row)
            record_key = self._safe_text(row_payload.get(key))
            if record_key:
                lookup[record_key] = row_payload
        return lookup

    def _build_variant_dossiers(
        self,
        *,
        collection_id: str,
        comparable_records: list[ComparableResult],
        scoped_records_by_result_id: dict[str, list[CollectionComparableResult]],
        projection_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        records_by_variant: dict[str, list[ComparableResult]] = {}
        for record in comparable_records:
            variant_key = (
                self._safe_text(record.binding.variant_id)
                or f"unresolved:{record.source_document_id}"
            )
            records_by_variant.setdefault(variant_key, []).append(record)

        dossiers: list[dict[str, Any]] = []
        for variant_key in sorted(records_by_variant):
            variant_records = records_by_variant[variant_key]
            representative = variant_records[0]
            dossier = self._build_variant_dossier_summary(
                representative,
                projection_context=projection_context,
            )
            dossier["series"] = self._build_result_series(
                collection_id=collection_id,
                comparable_records=variant_records,
                scoped_records_by_result_id=scoped_records_by_result_id,
                projection_context=projection_context,
            )
            dossiers.append(dossier)
        return dossiers

    def _build_result_series(
        self,
        *,
        collection_id: str,
        comparable_records: list[ComparableResult],
        scoped_records_by_result_id: dict[str, list[CollectionComparableResult]],
        projection_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[ComparableResult]] = {}
        for record in comparable_records:
            test_condition = self._build_test_condition_detail(
                record,
                projection_context=projection_context,
            )
            key = (
                self._property_family(record),
                self._test_family(record, test_condition),
            )
            grouped.setdefault(key, []).append(record)

        series_items: list[dict[str, Any]] = []
        for property_family, test_family in sorted(grouped):
            sibling_records = sorted(
                grouped[(property_family, test_family)],
                key=lambda item: item.comparable_result_id,
            )
            chain_payloads = [
                self._build_result_chain(
                    comparable_record=record,
                    scoped_records=scoped_records_by_result_id.get(
                        record.comparable_result_id,
                        [],
                    ),
                    projection_context=projection_context,
                )
                for record in sibling_records
            ]
            axis_name = self._select_series_axis(chain_payloads)
            chain_payloads.sort(
                key=lambda chain: (
                    self._axis_sort_key((chain.get("test_condition") or {}).get(axis_name)),
                    chain["result_id"],
                )
            )
            series_items.append(
                {
                    "series_key": f"{property_family}:{axis_name}",
                    "property_family": property_family,
                    "test_family": test_family,
                    "varying_axis": {
                        "axis_name": axis_name,
                        "axis_unit": _SERIES_AXIS_UNITS.get(axis_name),
                    },
                    "chains": chain_payloads,
                }
            )
        return series_items

    def _build_result_chain(
        self,
        *,
        comparable_record: ComparableResult,
        scoped_records: list[CollectionComparableResult],
        projection_context: dict[str, Any],
    ) -> dict[str, Any]:
        scoped_record = self._select_scoped_record(scoped_records)
        return {
            "result_id": comparable_record.comparable_result_id,
            "source_result_id": comparable_record.source_result_id,
            "measurement": self._build_measurement_payload(comparable_record),
            "test_condition": self._build_test_condition_detail(
                comparable_record,
                projection_context=projection_context,
            ),
            "baseline": self._build_baseline_detail(
                comparable_record,
                projection_context=projection_context,
                include_scope=False,
            ),
            "assessment": self._build_chain_assessment(scoped_record),
            "value_provenance": self._build_value_provenance(
                comparable_record,
                projection_context=projection_context,
            ),
            "evidence": self._build_chain_evidence(comparable_record),
        }

    def _select_scoped_record(
        self,
        scoped_records: list[CollectionComparableResult],
    ) -> CollectionComparableResult | None:
        if not scoped_records:
            return None
        return sorted(
            scoped_records,
            key=lambda record: (
                1_000_000_000 if record.sort_order is None else record.sort_order,
                record.comparable_result_id,
            ),
        )[0]

    def _build_variant_dossier_summary(
        self,
        comparable_record: ComparableResult,
        *,
        projection_context: dict[str, Any],
    ) -> dict[str, Any]:
        variant = self._lookup_variant(comparable_record, projection_context)
        variant_id = self._safe_text(comparable_record.binding.variant_id)
        host_material_system = self._safe_mapping(
            variant.get("host_material_system") if variant else None
        )
        composition = self._safe_text((variant or {}).get("composition")) or self._safe_text(
            host_material_system.get("composition")
        )
        material_label = (
            self._safe_text(comparable_record.normalized_context.material_system_normalized)
            or self._safe_text(host_material_system.get("family"))
            or composition
            or "unspecified material system"
        )
        return {
            "variant_id": variant_id,
            "variant_label": comparable_record.variant_label
            or self._safe_text((variant or {}).get("variant_label")),
            "material": {
                "label": material_label,
                "composition": composition,
                "host_material_system": host_material_system or None,
            },
            "shared_process_state": self._build_shared_process_state(variant),
            "shared_missingness": self._build_shared_missingness(variant),
        }

    def _build_shared_process_state(
        self,
        variant: dict[str, Any] | None,
    ) -> dict[str, Any]:
        process_context = self._safe_mapping((variant or {}).get("process_context"))
        process_state: dict[str, Any] = {}
        for key in _PROCESS_STATE_KEYS:
            value = process_context.get(key)
            if value not in (None, "", [], {}):
                process_state[key] = value
        return process_state

    def _build_shared_missingness(
        self,
        variant: dict[str, Any] | None,
    ) -> list[str]:
        process_context = self._safe_mapping((variant or {}).get("process_context"))
        missing: list[str] = []
        if variant is None:
            missing.append("variant_fact_not_available")
        if not process_context:
            missing.append("process_context_not_reported")
        return missing

    def _build_measurement_payload(
        self,
        comparable_record: ComparableResult,
    ) -> dict[str, Any]:
        return {
            "property": comparable_record.value.property_normalized,
            "value": comparable_record.value.numeric_value,
            "unit": comparable_record.value.unit,
            "result_type": comparable_record.value.result_type,
            "summary": comparable_record.value.summary,
            "statistic_type": comparable_record.value.statistic_type,
            "uncertainty": comparable_record.value.uncertainty,
        }

    def _build_test_condition_detail(
        self,
        comparable_record: ComparableResult,
        *,
        projection_context: dict[str, Any],
    ) -> dict[str, Any]:
        condition = self._lookup_test_condition(comparable_record, projection_context)
        payload = self._safe_mapping((condition or {}).get("condition_payload"))
        method = self._safe_text(payload.get("test_method")) or self._safe_text(
            payload.get("method")
        )
        methods = self._safe_list(payload.get("methods"))
        if method is None and methods:
            method = self._safe_text(methods[0])
        temperature = self._optional_float(payload.get("test_temperature_c"))
        if temperature is None:
            temperatures = self._safe_list(payload.get("temperatures_c"))
            if temperatures:
                temperature = self._optional_float(temperatures[0])
        return {
            "test_method": method
            or self._safe_text(comparable_record.normalized_context.test_condition_normalized),
            "test_temperature_c": temperature,
            "strain_rate_s-1": self._optional_float(
                payload.get("strain_rate_s-1")
                or payload.get("strain_rate_s_1")
                or payload.get("strain_rate")
                or payload.get("rate")
            )
            or self._safe_text(payload.get("strain_rate_text")),
            "loading_direction": self._safe_text(
                payload.get("loading_direction") or payload.get("direction")
            ),
            "sample_orientation": self._safe_text(payload.get("sample_orientation")),
            "environment": self._safe_text(payload.get("environment"))
            or self._safe_text(payload.get("atmosphere")),
            "frequency_hz": self._optional_float(
                payload.get("frequency_hz") or payload.get("frequency")
            ),
            "specimen_geometry": self._safe_text(payload.get("specimen_geometry")),
            "surface_state": self._safe_text(payload.get("surface_state")),
        }

    def _build_baseline_detail(
        self,
        comparable_record: ComparableResult,
        *,
        projection_context: dict[str, Any],
        include_scope: bool,
    ) -> dict[str, Any]:
        baseline = self._lookup_baseline(comparable_record, projection_context)
        label = self._safe_text((baseline or {}).get("baseline_label"))
        reference = comparable_record.baseline_reference or label
        payload = {
            "label": label or reference,
            "reference": reference,
            "baseline_type": self._safe_text((baseline or {}).get("baseline_type")),
            "resolved": bool(reference or baseline),
        }
        if include_scope:
            payload["baseline_scope"] = self._safe_text((baseline or {}).get("baseline_scope"))
        return payload

    def _build_chain_assessment(
        self,
        scoped_record: CollectionComparableResult | None,
    ) -> dict[str, Any]:
        if scoped_record is None:
            return {
                "comparability_status": "insufficient",
                "warnings": ["Collection assessment is missing for this result."],
                "basis": [],
                "missing_context": ["collection_assessment"],
                "requires_expert_review": True,
                "assessment_epistemic_status": "unresolved",
            }
        assessment = scoped_record.assessment
        return {
            "comparability_status": assessment.comparability_status,
            "warnings": list(assessment.comparability_warnings),
            "basis": list(assessment.comparability_basis),
            "missing_context": list(assessment.missing_critical_context),
            "requires_expert_review": assessment.requires_expert_review,
            "assessment_epistemic_status": assessment.assessment_epistemic_status,
        }

    def _build_value_provenance(
        self,
        comparable_record: ComparableResult,
        *,
        projection_context: dict[str, Any],
    ) -> dict[str, Any]:
        measurement_result = self._lookup_measurement_result(
            comparable_record,
            projection_context,
        )
        value_payload = self._safe_mapping((measurement_result or {}).get("value_payload"))
        value_origin = self._safe_text(value_payload.get("value_origin"))
        if value_origin is None:
            value_origin = "derived" if value_payload.get("derivation_formula") else "reported"
        source_value_text = self._safe_text(value_payload.get("source_value_text"))
        if source_value_text is None:
            source_value_text = self._first_value_text(
                value_payload,
                ("value", "min", "max", "retention_percent", "statement"),
            )
        return {
            "value_origin": value_origin,
            "source_value_text": source_value_text,
            "source_unit_text": self._safe_text(value_payload.get("source_unit_text"))
            or comparable_record.value.unit,
            "derivation_formula": self._safe_text(value_payload.get("derivation_formula")),
            "derivation_inputs": self._safe_mapping_or_none(
                value_payload.get("derivation_inputs")
            ),
        }

    def _build_chain_evidence(self, comparable_record: ComparableResult) -> dict[str, Any]:
        return {
            "evidence_ids": list(comparable_record.evidence.evidence_ids),
            "direct_anchor_ids": list(comparable_record.evidence.direct_anchor_ids),
            "contextual_anchor_ids": list(comparable_record.evidence.contextual_anchor_ids),
            "structure_feature_ids": list(comparable_record.evidence.structure_feature_ids),
            "characterization_observation_ids": list(
                comparable_record.evidence.characterization_observation_ids
            ),
            "traceability_status": comparable_record.evidence.traceability_status,
        }

    def _build_structure_support(
        self,
        comparable_record: ComparableResult,
        *,
        projection_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        supports: list[dict[str, Any]] = []
        structure_lookup = projection_context.get("structure_features_by_id", {})
        observation_lookup = projection_context.get("characterization_observations_by_id", {})
        for feature_id in comparable_record.evidence.structure_feature_ids:
            feature = structure_lookup.get(feature_id, {})
            supports.append(
                {
                    "support_id": feature_id,
                    "support_type": "structure_feature",
                    "summary": self._structure_feature_summary(feature, feature_id),
                    "condition": {
                        "characterization_temperature_c": self._support_temperature(
                            feature,
                            observation_lookup,
                        )
                    },
                }
            )
        for observation_id in comparable_record.evidence.characterization_observation_ids:
            observation = observation_lookup.get(observation_id, {})
            supports.append(
                {
                    "support_id": observation_id,
                    "support_type": "characterization_observation",
                    "summary": self._characterization_observation_summary(
                        observation,
                        observation_id,
                    ),
                    "condition": {
                        "characterization_temperature_c": self._observation_temperature(
                            observation,
                        )
                    },
                }
            )
        return supports

    def _build_series_navigation(
        self,
        *,
        current_record: ComparableResult,
        sibling_records: list[
            tuple[CollectionComparableResult, ComparableResult, dict[str, Any] | None]
        ],
        projection_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        current_variant = self._safe_text(current_record.binding.variant_id)
        current_property = self._property_family(current_record)
        current_test_condition = self._build_test_condition_detail(
            current_record,
            projection_context=projection_context,
        )
        current_test_family = self._test_family(current_record, current_test_condition)
        siblings: list[ComparableResult] = []
        for _scoped, record, _document in sibling_records:
            if self._safe_text(record.binding.variant_id) != current_variant:
                continue
            if self._property_family(record) != current_property:
                continue
            condition = self._build_test_condition_detail(
                record,
                projection_context=projection_context,
            )
            if self._test_family(record, condition) != current_test_family:
                continue
            siblings.append(record)
        if len(siblings) < 2:
            return None

        chain_payloads = [
            {
                "result_id": record.comparable_result_id,
                "test_condition": self._build_test_condition_detail(
                    record,
                    projection_context=projection_context,
                ),
                "measurement": self._build_measurement_payload(record),
            }
            for record in sorted(siblings, key=lambda item: item.comparable_result_id)
        ]
        axis_name = self._select_series_axis(chain_payloads)
        if axis_name == "test_condition":
            return None
        chain_payloads.sort(
            key=lambda chain: (
                self._axis_sort_key((chain["test_condition"] or {}).get(axis_name)),
                chain["result_id"],
            )
        )
        return {
            "series_key": f"{current_property}:{axis_name}",
            "varying_axis": {
                "axis_name": axis_name,
                "axis_unit": _SERIES_AXIS_UNITS.get(axis_name),
            },
            "siblings": [
                {
                    "result_id": chain["result_id"],
                    "axis_value": (chain["test_condition"] or {}).get(axis_name),
                    "axis_unit": _SERIES_AXIS_UNITS.get(axis_name),
                    "measurement": {
                        "property": chain["measurement"]["property"],
                        "value": chain["measurement"]["value"],
                        "unit": chain["measurement"]["unit"],
                    },
                }
                for chain in chain_payloads
            ],
        }

    def _select_series_axis(self, chains: list[dict[str, Any]]) -> str:
        for axis_name in _TEST_SERIES_AXIS_CANDIDATES:
            values = {
                self._axis_value_key((chain.get("test_condition") or {}).get(axis_name))
                for chain in chains
                if (chain.get("test_condition") or {}).get(axis_name) is not None
            }
            if len(values) > 1:
                return axis_name
        for axis_name in _TEST_SERIES_AXIS_CANDIDATES:
            if any((chain.get("test_condition") or {}).get(axis_name) is not None for chain in chains):
                return axis_name
        return "test_condition"

    def _property_family(self, comparable_record: ComparableResult) -> str:
        return comparable_record.value.property_normalized or "qualitative"

    def _test_family(
        self,
        comparable_record: ComparableResult,
        test_condition: dict[str, Any],
    ) -> str:
        return (
            self._safe_text(test_condition.get("test_method"))
            or self._safe_text(comparable_record.normalized_context.test_condition_normalized)
            or "unspecified test"
        )

    def _lookup_variant(
        self,
        comparable_record: ComparableResult,
        projection_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        variant_id = self._safe_text(comparable_record.binding.variant_id)
        return (projection_context.get("sample_variants_by_id", {}) or {}).get(variant_id)

    def _lookup_measurement_result(
        self,
        comparable_record: ComparableResult,
        projection_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        source_result_id = self._safe_text(comparable_record.source_result_id)
        return (projection_context.get("measurement_results_by_id", {}) or {}).get(
            source_result_id
        )

    def _lookup_test_condition(
        self,
        comparable_record: ComparableResult,
        projection_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        test_condition_id = self._safe_text(comparable_record.binding.test_condition_id)
        return (projection_context.get("test_conditions_by_id", {}) or {}).get(
            test_condition_id
        )

    def _lookup_baseline(
        self,
        comparable_record: ComparableResult,
        projection_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        baseline_id = self._safe_text(comparable_record.binding.baseline_id)
        return (projection_context.get("baseline_references_by_id", {}) or {}).get(
            baseline_id
        )

    def _structure_feature_summary(
        self,
        feature: dict[str, Any],
        fallback_id: str,
    ) -> str:
        descriptor = self._safe_text(feature.get("qualitative_descriptor"))
        feature_type = self._safe_text(feature.get("feature_type"))
        feature_value = feature.get("feature_value")
        feature_unit = self._safe_text(feature.get("feature_unit"))
        if descriptor:
            return descriptor
        if feature_type and feature_value not in (None, "", [], {}):
            value_text = str(feature_value)
            if feature_unit:
                value_text = f"{value_text} {feature_unit}"
            return f"{feature_type}: {value_text}"
        return f"Linked structure feature {fallback_id}"

    def _characterization_observation_summary(
        self,
        observation: dict[str, Any],
        fallback_id: str,
    ) -> str:
        text = self._safe_text(observation.get("observation_text"))
        if text:
            return text
        observation_type = self._safe_text(observation.get("characterization_type"))
        observed_value = observation.get("observed_value")
        observed_unit = self._safe_text(observation.get("observed_unit"))
        if observation_type and observed_value not in (None, "", [], {}):
            value_text = str(observed_value)
            if observed_unit:
                value_text = f"{value_text} {observed_unit}"
            return f"{observation_type}: {value_text}"
        return f"Linked characterization observation {fallback_id}"

    def _support_temperature(
        self,
        feature: dict[str, Any],
        observation_lookup: dict[str, dict[str, Any]],
    ) -> float | None:
        for observation_id in self._safe_list(feature.get("source_observation_ids")):
            temperature = self._observation_temperature(
                observation_lookup.get(str(observation_id), {})
            )
            if temperature is not None:
                return temperature
        return None

    def _observation_temperature(self, observation: dict[str, Any]) -> float | None:
        condition = self._safe_mapping(observation.get("condition_context"))
        direct = self._optional_float(condition.get("characterization_temperature_c"))
        if direct is not None:
            return direct
        process = self._safe_mapping(condition.get("process"))
        temperatures = self._safe_list(process.get("temperatures_c"))
        if temperatures:
            return self._optional_float(temperatures[0])
        return None

    def _safe_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}

    def _safe_mapping_or_none(self, value: Any) -> dict[str, Any] | None:
        payload = self._safe_mapping(value)
        return payload or None

    def _safe_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, set):
            return list(value)
        return []

    def _optional_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            if isinstance(value, float) and pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _first_value_text(
        self,
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str | None:
        for key in keys:
            value = payload.get(key)
            if value not in (None, "", [], {}):
                return str(value)
        return None

    def _axis_value_key(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    def _axis_sort_key(self, value: Any) -> tuple[int, float | str]:
        numeric = self._optional_float(value)
        if numeric is not None:
            return (0, numeric)
        text = self._safe_text(value)
        return (1, text or "")

    def _serialize_corpus_comparable_result(
        self,
        record: ComparableResult,
        *,
        observed_collection_ids: list[str],
        collection_overlays: list[CollectionComparableResult],
    ) -> dict[str, Any]:
        payload = self._serialize_comparable_result(record)
        payload["observed_collection_ids"] = observed_collection_ids
        payload["collection_overlays"] = [
            self._serialize_collection_comparable_result(scoped_record)
            for scoped_record in collection_overlays
        ]
        return payload

    def _serialize_collection_result_list_item(
        self,
        comparable_record: ComparableResult,
        scoped_record: CollectionComparableResult,
        *,
        document_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        baseline = self._safe_text(comparable_record.baseline_reference) or self._safe_text(
            comparable_record.normalized_context.baseline_normalized
        )
        return {
            "result_id": comparable_record.comparable_result_id,
            "document_id": comparable_record.source_document_id,
            "document_title": self._result_document_title(document_payload),
            "material_label": comparable_record.normalized_context.material_system_normalized,
            "variant_label": comparable_record.variant_label,
            "property": comparable_record.value.property_normalized,
            "value": comparable_record.value.numeric_value,
            "unit": comparable_record.value.unit,
            "summary": comparable_record.value.summary,
            "baseline": baseline,
            "test_condition": comparable_record.normalized_context.test_condition_normalized,
            "process": comparable_record.normalized_context.process_normalized,
            "traceability_status": comparable_record.evidence.traceability_status,
            "comparability_status": scoped_record.assessment.comparability_status,
            "requires_expert_review": scoped_record.assessment.requires_expert_review,
        }

    def _serialize_collection_result_detail(
        self,
        collection_id: str,
        comparable_record: ComparableResult,
        scoped_record: CollectionComparableResult,
        *,
        document_payload: dict[str, Any] | None,
        projection_context: dict[str, Any] | None = None,
        sibling_records: list[
            tuple[CollectionComparableResult, ComparableResult, dict[str, Any] | None]
        ]
        | None = None,
    ) -> dict[str, Any]:
        baseline = self._safe_text(comparable_record.baseline_reference) or self._safe_text(
            comparable_record.normalized_context.baseline_normalized
        )
        evidence_anchor_ids = [
            *comparable_record.evidence.direct_anchor_ids,
            *comparable_record.evidence.contextual_anchor_ids,
        ]
        context = projection_context or {}
        detail = {
            "result_id": comparable_record.comparable_result_id,
            "document": {
                "document_id": comparable_record.source_document_id,
                "title": self._result_document_title(document_payload),
                "source_filename": self._result_document_source_filename(document_payload),
            },
            "material": {
                "label": comparable_record.normalized_context.material_system_normalized,
                "variant_id": comparable_record.binding.variant_id,
                "variant_label": comparable_record.variant_label,
            },
            "measurement": {
                "property": comparable_record.value.property_normalized,
                "value": comparable_record.value.numeric_value,
                "unit": comparable_record.value.unit,
                "result_type": comparable_record.value.result_type,
                "summary": comparable_record.value.summary,
                "statistic_type": comparable_record.value.statistic_type,
                "uncertainty": comparable_record.value.uncertainty,
            },
            "context": {
                "process": comparable_record.normalized_context.process_normalized,
                "baseline": baseline,
                "baseline_reference": comparable_record.baseline_reference,
                "test_condition": comparable_record.normalized_context.test_condition_normalized,
                "axis_name": comparable_record.axis.axis_name,
                "axis_value": comparable_record.axis.axis_value,
                "axis_unit": comparable_record.axis.axis_unit,
            },
            "assessment": {
                "comparability_status": scoped_record.assessment.comparability_status,
                "warnings": list(scoped_record.assessment.comparability_warnings),
                "basis": list(scoped_record.assessment.comparability_basis),
                "missing_context": list(scoped_record.assessment.missing_critical_context),
                "requires_expert_review": scoped_record.assessment.requires_expert_review,
                "assessment_epistemic_status": scoped_record.assessment.assessment_epistemic_status,
            },
            "evidence": [
                {
                    "evidence_id": evidence_id,
                    "traceability_status": comparable_record.evidence.traceability_status,
                    "source_type": comparable_record.result_source_type,
                    "anchor_ids": evidence_anchor_ids,
                }
                for evidence_id in comparable_record.evidence.evidence_ids
            ],
            "actions": self._build_collection_result_actions(collection_id, comparable_record),
        }
        detail.update(
            {
                "variant_dossier": self._build_variant_dossier_summary(
                    comparable_record,
                    projection_context=context,
                ),
                "test_condition_detail": self._build_test_condition_detail(
                    comparable_record,
                    projection_context=context,
                ),
                "baseline_detail": self._build_baseline_detail(
                    comparable_record,
                    projection_context=context,
                    include_scope=True,
                ),
                "structure_support": self._build_structure_support(
                    comparable_record,
                    projection_context=context,
                ),
                "value_provenance": self._build_value_provenance(
                    comparable_record,
                    projection_context=context,
                ),
                "series_navigation": self._build_series_navigation(
                    current_record=comparable_record,
                    sibling_records=sibling_records or [],
                    projection_context=context,
                ),
            }
        )
        return detail

    def _load_document_profile_lookup(self, collection_id: str) -> dict[str, dict[str, Any]]:
        try:
            profiles = self.document_profile_service.list_document_profiles(
                collection_id,
                offset=0,
                limit=10_000,
            )
        except (DocumentProfilesNotReadyError, FileNotFoundError):
            return {}
        return {
            self._safe_text(item.get("document_id")) or "": item
            for item in profiles.get("items", [])
            if self._safe_text(item.get("document_id"))
        }

    def _result_document_title(
        self,
        document_payload: dict[str, Any] | None,
    ) -> str | None:
        return self._safe_text((document_payload or {}).get("title"))

    def _result_document_source_filename(
        self,
        document_payload: dict[str, Any] | None,
    ) -> str | None:
        return self._safe_text((document_payload or {}).get("source_filename"))

    def _build_collection_result_actions(
        self,
        collection_id: str,
        comparable_record: ComparableResult,
    ) -> dict[str, str]:
        comparison_query = urlencode(
            {
                key: value
                for key, value in {
                    "material_system_normalized": comparable_record.normalized_context.material_system_normalized,
                    "property_normalized": comparable_record.value.property_normalized,
                    "baseline_normalized": comparable_record.normalized_context.baseline_normalized,
                    "test_condition_normalized": comparable_record.normalized_context.test_condition_normalized,
                }.items()
                if self._safe_text(value)
            }
        )
        comparisons_path = f"/api/v1/collections/{collection_id}/comparisons"
        if comparison_query:
            comparisons_path = f"{comparisons_path}?{comparison_query}"
        return {
            "open_document": (
                f"/collections/{collection_id}/documents/{comparable_record.source_document_id}"
            ),
            "open_comparisons": (
                f"/collections/{collection_id}/comparisons?{comparison_query}"
                if comparison_query
                else f"/collections/{collection_id}/comparisons"
            ),
            "open_evidence": (
                f"/collections/{collection_id}/evidence"
                if comparable_record.evidence.evidence_ids
                else None
            ),
        }

    def _safe_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None


__all__ = [
    "ComparableResultNotFoundError",
    "ComparisonRowNotFoundError",
    "ComparisonRowsNotReadyError",
    "ComparisonService",
    "ResultNotFoundError",
]
