from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any

from application.core.comparison_service import (
    ComparisonService,
)
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.core.research_understanding_service import ResearchUnderstandingService
from application.core.workspace_overview_service import WorkspaceService
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from domain.core import ResearchUnderstanding
from domain.core.fact_store import CoreFactSet
from domain.core.objective_material_projection import (
    project_objective_material_rows,
)
from domain.ports import CoreFactRepository
from infra.persistence.factory import build_core_fact_repository


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
_NON_MATERIAL_SYSTEM_COMPACT_LABELS = {
    "argon",
    "ar",
}
_SAMPLE_CONTEXT_DIRECT_KEYS = (
    "sample",
    "sample_label",
    "variant_label",
    "sample_name",
    "specimen",
    "specimen_label",
    "condition",
    "condition_label",
    "sample_id",
    "variant_id",
)
_SAMPLE_CONTEXT_SECONDARY_KEYS = (
    "build platform conditions",
    "build platform condition",
    "printed",
    "printed > 316l",
    "printed 316l",
    "specimens",
    "sample number",
    "condition number",
    "sample_number",
    "condition_number",
)
_SAMPLE_CONTEXT_EXCLUDED_KEYS = {
    "material",
    "materials",
    "material_system",
    "host_material_system",
    "composition",
    "alloy",
}
_SAMPLE_CONTEXT_PROCESS_KEYS = {
    "build platform conditions",
    "build platform condition",
    "condition",
    "condition label",
}
_FactRows = dict[str, list[dict[str, Any]]]
_ComparisonGroups = dict[tuple[str, str, str, str, str], list[dict[str, Any]]]


class ResearchViewNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve research-view aggregation."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
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
        collection_service: CollectionService,
        task_service: TaskService | None = None,
        document_profile_service: DocumentProfileService | None = None,
        paper_facts_service: PaperFactsService | None = None,
        comparison_service: ComparisonService | None = None,
        workspace_service: WorkspaceService | None = None,
        core_fact_repository: CoreFactRepository | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.task_service = task_service or TaskService()
        self.core_fact_repository = (
            core_fact_repository
            or getattr(paper_facts_service, "core_fact_repository", None)
            or build_core_fact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            core_fact_repository=self.core_fact_repository,
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
            document_profile_service=self.document_profile_service,
            core_fact_repository=self.core_fact_repository,
        )
        self.comparison_service = comparison_service or ComparisonService(
            collection_service=self.collection_service,
            document_profile_service=self.document_profile_service,
            core_fact_repository=self.core_fact_repository,
        )
        self.workspace_service = workspace_service or WorkspaceService(
            collection_service=self.collection_service,
            task_service=self.task_service,
            document_profile_service=self.document_profile_service,
        )
        self.research_understanding_service = ResearchUnderstandingService()

    def get_collection_research_view(self, collection_id: str) -> dict[str, Any]:
        collection = self.collection_service.get_collection(collection_id)
        files = self.collection_service.list_files(collection_id)
        if not files:
            return self._empty_collection_payload(collection_id, collection)

        facts = self._load_collection_facts(collection_id)
        frames = self._core_fact_records(facts)
        projection = self._comparison_projection_from_facts(facts)
        objective_material_rows = self._objective_material_rows_from_facts(facts)
        if objective_material_rows:
            overview = self._build_objective_collection_overview(
                collection_id,
                facts,
                objective_material_rows,
                projection,
            )
            paper_coverage = self._build_objective_collection_paper_coverage(
                collection_id,
                facts,
                objective_material_rows,
            )
            comparable_groups = self._build_comparable_groups(
                collection_id,
                projection,
                frames,
            )
            materials = self._build_objective_material_summaries(
                collection_id,
                objective_material_rows,
            )
            return self._build_collection_research_payload(
                collection_id=collection_id,
                overview=overview,
                materials=materials,
                paper_coverage=paper_coverage,
                comparable_groups=comparable_groups,
                comparison_projection_warning=(
                    "Objective material evidence is available, but "
                    "comparable groups are not available until "
                    "comparison artifacts are generated."
                    if projection is None
                    else None
                ),
            )
        overview = self._build_collection_overview(collection_id, frames, projection)
        paper_coverage = self._build_paper_coverage(collection_id, frames)
        comparable_groups = self._build_comparable_groups(
            collection_id,
            projection,
            frames,
        )
        return self._build_collection_research_payload(
            collection_id=collection_id,
            overview=overview,
            materials=[],
            paper_coverage=paper_coverage,
            comparable_groups=comparable_groups,
            comparison_projection_warning=(
                "Paper coverage is available, but material research-view "
                "requires objective evidence units."
                if projection is None
                else None
            ),
        )

    def _build_collection_research_payload(
        self,
        *,
        collection_id: str,
        overview: dict[str, Any],
        materials: list[dict[str, Any]],
        paper_coverage: list[dict[str, Any]],
        comparable_groups: list[dict[str, Any]],
        comparison_projection_warning: str | None,
    ) -> dict[str, Any]:
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
        if comparison_projection_warning is not None:
            warnings.append(
                self._warning(
                    code="comparison_projection_unavailable",
                    severity="info",
                    scope="collection",
                    message=comparison_projection_warning,
                )
            )
        state = self._derive_collection_state(
            paper_coverage,
            comparable_groups,
            warnings,
        )
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

        facts = self._load_collection_facts(collection_id)
        objective_material_rows = self._objective_material_rows_from_facts(facts)
        if objective_material_rows:
            materials = self._build_objective_material_summaries(
                collection_id,
                objective_material_rows,
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

        raise ResearchViewNotReadyError(collection_id)

    def get_collection_material_research_view(
        self,
        collection_id: str,
        material_id: str,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        if not self.collection_service.list_files(collection_id):
            raise ResearchViewMaterialNotFoundError(collection_id, material_id)

        facts = self._load_collection_facts(collection_id)
        objective_material_rows = self._objective_material_rows_from_facts(facts)
        if objective_material_rows:
            profile = self._build_objective_material_profile(
                collection_id,
                material_id,
                facts,
                objective_material_rows,
            )
            if profile is None:
                raise ResearchViewMaterialNotFoundError(collection_id, material_id)
            understanding = self.core_fact_repository.read_research_understanding(
                collection_id,
                "material",
                profile["material_id"],
            )
            profile["understanding"] = (
                self.research_understanding_service.with_presentation(understanding)
            )
            return self._clean_value(profile)

        raise ResearchViewNotReadyError(collection_id)

    def persist_material_understandings(
        self,
        collection_id: str,
    ) -> tuple[ResearchUnderstanding, ...]:
        self.collection_service.get_collection(collection_id)
        facts = self._load_collection_facts(collection_id)
        objective_material_rows = self._objective_material_rows_from_facts(facts)
        if not objective_material_rows:
            existing_non_material = tuple(
                item
                for item in self.core_fact_repository.list_research_understandings(collection_id)
                if item.scope.scope_type != "material"
            )
            self.core_fact_repository.replace_collection_research_understandings(
                collection_id,
                existing_non_material,
            )
            return ()

        material_summaries = self._build_objective_material_summaries(
            collection_id,
            objective_material_rows,
        )
        understandings: list[ResearchUnderstanding] = []
        for summary in material_summaries:
            material_id = str(summary.get("material_id") or "").strip()
            if not material_id:
                continue
            profile = self._build_objective_material_profile(
                collection_id,
                material_id,
                facts,
                objective_material_rows,
            )
            if profile is None:
                continue
            understandings.append(
                ResearchUnderstanding.from_mapping(
                    self.research_understanding_service.build_material_understanding(
                        profile
                    )
                )
            )
        existing_non_material = tuple(
            item
            for item in self.core_fact_repository.list_research_understandings(collection_id)
            if item.scope.scope_type != "material"
        )
        persisted = (*existing_non_material, *understandings)
        self.core_fact_repository.replace_collection_research_understandings(
            collection_id,
            persisted,
        )
        return tuple(understandings)

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

    def _load_fact_frames(self, collection_id: str) -> _FactRows:
        return self._core_fact_records(self._load_collection_facts(collection_id))

    def _load_collection_facts(self, collection_id: str) -> CoreFactSet:
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if not facts.has_paper_facts() and not facts.objective_evidence_units:
            raise ResearchViewNotReadyError(collection_id)
        return facts

    def _objective_material_rows_from_facts(
        self,
        facts: CoreFactSet,
    ) -> list[dict[str, Any]]:
        rows = [
            row.to_record()
            for row in project_objective_material_rows(facts.objective_evidence_units)
        ]
        objective_material_scopes = self._objective_material_scopes(facts)
        if not objective_material_scopes:
            return rows
        return [
            self._row_with_objective_material_scope(row, objective_material_scopes)
            for row in rows
        ]

    def _objective_material_scopes(
        self,
        facts: CoreFactSet,
    ) -> dict[str, str]:
        scopes: dict[str, str] = {}
        for objective in facts.research_objectives:
            labels = [
                label
                for label in (
                    self._canonical_material_label(value)
                    for value in objective.material_scope
                )
                if label
            ]
            if len(set(labels)) == 1:
                scopes[objective.objective_id] = labels[0]
        return scopes

    def _row_with_objective_material_scope(
        self,
        row: dict[str, Any],
        objective_material_scopes: dict[str, str],
    ) -> dict[str, Any]:
        if self._objective_material_label_from_row(row) is not None:
            return row
        objective_id = self._safe_text(row.get("objective_id"))
        if objective_id is None:
            return row
        material_label = objective_material_scopes.get(objective_id)
        if material_label is None:
            return row
        enriched = dict(row)
        enriched["material_system"] = {
            **self._as_mapping(row.get("material_system")),
            "name": material_label,
        }
        return enriched

    def _comparison_projection_from_facts(
        self,
        facts: CoreFactSet,
    ) -> list[dict[str, Any]] | None:
        if not facts.comparison_rows:
            return None
        return self._records_list(facts.comparison_rows)

    def _core_fact_records(self, facts: CoreFactSet) -> _FactRows:
        return {
            "document_profiles": self._records_list(facts.document_profiles),
            "evidence_anchors": self._records_list(facts.evidence_anchors),
            "method_facts": self._records_list(facts.method_facts),
            "sample_variants": self._records_list(facts.sample_variants),
            "test_conditions": self._records_list(facts.test_conditions),
            "baseline_references": self._records_list(facts.baseline_references),
            "measurement_results": self._records_list(facts.measurement_results),
            "characterization_observations": self._records_list(
                facts.characterization_observations
            ),
            "structure_features": self._records_list(facts.structure_features),
        }

    def _records_list(self, records: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not records:
            return []
        return [self._record_to_dict(record.to_record()) for record in records]

    def _build_collection_overview(
        self,
        collection_id: str,
        frames: _FactRows,
        projection: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        sample_variants = frames.get("sample_variants", [])
        measurement_results = frames.get("measurement_results", [])
        test_conditions = frames.get("test_conditions", [])
        evidence_anchors = frames.get("evidence_anchors", [])
        profiles = frames.get("document_profiles", [])
        real_variants = [
            row
            for row in sample_variants
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
                for prop in self._record_values(
                    measurement_results,
                    "property_normalized",
                )
                if prop
            }
        )
        condition_families = sorted(
            {
                axis["axis_name"]
                for condition in test_conditions
                if (
                    axis := self._condition_axis_from_payload(
                        condition.get("condition_payload")
                    )
                )
            }
        )
        comparable_group_count = 0
        if projection is not None:
            comparable_group_count = len(self._group_comparison_rows(projection))
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

    def _build_objective_collection_overview(
        self,
        collection_id: str,
        facts: CoreFactSet,
        rows: list[dict[str, Any]],
        projection: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        document_ids = {
            document_id
            for row in rows
            if (document_id := self._safe_text(row.get("document_id")))
        }
        sample_keys = {
            sample_key
            for row in rows
            if (sample_key := self._objective_sample_key(row))
        }
        process_variables = sorted(
            {
                key
                for row in rows
                for key, value in self._as_mapping(
                    row.get("process_context")
                ).items()
                if self._has_observed_value(value)
            }
        )
        measured_properties = sorted(
            {
                property_name
                for row in rows
                if (property_name := self._safe_text(row.get("property_normalized")))
            }
        )
        condition_families = sorted(
            {
                key
                for row in rows
                for condition in (
                    self._as_mapping(row.get("test_condition")),
                    self._as_mapping(row.get("resolved_condition")),
                )
                for key, value in condition.items()
                if self._has_observed_value(value)
            }
        )
        comparable_group_count = 0
        if projection is not None:
            comparable_group_count = len(self._group_comparison_rows(projection))
        return {
            "collection_id": collection_id,
            "document_count": len(document_ids) or len(facts.document_profiles),
            "sample_variant_count": len(sample_keys),
            "measurement_count": sum(
                1
                for row in rows
                if self._safe_text(row.get("unit_kind")) == "measurement"
            ),
            "condition_count": len(
                {
                    self._objective_condition_text(row)
                    for row in rows
                    if self._objective_condition_text(row)
                }
            ),
            "evidence_count": len(self._build_objective_evidence_refs(rows)),
            "comparable_group_count": comparable_group_count,
            "material_systems": sorted(
                {
                    label
                    for row in rows
                    if (label := self._objective_material_label_from_row(row))
                }
            ),
            "process_variables": process_variables,
            "measured_properties": measured_properties,
            "condition_families": condition_families,
        }

    def _build_objective_collection_paper_coverage(
        self,
        collection_id: str,
        facts: CoreFactSet,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        profiles = self._records_list(facts.document_profiles)
        coverage: list[dict[str, Any]] = []
        for document_id in sorted(
            {
                document_id
                for row in rows
                if (document_id := self._safe_text(row.get("document_id")))
            }
        ):
            document_rows = [
                row
                for row in rows
                if self._safe_text(row.get("document_id")) == document_id
            ]
            sample_count = len(
                {
                    sample_key
                    for row in document_rows
                    if (sample_key := self._objective_sample_key(row))
                }
            )
            process_keys = {
                key
                for row in document_rows
                for key, value in self._as_mapping(
                    row.get("process_context")
                ).items()
                if self._has_observed_value(value)
            }
            measurement_count = sum(
                1
                for row in document_rows
                if self._safe_text(row.get("unit_kind")) == "measurement"
            )
            condition_count = len(
                {
                    self._objective_condition_text(row)
                    for row in document_rows
                    if self._objective_condition_text(row)
                }
            )
            evidence_count = len(self._build_objective_evidence_refs(document_rows))
            warnings = self._coverage_warnings(
                document_id=document_id,
                sample_count=sample_count,
                measurement_count=measurement_count,
                evidence_count=evidence_count,
            )
            coverage.append(
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
        return coverage

    def _build_paper_coverage(
        self,
        collection_id: str,
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        profiles = frames.get("document_profiles", [])
        rows: list[dict[str, Any]] = []
        for document_id in sorted(self._document_ids_from_frames(frames)):
            document_frames = self._document_frames(frames, document_id)
            sample_count = sum(
                1
                for row in document_frames["sample_variants"]
                if self._is_real_sample_variant(row)
            )
            process_keys = {
                key
                for row in document_frames["sample_variants"]
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
        frames: _FactRows,
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
                frames.get("document_profiles", []),
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
        frames: _FactRows,
    ) -> dict[str, Any]:
        variants = frames.get("sample_variants", [])
        measurements = frames.get("measurement_results", [])
        variant_rows = [
            row
            for row in variants
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
                for row in measurements
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
        for record in measurements:
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
        variant_row: dict[str, Any],
        measurements: list[dict[str, Any]],
        frames: _FactRows,
        document_material_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        variant = dict(variant_row)
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

    def _is_real_sample_variant(self, variant_row: dict[str, Any]) -> bool:
        variant = dict(variant_row)
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
        material = self._material_from_variant(variant)
        material_text = (material or "").lower()
        if not label and not composition and not material:
            return False
        generic_candidates = {label} - {""}
        if self._canonical_material_label(composition):
            generic_candidates.add(composition)
        if self._canonical_material_label(material):
            generic_candidates.add(material_text)
        return not any(
            term in candidate
            for candidate in generic_candidates
            for term in _GENERIC_VARIANT_TERMS
        )

    def _measurement_cell_key(self, measurement_row: dict[str, Any]) -> tuple:
        measurement = dict(measurement_row)
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
        frames: _FactRows,
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
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        anchors = frames.get("evidence_anchors", [])
        anchor_lookup = {
            self._safe_text(row.get("anchor_id")): row
            for row in anchors
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
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        measurements = frames.get("measurement_results", [])
        conditions = frames.get("test_conditions", [])
        variants = frames.get("sample_variants", [])
        condition_lookup = {
            self._safe_text(row.get("test_condition_id")): row
            for row in conditions
            if self._safe_text(row.get("test_condition_id"))
        }
        variant_lookup = {
            self._safe_text(row.get("variant_id")): row
            for row in variants
            if self._safe_text(row.get("variant_id"))
        }
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for measurement in measurements:
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
        projection: list[dict[str, Any]] | None,
        frames: _FactRows,
        *,
        include_matrix: bool = True,
        material_key: str | None = None,
    ) -> list[dict[str, Any]]:
        if projection is None:
            return []
        groups: list[dict[str, Any]] = []
        for group_key, group_rows in self._group_comparison_rows(projection).items():
            rows = [dict(row) for row in group_rows]
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
        group_rows: list[dict[str, Any]],
        frames: _FactRows,
    ) -> dict[str, Any]:
        rows = []
        for record in group_rows:
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
                self._safe_text(group_rows[0].get(column)) or ""
                for column in (
                    "material_system_normalized",
                    "process_normalized",
                    "test_condition_normalized",
                    "baseline_normalized",
                    "variable_axis",
                )
            )
        ) if group_rows else "empty"
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
        frames: _FactRows,
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
        frames: _FactRows,
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
        frames: _FactRows,
    ) -> _FactRows:
        document_frames = self._document_frames(frames, document_id)
        material_key = self._material_key_from_material_id(
            material_id,
            document_frames,
            [],
        )
        if material_key is None:
            return {key: [] for key in document_frames}
        return self._filter_frames_for_material_key(material_key, document_frames)

    def _build_objective_material_summaries(
        self,
        collection_id: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for material_key, entry in sorted(
            self._build_objective_material_index(rows).items(),
            key=lambda item: item[1]["canonical_name"].lower(),
        ):
            material_rows = self._filter_objective_rows_for_material(material_key, rows)
            warnings = self._objective_material_warnings(entry)
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
                    "evidence_coverage": self._objective_evidence_coverage(
                        material_rows,
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

    def _build_objective_material_profile(
        self,
        collection_id: str,
        material_id: str,
        facts: CoreFactSet,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        index = self._build_objective_material_index(rows)
        material_key = self._objective_material_key_from_material_id(material_id, index)
        if material_key is None:
            return None
        entry = index[material_key]
        material_rows = self._filter_objective_rows_for_material(material_key, rows)
        sample_matrix = self._build_objective_sample_matrix(material_key, material_rows)
        measured_properties = self._build_objective_property_summaries(material_rows)
        process_ranges = self._build_objective_process_ranges(material_rows)
        papers = self._build_objective_paper_coverage(
            collection_id,
            material_key,
            facts,
            material_rows,
        )
        warnings = self._dedupe_warnings(
            [
                *self._objective_material_warnings(entry),
                *sample_matrix.get("warnings", []),
            ]
        )
        evidence_refs = self._build_objective_evidence_refs(material_rows)
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
                "comparison_count": len(entry["comparison_group_ids"]),
                "condition_series_count": 0,
                "evidence_coverage": self._objective_evidence_coverage(material_rows),
            },
            "papers": papers,
            "sample_matrix": sample_matrix,
            "process_parameter_ranges": process_ranges,
            "measured_properties": measured_properties,
            "comparison_groups": [],
            "condition_series": [],
            "evidence_refs": evidence_refs,
            "debug_links": {
                "all_comparisons": f"/api/v1/collections/{collection_id}/comparisons",
                "results": f"/api/v1/collections/{collection_id}/results",
                "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
            },
            "warnings": warnings,
        }

    def _build_objective_material_index(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            material_key = self._objective_material_key_from_row(row)
            if material_key is None:
                continue
            entry = self._ensure_material_entry(
                index,
                material_key,
                self._objective_material_label_from_row(row),
            )
            if document_id := self._safe_text(row.get("document_id")):
                entry["document_ids"].add(document_id)
            if sample_key := self._objective_sample_key(row):
                entry["variant_ids"].add(sample_key)
            if process := self._objective_process_family(row):
                entry["process_families"].add(process)
            if property_name := self._safe_text(row.get("property_normalized")):
                entry["measured_properties"].add(property_name)
            if self._safe_text(row.get("unit_kind")) == "comparison":
                entry["comparison_group_ids"].add(
                    self._safe_text(row.get("evidence_unit_id")) or ""
                )
        return index

    def _build_objective_sample_matrix(
        self,
        material_key: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if sample_key := self._objective_sample_key(row):
                grouped[sample_key].append(row)
        matrix_rows = [
            self._build_objective_sample_matrix_row(material_key, sample_key, records)
            for sample_key, records in sorted(grouped.items())
            if any(
                self._safe_text(record.get("unit_kind")) == "measurement"
                for record in records
            )
        ]
        process_keys = [
            key
            for key in _PROCESS_COLUMN_ORDER
            if any(
                self._has_observed_value(row.get("process_context", {}).get(key))
                for row in matrix_rows
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
            *[
                {
                    "column_id": key,
                    "label": key,
                    "role": "process",
                    "value_key": key,
                }
                for key in process_keys
            ],
            *self._sample_matrix_property_columns(matrix_rows),
        ]
        warnings: list[dict[str, Any]] = []
        if not matrix_rows:
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
            "state": "ready" if matrix_rows else "empty",
            "columns": columns,
            "rows": matrix_rows,
            "warnings": warnings,
        }

    def _build_objective_sample_matrix_row(
        self,
        material_key: str,
        sample_key: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        process_context: dict[str, Any] = {}
        test_condition: dict[str, Any] = {}
        for row in rows:
            self._merge_observed_context(
                process_context,
                self._objective_sample_process_context(row),
            )
            self._merge_observed_context(
                process_context,
                self._as_mapping(row.get("process_context")),
            )
            self._merge_observed_context(
                test_condition,
                self._as_mapping(row.get("test_condition")),
            )
            self._merge_observed_context(
                test_condition,
                self._objective_resolved_condition_context(row),
            )
        measurement_rows = [
            row
            for row in rows
            if self._safe_text(row.get("unit_kind")) == "measurement"
        ]
        grouped_measurements: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in measurement_rows:
            property_name = (
                self._safe_text(row.get("property_normalized")) or "measurement"
            )
            grouped_measurements[property_name].append(row)
        values = {
            property_name: {
                **self._objective_value_from_rows(records),
                "label": property_name,
                "condition": self._objective_condition_text(records[0]),
            }
            for property_name, records in sorted(grouped_measurements.items())
        }
        first = measurement_rows[0] if measurement_rows else rows[0]
        return {
            "row_id": f"sample-row:{sample_key}",
            "document_id": self._safe_text(first.get("document_id")),
            "sample_id": sample_key,
            "sample_label": self._objective_sample_label(first) or sample_key,
            "material": self._canonical_material_label(material_key) or material_key,
            "process_context": process_context,
            "test_condition": test_condition,
            "variable_axis": None,
            "variable_value": None,
            "values": values,
            "evidence_refs": self._build_objective_evidence_refs(rows),
            "warnings": [],
        }

    def _objective_sample_process_context(self, row: dict[str, Any]) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for key, value in self._as_mapping(row.get("sample_context")).items():
            if self._sample_context_key(key) not in _SAMPLE_CONTEXT_PROCESS_KEYS:
                continue
            if self._has_observed_value(value):
                context[str(key)] = self._clean_value(value)
        return context

    def _objective_resolved_condition_context(
        self,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for key, value in self._as_mapping(row.get("resolved_condition")).items():
            normalized = self._sample_context_key(key)
            if normalized.endswith(" id") or normalized.endswith("_id"):
                continue
            if self._has_observed_value(value):
                context[str(key)] = self._clean_value(value)
        return context

    def _merge_observed_context(
        self,
        target: dict[str, Any],
        source: dict[str, Any],
    ) -> None:
        for key, value in source.items():
            if not self._has_observed_value(value):
                continue
            target.setdefault(str(key), self._clean_value(value))

    def _objective_value_from_rows(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        values = [self._objective_value_from_row(row) for row in rows]
        unique_value_keys = {
            (
                value.get("value"),
                self._safe_text(value.get("unit")),
                self._safe_text(value.get("display_value")),
            )
            for value in values
        }
        conflicted = len(unique_value_keys) > 1
        first_value = values[0]
        fact_ids = [
            self._safe_text(row.get("evidence_unit_id")) or ""
            for row in rows
            if self._safe_text(row.get("evidence_unit_id"))
        ]
        merged = {
            **first_value,
            "evidence_refs": self._build_objective_evidence_refs(rows),
            "duplicate_count": max(0, len(rows) - 1),
            "warnings": [],
        }
        if conflicted:
            merged.update(
                {
                    "display_value": "; ".join(
                        value["display_value"] for value in values
                    ),
                    "value": None,
                    "unit": None,
                    "normalized_value": None,
                    "normalized_unit": None,
                    "status": "conflicted",
                    "conflict_status": "conflicted",
                    "warnings": [
                        self._warning(
                            code="conflicting_objective_measurement_values",
                            severity="warning",
                            scope="value",
                            message=(
                                "Multiple distinct objective evidence values "
                                "were found for this matrix cell."
                            ),
                            related_object_ids=fact_ids,
                        )
                    ],
                }
            )
        elif len(rows) > 1:
            merged["conflict_status"] = "duplicate_only"
            merged["warnings"] = [
                self._warning(
                    code="duplicate_objective_measurements_collapsed",
                    severity="info",
                    scope="value",
                    message=(
                        "Duplicate objective evidence values were collapsed "
                        "in this cell."
                    ),
                    related_object_ids=fact_ids,
                )
            ]
        return merged

    def _build_objective_property_summaries(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if self._safe_text(row.get("unit_kind")) != "measurement":
                continue
            property_name = self._safe_text(row.get("property_normalized"))
            if property_name:
                grouped[property_name].append(row)
        summaries: list[dict[str, Any]] = []
        for property_name, records in sorted(grouped.items()):
            units = {
                self._safe_text(row.get("unit")) or ""
                for row in records
                if self._safe_text(row.get("unit"))
            }
            unit = next(iter(units)) if len(units) == 1 else None
            values = []
            for row in records:
                value = self._objective_value_from_row(row)
                values.append(value.get("value") or value.get("display_value"))
            summaries.append(
                {
                    "property": property_name,
                    **self._range_summary(values, unit),
                    "sample_count": len(
                        {
                            sample_key
                            for row in records
                            if (sample_key := self._objective_sample_key(row))
                        }
                    ),
                    "document_count": len(
                        {
                            self._safe_text(row.get("document_id")) or ""
                            for row in records
                            if self._safe_text(row.get("document_id"))
                        }
                    ),
                    "evidence_refs": self._build_objective_evidence_refs(records),
                    "warnings": [],
                }
            )
        return summaries

    def _build_objective_process_ranges(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[tuple[dict[str, Any], Any]]] = defaultdict(list)
        for row in rows:
            for key, value in self._as_mapping(row.get("process_context")).items():
                if self._has_observed_value(value):
                    grouped[key].append((row, value))
        ranges: list[dict[str, Any]] = []
        for parameter, records in sorted(grouped.items()):
            source_rows = [row for row, _ in records]
            ranges.append(
                {
                    "parameter": parameter,
                    **self._range_summary(
                        [value for _, value in records],
                        self._process_parameter_unit(parameter),
                    ),
                    "sample_count": len(
                        {
                            sample_key
                            for row in source_rows
                            if (sample_key := self._objective_sample_key(row))
                        }
                    ),
                    "document_count": len(
                        {
                            self._safe_text(row.get("document_id")) or ""
                            for row in source_rows
                            if self._safe_text(row.get("document_id"))
                        }
                    ),
                    "evidence_refs": self._build_objective_evidence_refs(source_rows),
                    "warnings": [],
                }
            )
        return ranges

    def _build_objective_paper_coverage(
        self,
        collection_id: str,
        material_key: str,
        facts: CoreFactSet,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        profiles = self._records_list(facts.document_profiles)
        material_id = self._material_id_from_key(material_key)
        coverage: list[dict[str, Any]] = []
        for document_id in sorted(
            {
                self._safe_text(row.get("document_id")) or ""
                for row in rows
                if self._safe_text(row.get("document_id"))
            }
        ):
            document_rows = [
                row
                for row in rows
                if self._safe_text(row.get("document_id")) == document_id
            ]
            sample_count = len(
                {
                    sample_key
                    for row in document_rows
                    if (sample_key := self._objective_sample_key(row))
                }
            )
            measurement_count = sum(
                1
                for row in document_rows
                if self._safe_text(row.get("unit_kind")) == "measurement"
            )
            evidence_count = len(self._build_objective_evidence_refs(document_rows))
            warnings = self._coverage_warnings(
                document_id=document_id,
                sample_count=sample_count,
                measurement_count=measurement_count,
                evidence_count=evidence_count,
            )
            coverage.append(
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
                    "process_families": sorted(
                        {
                            process
                            for row in document_rows
                            if (process := self._objective_process_family(row))
                        }
                    ),
                    "measured_properties": sorted(
                        {
                            self._safe_text(row.get("property_normalized")) or ""
                            for row in document_rows
                            if self._safe_text(row.get("property_normalized"))
                        }
                    ),
                    "evidence_count": evidence_count,
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
        return coverage

    def _objective_material_key_from_material_id(
        self,
        material_id: str,
        index: dict[str, dict[str, Any]],
    ) -> str | None:
        requested = self._safe_text(material_id)
        if requested is None:
            return None
        for material_key, entry in index.items():
            if requested in {material_key, entry["material_id"]}:
                return material_key
        return None

    def _filter_objective_rows_for_material(
        self,
        material_key: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if self._objective_material_key_from_row(row) == material_key
        ]

    def _objective_material_key_from_row(self, row: dict[str, Any]) -> str | None:
        return self._material_key_from_label(self._objective_material_label_from_row(row))

    def _objective_material_label_from_row(self, row: dict[str, Any]) -> str | None:
        for mapping in (
            self._as_mapping(row.get("material_system")),
            self._as_mapping(row.get("sample_context")),
        ):
            for key in (
                "name",
                "material",
                "material_system",
                "host_material_system",
                "family",
                "composition",
                "alloy",
            ):
                if label := self._safe_text(mapping.get(key)):
                    return label
        return None

    def _objective_sample_key(self, row: dict[str, Any]) -> str | None:
        label = self._objective_sample_label(row)
        if not label:
            return None
        document_id = self._safe_text(row.get("document_id")) or "document"
        return f"{document_id}:{self._slug(label)}"

    def _objective_sample_label(self, row: dict[str, Any]) -> str | None:
        sample_context = self._as_mapping(row.get("sample_context"))
        for key in _SAMPLE_CONTEXT_DIRECT_KEYS:
            if label := self._informative_sample_label(sample_context.get(key)):
                return label
        normalized_context = {
            self._sample_context_key(key): value
            for key, value in sample_context.items()
        }
        for key in _SAMPLE_CONTEXT_SECONDARY_KEYS:
            if label := self._informative_sample_label(normalized_context.get(key)):
                return label
        for key, value in sample_context.items():
            if self._sample_context_key(key) in _SAMPLE_CONTEXT_EXCLUDED_KEYS:
                continue
            if label := self._informative_sample_label(value):
                return label
        return None

    def _sample_context_key(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value).strip().lower().replace("_", " "))

    def _informative_sample_label(self, value: Any) -> str | None:
        label = self._safe_text(value)
        if label is None:
            return None
        if self._looks_like_material_only_sample_label(label):
            return None
        if label.lower() in _GENERIC_VARIANT_TERMS:
            return None
        return label

    def _looks_like_material_only_sample_label(self, label: str) -> bool:
        lowered = label.lower()
        compact = re.sub(r"[^a-z0-9]", "", lowered)
        return (
            "stainlesssteel" in compact
            or compact in {"316l", "ss316l", "aisi316l", "ti6al4v", "ti64"}
            or compact in {"material", "materials"}
            or "materialsystem" in compact
        )

    def _objective_process_family(self, row: dict[str, Any]) -> str | None:
        process_context = self._as_mapping(row.get("process_context"))
        for key in (
            "process_normalized",
            "process_family",
            "process",
            "manufacturing_process",
            "process_name",
            "post_treatment_summary",
        ):
            if process := self._safe_text(process_context.get(key)):
                return process
        return None

    def _objective_condition_text(self, row: dict[str, Any]) -> str | None:
        for mapping in (
            self._as_mapping(row.get("test_condition")),
            self._as_mapping(row.get("resolved_condition")),
        ):
            values = [
                f"{key}: {value}"
                for key, value in mapping.items()
                if self._has_observed_value(value)
            ]
            if values:
                return "; ".join(values)
        return None

    def _objective_value_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        value_payload = self._as_mapping(row.get("value_payload"))
        numeric_value = self._numeric_value(value_payload)
        unit = (
            self._safe_text(row.get("unit"))
            or self._safe_text(value_payload.get("source_unit_text"))
            or self._safe_text(value_payload.get("unit"))
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
            "normalized_value": numeric_value,
            "normalized_unit": unit,
            "status": "observed" if numeric_value is not None or source_value else "missing",
            "confidence": self._numeric_or_none(row.get("confidence")),
            "evidence_refs": self._build_objective_evidence_refs([row]),
            "duplicate_count": 0,
            "conflict_status": "none",
            "warnings": [],
        }

    def _build_objective_evidence_refs(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            fact_id = self._safe_text(row.get("evidence_unit_id")) or ""
            anchor_ids = self._dedupe_strings(
                self._as_list(row.get("evidence_anchor_ids"))
            )
            source_refs = self._as_list(row.get("source_refs")) or [{}]
            for index, source_ref_value in enumerate(source_refs):
                source_ref = self._as_mapping(source_ref_value)
                source_id = (
                    self._safe_text(source_ref.get("route_id"))
                    or self._safe_text(source_ref.get("source_ref"))
                    or str(index)
                )
                evidence_ref_id = f"eref:{fact_id}:{self._slug(source_id)}"
                if evidence_ref_id in seen:
                    continue
                seen.add(evidence_ref_id)
                refs.append(
                    {
                        "evidence_ref_id": evidence_ref_id,
                        "fact_ids": [fact_id] if fact_id else [],
                        "anchor_ids": anchor_ids,
                        "source_kind": self._safe_text(source_ref.get("source_kind"))
                        or self._safe_text(source_ref.get("kind"))
                        or "objective_unit",
                        "document_id": self._safe_text(row.get("document_id")),
                        "locator": {
                            key: self._clean_value(value)
                            for key, value in source_ref.items()
                            if key
                            not in {
                                "route_id",
                                "source_kind",
                                "kind",
                                "confidence",
                            }
                            and self._has_observed_value(value)
                        },
                        "confidence": self._numeric_or_none(
                            source_ref.get("confidence")
                        )
                        or self._numeric_or_none(row.get("confidence")),
                        "traceability_status": (
                            "direct" if source_ref or anchor_ids else "missing_anchor"
                        ),
                    }
                )
        return refs

    def _objective_evidence_coverage(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total = int(len(rows))
        with_evidence = sum(
            1
            for row in rows
            if self._as_list(row.get("source_refs"))
            or self._as_list(row.get("evidence_anchor_ids"))
        )
        return {
            "observed_count": total,
            "with_evidence_count": with_evidence,
            "coverage": round(with_evidence / total, 3) if total else None,
        }

    def _objective_material_warnings(
        self,
        entry: dict[str, Any],
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if not entry["variant_ids"]:
            warnings.append(
                self._warning(
                    code="material_without_sample_bindings",
                    severity="warning",
                    scope="material",
                    message="No objective sample context is bound to this material yet.",
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

    def _build_material_summaries(
        self,
        collection_id: str,
        frames: _FactRows,
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
        frames: _FactRows,
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
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        profiles = frames.get("document_profiles", [])
        rows: list[dict[str, Any]] = []
        for document_id in sorted(self._document_ids_from_frames(frames)):
            document_frames = self._document_frames(frames, document_id)
            variants = document_frames.get("sample_variants", [])
            measurements = document_frames.get("measurement_results", [])
            evidence_anchors = document_frames.get("evidence_anchors", [])
            sample_count = sum(
                1 for row in variants if self._is_real_sample_variant(row)
            )
            if sample_count == 0 and not measurements:
                continue
            properties = sorted(
                {
                    self._safe_text(row.get("property_normalized")) or ""
                    for row in measurements
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
                            for row in variants
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
        frames: _FactRows,
        document_material_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        variants = frames.get("sample_variants", [])
        measurements = frames.get("measurement_results", [])
        material_document_keys = document_material_keys or {
            document_id: material_key
            for document_id in self._document_ids_from_frames(frames)
        }
        variant_rows = [
            row
            for row in variants
            if self._material_key_from_variant(row, material_document_keys) == material_key
            and self._is_real_sample_variant(row)
        ]
        measurements_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in measurements:
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
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        variants = frames.get("sample_variants", [])
        grouped: dict[str, list[tuple[dict[str, Any], Any]]] = defaultdict(list)
        for variant in variants:
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
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        measurements = frames.get("measurement_results", [])
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for measurement in measurements:
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
        frames: _FactRows,
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
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        variants = frames.get("sample_variants", [])
        conditions: list[dict[str, Any]] = []
        for variant in variants:
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
        frames: _FactRows,
    ) -> list[dict[str, Any]]:
        conditions = frames.get("test_conditions", [])
        rows: list[dict[str, Any]] = []
        for condition in conditions:
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
        frames: _FactRows,
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
        frames: _FactRows,
        comparable_groups: list[dict[str, Any]],
    ) -> dict[str, str]:
        candidates: dict[str, set[str]] = defaultdict(set)
        profiles = frames.get("document_profiles", [])
        for document_id in self._document_ids_from_frames(frames):
            candidates[document_id].update(
                self._material_keys_from_document_profile(profiles, document_id)
            )

        variants = frames.get("sample_variants", [])
        for variant in variants:
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
        profiles: list[dict[str, Any]],
        document_id: str,
    ) -> set[str]:
        profile = self._first_record_by_value(profiles, "document_id", document_id)
        if profile is None:
            return set()
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
        frames: _FactRows,
        comparable_groups: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        variant_to_key: dict[str, str] = {}
        document_material_keys = self._single_material_key_by_document(
            frames,
            comparable_groups,
        )
        variants = frames.get("sample_variants", [])
        for variant in variants:
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

        measurements = frames.get("measurement_results", [])
        for measurement in measurements:
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
        frames: _FactRows,
        document_material_keys: dict[str, str] | None = None,
    ) -> _FactRows:
        material_keys_by_document = document_material_keys or (
            self._single_material_key_by_document(frames, [])
        )
        variants = frames.get("sample_variants", [])
        selected_variants = [
            variant
            for variant in variants
            if self._material_key_from_variant(
                variant,
                material_keys_by_document,
            )
            == material_key
            and self._is_real_sample_variant(variant)
        ]
        variant_ids = {
            self._safe_text(row.get("variant_id")) or ""
            for row in selected_variants
            if self._safe_text(row.get("variant_id"))
        }

        measurements = frames.get("measurement_results", [])
        selected_measurements = [
            measurement
            for measurement in measurements
            if self._safe_text(measurement.get("variant_id")) in variant_ids
        ]

        condition_ids = {
            self._safe_text(row.get("test_condition_id")) or ""
            for row in selected_measurements
            if self._safe_text(row.get("test_condition_id"))
        }
        test_conditions = frames.get("test_conditions", [])
        selected_conditions = [
            condition
            for condition in test_conditions
            if self._safe_text(condition.get("test_condition_id")) in condition_ids
        ]

        selected = {
            key: []
            for key in frames
            if key not in {"sample_variants", "measurement_results", "test_conditions"}
        }
        selected["sample_variants"] = selected_variants
        selected["measurement_results"] = selected_measurements
        selected["test_conditions"] = selected_conditions
        selected["document_profiles"] = frames.get("document_profiles", [])

        anchor_ids = self._anchor_ids_from_material_frames(selected)
        selected["evidence_anchors"] = self._filter_evidence_anchors(
            frames.get("evidence_anchors", []),
            anchor_ids,
        )
        return selected

    def _filter_evidence_anchors(
        self,
        anchors: list[dict[str, Any]],
        anchor_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not anchors:
            return []
        wanted = set(self._dedupe_strings(anchor_ids))
        return [
            anchor
            for anchor in anchors
            if self._safe_text(anchor.get("anchor_id")) in wanted
        ]

    def _material_key_from_variant(
        self,
        variant_row: dict[str, Any],
        document_material_keys: dict[str, str] | None = None,
    ) -> str | None:
        variant = dict(variant_row)
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
        row: dict[str, Any],
    ) -> str | None:
        record = dict(row)
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
        compact = re.sub(r"[^a-z0-9]", "", lowered)
        if compact in _NON_MATERIAL_SYSTEM_COMPACT_LABELS:
            return None
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
        frames: _FactRows,
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
        variant_row: dict[str, Any],
    ) -> str | None:
        variant = dict(variant_row)
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
        frames: _FactRows,
    ) -> dict[str, Any]:
        measurements = frames.get("measurement_results", [])
        if measurements:
            total = int(len(measurements))
            with_evidence = sum(
                1
                for row in measurements
                if self._as_list(row.get("evidence_anchor_ids"))
            )
        else:
            variants = frames.get("sample_variants", [])
            total = int(len(variants))
            with_evidence = sum(
                1
                for row in variants
                if self._as_list(row.get("source_anchor_ids"))
            )
        coverage = round(with_evidence / total, 3) if total else None
        return {
            "observed_count": total,
            "with_evidence_count": with_evidence,
            "coverage": coverage,
        }

    def _anchor_ids_from_material_frames(
        self,
        frames: _FactRows,
    ) -> list[str]:
        anchor_ids: list[str] = []
        for row in frames.get("sample_variants", []):
            anchor_ids.extend(self._as_list(row.get("source_anchor_ids")))
        for row in frames.get("measurement_results", []):
            anchor_ids.extend(self._as_list(row.get("evidence_anchor_ids")))
        for row in frames.get("test_conditions", []):
            anchor_ids.extend(self._as_list(row.get("evidence_anchor_ids")))
        return self._dedupe_strings(anchor_ids)

    def _fact_ids_from_material_frames(
        self,
        frames: _FactRows,
    ) -> list[str]:
        return self._dedupe_strings(
            [
                self._safe_text(row.get("variant_id")) or ""
                for row in frames.get("sample_variants", [])
            ]
            + [
                self._safe_text(row.get("result_id")) or ""
                for row in frames.get("measurement_results", [])
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
        frames: _FactRows,
        sample_matrix: dict[str, Any],
    ) -> dict[str, Any]:
        sample_variants = frames.get("sample_variants", [])
        measurements = frames.get("measurement_results", [])
        test_conditions = frames.get("test_conditions", [])
        real_variants = [
            row
            for row in sample_variants
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
                    for row in measurements
                    if self._safe_text(row.get("property_normalized"))
                }
            ),
            "condition_families": sorted(
                {
                    axis["axis_name"]
                    for row in test_conditions
                    if (
                        axis := self._condition_axis_from_payload(
                            row.get("condition_payload")
                        )
                    )
                }
            ),
            "warning_count": len(sample_matrix.get("warnings", [])),
        }

    def _document_frames(
        self,
        frames: _FactRows,
        document_id: str,
    ) -> _FactRows:
        return {
            key: self._filter_records_by_document(records, document_id)
            for key, records in frames.items()
            if key != "document_profiles"
        } | {"document_profiles": frames.get("document_profiles", [])}

    def _filter_records_by_document(
        self,
        records: list[dict[str, Any]],
        document_id: str,
    ) -> list[dict[str, Any]]:
        return [
            record
            for record in records
            if self._safe_text(record.get("document_id")) == document_id
        ]

    def _document_ids_from_frames(self, frames: _FactRows) -> set[str]:
        document_ids: set[str] = set()
        for records in frames.values():
            for record in records:
                if document_id := self._safe_text(record.get("document_id")):
                    document_ids.add(document_id)
        return document_ids

    def _document_title(
        self,
        profiles: list[dict[str, Any]],
        document_id: str,
    ) -> str | None:
        profile = self._first_record_by_value(profiles, "document_id", document_id)
        if profile is None:
            return None
        return self._safe_text(profile.get("title"))

    def _document_source_filename(
        self,
        profiles: list[dict[str, Any]],
        document_id: str,
    ) -> str | None:
        row = self._first_record_by_value(profiles, "document_id", document_id)
        if row is None:
            return None
        for key in ("source_filename", "filename", "source_file"):
            if source_filename := self._safe_text(row.get(key)):
                return source_filename
        return None

    def _document_count(
        self,
        frames: _FactRows,
        profiles: list[dict[str, Any]],
    ) -> int:
        if profiles:
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
        frames: _FactRows,
    ) -> tuple[str, str]:
        property_name, condition_id = self._measurement_cell_key(measurement)
        condition = self._row_by_id(
            frames.get("test_conditions", []),
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
        records: list[dict[str, Any]],
        id_column: str,
        value: str | None,
    ) -> dict[str, Any] | None:
        if not value:
            return None
        return self._first_record_by_value(records, id_column, value)

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
        frames: _FactRows,
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
        rows: list[dict[str, Any]],
    ) -> _ComparisonGroups:
        if not rows:
            return {}
        grouped: _ComparisonGroups = defaultdict(list)
        for row in rows:
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
            grouped[key].append(row)
        return dict(grouped)

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

    def _record_values(self, records: list[dict[str, Any]], column: str) -> list[str]:
        return [
            text
            for record in records
            if (text := self._safe_text(record.get(column)))
        ]

    def _first_record_by_value(
        self,
        records: list[dict[str, Any]],
        column: str,
        value: str,
    ) -> dict[str, Any] | None:
        for record in records:
            if self._safe_text(record.get(column)) == value:
                return record
        return None

    def _record_to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
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
        for key in ("value", "numeric_value", "normalized_value", "source_value_numeric"):
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
