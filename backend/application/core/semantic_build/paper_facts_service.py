from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
import os
import re
from time import perf_counter
from typing import Any, Mapping
from urllib.parse import urlencode
from uuid import uuid4

from .document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from .llm.schemas import (
    BaselineReferencePayload,
    ConditionContextPayload,
    EvidenceAnchorPayload,
    ExtractedTestConditionPayload,
    MeasurementResultPayload,
    MeasurementValuePayload,
    MethodFactPayload,
    ProcessContextPayload,
    SampleVariantPayload,
    StructuredExtractionBundle,
    StructuredTableBatchRowMentions,
    StructuredTextWindowMentions,
    TestConditionPayloadModel,
    TestContextPayload,
)
from .llm.extractor import (
    CoreLLMStructuredExtractor,
    build_default_core_llm_structured_extractor,
)
from application.source.artifact_input_service import (
    build_document_records,
    load_blocks_artifact,
    load_collection_inputs,
    load_tables_artifact,
    load_table_rows_artifact,
    load_table_cells_artifact,
)
from application.source.collection_service import CollectionService
from domain.core.evidence_backbone import (
    BaselineReference,
    CORE_NEUTRAL_DOMAIN_PROFILE,
    CharacterizationObservation,
    EvidenceAnchor,
    MethodFact,
    MeasurementResult,
    SampleVariant,
    StructureFeature,
    TestCondition,
)
from domain.core.document_profile import DocumentProfile
from domain.core.fact_store import CoreFactSet
from domain.core.research_objective import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
)
from domain.ports import CoreFactRepository, SourceArtifactRepository
from domain.shared.enums import (
    DOC_TYPE_REVIEW,
    EPISTEMIC_DIRECTLY_OBSERVED,
    EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    TRACEABILITY_STATUS_DIRECT,
    TRACEABILITY_STATUS_MISSING,
    TRACEABILITY_STATUS_PARTIAL,
)
from domain.shared.record_normalization import normalize_record_value
from infra.persistence.factory import (
    build_core_fact_repository,
)

logger = logging.getLogger(__name__)


_DEFAULT_MAX_EXTRACTION_CONCURRENCY = 4
_MAX_SUPPORTING_TEXT_WINDOWS = 3
_MAX_TABLE_ROW_SUPPORTING_TEXT_CHARS = 1200
_MAX_TABLE_CONTEXT_CHARS = 6000
_TABLE_ROWS_PER_EXTRACTION_BATCH = 5
_MAX_WHOLE_TABLE_EXTRACTION_ROWS = 40
_MAX_FULL_TABLE_CONTEXT_ROWS = 40
_TABLE_CONTEXT_LEADING_ROWS = 5
_TABLE_CONTEXT_TRAILING_ROWS = 3
_MAX_TEXT_WINDOWS_PER_DOCUMENT = 24
_INTRODUCTION_WINDOW_LIMIT = 1
_PAPER_FACT_TEXT_ROUTE_ROLES = {
    "current_experimental_evidence",
    "test_condition",
    "characterization",
}
_CHARACTERIZATION_COLUMNS = [
    "observation_id",
    "document_id",
    "collection_id",
    "variant_id",
    "characterization_type",
    "observation_text",
    "observed_value",
    "observed_unit",
    "condition_context",
    "evidence_anchor_ids",
    "confidence",
    "epistemic_status",
]
_STRUCTURE_FEATURE_COLUMNS = [
    "feature_id",
    "document_id",
    "collection_id",
    "variant_id",
    "feature_type",
    "feature_value",
    "feature_unit",
    "qualitative_descriptor",
    "source_observation_ids",
    "confidence",
    "epistemic_status",
]
_EVIDENCE_ANCHOR_COLUMNS = [
    "anchor_id",
    "document_id",
    "locator_type",
    "locator_confidence",
    "source_type",
    "section_id",
    "char_range",
    "bbox",
    "page",
    "quote",
    "deep_link",
    "block_id",
    "snippet_id",
    "figure_or_table",
    "quote_span",
]
_METHOD_FACT_COLUMNS = [
    "method_id",
    "document_id",
    "collection_id",
    "domain_profile",
    "method_role",
    "method_name",
    "method_payload",
    "evidence_anchor_ids",
    "confidence",
    "epistemic_status",
]
_TEST_CONDITION_COLUMNS = [
    "test_condition_id",
    "document_id",
    "collection_id",
    "domain_profile",
    "property_type",
    "template_type",
    "scope_level",
    "condition_payload",
    "condition_completeness",
    "missing_fields",
    "evidence_anchor_ids",
    "confidence",
    "epistemic_status",
]
_BASELINE_REFERENCE_COLUMNS = [
    "baseline_id",
    "document_id",
    "collection_id",
    "domain_profile",
    "variant_id",
    "baseline_type",
    "baseline_label",
    "baseline_scope",
    "evidence_anchor_ids",
    "confidence",
    "epistemic_status",
]
_SAMPLE_VARIANT_COLUMNS = [
    "variant_id",
    "document_id",
    "collection_id",
    "domain_profile",
    "variant_label",
    "host_material_system",
    "composition",
    "variable_axis_type",
    "variable_value",
    "process_context",
    "profile_payload",
    "structure_feature_ids",
    "source_anchor_ids",
    "confidence",
    "epistemic_status",
]
_MEASUREMENT_RESULT_COLUMNS = [
    "result_id",
    "document_id",
    "collection_id",
    "domain_profile",
    "variant_id",
    "property_normalized",
    "result_type",
    "claim_scope",
    "value_payload",
    "unit",
    "test_condition_id",
    "baseline_id",
    "structure_feature_ids",
    "characterization_observation_ids",
    "evidence_anchor_ids",
    "traceability_status",
    "result_source_type",
    "epistemic_status",
]
_EVIDENCE_SOURCE_TYPES = {"figure", "table", "method", "text"}
_CHARACTERIZATION_METHODS = (
    "XRD",
    "SEM",
    "TEM",
    "XPS",
    "Raman",
    "FTIR",
    "DSC",
    "TGA",
    "DMA",
)
_NULL_LIKE_SCALAR_TEXTS = {"null", "none", "n/a", "na", "nan"}
_PROPERTY_HINTS = (
    ("yield strength", "yield_strength"),
    ("tensile strength", "tensile_strength"),
    ("flexural strength", "flexural_strength"),
    ("residual stress", "residual_stress"),
    ("fatigue life", "fatigue_life"),
    ("fatigue", "fatigue_life"),
    ("elongation", "elongation"),
    ("retention", "retention"),
    ("modulus", "modulus"),
    ("hardness", "hardness"),
    ("conductivity", "conductivity"),
    ("stability", "stability"),
    ("porosity", "porosity"),
    ("density", "density"),
    ("strength", "strength"),
)
_PBF_PROCESS_PAYLOAD_KEYS = (
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
_TENSILE_TEST_PROPERTIES = frozenset(
    {"yield_strength", "tensile_strength", "strength", "elongation", "modulus"}
)
_MICROHARDNESS_TEST_PROPERTIES = frozenset({"hardness", "microhardness"})
_CHARACTERIZATION_TEST_PROPERTIES = frozenset(
    {
        "density",
        "relative_density",
        "porosity",
        "grain_size",
        "microstructure",
        "grain_size_primary_dendrite_spacing",
    }
)
_METHOD_FAMILY_PROPERTY_TYPES = (
    "tensile_mechanics",
    "microhardness",
    "density_porosity_microstructure",
)
_GENERIC_TEXT_VARIANT_TERMS = (
    "alloy",
    "material",
    "powder",
    "process",
    "sample",
    "samples",
    "scan strategy",
    "scanning strategy",
    "strategies",
    "stainless steel",
)
_STATISTIC_MEASUREMENT_TERMS = (
    "standard deviation",
    "std deviation",
    "std. deviation",
    "std dev",
)
_OBSERVED_VALUE_PATTERN = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*(nm|um|μm|mm|cm|m2/g|m\^2/g|m²/g|mpa|gpa|pa|%)\b",
    re.IGNORECASE,
)
_PHASE_PATTERN = re.compile(
    r"\b(alpha|beta|gamma|martensite|martensitic|austenite|ferrite|alpha-phase|beta-phase)\b",
    re.IGNORECASE,
)
_GRAIN_SIZE_PATTERN = re.compile(
    r"(?:grain size|grain diameter|prior-β grain size|alpha-lath size|alpha lath size)[^\d]{0,20}"
    r"([-+]?\d+(?:\.\d+)?)\s*(nm|um|μm|mm)\b",
    re.IGNORECASE,
)
_THICKNESS_PATTERN = re.compile(
    r"(?:thickness|film thickness|layer thickness)[^\d]{0,20}"
    r"([-+]?\d+(?:\.\d+)?)\s*(nm|um|μm|mm)\b",
    re.IGNORECASE,
)
_SURFACE_AREA_PATTERN = re.compile(
    r"(?:surface area|specific surface area)[^\d]{0,20}"
    r"([-+]?\d+(?:\.\d+)?)\s*(m2/g|m\^2/g|m²/g)\b",
    re.IGNORECASE,
)
_MORPHOLOGY_KEYWORDS = (
    "equiaxed",
    "columnar",
    "dendritic",
    "lamellar",
    "spherical",
    "melt pool",
)
_LOW_VALUE_HEADING_TERMS = (
    "reference",
    "acknowledg",
    "funding",
    "author contribution",
    "conflict of interest",
    "declaration",
    "supplementary",
    "appendix",
)
_INTRODUCTION_HEADING_TERMS = (
    "introduction",
    "background",
    "related work",
    "literature review",
)
_METHOD_HEADING_TERMS = (
    "materials and methods",
    "experimental",
    "method",
    "sample preparation",
    "fabrication",
    "processing",
)
_CHARACTERIZATION_HEADING_TERMS = (
    "characterization",
    "measurement",
    "testing",
    "analysis",
)
_RESULT_HEADING_TERMS = (
    "result",
    "discussion",
    "conclusion",
)
_PROCESS_SIGNAL_TERMS = (
    "anneal",
    "annealed",
    "as-built",
    "as built",
    "build orientation",
    "fabricated",
    "hatch spacing",
    "heat treated",
    "laser power",
    "layer thickness",
    "mixed",
    "oxygen",
    "powder",
    "process condition",
    "process conditions",
    "preheat",
    "scan speed",
    "scan strategy",
    "shielding gas",
    "stirred",
)
_COMPARISON_SIGNAL_TERMS = (
    "baseline",
    "control",
    "density",
    "elongation",
    "hardness",
    "porosity",
    "relative density",
    "residual stress",
    "roughness",
    "strength",
    "tensile",
    "yield",
)
_EXTRACTION_UNIT_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:w|kw|mm/s|mm s-1|mpa|gpa|pa|hv|ra|ppm|%|j/mm3|j/mm\^3|um|μm|mm|c|°c)\b",
    re.IGNORECASE,
)


class PaperFactsNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve paper facts."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"paper facts not ready: {collection_id}")


class EvidenceCardNotFoundError(FileNotFoundError):
    """Raised when one evidence card is missing from a collection."""

    def __init__(self, collection_id: str, evidence_id: str) -> None:
        self.collection_id = collection_id
        self.evidence_id = evidence_id
        super().__init__(f"evidence card not found: {collection_id}/{evidence_id}")


