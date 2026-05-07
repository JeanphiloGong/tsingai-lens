from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.semantic_build.paper_facts_service import (
    PaperFactsNotReadyError,
    PaperFactsService,
)
from application.core.workspace_overview_service import WorkspaceService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService


_PROCESS_COLUMN_ORDER = (
    "laser_power_w",
    "scan_speed_mm_s",
    "hatch_spacing_um",
    "layer_thickness_um",
    "energy_density_j_mm3",
    "energy_density_origin",
    "scan_strategy",
    "build_orientation",
    "post_treatment_summary",
    "preheat_temperature_c",
    "shielding_gas",
    "oxygen_level_ppm",
    "powder_size_distribution_um",
)
_CONDITION_AXIS_CANDIDATES: tuple[tuple[str, str | None], ...] = (
    ("test_temperature_c", "C"),
    ("temperature_c", "C"),
    ("strain_rate_s-1", "s^-1"),
    ("hold_time", "s"),
    ("hold_time_s", "s"),
    ("frequency_hz", "Hz"),
    ("test_condition", None),
    ("test_method", None),
)
_GENERIC_VARIANT_TERMS = (
    "stainless steel",
    "steel",
    "alloy",
    "powder",
    "powders",
    "sample",
    "samples",
    "specimen",
    "specimens",
    "material",
    "materials",
)


class ResearchViewNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve research-view aggregation."""

    def __init__(self, collection_id: str, output_dir: Path | None = None) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"research view not ready: {collection_id}")


class ResearchViewDocumentNotFoundError(FileNotFoundError):
    """Raised when one document has no research-view source rows."""

    def __init__(self, collection_id: str, document_id: str) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        super().__init__(f"research view document not found: {collection_id}/{document_id}")


class ResearchViewMaterialNotFoundError(FileNotFoundError):
    """Raised when a material profile cannot be found in research-view rows."""

    def __init__(
        self,
        collection_id: str,
        material_id: str,
        document_id: str | None = None,
    ) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        self.material_id = material_id
        scope = f"{collection_id}/{document_id}" if document_id else collection_id
        super().__init__(f"research view material not found: {scope}/{material_id}")


class ResearchViewAggregationService:
    """Build research-facing aggregate views from Core semantic artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        task_service: TaskService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        document_profile_service: DocumentProfileService | None = None,
        paper_facts_service: PaperFactsService | None = None,
        comparison_service: ComparisonService | None = None,
        workspace_service: WorkspaceService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.task_service = task_service or TaskService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
            document_profile_service=self.document_profile_service,
        )
        self.comparison_service = comparison_service or ComparisonService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
            paper_facts_service=self.paper_facts_service,
            document_profile_service=self.document_profile_service,
        )
        self.workspace_service = workspace_service or WorkspaceService(
            collection_service=self.collection_service,
            task_service=self.task_service,
            artifact_registry_service=self.artifact_registry_service,
            document_profile_service=self.document_profile_service,
        )

    def get_collection_research_view(self, collection_id: str) -> dict[str, Any]:
        collection = self.collection_service.get_collection(collection_id)
        files = self.collection_service.list_files(collection_id)
        if not files:
            return self._empty_collection_payload(collection_id, collection)

        frames = self._load_fact_frames(collection_id)
        projection = self._load_comparison_projection(collection_id)
        overview = self._build_collection_overview(collection_id, frames, projection)
        paper_coverage = self._build_paper_coverage(collection_id, frames)
        comparable_groups = self._build_comparable_groups(
            collection_id,
            projection,
            frames,
        )
        materials = self._build_material_summaries(
            collection_id,
            frames,
            comparable_groups,
        )
        cross_paper_matrices = [
            group["matrix"]
            for group in comparable_groups
            if group.get("matrix") is not None
        ]
        warnings = [
            warning
            for row in paper_coverage
            for warning in row.get("primary_warnings", [])
        ]
        if projection is None:
            warnings.append(
                self._warning(
                    code="comparison_projection_unavailable",
                    severity="info",
                    scope="collection",
                    message=(
                        "Paper coverage is available, but comparable groups are not "
                        "available until comparison artifacts are generated."
                    ),
                )
            )
        state = self._derive_collection_state(paper_coverage, comparable_groups, warnings)
        return self._clean_value(
            {
                "collection_id": collection_id,
                "state": state,
                "overview": overview,
                "materials": materials,
                "paper_coverage": paper_coverage,
                "comparable_groups": comparable_groups,
                "cross_paper_matrices": cross_paper_matrices,
                "trend_series": [],
                "evidence_links": {
                    "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
                },
                "debug_links": {
                    "results": f"/api/v1/collections/{collection_id}/results",
                    "comparisons": f"/api/v1/collections/{collection_id}/comparisons",
                    "comparable_results": (
                        f"/api/v1/comparable-results?collection_id={collection_id}"
                    ),
                },
                "warnings": self._dedupe_warnings(warnings),
            }
        )

    def list_collection_materials(self, collection_id: str) -> dict[str, Any]:
        collection = self.collection_service.get_collection(collection_id)
        files = self.collection_service.list_files(collection_id)
        if not files:
            return {
                "collection_id": collection_id,
                "state": "empty",
                "materials": [],
                "warnings": [],
            }

        frames = self._load_fact_frames(collection_id)
        projection = self._load_comparison_projection(collection_id)
        comparable_groups = self._build_comparable_groups(
            collection_id,
            projection,
            frames,
            include_matrix=False,
        )
        materials = self._build_material_summaries(
            collection_id,
            frames,
            comparable_groups,
        )
        warnings: list[dict[str, Any]] = []
        if collection.get("paper_count") and not materials:
            warnings.append(
                self._warning(
                    code="no_material_profiles",
                    severity="warning",
                    scope="materials",
                    message="No reliable material bindings were available for this collection.",
                )
            )
        return self._clean_value(
            {
                "collection_id": collection_id,
                "state": self._derive_material_list_state(materials, warnings),
                "materials": materials,
                "warnings": self._dedupe_warnings(warnings),
            }
        )

    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        if not self.collection_service.list_files(collection_id):
            raise ResearchViewMaterialNotFoundError(collection_id, material_id)

        frames = self._load_fact_frames(collection_id)
        projection = self._load_comparison_projection(collection_id)
        material_index_groups = self._build_comparable_groups(
            collection_id,
            projection,
            frames,
            include_matrix=False,
        )
        material_key = self._material_key_from_material_id(
            material_id,
            frames,
            material_index_groups,
        )
        if material_key is None:
            raise ResearchViewMaterialNotFoundError(collection_id, material_id)
        comparable_groups = self._build_comparable_groups(
            collection_id,
            projection,
            frames,
            material_key=material_key,
        )
        profile = self._build_material_profile(
            collection_id,
            material_id,
            frames,
            comparable_groups,
        )
        if profile is None:
            raise ResearchViewMaterialNotFoundError(collection_id, material_id)
        return self._clean_value(profile)

    def get_document_research_view(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        frames = self._load_fact_frames(collection_id)
        if document_id not in self._document_ids_from_frames(frames):
            raise ResearchViewDocumentNotFoundError(collection_id, document_id)
        return self._clean_value(
            self._build_document_aggregation(collection_id, document_id, frames)
        )

    def list_document_materials(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        frames = self._load_fact_frames(collection_id)
        if document_id not in self._document_ids_from_frames(frames):
            raise ResearchViewDocumentNotFoundError(collection_id, document_id)
        materials = self._build_document_material_summaries(
            collection_id,
            document_id,
            frames,
        )
        warnings: list[dict[str, Any]] = []
        if not materials:
            warnings.append(
                self._warning(
                    code="no_document_material_profiles",
                    severity="warning",
                    scope="paper_materials",
                    message="No reliable material bindings were available for this paper.",
                    related_object_ids=[document_id],
                )
            )
        return self._clean_value(
            {
                "collection_id": collection_id,
                "document_id": document_id,
                "state": self._derive_material_list_state(materials, warnings),
                "materials": materials,
                "warnings": self._dedupe_warnings(warnings),
            }
        )

    def get_document_material_research_view(
        self,
        collection_id: str,
        document_id: str,
        material_id: str,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        frames = self._load_fact_frames(collection_id)
        if document_id not in self._document_ids_from_frames(frames):
            raise ResearchViewDocumentNotFoundError(collection_id, document_id)
        profile = self._build_document_material_profile(
            collection_id,
            document_id,
            material_id,
            frames,
        )
        if profile is None:
            raise ResearchViewMaterialNotFoundError(
                collection_id,
                material_id,
                document_id,
            )
        return self._clean_value(profile)

    def _load_fact_frames(self, collection_id: str) -> dict[str, pd.DataFrame]:
        try:
            frames = dict(self.paper_facts_service.read_paper_fact_frames(collection_id))
        except PaperFactsNotReadyError as exc:
            raise ResearchViewNotReadyError(collection_id, exc.output_dir) from exc
        try:
            frames["document_profiles"] = (
                self.document_profile_service.read_document_profiles(collection_id)
            )
        except (DocumentProfilesNotReadyError, FileNotFoundError):
            frames["document_profiles"] = pd.DataFrame()
        return frames

    def _load_comparison_projection(self, collection_id: str):  # noqa: ANN001
        try:
            return self.comparison_service.read_comparison_projection(collection_id)
        except ComparisonRowsNotReadyError:
            return None

    def _build_collection_overview(
        self,
        collection_id: str,
        frames: dict[str, pd.DataFrame],
        projection,  # noqa: ANN001
    ) -> dict[str, Any]:
        sample_variants = frames.get("sample_variants", pd.DataFrame())
        measurement_results = frames.get("measurement_results", pd.DataFrame())
        test_conditions = frames.get("test_conditions", pd.DataFrame())
        evidence_anchors = frames.get("evidence_anchors", pd.DataFrame())
        profiles = frames.get("document_profiles", pd.DataFrame())
        real_variants = [
            self._series_to_dict(row)
            for _, row in sample_variants.iterrows()
            if self._is_real_sample_variant(row)
        ]
        process_variables = sorted(
            {
                key
                for variant in real_variants
                for key, value in self._as_mapping(
                    variant.get("process_context")
                ).items()
                if self._has_observed_value(value)
            }
        )
        document_material_keys = self._single_material_key_by_document(frames, [])
        material_systems = sorted(
            {
                label
                for variant in real_variants
                if (
                    label := self._material_label_from_variant(
                        variant,
                        document_material_keys,
                    )
                )
            }
        )
        measured_properties = sorted(
            {
                prop
                for prop in self._series_values(measurement_results, "property_normalized")
                if prop
            }
        )
        condition_families = sorted(
            {
                axis["axis_name"]
                for _, condition in test_conditions.iterrows()
                if (
                    axis := self._condition_axis_from_payload(
                        self._series_to_dict(condition).get("condition_payload")
                    )
                )
            }
        )
        comparable_group_count = 0
        if projection is not None:
            comparable_group_count = len(
                self._group_comparison_rows(projection.comparison_rows)
            )
        return {
            "collection_id": collection_id,
            "document_count": self._document_count(frames, profiles),
            "sample_variant_count": len(real_variants),
            "measurement_count": int(len(measurement_results)),
            "condition_count": int(len(test_conditions)),
            "evidence_count": int(len(evidence_anchors)),
            "comparable_group_count": comparable_group_count,
            "material_systems": material_systems,
            "process_variables": process_variables,
            "measured_properties": measured_properties,
            "condition_families": condition_families,
        }

    def _build_paper_coverage(
        self,
        collection_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        profiles = frames.get("document_profiles", pd.DataFrame())
        rows: list[dict[str, Any]] = []
        for document_id in sorted(self._document_ids_from_frames(frames)):
            document_frames = self._document_frames(frames, document_id)
            sample_count = sum(
                1
                for _, row in document_frames["sample_variants"].iterrows()
                if self._is_real_sample_variant(row)
            )
            process_keys = {
                key
                for _, row in document_frames["sample_variants"].iterrows()
                for key, value in self._as_mapping(row.get("process_context")).items()
                if self._has_observed_value(value)
            }
            measurement_count = int(len(document_frames["measurement_results"]))
            condition_count = int(len(document_frames["test_conditions"]))
            evidence_count = int(len(document_frames["evidence_anchors"]))
            warnings = self._coverage_warnings(
                document_id=document_id,
                sample_count=sample_count,
                measurement_count=measurement_count,
                evidence_count=evidence_count,
            )
            rows.append(
                {
                    "document_id": document_id,
                    "title": self._document_title(profiles, document_id),
                    "source_filename": self._document_source_filename(
                        profiles,
                        document_id,
                    ),
                    "state": self._derive_paper_state(
                        sample_count=sample_count,
                        measurement_count=measurement_count,
                        evidence_count=evidence_count,
                    ),
                    "sample_count": sample_count,
                    "process_param_count": len(process_keys),
                    "measurement_count": measurement_count,
                    "condition_count": condition_count,
                    "evidence_count": evidence_count,
                    "issue_count": len(warnings),
                    "primary_warnings": warnings,
                    "links": {
                        "research_view": (
                            f"/api/v1/collections/{collection_id}/documents/"
                            f"{document_id}/research-view"
                        ),
                        "profile": (
                            f"/api/v1/collections/{collection_id}/documents/"
                            f"{document_id}/profile"
                        ),
                        "content": (
                            f"/api/v1/collections/{collection_id}/documents/"
                            f"{document_id}/content"
                        ),
                        "debug_comparison_semantics": (
                            f"/api/v1/collections/{collection_id}/documents/"
                            f"{document_id}/comparison-semantics"
                        ),
                    },
                }
            )
        return rows

    def _build_document_aggregation(
        self,
        collection_id: str,
        document_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        document_frames = self._document_frames(frames, document_id)
        sample_matrix = self._build_sample_matrix(
            collection_id,
            document_id,
            document_frames,
        )
        condition_series = self._build_condition_series(
            collection_id,
            document_id,
            document_frames,
        )
        materials = self._build_document_material_summaries(
            collection_id,
            document_id,
            frames,
        )
        warnings = [
            *sample_matrix.get("warnings", []),
            *[
                warning
                for series in condition_series
                for warning in series.get("warnings", [])
            ],
        ]
        overview = self._build_paper_overview(document_id, document_frames, sample_matrix)
        state = self._derive_document_state(sample_matrix, condition_series, warnings)
        return {
            "collection_id": collection_id,
            "document_id": document_id,
            "paper_title": self._document_title(
                frames.get("document_profiles", pd.DataFrame()),
                document_id,
            ),
            "state": state,
            "overview": overview,
            "materials": materials,
            "sample_matrix": sample_matrix,
            "condition_series": condition_series,
            "evidence_links": {
                "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
            },
            "debug_links": {
                "comparison_semantics": (
                    f"/api/v1/collections/{collection_id}/documents/"
                    f"{document_id}/comparison-semantics"
                ),
            },
            "warnings": self._dedupe_warnings(warnings),
        }

    def _build_sample_matrix(
        self,
        collection_id: str,
        document_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        variants = frames.get("sample_variants", pd.DataFrame())
        measurements = frames.get("measurement_results", pd.DataFrame())
        variant_rows = [
            self._series_to_dict(row)
            for _, row in variants.iterrows()
            if self._is_real_sample_variant(row)
        ]
        variant_ids = {
            self._safe_text(row.get("variant_id"))
            for row in variant_rows
            if self._safe_text(row.get("variant_id"))
        }
        for variant_id in sorted(
            {
                self._safe_text(row.get("variant_id"))
                for _, row in measurements.iterrows()
                if self._safe_text(row.get("variant_id"))
            }
            - variant_ids
        ):
            variant_rows.append(
                {
                    "variant_id": variant_id,
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "variant_label": variant_id,
                    "process_context": {},
                    "_synthetic": True,
                }
            )

        measurements_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for _, row in measurements.iterrows():
            record = self._series_to_dict(row)
            variant_id = self._safe_text(record.get("variant_id")) or "unassigned"
            measurements_by_variant[variant_id].append(record)

        document_material_keys = self._single_material_key_by_document(frames, [])
        rows = [
            self._build_sample_matrix_row(
                variant_row,
                measurements_by_variant.get(
                    self._safe_text(variant_row.get("variant_id")) or "",
                    [],
                ),
                frames,
                document_material_keys,
            )
            for variant_row in variant_rows
        ]
        process_keys = [
            key
            for key in _PROCESS_COLUMN_ORDER
            if any(
                self._has_observed_value(row.get("process_context", {}).get(key))
                for row in rows
            )
        ]
        property_columns = self._sample_matrix_property_columns(rows)
        columns = [
            {
                "column_id": "sample_label",
                "label": "Sample",
                "role": "sample",
                "value_key": "sample_label",
            },
            {
                "column_id": "material",
                "label": "Material",
                "role": "process",
                "value_key": "material",
            },
            {
                "column_id": "variable_axis",
                "label": "Variable axis",
                "role": "process",
                "value_key": "variable_axis",
            },
            {
                "column_id": "variable_value",
                "label": "Variable value",
                "role": "process",
                "value_key": "variable_value",
            },
            *[
                {
                    "column_id": key,
                    "label": key,
                    "role": "process",
                    "value_key": key,
                }
                for key in process_keys
            ],
            *property_columns,
        ]
        warnings: list[dict[str, Any]] = []
        if len(variant_rows) < len(variants):
            warnings.append(
                self._warning(
                    code="generic_variants_filtered",
                    severity="info",
                    scope="sample_matrix",
                    message=(
                        "Generic material or process mentions were excluded from "
                        "sample rows."
                    ),
                )
            )
        if measurements_by_variant.get("unassigned"):
            warnings.append(
                self._warning(
                    code="measurement_variant_unassigned",
                    severity="warning",
                    scope="sample_matrix",
                    message="Some measurements do not have a sample or variant binding.",
                    related_object_ids=[
                        self._safe_text(row.get("result_id")) or ""
                        for row in measurements_by_variant["unassigned"]
                    ],
                )
            )
        state = "ready" if rows else "empty"
        if rows and warnings:
            state = "partial"
        return {
            "matrix_id": f"sample-matrix:{document_id}",
            "document_id": document_id,
            "state": state,
            "columns": columns,
            "rows": rows,
            "warnings": self._dedupe_warnings(warnings),
        }

    def _build_sample_matrix_row(
        self,
        variant_row: dict[str, Any] | pd.Series,
        measurements: list[dict[str, Any]],
        frames: dict[str, pd.DataFrame],
        document_material_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        variant = (
            self._series_to_dict(variant_row)
            if isinstance(variant_row, pd.Series)
            else dict(variant_row)
        )
        variant_id = self._safe_text(variant.get("variant_id")) or "unassigned"
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        labels: dict[str, str] = {}
        for measurement in measurements:
            key, label = self._measurement_value_key(measurement, frames)
            grouped[key].append(measurement)
            labels[key] = label

        values = {
            key: {
                **self._build_evidence_backed_value(records, frames),
                "label": labels.get(key, key),
            }
            for key, records in sorted(grouped.items())
        }
        warnings: list[dict[str, Any]] = []
        if variant.get("_synthetic"):
            warnings.append(
                self._warning(
                    code="variant_row_inferred_from_measurements",
                    severity="warning",
                    scope="sample_matrix_row",
                    message=(
                        "This sample row was inferred from measurement bindings "
                        "because no sample variant row was available."
                    ),
                    related_object_ids=[variant_id],
                )
            )
        return {
            "row_id": f"sample-row:{variant_id}",
            "document_id": self._safe_text(variant.get("document_id")),
            "sample_id": variant_id,
            "sample_label": self._safe_text(variant.get("variant_label")) or variant_id,
            "material": self._material_label_from_variant(
                variant,
                document_material_keys,
            )
            or self._material_from_variant(variant),
            "process_context": self._as_mapping(variant.get("process_context")),
            "variable_axis": self._safe_text(variant.get("variable_axis_type")),
            "variable_value": self._clean_value(variant.get("variable_value")),
            "values": values,
            "evidence_refs": self._build_evidence_refs(
                fact_ids=[],
                anchor_ids=self._as_list(variant.get("source_anchor_ids")),
                frames=frames,
            ),
            "warnings": warnings,
        }

    def _is_real_sample_variant(self, variant_row: dict[str, Any] | pd.Series) -> bool:
        variant = (
            self._series_to_dict(variant_row)
            if isinstance(variant_row, pd.Series)
            else dict(variant_row)
        )
        variant_id = self._safe_text(variant.get("variant_id"))
        if not variant_id:
            return False
        process_context = self._as_mapping(variant.get("process_context"))
        has_process = any(self._has_observed_value(value) for value in process_context.values())
        has_variable = self._has_observed_value(variant.get("variable_value")) or bool(
            self._safe_text(variant.get("variable_axis_type"))
        )
        if has_process or has_variable:
            return True

        label = (self._safe_text(variant.get("variant_label")) or "").lower()
        composition = (self._safe_text(variant.get("composition")) or "").lower()
        material = (self._material_from_variant(variant) or "").lower()
        if not label and not composition and not material:
            return False
        generic_candidates = {label, composition, material} - {""}
        return not any(
            term in candidate
            for candidate in generic_candidates
            for term in _GENERIC_VARIANT_TERMS
        )

    def _measurement_cell_key(self, measurement_row: dict[str, Any] | pd.Series) -> tuple:
        measurement = (
            self._series_to_dict(measurement_row)
            if isinstance(measurement_row, pd.Series)
            else dict(measurement_row)
        )
        return (
            self._safe_text(measurement.get("property_normalized"))
            or "unspecified_property",
            self._safe_text(measurement.get("test_condition_id")) or "unspecified_condition",
        )

    def _dedupe_measurements_for_cell(
        self,
        measurements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique: dict[tuple[Any, ...], dict[str, Any]] = {}
        for measurement in measurements:
            value_payload = self._as_mapping(measurement.get("value_payload"))
            numeric_value = self._numeric_value(value_payload)
            if numeric_value is None:
                key = (
                    self._safe_text(measurement.get("property_normalized")),
                    self._safe_text(value_payload.get("source_value_text")),
                    self._measurement_display_unit(measurement, value_payload),
                    self._safe_text(measurement.get("result_type")),
                )
            else:
                key = (
                    self._safe_text(measurement.get("property_normalized")),
                    numeric_value,
                    self._safe_text(measurement.get("result_type")),
                )
            existing = unique.get(key)
            measurement_score = self._measurement_display_score(measurement)
            existing_score = -1
            if existing is not None:
                existing_score = self._measurement_display_score(existing)
            if measurement_score > existing_score:
                unique[key] = measurement
        return list(unique.values())

    def _measurement_display_unit(
        self,
        measurement: dict[str, Any],
        value_payload: dict[str, Any],
    ) -> str:
        unit = self._safe_text(measurement.get("unit")) or self._safe_text(
            value_payload.get("source_unit_text")
        )
        return (unit or "").replace("％", "%").strip().lower()

    def _measurement_display_score(self, measurement: dict[str, Any]) -> int:
        value_payload = self._as_mapping(measurement.get("value_payload"))
        score = 0
        if self._safe_text(measurement.get("unit")):
            score += 2
        if self._safe_text(value_payload.get("source_unit_text")):
            score += 1
        if self._safe_text(value_payload.get("source_value_text")):
            score += 1
        return score

    def _build_evidence_backed_value(
        self,
        measurements: list[dict[str, Any]],
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        if not measurements:
            return self._missing_evidence_backed_value()
        unique = self._dedupe_measurements_for_cell(measurements)
        values = [self._value_from_measurement(measurement) for measurement in unique]
        unique_value_keys = {
            (
                value.get("value"),
                self._safe_text(value.get("unit")),
                self._safe_text(value.get("display_value")),
            )
            for value in values
        }
        conflicted = len(unique_value_keys) > 1
        duplicate_count = max(0, len(measurements) - len(unique))
        warnings: list[dict[str, Any]] = []
        if conflicted:
            warnings.append(
                self._warning(
                    code="conflicting_measurement_values",
                    severity="warning",
                    scope="value",
                    message="Multiple distinct values were found for this matrix cell.",
                    related_object_ids=[
                        self._safe_text(row.get("result_id")) or "" for row in unique
                    ],
                )
            )
        elif duplicate_count:
            warnings.append(
                self._warning(
                    code="duplicate_measurements_collapsed",
                    severity="info",
                    scope="value",
                    message="Duplicate raw measurement facts were collapsed in this cell.",
                    related_object_ids=[
                        self._safe_text(row.get("result_id")) or "" for row in measurements
                    ],
                )
            )
        anchor_ids = [
            anchor_id
            for measurement in measurements
            for anchor_id in self._as_list(measurement.get("evidence_anchor_ids"))
        ]
        fact_ids = [
            self._safe_text(measurement.get("result_id")) or ""
            for measurement in measurements
            if self._safe_text(measurement.get("result_id"))
        ]
        first_value = values[0]
        return {
            "display_value": (
                "; ".join(value["display_value"] for value in values)
                if conflicted
                else first_value["display_value"]
            ),
            "value": None if conflicted else first_value.get("value"),
            "unit": None if conflicted else first_value.get("unit"),
            "normalized_value": None if conflicted else first_value.get("value"),
            "normalized_unit": None if conflicted else first_value.get("unit"),
            "status": "conflicted" if conflicted else "observed",
            "confidence": None,
            "evidence_refs": self._build_evidence_refs(fact_ids, anchor_ids, frames),
            "duplicate_count": duplicate_count,
            "conflict_status": "conflicted" if conflicted else "duplicate_only" if duplicate_count else "none",
            "warnings": self._dedupe_warnings(warnings),
        }

    def _build_evidence_refs(
        self,
        fact_ids: list[str],
        anchor_ids: list[str],
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        anchors = frames.get("evidence_anchors", pd.DataFrame())
        anchor_lookup = {
            self._safe_text(row.get("anchor_id")): self._series_to_dict(row)
            for _, row in anchors.iterrows()
            if self._safe_text(row.get("anchor_id"))
        }
        deduped_anchor_ids = self._dedupe_strings(anchor_ids)
        if not deduped_anchor_ids and fact_ids:
            return [
                {
                    "evidence_ref_id": f"eref:{fact_id}",
                    "fact_ids": [fact_id],
                    "anchor_ids": [],
                    "source_kind": "fact",
                    "document_id": None,
                    "locator": {},
                    "confidence": None,
                    "traceability_status": "missing_anchor",
                }
                for fact_id in self._dedupe_strings(fact_ids)
            ]

        refs: list[dict[str, Any]] = []
        for anchor_id in deduped_anchor_ids:
            anchor = anchor_lookup.get(anchor_id, {})
            refs.append(
                {
                    "evidence_ref_id": f"eref:{anchor_id}",
                    "fact_ids": self._dedupe_strings(fact_ids),
                    "anchor_ids": [anchor_id],
                    "source_kind": self._safe_text(anchor.get("source_type")) or "anchor",
                    "document_id": self._safe_text(anchor.get("document_id")),
                    "locator": {
                        key: self._clean_value(anchor.get(key))
                        for key in (
                            "locator_type",
                            "page",
                            "section_id",
                            "block_id",
                            "snippet_id",
                            "figure_or_table",
                            "char_range",
                            "bbox",
                            "deep_link",
                            "quote",
                        )
                        if self._has_observed_value(anchor.get(key))
                    },
                    "confidence": self._numeric_or_none(anchor.get("locator_confidence")),
                    "traceability_status": "direct",
                }
            )
        return refs

    def _build_condition_series(
        self,
        collection_id: str,
        document_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        measurements = frames.get("measurement_results", pd.DataFrame())
        conditions = frames.get("test_conditions", pd.DataFrame())
        variants = frames.get("sample_variants", pd.DataFrame())
        condition_lookup = {
            self._safe_text(row.get("test_condition_id")): self._series_to_dict(row)
            for _, row in conditions.iterrows()
            if self._safe_text(row.get("test_condition_id"))
        }
        variant_lookup = {
            self._safe_text(row.get("variant_id")): self._series_to_dict(row)
            for _, row in variants.iterrows()
            if self._safe_text(row.get("variant_id"))
        }
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for _, row in measurements.iterrows():
            measurement = self._series_to_dict(row)
            condition_id = self._safe_text(measurement.get("test_condition_id"))
            condition = condition_lookup.get(condition_id or "")
            if not condition:
                continue
            axis = self._condition_axis_from_payload(condition.get("condition_payload"))
            if axis is None:
                continue
            variant_id = self._safe_text(measurement.get("variant_id")) or "unassigned"
            property_name = (
                self._safe_text(measurement.get("property_normalized"))
                or "unspecified_property"
            )
            grouped[(variant_id, property_name, axis["axis_name"])].append(measurement)

        series_items: list[dict[str, Any]] = []
        for (variant_id, property_name, axis_name), records in sorted(grouped.items()):
            points_by_value: dict[tuple[Any, str | None], list[dict[str, Any]]] = defaultdict(list)
            axis_unit: str | None = None
            for record in records:
                condition = condition_lookup.get(
                    self._safe_text(record.get("test_condition_id")) or ""
                )
                if not condition:
                    continue
                axis = self._condition_axis_from_payload(condition.get("condition_payload"))
                if axis is None:
                    continue
                axis_unit = axis.get("unit")
                points_by_value[(axis.get("value"), axis.get("unit"))].append(record)
            if len(points_by_value) < 2:
                continue
            points = [
                {
                    "point_id": (
                        f"series-point:{document_id}:{variant_id}:{property_name}:"
                        f"{axis_name}:{self._slug(str(value))}"
                    ),
                    "condition_value": self._clean_value(value),
                    "condition_unit": unit,
                    "result": self._build_evidence_backed_value(point_records, frames),
                    "evidence_refs": self._build_evidence_backed_value(
                        point_records,
                        frames,
                    )["evidence_refs"],
                    "warnings": [],
                }
                for (value, unit), point_records in sorted(
                    points_by_value.items(),
                    key=lambda item: self._sort_key(item[0][0]),
                )
            ]
            sample = variant_lookup.get(variant_id, {})
            series_items.append(
                {
                    "series_id": (
                        f"condition-series:{document_id}:{variant_id}:"
                        f"{property_name}:{axis_name}"
                    ),
                    "document_id": document_id,
                    "sample_id": variant_id,
                    "sample_label": self._safe_text(sample.get("variant_label")) or variant_id,
                    "property": property_name,
                    "condition_axis": {
                        "axis_name": axis_name,
                        "unit": axis_unit,
                    },
                    "points": points,
                    "warnings": [],
                }
            )
        return series_items

    def _condition_axis_from_payload(
        self,
        condition_payload: Any,
    ) -> dict[str, Any] | None:
        payload = self._as_mapping(condition_payload)
        for axis_name, unit in _CONDITION_AXIS_CANDIDATES:
            value = payload.get(axis_name)
            if self._has_observed_value(value):
                return {
                    "axis_name": axis_name,
                    "value": self._clean_value(value),
                    "unit": unit,
                }
        return None

    def _build_comparable_groups(
        self,
        collection_id: str,
        projection,  # noqa: ANN001
        frames: dict[str, pd.DataFrame],
        *,
        include_matrix: bool = True,
        material_key: str | None = None,
    ) -> list[dict[str, Any]]:
        if projection is None:
            return []
        groups: list[dict[str, Any]] = []
        for group_key, group_rows in self._group_comparison_rows(
            projection.comparison_rows
        ).items():
            rows = [self._series_to_dict(row) for _, row in group_rows.iterrows()]
            material, process, test_condition, baseline, variable_axis = group_key
            if material_key is not None and (
                self._material_key_from_label(material) != material_key
            ):
                continue
            matrix = (
                self._build_cross_paper_matrix(group_rows, frames)
                if include_matrix
                else None
            )
            warnings = self._comparison_group_warnings(rows)
            groups.append(
                {
                    "group_id": f"comparison-group:{self._slug('|'.join(group_key))}",
                    "title": self._comparison_group_title(
                        material,
                        process,
                        test_condition,
                        variable_axis,
                    ),
                    "material_system": material,
                    "process_family": process,
                    "variable_axis": variable_axis or "sample",
                    "fixed_conditions": {
                        "process": process,
                        "test_condition": test_condition,
                        "baseline": baseline,
                    },
                    "properties": sorted(
                        {
                            self._safe_text(row.get("property_normalized")) or ""
                            for row in rows
                            if self._safe_text(row.get("property_normalized"))
                        }
                    ),
                    "documents": sorted(
                        {
                            self._safe_text(row.get("source_document_id")) or ""
                            for row in rows
                            if self._safe_text(row.get("source_document_id"))
                        }
                    ),
                    "samples": sorted(
                        {
                            self._safe_text(row.get("variant_id")) or ""
                            for row in rows
                            if self._safe_text(row.get("variant_id"))
                        }
                    ),
                    "comparability_status": self._aggregate_comparability_status(rows),
                    "matrix": matrix,
                    "evidence_refs": (
                        self._build_evidence_refs(
                            fact_ids=[
                                self._safe_text(row.get("comparable_result_id")) or ""
                                for row in rows
                            ],
                            anchor_ids=[
                                anchor_id
                                for row in rows
                                for anchor_id in self._as_list(
                                    row.get("supporting_anchor_ids")
                                )
                            ],
                            frames=frames,
                        )
                        if include_matrix
                        else []
                    ),
                    "warnings": warnings,
                }
            )
        return groups

    def _build_cross_paper_matrix(
        self,
        group_rows: pd.DataFrame,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        rows = []
        for _, row in group_rows.iterrows():
            record = self._series_to_dict(row)
            result = self._evidence_value_from_comparison_row(record, frames)
            rows.append(
                {
                    "row_id": self._safe_text(record.get("row_id"))
                    or self._safe_text(record.get("comparable_result_id"))
                    or "",
                    "document_id": self._safe_text(record.get("source_document_id")) or "",
                    "sample_id": self._safe_text(record.get("variant_id")),
                    "sample_label": self._safe_text(record.get("variant_label")),
                    "material": self._safe_text(
                        record.get("material_system_normalized")
                    ),
                    "process_context": {
                        "process_normalized": self._safe_text(
                            record.get("process_normalized")
                        )
                    },
                    "variable_value": self._clean_value(record.get("variable_value")),
                    "test_condition": self._safe_text(
                        record.get("test_condition_normalized")
                    ),
                    "property": self._safe_text(record.get("property_normalized")) or "",
                    "result": result,
                    "evidence_refs": result["evidence_refs"],
                    "warnings": result["warnings"],
                }
            )
        group_id = self._slug(
            "|".join(
                self._safe_text(group_rows.iloc[0].get(column)) or ""
                for column in (
                    "material_system_normalized",
                    "process_normalized",
                    "test_condition_normalized",
                    "baseline_normalized",
                    "variable_axis",
                )
            )
        ) if not group_rows.empty else "empty"
        return {
            "matrix_id": f"cross-paper-matrix:{group_id}",
            "group_id": f"comparison-group:{group_id}",
            "columns": [
                {
                    "column_id": "document_id",
                    "label": "Document",
                    "role": "sample",
                    "value_key": "document_id",
                },
                {
                    "column_id": "sample_id",
                    "label": "Sample",
                    "role": "sample",
                    "value_key": "sample_id",
                },
                {
                    "column_id": "property",
                    "label": "Property",
                    "role": "property",
                    "value_key": "property",
                },
                {
                    "column_id": "result",
                    "label": "Result",
                    "role": "property",
                    "value_key": "result",
                },
            ],
            "rows": rows,
            "warnings": [],
        }

    def _build_document_material_summaries(
        self,
        collection_id: str,
        document_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        document_frames = self._document_frames(frames, document_id)
        index = self._build_material_index(document_frames, [])
        summaries: list[dict[str, Any]] = []
        for material_key, entry in sorted(
            index.items(),
            key=lambda item: item[1]["canonical_name"].lower(),
        ):
            material_frames = self._filter_frames_for_material_key(
                material_key,
                document_frames,
            )
            warnings = self._material_binding_warnings(entry)
            summaries.append(
                {
                    "material_id": entry["material_id"],
                    "canonical_name": entry["canonical_name"],
                    "aliases": sorted(entry["aliases"]),
                    "sample_count": len(entry["variant_ids"]),
                    "process_families": sorted(entry["process_families"]),
                    "measured_properties": sorted(entry["measured_properties"]),
                    "comparison_count": len(
                        self._build_within_paper_comparisons(
                            collection_id,
                            document_id,
                            material_frames,
                        )
                    ),
                    "evidence_coverage": self._material_evidence_coverage(
                        material_frames,
                    ),
                    "links": {
                        "research_view": (
                            f"/api/v1/collections/{collection_id}/documents/"
                            f"{document_id}/materials/{entry['material_id']}/research-view"
                        ),
                        "collection_material_research_view": (
                            f"/api/v1/collections/{collection_id}/materials/"
                            f"{entry['material_id']}/research-view"
                        ),
                    },
                    "warnings": warnings,
                }
            )
        return summaries

    def _build_document_material_profile(
        self,
        collection_id: str,
        document_id: str,
        material_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, Any] | None:
        document_frames = self._document_frames(frames, document_id)
        material_key = self._material_key_from_material_id(
            material_id,
            document_frames,
            [],
        )
        if material_key is None:
            return None
        material_frames = self._filter_frames_for_material_key(
            material_key,
            document_frames,
        )
        material_index = self._build_material_index(material_frames, [])
        entry = material_index.get(material_key)
        if entry is None:
            return None

        sample_matrix = self._build_sample_matrix(
            collection_id,
            document_id,
            material_frames,
        )
        condition_series = self._build_condition_series(
            collection_id,
            document_id,
            material_frames,
        )
        measured_properties = self._build_material_property_summaries(
            material_key,
            material_frames,
        )
        within_paper_comparisons = self._build_within_paper_comparisons(
            collection_id,
            document_id,
            material_frames,
        )
        warnings = self._dedupe_warnings(
            [
                *self._material_binding_warnings(entry),
                *sample_matrix.get("warnings", []),
            ]
        )
        return {
            "collection_id": collection_id,
            "document_id": document_id,
            "material_id": entry["material_id"],
            "canonical_name": entry["canonical_name"],
            "aliases": sorted(entry["aliases"]),
            "state": self._derive_material_profile_state(
                sample_matrix,
                measured_properties,
                warnings,
            ),
            "overview": {
                "paper_count": 1,
                "sample_count": len(sample_matrix.get("rows", [])),
                "process_families": sorted(entry["process_families"]),
                "measured_properties": [
                    item["property"] for item in measured_properties
                ],
                "comparison_count": len(within_paper_comparisons),
                "condition_series_count": len(condition_series),
                "evidence_coverage": self._material_evidence_coverage(
                    material_frames,
                ),
            },
            "sample_matrix": sample_matrix,
            "process_conditions": self._build_document_process_conditions(
                material_frames,
            ),
            "test_conditions": self._build_document_test_conditions(material_frames),
            "measured_properties": measured_properties,
            "within_paper_comparisons": within_paper_comparisons,
            "condition_series": condition_series,
            "evidence_refs": self._build_evidence_refs(
                fact_ids=self._fact_ids_from_material_frames(material_frames),
                anchor_ids=self._anchor_ids_from_material_frames(material_frames),
                frames=material_frames,
            ),
            "debug_links": {
                "document_research_view": (
                    f"/api/v1/collections/{collection_id}/documents/"
                    f"{document_id}/research-view"
                ),
                "comparison_semantics": (
                    f"/api/v1/collections/{collection_id}/documents/"
                    f"{document_id}/comparison-semantics"
                ),
            },
            "warnings": warnings,
        }

    def _filter_frames_for_document_material(
        self,
        collection_id: str,  # noqa: ARG002
        document_id: str,
        material_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, pd.DataFrame]:
        document_frames = self._document_frames(frames, document_id)
        material_key = self._material_key_from_material_id(
            material_id,
            document_frames,
            [],
        )
        if material_key is None:
            return {key: frame.iloc[0:0].copy() for key, frame in document_frames.items()}
        return self._filter_frames_for_material_key(material_key, document_frames)

    def _build_material_summaries(
        self,
        collection_id: str,
        frames: dict[str, pd.DataFrame],
        comparable_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        document_material_keys = self._single_material_key_by_document(
            frames,
            comparable_groups,
        )
        index = self._build_material_index(frames, comparable_groups)
        summaries: list[dict[str, Any]] = []
        for material_key, entry in sorted(
            index.items(),
            key=lambda item: item[1]["canonical_name"].lower(),
        ):
            material_frames = self._filter_frames_for_material_key(
                material_key,
                frames,
                document_material_keys,
            )
            warnings = self._material_binding_warnings(entry)
            summaries.append(
                {
                    "material_id": entry["material_id"],
                    "canonical_name": entry["canonical_name"],
                    "aliases": sorted(entry["aliases"]),
                    "paper_count": len(entry["document_ids"]),
                    "sample_count": len(entry["variant_ids"]),
                    "process_families": sorted(entry["process_families"]),
                    "measured_properties": sorted(entry["measured_properties"]),
                    "comparison_count": len(entry["comparison_group_ids"]),
                    "evidence_coverage": self._material_evidence_coverage(
                        material_frames,
                    ),
                    "state": self._derive_material_summary_state(entry, warnings),
                    "links": {
                        "research_view": (
                            f"/api/v1/collections/{collection_id}/materials/"
                            f"{entry['material_id']}/research-view"
                        ),
                        "papers": f"/api/v1/collections/{collection_id}/documents/profiles",
                    },
                    "warnings": warnings,
                }
            )
        return summaries

    def _build_material_profile(
        self,
        collection_id: str,
        material_id: str,
        frames: dict[str, pd.DataFrame],
        comparable_groups: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        material_key = self._material_key_from_material_id(
            material_id,
            frames,
            comparable_groups,
        )
        if material_key is None:
            return None
        document_material_keys = self._single_material_key_by_document(
            frames,
            comparable_groups,
        )
        material_frames = self._filter_frames_for_material_key(
            material_key,
            frames,
            document_material_keys,
        )
        material_index = self._build_material_index(
            material_frames,
            self._filter_comparable_groups_for_material(
                material_key,
                comparable_groups,
            ),
        )
        entry = material_index.get(material_key)
        if entry is None:
            return None

        material_groups = self._filter_comparable_groups_for_material(
            material_key,
            comparable_groups,
        )
        sample_matrix = self._build_material_sample_matrix(
            material_key,
            material_frames,
            document_material_keys,
        )
        papers = self._build_material_paper_coverage(
            collection_id,
            material_key,
            material_frames,
        )
        process_ranges = self._build_material_process_ranges(
            material_key,
            material_frames,
        )
        measured_properties = self._build_material_property_summaries(
            material_key,
            material_frames,
        )
        condition_series = self._build_material_condition_series(
            collection_id,
            material_frames,
        )
        warnings = self._dedupe_warnings(
            [
                *self._material_binding_warnings(entry),
                *sample_matrix.get("warnings", []),
                *[warning for paper in papers for warning in paper.get("warnings", [])],
            ]
        )
        return {
            "collection_id": collection_id,
            "material_id": entry["material_id"],
            "canonical_name": entry["canonical_name"],
            "aliases": sorted(entry["aliases"]),
            "state": self._derive_material_profile_state(
                sample_matrix,
                measured_properties,
                warnings,
            ),
            "overview": {
                "paper_count": len(papers),
                "sample_count": len(sample_matrix.get("rows", [])),
                "process_families": sorted(entry["process_families"]),
                "measured_properties": [
                    item["property"] for item in measured_properties
                ],
                "comparison_count": len(material_groups),
                "condition_series_count": len(condition_series),
                "evidence_coverage": self._material_evidence_coverage(
                    material_frames,
                ),
            },
            "papers": papers,
            "sample_matrix": sample_matrix,
            "process_parameter_ranges": process_ranges,
            "measured_properties": measured_properties,
            "comparison_groups": material_groups,
            "condition_series": condition_series,
            "evidence_refs": self._build_evidence_refs(
                fact_ids=self._fact_ids_from_material_frames(material_frames),
                anchor_ids=self._anchor_ids_from_material_frames(material_frames),
                frames=material_frames,
            ),
            "debug_links": {
                "all_comparisons": f"/api/v1/collections/{collection_id}/comparisons",
                "results": f"/api/v1/collections/{collection_id}/results",
                "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
            },
            "warnings": warnings,
        }

    def _build_material_paper_coverage(
        self,
        collection_id: str,
        material_key: str,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        profiles = frames.get("document_profiles", pd.DataFrame())
        rows: list[dict[str, Any]] = []
        for document_id in sorted(self._document_ids_from_frames(frames)):
            document_frames = self._document_frames(frames, document_id)
            variants = document_frames.get("sample_variants", pd.DataFrame())
            measurements = document_frames.get("measurement_results", pd.DataFrame())
            evidence_anchors = document_frames.get("evidence_anchors", pd.DataFrame())
            sample_count = sum(
                1 for _, row in variants.iterrows() if self._is_real_sample_variant(row)
            )
            if sample_count == 0 and measurements.empty:
                continue
            properties = sorted(
                {
                    self._safe_text(row.get("property_normalized")) or ""
                    for _, row in measurements.iterrows()
                    if self._safe_text(row.get("property_normalized"))
                }
            )
            warnings = self._coverage_warnings(
                document_id=document_id,
                sample_count=sample_count,
                measurement_count=int(len(measurements)),
                evidence_count=int(len(evidence_anchors)),
            )
            material_id = self._material_id_from_key(material_key)
            rows.append(
                {
                    "document_id": document_id,
                    "title": self._document_title(profiles, document_id),
                    "source_filename": self._document_source_filename(
                        profiles,
                        document_id,
                    ),
                    "state": self._derive_paper_state(
                        sample_count=sample_count,
                        measurement_count=int(len(measurements)),
                        evidence_count=int(len(evidence_anchors)),
                    ),
                    "sample_count": sample_count,
                    "process_families": sorted(
                        {
                            process
                            for _, row in variants.iterrows()
                            if (process := self._process_family_from_variant(row))
                        }
                    ),
                    "measured_properties": properties,
                    "evidence_count": int(len(evidence_anchors)),
                    "issue_count": len(warnings),
                    "links": {
                        "paper_research_view": (
                            f"/api/v1/collections/{collection_id}/documents/"
                            f"{document_id}/research-view"
                        ),
                        "document_material_research_view": (
                            f"/api/v1/collections/{collection_id}/documents/"
                            f"{document_id}/materials/{material_id}/research-view"
                        ),
                    },
                    "warnings": warnings,
                }
            )
        return rows

    def _build_material_sample_matrix(
        self,
        material_key: str,
        frames: dict[str, pd.DataFrame],
        document_material_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        variants = frames.get("sample_variants", pd.DataFrame())
        measurements = frames.get("measurement_results", pd.DataFrame())
        material_document_keys = document_material_keys or {
            document_id: material_key
            for document_id in self._document_ids_from_frames(frames)
        }
        variant_rows = [
            self._series_to_dict(row)
            for _, row in variants.iterrows()
            if self._material_key_from_variant(row, material_document_keys) == material_key
            and self._is_real_sample_variant(row)
        ]
        measurements_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for _, row in measurements.iterrows():
            record = self._series_to_dict(row)
            variant_id = self._safe_text(record.get("variant_id")) or "unassigned"
            measurements_by_variant[variant_id].append(record)

        rows = [
            self._build_sample_matrix_row(
                variant_row,
                measurements_by_variant.get(
                    self._safe_text(variant_row.get("variant_id")) or "",
                    [],
                ),
                frames,
                material_document_keys,
            )
            for variant_row in variant_rows
        ]
        process_keys = [
            key
            for key in _PROCESS_COLUMN_ORDER
            if any(
                self._has_observed_value(row.get("process_context", {}).get(key))
                for row in rows
            )
        ]
        columns = [
            {
                "column_id": "document_id",
                "label": "Document",
                "role": "sample",
                "value_key": "document_id",
            },
            {
                "column_id": "sample_label",
                "label": "Sample",
                "role": "sample",
                "value_key": "sample_label",
            },
            {
                "column_id": "variable_axis",
                "label": "Variable axis",
                "role": "process",
                "value_key": "variable_axis",
            },
            {
                "column_id": "variable_value",
                "label": "Variable value",
                "role": "process",
                "value_key": "variable_value",
            },
            *[
                {
                    "column_id": key,
                    "label": key,
                    "role": "process",
                    "value_key": key,
                }
                for key in process_keys
            ],
            *self._sample_matrix_property_columns(rows),
        ]
        warnings: list[dict[str, Any]] = []
        if not rows:
            warnings.append(
                self._warning(
                    code="no_material_sample_rows",
                    severity="warning",
                    scope="material_sample_matrix",
                    message="No sample rows were available for this material.",
                    related_object_ids=[material_key],
                )
            )
        return {
            "matrix_id": f"material-sample-matrix:{self._material_id_from_key(material_key)}",
            "document_id": None,
            "state": "ready" if rows else "empty",
            "columns": columns,
            "rows": rows,
            "warnings": warnings,
        }

    def _build_material_process_ranges(
        self,
        material_key: str,  # noqa: ARG002
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        variants = frames.get("sample_variants", pd.DataFrame())
        grouped: dict[str, list[tuple[dict[str, Any], Any]]] = defaultdict(list)
        for _, row in variants.iterrows():
            variant = self._series_to_dict(row)
            for key, value in self._as_mapping(
                variant.get("process_context")
            ).items():
                if self._has_observed_value(value):
                    grouped[key].append((variant, value))

        ranges: list[dict[str, Any]] = []
        for parameter, records in sorted(grouped.items()):
            values = [value for _, value in records]
            anchor_ids = [
                anchor_id
                for variant, _ in records
                for anchor_id in self._as_list(variant.get("source_anchor_ids"))
            ]
            documents = {
                self._safe_text(variant.get("document_id")) or ""
                for variant, _ in records
                if self._safe_text(variant.get("document_id"))
            }
            samples = {
                self._safe_text(variant.get("variant_id")) or ""
                for variant, _ in records
                if self._safe_text(variant.get("variant_id"))
            }
            summary = self._range_summary(
                values,
                self._process_parameter_unit(parameter),
            )
            ranges.append(
                {
                    "parameter": parameter,
                    **summary,
                    "sample_count": len(samples),
                    "document_count": len(documents),
                    "evidence_refs": self._build_evidence_refs(
                        fact_ids=[],
                        anchor_ids=anchor_ids,
                        frames=frames,
                    ),
                    "warnings": [],
                }
            )
        return ranges

    def _build_material_property_summaries(
        self,
        material_key: str,  # noqa: ARG002
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        measurements = frames.get("measurement_results", pd.DataFrame())
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for _, row in measurements.iterrows():
            measurement = self._series_to_dict(row)
            property_name = (
                self._safe_text(measurement.get("property_normalized"))
                or "unspecified_property"
            )
            grouped[property_name].append(measurement)

        summaries: list[dict[str, Any]] = []
        for property_name, records in sorted(grouped.items()):
            units = {
                self._safe_text(record.get("unit")) or ""
                for record in records
                if self._safe_text(record.get("unit"))
            }
            values = []
            for record in records:
                value_info = self._value_from_measurement(record)
                value = value_info.get("value")
                values.append(
                    value if value is not None else value_info.get("display_value")
                )
            unit = next(iter(units)) if len(units) == 1 else None
            warnings: list[dict[str, Any]] = []
            if len(units) > 1:
                warnings.append(
                    self._warning(
                        code="mixed_property_units",
                        severity="warning",
                        scope="property_summary",
                        message="This property uses multiple units in the source facts.",
                        related_object_ids=[property_name],
                    )
                )
            samples = {
                self._safe_text(record.get("variant_id")) or ""
                for record in records
                if self._safe_text(record.get("variant_id"))
            }
            documents = {
                self._safe_text(record.get("document_id")) or ""
                for record in records
                if self._safe_text(record.get("document_id"))
            }
            summaries.append(
                {
                    "property": property_name,
                    **self._range_summary(values, unit),
                    "sample_count": len(samples),
                    "document_count": len(documents),
                    "evidence_refs": self._build_evidence_refs(
                        fact_ids=[
                            self._safe_text(record.get("result_id")) or ""
                            for record in records
                        ],
                        anchor_ids=[
                            anchor_id
                            for record in records
                            for anchor_id in self._as_list(
                                record.get("evidence_anchor_ids")
                            )
                        ],
                        frames=frames,
                    ),
                    "warnings": warnings,
                }
            )
        return summaries

    def _build_material_condition_series(
        self,
        collection_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        series: list[dict[str, Any]] = []
        for document_id in sorted(self._document_ids_from_frames(frames)):
            series.extend(
                self._build_condition_series(
                    collection_id,
                    document_id,
                    self._document_frames(frames, document_id),
                )
            )
        return series

    def _build_document_process_conditions(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        variants = frames.get("sample_variants", pd.DataFrame())
        conditions: list[dict[str, Any]] = []
        for _, row in variants.iterrows():
            variant = self._series_to_dict(row)
            process_context = self._as_mapping(variant.get("process_context"))
            if not process_context:
                continue
            conditions.append(
                {
                    "sample_id": self._safe_text(variant.get("variant_id")),
                    "sample_label": self._safe_text(variant.get("variant_label")),
                    "process_context": process_context,
                    "evidence_refs": self._build_evidence_refs(
                        fact_ids=[],
                        anchor_ids=self._as_list(variant.get("source_anchor_ids")),
                        frames=frames,
                    ),
                }
            )
        return conditions

    def _build_document_test_conditions(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        conditions = frames.get("test_conditions", pd.DataFrame())
        rows: list[dict[str, Any]] = []
        for _, row in conditions.iterrows():
            condition = self._series_to_dict(row)
            rows.append(
                {
                    "test_condition_id": self._safe_text(
                        condition.get("test_condition_id")
                    ),
                    "condition_payload": self._as_mapping(
                        condition.get("condition_payload")
                    ),
                    "evidence_refs": self._build_evidence_refs(
                        fact_ids=[],
                        anchor_ids=self._as_list(condition.get("evidence_anchor_ids")),
                        frames=frames,
                    ),
                }
            )
        return rows

    def _build_within_paper_comparisons(
        self,
        collection_id: str,  # noqa: ARG002
        document_id: str,
        frames: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        sample_matrix = self._build_sample_matrix(collection_id, document_id, frames)
        grouped: dict[str, list[tuple[dict[str, Any], str, dict[str, Any]]]] = defaultdict(list)
        for row in sample_matrix.get("rows", []):
            for value_key, value in row.get("values", {}).items():
                if value.get("status") not in {"observed", "normalized"}:
                    continue
                property_name = value_key.split("@", 1)[0]
                grouped[property_name].append((row, value_key, value))

        comparisons: list[dict[str, Any]] = []
        for property_name, records in sorted(grouped.items()):
            sample_ids = {row["sample_id"] for row, _, _ in records}
            if len(sample_ids) < 2:
                continue
            variable_axes = {
                self._safe_text(row.get("variable_axis")) or "sample"
                for row, _, _ in records
            }
            variable_axis = next(iter(variable_axes)) if len(variable_axes) == 1 else "sample"
            material = (
                self._safe_text(records[0][0].get("material")) or "unspecified material"
            )
            group_id = (
                f"within-paper-comparison:{document_id}:"
                f"{self._slug(material)}:{self._slug(property_name)}"
            )
            matrix_rows = [
                {
                    "row_id": f"{group_id}:{row['sample_id']}:{self._slug(value_key)}",
                    "document_id": document_id,
                    "sample_id": row.get("sample_id"),
                    "sample_label": row.get("sample_label"),
                    "material": row.get("material"),
                    "process_context": row.get("process_context", {}),
                    "variable_value": row.get("variable_value"),
                    "test_condition": None,
                    "property": property_name,
                    "result": value,
                    "evidence_refs": value.get("evidence_refs", []),
                    "warnings": value.get("warnings", []),
                }
                for row, value_key, value in records
            ]
            comparisons.append(
                {
                    "group_id": group_id,
                    "title": f"{material} {variable_axis} comparison for {property_name}",
                    "material_system": material,
                    "process_family": "paper scoped",
                    "variable_axis": variable_axis,
                    "fixed_conditions": {"document_id": document_id},
                    "properties": [property_name],
                    "documents": [document_id],
                    "samples": sorted(sample_ids),
                    "comparability_status": "comparable",
                    "matrix": {
                        "matrix_id": f"within-paper-matrix:{self._slug(group_id)}",
                        "group_id": group_id,
                        "columns": [
                            {
                                "column_id": "sample_id",
                                "label": "Sample",
                                "role": "sample",
                                "value_key": "sample_id",
                            },
                            {
                                "column_id": "variable_value",
                                "label": "Variable value",
                                "role": "process",
                                "value_key": "variable_value",
                            },
                            {
                                "column_id": "result",
                                "label": "Result",
                                "role": "property",
                                "value_key": "result",
                            },
                        ],
                        "rows": matrix_rows,
                        "warnings": [],
                    },
                    "evidence_refs": [
                        ref
                        for _, _, value in records
                        for ref in value.get("evidence_refs", [])
                    ],
                    "warnings": [],
                }
            )
        return comparisons

    def _filter_comparable_groups_for_material(
        self,
        material_key: str,
        comparable_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            group
            for group in comparable_groups
            if self._material_key_from_label(group.get("material_system")) == material_key
        ]

    def _single_material_key_by_document(
        self,
        frames: dict[str, pd.DataFrame],
        comparable_groups: list[dict[str, Any]],
    ) -> dict[str, str]:
        candidates: dict[str, set[str]] = defaultdict(set)
        profiles = frames.get("document_profiles", pd.DataFrame())
        for document_id in self._document_ids_from_frames(frames):
            candidates[document_id].update(
                self._material_keys_from_document_profile(profiles, document_id)
            )

        variants = frames.get("sample_variants", pd.DataFrame())
        for _, row in variants.iterrows():
            variant = self._series_to_dict(row)
            if not self._is_real_sample_variant(variant):
                continue
            document_id = self._safe_text(variant.get("document_id"))
            material_key = self._material_key_from_label(self._material_from_variant(variant))
            if document_id and material_key:
                candidates[document_id].add(material_key)

        for group in comparable_groups:
            material_key = self._material_key_from_label(group.get("material_system"))
            if material_key is None:
                continue
            for document_id in group.get("documents", []):
                if document_id_text := self._safe_text(document_id):
                    candidates[document_id_text].add(material_key)

        return {
            document_id: next(iter(material_keys))
            for document_id, material_keys in candidates.items()
            if len(material_keys) == 1
        }

    def _material_keys_from_document_profile(
        self,
        profiles: pd.DataFrame,
        document_id: str,
    ) -> set[str]:
        if profiles is None or profiles.empty or "document_id" not in profiles.columns:
            return set()
        matched = profiles[
            profiles["document_id"].apply(lambda value: self._safe_text(value) == document_id)
        ]
        if matched.empty:
            return set()
        profile = self._series_to_dict(matched.iloc[0])
        material_keys: set[str] = set()
        for key in (
            "title",
            "source_filename",
            "filename",
            "document_title",
            "name",
        ):
            if material_key := self._material_key_from_document_text(profile.get(key)):
                material_keys.add(material_key)
        return material_keys

    def _material_key_from_document_text(self, value: Any) -> str | None:
        text = self._safe_text(value)
        if text is None:
            return None
        compact = re.sub(r"[^a-z0-9]", "", text.lower())
        if "316l" in compact:
            return self._material_key_from_label("316L stainless steel")
        if "ti6al4v" in compact or "ti64" in compact:
            return self._material_key_from_label("Ti-6Al-4V")
        if "inconel718" in compact:
            return self._material_key_from_label("Inconel 718")
        if "alsi10mg" in compact:
            return self._material_key_from_label("AlSi10Mg")
        return None

    def _material_label_from_variant(
        self,
        variant: dict[str, Any],
        document_material_keys: dict[str, str] | None = None,
    ) -> str | None:
        material_key = self._material_key_from_variant(variant, document_material_keys)
        if material_key is None:
            return None
        return self._canonical_material_label(self._material_from_variant(variant)) or (
            self._canonical_material_label(material_key)
        )

    def _build_material_index(
        self,
        frames: dict[str, pd.DataFrame],
        comparable_groups: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        variant_to_key: dict[str, str] = {}
        document_material_keys = self._single_material_key_by_document(
            frames,
            comparable_groups,
        )
        variants = frames.get("sample_variants", pd.DataFrame())
        for _, row in variants.iterrows():
            variant = self._series_to_dict(row)
            if not self._is_real_sample_variant(variant):
                continue
            material_key = self._material_key_from_variant(
                variant,
                document_material_keys,
            )
            if material_key is None:
                continue
            display_material = self._material_from_variant(variant)
            if self._material_key_from_label(display_material) is None:
                display_material = material_key
            entry = self._ensure_material_entry(
                index,
                material_key,
                display_material,
            )
            entry["aliases"].update(self._material_aliases_from_variant(variant))
            if document_id := self._safe_text(variant.get("document_id")):
                entry["document_ids"].add(document_id)
            if variant_id := self._safe_text(variant.get("variant_id")):
                entry["variant_ids"].add(variant_id)
                variant_to_key[variant_id] = material_key
            if process := self._process_family_from_variant(variant):
                entry["process_families"].add(process)

        measurements = frames.get("measurement_results", pd.DataFrame())
        for _, row in measurements.iterrows():
            measurement = self._series_to_dict(row)
            material_key = variant_to_key.get(
                self._safe_text(measurement.get("variant_id")) or ""
            )
            if material_key is None:
                continue
            entry = index[material_key]
            if document_id := self._safe_text(measurement.get("document_id")):
                entry["document_ids"].add(document_id)
            if property_name := self._safe_text(
                measurement.get("property_normalized")
            ):
                entry["measured_properties"].add(property_name)

        for group in comparable_groups:
            material_key = self._material_key_from_label(group.get("material_system"))
            if material_key is None:
                continue
            entry = self._ensure_material_entry(
                index,
                material_key,
                self._safe_text(group.get("material_system")),
            )
            if alias := self._safe_text(group.get("material_system")):
                entry["aliases"].add(alias)
            entry["document_ids"].update(
                document_id
                for document_id in group.get("documents", [])
                if self._safe_text(document_id)
            )
            entry["variant_ids"].update(
                sample_id
                for sample_id in group.get("samples", [])
                if self._safe_text(sample_id)
            )
            if process := self._safe_text(group.get("process_family")):
                entry["process_families"].add(process)
            entry["measured_properties"].update(
                property_name
                for property_name in group.get("properties", [])
                if self._safe_text(property_name)
            )
            if group_id := self._safe_text(group.get("group_id")):
                entry["comparison_group_ids"].add(group_id)
        return index

    def _ensure_material_entry(
        self,
        index: dict[str, dict[str, Any]],
        material_key: str,
        display_name: Any,
    ) -> dict[str, Any]:
        canonical_name = (
            self._canonical_material_label(display_name)
            or self._canonical_material_label(material_key)
            or material_key
        )
        entry = index.get(material_key)
        if entry is None:
            entry = {
                "material_key": material_key,
                "material_id": self._material_id_from_key(material_key),
                "canonical_name": canonical_name,
                "aliases": set(),
                "document_ids": set(),
                "variant_ids": set(),
                "process_families": set(),
                "measured_properties": set(),
                "comparison_group_ids": set(),
            }
            index[material_key] = entry
        entry["aliases"].add(canonical_name)
        return entry

    def _material_binding_warnings(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if not entry["variant_ids"]:
            warnings.append(
                self._warning(
                    code="material_without_sample_bindings",
                    severity="warning",
                    scope="material",
                    message=(
                        "This material was detected from comparison rows, but no "
                        "sample variants are bound to it."
                    ),
                    related_object_ids=[entry["material_id"]],
                )
            )
        if not entry["measured_properties"]:
            warnings.append(
                self._warning(
                    code="material_without_measurements",
                    severity="info",
                    scope="material",
                    message="No measured properties are bound to this material yet.",
                    related_object_ids=[entry["material_id"]],
                )
            )
        return warnings

    def _filter_frames_for_material_key(
        self,
        material_key: str,
        frames: dict[str, pd.DataFrame],
        document_material_keys: dict[str, str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        material_keys_by_document = document_material_keys or (
            self._single_material_key_by_document(frames, [])
        )
        variants = frames.get("sample_variants", pd.DataFrame())
        if variants is None or variants.empty:
            selected_variants = pd.DataFrame(
                columns=list(variants.columns) if variants is not None else []
            )
        else:
            selected_variants = variants[
                variants.apply(
                    lambda row: self._material_key_from_variant(
                        row,
                        material_keys_by_document,
                    )
                    == material_key
                    and self._is_real_sample_variant(row),
                    axis=1,
                )
            ].copy()
        variant_ids = {
            self._safe_text(row.get("variant_id")) or ""
            for _, row in selected_variants.iterrows()
            if self._safe_text(row.get("variant_id"))
        }

        measurements = frames.get("measurement_results", pd.DataFrame())
        if (
            measurements is None
            or measurements.empty
            or "variant_id" not in measurements.columns
        ):
            selected_measurements = pd.DataFrame(
                columns=list(measurements.columns) if measurements is not None else []
            )
        else:
            selected_measurements = measurements[
                measurements["variant_id"].apply(
                    lambda value: self._safe_text(value) in variant_ids
                )
            ].copy()

        condition_ids = {
            self._safe_text(row.get("test_condition_id")) or ""
            for _, row in selected_measurements.iterrows()
            if self._safe_text(row.get("test_condition_id"))
        }
        test_conditions = frames.get("test_conditions", pd.DataFrame())
        if (
            test_conditions is None
            or test_conditions.empty
            or "test_condition_id" not in test_conditions.columns
        ):
            selected_conditions = pd.DataFrame(
                columns=list(test_conditions.columns) if test_conditions is not None else []
            )
        else:
            selected_conditions = test_conditions[
                test_conditions["test_condition_id"].apply(
                    lambda value: self._safe_text(value) in condition_ids
                )
            ].copy()

        selected = {
            key: frame.iloc[0:0].copy()
            for key, frame in frames.items()
            if key not in {"sample_variants", "measurement_results", "test_conditions"}
        }
        selected["sample_variants"] = selected_variants
        selected["measurement_results"] = selected_measurements
        selected["test_conditions"] = selected_conditions
        selected["document_profiles"] = frames.get("document_profiles", pd.DataFrame())

        anchor_ids = self._anchor_ids_from_material_frames(selected)
        selected["evidence_anchors"] = self._filter_evidence_anchors(
            frames.get("evidence_anchors", pd.DataFrame()),
            anchor_ids,
        )
        return selected

    def _filter_evidence_anchors(
        self,
        anchors: pd.DataFrame,
        anchor_ids: list[str],
    ) -> pd.DataFrame:
        if anchors is None or anchors.empty or "anchor_id" not in anchors.columns:
            return pd.DataFrame(columns=list(anchors.columns) if anchors is not None else [])
        wanted = set(self._dedupe_strings(anchor_ids))
        return anchors[
            anchors["anchor_id"].apply(lambda value: self._safe_text(value) in wanted)
        ].copy()

    def _material_key_from_variant(
        self,
        variant_row: dict[str, Any] | pd.Series,
        document_material_keys: dict[str, str] | None = None,
    ) -> str | None:
        variant = (
            self._series_to_dict(variant_row)
            if isinstance(variant_row, pd.Series)
            else dict(variant_row)
        )
        material_key = self._material_key_from_label(self._material_from_variant(variant))
        if material_key is not None:
            return material_key
        if document_material_keys is None:
            return None
        document_id = self._safe_text(variant.get("document_id"))
        if document_id is None:
            return None
        return document_material_keys.get(document_id)

    def _material_key_from_comparison_row(
        self,
        row: dict[str, Any] | pd.Series,
    ) -> str | None:
        record = self._series_to_dict(row) if isinstance(row, pd.Series) else dict(row)
        for key in ("material_system_normalized", "material_system", "material"):
            if material_key := self._material_key_from_label(record.get(key)):
                return material_key
        return None

    def _material_key_from_label(self, label: Any) -> str | None:
        canonical = self._canonical_material_label(label)
        if canonical is None:
            return None
        return self._slug(canonical)

    def _canonical_material_label(self, label: Any) -> str | None:
        text = self._safe_text(label)
        if text is None:
            return None
        normalized = re.sub(r"\s+", " ", text.replace("_", " ")).strip()
        lowered = normalized.lower()
        if lowered in {
            "unspecified material",
            "unspecified material system",
            "unspecified_material_system",
            "unknown material",
            "unknown material system",
            "unknown",
            "material",
            "materials",
        }:
            return None
        compact = re.sub(r"[^a-z0-9]", "", lowered)
        if compact in {
            "unspecifiedmaterial",
            "unspecifiedmaterialsystem",
            "unknownmaterial",
            "unknownmaterialsystem",
        }:
            return None
        if compact in {"316l", "ss316l", "aisi316l"} or "316l" in compact:
            return "316L stainless steel"
        if compact in {"ti6al4v", "ti64"} or "ti6al4v" in compact:
            return "Ti-6Al-4V"
        if "inconel718" in compact:
            return "Inconel 718"
        if "alsi10mg" in compact:
            return "AlSi10Mg"
        return normalized

    def _material_key_from_material_id(
        self,
        material_id: str,
        frames: dict[str, pd.DataFrame],
        comparable_groups: list[dict[str, Any]],
    ) -> str | None:
        requested = self._safe_text(material_id)
        if requested is None:
            return None
        index = self._build_material_index(frames, comparable_groups)
        for material_key, entry in index.items():
            if requested in {material_key, entry["material_id"]}:
                return material_key
        return None

    def _material_id_from_key(self, material_key: str) -> str:
        return f"mat-{self._slug(material_key)}"

    def _material_aliases_from_variant(self, variant: dict[str, Any]) -> set[str]:
        aliases: set[str] = set()
        host = self._as_mapping(variant.get("host_material_system"))
        for key in ("composition", "name", "material", "family"):
            if alias := self._safe_text(host.get(key)):
                if self._canonical_material_label(alias):
                    aliases.add(alias)
        if alias := self._safe_text(variant.get("composition")):
            if self._canonical_material_label(alias):
                aliases.add(alias)
        return aliases

    def _process_family_from_variant(
        self,
        variant_row: dict[str, Any] | pd.Series,
    ) -> str | None:
        variant = (
            self._series_to_dict(variant_row)
            if isinstance(variant_row, pd.Series)
            else dict(variant_row)
        )
        process_context = self._as_mapping(variant.get("process_context"))
        for key in (
            "process_family",
            "process_normalized",
            "process",
            "manufacturing_process",
            "process_name",
        ):
            if process := self._safe_text(process_context.get(key)):
                return process
        if any(
            self._has_observed_value(process_context.get(key))
            for key in (
                "laser_power_w",
                "scan_speed_mm_s",
                "hatch_spacing_um",
                "layer_thickness_um",
                "energy_density_j_mm3",
            )
        ):
            return "PBF/laser processing"
        return None

    def _process_parameter_unit(self, parameter: str) -> str | None:
        units = {
            "laser_power_w": "W",
            "scan_speed_mm_s": "mm/s",
            "hatch_spacing_um": "um",
            "layer_thickness_um": "um",
            "energy_density_j_mm3": "J/mm3",
            "preheat_temperature_c": "C",
            "oxygen_level_ppm": "ppm",
            "powder_size_distribution_um": "um",
        }
        return units.get(parameter)

    def _range_summary(
        self,
        values: list[Any],
        unit: str | None,
    ) -> dict[str, Any]:
        cleaned = [value for value in values if self._has_observed_value(value)]
        numeric_values = [
            numeric
            for value in cleaned
            if (numeric := self._numeric_or_none(value)) is not None
        ]
        if numeric_values and len(numeric_values) == len(cleaned):
            min_value = min(numeric_values)
            max_value = max(numeric_values)
            if min_value == max_value:
                display_range = f"{min_value:g}"
            else:
                display_range = f"{min_value:g}-{max_value:g}"
            if unit:
                display_range = f"{display_range} {unit}"
            return {
                "display_range": display_range,
                "min_value": min_value,
                "max_value": max_value,
                "unit": unit,
            }
        labels = self._dedupe_strings(cleaned)
        display_range = ", ".join(labels[:3])
        if len(labels) > 3:
            display_range = f"{display_range}, +{len(labels) - 3} more"
        return {
            "display_range": display_range or None,
            "min_value": None,
            "max_value": None,
            "unit": unit,
        }

    def _material_evidence_coverage(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        measurements = frames.get("measurement_results", pd.DataFrame())
        if measurements is not None and not measurements.empty:
            total = int(len(measurements))
            with_evidence = sum(
                1
                for _, row in measurements.iterrows()
                if self._as_list(row.get("evidence_anchor_ids"))
            )
        else:
            variants = frames.get("sample_variants", pd.DataFrame())
            total = int(len(variants)) if variants is not None else 0
            with_evidence = sum(
                1
                for _, row in variants.iterrows()
                if self._as_list(row.get("source_anchor_ids"))
            ) if variants is not None else 0
        coverage = round(with_evidence / total, 3) if total else None
        return {
            "observed_count": total,
            "with_evidence_count": with_evidence,
            "coverage": coverage,
        }

    def _anchor_ids_from_material_frames(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> list[str]:
        anchor_ids: list[str] = []
        for _, row in frames.get("sample_variants", pd.DataFrame()).iterrows():
            anchor_ids.extend(self._as_list(row.get("source_anchor_ids")))
        for _, row in frames.get("measurement_results", pd.DataFrame()).iterrows():
            anchor_ids.extend(self._as_list(row.get("evidence_anchor_ids")))
        for _, row in frames.get("test_conditions", pd.DataFrame()).iterrows():
            anchor_ids.extend(self._as_list(row.get("evidence_anchor_ids")))
        return self._dedupe_strings(anchor_ids)

    def _fact_ids_from_material_frames(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> list[str]:
        return self._dedupe_strings(
            [
                self._safe_text(row.get("variant_id")) or ""
                for _, row in frames.get("sample_variants", pd.DataFrame()).iterrows()
            ]
            + [
                self._safe_text(row.get("result_id")) or ""
                for _, row in frames.get("measurement_results", pd.DataFrame()).iterrows()
            ]
        )

    def _derive_material_list_state(
        self,
        materials: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> str:
        if not materials:
            return "empty"
        if any(warning.get("severity") == "error" for warning in warnings):
            return "failed"
        if warnings or any(material.get("state") == "partial" for material in materials):
            return "partial"
        return "ready"

    def _derive_material_summary_state(
        self,
        entry: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> str:
        if not entry["variant_ids"] and not entry["comparison_group_ids"]:
            return "empty"
        if any(warning.get("severity") == "error" for warning in warnings):
            return "failed"
        if warnings:
            return "partial"
        return "ready"

    def _derive_material_profile_state(
        self,
        sample_matrix: dict[str, Any],
        measured_properties: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> str:
        if not sample_matrix.get("rows") and not measured_properties:
            return "empty"
        if any(warning.get("severity") == "error" for warning in warnings):
            return "failed"
        if warnings or sample_matrix.get("state") == "partial":
            return "partial"
        return "ready"

    def _warning(
        self,
        code: str,
        severity: str,
        scope: str,
        message: str,
        related_object_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        related_ids = self._dedupe_strings(related_object_ids or [])
        warning_id = self._slug(":".join([code, scope, *related_ids]) or code)
        return {
            "warning_id": f"warning:{warning_id}",
            "severity": severity,
            "scope": scope,
            "code": code,
            "message": message,
            "related_object_ids": related_ids,
        }

    def _empty_collection_payload(
        self,
        collection_id: str,
        collection: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "collection_id": collection_id,
            "state": "empty",
            "overview": {
                "collection_id": collection_id,
                "document_count": int(collection.get("paper_count") or 0),
                "sample_variant_count": 0,
                "measurement_count": 0,
                "condition_count": 0,
                "evidence_count": 0,
                "comparable_group_count": 0,
                "material_systems": [],
                "process_variables": [],
                "measured_properties": [],
                "condition_families": [],
            },
            "materials": [],
            "paper_coverage": [],
            "comparable_groups": [],
            "cross_paper_matrices": [],
            "trend_series": [],
            "evidence_links": {
                "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
            },
            "debug_links": {
                "results": f"/api/v1/collections/{collection_id}/results",
                "comparisons": f"/api/v1/collections/{collection_id}/comparisons",
                "comparable_results": (
                    f"/api/v1/comparable-results?collection_id={collection_id}"
                ),
            },
            "warnings": [],
        }

    def _build_paper_overview(
        self,
        document_id: str,
        frames: dict[str, pd.DataFrame],
        sample_matrix: dict[str, Any],
    ) -> dict[str, Any]:
        sample_variants = frames.get("sample_variants", pd.DataFrame())
        measurements = frames.get("measurement_results", pd.DataFrame())
        test_conditions = frames.get("test_conditions", pd.DataFrame())
        real_variants = [
            self._series_to_dict(row)
            for _, row in sample_variants.iterrows()
            if self._is_real_sample_variant(row)
        ]
        return {
            "document_id": document_id,
            "material_systems": sorted(
                {
                    label
                    for variant in real_variants
                    if (
                        label := self._material_label_from_variant(
                            variant,
                            self._single_material_key_by_document(frames, []),
                        )
                    )
                }
            ),
            "sample_variant_count": len(sample_matrix.get("rows", [])),
            "main_process_variables": sorted(
                {
                    key
                    for variant in real_variants
                    for key, value in self._as_mapping(
                        variant.get("process_context")
                    ).items()
                    if self._has_observed_value(value)
                }
            ),
            "measured_properties": sorted(
                {
                    self._safe_text(row.get("property_normalized")) or ""
                    for _, row in measurements.iterrows()
                    if self._safe_text(row.get("property_normalized"))
                }
            ),
            "condition_families": sorted(
                {
                    axis["axis_name"]
                    for _, row in test_conditions.iterrows()
                    if (
                        axis := self._condition_axis_from_payload(
                            self._series_to_dict(row).get("condition_payload")
                        )
                    )
                }
            ),
            "warning_count": len(sample_matrix.get("warnings", [])),
        }

    def _document_frames(
        self,
        frames: dict[str, pd.DataFrame],
        document_id: str,
    ) -> dict[str, pd.DataFrame]:
        return {
            key: self._filter_frame_by_document(frame, document_id)
            for key, frame in frames.items()
            if key != "document_profiles"
        } | {"document_profiles": frames.get("document_profiles", pd.DataFrame())}

    def _filter_frame_by_document(
        self,
        frame: pd.DataFrame,
        document_id: str,
    ) -> pd.DataFrame:
        if frame is None or frame.empty or "document_id" not in frame.columns:
            return pd.DataFrame(columns=list(frame.columns) if frame is not None else [])
        return frame[
            frame["document_id"].apply(lambda value: self._safe_text(value) == document_id)
        ].copy()

    def _document_ids_from_frames(self, frames: dict[str, pd.DataFrame]) -> set[str]:
        document_ids: set[str] = set()
        for frame in frames.values():
            if frame is None or frame.empty or "document_id" not in frame.columns:
                continue
            document_ids.update(
                self._safe_text(value) or ""
                for value in frame["document_id"].tolist()
                if self._safe_text(value)
            )
        return document_ids

    def _document_title(self, profiles: pd.DataFrame, document_id: str) -> str | None:
        if profiles is None or profiles.empty or "document_id" not in profiles.columns:
            return None
        matched = profiles[
            profiles["document_id"].apply(lambda value: self._safe_text(value) == document_id)
        ]
        if matched.empty:
            return None
        return self._safe_text(matched.iloc[0].get("title"))

    def _document_source_filename(
        self,
        profiles: pd.DataFrame,
        document_id: str,
    ) -> str | None:
        if profiles is None or profiles.empty or "document_id" not in profiles.columns:
            return None
        matched = profiles[
            profiles["document_id"].apply(lambda value: self._safe_text(value) == document_id)
        ]
        if matched.empty:
            return None
        row = matched.iloc[0]
        for key in ("source_filename", "filename", "source_file"):
            if source_filename := self._safe_text(row.get(key)):
                return source_filename
        return None

    def _document_count(
        self,
        frames: dict[str, pd.DataFrame],
        profiles: pd.DataFrame,
    ) -> int:
        if profiles is not None and not profiles.empty:
            return int(len(profiles))
        return len(self._document_ids_from_frames(frames))

    def _coverage_warnings(
        self,
        *,
        document_id: str,
        sample_count: int,
        measurement_count: int,
        evidence_count: int,
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if sample_count == 0:
            warnings.append(
                self._warning(
                    code="no_sample_rows",
                    severity="warning",
                    scope="paper",
                    message="No real sample or variant rows were detected for this paper.",
                    related_object_ids=[document_id],
                )
            )
        if measurement_count == 0:
            warnings.append(
                self._warning(
                    code="no_measurement_results",
                    severity="warning",
                    scope="paper",
                    message="No measurement results were detected for this paper.",
                    related_object_ids=[document_id],
                )
            )
        if measurement_count and evidence_count == 0:
            warnings.append(
                self._warning(
                    code="missing_evidence_anchors",
                    severity="warning",
                    scope="paper",
                    message="Measurement results exist, but evidence anchors are unavailable.",
                    related_object_ids=[document_id],
                )
            )
        return warnings

    def _derive_collection_state(
        self,
        paper_coverage: list[dict[str, Any]],
        comparable_groups: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> str:
        if not paper_coverage:
            return "empty"
        if comparable_groups and not any(warning["severity"] == "error" for warning in warnings):
            return "ready"
        if any(row.get("state") == "ready" for row in paper_coverage):
            return "partial"
        return "empty"

    def _derive_paper_state(
        self,
        *,
        sample_count: int,
        measurement_count: int,
        evidence_count: int,
    ) -> str:
        if sample_count == 0 and measurement_count == 0:
            return "empty"
        if sample_count > 0 and measurement_count > 0 and evidence_count > 0:
            return "ready"
        return "partial"

    def _derive_document_state(
        self,
        sample_matrix: dict[str, Any],
        condition_series: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> str:
        if not sample_matrix.get("rows") and not condition_series:
            return "empty"
        if any(warning["severity"] == "error" for warning in warnings):
            return "failed"
        if warnings or sample_matrix.get("state") == "partial":
            return "partial"
        return "ready"

    def _sample_matrix_property_columns(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        columns: dict[str, dict[str, Any]] = {}
        for row in rows:
            for key, value in row.get("values", {}).items():
                columns[key] = {
                    "column_id": key,
                    "label": value.get("label") or key,
                    "role": "property",
                    "value_key": key,
                }
        return [columns[key] for key in sorted(columns)]

    def _measurement_value_key(
        self,
        measurement: dict[str, Any],
        frames: dict[str, pd.DataFrame],
    ) -> tuple[str, str]:
        property_name, condition_id = self._measurement_cell_key(measurement)
        condition = self._row_by_id(
            frames.get("test_conditions", pd.DataFrame()),
            "test_condition_id",
            condition_id,
        )
        if condition:
            axis = self._condition_axis_from_payload(condition.get("condition_payload"))
            if axis is not None:
                value = axis.get("value")
                unit = axis.get("unit")
                value_text = f"{value} {unit}".strip() if unit else str(value)
                key = f"{property_name}@{axis['axis_name']}={self._slug(str(value))}"
                return key, f"{property_name} @ {value_text}"
        return property_name, property_name

    def _row_by_id(
        self,
        frame: pd.DataFrame,
        id_column: str,
        value: str | None,
    ) -> dict[str, Any] | None:
        if frame is None or frame.empty or id_column not in frame.columns or not value:
            return None
        matched = frame[
            frame[id_column].apply(lambda candidate: self._safe_text(candidate) == value)
        ]
        if matched.empty:
            return None
        return self._series_to_dict(matched.iloc[0])

    def _value_from_measurement(self, measurement: dict[str, Any]) -> dict[str, Any]:
        value_payload = self._as_mapping(measurement.get("value_payload"))
        numeric_value = self._numeric_value(value_payload)
        unit = self._safe_text(measurement.get("unit")) or self._safe_text(
            value_payload.get("source_unit_text")
        )
        source_value = self._safe_text(value_payload.get("source_value_text"))
        display = source_value or (
            str(numeric_value) if numeric_value is not None else "reported"
        )
        if unit and unit not in display:
            display = f"{display} {unit}"
        return {
            "display_value": display,
            "value": numeric_value,
            "unit": unit,
        }

    def _missing_evidence_backed_value(self) -> dict[str, Any]:
        return {
            "display_value": None,
            "value": None,
            "unit": None,
            "normalized_value": None,
            "normalized_unit": None,
            "status": "missing",
            "confidence": None,
            "evidence_refs": [],
            "duplicate_count": 0,
            "conflict_status": "none",
            "warnings": [],
        }

    def _evidence_value_from_comparison_row(
        self,
        row: dict[str, Any],
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        value = self._numeric_or_none(row.get("value"))
        unit = self._safe_text(row.get("unit"))
        display_value = self._safe_text(row.get("result_summary")) or (
            f"{value} {unit}".strip() if value is not None else None
        )
        warnings = [
            self._warning(
                code="comparison_row_limited",
                severity="warning",
                scope="comparison_row",
                message=warning,
                related_object_ids=[self._safe_text(row.get("comparable_result_id")) or ""],
            )
            for warning in self._as_list(row.get("comparability_warnings"))
        ]
        return {
            "display_value": display_value,
            "value": value,
            "unit": unit,
            "normalized_value": value,
            "normalized_unit": unit,
            "status": "observed" if value is not None or display_value else "missing",
            "confidence": None,
            "evidence_refs": self._build_evidence_refs(
                fact_ids=[self._safe_text(row.get("comparable_result_id")) or ""],
                anchor_ids=self._as_list(row.get("supporting_anchor_ids")),
                frames=frames,
            ),
            "duplicate_count": 0,
            "conflict_status": "none",
            "warnings": warnings,
        }

    def _group_comparison_rows(
        self,
        rows: pd.DataFrame,
    ) -> dict[tuple[str, str, str, str, str], pd.DataFrame]:
        if rows is None or rows.empty:
            return {}
        grouped: dict[tuple[str, str, str, str, str], list[int]] = defaultdict(list)
        for index, row in rows.iterrows():
            key = (
                self._safe_text(row.get("material_system_normalized"))
                or "unspecified material",
                self._safe_text(row.get("process_normalized")) or "unspecified process",
                self._safe_text(row.get("test_condition_normalized"))
                or "unspecified test condition",
                self._safe_text(row.get("baseline_normalized"))
                or "unspecified baseline",
                self._safe_text(row.get("variable_axis")) or "",
            )
            grouped[key].append(index)
        return {key: rows.loc[indexes].copy() for key, indexes in grouped.items()}

    def _comparison_group_title(
        self,
        material: str,
        process: str,
        test_condition: str,
        variable_axis: str,
    ) -> str:
        axis = variable_axis or "sample"
        return f"{material} {axis} comparison under {test_condition} ({process})"

    def _aggregate_comparability_status(self, rows: list[dict[str, Any]]) -> str:
        statuses = {
            self._safe_text(row.get("comparability_status")) or "limited"
            for row in rows
        }
        sample_count = len(
            {
                self._safe_text(row.get("variant_id")) or self._safe_text(row.get("row_id"))
                for row in rows
            }
        )
        if "not_comparable" in statuses:
            return "blocked"
        if statuses <= {"comparable"} and sample_count > 1:
            return "comparable"
        return "limited"

    def _comparison_group_warnings(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        samples = {
            self._safe_text(row.get("variant_id")) or ""
            for row in rows
            if self._safe_text(row.get("variant_id"))
        }
        if len(samples) < 2:
            warnings.append(
                self._warning(
                    code="single_sample_comparison_group",
                    severity="info",
                    scope="comparable_group",
                    message=(
                        "This group has fewer than two sample bindings, so it is "
                        "a limited comparison group."
                    ),
                )
            )
        for row in rows:
            for warning in self._as_list(row.get("comparability_warnings")):
                warnings.append(
                    self._warning(
                        code="row_comparability_warning",
                        severity="warning",
                        scope="comparable_group",
                        message=str(warning),
                        related_object_ids=[
                            self._safe_text(row.get("comparable_result_id")) or ""
                        ],
                    )
                )
        return self._dedupe_warnings(warnings)

    def _material_from_variant(self, variant: dict[str, Any]) -> str | None:
        host = self._as_mapping(variant.get("host_material_system"))
        for key in ("composition", "family", "name", "material"):
            if material := self._safe_text(host.get(key)):
                return material
        return self._safe_text(variant.get("composition"))

    def _series_values(self, frame: pd.DataFrame, column: str) -> list[str]:
        if frame is None or frame.empty or column not in frame.columns:
            return []
        return [
            self._safe_text(value) or ""
            for value in frame[column].tolist()
            if self._safe_text(value)
        ]

    def _series_to_dict(self, row: pd.Series | dict[str, Any]) -> dict[str, Any]:
        return {
            str(key): self._clean_value(value)
            for key, value in dict(row).items()
        }

    def _as_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return self._clean_value(value)
        return {}

    def _as_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return [self._clean_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._clean_value(item) for item in value]
        if isinstance(value, set):
            return [self._clean_value(item) for item in sorted(value)]
        if self._has_observed_value(value):
            return [self._clean_value(value)]
        return []

    def _numeric_value(self, value_payload: dict[str, Any]) -> float | int | None:
        for key in ("value", "numeric_value", "normalized_value"):
            value = value_payload.get(key)
            numeric = self._numeric_or_none(value)
            if numeric is not None:
                return numeric
        return None

    def _numeric_or_none(self, value: Any) -> float | int | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return None
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed

    def _safe_text(self, value: Any) -> str | None:
        if value is None or isinstance(value, (dict, list, tuple, set)):
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null", "n/a", "na"}:
            return None
        return text

    def _has_observed_value(self, value: Any) -> bool:
        if isinstance(value, (dict, list, tuple, set)):
            return bool(value)
        return self._safe_text(value) is not None or self._numeric_or_none(value) is not None

    def _dedupe_strings(self, values: list[Any]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            text = self._safe_text(value)
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    def _dedupe_warnings(
        self,
        warnings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for warning in warnings:
            deduped.setdefault(str(warning.get("warning_id") or warning.get("code")), warning)
        return list(deduped.values())

    def _clean_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._clean_value(item)
                for key, item in value.items()
                if self._clean_value(item) is not None
            }
        if isinstance(value, list):
            return [self._clean_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._clean_value(item) for item in value]
        if value is None:
            return None
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", value.strip().lower()).strip("-")
        return slug or "unspecified"

    def _sort_key(self, value: Any) -> tuple[int, Any]:
        numeric = self._numeric_or_none(value)
        if numeric is not None:
            return (0, numeric)
        return (1, str(value))