class PaperFactsService:
    """Generate and serve collection-scoped paper facts and evidence views."""

    def __init__(
        self,
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        document_profile_service: DocumentProfileService | None = None,
        structured_extractor: CoreLLMStructuredExtractor | None = None,
        core_fact_repository: CoreFactRepository | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            core_fact_repository=core_fact_repository,
            source_artifact_repository=source_artifact_repository,
        )
        self._structured_extractor = structured_extractor
        self.core_fact_repository = (
            core_fact_repository
            or build_core_fact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.source_artifact_repository = source_artifact_repository

    def _get_structured_extractor(self) -> CoreLLMStructuredExtractor:
        if self._structured_extractor is None:
            self._structured_extractor = build_default_core_llm_structured_extractor()
        return self._structured_extractor

    def _get_max_extraction_concurrency(self) -> int:
        raw_value = os.getenv("CORE_EXTRACTION_MAX_CONCURRENCY", "").strip()
        if not raw_value:
            return _DEFAULT_MAX_EXTRACTION_CONCURRENCY
        try:
            parsed = int(raw_value)
        except ValueError:
            logger.warning(
                "Invalid CORE_EXTRACTION_MAX_CONCURRENCY=%s; using default=%s",
                raw_value,
                _DEFAULT_MAX_EXTRACTION_CONCURRENCY,
            )
            return _DEFAULT_MAX_EXTRACTION_CONCURRENCY
        if parsed < 1:
            logger.warning(
                "Non-positive CORE_EXTRACTION_MAX_CONCURRENCY=%s; using default=%s",
                raw_value,
                _DEFAULT_MAX_EXTRACTION_CONCURRENCY,
            )
            return _DEFAULT_MAX_EXTRACTION_CONCURRENCY
        return parsed

    def list_evidence_cards(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        cards = self.read_evidence_cards(collection_id)
        items = [
            self._serialize_card_row(row)
            for row in cards[offset : offset + limit]
        ]
        return {
            "collection_id": collection_id,
            "total": len(cards),
            "count": len(items),
            "items": items,
        }

    def get_evidence_card(
        self,
        collection_id: str,
        evidence_id: str,
    ) -> dict[str, Any]:
        cards = self.read_evidence_cards(collection_id)
        matched = next(
            (
                row
                for row in cards
                if str(row.get("evidence_id") or "") == str(evidence_id)
            ),
            None,
        )
        if matched is None:
            raise EvidenceCardNotFoundError(collection_id, evidence_id)
        return self._serialize_card_row(matched)

    def get_evidence_traceback(
        self,
        collection_id: str,
        evidence_id: str,
    ) -> dict[str, Any]:
        cards = self.read_evidence_cards(collection_id)
        row = next(
            (
                card
                for card in cards
                if str(card.get("evidence_id") or "") == str(evidence_id)
            ),
            None,
        )
        if row is None:
            raise EvidenceCardNotFoundError(collection_id, evidence_id)

        document_id = str(row.get("document_id") or "").strip()
        if not document_id:
            return {
                "collection_id": collection_id,
                "evidence_id": evidence_id,
                "traceback_status": "unavailable",
                "anchors": [],
            }

        content = self.document_profile_service.get_document_content(
            collection_id,
            document_id,
        )
        _, text_units = load_collection_inputs(
            collection_id,
            self.source_artifact_repository,
        )
        text_unit_lookup = self._build_text_unit_lookup(text_units, document_id)

        anchors = self._normalize_evidence_anchors_payload(
            row.get("evidence_anchors"),
            collection_id=collection_id,
            document_id=document_id,
            evidence_id=evidence_id,
        )
        resolved_anchors = [
            resolved
            for anchor in anchors
            if (resolved := self._resolve_traceback_anchor(anchor, content, text_unit_lookup))
            is not None
        ]
        traceback_status = self._derive_traceback_status(resolved_anchors)
        if traceback_status == "unavailable":
            resolved_anchors = []

        return {
            "collection_id": collection_id,
            "evidence_id": evidence_id,
            "traceback_status": traceback_status,
            "anchors": resolved_anchors,
        }

    def read_evidence_cards(self, collection_id: str) -> tuple[dict[str, Any], ...]:
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        cards = self._objective_evidence_cards_from_facts(collection_id, facts)
        if cards:
            return cards
        records = self.read_paper_fact_records(collection_id)
        return self._normalize_card_records(
            self._legacy_evidence_cards_from_records(collection_id, records),
            collection_id,
        )

    def read_paper_fact_records(
        self,
        collection_id: str,
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        return self._load_paper_fact_records(collection_id)

    def build_paper_facts(
        self,
        collection_id: str,
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        self.collection_service.get_collection(collection_id)
        try:
            profiles = self.document_profile_service.read_document_profiles(collection_id)
        except DocumentProfilesNotReadyError as exc:
            raise PaperFactsNotReadyError(collection_id) from exc

        objective_facts = self.core_fact_repository.read_collection_facts(collection_id)
        objective_contexts = (
            objective_facts.objective_contexts
            if objective_facts.research_objectives_ready
            else ()
        )
        objective_route_gate = self._build_objective_route_gate(
            objective_facts.objective_evidence_routes
        )
        try:
            documents, text_units = load_collection_inputs(
                collection_id,
                self.source_artifact_repository,
            )
            blocks = load_blocks_artifact(
                collection_id,
                self.source_artifact_repository,
            )
            tables = load_tables_artifact(
                collection_id,
                self.source_artifact_repository,
            )
            table_rows = load_table_rows_artifact(
                collection_id,
                self.source_artifact_repository,
            )
            table_cells = load_table_cells_artifact(
                collection_id,
                self.source_artifact_repository,
            )
        except FileNotFoundError as exc:
            raise PaperFactsNotReadyError(collection_id) from exc

        document_records = build_document_records(documents, text_units)
        all_text_windows_by_doc = self._build_text_windows_by_document(blocks)
        tables_by_doc = self._group_tables_by_document(tables)
        table_rows_by_doc = self._group_table_rows_by_document(table_rows)
        table_cells_by_doc = self._group_table_cells_by_document(table_cells)
        profile_by_doc = {
            profile.document_id: profile.to_record()
            for profile in profiles
        }
        total_documents = len(document_records)
        total_extraction_units = 0
        selected_text_windows_by_doc: dict[str, list[dict[str, Any]]] = {}
        selected_table_rows_by_doc: dict[str, list[dict[str, Any]]] = {}
        selected_table_row_batches_by_doc: dict[str, list[list[dict[str, Any]]]] = {}
        for candidate_row in document_records:
            candidate_document_id = str(candidate_row.get("paper_id") or "")
            candidate_profile = profile_by_doc.get(candidate_document_id)
            if not candidate_profile:
                continue
            candidate_text_windows = all_text_windows_by_doc.get(candidate_document_id, [])
            candidate_table_rows = table_rows_by_doc.get(candidate_document_id, [])
            grouped_row_cells = self._group_table_cells_by_row(
                table_cells_by_doc.get(candidate_document_id, [])
            )
            if objective_route_gate is None:
                selected_text_windows = self._select_text_windows_for_extraction(
                    text_windows=candidate_text_windows,
                    profile=candidate_profile,
                    has_table_rows=bool(candidate_table_rows),
                )
            else:
                selected_text_windows = self._select_route_gated_text_windows(
                    text_windows=candidate_text_windows,
                    document_id=candidate_document_id,
                    route_gate=objective_route_gate,
                )
            if str(candidate_profile.get("doc_type") or "") == DOC_TYPE_REVIEW:
                selected_table_rows: list[dict[str, Any]] = []
            elif objective_route_gate is None:
                selected_table_rows = self._select_table_rows_for_extraction(
                    table_rows=candidate_table_rows,
                    grouped_row_cells=grouped_row_cells,
                )
            else:
                selected_table_rows = self._select_route_gated_table_rows(
                    table_rows=candidate_table_rows,
                    document_id=candidate_document_id,
                    grouped_row_cells=grouped_row_cells,
                    route_gate=objective_route_gate,
                )
            selected_table_row_batches = self._batch_table_rows_for_extraction(
                selected_table_rows
            )
            selected_text_windows_by_doc[candidate_document_id] = selected_text_windows
            selected_table_rows_by_doc[candidate_document_id] = selected_table_rows
            selected_table_row_batches_by_doc[candidate_document_id] = (
                selected_table_row_batches
            )
            total_extraction_units += len(selected_text_windows) + len(selected_table_row_batches)
        completed_extraction_units = 0
        logger.info(
            "Paper facts extraction started collection_id=%s document_count=%s block_count=%s table_count=%s table_row_count=%s table_cell_count=%s total_extraction_units=%s",
            collection_id,
            total_documents,
            len(blocks),
            len(tables),
            len(table_rows),
            len(table_cells),
            total_extraction_units,
        )
        if not table_cells:
            logger.warning(
                "Paper facts extraction found empty table_cells collection_id=%s",
                collection_id,
            )

        evidence_anchor_rows: list[dict[str, Any]] = []
        method_fact_rows: list[dict[str, Any]] = []
        sample_variant_rows: list[dict[str, Any]] = []
        test_condition_rows: list[dict[str, Any]] = []
        baseline_rows: list[dict[str, Any]] = []
        measurement_rows: list[dict[str, Any]] = []

        extractor = self._get_structured_extractor()
        max_extraction_concurrency = self._get_max_extraction_concurrency()
        logger.info(
            "Paper facts extraction concurrency collection_id=%s max_extraction_concurrency=%s",
            collection_id,
            max_extraction_concurrency,
        )
        if objective_contexts:
            logger.info(
                "Paper facts objective contexts loaded collection_id=%s objective_context_count=%s",
                collection_id,
                len(objective_contexts),
            )
        if objective_route_gate is not None:
            text_route_count = sum(
                len(document_gate["text_windows"])
                for document_gate in objective_route_gate.values()
            )
            table_route_count = sum(
                len(document_gate["tables"])
                for document_gate in objective_route_gate.values()
            )
            logger.info(
                "Paper facts objective route gate loaded collection_id=%s document_count=%s text_window_routes=%s table_routes=%s",
                collection_id,
                len(objective_route_gate),
                text_route_count,
                table_route_count,
            )

        for document_position, row in enumerate(document_records, start=1):
            document_id = str(row.get("paper_id") or "")
            profile = profile_by_doc.get(document_id)
            if not profile:
                continue

            title = (
                self._normalize_scalar_text(profile.get("title"))
                or self._normalize_scalar_text(row.get("title"))
                or document_id
            )
            source_filename = self._normalize_scalar_text(profile.get("source_filename"))
            all_doc_text_windows = all_text_windows_by_doc.get(document_id, [])
            doc_text_windows = selected_text_windows_by_doc.get(document_id, [])
            raw_doc_table_rows = table_rows_by_doc.get(document_id, [])
            doc_table_rows = selected_table_rows_by_doc.get(document_id, [])
            doc_table_row_batches = selected_table_row_batches_by_doc.get(document_id, [])
            doc_tables_by_id = self._group_tables_by_id(tables_by_doc.get(document_id, []))
            grouped_row_cells = self._group_table_cells_by_row(table_cells_by_doc.get(document_id, []))
            document_state = self._build_document_state()
            document_total_units = len(doc_text_windows) + len(doc_table_row_batches)
            document_completed_units = 0
            logger.info(
                "Paper facts extraction document started collection_id=%s document_id=%s document_position=%s document_count=%s remaining_documents=%s text_window_count=%s raw_text_window_count=%s table_batch_count=%s table_row_count=%s raw_table_row_count=%s doc_type=%s completed_units=%s total_units=%s remaining_units=%s document_total_units=%s",
                collection_id,
                document_id,
                document_position,
                total_documents,
                total_documents - document_position,
                len(doc_text_windows),
                len(all_doc_text_windows),
                len(doc_table_row_batches),
                len(doc_table_rows),
                len(raw_doc_table_rows),
                profile.get("doc_type"),
                completed_extraction_units,
                total_extraction_units,
                max(total_extraction_units - completed_extraction_units, 0),
                document_total_units,
            )

            doc_anchor_start = len(evidence_anchor_rows)
            doc_method_start = len(method_fact_rows)
            doc_variant_start = len(sample_variant_rows)
            doc_condition_start = len(test_condition_rows)
            doc_baseline_start = len(baseline_rows)
            doc_measurement_start = len(measurement_rows)
            text_window_jobs = [
                {
                    "text_window": text_window,
                    "payload": self._build_text_window_extraction_payload(
                        title=title,
                        source_filename=source_filename,
                        profile=profile,
                        text_window=text_window,
                        objective_context=self._select_text_window_objective_context(
                            objective_contexts,
                            text_window=text_window,
                        ),
                    ),
                }
                for text_window in doc_text_windows
            ]
            for text_window_position, job in enumerate(text_window_jobs, start=1):
                text_window = job["text_window"]
                window_id = self._normalize_scalar_text(text_window.get("window_id")) or ""
                heading_path = self._normalize_scalar_text(text_window.get("heading_path"))
                block_type = self._normalize_scalar_text(text_window.get("block_type"))
                text_chars = len(str(text_window.get("text") or ""))
                logger.info(
                    "Paper facts text-window extraction started collection_id=%s document_id=%s document_position=%s document_count=%s window_position=%s window_count=%s window_id=%s block_type=%s chars=%s heading_path=%s completed_units=%s total_units=%s remaining_units=%s document_completed_units=%s document_total_units=%s document_remaining_units=%s",
                    collection_id,
                    document_id,
                    document_position,
                    total_documents,
                    text_window_position,
                    len(doc_text_windows),
                    window_id,
                    block_type,
                    text_chars,
                    heading_path,
                    completed_extraction_units,
                    total_extraction_units,
                    max(total_extraction_units - completed_extraction_units, 0),
                    document_completed_units,
                    document_total_units,
                    max(document_total_units - document_completed_units, 0),
                )
            text_window_results = self._execute_extraction_jobs(
                extractor=extractor,
                jobs=text_window_jobs,
                kind="text_window",
                max_extraction_concurrency=max_extraction_concurrency,
            )
            for text_window_position, (job, result) in enumerate(
                zip(text_window_jobs, text_window_results, strict=False),
                start=1,
            ):
                text_window = job["text_window"]
                window_id = self._normalize_scalar_text(text_window.get("window_id")) or ""
                if result["error"] is not None:
                    logger.error(
                        "Paper facts text-window extraction failed collection_id=%s document_id=%s window_position=%s window_count=%s window_id=%s elapsed_s=%.3f elapsed_ms=%s",
                        collection_id,
                        document_id,
                        text_window_position,
                        len(doc_text_windows),
                        window_id,
                        result["elapsed_s"],
                        round(result["elapsed_s"] * 1000),
                    )
                    raise result["error"]
                mentions = result["parsed"]
                bundle = self._bind_text_window_mentions_to_bundle(
                    mentions=mentions,
                    text_window=text_window,
                )
                text_window_elapsed_s = result["elapsed_s"]
                text_window_elapsed_ms = round(text_window_elapsed_s * 1000)
                self._materialize_bundle(
                    bundle=bundle,
                    collection_id=collection_id,
                    document_id=document_id,
                    text_window=text_window,
                    table_id=None,
                    row_index=None,
                    evidence_anchor_rows=evidence_anchor_rows,
                    method_fact_rows=method_fact_rows,
                    sample_variant_rows=sample_variant_rows,
                    test_condition_rows=test_condition_rows,
                    baseline_rows=baseline_rows,
                    measurement_rows=measurement_rows,
                    document_state=document_state,
                )
                completed_extraction_units += 1
                document_completed_units += 1
                logger.info(
                    "Paper facts text-window extraction finished collection_id=%s document_id=%s document_position=%s document_count=%s window_position=%s window_count=%s window_id=%s elapsed_s=%.3f elapsed_ms=%s method_facts=%s sample_variants=%s test_conditions=%s baselines=%s measurements=%s completed_units=%s total_units=%s remaining_units=%s document_completed_units=%s document_total_units=%s document_remaining_units=%s",
                    collection_id,
                    document_id,
                    document_position,
                    total_documents,
                    text_window_position,
                    len(doc_text_windows),
                    window_id,
                    text_window_elapsed_s,
                    text_window_elapsed_ms,
                    len(bundle.method_facts),
                    len(bundle.sample_variants),
                    len(bundle.test_conditions),
                    len(bundle.baseline_references),
                    len(bundle.measurement_results),
                    completed_extraction_units,
                    total_extraction_units,
                    max(total_extraction_units - completed_extraction_units, 0),
                    document_completed_units,
                    document_total_units,
                    max(document_total_units - document_completed_units, 0),
                )

            table_batch_jobs = []
            for batch_rows in doc_table_row_batches:
                if not batch_rows:
                    continue
                first_row = batch_rows[0]
                table_id = str(first_row.get("table_id") or "")
                table_context = doc_tables_by_id.get(table_id)
                row_cells_by_index = {
                    self._safe_int(row.get("row_index")): grouped_row_cells.get(
                        (table_id, self._safe_int(row.get("row_index"))),
                        [],
                    )
                    for row in batch_rows
                }
                objective_context, objective_table_route = (
                    self._select_table_batch_objective_context(
                        objective_contexts,
                        document_id=document_id,
                        table_id=table_id,
                        table_context=table_context,
                        table_rows=batch_rows,
                        row_cells_by_index=row_cells_by_index,
                    )
                )
                table_batch_jobs.append(
                    {
                        "rows": batch_rows,
                        "row_cells_by_index": row_cells_by_index,
                        "table_id": table_id,
                        "table_context": table_context,
                        "payload": self._build_table_batch_extraction_payload(
                            title=title,
                            source_filename=source_filename,
                            profile=profile,
                            table_context=table_context,
                            table_rows=batch_rows,
                            row_cells_by_index=row_cells_by_index,
                            text_windows=all_doc_text_windows,
                            objective_context=objective_context,
                            objective_table_route=objective_table_route,
                        ),
                    }
                )
            for table_batch_position, job in enumerate(table_batch_jobs, start=1):
                rows = job["rows"]
                table_id = job["table_id"]
                row_indices = [
                    self._safe_int(row.get("row_index"))
                    for row in rows
                ]
                cell_count = sum(
                    len(job["row_cells_by_index"].get(row_index, []))
                    for row_index in row_indices
                )
                logger.info(
                    "Paper facts table-batch extraction started collection_id=%s document_id=%s document_position=%s document_count=%s batch_position=%s table_batch_count=%s table_id=%s row_indices=%s row_count=%s cell_count=%s completed_units=%s total_units=%s remaining_units=%s document_completed_units=%s document_total_units=%s document_remaining_units=%s",
                    collection_id,
                    document_id,
                    document_position,
                    total_documents,
                    table_batch_position,
                    len(table_batch_jobs),
                    table_id,
                    row_indices,
                    len(rows),
                    cell_count,
                    completed_extraction_units,
                    total_extraction_units,
                    max(total_extraction_units - completed_extraction_units, 0),
                    document_completed_units,
                    document_total_units,
                    max(document_total_units - document_completed_units, 0),
                )
            table_batch_results = self._execute_extraction_jobs(
                extractor=extractor,
                jobs=table_batch_jobs,
                kind="table_batch",
                max_extraction_concurrency=max_extraction_concurrency,
            )
            for table_batch_position, (job, result) in enumerate(
                zip(table_batch_jobs, table_batch_results, strict=False),
                start=1,
            ):
                rows = job["rows"]
                table_id = job["table_id"]
                row_by_index = {
                    self._safe_int(row.get("row_index")): row
                    for row in rows
                }
                row_indices = list(row_by_index)
                if result["error"] is not None:
                    logger.error(
                        "Paper facts table-batch extraction failed collection_id=%s document_id=%s batch_position=%s table_batch_count=%s table_id=%s row_indices=%s elapsed_s=%.3f elapsed_ms=%s",
                        collection_id,
                        document_id,
                        table_batch_position,
                        len(table_batch_jobs),
                        table_id,
                        row_indices,
                        result["elapsed_s"],
                        round(result["elapsed_s"] * 1000),
                    )
                    raise result["error"]
                mentions = result["parsed"]
                table_batch_elapsed_s = result["elapsed_s"]
                table_batch_elapsed_ms = round(table_batch_elapsed_s * 1000)
                batch_method_count = 0
                batch_variant_count = 0
                batch_condition_count = 0
                batch_baseline_count = 0
                batch_measurement_count = 0
                for row_mentions in mentions.row_results:
                    row_index = self._safe_int(row_mentions.row_index)
                    row = row_by_index.get(row_index)
                    if row is None:
                        logger.warning(
                            "Paper facts table-batch extraction returned unknown row_index collection_id=%s document_id=%s table_id=%s row_index=%s target_row_indices=%s",
                            collection_id,
                            document_id,
                            table_id,
                            row_index,
                            row_indices,
                        )
                        continue
                    row_cells = job["row_cells_by_index"].get(row_index, [])
                    bundle = self._bind_table_row_mentions_to_bundle(
                        mentions=row_mentions,
                        table_row=row,
                        row_cells=row_cells,
                        table_context=job["table_context"],
                    )
                    self._materialize_bundle(
                        bundle=bundle,
                        collection_id=collection_id,
                        document_id=document_id,
                        text_window=None,
                        table_id=table_id,
                        row_index=row_index,
                        evidence_anchor_rows=evidence_anchor_rows,
                        method_fact_rows=method_fact_rows,
                        sample_variant_rows=sample_variant_rows,
                        test_condition_rows=test_condition_rows,
                        baseline_rows=baseline_rows,
                        measurement_rows=measurement_rows,
                        document_state=document_state,
                    )
                    batch_method_count += len(bundle.method_facts)
                    batch_variant_count += len(bundle.sample_variants)
                    batch_condition_count += len(bundle.test_conditions)
                    batch_baseline_count += len(bundle.baseline_references)
                    batch_measurement_count += len(bundle.measurement_results)
                completed_extraction_units += 1
                document_completed_units += 1
                logger.info(
                    "Paper facts table-batch extraction finished collection_id=%s document_id=%s document_position=%s document_count=%s batch_position=%s table_batch_count=%s table_id=%s row_indices=%s rows_returned=%s elapsed_s=%.3f elapsed_ms=%s method_facts=%s sample_variants=%s test_conditions=%s baselines=%s measurements=%s completed_units=%s total_units=%s remaining_units=%s document_completed_units=%s document_total_units=%s document_remaining_units=%s",
                    collection_id,
                    document_id,
                    document_position,
                    total_documents,
                    table_batch_position,
                    len(table_batch_jobs),
                    table_id,
                    row_indices,
                    len(mentions.row_results),
                    table_batch_elapsed_s,
                    table_batch_elapsed_ms,
                    batch_method_count,
                    batch_variant_count,
                    batch_condition_count,
                    batch_baseline_count,
                    batch_measurement_count,
                    completed_extraction_units,
                    total_extraction_units,
                    max(total_extraction_units - completed_extraction_units, 0),
                    document_completed_units,
                    document_total_units,
                    max(document_total_units - document_completed_units, 0),
                )

            doc_method_family_condition_start = len(test_condition_rows)
            self._materialize_document_method_family_test_conditions(
                collection_id=collection_id,
                document_id=document_id,
                text_windows=all_doc_text_windows,
                evidence_anchor_rows=evidence_anchor_rows,
                test_condition_rows=test_condition_rows,
                document_state=document_state,
            )
            doc_method_family_condition_count = (
                len(test_condition_rows) - doc_method_family_condition_start
            )
            logger.info(
                "Paper facts extraction document finished collection_id=%s document_id=%s document_position=%s document_count=%s remaining_documents=%s evidence_anchors=%s method_facts=%s sample_variants=%s test_conditions=%s method_family_test_conditions=%s baselines=%s measurements=%s completed_units=%s total_units=%s remaining_units=%s",
                collection_id,
                document_id,
                document_position,
                total_documents,
                total_documents - document_position,
                len(evidence_anchor_rows) - doc_anchor_start,
                len(method_fact_rows) - doc_method_start,
                len(sample_variant_rows) - doc_variant_start,
                len(test_condition_rows) - doc_condition_start,
                doc_method_family_condition_count,
                len(baseline_rows) - doc_baseline_start,
                len(measurement_rows) - doc_measurement_start,
                completed_extraction_units,
                total_extraction_units,
                max(total_extraction_units - completed_extraction_units, 0),
            )

        evidence_anchors = self._normalize_evidence_anchor_records(
            evidence_anchor_rows,
        )
        method_facts = self._normalize_method_fact_records(
            method_fact_rows,
            collection_id,
        )
        sample_variants = self._normalize_sample_variant_records(
            sample_variant_rows,
            collection_id,
        )
        sample_variants, removed_variant_ids = self._filter_generic_text_sample_variants(
            sample_variants
        )
        test_conditions = self._normalize_test_condition_records(
            test_condition_rows,
            collection_id,
        )
        test_conditions = self._filter_superseded_local_test_conditions(
            test_conditions
        )
        baseline_references = self._normalize_baseline_reference_records(
            baseline_rows,
            collection_id,
        )
        measurement_results = self._normalize_measurement_result_records(
            measurement_rows,
            collection_id,
        )
        measurement_results = self._clear_removed_variant_ids_from_measurements(
            measurement_results,
            removed_variant_ids,
        )
        measurement_results = self._attach_document_test_condition_ids_to_measurements(
            measurement_results=measurement_results,
            test_conditions=test_conditions,
        )
        if method_facts and not measurement_results:
            logger.warning(
                "Paper facts extraction produced zero measurement_results collection_id=%s method_fact_count=%s raw_measurement_count=%s",
                collection_id,
                len(method_facts),
                len(measurement_rows),
            )

        characterization = self._build_characterization_observations(
            collection_id=collection_id,
            method_facts=method_facts,
            evidence_anchors=evidence_anchors,
            text_windows_by_doc=all_text_windows_by_doc,
            sample_variants=sample_variants,
            measurement_results=measurement_results,
        )
        characterization = self._attach_variant_ids_to_characterization(
            characterization,
            sample_variants,
        )
        structure_features = self._build_structure_features(characterization)
        sample_variants = self._attach_structure_feature_ids_to_variants(
            sample_variants,
            structure_features,
        )
        baseline_references = self._attach_variant_ids_to_baseline_references(
            baseline_references,
            sample_variants,
        )
        measurement_results = self._attach_context_to_measurement_results(
            measurement_results=measurement_results,
            characterization=characterization,
            structure_features=structure_features,
        )
        measurement_results = self._deduplicate_measurement_result_records(
            measurement_results
        )
        self.core_fact_repository.replace_collection_facts(
            collection_id,
            self._build_core_fact_set(
                document_profiles=profiles,
                evidence_anchors=evidence_anchors,
                method_facts=method_facts,
                sample_variants=sample_variants,
                test_conditions=test_conditions,
                baseline_references=baseline_references,
                measurement_results=measurement_results,
                characterization=characterization,
                structure_features=structure_features,
            ),
        )
        objective_evidence_units = (
            self.core_fact_repository.read_collection_facts(
                collection_id
            ).objective_evidence_units
        )

        logger.info(
            "Paper facts extraction finished collection_id=%s evidence_anchors=%s method_facts=%s sample_variants=%s test_conditions=%s baselines=%s measurement_results=%s characterization_observations=%s structure_features=%s objective_evidence_units=%s",
            collection_id,
            len(evidence_anchors),
            len(method_facts),
            len(sample_variants),
            len(test_conditions),
            len(baseline_references),
            len(measurement_results),
            len(characterization),
            len(structure_features),
            len(objective_evidence_units),
        )
        return {
            "evidence_anchors": evidence_anchors,
            "method_facts": method_facts,
            "sample_variants": sample_variants,
            "test_conditions": test_conditions,
            "baseline_references": baseline_references,
            "measurement_results": measurement_results,
            "characterization_observations": characterization,
            "structure_features": structure_features,
            "objective_evidence_units": tuple(
                unit.to_record() for unit in objective_evidence_units
            ),
        }

    def build_evidence_cards(
        self,
        collection_id: str,
    ) -> tuple[dict[str, Any], ...]:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        cards_table = self._objective_evidence_cards_from_facts(collection_id, facts)
        if cards_table:
            logger.info(
                "Objective evidence view derivation finished collection_id=%s evidence_cards=%s",
                collection_id,
                len(cards_table),
            )
            return cards_table
        if not self._paper_fact_records_available(facts):
            self.build_paper_facts(collection_id)
        records = self._load_paper_fact_records(collection_id)
        cards_table = self._legacy_evidence_cards_from_records(collection_id, records)
        logger.info(
            "Evidence view derivation finished collection_id=%s evidence_cards=%s",
            collection_id,
            len(cards_table),
        )
        return cards_table

    def _objective_evidence_cards_from_facts(
        self,
        collection_id: str,
        facts: CoreFactSet,
    ) -> tuple[dict[str, Any], ...]:
        if not facts.objective_evidence_units:
            return ()
        return self._derive_objective_evidence_card_records(
            collection_id=collection_id,
            objective_evidence_units=facts.objective_evidence_units,
        )

    def _legacy_evidence_cards_from_records(
        self,
        collection_id: str,
        records: dict[str, tuple[dict[str, Any], ...]],
    ) -> tuple[dict[str, Any], ...]:
        return self._derive_evidence_card_records(
            collection_id=collection_id,
            evidence_anchors=records["evidence_anchors"],
            method_facts=records["method_facts"],
            sample_variants=records["sample_variants"],
            test_conditions=records["test_conditions"],
            baseline_references=records["baseline_references"],
            measurement_results=records["measurement_results"],
        )

    def _derive_objective_evidence_card_records(
        self,
        *,
        collection_id: str,
        objective_evidence_units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for unit in objective_evidence_units:
            if unit.resolution_status in {"rejected", "skipped"}:
                continue
            claim_text = self._objective_evidence_claim_text(unit)
            if not claim_text:
                continue
            rows.append(
                {
                    "evidence_id": f"ev_objective_{unit.evidence_unit_id}",
                    "document_id": unit.document_id,
                    "collection_id": collection_id,
                    "claim_text": claim_text,
                    "claim_type": self._objective_evidence_claim_type(unit),
                    "evidence_source_type": self._objective_evidence_source_type(unit),
                    "evidence_anchors": self._objective_evidence_anchor_payloads(
                        unit
                    ),
                    "material_system": self._normalize_material_system_payload(
                        self._objective_material_system_payload(unit.material_system)
                    ),
                    "condition_context": self._objective_condition_context(unit),
                    "confidence": unit.confidence,
                    "traceability_status": self._objective_traceability_status(unit),
                }
            )
        return self._normalize_card_records(rows, collection_id)

    def _objective_evidence_claim_text(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> str:
        interpretation = self._normalize_scalar_text(unit.interpretation)
        if interpretation:
            return interpretation
        sample_label = self._objective_sample_label(unit.sample_context)
        property_name = self._normalize_scalar_text(unit.property_normalized)
        value = self._objective_value_summary(unit.value_payload, unit.unit)
        if unit.unit_kind in {"measurement", "comparison"}:
            subject = sample_label or "sample"
            if value and property_name:
                return f"{subject} reported {property_name} of {value}."
            if property_name:
                return f"{subject} reported {property_name}."
        if unit.unit_kind == "process_context":
            process = self._objective_mapping_summary(unit.process_context)
            subject = sample_label or "sample"
            return f"{subject} used {process or 'the reported process context'}."
        if unit.unit_kind == "test_condition":
            condition = self._objective_mapping_summary(
                unit.test_condition or unit.resolved_condition
            )
            return f"Testing used {condition or 'the reported condition'}."
        return self._objective_mapping_summary(unit.value_payload) or (
            f"Objective evidence unit {unit.evidence_unit_id} was reported."
        )

    def _objective_evidence_claim_type(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> str:
        if unit.unit_kind in {"measurement", "comparison"}:
            return "property"
        if unit.unit_kind == "process_context":
            return "process"
        if unit.unit_kind == "test_condition":
            return "test"
        return "qualitative"

    def _objective_evidence_source_type(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> str:
        for source_ref in unit.source_refs:
            source_kind = self._normalize_scalar_text(source_ref.get("source_kind"))
            if source_kind in _EVIDENCE_SOURCE_TYPES:
                return source_kind
            if source_kind == "text_window":
                return "text"
        return "text"

    def _objective_evidence_anchor_payloads(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> list[dict[str, Any]]:
        anchors: list[dict[str, Any]] = []
        source_refs = list(unit.source_refs)
        anchor_ids = list(unit.evidence_anchor_ids)
        if not source_refs and anchor_ids:
            source_refs = [{"source_kind": "text", "source_ref": None}]
        for index, source_ref in enumerate(source_refs):
            source_kind = self._normalize_scalar_text(source_ref.get("source_kind"))
            source_ref_id = self._normalize_scalar_text(source_ref.get("source_ref"))
            source_type = (
                source_kind
                if source_kind in _EVIDENCE_SOURCE_TYPES
                else "text"
            )
            anchor_id = (
                anchor_ids[index]
                if index < len(anchor_ids)
                else f"anchor_{unit.evidence_unit_id}_{index + 1}"
            )
            anchor = {
                "anchor_id": anchor_id,
                "document_id": unit.document_id,
                "source_type": source_type,
                "section_id": source_ref_id,
                "page": source_ref.get("page"),
            }
            if source_kind == "text_window":
                anchor["block_id"] = source_ref_id
            elif source_kind == "table":
                anchor["figure_or_table"] = source_ref_id
            anchors.append(anchor)
        return anchors

    def _objective_condition_context(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, Any]:
        condition = unit.test_condition or unit.resolved_condition
        return self._normalize_condition_context_payload(
            {
                "process": unit.process_context,
                "baseline": {
                    "control": self._objective_mapping_summary(
                        unit.baseline_context
                    ),
                },
                "test": {
                    "method": self._normalize_scalar_text(condition.get("method")),
                    "methods": [
                        value
                        for value in (
                            self._normalize_scalar_text(value)
                            for value in condition.values()
                        )
                        if value
                    ],
                },
            }
        )

    def _objective_material_system_payload(
        self,
        material_system: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = dict(material_system)
        if "family" not in payload:
            payload["family"] = (
                self._normalize_scalar_text(payload.get("name"))
                or self._normalize_scalar_text(payload.get("material_system"))
                or self._normalize_scalar_text(payload.get("material"))
            )
        return payload

    def _objective_traceability_status(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> str:
        if unit.evidence_anchor_ids:
            return TRACEABILITY_STATUS_DIRECT
        if unit.source_refs:
            return TRACEABILITY_STATUS_PARTIAL
        return TRACEABILITY_STATUS_MISSING

    def _objective_sample_label(
        self,
        sample_context: Mapping[str, Any],
    ) -> str | None:
        for key in (
            "sample",
            "sample_label",
            "variant_label",
            "sample_name",
            "specimen",
            "condition",
            "sample_id",
        ):
            if value := self._normalize_scalar_text(sample_context.get(key)):
                return value
        return None

    def _objective_value_summary(
        self,
        value_payload: Mapping[str, Any],
        unit: str | None,
    ) -> str | None:
        display = self._normalize_scalar_text(value_payload.get("source_value_text"))
        if not display:
            value = value_payload.get("value")
            display = self._normalize_scalar_text(value)
        if display and unit and unit not in display:
            return f"{display} {unit}"
        return display

    def _objective_mapping_summary(
        self,
        payload: Mapping[str, Any],
    ) -> str | None:
        parts = [
            f"{key}: {value}"
            for key, value in payload.items()
            if self._normalize_scalar_text(value)
        ]
        return "; ".join(parts) if parts else None

    def _load_paper_fact_records(
        self,
        collection_id: str,
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if not self._paper_fact_records_available(facts):
            raise PaperFactsNotReadyError(collection_id)

        return {
            "evidence_anchors": self._records_to_records(
                facts.evidence_anchors,
                _EVIDENCE_ANCHOR_COLUMNS,
            ),
            "method_facts": self._records_to_records(
                facts.method_facts,
                _METHOD_FACT_COLUMNS,
            ),
            "sample_variants": self._records_to_records(
                facts.sample_variants,
                _SAMPLE_VARIANT_COLUMNS,
            ),
            "test_conditions": self._records_to_records(
                facts.test_conditions,
                _TEST_CONDITION_COLUMNS,
            ),
            "baseline_references": self._records_to_records(
                facts.baseline_references,
                _BASELINE_REFERENCE_COLUMNS,
            ),
            "measurement_results": self._records_to_records(
                facts.measurement_results,
                _MEASUREMENT_RESULT_COLUMNS,
            ),
            "characterization_observations": self._records_to_records(
                facts.characterization_observations,
                _CHARACTERIZATION_COLUMNS,
            ),
            "structure_features": self._records_to_records(
                facts.structure_features,
                _STRUCTURE_FEATURE_COLUMNS,
            ),
        }

    def _paper_fact_records_available(self, facts: CoreFactSet) -> bool:
        return bool(
            facts.paper_facts_ready
            or facts.evidence_anchors
            or facts.method_facts
            or facts.sample_variants
            or facts.test_conditions
            or facts.baseline_references
            or facts.measurement_results
            or facts.characterization_observations
            or facts.structure_features
        )

    def _load_objective_contexts(
        self,
        collection_id: str,
    ) -> tuple[ObjectiveContext, ...]:
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if not facts.research_objectives_ready:
            return ()
        return facts.objective_contexts

    def _records_to_records(
        self,
        records: tuple[Any, ...],
        columns: list[str],
    ) -> tuple[dict[str, Any], ...]:
        if not records:
            return ()
        return tuple(
            {column: payload.get(column) for column in columns}
            for record in records
            for payload in (record.to_record(),)
        )

    def _build_core_fact_set(
        self,
        *,
        document_profiles: tuple[DocumentProfile, ...],
        evidence_anchors: tuple[dict[str, Any], ...],
        method_facts: tuple[dict[str, Any], ...],
        sample_variants: tuple[dict[str, Any], ...],
        test_conditions: tuple[dict[str, Any], ...],
        baseline_references: tuple[dict[str, Any], ...],
        measurement_results: tuple[dict[str, Any], ...],
        characterization: tuple[dict[str, Any], ...],
        structure_features: tuple[dict[str, Any], ...],
    ) -> CoreFactSet:
        return CoreFactSet(
            document_profiles=document_profiles,
            evidence_anchors=self._domain_records_from_records(
                evidence_anchors,
                EvidenceAnchor,
            ),
            method_facts=self._domain_records_from_records(method_facts, MethodFact),
            sample_variants=self._domain_records_from_records(sample_variants, SampleVariant),
            test_conditions=self._domain_records_from_records(test_conditions, TestCondition),
            baseline_references=self._domain_records_from_records(
                baseline_references,
                BaselineReference,
            ),
            measurement_results=self._domain_records_from_records(
                measurement_results,
                MeasurementResult,
            ),
            characterization_observations=self._domain_records_from_records(
                characterization,
                CharacterizationObservation,
            ),
            structure_features=self._domain_records_from_records(
                structure_features,
                StructureFeature,
            ),
        )

    def _domain_records_from_records(
        self,
        records: tuple[dict[str, Any], ...],
        record_cls: type,
    ) -> tuple[Any, ...]:
        if not records:
            return ()
        return tuple(
            record_cls.from_mapping(row)
            for row in records
        )

    def _build_document_state(self) -> dict[str, Any]:
        return {
            "anchor_ids_by_key": {},
            "anchor_records_by_id": {},
            "method_ids_by_key": {},
            "method_records_by_id": {},
            "variant_ids_by_key": {},
            "variant_records_by_id": {},
            "test_condition_ids_by_key": {},
            "test_condition_records_by_id": {},
            "baseline_ids_by_key": {},
            "baseline_records_by_id": {},
        }

    def _filter_generic_text_sample_variants(
        self,
        sample_variants: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[dict[str, Any], ...], set[str]]:
        if not sample_variants:
            return self._normalize_sample_variant_records(sample_variants, None), set()

        table_variant_documents = {
            self._normalize_scalar_text(row.get("document_id"))
            for row in sample_variants
            if self._sample_variant_source_kind(row) == "table_row"
        }
        table_variant_labels_by_document: dict[str, set[str]] = {}
        for row in sample_variants:
            document_id = self._normalize_scalar_text(row.get("document_id"))
            label = self._normalize_scalar_text(row.get("variant_label"))
            if (
                document_id
                and label
                and self._sample_variant_source_kind(row) == "table_row"
            ):
                table_variant_labels_by_document.setdefault(document_id, set()).add(
                    label.lower()
                )
        if not table_variant_documents:
            return sample_variants, set()

        kept_rows: list[dict[str, Any]] = []
        removed_variant_ids: set[str] = set()
        for row in sample_variants:
            document_id = self._normalize_scalar_text(row.get("document_id"))
            variant_id = self._normalize_scalar_text(row.get("variant_id"))
            if (
                document_id in table_variant_documents
                and self._sample_variant_source_kind(row) == "text_window"
                and (
                    self._normalize_scalar_text(row.get("variant_label")) or ""
                ).lower()
                not in table_variant_labels_by_document.get(document_id or "", set())
            ):
                if variant_id:
                    removed_variant_ids.add(variant_id)
                continue
            if (
                document_id in table_variant_documents
                and self._is_generic_text_sample_variant(row)
            ):
                if variant_id:
                    removed_variant_ids.add(variant_id)
                continue
            kept_rows.append(dict(row))

        if not removed_variant_ids:
            return sample_variants, set()
        return (
            self._normalize_sample_variant_records(
                kept_rows,
                None,
            ),
            removed_variant_ids,
        )

    def _sample_variant_source_kind(self, row: Any) -> str | None:
        profile_payload = self._normalize_object(row.get("profile_payload"))
        if not isinstance(profile_payload, dict):
            return None
        return self._normalize_scalar_text(profile_payload.get("source_kind"))

    def _is_generic_text_sample_variant(self, row: Any) -> bool:
        if self._sample_variant_source_kind(row) != "text_window":
            return False
        if self._normalize_scalar_text(row.get("variable_axis_type")):
            return False
        if self._normalize_scalar_variant_value(row.get("variable_value")) is not None:
            return False

        label = (self._normalize_scalar_text(row.get("variant_label")) or "").lower()
        if not label:
            return True
        epistemic_status = (
            self._normalize_scalar_text(row.get("epistemic_status")) or ""
        ).lower()
        return (
            epistemic_status == "inferred_with_low_confidence"
            or any(term in label for term in _GENERIC_TEXT_VARIANT_TERMS)
        )

    def _clear_removed_variant_ids_from_measurements(
        self,
        measurement_results: tuple[dict[str, Any], ...],
        removed_variant_ids: set[str],
    ) -> tuple[dict[str, Any], ...]:
        if not measurement_results or not removed_variant_ids:
            return self._normalize_measurement_result_records(measurement_results, None)

        normalized = []
        for row in measurement_results:
            payload = dict(row)
            if self._normalize_scalar_text(payload.get("variant_id")) in removed_variant_ids:
                payload["variant_id"] = None
            normalized.append(payload)
        return self._normalize_measurement_result_records(normalized, None)

    def _materialize_document_method_family_test_conditions(
        self,
        *,
        collection_id: str,
        document_id: str,
        text_windows: list[dict[str, Any]],
        evidence_anchor_rows: list[dict[str, Any]],
        test_condition_rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> None:
        for candidate in self._build_document_method_family_test_conditions(
            text_windows
        ):
            text_window = candidate["text_window"]
            anchors = self._materialize_anchor_payloads(
                anchors=[
                    EvidenceAnchorPayload(
                        quote=candidate["quote"],
                        source_type="text",
                        page=self._safe_int(text_window.get("page")),
                    )
                ],
                document_id=document_id,
                text_window=text_window,
                table_id=None,
                rows=evidence_anchor_rows,
                document_state=document_state,
            )
            condition_id, created = self._materialize_test_condition_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=candidate["condition"],
                text_window=text_window,
                table_id=None,
                rows=test_condition_rows,
                document_state=document_state,
                scope_level="document",
            )
            condition_record = created or document_state[
                "test_condition_records_by_id"
            ].get(condition_id)
            if condition_record is None:
                continue
            for anchor in anchors:
                anchor_id = self._normalize_scalar_text(anchor.get("anchor_id"))
                if (
                    anchor_id
                    and anchor_id not in condition_record["evidence_anchor_ids"]
                ):
                    condition_record["evidence_anchor_ids"].append(anchor_id)
            if created:
                document_state["test_condition_records_by_id"][condition_id] = (
                    condition_record
                )

    def _build_document_method_family_test_conditions(
        self,
        text_windows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: dict[str, tuple[int, dict[str, Any]]] = {}
        for text_window in text_windows:
            text = self._normalize_scalar_text(text_window.get("text")) or ""
            if not text:
                continue
            combined_text = " ".join(
                part
                for part in (
                    self._normalize_scalar_text(text_window.get("heading")),
                    self._normalize_scalar_text(text_window.get("heading_path")),
                    text,
                )
                if part
            )
            for family in _METHOD_FAMILY_PROPERTY_TYPES:
                score = self._score_method_family_condition_window(
                    family,
                    combined_text,
                )
                if score <= 0:
                    continue
                quote = self._select_method_family_quote(text, family=family)
                if not quote:
                    continue
                candidate = {
                    "text_window": text_window,
                    "quote": quote,
                    "condition": ExtractedTestConditionPayload(
                        property_type=family,
                        condition_payload=self._build_method_family_condition_payload(
                            family=family,
                            text=text,
                        ),
                        confidence=0.86,
                    ),
                }
                current = candidates.get(family)
                if current is None or score > current[0]:
                    candidates[family] = (score, candidate)
        return [item[1] for item in candidates.values()]

    def _score_method_family_condition_window(
        self,
        family: str,
        text: str,
    ) -> int:
        lowered = text.lower()
        if family == "tensile_mechanics":
            terms = (
                ("tensile", 4),
                ("stress-strain", 3),
                ("yield strength", 2),
                ("ultimate tensile", 2),
                ("astm e8", 4),
                ("instron", 4),
                ("strain rate", 2),
            )
        elif family == "microhardness":
            terms = (
                ("microhardness", 4),
                ("vickers", 4),
                ("hardness", 2),
                ("wilson", 3),
                ("holding time", 2),
                ("readings", 2),
            )
        elif family == "density_porosity_microstructure":
            terms = (
                ("sem", 3),
                ("imagej", 4),
                ("porosity", 3),
                ("relative density", 3),
                ("microstructure", 2),
                ("magnification", 2),
                ("horizontal", 1),
                ("vertical", 1),
            )
        else:
            return 0
        return sum(weight for term, weight in terms if term in lowered)

    def _build_method_family_condition_payload(
        self,
        *,
        family: str,
        text: str,
    ) -> TestConditionPayloadModel:
        if family == "tensile_mechanics":
            payload = {
                "method": "tensile testing",
                "methods": ["tensile testing"],
                "test_method": "tensile testing",
                "standard": self._extract_first_pattern(
                    text,
                    r"\bASTM\s*E8M?\b",
                ),
                "instrument": self._extract_first_pattern(
                    text,
                    r"\bINSTRON\b[^.;,\n]*",
                ),
                "strain_rate_s-1": self._extract_first_pattern(
                    text,
                    r"\b\d+(?:\.\d+)?\s*mm\s*/\s*min\b",
                ),
                "specimen_geometry": (
                    "Fig. 2"
                    if re.search(r"\bFig\.\s*2\b", text, re.IGNORECASE)
                    else None
                ),
                "sample_orientation": self._extract_orientation_phrase(text),
                "details": self._compact_condition_details(text),
            }
        elif family == "microhardness":
            payload = {
                "method": "Vickers microhardness",
                "methods": ["Vickers microhardness"],
                "test_method": "Vickers microhardness",
                "instrument": self._extract_first_pattern(
                    text,
                    r"\b(?:Vickers\s+)?microhardness[^.;\n]*",
                ),
                "load": self._extract_first_pattern(text, r"\b\d+(?:\.\d+)?\s*N\b"),
                "holding_time": self._extract_first_pattern(
                    text,
                    r"\b\d+(?:\.\d+)?\s*s\b",
                ),
                "readings_per_sample": self._extract_first_pattern(
                    text,
                    r"\b\d+\s+(?:readings|measurements)\b[^.;\n]*",
                ),
                "sample_orientation": self._extract_orientation_phrase(text),
                "details": self._compact_condition_details(text),
            }
        else:
            payload = {
                "method": "SEM / ImageJ",
                "methods": self._dedupe_preserving_order(
                    [
                        method
                        for method in ("SEM", "ImageJ")
                        if method.lower() in text.lower()
                    ]
                )
                or ["SEM / ImageJ"],
                "test_method": "SEM / ImageJ",
                "instrument": self._extract_first_pattern(
                    text,
                    r"\bFEI[-\s]INSPECT\s*50\s*SEM\b",
                )
                or ("SEM" if re.search(r"\bSEM\b", text, re.IGNORECASE) else None),
                "section_orientation": self._extract_section_orientation_phrase(text),
                "surface_state": self._extract_surface_preparation_phrase(text),
                "magnification": self._extract_first_pattern(
                    text,
                    r"\b\d+(?:\.\d+)?\s*[x×]\s*(?:-|to)\s*\d+(?:\.\d+)?\s*[x×]\b",
                ),
                "details": self._compact_condition_details(text),
            }
        return TestConditionPayloadModel(
            **{
                key: value
                for key, value in payload.items()
                if value not in (None, "", [], {})
            }
        )

    def _select_method_family_quote(
        self,
        text: str,
        *,
        family: str,
    ) -> str | None:
        terms = {
            "tensile_mechanics": ("tensile", "astm", "instron", "stress-strain"),
            "microhardness": ("microhardness", "vickers", "hardness", "wilson"),
            "density_porosity_microstructure": (
                "sem",
                "imagej",
                "porosity",
                "relative density",
                "microstructure",
            ),
        }.get(family, ())
        normalized_text = self._normalize_scalar_text(text)
        if not normalized_text:
            return None
        for sentence in re.split(r"(?<=[.!?])\s+", normalized_text):
            if any(term in sentence.lower() for term in terms):
                return sentence[:900].strip()
        return normalized_text[:900].strip()

    def _extract_first_pattern(
        self,
        text: str,
        pattern: str,
    ) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is None:
            return None
        return re.sub(r"\s+", " ", match.group(0)).strip()

    def _extract_orientation_phrase(self, text: str) -> str | None:
        lowered = text.lower()
        if "horizontally" in lowered and "substrate" in lowered:
            return "all blocks built horizontally on substrate"
        if "horizontal" in lowered and "vertical" in lowered:
            return "horizontal and vertical sections"
        if "horizontal" in lowered:
            return "horizontal"
        if "vertical" in lowered:
            return "vertical"
        return None

    def _extract_section_orientation_phrase(self, text: str) -> str | None:
        lowered = text.lower()
        if "horizontal" in lowered and "vertical" in lowered:
            return "horizontal and vertical sections"
        return self._extract_orientation_phrase(text)

    def _extract_surface_preparation_phrase(self, text: str) -> str | None:
        parts = []
        grit = self._extract_first_pattern(
            text,
            r"\b\d+\s*[-–]\s*\d+\s*grit\b",
        )
        if grit:
            parts.append(grit)
        silica = self._extract_first_pattern(
            text,
            r"\bcolloidal\s+silica\b[^.;\n]*",
        )
        if silica:
            parts.append(silica)
        return "; ".join(parts) if parts else None

    def _compact_condition_details(self, text: str) -> str | None:
        normalized = self._normalize_scalar_text(text)
        if not normalized:
            return None
        return re.sub(r"\s+", " ", normalized).strip()[:1000]

    def _attach_document_test_condition_ids_to_measurements(
        self,
        *,
        measurement_results: tuple[dict[str, Any], ...],
        test_conditions: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not measurement_results or not test_conditions:
            return self._normalize_measurement_result_records(measurement_results, None)

        valid_condition_ids = {
            self._normalize_scalar_text(condition.get("test_condition_id"))
            for condition in test_conditions
            if self._normalize_scalar_text(condition.get("test_condition_id"))
        }
        conditions_by_document: dict[str, dict[str, dict[str, Any]]] = {}
        for condition in test_conditions:
            document_id = self._normalize_scalar_text(condition.get("document_id"))
            raw_property_type = self._normalize_scalar_text(condition.get("property_type"))
            property_type = (
                raw_property_type
                if raw_property_type in _METHOD_FAMILY_PROPERTY_TYPES
                else self._normalize_property_name(raw_property_type)
            )
            if not document_id or property_type not in _METHOD_FAMILY_PROPERTY_TYPES:
                continue
            conditions_by_document.setdefault(document_id, {})[property_type] = dict(
                condition
            )

        normalized: list[dict[str, Any]] = []
        for result in measurement_results:
            payload = dict(result)
            existing_condition_id = self._normalize_scalar_text(
                payload.get("test_condition_id")
            )
            if existing_condition_id and existing_condition_id not in valid_condition_ids:
                payload["test_condition_id"] = None
                existing_condition_id = None
            if existing_condition_id:
                normalized.append(payload)
                continue
            if self._normalize_scalar_text(payload.get("result_source_type")) != "table":
                normalized.append(payload)
                continue
            document_id = self._normalize_scalar_text(payload.get("document_id"))
            property_name = self._normalize_property_name(payload.get("property_normalized"))
            property_type = self._method_family_property_type_for_result(property_name)
            condition = conditions_by_document.get(document_id or "", {}).get(
                property_type or ""
            )
            if condition is not None:
                payload["test_condition_id"] = condition.get("test_condition_id")
            normalized.append(payload)
        return self._normalize_measurement_result_records(normalized, None)

    def _filter_superseded_local_test_conditions(
        self,
        test_conditions: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not test_conditions:
            return ()
        documents_with_method_family_conditions = {
            self._normalize_scalar_text(row.get("document_id"))
            for row in test_conditions
            if self._normalize_scalar_text(row.get("property_type"))
            in _METHOD_FAMILY_PROPERTY_TYPES
            and self._normalize_scalar_text(row.get("scope_level")) == "document"
        }
        if not documents_with_method_family_conditions:
            return self._normalize_test_condition_records(test_conditions, None)
        filtered = [
            row
            for row in test_conditions
            if self._normalize_scalar_text(row.get("document_id"))
            not in documents_with_method_family_conditions
            or self._normalize_scalar_text(row.get("scope_level")) == "document"
        ]
        return self._normalize_test_condition_records(filtered, None)

    def _method_family_property_type_for_result(
        self,
        property_name: str,
    ) -> str | None:
        if property_name in _TENSILE_TEST_PROPERTIES:
            return "tensile_mechanics"
        if property_name in _MICROHARDNESS_TEST_PROPERTIES:
            return "microhardness"
        if property_name in _CHARACTERIZATION_TEST_PROPERTIES:
            return "density_porosity_microstructure"
        return None

    def _build_text_window_extraction_payload(
        self,
        *,
        title: str,
        source_filename: str | None,
        profile: dict[str, Any],
        text_window: dict[str, Any],
        objective_context: ObjectiveContext | None = None,
    ) -> dict[str, Any]:
        payload = {
            "document_title": title,
            "source_filename": source_filename,
            "document_profile": {
                "doc_type": str(profile.get("doc_type") or ""),
            },
            "text_window": {
                "heading": self._normalize_scalar_text(text_window.get("heading")),
                "heading_path": self._normalize_scalar_text(text_window.get("heading_path")),
                "text": str(text_window.get("text") or "")[:12000],
                "page": self._safe_int(text_window.get("page")),
            },
        }
        if objective_context is not None:
            payload["objective_context"] = self._build_objective_context_payload(
                objective_context,
            )
        return payload

    def _build_table_batch_extraction_payload(
        self,
        *,
        title: str,
        source_filename: str | None,
        profile: dict[str, Any],
        table_context: dict[str, Any] | None,
        table_rows: list[dict[str, Any]],
        row_cells_by_index: dict[int | None, list[dict[str, Any]]],
        text_windows: list[dict[str, Any]],
        objective_context: ObjectiveContext | None = None,
        objective_table_route: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        supporting_text_windows = self._select_batch_supporting_text_windows(
            text_windows=text_windows,
            table_rows=table_rows,
        )
        payload = {
            "document_title": title,
            "source_filename": source_filename,
            "document_profile": {
                "doc_type": str(profile.get("doc_type") or ""),
            },
            "table_context": self._build_table_context_payload(
                table_context=table_context,
                table_rows=table_rows,
            ),
            "target_rows": [
                self._build_table_batch_target_row_payload(
                    table_row=row,
                    row_cells=row_cells_by_index.get(self._safe_int(row.get("row_index")), []),
                )
                for row in table_rows
            ],
            "supporting_text_windows": [
                {
                    "heading": self._normalize_scalar_text(window.get("heading")),
                    "heading_path": self._normalize_scalar_text(window.get("heading_path")),
                    "text": str(window.get("text") or "")[
                        :_MAX_TABLE_ROW_SUPPORTING_TEXT_CHARS
                    ],
                    "page": self._safe_int(window.get("page")),
                }
                for window in supporting_text_windows
            ],
        }
        if objective_context is not None:
            payload["objective_context"] = self._build_objective_context_payload(
                objective_context,
                table_route=objective_table_route,
            )
        return payload

    def _build_objective_context_payload(
        self,
        objective_context: ObjectiveContext,
        *,
        table_route: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        route_payload = self._build_objective_table_route_payload(table_route)
        return {
            "focus": objective_context.question,
            "material_scope": list(objective_context.material_scope),
            "variable_process_axes": list(objective_context.variable_process_axes),
            "process_context_axes": list(objective_context.process_context_axes),
            "target_property_axes": list(objective_context.target_property_axes),
            "excluded_property_axes": list(objective_context.excluded_property_axes),
            "objective_evidence_lens": dict(objective_context.objective_evidence_lens),
            "routing_hints": [route_payload] if route_payload else [],
            "extraction_guidance": dict(objective_context.extraction_guidance),
            "confidence": objective_context.confidence,
        }

    def _build_objective_table_route_payload(
        self,
        table_route: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if not table_route:
            return {}
        payload = {
            "role": self._normalize_scalar_text(table_route.get("role")),
            "strength": self._normalize_scalar_text(table_route.get("strength")),
            "matched_property_axes": self._normalize_list(
                table_route.get("matched_property_axes")
            ),
            "matched_variable_process_axes": self._normalize_list(
                table_route.get("matched_variable_process_axes")
            ),
            "reason": self._normalize_scalar_text(table_route.get("reason")),
            "caption_text": self._normalize_scalar_text(table_route.get("caption_text")),
        }
        return {
            key: value
            for key, value in payload.items()
            if value not in (None, "", [])
        }

    def _build_table_batch_target_row_payload(
        self,
        *,
        table_row: dict[str, Any],
        row_cells: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "row_index": self._safe_int(table_row.get("row_index")),
            "row_summary": self._normalize_scalar_text(table_row.get("row_text"))
            or self._build_table_row_summary(row_cells),
            "cells": [
                {
                    "header_path": self._normalize_scalar_text(cell.get("header_path")),
                    "cell_text": self._normalize_scalar_text(cell.get("cell_text")),
                    "unit_hint": self._normalize_scalar_text(cell.get("unit_hint")),
                }
                for cell in sorted(
                    row_cells,
                    key=lambda item: self._safe_int(item.get("col_index")) or 0,
                )
            ],
        }

    def _bind_text_window_mentions_to_bundle(
        self,
        *,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
    ) -> StructuredExtractionBundle:
        method_facts = self._build_text_window_method_facts(mentions, text_window)
        process_context = self._build_process_context_from_text_window_mentions(
            mentions,
            text_window,
        )
        sample_variants = self._build_text_window_sample_variants(
            mentions,
            text_window,
            process_context,
        )
        baseline_references = self._build_text_window_baseline_references(
            mentions,
            text_window,
        )
        result_claims = [
            claim
            for claim in mentions.result_claims
            if self._normalize_text_window_evidence_quote(text_window, claim.evidence_quote)
            and str(claim.claim_scope or "").strip() == "current_work"
            and bool(claim.eligible_for_measurement_result)
        ]
        test_conditions = self._build_text_window_test_conditions(
            mentions,
            text_window,
            result_claims,
        )
        measurement_results = self._build_text_window_measurement_results(
            result_claims,
            text_window,
            sample_variants,
            baseline_references,
        )
        return StructuredExtractionBundle(
            method_facts=method_facts,
            sample_variants=sample_variants,
            test_conditions=test_conditions,
            baseline_references=baseline_references,
            measurement_results=measurement_results,
        )

    def _bind_table_row_mentions_to_bundle(
        self,
        *,
        mentions: StructuredTableBatchRowMentions,
        table_row: dict[str, Any],
        row_cells: list[dict[str, Any]],
        table_context: dict[str, Any] | None,
    ) -> StructuredExtractionBundle:
        process_context = self._build_table_row_process_context(
            mentions.process_mentions,
            row_cells=row_cells,
        )
        current_work_claims = [
            claim
            for claim in mentions.result_claims
            if str(claim.claim_scope or "").strip() == "current_work"
        ]
        sample_variants = self._build_table_row_sample_variants(
            mentions=mentions,
            process_context=process_context,
            result_claims=current_work_claims,
            table_row=table_row,
            row_cells=row_cells,
        )
        baseline_references = self._build_table_row_baseline_references(
            mentions=mentions,
            result_claims=current_work_claims,
        )
        test_conditions = self._build_table_row_test_conditions(
            mentions=mentions,
            result_claims=current_work_claims,
        )
        measurement_results = self._build_table_row_measurement_results(
            result_claims=current_work_claims,
            table_row=table_row,
            table_context=table_context,
            process_context=process_context,
            row_cells=row_cells,
        )
        return StructuredExtractionBundle(
            sample_variants=sample_variants,
            test_conditions=test_conditions,
            baseline_references=baseline_references,
            measurement_results=measurement_results,
        )

    def _build_table_row_process_context(
        self,
        mentions: list[Any],
        *,
        row_cells: list[dict[str, Any]] | None = None,
    ) -> ProcessContextPayload:
        payload = self._build_table_row_process_context_from_cells(row_cells or [])
        payload.setdefault("temperatures_c", [])
        payload.setdefault("durations", [])
        numeric_fields = {
            "laser_power_w",
            "scan_speed_mm_s",
            "layer_thickness_um",
            "hatch_spacing_um",
            "spot_size_um",
            "energy_density_j_mm3",
            "preheat_temperature_c",
            "oxygen_level_ppm",
        }
        text_fields = {
            "atmosphere",
            "scan_strategy",
            "build_orientation",
            "shielding_gas",
            "powder_size_distribution_um",
            "post_treatment_summary",
        }
        for mention in mentions:
            field_name = self._normalize_table_row_field_name(mention.name)
            value = self._normalize_scalar_text(mention.value_text)
            quote = self._normalize_scalar_text(mention.quote)
            if not field_name or not (value or quote):
                continue
            source_text = value or quote or ""
            if field_name in {"temperature", "temperature_c"}:
                numeric = self._coerce_numeric_text_window_value(source_text, quote)
                if numeric is not None:
                    payload["temperatures_c"].append(float(numeric))
            elif field_name == "duration":
                payload["durations"].append(source_text)
            elif field_name in numeric_fields:
                numeric = self._coerce_numeric_text_window_value(source_text, quote)
                if numeric is not None and field_name not in payload:
                    payload[field_name] = float(numeric)
            elif field_name in text_fields and field_name not in payload:
                payload[field_name] = source_text

        payload["temperatures_c"] = self._dedupe_preserving_order(
            [round(float(item), 4) for item in payload["temperatures_c"]]
        )
        payload["durations"] = self._dedupe_preserving_order(payload["durations"])
        return ProcessContextPayload(**payload)

    def _build_table_row_process_context_from_cells(
        self,
        row_cells: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for cell in sorted(
            row_cells,
            key=lambda item: self._safe_int(item.get("col_index")) or 0,
        ):
            header = self._normalize_scalar_text(cell.get("header_path"))
            value_text = self._normalize_scalar_text(cell.get("cell_text"))
            if not header or not value_text:
                continue
            field_name = self._process_context_field_from_table_header(header)
            if field_name is None:
                continue
            if field_name in {
                "scan_strategy",
                "build_orientation",
                "shielding_gas",
                "post_treatment_summary",
            }:
                payload[field_name] = value_text
                continue

            numeric = self._coerce_numeric_text_window_value(value_text, value_text)
            if numeric is None:
                continue
            payload[field_name] = self._convert_table_process_value(
                field_name=field_name,
                value=float(numeric),
                header=header,
                unit_hint=self._normalize_scalar_text(cell.get("unit_hint")),
            )
        return payload

    def _process_context_field_from_table_header(self, header: str) -> str | None:
        normalized = re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()
        if not normalized:
            return None
        if "condition" in normalized or "sample" in normalized:
            return None
        if "laser" in normalized and "power" in normalized:
            return "laser_power_w"
        if ("scan" in normalized or "scanning" in normalized) and "speed" in normalized:
            return "scan_speed_mm_s"
        if "hatch" in normalized and ("space" in normalized or "spacing" in normalized):
            return "hatch_spacing_um"
        if "layer" in normalized and "thickness" in normalized:
            return "layer_thickness_um"
        if "spot" in normalized and "size" in normalized:
            return "spot_size_um"
        if "energy" in normalized and "density" in normalized:
            return "energy_density_j_mm3"
        if ("scan" in normalized or "scanning" in normalized) and "strategy" in normalized:
            return "scan_strategy"
        if "build" in normalized and "orientation" in normalized:
            return "build_orientation"
        if "preheat" in normalized and "temperature" in normalized:
            return "preheat_temperature_c"
        if "oxygen" in normalized:
            return "oxygen_level_ppm"
        return None

    def _convert_table_process_value(
        self,
        *,
        field_name: str,
        value: float,
        header: str,
        unit_hint: str | None,
    ) -> float:
        unit_text = " ".join(
            part.lower()
            for part in (header, unit_hint)
            if self._normalize_scalar_text(part)
        )
        if field_name.endswith("_um") and re.search(r"\bmm\b", unit_text):
            return round(value * 1000.0, 6)
        return value

    def _repair_table_row_variant_label(
        self,
        variant_label: Any,
        *,
        process_context: ProcessContextPayload,
        row_cells: list[dict[str, Any]],
    ) -> str | None:
        label = self._normalize_scalar_text(variant_label)
        if not label:
            return None

        label_lower = label.lower()
        if not any(
            token in label_lower for token in ("as-slm", "ht-slm", "hip-slm")
        ):
            return label

        power = self._process_context_number(
            process_context,
            "laser_power_w",
        )
        if power is None:
            power = self._numeric_value_from_table_cells(row_cells, ("laser", "power"))
        speed = self._process_context_number(
            process_context,
            "scan_speed_mm_s",
        )
        if speed is None:
            speed = self._numeric_value_from_table_cells(row_cells, ("scan", "speed"))
        if power is None or speed is None:
            return label

        treatment_text = " ".join(
            part
            for part in (
                self._normalize_scalar_text(
                    getattr(process_context, "post_treatment_summary", None)
                ),
                self._text_value_from_table_cells(row_cells, ("heat", "treatment")),
                label,
            )
            if part
        ).lower()
        if "hip-slm" in label_lower or "hip" in treatment_text:
            process_label = "HIP-SLM"
        elif (
            "ht-slm" in label_lower
            or "furnace" in treatment_text
            or "heat treatment" in treatment_text
        ):
            process_label = "HT-SLM"
        elif "as-slm" in label_lower:
            process_label = "as-SLM"
        else:
            return label

        return (
            f"{process_label} "
            f"({self._format_table_process_number(power)}/"
            f"{self._format_table_process_number(speed)})"
        )

    def _process_context_number(
        self,
        process_context: ProcessContextPayload,
        field_name: str,
    ) -> float | None:
        value = getattr(process_context, field_name, None)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _numeric_value_from_table_cells(
        self,
        row_cells: list[dict[str, Any]],
        header_tokens: tuple[str, ...],
    ) -> float | None:
        value_text = self._text_value_from_table_cells(row_cells, header_tokens)
        if value_text is None:
            return None
        numeric = self._coerce_numeric_text_window_value(value_text, value_text)
        return float(numeric) if numeric is not None else None

    def _text_value_from_table_cells(
        self,
        row_cells: list[dict[str, Any]],
        header_tokens: tuple[str, ...],
    ) -> str | None:
        for cell in row_cells:
            header = self._normalize_scalar_text(cell.get("header_path"))
            value = self._normalize_scalar_text(cell.get("cell_text"))
            if not header or not value:
                continue
            normalized_header = re.sub(r"[^a-z0-9]+", " ", header.lower())
            if all(token in normalized_header for token in header_tokens):
                return value
        return None

    def _format_table_process_number(self, value: float) -> str:
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:g}"

    def _build_table_row_sample_variants(
        self,
        *,
        mentions: StructuredTableBatchRowMentions,
        process_context: ProcessContextPayload,
        result_claims: list[Any],
        table_row: dict[str, Any],
        row_cells: list[dict[str, Any]],
    ) -> list[SampleVariantPayload]:
        rows: list[SampleVariantPayload] = []
        seen: set[str] = set()
        for subject in mentions.row_subjects:
            variant_label = self._repair_table_row_variant_label(
                subject.variant_label,
                process_context=process_context,
                row_cells=row_cells,
            )
            if not variant_label or variant_label.lower() in seen:
                continue
            seen.add(variant_label.lower())
            family = self._sanitize_material_family(subject.family)
            composition = self._normalize_scalar_text(subject.composition)
            rows.append(
                SampleVariantPayload(
                    variant_label=variant_label,
                    host_material_system=(
                        {"family": family, "composition": composition}
                        if family or composition
                        else None
                    ),
                    composition=composition,
                    variable_axis_type=subject.variable_axis_type,
                    variable_value=subject.variable_value,
                    process_context=process_context,
                    source_kind="table_row",
                )
            )

        if rows:
            return rows

        for claim in result_claims:
            variant_label = self._repair_table_row_variant_label(
                claim.variant_label,
                process_context=process_context,
                row_cells=row_cells,
            )
            if not variant_label or variant_label.lower() in seen:
                continue
            seen.add(variant_label.lower())
            rows.append(
                SampleVariantPayload(
                    variant_label=variant_label,
                    process_context=process_context,
                    source_kind="table_row",
                )
            )

        if rows:
            return rows

        sample_label = self._infer_table_row_sample_label(row_cells)
        if sample_label:
            sample_label = (
                self._repair_table_row_variant_label(
                    sample_label,
                    process_context=process_context,
                    row_cells=row_cells,
                )
                or sample_label
            )
            return [
                SampleVariantPayload(
                    variant_label=sample_label,
                    process_context=process_context,
                    source_kind="table_row",
                )
            ]

        row_summary = self._normalize_scalar_text(table_row.get("row_text"))
        if row_summary and result_claims:
            return [
                SampleVariantPayload(
                    variant_label=row_summary.split("|", 1)[0].strip(),
                    process_context=process_context,
                    source_kind="table_row",
                )
            ]
        return []

    def _build_table_row_baseline_references(
        self,
        *,
        mentions: StructuredTableBatchRowMentions,
        result_claims: list[Any],
    ) -> list[BaselineReferencePayload]:
        rows: list[BaselineReferencePayload] = []
        seen: set[str] = set()
        labels = [
            self._normalize_scalar_text(mention.baseline_label)
            for mention in mentions.baseline_mentions
        ]
        labels.extend(
            self._normalize_scalar_text(claim.baseline_label)
            for claim in result_claims
        )
        for label in labels:
            if not label or label.lower() in seen:
                continue
            seen.add(label.lower())
            rows.append(BaselineReferencePayload(baseline_label=label))
        return rows

    def _build_table_row_test_conditions(
        self,
        *,
        mentions: StructuredTableBatchRowMentions,
        result_claims: list[Any],
    ) -> list[ExtractedTestConditionPayload]:
        condition_payload = self._build_table_row_test_condition_payload(
            mentions.test_condition_mentions
        )
        payload_dict = condition_payload.model_dump(exclude_none=True, by_alias=True)
        if not self._has_meaningful_condition_payload(payload_dict):
            return []

        rows: list[ExtractedTestConditionPayload] = []
        seen: set[str] = set()
        for claim in result_claims:
            property_type = self._normalize_property_name(claim.property_normalized)
            if property_type in seen:
                continue
            seen.add(property_type)
            rows.append(
                ExtractedTestConditionPayload(
                    property_type=property_type,
                    condition_payload=payload_dict,
                )
            )
        return rows

    def _build_table_row_test_condition_payload(
        self,
        mentions: list[Any],
    ) -> TestConditionPayloadModel:
        payload: dict[str, Any] = {
            "methods": [],
            "temperatures_c": [],
            "durations": [],
        }
        for mention in mentions:
            field_name = self._normalize_table_row_field_name(mention.name)
            value = self._normalize_scalar_text(mention.value_text)
            quote = self._normalize_scalar_text(mention.quote)
            if not field_name or not (value or quote):
                continue
            source_text = value or quote or ""
            if field_name in {"method", "test_method"}:
                payload["methods"].append(source_text)
                payload.setdefault("method", source_text)
                payload["test_method"] = source_text
            elif field_name in {"temperature", "temperature_c", "test_temperature_c"}:
                numeric = self._coerce_numeric_text_window_value(source_text, quote)
                if numeric is not None:
                    payload["test_temperature_c"] = float(numeric)
            elif field_name == "duration":
                payload["durations"].append(source_text)
            elif field_name == "atmosphere":
                payload["atmosphere"] = source_text
            elif field_name in {
                "strain_rate_s-1",
                "loading_direction",
                "sample_orientation",
                "environment",
                "frequency_hz",
                "specimen_geometry",
                "surface_state",
            }:
                if field_name == "frequency_hz":
                    numeric = self._coerce_numeric_text_window_value(source_text, quote)
                    payload[field_name] = float(numeric) if numeric is not None else source_text
                else:
                    payload[field_name] = source_text

        payload["methods"] = self._dedupe_preserving_order(payload["methods"])
        payload["temperatures_c"] = self._dedupe_preserving_order(
            payload["temperatures_c"]
        )
        payload["durations"] = self._dedupe_preserving_order(payload["durations"])
        return TestConditionPayloadModel(**payload)

    def _build_table_row_measurement_results(
        self,
        *,
        result_claims: list[Any],
        table_row: dict[str, Any],
        table_context: dict[str, Any] | None,
        process_context: ProcessContextPayload,
        row_cells: list[dict[str, Any]],
    ) -> list[MeasurementResultPayload]:
        rows: list[MeasurementResultPayload] = []
        seen_keys: set[tuple[Any, ...]] = set()
        for claim in result_claims:
            if self._is_non_measurement_statistic_claim(claim):
                continue
            value_payload, unit = self._build_measurement_value_from_table_row_claim(
                claim
            )
            quote = self._normalize_table_row_quote(
                claim.quote,
                table_row=table_row,
            )
            claim_text = (
                self._normalize_scalar_text(claim.claim_text)
                or quote
                or self._build_table_row_claim_text(claim, unit)
            )
            property_name = self._normalize_property_name(claim.property_normalized)
            unit = self._infer_measurement_unit_from_parts(
                property_normalized=property_name,
                result_type=str(claim.result_type or "").strip() or "scalar",
                value_payload=value_payload.model_dump(exclude_none=True),
                explicit_unit=unit,
                text=claim_text,
            )
            variant_label = self._repair_table_row_variant_label(
                claim.variant_label,
                process_context=process_context,
                row_cells=row_cells,
            )
            raw_variant_label = self._normalize_scalar_text(claim.variant_label)
            if (
                claim_text
                and variant_label
                and raw_variant_label
                and raw_variant_label in claim_text
            ):
                claim_text = claim_text.replace(raw_variant_label, variant_label)
            dedupe_key = (
                variant_label,
                property_name,
                str(claim.result_type or "").strip() or "scalar",
                self._measurement_value_signature(
                    value_payload.model_dump(exclude_none=True)
                ),
                self._canonical_unit_text(unit),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            rows.append(
                MeasurementResultPayload(
                    claim_text=claim_text,
                    property_normalized=property_name,
                    result_type=str(claim.result_type or "").strip() or "scalar",
                    value_payload=value_payload,
                    unit=unit,
                    variant_label=variant_label,
                    baseline_label=claim.baseline_label,
                    anchors=[
                        EvidenceAnchorPayload(
                            quote=quote,
                            source_type="table",
                            page=self._table_row_page(table_row, table_context),
                        )
                    ],
                    claim_scope=claim.claim_scope,
                )
            )
        return rows

    def _build_measurement_value_from_table_row_claim(
        self,
        claim: Any,
    ) -> tuple[MeasurementValuePayload, str | None]:
        return self._build_measurement_value_from_text_window_claim(claim)

    def _build_table_row_claim_text(
        self,
        claim: Any,
        unit: str | None,
    ) -> str:
        parts = [
            self._normalize_scalar_text(claim.variant_label),
            self._normalize_property_name(claim.property_normalized),
            self._normalize_scalar_text(claim.value_text),
            unit,
        ]
        return " ".join(part for part in parts if part)

    def _normalize_table_row_quote(
        self,
        quote: Any,
        *,
        table_row: dict[str, Any],
    ) -> str | None:
        return (
            self._normalize_scalar_text(quote)
            or self._normalize_scalar_text(table_row.get("row_text"))
            or self._normalize_scalar_text(table_row.get("row_summary"))
        )

    def _table_row_page(
        self,
        table_row: dict[str, Any],
        table_context: dict[str, Any] | None,
    ) -> int | None:
        return (
            self._safe_int((table_context or {}).get("page"))
            or self._safe_int(table_row.get("page"))
        )

    def _infer_table_row_sample_label(
        self,
        row_cells: list[dict[str, Any]],
    ) -> str | None:
        for cell in row_cells:
            header = str(cell.get("header_path") or "").lower()
            if any(token in header for token in ("sample", "group", "variant")):
                return self._normalize_scalar_text(cell.get("cell_text"))
        return None

    def _normalize_table_row_field_name(
        self,
        value: Any,
    ) -> str | None:
        text = self._normalize_scalar_text(value)
        if text is None:
            return None
        normalized = re.sub(r"[^a-z0-9-]+", "_", text.lower()).strip("_")
        aliases = {
            "laser_power": "laser_power_w",
            "power": "laser_power_w",
            "scan_speed": "scan_speed_mm_s",
            "layer_thickness": "layer_thickness_um",
            "hatch_spacing": "hatch_spacing_um",
            "spot_size": "spot_size_um",
            "energy_density": "energy_density_j_mm3",
            "ved": "energy_density_j_mm3",
            "temperature": "temperature_c",
            "temp": "temperature_c",
            "preheat_temperature": "preheat_temperature_c",
            "preheat": "preheat_temperature_c",
            "time": "duration",
            "method_name": "method",
            "test": "test_method",
            "strain_rate": "strain_rate_s-1",
            "strain_rate_s_1": "strain_rate_s-1",
            "orientation": "sample_orientation",
        }
        return aliases.get(normalized, normalized)

    def _build_text_window_method_facts(
        self,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
    ) -> list[MethodFactPayload]:
        rows: list[MethodFactPayload] = []
        for mention in mentions.method_mentions:
            evidence_quote = self._normalize_text_window_evidence_quote(
                text_window,
                mention.evidence_quote,
            )
            method_name = self._normalize_scalar_text(mention.method_name)
            if not evidence_quote or not method_name:
                continue
            method_role = self._normalize_method_role(mention.method_role)
            payload: dict[str, Any] = {
                "details": self._normalize_scalar_text(mention.details),
            }
            if method_role in {"characterization", "test"}:
                payload["methods"] = [method_name]
            rows.append(
                MethodFactPayload(
                    method_role=method_role,
                    method_name=method_name,
                    method_payload=payload,
                    anchors=[
                        EvidenceAnchorPayload(
                            quote=evidence_quote,
                            source_type="text",
                        )
                    ],
                    confidence=mention.confidence,
                )
            )
        return rows

    def _build_process_context_from_text_window_mentions(
        self,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
    ) -> ProcessContextPayload:
        temperatures: list[float] = []
        durations: list[str] = []
        atmosphere: str | None = None
        for mention in mentions.condition_mentions:
            evidence_quote = self._normalize_text_window_evidence_quote(
                text_window,
                mention.evidence_quote,
            )
            if not evidence_quote:
                continue
            condition_type = str(mention.condition_type or "").strip().lower()
            if condition_type == "temperature":
                numeric = self._coerce_numeric_text_window_value(
                    mention.normalized_value,
                    mention.condition_text,
                )
                if numeric is not None:
                    temperatures.append(float(numeric))
            elif condition_type == "duration":
                duration_text = self._normalize_scalar_text(mention.condition_text)
                if duration_text:
                    durations.append(duration_text)
            elif condition_type == "atmosphere":
                atmosphere = self._normalize_scalar_text(
                    mention.normalized_value
                ) or self._normalize_scalar_text(mention.condition_text)
        return ProcessContextPayload(
            temperatures_c=self._dedupe_preserving_order(
                [round(item, 4) for item in temperatures]
            ),
            durations=self._dedupe_preserving_order(durations),
            atmosphere=atmosphere,
        )

    def _build_text_window_sample_variants(
        self,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
        process_context: ProcessContextPayload,
    ) -> list[SampleVariantPayload]:
        materials = self._collect_text_window_material_mentions(mentions, text_window)
        shared_material = materials[0] if len(materials) == 1 else None
        rows: list[SampleVariantPayload] = []
        if mentions.variant_mentions:
            for mention in mentions.variant_mentions:
                evidence_quote = self._normalize_text_window_evidence_quote(
                    text_window,
                    mention.evidence_quote,
                )
                variant_label = self._normalize_scalar_text(mention.variant_label)
                if not evidence_quote or not variant_label:
                    continue
                matched_material = shared_material
                if matched_material is None:
                    quote_matches = [
                        material
                        for material in materials
                        if material["evidence_quote"] == evidence_quote
                    ]
                    if len(quote_matches) == 1:
                        matched_material = quote_matches[0]
                host_material_system = (
                    {
                        "family": matched_material["family"],
                        "composition": matched_material["composition"],
                    }
                    if matched_material is not None
                    else None
                )
                rows.append(
                    SampleVariantPayload(
                        variant_label=variant_label,
                        host_material_system=host_material_system,
                        composition=(
                            matched_material["composition"]
                            if matched_material is not None
                            else None
                        ),
                        variable_axis_type=mention.variable_axis_type,
                        variable_value=mention.variable_value,
                        process_context=process_context,
                        confidence=mention.confidence,
                        source_kind="text_window",
                    )
                )
        elif materials:
            for material in materials:
                rows.append(
                    SampleVariantPayload(
                        variant_label=material["material_label"],
                        host_material_system={
                            "family": material["family"],
                            "composition": material["composition"],
                        },
                        composition=material["composition"],
                        variable_axis_type=None,
                        variable_value=None,
                        process_context=process_context,
                        confidence=material["confidence"],
                        epistemic_status="inferred_with_low_confidence",
                        source_kind="text_window",
                    )
                )
        return rows

    def _collect_text_window_material_mentions(
        self,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for mention in mentions.material_mentions:
            evidence_quote = self._normalize_text_window_evidence_quote(
                text_window,
                mention.evidence_quote,
            )
            material_label = self._normalize_scalar_text(mention.material_label)
            family = self._sanitize_material_family(mention.family) or material_label
            if not evidence_quote or not material_label or not family:
                continue
            rows.append(
                {
                    "material_label": material_label,
                    "family": family,
                    "composition": self._normalize_scalar_text(mention.composition),
                    "evidence_quote": evidence_quote,
                    "confidence": mention.confidence,
                }
            )
        return rows

    def _build_text_window_baseline_references(
        self,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
    ) -> list[BaselineReferencePayload]:
        rows: list[BaselineReferencePayload] = []
        for mention in mentions.baseline_mentions:
            evidence_quote = self._normalize_text_window_evidence_quote(
                text_window,
                mention.evidence_quote,
            )
            baseline_label = self._normalize_scalar_text(mention.baseline_label)
            if not evidence_quote or not baseline_label:
                continue
            rows.append(
                BaselineReferencePayload(
                    baseline_label=baseline_label,
                    confidence=mention.confidence,
                )
            )
        return rows

    def _build_text_window_test_conditions(
        self,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
        result_claims: list[Any],
    ) -> list[ExtractedTestConditionPayload]:
        if not result_claims:
            return []
        condition_payload = self._build_text_window_test_condition_payload(
            mentions,
            text_window,
        )
        payload_dict = condition_payload.model_dump(exclude_none=True, by_alias=True)
        if not self._has_meaningful_condition_payload(payload_dict):
            return []
        rows: list[ExtractedTestConditionPayload] = []
        seen: set[str] = set()
        for claim in result_claims:
            property_type = self._normalize_property_name(claim.property_normalized)
            if property_type in seen:
                continue
            seen.add(property_type)
            rows.append(
                ExtractedTestConditionPayload(
                    property_type=property_type,
                    condition_payload=payload_dict,
                    confidence=max(
                        [claim.confidence]
                        + [
                            mention.confidence
                            for mention in mentions.condition_mentions
                            if self._normalize_text_window_evidence_quote(
                                text_window,
                                mention.evidence_quote,
                            )
                        ]
                        + [
                            mention.confidence
                            for mention in mentions.method_mentions
                            if str(mention.method_role or "").strip().lower() == "test"
                            and self._normalize_text_window_evidence_quote(
                                text_window,
                                mention.evidence_quote,
                            )
                        ]
                    ),
                )
            )
        return rows

    def _build_text_window_test_condition_payload(
        self,
        mentions: StructuredTextWindowMentions,
        text_window: dict[str, Any],
    ) -> TestConditionPayloadModel:
        methods: list[str] = []
        temperatures: list[float] = []
        durations: list[str] = []
        atmosphere: str | None = None

        for mention in mentions.method_mentions:
            evidence_quote = self._normalize_text_window_evidence_quote(
                text_window,
                mention.evidence_quote,
            )
            if not evidence_quote:
                continue
            if str(mention.method_role or "").strip().lower() == "test":
                method_name = self._normalize_scalar_text(mention.method_name)
                if method_name:
                    methods.append(method_name)

        for mention in mentions.condition_mentions:
            evidence_quote = self._normalize_text_window_evidence_quote(
                text_window,
                mention.evidence_quote,
            )
            if not evidence_quote:
                continue
            condition_type = str(mention.condition_type or "").strip().lower()
            if condition_type == "temperature":
                numeric = self._coerce_numeric_text_window_value(
                    mention.normalized_value,
                    mention.condition_text,
                )
                if numeric is not None:
                    temperatures.append(float(numeric))
            elif condition_type == "duration":
                duration_text = self._normalize_scalar_text(mention.condition_text)
                if duration_text:
                    durations.append(duration_text)
            elif condition_type == "atmosphere":
                atmosphere = self._normalize_scalar_text(
                    mention.normalized_value
                ) or self._normalize_scalar_text(mention.condition_text)

        deduped_methods = self._dedupe_preserving_order(methods)
        return TestConditionPayloadModel(
            method=deduped_methods[0] if len(deduped_methods) == 1 else None,
            methods=deduped_methods,
            temperatures_c=self._dedupe_preserving_order(
                [round(item, 4) for item in temperatures]
            ),
            durations=self._dedupe_preserving_order(durations),
            atmosphere=atmosphere,
        )

    def _has_meaningful_condition_payload(self, payload: dict[str, Any]) -> bool:
        return any(value not in (None, "", [], {}) for value in payload.values())

    def _build_text_window_measurement_results(
        self,
        result_claims: list[Any],
        text_window: dict[str, Any],
        sample_variants: list[SampleVariantPayload],
        baseline_references: list[BaselineReferencePayload],
    ) -> list[MeasurementResultPayload]:
        rows: list[MeasurementResultPayload] = []
        for claim in result_claims:
            evidence_quote = self._normalize_text_window_evidence_quote(
                text_window,
                claim.evidence_quote,
            )
            if not evidence_quote:
                continue
            value_payload, unit = self._build_measurement_value_from_text_window_claim(
                claim
            )
            rows.append(
                MeasurementResultPayload(
                    claim_text=self._normalize_scalar_text(claim.claim_text) or evidence_quote,
                    property_normalized=self._normalize_property_name(
                        claim.property_normalized
                    ),
                    result_type=str(claim.result_type or "").strip() or "trend",
                    value_payload=value_payload,
                    unit=unit,
                    variant_label=self._match_variant_label_for_text_window_claim(
                        claim,
                        sample_variants,
                    ),
                    baseline_label=self._match_baseline_label_for_text_window_claim(
                        claim,
                        baseline_references,
                    ),
                    anchors=[
                        EvidenceAnchorPayload(
                            quote=evidence_quote,
                            source_type="text",
                        )
                    ],
                    claim_scope=claim.claim_scope,
                    confidence=claim.confidence,
                )
            )
        return rows

    def _build_measurement_value_from_text_window_claim(
        self,
        claim: Any,
    ) -> tuple[MeasurementValuePayload, str | None]:
        claim_text = self._normalize_scalar_text(claim.claim_text)
        value_text = self._normalize_scalar_text(claim.value_text)
        unit = self._sanitize_unit(claim.unit) or self._extract_unit_from_text(
            value_text or claim_text or ""
        )
        source_text = value_text or claim_text or ""
        lowered = source_text.lower()
        statement = claim_text or value_text or None

        range_match = re.search(
            r"([-+]?\d+(?:\.\d+)?)\s*(?:-|to)\s*([-+]?\d+(?:\.\d+)?)",
            source_text,
        )
        if range_match is not None:
            return (
                MeasurementValuePayload(
                    min=float(range_match.group(1)),
                    max=float(range_match.group(2)),
                    statement=statement,
                    value_origin="reported",
                    source_value_text=range_match.group(0),
                    source_unit_text=unit,
                ),
                unit,
            )

        min_match = re.search(
            r"\b(?:over|more than|greater than|above)\s+([-+]?\d+(?:\.\d+)?)",
            lowered,
        )
        if min_match is not None:
            return (
                MeasurementValuePayload(
                    min=float(min_match.group(1)),
                    statement=statement,
                    value_origin="reported",
                    source_value_text=min_match.group(0),
                    source_unit_text=unit,
                ),
                unit,
            )

        max_match = re.search(
            r"\b(?:under|less than|below)\s+([-+]?\d+(?:\.\d+)?)",
            lowered,
        )
        if max_match is not None:
            return (
                MeasurementValuePayload(
                    max=float(max_match.group(1)),
                    statement=statement,
                    value_origin="reported",
                    source_value_text=max_match.group(0),
                    source_unit_text=unit,
                ),
                unit,
            )

        approx_match = re.search(
            r"(?:about|approximately|approx\.?|~)\s*([-+]?\d+(?:\.\d+)?)",
            lowered,
        )
        if approx_match is not None:
            numeric = float(approx_match.group(1))
            if str(claim.result_type or "").strip().lower() == "retention":
                return (
                    MeasurementValuePayload(
                        retention_percent=numeric,
                        statement=statement,
                        value_origin="reported",
                        source_value_text=approx_match.group(0),
                        source_unit_text=unit or "%",
                    ),
                    unit or "%",
                )
            return (
                MeasurementValuePayload(
                    value=numeric,
                    statement=statement,
                    value_origin="reported",
                    source_value_text=approx_match.group(0),
                    source_unit_text=unit,
                ),
                unit,
            )

        numeric = self._coerce_numeric_text_window_value(value_text, claim_text)
        if numeric is None:
            return MeasurementValuePayload(statement=statement), unit
        source_value_text = value_text or f"{numeric:g}"
        if str(claim.result_type or "").strip().lower() == "retention":
            return (
                MeasurementValuePayload(
                    retention_percent=float(numeric),
                    statement=statement,
                    value_origin="reported",
                    source_value_text=source_value_text,
                    source_unit_text=unit or "%",
                ),
                unit or "%",
            )
        return (
            MeasurementValuePayload(
                value=float(numeric),
                statement=statement,
                value_origin="reported",
                source_value_text=source_value_text,
                source_unit_text=unit,
            ),
            unit,
        )

    def _match_variant_label_for_text_window_claim(
        self,
        claim: Any,
        sample_variants: list[SampleVariantPayload],
    ) -> str | None:
        if len(sample_variants) == 1:
            return self._normalize_scalar_text(sample_variants[0].variant_label)
        claim_text = " ".join(
            filter(
                None,
                [
                    self._normalize_scalar_text(claim.claim_text),
                    self._normalize_scalar_text(claim.evidence_quote),
                ],
            )
        ).lower()
        matched = [
            self._normalize_scalar_text(variant.variant_label)
            for variant in sample_variants
            if self._normalize_scalar_text(variant.variant_label)
            and self._normalize_scalar_text(variant.variant_label).lower() in claim_text
        ]
        if len(matched) == 1:
            return matched[0]
        return None

    def _match_baseline_label_for_text_window_claim(
        self,
        claim: Any,
        baseline_references: list[BaselineReferencePayload],
    ) -> str | None:
        if len(baseline_references) == 1:
            return self._normalize_scalar_text(baseline_references[0].baseline_label)
        claim_text = " ".join(
            filter(
                None,
                [
                    self._normalize_scalar_text(claim.claim_text),
                    self._normalize_scalar_text(claim.evidence_quote),
                ],
            )
        ).lower()
        matched = [
            self._normalize_scalar_text(baseline.baseline_label)
            for baseline in baseline_references
            if self._normalize_scalar_text(baseline.baseline_label)
            and self._normalize_scalar_text(baseline.baseline_label).lower() in claim_text
        ]
        if len(matched) == 1:
            return matched[0]
        return None

    def _normalize_text_window_evidence_quote(
        self,
        text_window: dict[str, Any],
        quote: Any,
    ) -> str | None:
        normalized_quote = self._normalize_scalar_text(quote)
        if normalized_quote is None:
            return None
        window_text = str(text_window.get("text") or "")
        if normalized_quote not in window_text:
            return None
        return normalized_quote

    def _coerce_numeric_text_window_value(
        self,
        explicit_value: Any,
        fallback_text: Any,
    ) -> int | float | None:
        normalized = normalize_record_value(explicit_value)
        if isinstance(normalized, bool):
            return None
        if isinstance(normalized, int):
            return normalized
        if isinstance(normalized, float):
            if math.isnan(normalized):
                return None
            return int(normalized) if normalized.is_integer() else normalized
        text = self._normalize_scalar_text(explicit_value) or self._normalize_scalar_text(
            fallback_text
        )
        if text is None:
            return None
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if match is None:
            return None
        numeric = float(match.group(0))
        return int(numeric) if numeric.is_integer() else numeric

    def _extract_unit_from_text(self, value: str) -> str | None:
        text = str(value or "")
        if re.search(r"\bHV\b", text, re.IGNORECASE):
            return "HV"
        if re.search(r"\bMPa\b", text, re.IGNORECASE):
            return "MPa"
        if re.search(r"\bGPa\b", text, re.IGNORECASE):
            return "GPa"
        if re.search(r"\bPa\b", text, re.IGNORECASE):
            return "Pa"
        if "%" in text:
            return "%"
        if re.search(r"(?:°\s*C|\bC\b)", text, re.IGNORECASE):
            return "C"
        return None

    def _dedupe_preserving_order(self, values: list[Any]) -> list[Any]:
        seen: set[Any] = set()
        rows: list[Any] = []
        for value in values:
            key = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            if key in seen:
                continue
            seen.add(key)
            rows.append(value)
        return rows

    def _materialize_bundle(
        self,
        *,
        bundle: StructuredExtractionBundle,
        collection_id: str,
        document_id: str,
        text_window: dict[str, Any] | None,
        table_id: str | None,
        row_index: int | None,
        evidence_anchor_rows: list[dict[str, Any]],
        method_fact_rows: list[dict[str, Any]],
        sample_variant_rows: list[dict[str, Any]],
        test_condition_rows: list[dict[str, Any]],
        baseline_rows: list[dict[str, Any]],
        measurement_rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> None:
        local_variant_records: list[dict[str, Any]] = []
        local_variant_record_ids: set[str] = set()
        local_test_condition_records: list[dict[str, Any]] = []
        local_test_condition_record_ids: set[str] = set()
        local_baseline_records: list[dict[str, Any]] = []
        local_baseline_record_ids: set[str] = set()
        bundle_anchor_ids: list[str] = []

        for method_fact in bundle.method_facts:
            method_id, created = self._materialize_method_fact_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=method_fact,
                text_window=text_window,
                table_id=table_id,
                rows=method_fact_rows,
                evidence_anchor_rows=evidence_anchor_rows,
                document_state=document_state,
            )
            method_record = (
                created
                or document_state["method_records_by_id"].get(method_id)
            )
            if method_record is None:
                continue
            for anchor_id in method_record["evidence_anchor_ids"]:
                if anchor_id not in bundle_anchor_ids:
                    bundle_anchor_ids.append(anchor_id)
            if created:
                document_state["method_records_by_id"][method_id] = created

        for variant in bundle.sample_variants:
            variant_id, created = self._materialize_variant_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=variant,
                text_window=text_window,
                table_id=table_id,
                row_index=row_index,
                rows=sample_variant_rows,
                document_state=document_state,
            )
            if created:
                document_state["variant_records_by_id"][variant_id] = created
            variant_record = created or document_state["variant_records_by_id"].get(variant_id)
            if variant_record is not None and variant_id not in local_variant_record_ids:
                local_variant_record_ids.add(variant_id)
                local_variant_records.append(variant_record)

        for condition in bundle.test_conditions:
            condition_id, created = self._materialize_test_condition_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=condition,
                text_window=text_window,
                table_id=table_id,
                rows=test_condition_rows,
                document_state=document_state,
            )
            if created:
                document_state["test_condition_records_by_id"][condition_id] = created
            condition_record = created or document_state["test_condition_records_by_id"].get(condition_id)
            if condition_record is not None and condition_id not in local_test_condition_record_ids:
                local_test_condition_record_ids.add(condition_id)
                local_test_condition_records.append(condition_record)

        for baseline in bundle.baseline_references:
            baseline_id, created = self._materialize_baseline_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=baseline,
                text_window=text_window,
                table_id=table_id,
                rows=baseline_rows,
                document_state=document_state,
            )
            if created:
                document_state["baseline_records_by_id"][baseline_id] = created
            baseline_record = created or document_state["baseline_records_by_id"].get(baseline_id)
            if baseline_record is not None and baseline_id not in local_baseline_record_ids:
                local_baseline_record_ids.add(baseline_id)
                local_baseline_records.append(baseline_record)

        for result in bundle.measurement_results:
            anchors = self._materialize_anchor_payloads(
                anchors=result.anchors,
                document_id=document_id,
                text_window=text_window,
                table_id=table_id,
                rows=evidence_anchor_rows,
                document_state=document_state,
            )
            anchor_ids = [anchor["anchor_id"] for anchor in anchors]
            bundle_anchor_ids.extend(
                anchor_id for anchor_id in anchor_ids if anchor_id not in bundle_anchor_ids
            )
            linked_variant_id = self._resolve_result_variant_id(
                result,
                local_variant_records,
            )
            linked_test_condition_id = self._resolve_result_test_condition_id(
                result,
                local_test_condition_records,
            )
            linked_baseline_id = self._resolve_result_baseline_id(
                result,
                local_baseline_records,
            )

            measurement_record = MeasurementResult.from_mapping(
                {
                    "result_id": f"res_{uuid4().hex[:12]}",
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                    "variant_id": linked_variant_id,
                    "property_normalized": self._normalize_property_name(
                        result.property_normalized
                    ),
                    "result_type": self._normalize_result_type(result.result_type),
                    "claim_scope": str(result.claim_scope or "current_work"),
                    "value_payload": self._sanitize_value_payload(
                        result.value_payload.model_dump(exclude_none=True)
                    ),
                    "unit": self._sanitize_unit(result.unit),
                    "test_condition_id": linked_test_condition_id,
                    "baseline_id": linked_baseline_id,
                    "structure_feature_ids": [],
                    "characterization_observation_ids": [],
                    "evidence_anchor_ids": anchor_ids,
                    "traceability_status": (
                        TRACEABILITY_STATUS_DIRECT if anchor_ids else TRACEABILITY_STATUS_MISSING
                    ),
                    "result_source_type": "table" if table_id else "text",
                    "epistemic_status": (
                        EPISTEMIC_DIRECTLY_OBSERVED if table_id else EPISTEMIC_NORMALIZED_FROM_EVIDENCE
                    ),
                }
            ).to_record()
            if not measurement_record["value_payload"]:
                logger.warning(
                    "Dropped empty measurement payload collection_id=%s document_id=%s property=%s result_type=%s text_window_id=%s table_id=%s row_index=%s",
                    collection_id,
                    document_id,
                    self._normalize_property_name(result.property_normalized),
                    self._normalize_result_type(result.result_type),
                    self._normalize_scalar_text(text_window.get("window_id")) if text_window else None,
                    table_id,
                    row_index,
                )
                continue
            measurement_rows.append(measurement_record)

        for variant_record in local_variant_records:
            for anchor_id in bundle_anchor_ids:
                if anchor_id not in variant_record["source_anchor_ids"]:
                    variant_record["source_anchor_ids"].append(anchor_id)

        for condition_record in local_test_condition_records:
            for anchor_id in bundle_anchor_ids:
                if anchor_id not in condition_record["evidence_anchor_ids"]:
                    condition_record["evidence_anchor_ids"].append(anchor_id)

        for baseline_record in local_baseline_records:
            for anchor_id in bundle_anchor_ids:
                if anchor_id not in baseline_record["evidence_anchor_ids"]:
                    baseline_record["evidence_anchor_ids"].append(anchor_id)

    def _materialize_method_fact_row(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: MethodFactPayload,
        text_window: dict[str, Any] | None,
        table_id: str | None,
        rows: list[dict[str, Any]],
        evidence_anchor_rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        normalized_payload = self._normalize_method_payload(
            payload.method_payload.model_dump(exclude_none=True)
        )
        method_role = self._normalize_method_role(payload.method_role)
        method_name = self._normalize_scalar_text(payload.method_name) or method_role
        anchors = self._materialize_anchor_payloads(
            anchors=payload.anchors,
            document_id=document_id,
            text_window=text_window,
            table_id=table_id,
            rows=evidence_anchor_rows,
            document_state=document_state,
        )
        anchor_ids = [str(anchor.get("anchor_id") or "") for anchor in anchors if str(anchor.get("anchor_id") or "").strip()]
        method_key = (
            document_id,
            method_role,
            method_name.lower(),
            json.dumps(normalized_payload, sort_keys=True, ensure_ascii=False),
        )
        existing_id = document_state["method_ids_by_key"].get(method_key)
        if existing_id:
            existing_record = document_state["method_records_by_id"].get(existing_id)
            if existing_record is not None:
                for anchor_id in anchor_ids:
                    if anchor_id not in existing_record["evidence_anchor_ids"]:
                        existing_record["evidence_anchor_ids"].append(anchor_id)
            return existing_id, None

        method_record = MethodFact.from_mapping(
            {
                "method_id": f"mf_{uuid4().hex[:12]}",
                "document_id": document_id,
                "collection_id": collection_id,
                "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                "method_role": method_role,
                "method_name": method_name,
                "method_payload": normalized_payload,
                "evidence_anchor_ids": anchor_ids,
                "confidence": payload.confidence,
                "epistemic_status": str(payload.epistemic_status or EPISTEMIC_NORMALIZED_FROM_EVIDENCE),
            }
        ).to_record()
        rows.append(method_record)
        document_state["method_ids_by_key"][method_key] = method_record["method_id"]
        return method_record["method_id"], method_record

    def _materialize_variant_row(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: SampleVariantPayload,
        text_window: dict[str, Any] | None,
        table_id: str | None,
        row_index: int | None,
        rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        normalized_material = self._normalize_material_system_payload(
            payload.host_material_system.model_dump(exclude_none=True)
            if payload.host_material_system
            else {}
        )
        variable_axis_type = self._normalize_variant_axis_type(payload.variable_axis_type)
        variable_value = self._normalize_scalar_variant_value(payload.variable_value)
        variant_key = (
            document_id,
            str(payload.variant_label or "").strip().lower(),
            str(variable_axis_type or "").strip().lower(),
            str(variable_value if variable_value is not None else "").strip().lower(),
            str(normalized_material.get("family") or "").strip().lower(),
        )
        existing_id = document_state["variant_ids_by_key"].get(variant_key)
        if existing_id:
            return existing_id, None

        variant_record = SampleVariant.from_mapping(
            {
                "variant_id": f"var_{uuid4().hex[:12]}",
                "document_id": document_id,
                "collection_id": collection_id,
                "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                "variant_label": str(payload.variant_label or "").strip(),
                "host_material_system": normalized_material,
                "composition": self._normalize_scalar_text(payload.composition),
                "variable_axis_type": variable_axis_type,
                "variable_value": variable_value,
                "process_context": self._normalize_condition_payload(
                    payload.process_context.model_dump(exclude_none=True)
                ),
                "profile_payload": {
                    "source_kind": payload.source_kind,
                    "text_window_id": self._normalize_scalar_text(text_window.get("window_id"))
                    if text_window
                    else None,
                    "table_id": table_id,
                    "row_index": row_index,
                },
                "structure_feature_ids": [],
                "source_anchor_ids": [],
                "confidence": payload.confidence,
                "epistemic_status": str(payload.epistemic_status or EPISTEMIC_NORMALIZED_FROM_EVIDENCE),
            }
        ).to_record()
        rows.append(variant_record)
        document_state["variant_ids_by_key"][variant_key] = variant_record["variant_id"]
        return variant_record["variant_id"], variant_record

    def _materialize_test_condition_row(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: ExtractedTestConditionPayload,
        text_window: dict[str, Any] | None,
        table_id: str | None,
        rows: list[dict[str, Any]],
        document_state: dict[str, Any],
        scope_level: str | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        normalized_payload = self._normalize_condition_payload(
            payload.condition_payload.model_dump(exclude_none=True, by_alias=True)
        )
        raw_property_type = self._normalize_scalar_text(payload.property_type)
        property_type = (
            raw_property_type
            if raw_property_type in _METHOD_FAMILY_PROPERTY_TYPES
            else self._normalize_property_name(payload.property_type)
        )
        condition_key = (
            document_id,
            property_type,
            json.dumps(normalized_payload, sort_keys=True, ensure_ascii=False),
        )
        existing_id = document_state["test_condition_ids_by_key"].get(condition_key)
        if existing_id:
            return existing_id, None

        template_type = self._infer_condition_template_type(property_type)
        resolved_scope_level = scope_level or ("table" if table_id else "measurement")
        missing_fields = self._infer_missing_condition_fields(
            payload=normalized_payload,
            template_type=template_type,
            scope_level=resolved_scope_level,
        )
        condition_record = TestCondition.from_mapping(
            {
                "test_condition_id": f"tc_{uuid4().hex[:12]}",
                "document_id": document_id,
                "collection_id": collection_id,
                "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                "property_type": property_type,
                "template_type": template_type,
                "scope_level": resolved_scope_level,
                "condition_payload": normalized_payload,
                "condition_completeness": self._infer_condition_completeness(
                    payload=normalized_payload,
                    missing_fields=missing_fields,
                ),
                "missing_fields": missing_fields,
                "evidence_anchor_ids": [],
                "confidence": payload.confidence,
                "epistemic_status": str(payload.epistemic_status or EPISTEMIC_NORMALIZED_FROM_EVIDENCE),
            }
        ).to_record()
        rows.append(condition_record)
        document_state["test_condition_ids_by_key"][condition_key] = condition_record["test_condition_id"]
        return condition_record["test_condition_id"], condition_record

    def _materialize_baseline_row(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: BaselineReferencePayload,
        text_window: dict[str, Any] | None,
        table_id: str | None,
        rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        baseline_label = str(payload.baseline_label or "").strip()
        baseline_key = (document_id, baseline_label.lower())
        existing_id = document_state["baseline_ids_by_key"].get(baseline_key)
        if existing_id:
            return existing_id, None

        baseline_record = BaselineReference.from_mapping(
            {
                "baseline_id": f"base_{uuid4().hex[:12]}",
                "document_id": document_id,
                "collection_id": collection_id,
                "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                "variant_id": None,
                "baseline_type": self._classify_baseline_type(baseline_label),
                "baseline_label": baseline_label,
                "baseline_scope": "table" if table_id else "measurement",
                "evidence_anchor_ids": [],
                "confidence": payload.confidence,
                "epistemic_status": str(payload.epistemic_status or EPISTEMIC_NORMALIZED_FROM_EVIDENCE),
            }
        ).to_record()
        rows.append(baseline_record)
        document_state["baseline_ids_by_key"][baseline_key] = baseline_record["baseline_id"]
        return baseline_record["baseline_id"], baseline_record

    def _materialize_anchor_payloads(
        self,
        *,
        anchors: list[EvidenceAnchorPayload],
        document_id: str,
        text_window: dict[str, Any] | None,
        table_id: str | None,
        rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        section_id = self._normalize_scalar_text(text_window.get("window_id")) if text_window else None
        window_block_ids = self._normalize_list(text_window.get("block_ids")) if text_window else []
        block_id = self._normalize_scalar_text(window_block_ids[0]) if window_block_ids else None
        snippet_ids = self._normalize_list(text_window.get("text_unit_ids")) if text_window else []
        resolved_section_id = block_id or section_id
        resolved_snippet_id = snippet_ids[0] if len(snippet_ids) == 1 else None
        window_text = self._normalize_scalar_text(text_window.get("text")) if text_window else None
        window_char_range = (
            self._normalize_char_range_payload(text_window.get("char_range")) if text_window else None
        )
        scope_page = self._safe_int(text_window.get("page")) if text_window else None
        for anchor in anchors:
            quote = self._normalize_scalar_text(anchor.quote)
            source_type = (
                str(anchor.source_type or "text")
                if str(anchor.source_type or "text") in _EVIDENCE_SOURCE_TYPES
                else ("table" if table_id else "text")
            )
            page = self._safe_int(anchor.page) or scope_page
            char_range = None
            locator_type = "section"
            locator_confidence = "low"
            if quote and window_text and window_char_range is not None:
                local_index = window_text.find(quote)
                if local_index >= 0:
                    char_range = {
                        "start": window_char_range["start"] + local_index,
                        "end": window_char_range["start"] + local_index + len(quote),
                    }
                    locator_type = "char_range"
                    locator_confidence = "high"
            anchor_key = (
                document_id,
                source_type,
                resolved_section_id,
                resolved_snippet_id,
                table_id,
                page,
                quote,
                char_range["start"] if char_range is not None else None,
                char_range["end"] if char_range is not None else None,
            )
            existing_id = document_state["anchor_ids_by_key"].get(anchor_key)
            if existing_id:
                existing_record = document_state["anchor_records_by_id"].get(existing_id)
                if existing_record is not None:
                    payload.append(existing_record)
                    continue

            anchor_record = EvidenceAnchor.from_mapping(
                {
                    "anchor_id": f"anchor_{uuid4().hex[:12]}",
                    "document_id": document_id,
                    "locator_type": locator_type,
                    "locator_confidence": locator_confidence,
                    "source_type": source_type,
                    "section_id": resolved_section_id,
                    "char_range": char_range,
                    "bbox": None,
                    "page": page,
                    "quote": quote,
                    "deep_link": None,
                    "block_id": block_id,
                    "snippet_id": resolved_snippet_id,
                    "figure_or_table": table_id,
                    "quote_span": quote,
                }
            ).to_record()
            rows.append(anchor_record)
            document_state["anchor_ids_by_key"][anchor_key] = anchor_record["anchor_id"]
            document_state["anchor_records_by_id"][anchor_record["anchor_id"]] = anchor_record
            payload.append(anchor_record)
        return payload

    def _resolve_result_variant_id(
        self,
        result: MeasurementResultPayload,
        local_variant_records: list[dict[str, Any]],
    ) -> str | None:
        if len(local_variant_records) == 1:
            return self._normalize_scalar_text(local_variant_records[0].get("variant_id"))

        label_hint = self._normalize_scalar_text(result.variant_label)
        if label_hint:
            matched = [
                record
                for record in local_variant_records
                if self._normalize_scalar_text(record.get("variant_label"))
                and self._normalize_scalar_text(record.get("variant_label")).lower()
                == label_hint.lower()
            ]
            if len(matched) == 1:
                return self._normalize_scalar_text(matched[0].get("variant_id"))

        claim_text = str(result.claim_text or "").lower()
        matched = [
            record
            for record in local_variant_records
            if self._normalize_scalar_text(record.get("variant_label"))
            and self._normalize_scalar_text(record.get("variant_label")).lower() in claim_text
        ]
        if len(matched) == 1:
            return self._normalize_scalar_text(matched[0].get("variant_id"))
        return None

    def _resolve_result_test_condition_id(
        self,
        result: MeasurementResultPayload,
        local_test_condition_records: list[dict[str, Any]],
    ) -> str | None:
        if len(local_test_condition_records) == 1:
            return self._normalize_scalar_text(
                local_test_condition_records[0].get("test_condition_id")
            )

        property_name = self._normalize_property_name(result.property_normalized)
        matched = [
            record
            for record in local_test_condition_records
            if self._normalize_property_name(record.get("property_type")) == property_name
        ]
        if len(matched) == 1:
            return self._normalize_scalar_text(matched[0].get("test_condition_id"))
        return None

    def _resolve_result_baseline_id(
        self,
        result: MeasurementResultPayload,
        local_baseline_records: list[dict[str, Any]],
    ) -> str | None:
        if len(local_baseline_records) == 1:
            return self._normalize_scalar_text(local_baseline_records[0].get("baseline_id"))

        label_hint = self._normalize_scalar_text(result.baseline_label)
        if label_hint:
            matched = [
                record
                for record in local_baseline_records
                if self._normalize_scalar_text(record.get("baseline_label"))
                and self._normalize_scalar_text(record.get("baseline_label")).lower()
                == label_hint.lower()
            ]
            if len(matched) == 1:
                return self._normalize_scalar_text(matched[0].get("baseline_id"))

        claim_text = str(result.claim_text or "").lower()
        matched = [
            record
            for record in local_baseline_records
            if self._normalize_scalar_text(record.get("baseline_label"))
            and self._normalize_scalar_text(record.get("baseline_label")).lower() in claim_text
        ]
        if len(matched) == 1:
            return self._normalize_scalar_text(matched[0].get("baseline_id"))
        return None

    def _to_material_payload(self, value: Any) -> Any:
        normalized = self._normalize_material_system_payload(value)
        return {
            "family": normalized.get("family"),
            "composition": normalized.get("composition"),
        }

    def _condition_context_from_records(
        self,
        test_condition: dict[str, Any] | None,
        baseline: dict[str, Any] | None,
    ) -> ConditionContextPayload:
        payload = self._normalize_condition_payload(
            (test_condition or {}).get("condition_payload")
        )
        return ConditionContextPayload(
            process=ProcessContextPayload(
                temperatures_c=list(payload.get("temperatures_c") or []),
                durations=[str(item) for item in payload.get("durations") or []],
                atmosphere=self._normalize_scalar_text(payload.get("atmosphere")),
            ),
            baseline={"control": self._normalize_scalar_text((baseline or {}).get("baseline_label"))},
            test=TestContextPayload(
                methods=[str(item) for item in payload.get("methods") or []],
                method=self._normalize_scalar_text(payload.get("method")),
            ),
        )

    def _condition_context_from_method_fact(
        self,
        method_fact: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = self._normalize_method_payload(method_fact.get("method_payload"))
        method_role = self._normalize_method_role(method_fact.get("method_role"))
        method_name = self._normalize_scalar_text(method_fact.get("method_name"))
        methods = [str(item) for item in payload.get("methods") or [] if str(item).strip()]
        if method_name and method_role in {"characterization", "test"} and method_name not in methods:
            methods = [method_name, *methods]
        test_method = method_name if method_role in {"characterization", "test"} else None
        return self._normalize_condition_context_payload(
            {
                "process": {
                    "temperatures_c": payload.get("temperatures_c") or [],
                    "durations": payload.get("durations") or [],
                    "atmosphere": payload.get("atmosphere"),
                },
                "baseline": {"control": None},
                "test": {
                    "methods": methods,
                    "method": test_method,
                },
            }
        )

    def _derive_evidence_card_records(
        self,
        *,
        collection_id: str,
        evidence_anchors: tuple[dict[str, Any], ...],
        method_facts: tuple[dict[str, Any], ...],
        sample_variants: tuple[dict[str, Any], ...],
        test_conditions: tuple[dict[str, Any], ...],
        baseline_references: tuple[dict[str, Any], ...],
        measurement_results: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        anchor_lookup = self._index_rows_by_id(evidence_anchors, "anchor_id")
        sample_lookup = self._index_rows_by_id(sample_variants, "variant_id")
        test_condition_lookup = self._index_rows_by_id(test_conditions, "test_condition_id")
        baseline_lookup = self._index_rows_by_id(baseline_references, "baseline_id")
        document_material_lookup: dict[str, dict[str, Any]] = {}
        for variant in sample_variants:
            document_id = str(variant.get("document_id") or "")
            if document_id and document_id not in document_material_lookup:
                document_material_lookup[document_id] = self._normalize_material_system_payload(
                    variant.get("host_material_system")
                )

        rows: list[dict[str, Any]] = []
        for method_fact in method_facts:
            anchors = self._resolve_anchor_rows(
                method_fact.get("evidence_anchor_ids"),
                anchor_lookup,
            )
            method_role = self._normalize_method_role(method_fact.get("method_role"))
            rows.append(
                {
                    "evidence_id": self._method_fact_evidence_id(method_fact.get("method_id")),
                    "document_id": str(method_fact.get("document_id") or ""),
                    "collection_id": collection_id,
                    "claim_text": self._summarize_method_fact_card(method_fact),
                    "claim_type": (
                        "process"
                        if method_role == "process"
                        else "characterization"
                        if method_role == "characterization"
                        else "qualitative"
                    ),
                    "evidence_source_type": self._determine_evidence_source_type(
                        anchors,
                        "method" if method_role == "process" else "text",
                    ),
                    "evidence_anchors": anchors,
                    "material_system": document_material_lookup.get(
                        str(method_fact.get("document_id") or ""),
                        {},
                    ),
                    "condition_context": self._condition_context_from_method_fact(method_fact),
                    "confidence": round(float(method_fact.get("confidence") or 0.0), 2),
                    "traceability_status": (
                        TRACEABILITY_STATUS_DIRECT if anchors else TRACEABILITY_STATUS_MISSING
                    ),
                }
            )

        for result in measurement_results:
            variant = sample_lookup.get(str(result.get("variant_id") or ""), {})
            test_condition = test_condition_lookup.get(
                str(result.get("test_condition_id") or ""),
                {},
            )
            baseline = baseline_lookup.get(str(result.get("baseline_id") or ""), {})
            anchors = self._resolve_anchor_rows(result.get("evidence_anchor_ids"), anchor_lookup)
            rows.append(
                {
                    "evidence_id": self._measurement_result_evidence_id(result.get("result_id")),
                    "document_id": str(result.get("document_id") or ""),
                    "collection_id": collection_id,
                    "claim_text": self._measurement_result_claim_text(result, variant),
                    "claim_type": "property",
                    "evidence_source_type": self._determine_evidence_source_type(
                        anchors,
                        self._normalize_scalar_text(result.get("result_source_type")) or "text",
                    ),
                    "evidence_anchors": anchors,
                    "material_system": self._normalize_material_system_payload(
                        variant.get("host_material_system")
                    ),
                    "condition_context": self._normalize_condition_context_payload(
                        self._condition_context_from_records(test_condition, baseline).model_dump(
                            exclude_none=True
                        )
                    ),
                    "confidence": 0.0,
                    "traceability_status": str(
                        result.get("traceability_status") or TRACEABILITY_STATUS_MISSING
                    ),
                }
            )

        return self._normalize_card_records(rows, collection_id)

    def _resolve_anchor_rows(
        self,
        anchor_ids: Any,
        anchor_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for anchor_id in self._normalize_list(anchor_ids):
            anchor = anchor_lookup.get(anchor_id)
            if anchor is not None:
                resolved.append(dict(anchor))
        return resolved

    def _determine_evidence_source_type(
        self,
        anchors: list[dict[str, Any]],
        fallback: str,
    ) -> str:
        for anchor in anchors:
            source_type = self._normalize_scalar_text(anchor.get("source_type"))
            if source_type in _EVIDENCE_SOURCE_TYPES:
                return source_type
        return fallback if fallback in _EVIDENCE_SOURCE_TYPES else "text"

    def _measurement_result_evidence_id(self, result_id: Any) -> str:
        return f"ev_result_{self._normalize_scalar_text(result_id) or 'missing'}"

    def _method_fact_evidence_id(self, method_id: Any) -> str:
        return f"ev_method_{self._normalize_scalar_text(method_id) or 'missing'}"

    def _summarize_method_fact_card(
        self,
        method_fact: Mapping[str, Any],
    ) -> str:
        source = dict(method_fact)
        method_role = self._normalize_method_role(source.get("method_role"))
        method_name = self._normalize_scalar_text(source.get("method_name")) or "unspecified method"
        payload = self._normalize_method_payload(source.get("method_payload"))
        details = self._normalize_scalar_text(payload.get("details"))
        if details:
            return details
        if method_role == "characterization":
            return f"Characterization used {method_name}."
        if method_role == "test":
            return f"Testing used {method_name}."
        return f"Process used {method_name}."

    def _measurement_result_claim_text(
        self,
        result_row: Mapping[str, Any],
        variant_row: dict[str, Any] | None,
    ) -> str:
        source = dict(result_row)
        value_payload = self._normalize_object(source.get("value_payload"))
        if isinstance(value_payload, dict):
            statement = self._normalize_scalar_text(value_payload.get("statement"))
            if statement:
                return statement
        result_summary, _ = self._summarize_result(
            result_type=self._normalize_result_type(source.get("result_type")),
            value_payload=source.get("value_payload"),
            unit=self._sanitize_unit(source.get("unit")),
        )
        variant_label = self._normalize_scalar_text((variant_row or {}).get("variant_label")) or "sample"
        property_name = self._normalize_property_name(source.get("property_normalized"))
        if result_summary and result_summary != "Result reported":
            return f"{variant_label} reported {property_name} of {result_summary}."
        return f"{variant_label} reported {property_name}."

    def _resolve_characterization_window_text(
        self,
        *,
        text_windows: list[dict[str, Any]],
        anchor_block_ids: set[str],
        method_name: str | None,
        method_payload: Any,
    ) -> str | None:
        for text_window in text_windows:
            window_text = str(text_window.get("text") or "").strip()
            if not window_text:
                continue
            window_block_ids = {
                str(block_id).strip()
                for block_id in self._normalize_list(text_window.get("block_ids"))
                if str(block_id).strip()
            }
            if anchor_block_ids and window_block_ids & anchor_block_ids:
                return window_text
            if method_name and method_name.lower() in window_text.lower():
                return window_text
        payload = self._normalize_method_payload(method_payload)
        return self._normalize_scalar_text(payload.get("details"))

    def _select_supporting_text_windows(
        self,
        *,
        text_windows: list[dict[str, Any]],
        table_row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not text_windows:
            return []

        target_heading_path = self._normalize_scalar_text(table_row.get("heading_path"))

        def _score(window: dict[str, Any]) -> tuple[int, int]:
            score = 0
            heading_path = self._normalize_scalar_text(window.get("heading_path"))
            if target_heading_path and heading_path == target_heading_path:
                score += 3
            elif target_heading_path and heading_path and (
                target_heading_path in heading_path or heading_path in target_heading_path
            ):
                score += 1
            if self._normalize_scalar_text(window.get("block_type")) == "table_caption":
                score += 2
            if str(window.get("text") or "").strip():
                score += 1
            return score, -(self._safe_int(window.get("order")) or 0)

        ranked = sorted(text_windows, key=_score, reverse=True)
        selected = [
            window
            for window in ranked
            if str(window.get("text") or "").strip()
        ]
        return selected[:_MAX_SUPPORTING_TEXT_WINDOWS]

    def _select_batch_supporting_text_windows(
        self,
        *,
        text_windows: list[dict[str, Any]],
        table_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen: set[tuple[str | None, str | None, int | None]] = set()
        selected: list[dict[str, Any]] = []
        for row in table_rows:
            for window in self._select_supporting_text_windows(
                text_windows=text_windows,
                table_row=row,
            ):
                key = (
                    self._normalize_scalar_text(window.get("heading_path")),
                    self._normalize_scalar_text(window.get("text")),
                    self._safe_int(window.get("page")),
                )
                if key in seen:
                    continue
                seen.add(key)
                selected.append(window)
                if len(selected) >= _MAX_SUPPORTING_TEXT_WINDOWS:
                    return selected
        return selected

    def _select_text_windows_for_extraction(
        self,
        *,
        text_windows: list[dict[str, Any]],
        profile: dict[str, Any],
        has_table_rows: bool,
    ) -> list[dict[str, Any]]:
        if not text_windows:
            return []

        scored_windows: list[dict[str, Any]] = []
        for index, window in enumerate(text_windows, start=1):
            score = self._score_text_window_for_extraction(
                window=window,
                has_table_rows=has_table_rows,
            )
            if score is None:
                continue
            scored_windows.append(
                {
                    "index": index,
                    "score": score,
                    "is_intro": self._is_introductory_window(window),
                    "window": window,
                }
            )

        if not scored_windows:
            return []

        intro_windows = [item for item in scored_windows if item["is_intro"]]
        non_intro_windows = [item for item in scored_windows if not item["is_intro"]]
        selected = list(non_intro_windows)
        if has_table_rows and len(selected) > _MAX_TEXT_WINDOWS_PER_DOCUMENT:
            selected = self._limit_ranked_windows(
                selected,
                limit=_MAX_TEXT_WINDOWS_PER_DOCUMENT,
            )

        selected.extend(
            self._limit_ranked_windows(
                intro_windows,
                limit=_INTRODUCTION_WINDOW_LIMIT,
            )
        )
        if not selected:
            selected = self._limit_ranked_windows(scored_windows, limit=_INTRODUCTION_WINDOW_LIMIT)

        return [
            item["window"]
            for item in sorted(selected, key=lambda item: item["index"])
        ]

    def _build_objective_route_gate(
        self,
        routes: tuple[ObjectiveEvidenceRoute, ...],
    ) -> dict[str, dict[str, set[str]]] | None:
        if not routes:
            return None

        route_gate: dict[str, dict[str, set[str]]] = {}
        for route in routes:
            if not route.extractable or route.role == "low_value_or_irrelevant":
                continue
            document_id = self._normalize_scalar_text(route.document_id)
            source_ref = self._normalize_scalar_text(route.source_ref)
            if not document_id or not source_ref:
                continue
            document_gate = route_gate.setdefault(
                document_id,
                {"text_windows": set(), "tables": set()},
            )
            if (
                route.source_kind == "text_window"
                and route.role in _PAPER_FACT_TEXT_ROUTE_ROLES
            ):
                document_gate["text_windows"].add(source_ref)
            elif route.source_kind == "table":
                document_gate["tables"].add(source_ref)
        return route_gate

    def _select_route_gated_text_windows(
        self,
        *,
        text_windows: list[dict[str, Any]],
        document_id: str,
        route_gate: dict[str, dict[str, set[str]]],
    ) -> list[dict[str, Any]]:
        allowed_refs = route_gate.get(document_id, {}).get("text_windows", set())
        if not allowed_refs:
            return []

        selected: list[dict[str, Any]] = []
        for window in text_windows:
            window_id = self._normalize_scalar_text(window.get("window_id"))
            block_ids = {
                block_id
                for block_id in (
                    self._normalize_scalar_text(item)
                    for item in self._normalize_list(window.get("block_ids"))
                )
                if block_id
            }
            if window_id in allowed_refs or bool(block_ids & allowed_refs):
                selected.append(window)
        return selected

    def _select_route_gated_table_rows(
        self,
        *,
        table_rows: list[dict[str, Any]],
        document_id: str,
        grouped_row_cells: dict[tuple[str, int], list[dict[str, Any]]],
        route_gate: dict[str, dict[str, set[str]]],
    ) -> list[dict[str, Any]]:
        allowed_table_ids = route_gate.get(document_id, {}).get("tables", set())
        if not allowed_table_ids:
            return []

        routed_rows = [
            row
            for row in table_rows
            if self._normalize_scalar_text(row.get("table_id")) in allowed_table_ids
        ]
        return self._select_table_rows_for_extraction(
            table_rows=routed_rows,
            grouped_row_cells=grouped_row_cells,
        )

    def _select_table_rows_for_extraction(
        self,
        *,
        table_rows: list[dict[str, Any]],
        grouped_row_cells: dict[tuple[str, int], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for row in table_rows:
            table_id = str(row.get("table_id") or "")
            row_index = self._safe_int(row.get("row_index"))
            row_cells = grouped_row_cells.get((table_id, row_index), [])
            if self._should_extract_table_row(row=row, row_cells=row_cells):
                selected.append(row)
        return selected

    def _batch_table_rows_for_extraction(
        self,
        table_rows: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        batches: list[list[dict[str, Any]]] = []
        current_table_rows: list[dict[str, Any]] = []

        def flush_table_rows() -> None:
            if not current_table_rows:
                return
            if len(current_table_rows) <= _MAX_WHOLE_TABLE_EXTRACTION_ROWS:
                batches.append(list(current_table_rows))
                return
            for index in range(0, len(current_table_rows), _TABLE_ROWS_PER_EXTRACTION_BATCH):
                batches.append(
                    current_table_rows[index:index + _TABLE_ROWS_PER_EXTRACTION_BATCH]
                )

        current_table_id: str | None = None
        for row in table_rows:
            table_id = str(row.get("table_id") or "")
            if current_table_rows and table_id != current_table_id:
                flush_table_rows()
                current_table_rows = []
            current_table_id = table_id
            current_table_rows.append(row)
        flush_table_rows()
        return batches

    def _select_text_window_objective_context(
        self,
        objective_contexts: tuple[ObjectiveContext, ...],
        *,
        text_window: dict[str, Any],
    ) -> ObjectiveContext | None:
        if not objective_contexts:
            return None
        text = " ".join(
            part
            for part in (
                self._normalize_scalar_text(text_window.get("heading")),
                self._normalize_scalar_text(text_window.get("heading_path")),
                self._normalize_scalar_text(text_window.get("text")),
            )
            if part
        )
        return self._select_best_objective_context(objective_contexts, text)

    def _select_table_batch_objective_context(
        self,
        objective_contexts: tuple[ObjectiveContext, ...],
        *,
        document_id: str,
        table_id: str,
        table_context: dict[str, Any] | None,
        table_rows: list[dict[str, Any]],
        row_cells_by_index: dict[int | None, list[dict[str, Any]]],
    ) -> tuple[ObjectiveContext | None, Mapping[str, Any] | None]:
        if not objective_contexts:
            return None, None

        route_candidates: list[tuple[int, int, ObjectiveContext, Mapping[str, Any]]] = []
        table_text = self._build_objective_table_match_text(
            table_context=table_context,
            table_rows=table_rows,
            row_cells_by_index=row_cells_by_index,
        )
        for context_index, context in enumerate(objective_contexts):
            for route in context.routing_hints:
                route_table_id = self._normalize_scalar_text(route.get("table_id"))
                if route_table_id != table_id:
                    continue
                route_document_id = self._normalize_scalar_text(route.get("document_id"))
                if route_document_id and route_document_id != document_id:
                    continue
                score = self._score_objective_table_route(route)
                score += self._score_objective_context_for_text(context, table_text)
                route_candidates.append((score, -context_index, context, route))
        if route_candidates:
            _, _, selected_context, selected_route = max(
                route_candidates,
                key=lambda item: (item[0], item[1]),
            )
            return selected_context, selected_route

        selected_context = self._select_best_objective_context(
            objective_contexts,
            table_text,
        )
        return selected_context, None

    def _select_best_objective_context(
        self,
        objective_contexts: tuple[ObjectiveContext, ...],
        text: str,
    ) -> ObjectiveContext | None:
        if len(objective_contexts) == 1:
            return objective_contexts[0]
        scored = [
            (self._score_objective_context_for_text(context, text), -index, context)
            for index, context in enumerate(objective_contexts)
        ]
        positive_scores = [item for item in scored if item[0] > 0]
        if not positive_scores:
            return None
        positive_scores.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best_score = positive_scores[0][0]
        if len(positive_scores) > 1 and positive_scores[1][0] == best_score:
            return None
        return positive_scores[0][2]

    def _score_objective_table_route(self, route: Mapping[str, Any]) -> int:
        role = self._normalize_scalar_text(route.get("role"))
        strength = self._normalize_scalar_text(route.get("strength"))
        score = 0
        if role == "result_table":
            score += 100
        elif role == "condition_context":
            score += 50
        if strength == "strong":
            score += 20
        elif strength == "medium":
            score += 10
        score += 5 * len(self._normalize_list(route.get("matched_property_axes")))
        score += 2 * len(self._normalize_list(route.get("matched_variable_process_axes")))
        return score

    def _score_objective_context_for_text(
        self,
        objective_context: ObjectiveContext,
        text: str,
    ) -> int:
        score = 0
        score += 3 * self._count_objective_terms_in_text(
            objective_context.target_property_axes,
            text,
        )
        score += 2 * self._count_objective_terms_in_text(
            objective_context.variable_process_axes,
            text,
        )
        score += 2 * self._count_objective_terms_in_text(
            objective_context.material_scope,
            text,
        )
        score += self._count_objective_terms_in_text(
            objective_context.process_context_axes,
            text,
        )
        return score

    def _count_objective_terms_in_text(
        self,
        terms: tuple[str, ...],
        text: str,
    ) -> int:
        text_key = self._objective_context_match_key(text)
        if not text_key:
            return 0
        text_tokens = set(text_key.split())
        return sum(
            1
            for term in terms
            if self._objective_term_matches_text(
                term,
                text_key=text_key,
                text_tokens=text_tokens,
            )
        )

    def _objective_term_matches_text(
        self,
        term: str,
        *,
        text_key: str,
        text_tokens: set[str],
    ) -> bool:
        term_key = self._objective_context_match_key(term)
        if not term_key:
            return False
        if term_key in text_key:
            return True
        term_tokens = term_key.split()
        if term_tokens and all(token in text_tokens for token in term_tokens):
            return True
        acronym = "".join(token[0] for token in term_tokens if token)
        return bool(len(acronym) > 1 and acronym in text_tokens)

    def _objective_context_match_key(self, value: Any) -> str:
        text = self._normalize_scalar_text(value) or ""
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def _build_objective_table_match_text(
        self,
        *,
        table_context: dict[str, Any] | None,
        table_rows: list[dict[str, Any]],
        row_cells_by_index: dict[int | None, list[dict[str, Any]]],
    ) -> str:
        parts = [
            self._normalize_scalar_text((table_context or {}).get("caption_text")),
            self._normalize_scalar_text((table_context or {}).get("heading_path")),
            self._normalize_scalar_text((table_context or {}).get("table_text")),
        ]
        for header in (table_context or {}).get("column_headers") or []:
            parts.append(self._normalize_scalar_text(header))
        for row in table_rows:
            row_index = self._safe_int(row.get("row_index"))
            parts.append(self._normalize_scalar_text(row.get("row_text")))
            for cell in row_cells_by_index.get(row_index, []):
                parts.append(self._normalize_scalar_text(cell.get("header_path")))
                parts.append(self._normalize_scalar_text(cell.get("cell_text")))
                parts.append(self._normalize_scalar_text(cell.get("unit_hint")))
        return " ".join(part for part in parts if part)

    def _score_text_window_for_extraction(
        self,
        *,
        window: dict[str, Any],
        has_table_rows: bool,
    ) -> int | None:
        text = str(window.get("text") or "").strip()
        if not text:
            return None

        block_type = (self._normalize_scalar_text(window.get("block_type")) or "").lower()
        if block_type in {"title", "heading", "figure_caption", "table_caption"}:
            return None

        heading_path = self._normalize_scalar_text(window.get("heading_path")) or ""
        lowered_heading = heading_path.lower()
        lowered_text = text.lower()
        if self._contains_any_term(lowered_heading, _LOW_VALUE_HEADING_TERMS):
            return None

        signal_score = self._signal_score(lowered_text, text)
        is_intro = self._contains_any_term(lowered_heading, _INTRODUCTION_HEADING_TERMS)
        if is_intro and signal_score == 0:
            return None

        score = signal_score
        if self._contains_any_term(lowered_heading, _METHOD_HEADING_TERMS):
            score += 4
        if self._contains_any_term(lowered_heading, _CHARACTERIZATION_HEADING_TERMS):
            score += 3
        if self._contains_any_term(lowered_heading, _RESULT_HEADING_TERMS):
            score += 1 if has_table_rows else 2
        if is_intro:
            score -= 2
        return score if score > 0 else None

    def _should_extract_table_row(
        self,
        *,
        row: dict[str, Any],
        row_cells: list[dict[str, Any]],
    ) -> bool:
        row_summary = (
            self._normalize_scalar_text(row.get("row_text"))
            or self._build_table_row_summary(row_cells)
        )
        if not row_summary:
            return False

        nonempty_cells = [
            cell for cell in row_cells if self._normalize_scalar_text(cell.get("cell_text"))
        ]
        if len(nonempty_cells) < 2:
            return False

        header_text = " ".join(
            self._normalize_scalar_text(cell.get("header_path")) or ""
            for cell in row_cells
        ).strip()
        if self._contains_any_term(header_text.lower(), _LOW_VALUE_HEADING_TERMS):
            return False

        combined_text = "\n".join(part for part in (header_text, row_summary) if part)
        if self._signal_score(combined_text.lower(), combined_text) > 0:
            return True
        return any(self._normalize_scalar_text(cell.get("unit_hint")) for cell in row_cells)

    def _limit_ranked_windows(
        self,
        windows: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or len(windows) <= limit:
            return list(windows)
        ranked = sorted(
            windows,
            key=lambda item: (item["score"], -item["index"]),
            reverse=True,
        )
        return ranked[:limit]

    def _is_introductory_window(self, window: dict[str, Any]) -> bool:
        heading_path = (self._normalize_scalar_text(window.get("heading_path")) or "").lower()
        return self._contains_any_term(heading_path, _INTRODUCTION_HEADING_TERMS)

    def _signal_score(self, lowered_text: str, raw_text: str) -> int:
        score = 0
        if any(token in lowered_text for token, _ in _PROPERTY_HINTS):
            score += 2
        if self._contains_any_term(lowered_text, _PROCESS_SIGNAL_TERMS):
            score += 2
        if self._contains_any_term(lowered_text, _COMPARISON_SIGNAL_TERMS):
            score += 2
        if any(method.lower() in lowered_text for method in _CHARACTERIZATION_METHODS):
            score += 2
        if _EXTRACTION_UNIT_PATTERN.search(raw_text):
            score += 1
        return score

    def _contains_any_term(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    def _execute_extraction_jobs(
        self,
        *,
        extractor: CoreLLMStructuredExtractor,
        jobs: list[dict[str, Any]],
        kind: str,
        max_extraction_concurrency: int,
    ) -> list[dict[str, Any]]:
        if not jobs:
            return []
        if len(jobs) == 1:
            return [self._execute_extraction_job(extractor=extractor, job=jobs[0], kind=kind)]

        with ThreadPoolExecutor(
            max_workers=min(max_extraction_concurrency, len(jobs)),
        ) as executor:
            futures = [
                executor.submit(
                    self._execute_extraction_job,
                    extractor=extractor,
                    job=job,
                    kind=kind,
                )
                for job in jobs
            ]
            return [future.result() for future in futures]

    def _execute_extraction_job(
        self,
        *,
        extractor: CoreLLMStructuredExtractor,
        job: dict[str, Any],
        kind: str,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        try:
            if kind == "text_window":
                parsed = extractor.extract_text_window_mentions(job["payload"])
            elif kind == "table_batch":
                parsed = extractor.extract_table_batch_mentions(job["payload"])
            else:
                raise ValueError(f"unsupported extraction job kind: {kind}")
        except Exception as exc:
            return {
                "parsed": None,
                "elapsed_s": perf_counter() - started_at,
                "error": exc,
            }
        return {
            "parsed": parsed,
            "elapsed_s": perf_counter() - started_at,
            "error": None,
        }

    def _build_characterization_observations(
        self,
        *,
        collection_id: str,
        method_facts: tuple[dict[str, Any], ...],
        evidence_anchors: tuple[dict[str, Any], ...],
        text_windows_by_doc: dict[str, list[dict[str, Any]]],
        sample_variants: tuple[dict[str, Any], ...],
        measurement_results: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        anchor_lookup = {
            str(row.get("anchor_id") or ""): dict(row)
            for row in evidence_anchors
        }
        dedicated_rows = [
            *self._build_table_derived_characterization_observations(
                collection_id=collection_id,
                sample_variants=sample_variants,
                measurement_results=measurement_results,
            ),
            *self._build_text_derived_characterization_observations(
                collection_id=collection_id,
                text_windows_by_doc=text_windows_by_doc,
                evidence_anchors=evidence_anchors,
            ),
        ]
        rows.extend(dedicated_rows)
        documents_with_dedicated_observations = {
            self._normalize_scalar_text(row.get("document_id"))
            for row in dedicated_rows
            if self._normalize_scalar_text(row.get("document_id"))
        }

        if not method_facts:
            return self._normalize_characterization_records(rows, collection_id)

        characterization_facts = [
            method_fact
            for method_fact in method_facts
            if str(method_fact.get("method_role") or "") == "characterization"
        ]
        for method_fact in characterization_facts:
            document_id = str(method_fact.get("document_id") or "")
            if not document_id:
                continue
            if document_id in documents_with_dedicated_observations:
                continue
            text_windows = text_windows_by_doc.get(document_id, [])
            anchor_ids = self._normalize_list(method_fact.get("evidence_anchor_ids"))
            anchor_block_ids = {
                self._normalize_scalar_text(anchor_lookup.get(anchor_id, {}).get("block_id"))
                or self._normalize_scalar_text(anchor_lookup.get(anchor_id, {}).get("section_id"))
                for anchor_id in anchor_ids
            }
            anchor_block_ids.discard(None)
            section_text = self._resolve_characterization_window_text(
                text_windows=text_windows,
                anchor_block_ids=anchor_block_ids,
                method_name=self._normalize_scalar_text(method_fact.get("method_name")),
                method_payload=method_fact.get("method_payload"),
            )
            if not section_text:
                continue
            observed_value, observed_unit = self._extract_observed_value_and_unit(section_text)
            method_name = self._normalize_scalar_text(method_fact.get("method_name")) or ""
            rows.append(
                CharacterizationObservation.from_mapping(
                    {
                        "observation_id": f"obs_{uuid4().hex[:12]}",
                        "document_id": document_id,
                        "collection_id": collection_id,
                        "variant_id": None,
                        "characterization_type": method_name.lower(),
                        "observation_text": section_text,
                        "observed_value": observed_value,
                        "observed_unit": observed_unit,
                        "condition_context": self._condition_context_from_method_fact(method_fact),
                        "evidence_anchor_ids": anchor_ids,
                        "confidence": max(float(method_fact.get("confidence") or 0.0), 0.76),
                        "epistemic_status": EPISTEMIC_DIRECTLY_OBSERVED,
                    }
                ).to_record()
            )

        return self._normalize_characterization_records(
            rows,
            collection_id,
        )

    def _build_table_derived_characterization_observations(
        self,
        *,
        collection_id: str,
        sample_variants: tuple[dict[str, Any], ...],
        measurement_results: tuple[dict[str, Any], ...],
    ) -> list[dict[str, Any]]:
        table_results = [
            row
            for row in measurement_results
            if self._normalize_scalar_text(row.get("result_source_type")) == "table"
            and self._measurement_numeric_value(
                self._normalize_object(row.get("value_payload"))
                if isinstance(self._normalize_object(row.get("value_payload")), dict)
                else {}
            )
            is not None
        ]
        if not table_results:
            return []

        sample_lookup = self._index_rows_by_id(sample_variants, "variant_id")
        rows: list[dict[str, Any]] = []
        documents = sorted(
            {
                self._normalize_scalar_text(row.get("document_id"))
                for row in table_results
                if self._normalize_scalar_text(row.get("document_id"))
            }
        )
        for document_id in documents:
            document_results = [
                row
                for row in table_results
                if self._normalize_scalar_text(row.get("document_id")) == document_id
            ]
            density_results = [
                row
                for row in document_results
                if self._normalize_property_name(row.get("property_normalized"))
                in {"density", "relative_density"}
            ]
            rows.extend(
                self._build_density_characterization_observations(
                    collection_id=collection_id,
                    document_id=document_id,
                    density_results=density_results,
                    sample_lookup=sample_lookup,
                )
            )
            rows.extend(
                self._build_strategy_characterization_observations(
                    collection_id=collection_id,
                    document_id=document_id,
                    sample_variants=self._filter_rows_by_document(
                        sample_variants,
                        document_id,
                    ),
                    measurement_results=document_results,
                    sample_lookup=sample_lookup,
                )
            )
        return rows

    def _build_density_characterization_observations(
        self,
        *,
        collection_id: str,
        document_id: str,
        density_results: list[dict[str, Any]],
        sample_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not density_results:
            return []
        values = [
            (
                row,
                self._measurement_numeric_value(
                    self._normalize_object(row.get("value_payload"))
                    if isinstance(self._normalize_object(row.get("value_payload")), dict)
                    else {}
                ),
            )
            for row in density_results
        ]
        numeric_values = [(row, value) for row, value in values if value is not None]
        if not numeric_values:
            return []

        min_value = min(value for _, value in numeric_values)
        max_row, max_value = max(numeric_values, key=lambda item: item[1])
        anchor_ids = self._dedupe_preserving_order(
            [
                anchor_id
                for row, _ in numeric_values
                for anchor_id in self._normalize_list(row.get("evidence_anchor_ids"))
            ]
        )
        rows = [
            CharacterizationObservation.from_mapping(
                {
                    "observation_id": f"obs_{uuid4().hex[:12]}",
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "variant_id": None,
                    "characterization_type": "density_porosity_sem_imagej",
                    "observation_text": (
                        "Table-derived relative density and porosity evidence "
                        f"covers {len(numeric_values)} samples with relative "
                        f"density from {min_value:g}% to {max_value:g}%."
                    ),
                    "observed_value": {
                        "relative_density_min": min_value,
                        "relative_density_max": max_value,
                        "sample_count": len(numeric_values),
                    },
                    "observed_unit": "%",
                    "condition_context": {
                        "test": {"methods": ["SEM", "ImageJ"], "method": "SEM / ImageJ"}
                    },
                    "evidence_anchor_ids": anchor_ids,
                    "confidence": 0.88,
                    "epistemic_status": EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
                }
            ).to_record()
        ]

        max_variant_id = self._normalize_scalar_text(max_row.get("variant_id"))
        max_variant = sample_lookup.get(max_variant_id or "", {})
        max_label = self._normalize_scalar_text(max_variant.get("variant_label")) or "sample"
        rows.append(
            CharacterizationObservation.from_mapping(
                {
                    "observation_id": f"obs_{uuid4().hex[:12]}",
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "variant_id": max_variant_id,
                    "characterization_type": "highest_density_sample",
                    "observation_text": (
                        f"Sample {max_label} has the highest table-derived "
                        f"relative density at {max_value:g}%."
                    ),
                    "observed_value": {"relative_density": max_value},
                    "observed_unit": "%",
                    "condition_context": {
                        "test": {"methods": ["SEM", "ImageJ"], "method": "SEM / ImageJ"}
                    },
                    "evidence_anchor_ids": self._normalize_list(
                        max_row.get("evidence_anchor_ids")
                    ),
                    "confidence": 0.9,
                    "epistemic_status": EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
                }
            ).to_record()
        )
        return rows

    def _build_strategy_characterization_observations(
        self,
        *,
        collection_id: str,
        document_id: str,
        sample_variants: list[dict[str, Any]],
        measurement_results: list[dict[str, Any]],
        sample_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        variants_by_strategy: dict[str, list[dict[str, Any]]] = {}
        for variant in sample_variants:
            process_context = self._normalize_condition_payload(
                variant.get("process_context")
            )
            strategy = self._normalize_scalar_text(process_context.get("scan_strategy"))
            if strategy:
                variants_by_strategy.setdefault(strategy.upper(), []).append(variant)
        rows: list[dict[str, Any]] = []
        for strategy in sorted(variants_by_strategy):
            variants = variants_by_strategy[strategy]
            variant_ids = {
                self._normalize_scalar_text(variant.get("variant_id"))
                for variant in variants
                if self._normalize_scalar_text(variant.get("variant_id"))
            }
            density_values = []
            anchor_ids = []
            for result in measurement_results:
                if self._normalize_scalar_text(result.get("variant_id")) not in variant_ids:
                    continue
                if self._normalize_property_name(result.get("property_normalized")) != "density":
                    continue
                payload = self._normalize_object(result.get("value_payload"))
                value = self._measurement_numeric_value(payload if isinstance(payload, dict) else {})
                if value is not None:
                    density_values.append(value)
                anchor_ids.extend(self._normalize_list(result.get("evidence_anchor_ids")))
            if not density_values:
                continue
            labels = [
                self._normalize_scalar_text(sample_lookup.get(variant_id or "", {}).get("variant_label"))
                or self._normalize_scalar_text(variant_id)
                for variant_id in sorted(variant_ids)
            ]
            rows.append(
                CharacterizationObservation.from_mapping(
                    {
                        "observation_id": f"obs_{uuid4().hex[:12]}",
                        "document_id": document_id,
                        "collection_id": collection_id,
                        "variant_id": None,
                        "characterization_type": f"scan_strategy_{strategy.lower()}",
                        "observation_text": (
                            f"Scan strategy {strategy} appears in samples "
                            f"{', '.join(label for label in labels if label)} with "
                            f"table-derived relative density from {min(density_values):g}% "
                            f"to {max(density_values):g}%."
                        ),
                        "observed_value": {
                            "scan_strategy": strategy,
                            "relative_density_min": min(density_values),
                            "relative_density_max": max(density_values),
                            "sample_labels": [label for label in labels if label],
                        },
                        "observed_unit": "%",
                        "condition_context": {
                            "test": {"methods": ["SEM", "ImageJ"], "method": "SEM / ImageJ"}
                        },
                        "evidence_anchor_ids": self._dedupe_preserving_order(anchor_ids),
                        "confidence": 0.82,
                        "epistemic_status": EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
                    }
                ).to_record()
            )
        return rows

    def _build_text_derived_characterization_observations(
        self,
        *,
        collection_id: str,
        text_windows_by_doc: dict[str, list[dict[str, Any]]],
        evidence_anchors: tuple[dict[str, Any], ...],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for document_id, text_windows in text_windows_by_doc.items():
            for observation_type, terms, text_builder in (
                (
                    "sectioned_microstructure",
                    ("horizontal", "vertical", "sem"),
                    lambda quote: (
                        "SEM characterization covers horizontal and vertical "
                        "sections for microstructure and pore distribution."
                    ),
                ),
                (
                    "dendrite_cellular_trend",
                    ("dendrite", "scan"),
                    lambda quote: quote,
                ),
                (
                    "pore_defect_interpretation",
                    ("pore", "balling"),
                    lambda quote: quote,
                ),
            ):
                selected = self._select_characterization_observation_window(
                    text_windows,
                    required_terms=terms,
                )
                if selected is None:
                    continue
                quote = self._select_characterization_observation_quote(
                    selected,
                    required_terms=terms,
                )
                if not quote:
                    continue
                rows.append(
                    CharacterizationObservation.from_mapping(
                        {
                            "observation_id": f"obs_{uuid4().hex[:12]}",
                            "document_id": document_id,
                            "collection_id": collection_id,
                            "variant_id": None,
                            "characterization_type": observation_type,
                            "observation_text": text_builder(quote),
                            "observed_value": {"statement": quote},
                            "observed_unit": None,
                            "condition_context": {
                                "test": {
                                    "methods": self._extract_characterization_methods(
                                        quote
                                    )
                                    or ["SEM"],
                                    "method": "SEM",
                                }
                            },
                            "evidence_anchor_ids": self._anchor_ids_for_text_window(
                                selected,
                                evidence_anchors,
                            ),
                            "confidence": 0.8,
                            "epistemic_status": EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
                        }
                    ).to_record()
                )
        return rows

    def _select_characterization_observation_window(
        self,
        text_windows: list[dict[str, Any]],
        *,
        required_terms: tuple[str, ...],
    ) -> dict[str, Any] | None:
        scored: list[tuple[int, dict[str, Any]]] = []
        for window in text_windows:
            text = " ".join(
                part
                for part in (
                    self._normalize_scalar_text(window.get("heading")),
                    self._normalize_scalar_text(window.get("heading_path")),
                    self._normalize_scalar_text(window.get("text")),
                )
                if part
            )
            lowered = text.lower()
            score = sum(1 for term in required_terms if term in lowered)
            if score == len(required_terms):
                scored.append((score, window))
        if not scored:
            return None
        scored.sort(
            key=lambda item: (
                item[0],
                -(self._safe_int(item[1].get("order")) or 0),
            ),
            reverse=True,
        )
        return scored[0][1]

    def _select_characterization_observation_quote(
        self,
        text_window: dict[str, Any],
        *,
        required_terms: tuple[str, ...],
    ) -> str | None:
        text = self._normalize_scalar_text(text_window.get("text"))
        if not text:
            return None
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            lowered = sentence.lower()
            if all(term in lowered for term in required_terms):
                return sentence[:900].strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            lowered = sentence.lower()
            if any(term in lowered for term in required_terms):
                return sentence[:900].strip()
        return text[:900].strip()

    def _anchor_ids_for_text_window(
        self,
        text_window: dict[str, Any],
        evidence_anchors: tuple[dict[str, Any], ...],
    ) -> list[str]:
        window_block_ids = {
            self._normalize_scalar_text(block_id)
            for block_id in self._normalize_list(text_window.get("block_ids"))
        }
        window_block_ids.discard(None)
        window_id = self._normalize_scalar_text(text_window.get("window_id"))
        if window_id:
            window_block_ids.add(window_id)
        anchor_ids = []
        for anchor in evidence_anchors:
            block_id = self._normalize_scalar_text(anchor.get("block_id"))
            section_id = self._normalize_scalar_text(anchor.get("section_id"))
            if not ({block_id, section_id} & window_block_ids):
                continue
            anchor_id = self._normalize_scalar_text(anchor.get("anchor_id"))
            if anchor_id:
                anchor_ids.append(anchor_id)
        return self._dedupe_preserving_order(anchor_ids)

    def _build_structure_features(
        self,
        characterization: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        if not characterization:
            return self._normalize_structure_feature_records(())
        for observation in characterization:
            rows.extend(self._extract_structure_features_from_observation(observation))
        return self._normalize_structure_feature_records(rows)

    def _attach_variant_ids_to_characterization(
        self,
        characterization: tuple[dict[str, Any], ...],
        sample_variants: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not characterization:
            return self._normalize_characterization_records(characterization, None)
        if not sample_variants:
            return self._normalize_characterization_records(characterization, None)

        normalized: list[dict[str, Any]] = []
        for row in characterization:
            payload = dict(row)
            document_id = str(row.get("document_id") or "")
            document_variants = self._filter_rows_by_document(sample_variants, document_id)
            if len(document_variants) == 1:
                payload["variant_id"] = document_variants[0].get("variant_id")
            normalized.append(payload)
        return self._normalize_characterization_records(normalized, None)

    def _attach_variant_ids_to_baseline_references(
        self,
        baseline_references: tuple[dict[str, Any], ...],
        sample_variants: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not baseline_references:
            return self._normalize_baseline_reference_records(baseline_references, None)

        normalized: list[dict[str, Any]] = []
        for row in baseline_references:
            payload = dict(row)
            document_id = str(row.get("document_id") or "")
            label = str(row.get("baseline_label") or "").strip().lower()
            if not label:
                normalized.append(payload)
                continue
            document_variants = self._filter_rows_by_document(sample_variants, document_id)
            matched = [
                variant
                for variant in document_variants
                if str(variant.get("variant_label") or "").lower() == label
            ]
            if len(matched) == 1:
                payload["variant_id"] = matched[0].get("variant_id")
            normalized.append(payload)
        return self._normalize_baseline_reference_records(normalized, None)

    def _attach_structure_feature_ids_to_variants(
        self,
        sample_variants: tuple[dict[str, Any], ...],
        structure_features: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not sample_variants:
            return self._normalize_sample_variant_records(sample_variants, None)

        normalized: list[dict[str, Any]] = []
        for row in sample_variants:
            payload = dict(row)
            variant_id = str(row.get("variant_id") or "")
            matched = [
                feature
                for feature in structure_features
                if str(feature.get("variant_id") or "") == variant_id
            ]
            payload["structure_feature_ids"] = [
                str(feature.get("feature_id"))
                for feature in matched
                if str(feature.get("feature_id") or "").strip()
            ]
            normalized.append(payload)
        return self._normalize_sample_variant_records(normalized, None)

    def _attach_context_to_measurement_results(
        self,
        *,
        measurement_results: tuple[dict[str, Any], ...],
        characterization: tuple[dict[str, Any], ...],
        structure_features: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not measurement_results:
            return self._normalize_measurement_result_records(measurement_results, None)

        normalized: list[dict[str, Any]] = []
        for row in measurement_results:
            payload = dict(row)
            document_id = str(row.get("document_id") or "")
            variant_id = self._normalize_scalar_text(row.get("variant_id"))
            matched_characterization = self._filter_rows_by_document(characterization, document_id)
            matched_structure = self._filter_rows_by_document(structure_features, document_id)
            if variant_id:
                matched_characterization = [
                    item
                    for item in matched_characterization
                    if str(item.get("variant_id") or "") == variant_id
                ]
                matched_structure = [
                    item
                    for item in matched_structure
                    if str(item.get("variant_id") or "") == variant_id
                ]
            payload["characterization_observation_ids"] = [
                str(item.get("observation_id"))
                for item in matched_characterization
                if str(item.get("observation_id") or "").strip()
            ]
            payload["structure_feature_ids"] = [
                str(item.get("feature_id"))
                for item in matched_structure
                if str(item.get("feature_id") or "").strip()
            ]
            normalized.append(payload)
        return self._normalize_measurement_result_records(normalized, None)

    def _filter_rows_by_document(
        self,
        rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        document_id: str,
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if str(row.get("document_id") or "") == str(document_id)
        ]

    def _group_table_cells_by_row(
        self,
        table_cells: list[dict[str, Any]],
    ) -> dict[tuple[str, int], list[dict[str, Any]]]:
        grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for cell in table_cells:
            table_id = str(cell.get("table_id") or "").strip()
            row_index = self._safe_int(cell.get("row_index"))
            if not table_id or row_index is None or row_index <= 0:
                continue
            grouped.setdefault((table_id, row_index), []).append(cell)
        return grouped

    def _build_table_context_payload(
        self,
        *,
        table_context: dict[str, Any] | None,
        table_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        first_row = table_rows[0] if table_rows else {}
        if not table_context:
            return {
                "caption_text": None,
                "heading_path": self._normalize_scalar_text(first_row.get("heading_path")),
                "column_headers": [],
                "table_matrix": [],
                "table_markdown": None,
                "table_text": None,
                "page": self._safe_int(first_row.get("page")),
            }
        table_matrix = self._normalize_table_matrix(table_context.get("table_matrix"))

        return {
            "caption_text": self._normalize_scalar_text(table_context.get("caption_text")),
            "heading_path": self._normalize_scalar_text(
                table_context.get("heading_path")
            )
            or self._normalize_scalar_text(first_row.get("heading_path")),
            "column_headers": self._normalize_list(table_context.get("column_headers")),
            "table_matrix": self._bound_table_matrix_for_rows(
                table_matrix=table_matrix,
                table_rows=table_rows,
            ),
            "table_markdown": self._truncate_context_text(
                table_context.get("table_markdown"),
                _MAX_TABLE_CONTEXT_CHARS,
            ),
            "table_text": self._truncate_context_text(
                table_context.get("table_text"),
                _MAX_TABLE_CONTEXT_CHARS,
            ),
            "page": self._safe_int(table_context.get("page"))
            or self._safe_int(first_row.get("page")),
        }

    def _build_text_windows_by_document(
        self,
        blocks: tuple[dict[str, Any], ...],
    ) -> dict[str, list[dict[str, Any]]]:
        if not blocks:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in blocks:
            document_id = str(row.get("document_id") or row.get("paper_id") or row.get("id") or "")
            block_payload = dict(row)
            heading_path = self._normalize_scalar_text(block_payload.get("heading_path"))
            heading = heading_path.split(" > ")[-1].strip() if heading_path else None
            if heading is None and str(block_payload.get("block_type") or "") == "heading":
                heading = self._normalize_scalar_text(block_payload.get("text"))
            block_id = self._normalize_scalar_text(block_payload.get("block_id"))
            grouped.setdefault(document_id, []).append(
                {
                    "window_id": block_id
                    or f"window_{document_id}_{len(grouped.get(document_id, [])) + 1}",
                    "heading": heading,
                    "heading_path": heading_path,
                    "text": self._normalize_scalar_text(block_payload.get("text")) or "",
                    "order": self._safe_int(block_payload.get("block_order")) or 0,
                    "text_unit_ids": self._normalize_list(block_payload.get("text_unit_ids")),
                    "page": self._safe_int(block_payload.get("page")),
                    "char_range": block_payload.get("char_range"),
                    "block_ids": [block_id] if block_id else [],
                    "block_type": self._normalize_scalar_text(block_payload.get("block_type")),
                }
            )
        for document_id, items in grouped.items():
            grouped[document_id] = sorted(
                items,
                key=lambda item: self._safe_int(item.get("order")) or 0,
            )
        return grouped

    def _build_table_row_summary(
        self,
        row_cells: list[dict[str, Any]],
    ) -> str:
        ordered = sorted(
            row_cells,
            key=lambda item: self._safe_int(item.get("col_index")) or 0,
        )
        parts: list[str] = []
        for cell in ordered:
            header = self._normalize_scalar_text(cell.get("header_path"))
            value = self._normalize_scalar_text(cell.get("cell_text"))
            if not value:
                continue
            parts.append(f"{header}: {value}" if header else value)
        return "; ".join(parts)

    def _truncate_context_text(self, value: Any, limit: int) -> str | None:
        text = self._normalize_scalar_text(value)
        if text is None:
            return None
        if limit <= 0 or len(text) <= limit:
            return text
        return text[:limit].rstrip()

    def _normalize_property_name(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return "qualitative"
        if raw in {
            "yield_strength",
            "tensile_strength",
            "flexural_strength",
            "fatigue_life",
            "retention",
            "hardness",
            "conductivity",
            "modulus",
            "elongation",
            "strength",
        }:
            return raw
        lowered = raw.replace("_", " ")
        for token, normalized in _PROPERTY_HINTS:
            if token in lowered:
                return normalized
        normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        return normalized or "qualitative"

    def _normalize_claim_type(self, value: Any) -> str:
        lowered = str(value or "").strip().lower()
        if lowered in {"process", "characterization", "property", "mechanism"}:
            return lowered
        return "property" if "property" in lowered else "qualitative"

    def _normalize_result_type(self, value: Any) -> str:
        lowered = str(value or "").strip().lower()
        if lowered in {"scalar", "range", "retention", "trend", "optimum", "fitted_value"}:
            return lowered
        if lowered in {"measurement"}:
            return "scalar"
        if lowered in {
            "increase",
            "decrease",
            "reduction",
            "improvement",
            "agreement",
            "spatial_observation",
            "other",
            "qualitative",
        }:
            return "trend"
        return "scalar"

    def _normalize_variant_axis_type(self, value: Any) -> str | None:
        text = self._normalize_scalar_text(value)
        if text is None:
            return None
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
            return None
        lowered = text.lower()
        if "current" in lowered:
            return "induction_current"
        normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        return normalized or None

    def _normalize_scalar_variant_value(self, value: Any) -> Any:
        normalized = normalize_record_value(value)
        if normalized is None:
            return None
        if isinstance(normalized, bool):
            return str(normalized).lower()
        if isinstance(normalized, int):
            return normalized
        if isinstance(normalized, float):
            if math.isnan(normalized):
                return None
            if normalized.is_integer():
                return int(normalized)
            return normalized
        text = str(normalized).strip()
        if not text:
            return None
        if text.lower() in _NULL_LIKE_SCALAR_TEXTS:
            return None
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
            return float(text)
        return text

    def _sanitize_unit(self, value: Any) -> str | None:
        text = self._normalize_scalar_text(value)
        if text is None:
            return None
        if re.fullmatch(r"\d{4}", text):
            return None
        return text

    def _sanitize_value_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            parsed = normalize_record_value(value)
            if parsed in (None, "", [], {}):
                continue
            normalized[key] = parsed
        return normalized

    def _extract_observed_value_and_unit(
        self,
        text: str,
    ) -> tuple[float | None, str | None]:
        match = _OBSERVED_VALUE_PATTERN.search(str(text or ""))
        if match is None:
            return None, None
        return float(match.group(1)), match.group(2)

    def _extract_structure_features_from_observation(
        self,
        observation: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        observation_text = str(observation.get("observation_text") or "")
        lowered = observation_text.lower()
        observation_id = str(observation.get("observation_id") or "")
        document_id = str(observation.get("document_id") or "")
        collection_id = str(observation.get("collection_id") or "")
        variant_id = self._normalize_scalar_text(observation.get("variant_id"))

        phase_match = _PHASE_PATTERN.search(observation_text)
        if phase_match:
            rows.append(
                self._build_structure_feature_row(
                    document_id=document_id,
                    collection_id=collection_id,
                    variant_id=variant_id,
                    feature_type="phase",
                    feature_value=phase_match.group(1).lower(),
                    feature_unit=None,
                    qualitative_descriptor=observation_text,
                    source_observation_ids=[observation_id],
                    confidence=0.7,
                )
            )

        for keyword in _MORPHOLOGY_KEYWORDS:
            if keyword not in lowered:
                continue
            rows.append(
                self._build_structure_feature_row(
                    document_id=document_id,
                    collection_id=collection_id,
                    variant_id=variant_id,
                    feature_type="morphology",
                    feature_value=keyword,
                    feature_unit=None,
                    qualitative_descriptor=observation_text,
                    source_observation_ids=[observation_id],
                    confidence=0.74,
                )
            )

        grain_match = _GRAIN_SIZE_PATTERN.search(observation_text)
        if grain_match:
            rows.append(
                self._build_structure_feature_row(
                    document_id=document_id,
                    collection_id=collection_id,
                    variant_id=variant_id,
                    feature_type="grain_size",
                    feature_value=float(grain_match.group(1)),
                    feature_unit=grain_match.group(2),
                    qualitative_descriptor=observation_text,
                    source_observation_ids=[observation_id],
                    confidence=0.84,
                )
            )

        thickness_match = _THICKNESS_PATTERN.search(observation_text)
        if thickness_match:
            rows.append(
                self._build_structure_feature_row(
                    document_id=document_id,
                    collection_id=collection_id,
                    variant_id=variant_id,
                    feature_type="thickness",
                    feature_value=float(thickness_match.group(1)),
                    feature_unit=thickness_match.group(2),
                    qualitative_descriptor=observation_text,
                    source_observation_ids=[observation_id],
                    confidence=0.84,
                )
            )

        surface_area_match = _SURFACE_AREA_PATTERN.search(observation_text)
        if surface_area_match:
            rows.append(
                self._build_structure_feature_row(
                    document_id=document_id,
                    collection_id=collection_id,
                    variant_id=variant_id,
                    feature_type="surface_area",
                    feature_value=float(surface_area_match.group(1)),
                    feature_unit=surface_area_match.group(2),
                    qualitative_descriptor=observation_text,
                    source_observation_ids=[observation_id],
                    confidence=0.84,
                )
            )

        return rows

    def _build_structure_feature_row(
        self,
        *,
        document_id: str,
        collection_id: str,
        variant_id: str | None,
        feature_type: str,
        feature_value: Any,
        feature_unit: str | None,
        qualitative_descriptor: str | None,
        source_observation_ids: list[str],
        confidence: float,
    ) -> dict[str, Any]:
        return StructureFeature.from_mapping(
            {
                "feature_id": f"feat_{uuid4().hex[:12]}",
                "document_id": document_id,
                "collection_id": collection_id,
                "variant_id": variant_id,
                "feature_type": feature_type,
                "feature_value": feature_value,
                "feature_unit": feature_unit,
                "qualitative_descriptor": qualitative_descriptor,
                "source_observation_ids": source_observation_ids,
                "confidence": confidence,
                "epistemic_status": EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
            }
        ).to_record()

    def _infer_condition_template_type(
        self,
        property_type: str,
    ) -> str:
        if property_type == "tensile_mechanics":
            return "tensile_mechanics"
        if property_type == "density_porosity_microstructure":
            return "characterization"
        if property_type == "microhardness":
            return "microhardness"
        if property_type in {
            "strength",
            "tensile_strength",
            "yield_strength",
            "flexural_strength",
            "modulus",
            "elongation",
        }:
            return "tensile_mechanics"
        if property_type == "fatigue_life":
            return "fatigue"
        if property_type == "hardness":
            return "microhardness"
        if property_type == "residual_stress":
            return "residual_stress_measurement"
        if property_type == "characterization":
            return "characterization"
        return "generic_materials_measurement"

    def _infer_missing_condition_fields(
        self,
        *,
        payload: dict[str, Any],
        template_type: str,
        scope_level: str,
    ) -> list[str]:
        missing: list[str] = []
        methods = payload.get("methods") or []
        if not methods and not payload.get("method") and template_type != "generic_materials_measurement":
            missing.append("method")
        if scope_level == "experiment" and not payload.get("temperatures_c") and not payload.get("durations"):
            missing.append("process_window")
        return missing

    def _infer_condition_completeness(
        self,
        *,
        payload: dict[str, Any],
        missing_fields: list[str],
    ) -> str:
        if not payload:
            return "unresolved"
        if missing_fields:
            return "partial"
        return "complete"

    def _classify_baseline_type(
        self,
        baseline_label: str,
    ) -> str:
        lowered = str(baseline_label or "").lower()
        if any(token in lowered for token in ("as-built", "as built", "as-prepared", "as prepared", "pristine")):
            return "as_built_reference"
        if "without" in lowered and any(token in lowered for token in ("field", "heating", "induction", "beam")):
            return "same_process_without_auxiliary_field"
        if any(token in lowered for token in ("annealed", "heat treated", "post-heat", "post heat")):
            return "post_heat_treated_reference"
        if any(token in lowered for token in ("literature", "reported", "prior art", "benchmark")):
            return "literature_benchmark"
        if any(token in lowered for token in ("conventional", "wrought", "cast", "rolling")):
            return "conventional_process_reference"
        return "implicit_within_document_control"

    def _extract_anchor_ids(
        self,
        evidence_anchors: Any,
    ) -> list[str]:
        anchors = self._normalize_object(evidence_anchors)
        if not isinstance(anchors, list):
            return []
        anchor_ids: list[str] = []
        for anchor in anchors:
            if not isinstance(anchor, dict):
                continue
            anchor_id = self._normalize_scalar_text(anchor.get("anchor_id"))
            if anchor_id:
                anchor_ids.append(anchor_id)
        return anchor_ids

    def _extract_characterization_methods(self, text: Any) -> list[str]:
        source = str(text or "")
        return [method for method in _CHARACTERIZATION_METHODS if method.lower() in source.lower()]

    def _group_table_rows_by_document(
        self,
        table_rows: tuple[dict[str, Any], ...],
    ) -> dict[str, list[dict[str, Any]]]:
        if not table_rows:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in table_rows:
            document_id = str(row.get("document_id") or row.get("id") or "")
            grouped.setdefault(document_id, []).append(dict(row))
        for document_id, items in grouped.items():
            grouped[document_id] = sorted(
                items,
                key=lambda item: (
                    str(item.get("table_id") or ""),
                    self._safe_int(item.get("row_index")) or 0,
                ),
            )
        return grouped

    def _group_tables_by_document(
        self,
        tables: tuple[dict[str, Any], ...],
    ) -> dict[str, list[dict[str, Any]]]:
        if not tables:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in tables:
            document_id = str(row.get("document_id") or row.get("id") or "")
            grouped.setdefault(document_id, []).append(dict(row))
        for document_id, items in grouped.items():
            grouped[document_id] = sorted(
                items,
                key=lambda item: self._safe_int(item.get("table_order")) or 0,
            )
        return grouped

    def _group_tables_by_id(
        self,
        tables: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for table in tables:
            table_id = self._normalize_scalar_text(table.get("table_id"))
            if table_id:
                grouped[table_id] = table
        return grouped

    def _group_table_cells_by_document(
        self,
        table_cells: tuple[dict[str, Any], ...],
    ) -> dict[str, list[dict[str, Any]]]:
        if not table_cells:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in table_cells:
            document_id = str(row.get("document_id") or row.get("id") or "")
            grouped.setdefault(document_id, []).append(dict(row))
        return grouped

    def _normalize_card_records(
        self,
        cards: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        collection_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        rows = []
        for card in cards or ():
            payload = dict(card)
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            payload["evidence_anchors"] = self._normalize_object(
                payload.get("evidence_anchors")
            )
            payload["material_system"] = self._normalize_material_system_payload(
                payload.get("material_system")
            )
            payload["condition_context"] = self._normalize_condition_context_payload(
                payload.get("condition_context")
            )
            payload["confidence"] = round(float(payload.get("confidence") or 0.0), 2)
            rows.append(
                {
                    "evidence_id": payload.get("evidence_id"),
                    "document_id": payload.get("document_id"),
                    "collection_id": payload.get("collection_id"),
                    "claim_text": payload.get("claim_text"),
                    "claim_type": payload.get("claim_type"),
                    "evidence_source_type": payload.get("evidence_source_type"),
                    "evidence_anchors": payload.get("evidence_anchors"),
                    "material_system": payload.get("material_system"),
                    "condition_context": payload.get("condition_context"),
                    "confidence": payload.get("confidence"),
                    "traceability_status": payload.get("traceability_status"),
                }
            )
        return tuple(rows)

    def _serialize_card_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        collection_id = str(row.get("collection_id") or "")
        document_id = str(row.get("document_id") or "")
        evidence_id = str(row.get("evidence_id") or "")
        return {
            "evidence_id": evidence_id,
            "document_id": document_id,
            "collection_id": collection_id,
            "claim_text": str(row.get("claim_text") or ""),
            "claim_type": str(row.get("claim_type") or "qualitative"),
            "evidence_source_type": str(row.get("evidence_source_type") or "text"),
            "evidence_anchors": self._normalize_evidence_anchors_payload(
                row.get("evidence_anchors"),
                collection_id=collection_id,
                document_id=document_id,
                evidence_id=evidence_id,
            ),
            "material_system": self._normalize_material_system_payload(row.get("material_system")),
            "condition_context": self._normalize_condition_context_payload(row.get("condition_context")),
            "confidence": round(float(row.get("confidence") or 0.0), 2),
            "traceability_status": str(
                row.get("traceability_status") or TRACEABILITY_STATUS_MISSING
            ),
        }

    def _normalize_evidence_anchors_payload(
        self,
        value: Any,
        *,
        collection_id: str | None = None,
        document_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized = self._normalize_object(value)
        if normalized is None:
            return []
        if isinstance(normalized, dict):
            anchors = [normalized]
        elif isinstance(normalized, list):
            anchors = normalized
        else:
            return []

        payload: list[dict[str, Any]] = []
        for index, anchor in enumerate(anchors):
            if not isinstance(anchor, dict):
                continue

            anchor_id = self._normalize_scalar_text(anchor.get("anchor_id")) or f"anchor_{index + 1}"
            anchor_document_id = (
                self._normalize_scalar_text(anchor.get("document_id")) or document_id or ""
            )
            source_type = self._normalize_scalar_text(anchor.get("source_type")) or "text"
            if source_type not in _EVIDENCE_SOURCE_TYPES:
                source_type = "text"
            quote = self._normalize_scalar_text(anchor.get("quote")) or self._normalize_scalar_text(
                anchor.get("quote_span")
            )
            section_id = self._normalize_scalar_text(anchor.get("section_id"))
            char_range = self._normalize_char_range_payload(anchor.get("char_range"))
            bbox = self._normalize_bbox_payload(anchor.get("bbox"))
            explicit_locator_type = self._normalize_scalar_text(anchor.get("locator_type"))
            locator_type = explicit_locator_type if explicit_locator_type in {
                "char_range",
                "bbox",
                "section",
            } else None
            if locator_type is None:
                if char_range is not None:
                    locator_type = "char_range"
                elif bbox is not None:
                    locator_type = "bbox"
                elif section_id:
                    locator_type = "section"
                elif quote or self._normalize_scalar_text(anchor.get("snippet_id")):
                    locator_type = "char_range"
                else:
                    locator_type = "section"

            explicit_confidence = self._normalize_scalar_text(anchor.get("locator_confidence"))
            locator_confidence = explicit_confidence if explicit_confidence in {
                "high",
                "medium",
                "low",
            } else ("medium" if char_range is not None or bbox is not None else "low")
            page = self._normalize_optional_int(anchor.get("page"))
            deep_link = self._normalize_scalar_text(anchor.get("deep_link")) or self._build_traceback_deep_link(
                collection_id=collection_id,
                document_id=anchor_document_id or document_id,
                evidence_id=evidence_id,
                anchor_id=anchor_id,
                page=page,
            )

            payload.append(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": anchor_id,
                        "document_id": anchor_document_id,
                        "locator_type": locator_type,
                        "locator_confidence": locator_confidence,
                        "source_type": source_type,
                        "section_id": section_id,
                        "char_range": char_range,
                        "bbox": bbox,
                        "page": page,
                        "quote": quote,
                        "deep_link": deep_link,
                        "block_id": self._normalize_scalar_text(anchor.get("block_id")),
                        "snippet_id": self._normalize_scalar_text(anchor.get("snippet_id")),
                        "figure_or_table": self._normalize_scalar_text(
                            anchor.get("figure_or_table")
                        ),
                        "quote_span": quote,
                    }
                ).to_record()
            )
        return payload

    def _resolve_traceback_anchor(
        self,
        anchor: dict[str, Any],
        content: dict[str, Any],
        text_unit_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        full_text = str(content.get("content_text") or "")
        blocks = content.get("blocks") if isinstance(content.get("blocks"), list) else []
        section_id = self._normalize_scalar_text(anchor.get("section_id"))
        block_id = self._normalize_scalar_text(anchor.get("block_id")) or section_id
        block = self._find_block_by_id(block_id, blocks) if block_id else None

        quote = self._normalize_scalar_text(anchor.get("quote")) or self._normalize_scalar_text(
            anchor.get("quote_span")
        )
        snippet_id = self._normalize_scalar_text(anchor.get("snippet_id"))
        snippet_text = None
        if snippet_id:
            snippet_text = self._normalize_scalar_text(text_unit_lookup.get(snippet_id, {}).get("text"))

        explicit_char_range = self._normalize_char_range_payload(anchor.get("char_range"))
        explicit_bbox = self._normalize_bbox_payload(anchor.get("bbox"))
        locator_confidence = str(anchor.get("locator_confidence") or "low")

        if explicit_char_range is not None:
            block = block or self._find_block_for_char_range(explicit_char_range, blocks)
            block_id = block_id or (
                self._normalize_scalar_text(block.get("block_id")) if block else None
            )
            return {
                **anchor,
                "section_id": section_id or block_id,
                "block_id": block_id,
                "char_range": explicit_char_range,
                "bbox": None,
                "locator_type": "char_range",
                "locator_confidence": locator_confidence if locator_confidence in {"high", "medium"} else "medium",
                "quote": quote or snippet_text,
                "quote_span": quote or snippet_text,
            }

        if explicit_bbox is not None:
            return {
                **anchor,
                "section_id": section_id or block_id,
                "block_id": block_id,
                "char_range": None,
                "bbox": explicit_bbox,
                "locator_type": "bbox",
                "locator_confidence": locator_confidence if locator_confidence in {"high", "medium"} else "medium",
                "quote": quote or snippet_text,
                "quote_span": quote or snippet_text,
            }

        match_text = quote or snippet_text
        resolved_char_range: dict[str, int] | None = None

        if match_text:
            if block is None:
                block = self._find_block_by_snippet_id(snippet_id, blocks)
            if block is None:
                block = self._find_block_for_quote(match_text, blocks)

            if block is not None:
                local_index = str(block.get("text") or "").find(match_text)
                if local_index >= 0 and block.get("start_offset") is not None:
                    section_start = self._safe_int(block.get("start_offset"))
                    resolved_char_range = {
                        "start": section_start + local_index,
                        "end": section_start + local_index + len(match_text),
                    }
                    block_id = self._normalize_scalar_text(block.get("block_id")) or block_id
                    section_id = section_id or block_id

            if resolved_char_range is None and full_text:
                global_index = full_text.find(match_text)
                if global_index >= 0:
                    resolved_char_range = {
                        "start": global_index,
                        "end": global_index + len(match_text),
                    }
                    block = block or self._find_block_for_char_range(resolved_char_range, blocks)
                    block_id = (
                        self._normalize_scalar_text(block.get("block_id")) if block else block_id
                    ) or block_id
                    section_id = section_id or block_id

        if resolved_char_range is not None:
            return {
                **anchor,
                "section_id": section_id or block_id,
                "block_id": block_id,
                "char_range": resolved_char_range,
                "bbox": None,
                "locator_type": "char_range",
                "locator_confidence": "medium" if snippet_text else "high",
                "quote": match_text,
                "quote_span": match_text,
            }

        if block is None:
            block = self._find_block_by_snippet_id(snippet_id, blocks)
        block_id = block_id or (
            self._normalize_scalar_text(block.get("block_id")) if block else None
        )
        section_id = section_id or block_id
        if block_id is None and section_id is None:
            return None

        return {
            **anchor,
            "section_id": section_id,
            "block_id": block_id,
            "char_range": None,
            "bbox": None,
            "locator_type": "section",
            "locator_confidence": "low",
            "quote": match_text,
            "quote_span": match_text,
        }

    def _derive_traceback_status(self, anchors: list[dict[str, Any]]) -> str:
        if any(
            str(anchor.get("locator_type")) in {"char_range", "bbox"}
            and str(anchor.get("locator_confidence")) in {"high", "medium"}
            for anchor in anchors
        ):
            return "ready"
        if any(
            str(anchor.get("locator_type")) in {"char_range", "bbox", "section"}
            for anchor in anchors
        ):
            return "partial"
        return "unavailable"

    def _build_text_unit_lookup(
        self,
        text_units: tuple[dict[str, Any], ...] | None,
        document_id: str,
    ) -> dict[str, dict[str, Any]]:
        if not text_units:
            return {}

        lookup: dict[str, dict[str, Any]] = {}
        for row in text_units:
            text_unit_id = self._normalize_scalar_text(row.get("id"))
            if text_unit_id is None:
                continue
            document_ids = self._normalize_list(row.get("document_ids"))
            if document_ids and str(document_id) not in document_ids:
                continue
            lookup[text_unit_id] = dict(row)
        return lookup

    def _find_block_by_id(
        self,
        block_id: str | None,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not block_id:
            return None
        for block in blocks:
            if self._normalize_scalar_text(block.get("block_id")) == block_id:
                return block
        return None

    def _find_block_by_snippet_id(
        self,
        snippet_id: str | None,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not snippet_id:
            return None
        for block in blocks:
            if snippet_id in self._normalize_list(block.get("text_unit_ids")):
                return block
        return None

    def _find_block_for_quote(
        self,
        quote: str,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for block in blocks:
            if quote and quote in str(block.get("text") or ""):
                return block
        return None

    def _find_block_for_char_range(
        self,
        char_range: dict[str, int],
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        start = self._safe_int(char_range.get("start"))
        end = self._safe_int(char_range.get("end"))
        if start is None or end is None:
            return None
        for block in blocks:
            section_start = self._safe_int(block.get("start_offset"))
            section_end = self._safe_int(block.get("end_offset"))
            if section_start is None or section_end is None:
                continue
            if section_start <= start and end <= section_end:
                return block
        return None

    def _build_traceback_deep_link(
        self,
        *,
        collection_id: str | None,
        document_id: str | None,
        evidence_id: str | None,
        anchor_id: str | None,
        page: int | None = None,
    ) -> str | None:
        if not collection_id or not document_id:
            return None

        query: list[tuple[str, str]] = []
        if evidence_id:
            query.append(("evidence_id", evidence_id))
        if anchor_id:
            query.append(("anchor_id", anchor_id))
        if page is not None:
            query.append(("page", str(page)))
        query_text = urlencode(query)
        base = f"/collections/{collection_id}/documents/{document_id}"
        return f"{base}?{query_text}" if query_text else base

    def _normalize_char_range_payload(self, value: Any) -> dict[str, int] | None:
        payload = self._normalize_object(value)
        if payload is None or not isinstance(payload, dict):
            return None

        start = self._safe_int(payload.get("start"))
        end = self._safe_int(payload.get("end"))
        if start is None or end is None or end < start:
            return None
        return {"start": start, "end": end}

    def _normalize_bbox_payload(self, value: Any) -> dict[str, float] | None:
        payload = self._normalize_object(value)
        if payload is None or not isinstance(payload, dict):
            return None
        try:
            x0 = float(payload.get("x0"))
            y0 = float(payload.get("y0"))
            x1 = float(payload.get("x1"))
            y1 = float(payload.get("y1"))
        except (TypeError, ValueError):
            return None
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}

    def _normalize_optional_int(self, value: Any) -> int | None:
        parsed = self._safe_int(value)
        if parsed is None or parsed < 0:
            return None
        return parsed

    def _safe_int(self, value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_scalar_text(self, value: Any) -> str | None:
        normalized = self._normalize_object(value)
        if normalized is None:
            return None
        if isinstance(normalized, str):
            text = normalized.strip()
            return text or None
        if isinstance(normalized, (list, dict)):
            text = json.dumps(normalized, ensure_ascii=False)
            text = text.strip()
            return text or None
        text = str(normalized).strip()
        return text or None

    def _normalize_material_system_payload(self, value: Any) -> dict[str, Any]:
        payload = self._normalize_object(value) or {}
        if not isinstance(payload, dict):
            text = str(payload).strip()
            return {
                "family": self._sanitize_material_family(text),
                "composition": None,
            }
        family = self._sanitize_material_family(payload.get("family"))
        composition = self._normalize_scalar_text(payload.get("composition"))
        return {
            "family": family or "unspecified material system",
            "composition": composition,
        }

    def _sanitize_material_family(self, value: Any) -> str | None:
        text = self._normalize_scalar_text(value)
        if text is None:
            return None
        lowered = text.lower()
        if lowered.endswith((".pdf", ".txt", ".docx")):
            return None
        return text

    def _normalize_condition_context_payload(self, value: Any) -> dict[str, Any]:
        payload = self._normalize_object(value) or {}
        if not isinstance(payload, dict):
            payload = {}

        process = self._normalize_object(payload.get("process")) or {}
        baseline = self._normalize_object(payload.get("baseline")) or {}
        test = self._normalize_object(payload.get("test")) or {}

        if not isinstance(process, dict):
            process = {}
        if not isinstance(baseline, dict):
            baseline = {}
        if not isinstance(test, dict):
            test = {}

        temperatures = process.get("temperatures_c") or []
        if not isinstance(temperatures, list):
            temperatures = [temperatures]
        durations = process.get("durations") or []
        if not isinstance(durations, list):
            durations = [durations]
        methods = test.get("methods") or []
        if not isinstance(methods, list):
            methods = [methods]

        return {
            "process": {
                "temperatures_c": [
                    float(item) for item in temperatures if str(item).strip()
                ],
                "durations": [str(item) for item in durations if str(item).strip()],
                "atmosphere": str(process.get("atmosphere") or "").strip() or None,
            },
            "baseline": {
                "control": str(baseline.get("control") or "").strip() or None,
            },
            "test": {
                "methods": [str(item) for item in methods if str(item).strip()],
                "method": str(test.get("method") or "").strip() or None,
            },
        }

    def _normalize_condition_payload(
        self,
        value: Any,
    ) -> dict[str, Any]:
        payload = self._normalize_object(value) or {}
        if not isinstance(payload, dict):
            return {}

        normalized: dict[str, Any] = {}
        for key, item in payload.items():
            parsed = self._normalize_object(item)
            if isinstance(parsed, list):
                normalized[key] = [entry for entry in parsed if entry not in (None, "", [], {})]
            else:
                normalized[key] = parsed
        return {
            key: value
            for key, value in normalized.items()
            if value not in (None, "", [], {})
        }

    def _normalize_object(self, value: Any) -> Any:
        return normalize_record_value(value)

    def _normalize_list(self, value: Any) -> list[str]:
        normalized = self._normalize_object(value)
        if normalized is None:
            return []
        if isinstance(normalized, list):
            return [str(item) for item in normalized if str(item).strip()]
        return [str(normalized)]

    def _normalize_table_matrix(self, value: Any) -> list[list[str]]:
        normalized = self._normalize_object(value)
        if not isinstance(normalized, list):
            return []
        matrix: list[list[str]] = []
        for row in normalized:
            if isinstance(row, list):
                matrix.append([str(cell) for cell in row])
            elif row not in (None, ""):
                matrix.append([str(row)])
        return matrix

    def _bound_table_matrix_for_rows(
        self,
        *,
        table_matrix: list[list[str]],
        table_rows: list[dict[str, Any]],
    ) -> list[list[str]]:
        if len(table_matrix) <= _MAX_FULL_TABLE_CONTEXT_ROWS:
            return table_matrix

        indices = set(range(min(_TABLE_CONTEXT_LEADING_ROWS, len(table_matrix))))
        trailing_start = max(len(table_matrix) - _TABLE_CONTEXT_TRAILING_ROWS, 0)
        indices.update(range(trailing_start, len(table_matrix)))
        for row in table_rows:
            row_index = self._safe_int(row.get("row_index"))
            if row_index is None:
                continue
            for index in (row_index - 1, row_index, row_index + 1):
                if 0 <= index < len(table_matrix):
                    indices.add(index)
        return [table_matrix[index] for index in sorted(indices)]

    def _normalize_method_role(self, value: Any) -> str:
        lowered = str(value or "").strip().lower()
        if lowered in {"process", "characterization", "test"}:
            return lowered
        return "process"

    def _normalize_method_payload(
        self,
        value: Any,
    ) -> dict[str, Any]:
        payload = self._normalize_object(value) or {}
        if not isinstance(payload, dict):
            return {}
        normalized = self._normalize_condition_payload(
            {
                "temperatures_c": payload.get("temperatures_c"),
                "durations": payload.get("durations"),
                "atmosphere": payload.get("atmosphere"),
                "methods": payload.get("methods"),
                **{
                    key: payload.get(key)
                    for key in _PBF_PROCESS_PAYLOAD_KEYS
                    if key in payload
                },
            }
        )
        details = self._normalize_scalar_text(payload.get("details"))
        if details is not None:
            normalized["details"] = details
        return normalized

    def _index_rows_by_id(
        self,
        rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        id_column: str,
    ) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        for row in rows or ():
            item_id = self._normalize_scalar_text(row.get(id_column))
            if item_id:
                lookup[item_id] = dict(row)
        return lookup

    def _normalize_evidence_anchor_records(
        self,
        evidence_anchors: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in evidence_anchors or ():
            payload = dict(row)
            payload["char_range"] = self._normalize_object(row.get("char_range"))
            payload["bbox"] = self._normalize_object(row.get("bbox"))
            records.append(EvidenceAnchor.from_mapping(payload).to_record())
        return tuple(records)

    def _normalize_method_fact_records(
        self,
        method_facts: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        collection_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in method_facts or ():
            payload = dict(row)
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            if not payload.get("domain_profile"):
                payload["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
            payload["method_role"] = self._normalize_method_role(row.get("method_role"))
            payload["method_payload"] = self._normalize_method_payload(row.get("method_payload"))
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            records.append(MethodFact.from_mapping(payload).to_record())
        return tuple(records)

    def _normalize_sample_variant_records(
        self,
        sample_variants: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        collection_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in sample_variants or ():
            payload = dict(row)
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            if not payload.get("domain_profile"):
                payload["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
            payload["host_material_system"] = self._normalize_material_system_payload(
                row.get("host_material_system")
            )
            payload["process_context"] = self._normalize_condition_payload(
                row.get("process_context")
            )
            profile_payload = self._normalize_object(row.get("profile_payload"))
            payload["profile_payload"] = (
                profile_payload if isinstance(profile_payload, dict) else {}
            )
            payload["structure_feature_ids"] = self._normalize_list(
                row.get("structure_feature_ids")
            )
            payload["source_anchor_ids"] = self._normalize_list(
                row.get("source_anchor_ids")
            )
            records.append(SampleVariant.from_mapping(payload).to_record())
        return tuple(records)

    def _normalize_measurement_result_records(
        self,
        measurement_results: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        collection_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in measurement_results or ():
            payload = dict(row)
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            if not payload.get("domain_profile"):
                payload["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
            value_payload = self._normalize_object(row.get("value_payload"))
            payload["value_payload"] = value_payload if isinstance(value_payload, dict) else {}
            payload["structure_feature_ids"] = self._normalize_list(
                row.get("structure_feature_ids")
            )
            payload["characterization_observation_ids"] = self._normalize_list(
                row.get("characterization_observation_ids")
            )
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            record = MeasurementResult.from_mapping(payload).to_record()
            record["unit"] = self._infer_measurement_unit(record)
            if self._is_non_measurement_statistic_result(record):
                continue
            records.append(record)
        return tuple(records)

    def _deduplicate_measurement_result_records(
        self,
        measurement_results: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not measurement_results:
            return ()

        records_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        loose_records: list[dict[str, Any]] = []
        for row in measurement_results:
            record = MeasurementResult.from_mapping(row).to_record()
            record["unit"] = self._infer_measurement_unit(record)
            if self._is_non_measurement_statistic_result(record):
                continue
            key = self._measurement_result_dedupe_key(record)
            if key is None:
                loose_records.append(record)
                continue
            existing = records_by_key.get(key)
            records_by_key[key] = (
                self._merge_measurement_result_records(existing, record)
                if existing is not None
                else record
            )

        records = [*records_by_key.values(), *loose_records]
        return self._normalize_measurement_result_records(records, None)

    def _measurement_result_dedupe_key(
        self,
        record: dict[str, Any],
    ) -> tuple[Any, ...] | None:
        property_name = self._normalize_property_name(record.get("property_normalized"))
        result_type = self._normalize_result_type(record.get("result_type"))
        value_signature = self._measurement_value_signature(record.get("value_payload"))
        if value_signature is None:
            return None
        return (
            self._normalize_scalar_text(record.get("document_id")),
            self._normalize_scalar_text(record.get("variant_id")),
            property_name,
            result_type,
            self._normalize_scalar_text(record.get("claim_scope")) or "current_work",
            value_signature,
            self._canonical_unit_text(record.get("unit")),
        )

    def _measurement_value_signature(self, value_payload: Any) -> tuple[Any, ...] | None:
        payload = self._normalize_object(value_payload)
        if not isinstance(payload, dict):
            return None
        numeric_parts: list[tuple[str, float]] = []
        for key in ("value", "retention_percent", "min", "max"):
            numeric = self._coerce_float(payload.get(key))
            if numeric is not None:
                numeric_parts.append((key, round(numeric, 8)))
        if numeric_parts:
            return tuple(numeric_parts)
        direction = self._normalize_scalar_text(payload.get("direction"))
        if direction:
            return (("direction", direction.lower()),)
        statement = self._normalize_scalar_text(payload.get("statement"))
        if statement:
            normalized = re.sub(r"\s+", " ", statement.lower()).strip()
            return (("statement", normalized),)
        return None

    def _merge_measurement_result_records(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        preferred = self._preferred_measurement_record(existing, incoming)
        secondary = incoming if preferred is existing else existing
        merged = dict(preferred)
        for column in (
            "structure_feature_ids",
            "characterization_observation_ids",
            "evidence_anchor_ids",
        ):
            merged[column] = self._dedupe_preserving_order(
                [
                    *self._normalize_list(preferred.get(column)),
                    *self._normalize_list(secondary.get(column)),
                ]
            )
        for column in ("test_condition_id", "baseline_id", "variant_id", "unit"):
            if not self._normalize_scalar_text(merged.get(column)):
                merged[column] = secondary.get(column)
        if self._normalize_scalar_text(incoming.get("result_source_type")) == "table":
            merged["result_source_type"] = "table"
        if TRACEABILITY_STATUS_DIRECT in {
            self._normalize_scalar_text(existing.get("traceability_status")),
            self._normalize_scalar_text(incoming.get("traceability_status")),
        }:
            merged["traceability_status"] = TRACEABILITY_STATUS_DIRECT
        if EPISTEMIC_DIRECTLY_OBSERVED in {
            self._normalize_scalar_text(existing.get("epistemic_status")),
            self._normalize_scalar_text(incoming.get("epistemic_status")),
        }:
            merged["epistemic_status"] = EPISTEMIC_DIRECTLY_OBSERVED
        return MeasurementResult.from_mapping(merged).to_record()

    def _preferred_measurement_record(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        existing_score = self._measurement_record_quality_score(existing)
        incoming_score = self._measurement_record_quality_score(incoming)
        return incoming if incoming_score > existing_score else existing

    def _measurement_record_quality_score(self, record: dict[str, Any]) -> tuple[int, int, int]:
        return (
            1 if self._normalize_scalar_text(record.get("result_source_type")) == "table" else 0,
            1 if self._normalize_scalar_text(record.get("unit")) else 0,
            len(self._normalize_list(record.get("evidence_anchor_ids"))),
        )

    def _infer_measurement_unit(self, record: dict[str, Any]) -> str | None:
        value_payload = self._normalize_object(record.get("value_payload"))
        return self._infer_measurement_unit_from_parts(
            property_normalized=self._normalize_property_name(
                record.get("property_normalized")
            ),
            result_type=self._normalize_result_type(record.get("result_type")),
            value_payload=value_payload if isinstance(value_payload, dict) else {},
            explicit_unit=record.get("unit"),
            text=self._normalize_scalar_text(
                (value_payload or {}).get("statement")
                if isinstance(value_payload, dict)
                else None
            ),
        )

    def _infer_measurement_unit_from_parts(
        self,
        *,
        property_normalized: str,
        result_type: str,
        value_payload: dict[str, Any],
        explicit_unit: Any,
        text: str | None,
    ) -> str | None:
        unit = self._canonical_unit_text(explicit_unit) or self._canonical_unit_text(
            value_payload.get("source_unit_text")
        )
        if unit:
            return unit
        unit = self._extract_unit_from_text(text or "")
        if unit:
            return unit
        return self._default_unit_for_measurement(
            property_normalized=property_normalized,
            result_type=result_type,
            value_payload=value_payload,
            text=text,
        )

    def _default_unit_for_measurement(
        self,
        *,
        property_normalized: str,
        result_type: str,
        value_payload: dict[str, Any],
        text: str | None,
    ) -> str | None:
        if result_type == "retention" or property_normalized in {"elongation"}:
            return "%"
        if property_normalized in {
            "yield_strength",
            "tensile_strength",
            "flexural_strength",
        }:
            return "MPa"
        if property_normalized == "hardness":
            return "HV"
        if property_normalized == "density":
            value = self._measurement_numeric_value(value_payload)
            lowered = (text or "").lower()
            if "%" in lowered or "relative" in lowered or "densification" in lowered:
                return "%"
            if value is not None and 20 <= value <= 100:
                return "%"
        return None

    def _canonical_unit_text(self, value: Any) -> str | None:
        text = self._sanitize_unit(value)
        if text is None:
            return None
        normalized = text.strip().replace("μ", "u")
        lowered = normalized.lower().replace(" ", "")
        aliases = {
            "%": "%",
            "percent": "%",
            "mpa": "MPa",
            "gpa": "GPa",
            "pa": "Pa",
            "hv": "HV",
            "vickers": "HV",
            "c": "C",
            "degc": "C",
            "°c": "C",
            "j/mm3": "J/mm3",
            "j/mm^3": "J/mm3",
            "jmm-3": "J/mm3",
        }
        return aliases.get(lowered, text)

    def _measurement_numeric_value(self, value_payload: dict[str, Any]) -> float | None:
        for key in ("value", "retention_percent", "min", "max"):
            numeric = self._coerce_float(value_payload.get(key))
            if numeric is not None:
                return numeric
        return None

    def _coerce_float(self, value: Any) -> float | None:
        normalized = normalize_record_value(value)
        if isinstance(normalized, bool):
            return None
        if isinstance(normalized, (int, float)):
            try:
                numeric = float(normalized)
            except (TypeError, ValueError):
                return None
            if math.isnan(numeric):
                return None
            return numeric
        text = self._normalize_scalar_text(normalized)
        if text is None:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _is_non_measurement_statistic_claim(self, claim: Any) -> bool:
        text = " ".join(
            part
            for part in (
                self._normalize_scalar_text(getattr(claim, "claim_text", None)),
                self._normalize_scalar_text(getattr(claim, "quote", None)),
                self._normalize_scalar_text(getattr(claim, "property_normalized", None)),
            )
            if part
        )
        return self._is_statistic_text(text)

    def _is_non_measurement_statistic_result(self, record: dict[str, Any]) -> bool:
        value_payload = self._normalize_object(record.get("value_payload"))
        statement = (
            self._normalize_scalar_text(value_payload.get("statement"))
            if isinstance(value_payload, dict)
            else None
        )
        text = " ".join(
            part
            for part in (
                statement,
                self._normalize_scalar_text(record.get("property_normalized")),
            )
            if part
        )
        return self._is_statistic_text(text)

    def _is_statistic_text(self, text: str) -> bool:
        lowered = str(text or "").lower()
        return any(term in lowered for term in _STATISTIC_MEASUREMENT_TERMS)

    def _normalize_characterization_records(
        self,
        characterization: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        collection_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in characterization or ():
            payload = dict(row)
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            payload["condition_context"] = self._normalize_condition_context_payload(
                row.get("condition_context")
            )
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            records.append(CharacterizationObservation.from_mapping(payload).to_record())
        return tuple(records)

    def _normalize_structure_feature_records(
        self,
        structure_features: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in structure_features or ():
            payload = dict(row)
            payload["source_observation_ids"] = self._normalize_list(
                row.get("source_observation_ids")
            )
            records.append(StructureFeature.from_mapping(payload).to_record())
        return tuple(records)

    def _normalize_test_condition_records(
        self,
        test_conditions: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        collection_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in test_conditions or ():
            payload = dict(row)
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            if not payload.get("domain_profile"):
                payload["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
            payload["condition_payload"] = self._normalize_condition_payload(
                row.get("condition_payload")
            )
            payload["missing_fields"] = self._normalize_list(row.get("missing_fields"))
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            records.append(TestCondition.from_mapping(payload).to_record())
        return tuple(records)

    def _normalize_baseline_reference_records(
        self,
        baseline_references: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        collection_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        records = []
        for row in baseline_references or ():
            payload = dict(row)
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            if not payload.get("domain_profile"):
                payload["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            records.append(BaselineReference.from_mapping(payload).to_record())
        return tuple(records)


__all__ = [
    "EvidenceCardNotFoundError",
    "PaperFactsNotReadyError",
    "PaperFactsService",
]
