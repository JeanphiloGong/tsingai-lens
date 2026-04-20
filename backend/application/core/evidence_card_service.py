from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pandas as pd

from application.core.core_semantic_version import (
    core_semantic_rebuild_required,
    purge_stale_core_semantic_artifacts,
    write_core_semantic_manifest,
)
from application.core.document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.llm_extraction_models import (
    BaselineReferencePayload,
    ConditionContextPayload,
    EvidenceAnchorPayload,
    EvidenceCardPayload,
    ExtractedTestConditionPayload,
    MeasurementResultPayload,
    ProcessContextPayload,
    SampleVariantPayload,
    StructuredExtractionBundle,
    TestConditionPayloadModel,
    TestContextPayload,
)
from application.core.llm_structured_extractor import (
    CoreLLMStructuredExtractor,
    build_default_core_llm_structured_extractor,
)
from application.source.artifact_input_service import (
    build_document_records,
    load_collection_inputs,
    load_sections_artifact,
    load_table_cells_artifact,
)
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from domain.core.evidence_backbone import (
    BaselineReference,
    CORE_NEUTRAL_DOMAIN_PROFILE,
    CharacterizationObservation,
    EvidenceAnchor,
    MeasurementResult,
    SampleVariant,
    StructureFeature,
    TestCondition,
)
from domain.shared.enums import (
    DOC_TYPE_REVIEW,
    EPISTEMIC_DIRECTLY_OBSERVED,
    EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    EPISTEMIC_UNRESOLVED,
    TRACEABILITY_STATUS_DIRECT,
    TRACEABILITY_STATUS_MISSING,
)
from infra.persistence.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)

logger = logging.getLogger(__name__)


_EVIDENCE_CARDS_FILE = "evidence_cards.parquet"
_EVIDENCE_JSON_COLUMNS = (
    "evidence_anchors",
    "material_system",
    "condition_context",
)
_CHARACTERIZATION_OBSERVATIONS_FILE = "characterization_observations.parquet"
_CHARACTERIZATION_JSON_COLUMNS = (
    "condition_context",
    "evidence_anchor_ids",
)
_STRUCTURE_FEATURES_FILE = "structure_features.parquet"
_STRUCTURE_FEATURES_JSON_COLUMNS = ("source_observation_ids",)
_TEST_CONDITIONS_FILE = "test_conditions.parquet"
_TEST_CONDITIONS_JSON_COLUMNS = (
    "condition_payload",
    "missing_fields",
    "evidence_anchor_ids",
)
_BASELINE_REFERENCES_FILE = "baseline_references.parquet"
_BASELINE_REFERENCES_JSON_COLUMNS = ("evidence_anchor_ids",)
_SAMPLE_VARIANTS_FILE = "sample_variants.parquet"
_SAMPLE_VARIANTS_JSON_COLUMNS = (
    "host_material_system",
    "process_context",
    "profile_payload",
    "structure_feature_ids",
    "source_anchor_ids",
)
_MEASUREMENT_RESULTS_FILE = "measurement_results.parquet"
_MEASUREMENT_RESULTS_JSON_COLUMNS = (
    "value_payload",
    "structure_feature_ids",
    "characterization_observation_ids",
    "evidence_anchor_ids",
)
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


class EvidenceCardsNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve evidence cards."""

    def __init__(self, collection_id: str, output_dir: Path) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"evidence cards not ready: {collection_id}")


class EvidenceCardNotFoundError(FileNotFoundError):
    """Raised when one evidence card is missing from a collection."""

    def __init__(self, collection_id: str, evidence_id: str) -> None:
        self.collection_id = collection_id
        self.evidence_id = evidence_id
        super().__init__(f"evidence card not found: {collection_id}/{evidence_id}")


class EvidenceCardService:
    """Generate and serve collection-scoped evidence card artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        document_profile_service: DocumentProfileService | None = None,
        structured_extractor: CoreLLMStructuredExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )
        self._structured_extractor = structured_extractor

    def _get_structured_extractor(self) -> CoreLLMStructuredExtractor:
        if self._structured_extractor is None:
            self._structured_extractor = build_default_core_llm_structured_extractor()
        return self._structured_extractor

    def list_evidence_cards(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        cards = self.read_evidence_cards(collection_id)
        items = [
            self._serialize_card_row(row)
            for _, row in cards.iloc[offset : offset + limit].iterrows()
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
        matched = cards[cards["evidence_id"].astype(str) == str(evidence_id)]
        if matched.empty:
            raise EvidenceCardNotFoundError(collection_id, evidence_id)
        return self._serialize_card_row(matched.iloc[0])

    def get_evidence_traceback(
        self,
        collection_id: str,
        evidence_id: str,
    ) -> dict[str, Any]:
        cards = self.read_evidence_cards(collection_id)
        matched = cards[cards["evidence_id"].astype(str) == str(evidence_id)]
        if matched.empty:
            raise EvidenceCardNotFoundError(collection_id, evidence_id)

        row = matched.iloc[0]
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
        output_dir = self._resolve_output_dir(collection_id)
        _, text_units = load_collection_inputs(output_dir)
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

    def read_evidence_cards(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        path = output_dir / _EVIDENCE_CARDS_FILE
        if path.is_file():
            cards = restore_frame_from_storage(
                pd.read_parquet(path),
                _EVIDENCE_JSON_COLUMNS,
            )
            if core_semantic_rebuild_required(output_dir) and (output_dir / "documents.parquet").is_file():
                cards = self.build_evidence_cards(collection_id, output_dir)
        else:
            cards = self.build_evidence_cards(collection_id, output_dir)
        return self._normalize_cards_table(cards, collection_id)

    def build_evidence_cards(
        self,
        collection_id: str,
        output_dir: str | Path | None = None,
    ) -> pd.DataFrame:
        base_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else self._resolve_output_dir(collection_id)
        )
        purge_stale_core_semantic_artifacts(base_dir)
        documents_path = base_dir / "documents.parquet"
        if not documents_path.is_file():
            raise EvidenceCardsNotReadyError(collection_id, base_dir)

        try:
            profiles = self.document_profile_service.read_document_profiles(collection_id)
        except DocumentProfilesNotReadyError as exc:
            raise EvidenceCardsNotReadyError(collection_id, exc.output_dir) from exc

        documents, text_units = load_collection_inputs(base_dir)
        try:
            sections = load_sections_artifact(base_dir)
            table_cells = load_table_cells_artifact(base_dir)
        except FileNotFoundError as exc:
            raise EvidenceCardsNotReadyError(collection_id, base_dir) from exc

        document_records = build_document_records(documents, text_units)
        sections_by_doc = self._group_sections_by_document(sections)
        table_cells_by_doc = self._group_table_cells_by_document(table_cells)
        profile_by_doc = {
            str(row.get("document_id")): dict(row)
            for _, row in profiles.iterrows()
        }
        logger.info(
            "Evidence extraction started collection_id=%s document_count=%s section_count=%s table_cell_count=%s",
            collection_id,
            len(document_records),
            len(sections),
            len(table_cells),
        )
        if table_cells.empty:
            logger.warning(
                "Evidence extraction found empty table_cells collection_id=%s",
                collection_id,
            )

        card_rows: list[dict[str, Any]] = []
        sample_variant_rows: list[dict[str, Any]] = []
        test_condition_rows: list[dict[str, Any]] = []
        baseline_rows: list[dict[str, Any]] = []
        measurement_rows: list[dict[str, Any]] = []

        extractor = self._get_structured_extractor()

        for _, row in document_records.iterrows():
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
            doc_sections = sections_by_doc.get(document_id, [])
            grouped_rows = self._group_table_rows(table_cells_by_doc.get(document_id, []))
            document_state = self._build_document_state()
            logger.info(
                "Evidence extraction document started collection_id=%s document_id=%s section_count=%s table_row_count=%s doc_type=%s",
                collection_id,
                document_id,
                len(doc_sections),
                len(grouped_rows),
                profile.get("doc_type"),
            )

            doc_card_start = len(card_rows)
            doc_variant_start = len(sample_variant_rows)
            doc_condition_start = len(test_condition_rows)
            doc_baseline_start = len(baseline_rows)
            doc_measurement_start = len(measurement_rows)
            for section in doc_sections:
                bundle = extractor.extract_section_bundle(
                    self._build_section_extraction_payload(
                        document_id=document_id,
                        title=title,
                        source_filename=source_filename,
                        profile=profile,
                        section=section,
                    )
                )
                self._materialize_bundle(
                    bundle=bundle,
                    collection_id=collection_id,
                    document_id=document_id,
                    section=section,
                    table_id=None,
                    row_index=None,
                    card_rows=card_rows,
                    sample_variant_rows=sample_variant_rows,
                        test_condition_rows=test_condition_rows,
                        baseline_rows=baseline_rows,
                        measurement_rows=measurement_rows,
                        document_state=document_state,
                    )
                logger.debug(
                    "Evidence section bundle extracted collection_id=%s document_id=%s section_id=%s section_type=%s evidence_cards=%s sample_variants=%s test_conditions=%s baselines=%s measurements=%s",
                    collection_id,
                    document_id,
                    section.get("section_id"),
                    section.get("section_type"),
                    len(bundle.evidence_cards),
                    len(bundle.sample_variants),
                    len(bundle.test_conditions),
                    len(bundle.baseline_references),
                    len(bundle.measurement_results),
                )

            if str(profile.get("doc_type") or "") != DOC_TYPE_REVIEW:
                for (table_id, row_index), row_cells in grouped_rows.items():
                    bundle = extractor.extract_table_row_bundle(
                        self._build_table_row_extraction_payload(
                            document_id=document_id,
                            title=title,
                            source_filename=source_filename,
                            profile=profile,
                            table_id=table_id,
                            row_index=row_index,
                            row_cells=row_cells,
                            sections=doc_sections,
                        )
                    )
                    self._materialize_bundle(
                        bundle=bundle,
                        collection_id=collection_id,
                        document_id=document_id,
                        section=None,
                        table_id=table_id,
                        row_index=row_index,
                        card_rows=card_rows,
                        sample_variant_rows=sample_variant_rows,
                        test_condition_rows=test_condition_rows,
                        baseline_rows=baseline_rows,
                            measurement_rows=measurement_rows,
                            document_state=document_state,
                        )
                    logger.debug(
                        "Evidence table-row bundle extracted collection_id=%s document_id=%s table_id=%s row_index=%s cell_count=%s evidence_cards=%s sample_variants=%s test_conditions=%s baselines=%s measurements=%s",
                        collection_id,
                        document_id,
                        table_id,
                        row_index,
                        len(row_cells),
                        len(bundle.evidence_cards),
                        len(bundle.sample_variants),
                        len(bundle.test_conditions),
                        len(bundle.baseline_references),
                        len(bundle.measurement_results),
                    )

            logger.info(
                "Evidence extraction document finished collection_id=%s document_id=%s evidence_cards=%s sample_variants=%s test_conditions=%s baselines=%s measurements=%s",
                collection_id,
                document_id,
                len(card_rows) - doc_card_start,
                len(sample_variant_rows) - doc_variant_start,
                len(test_condition_rows) - doc_condition_start,
                len(baseline_rows) - doc_baseline_start,
                len(measurement_rows) - doc_measurement_start,
            )

        cards_table = self._normalize_cards_table(
            pd.DataFrame(
                card_rows,
                columns=[
                    "evidence_id",
                    "document_id",
                    "collection_id",
                    "claim_text",
                    "claim_type",
                    "evidence_source_type",
                    "evidence_anchors",
                    "material_system",
                    "condition_context",
                    "confidence",
                    "traceability_status",
                ],
            ),
            collection_id,
        )
        sample_variants = self._normalize_sample_variants_table(
            pd.DataFrame(sample_variant_rows, columns=_SAMPLE_VARIANT_COLUMNS),
            collection_id,
        )
        test_conditions = self._normalize_test_conditions_table(
            pd.DataFrame(test_condition_rows, columns=_TEST_CONDITION_COLUMNS),
            collection_id,
        )
        baseline_references = self._normalize_baseline_references_table(
            pd.DataFrame(baseline_rows, columns=_BASELINE_REFERENCE_COLUMNS),
            collection_id,
        )
        measurement_results = self._normalize_measurement_results_table(
            pd.DataFrame(measurement_rows, columns=_MEASUREMENT_RESULT_COLUMNS),
            collection_id,
        )
        if not cards_table.empty and measurement_results.empty:
            logger.warning(
                "Evidence extraction produced zero measurement_results collection_id=%s evidence_card_count=%s raw_measurement_count=%s",
                collection_id,
                len(cards_table),
                len(measurement_rows),
            )

        characterization = self._build_characterization_observations(
            collection_id=collection_id,
            cards_table=cards_table,
            sections_by_doc=sections_by_doc,
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

        base_dir.mkdir(parents=True, exist_ok=True)
        prepare_frame_for_storage(
            cards_table,
            _EVIDENCE_JSON_COLUMNS,
        ).to_parquet(base_dir / _EVIDENCE_CARDS_FILE, index=False)
        prepare_frame_for_storage(
            characterization,
            _CHARACTERIZATION_JSON_COLUMNS,
        ).to_parquet(base_dir / _CHARACTERIZATION_OBSERVATIONS_FILE, index=False)
        prepare_frame_for_storage(
            structure_features,
            _STRUCTURE_FEATURES_JSON_COLUMNS,
        ).to_parquet(base_dir / _STRUCTURE_FEATURES_FILE, index=False)
        prepare_frame_for_storage(
            test_conditions,
            _TEST_CONDITIONS_JSON_COLUMNS,
        ).to_parquet(base_dir / _TEST_CONDITIONS_FILE, index=False)
        prepare_frame_for_storage(
            baseline_references,
            _BASELINE_REFERENCES_JSON_COLUMNS,
        ).to_parquet(base_dir / _BASELINE_REFERENCES_FILE, index=False)
        prepare_frame_for_storage(
            sample_variants,
            _SAMPLE_VARIANTS_JSON_COLUMNS,
        ).to_parquet(base_dir / _SAMPLE_VARIANTS_FILE, index=False)
        prepare_frame_for_storage(
            measurement_results,
            _MEASUREMENT_RESULTS_JSON_COLUMNS,
        ).to_parquet(base_dir / _MEASUREMENT_RESULTS_FILE, index=False)

        write_core_semantic_manifest(base_dir)
        self.artifact_registry_service.upsert(collection_id, base_dir)
        logger.info(
            "Evidence extraction finished collection_id=%s evidence_cards=%s sample_variants=%s test_conditions=%s baselines=%s measurement_results=%s characterization_observations=%s structure_features=%s",
            collection_id,
            len(cards_table),
            len(sample_variants),
            len(test_conditions),
            len(baseline_references),
            len(measurement_results),
            len(characterization),
            len(structure_features),
        )
        return cards_table

    def _build_document_state(self) -> dict[str, Any]:
        return {
            "variant_ids_by_key": {},
            "variant_records_by_id": {},
            "test_condition_ids_by_key": {},
            "test_condition_records_by_id": {},
            "baseline_ids_by_key": {},
            "baseline_records_by_id": {},
            "card_keys": set(),
        }

    def _build_section_extraction_payload(
        self,
        *,
        document_id: str,
        title: str,
        source_filename: str | None,
        profile: dict[str, Any],
        section: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "document_title": title,
            "source_filename": source_filename,
            "document_profile": {
                "doc_type": str(profile.get("doc_type") or ""),
                "protocol_extractable": str(profile.get("protocol_extractable") or ""),
            },
            "section": {
                "section_id": str(section.get("section_id") or ""),
                "section_type": str(section.get("section_type") or ""),
                "heading": self._normalize_scalar_text(section.get("heading")),
                "text": str(section.get("text") or "")[:12000],
                "text_unit_ids": self._normalize_list(section.get("text_unit_ids")),
            },
        }

    def _build_table_row_extraction_payload(
        self,
        *,
        document_id: str,
        title: str,
        source_filename: str | None,
        profile: dict[str, Any],
        table_id: str,
        row_index: int,
        row_cells: list[dict[str, Any]],
        sections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "document_title": title,
            "source_filename": source_filename,
            "document_profile": {
                "doc_type": str(profile.get("doc_type") or ""),
                "protocol_extractable": str(profile.get("protocol_extractable") or ""),
            },
            "table_row": {
                "table_id": table_id,
                "row_index": row_index,
                "row_summary": self._build_table_row_summary(row_cells),
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
            },
            "nearby_context": {
                "methods_text": self._first_section_text_by_type(sections, "methods"),
                "characterization_text": self._first_section_text_by_type(
                    sections,
                    "characterization",
                ),
            },
        }

    def _materialize_bundle(
        self,
        *,
        bundle: StructuredExtractionBundle,
        collection_id: str,
        document_id: str,
        section: dict[str, Any] | None,
        table_id: str | None,
        row_index: int | None,
        card_rows: list[dict[str, Any]],
        sample_variant_rows: list[dict[str, Any]],
        test_condition_rows: list[dict[str, Any]],
        baseline_rows: list[dict[str, Any]],
        measurement_rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> None:
        local_variant_ids: dict[str, str] = {}
        local_test_condition_ids: dict[str, str] = {}
        local_baseline_ids: dict[str, str] = {}
        bundle_anchor_ids: list[str] = []

        for variant in bundle.sample_variants:
            variant_id, created = self._materialize_variant_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=variant,
                section=section,
                table_id=table_id,
                row_index=row_index,
                rows=sample_variant_rows,
                document_state=document_state,
            )
            local_variant_ids[variant.variant_ref] = variant_id
            if created:
                document_state["variant_records_by_id"][variant_id] = created

        for condition in bundle.test_conditions:
            condition_id, created = self._materialize_test_condition_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=condition,
                section=section,
                table_id=table_id,
                rows=test_condition_rows,
                document_state=document_state,
            )
            local_test_condition_ids[condition.test_condition_ref] = condition_id
            if created:
                document_state["test_condition_records_by_id"][condition_id] = created

        for baseline in bundle.baseline_references:
            baseline_id, created = self._materialize_baseline_row(
                collection_id=collection_id,
                document_id=document_id,
                payload=baseline,
                section=section,
                table_id=table_id,
                rows=baseline_rows,
                document_state=document_state,
            )
            local_baseline_ids[baseline.baseline_ref] = baseline_id
            if created:
                document_state["baseline_records_by_id"][baseline_id] = created

        for result in bundle.measurement_results:
            anchors = self._materialize_anchor_payloads(
                anchors=result.anchors,
                document_id=document_id,
                section=section,
                table_id=table_id,
            )
            anchor_ids = [anchor["anchor_id"] for anchor in anchors]
            bundle_anchor_ids.extend(
                anchor_id for anchor_id in anchor_ids if anchor_id not in bundle_anchor_ids
            )
            linked_variant_id = self._resolve_local_or_single_id(
                result.variant_ref,
                local_variant_ids,
            )
            linked_test_condition_id = self._resolve_local_or_single_id(
                result.test_condition_ref,
                local_test_condition_ids,
            )
            linked_baseline_id = self._resolve_local_or_single_id(
                result.baseline_ref,
                local_baseline_ids,
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
                    "Dropped empty measurement payload collection_id=%s document_id=%s property=%s result_type=%s section_id=%s table_id=%s row_index=%s",
                    collection_id,
                    document_id,
                    self._normalize_property_name(result.property_normalized),
                    self._normalize_result_type(result.result_type),
                    self._normalize_scalar_text(section.get("section_id")) if section else None,
                    table_id,
                    row_index,
                )
                continue
            measurement_rows.append(measurement_record)

            variant_record = (
                document_state["variant_records_by_id"].get(linked_variant_id)
                if linked_variant_id
                else None
            )
            test_condition_record = (
                document_state["test_condition_records_by_id"].get(linked_test_condition_id)
                if linked_test_condition_id
                else None
            )
            baseline_record = (
                document_state["baseline_records_by_id"].get(linked_baseline_id)
                if linked_baseline_id
                else None
            )
            self._append_card_row(
                card_rows=card_rows,
                document_state=document_state,
                payload=EvidenceCardPayload(
                    claim_text=result.claim_text,
                    claim_type="property",
                    evidence_source_type="table" if table_id else "text",
                    material_system=self._to_material_payload(
                        (variant_record or {}).get("host_material_system")
                    ),
                    condition_context=self._condition_context_from_records(
                        test_condition_record,
                        baseline_record,
                    ),
                    anchors=[
                        EvidenceAnchorPayload(
                            quote=str(anchor.get("quote") or anchor.get("quote_span") or ""),
                            source_type=str(anchor.get("source_type") or "text"),
                            section_id=self._normalize_scalar_text(anchor.get("section_id")),
                            snippet_id=self._normalize_scalar_text(anchor.get("snippet_id")),
                            figure_or_table=self._normalize_scalar_text(
                                anchor.get("figure_or_table")
                            ),
                            page=self._safe_int(anchor.get("page")),
                        )
                        for anchor in anchors
                    ],
                    confidence=result.confidence,
                ),
                collection_id=collection_id,
                document_id=document_id,
                section=section,
                table_id=table_id,
            )

        for card in bundle.evidence_cards:
            anchors = self._materialize_anchor_payloads(
                anchors=card.anchors,
                document_id=document_id,
                section=section,
                table_id=table_id,
            )
            bundle_anchor_ids.extend(
                anchor["anchor_id"]
                for anchor in anchors
                if anchor["anchor_id"] not in bundle_anchor_ids
            )
            self._append_card_row(
                card_rows=card_rows,
                document_state=document_state,
                payload=card,
                collection_id=collection_id,
                document_id=document_id,
                section=section,
                table_id=table_id,
                prebuilt_anchors=anchors,
            )

        for variant_id in local_variant_ids.values():
            variant_record = document_state["variant_records_by_id"].get(variant_id)
            if variant_record is None:
                continue
            for anchor_id in bundle_anchor_ids:
                if anchor_id not in variant_record["source_anchor_ids"]:
                    variant_record["source_anchor_ids"].append(anchor_id)

        for condition_id in local_test_condition_ids.values():
            condition_record = document_state["test_condition_records_by_id"].get(condition_id)
            if condition_record is None:
                continue
            for anchor_id in bundle_anchor_ids:
                if anchor_id not in condition_record["evidence_anchor_ids"]:
                    condition_record["evidence_anchor_ids"].append(anchor_id)

        for baseline_id in local_baseline_ids.values():
            baseline_record = document_state["baseline_records_by_id"].get(baseline_id)
            if baseline_record is None:
                continue
            for anchor_id in bundle_anchor_ids:
                if anchor_id not in baseline_record["evidence_anchor_ids"]:
                    baseline_record["evidence_anchor_ids"].append(anchor_id)

    def _materialize_variant_row(
        self,
        *,
        collection_id: str,
        document_id: str,
        payload: SampleVariantPayload,
        section: dict[str, Any] | None,
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
                    "section_id": self._normalize_scalar_text(section.get("section_id"))
                    if section
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
        section: dict[str, Any] | None,
        table_id: str | None,
        rows: list[dict[str, Any]],
        document_state: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        normalized_payload = self._normalize_condition_payload(
            payload.condition_payload.model_dump(exclude_none=True)
        )
        property_type = self._normalize_property_name(payload.property_type)
        condition_key = (
            document_id,
            property_type,
            json.dumps(normalized_payload, sort_keys=True, ensure_ascii=False),
        )
        existing_id = document_state["test_condition_ids_by_key"].get(condition_key)
        if existing_id:
            return existing_id, None

        template_type = self._infer_condition_template_type(property_type)
        scope_level = "table" if table_id else ("experiment" if section and str(section.get("section_type")) == "methods" else "measurement")
        missing_fields = self._infer_missing_condition_fields(
            payload=normalized_payload,
            template_type=template_type,
            scope_level=scope_level,
        )
        condition_record = TestCondition.from_mapping(
            {
                "test_condition_id": f"tc_{uuid4().hex[:12]}",
                "document_id": document_id,
                "collection_id": collection_id,
                "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                "property_type": property_type,
                "template_type": template_type,
                "scope_level": scope_level,
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
        section: dict[str, Any] | None,
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

    def _append_card_row(
        self,
        *,
        card_rows: list[dict[str, Any]],
        document_state: dict[str, Any],
        payload: EvidenceCardPayload,
        collection_id: str,
        document_id: str,
        section: dict[str, Any] | None,
        table_id: str | None,
        prebuilt_anchors: list[dict[str, Any]] | None = None,
    ) -> None:
        anchors = prebuilt_anchors or self._materialize_anchor_payloads(
            anchors=payload.anchors,
            document_id=document_id,
            section=section,
            table_id=table_id,
        )
        anchor_signature = tuple(
            str(anchor.get("quote") or anchor.get("quote_span") or "").strip()
            for anchor in anchors
        )
        card_key = (
            document_id,
            str(payload.claim_text or "").strip().lower(),
            str(payload.claim_type or "").strip().lower(),
            str(payload.evidence_source_type or "").strip().lower(),
            anchor_signature,
        )
        if card_key in document_state["card_keys"]:
            return

        card_rows.append(
            {
                "evidence_id": f"ev_{uuid4().hex[:12]}",
                "document_id": document_id,
                "collection_id": collection_id,
                "claim_text": str(payload.claim_text or "").strip(),
                "claim_type": self._normalize_claim_type(payload.claim_type),
                "evidence_source_type": (
                    str(payload.evidence_source_type or "text")
                    if str(payload.evidence_source_type or "text") in _EVIDENCE_SOURCE_TYPES
                    else ("table" if table_id else "text")
                ),
                "evidence_anchors": anchors,
                "material_system": self._normalize_material_system_payload(
                    payload.material_system.model_dump(exclude_none=True)
                    if payload.material_system
                    else {}
                ),
                "condition_context": self._normalize_condition_context_payload(
                    payload.condition_context.model_dump(exclude_none=True)
                ),
                "confidence": payload.confidence,
                "traceability_status": (
                    TRACEABILITY_STATUS_DIRECT if anchors else TRACEABILITY_STATUS_MISSING
                ),
            }
        )
        document_state["card_keys"].add(card_key)

    def _materialize_anchor_payloads(
        self,
        *,
        anchors: list[EvidenceAnchorPayload],
        document_id: str,
        section: dict[str, Any] | None,
        table_id: str | None,
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        section_id = self._normalize_scalar_text(section.get("section_id")) if section else None
        snippet_ids = self._normalize_list(section.get("text_unit_ids")) if section else []
        for anchor in anchors:
            quote = self._normalize_scalar_text(anchor.quote)
            source_type = (
                str(anchor.source_type or "text")
                if str(anchor.source_type or "text") in _EVIDENCE_SOURCE_TYPES
                else ("table" if table_id else "text")
            )
            payload.append(
                {
                    "anchor_id": f"anchor_{uuid4().hex[:12]}",
                    "document_id": document_id,
                    "source_type": source_type,
                    "section_id": self._normalize_scalar_text(anchor.section_id) or section_id,
                    "block_id": None,
                    "snippet_id": self._normalize_scalar_text(anchor.snippet_id)
                    or (snippet_ids[0] if snippet_ids else None),
                    "figure_or_table": self._normalize_scalar_text(anchor.figure_or_table) or table_id,
                    "page": anchor.page,
                    "quote": quote,
                    "quote_span": quote,
                }
            )
        return payload

    def _resolve_local_or_single_id(
        self,
        reference: str | None,
        lookup: dict[str, str],
    ) -> str | None:
        if reference and lookup.get(reference):
            return lookup[reference]
        if len(lookup) == 1:
            return next(iter(lookup.values()))
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

    def _first_section_text_by_type(
        self,
        sections: list[dict[str, Any]],
        section_type: str,
    ) -> str | None:
        for section in sections:
            if str(section.get("section_type") or "") != section_type:
                continue
            text = str(section.get("text") or "").strip()
            if text:
                return text[:4000]
        return None

    def _build_characterization_observations(
        self,
        *,
        collection_id: str,
        cards_table: pd.DataFrame,
        sections_by_doc: dict[str, list[dict[str, Any]]],
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        characterization_cards = (
            cards_table[cards_table["claim_type"].astype(str) == "characterization"]
            if cards_table is not None and not cards_table.empty
            else pd.DataFrame(columns=cards_table.columns if cards_table is not None else [])
        )

        for document_id, sections in sections_by_doc.items():
            matching_cards = characterization_cards[
                characterization_cards["document_id"].astype(str) == str(document_id)
            ]
            anchor_ids: list[str] = []
            condition_context: dict[str, Any] = self._normalize_condition_context_payload({})
            if not matching_cards.empty:
                card_row = matching_cards.iloc[0]
                anchor_ids = self._extract_anchor_ids(card_row.get("evidence_anchors"))
                condition_context = self._normalize_condition_context_payload(
                    card_row.get("condition_context")
                )

            for section in sections:
                if str(section.get("section_type") or "") != "characterization":
                    continue
                section_text = str(section.get("text") or "").strip()
                if not section_text:
                    continue
                methods = self._extract_characterization_methods(section_text)
                if not methods:
                    continue
                observed_value, observed_unit = self._extract_observed_value_and_unit(section_text)
                for method in methods:
                    rows.append(
                        CharacterizationObservation.from_mapping(
                            {
                                "observation_id": f"obs_{uuid4().hex[:12]}",
                                "document_id": str(document_id),
                                "collection_id": collection_id,
                                "variant_id": None,
                                "characterization_type": method.lower(),
                                "observation_text": section_text,
                                "observed_value": observed_value,
                                "observed_unit": observed_unit,
                                "condition_context": condition_context,
                                "evidence_anchor_ids": anchor_ids,
                                "confidence": 0.82 if observed_value is not None else 0.76,
                                "epistemic_status": EPISTEMIC_DIRECTLY_OBSERVED,
                            }
                        ).to_record()
                    )

        return self._normalize_characterization_table(
            pd.DataFrame(rows, columns=_CHARACTERIZATION_COLUMNS),
            collection_id,
        )

    def _build_structure_features(
        self,
        characterization: pd.DataFrame,
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        if characterization is None or characterization.empty:
            return self._normalize_structure_features_table(
                pd.DataFrame(columns=_STRUCTURE_FEATURE_COLUMNS)
            )
        for _, observation in characterization.iterrows():
            rows.extend(self._extract_structure_features_from_observation(observation))
        return self._normalize_structure_features_table(
            pd.DataFrame(rows, columns=_STRUCTURE_FEATURE_COLUMNS)
        )

    def _attach_variant_ids_to_characterization(
        self,
        characterization: pd.DataFrame,
        sample_variants: pd.DataFrame,
    ) -> pd.DataFrame:
        if characterization is None or characterization.empty:
            return self._normalize_characterization_table(characterization, None)
        if sample_variants is None or sample_variants.empty:
            return self._normalize_characterization_table(characterization, None)

        normalized = characterization.copy()
        for index, row in normalized.iterrows():
            document_id = str(row.get("document_id") or "")
            document_variants = self._filter_rows_by_document(sample_variants, document_id)
            if len(document_variants) == 1:
                normalized.at[index, "variant_id"] = document_variants.iloc[0]["variant_id"]
        return self._normalize_characterization_table(normalized, None)

    def _attach_variant_ids_to_baseline_references(
        self,
        baseline_references: pd.DataFrame,
        sample_variants: pd.DataFrame,
    ) -> pd.DataFrame:
        if baseline_references is None or baseline_references.empty:
            return self._normalize_baseline_references_table(baseline_references, None)

        normalized = baseline_references.copy()
        for index, row in normalized.iterrows():
            document_id = str(row.get("document_id") or "")
            label = str(row.get("baseline_label") or "").strip().lower()
            if not label:
                continue
            document_variants = self._filter_rows_by_document(sample_variants, document_id)
            matched = document_variants[
                document_variants["variant_label"].astype(str).str.lower() == label
            ]
            if len(matched) == 1:
                normalized.at[index, "variant_id"] = matched.iloc[0]["variant_id"]
        return self._normalize_baseline_references_table(normalized, None)

    def _attach_structure_feature_ids_to_variants(
        self,
        sample_variants: pd.DataFrame,
        structure_features: pd.DataFrame,
    ) -> pd.DataFrame:
        if sample_variants is None or sample_variants.empty:
            return self._normalize_sample_variants_table(sample_variants, None)

        normalized = sample_variants.copy()
        for index, row in normalized.iterrows():
            variant_id = str(row.get("variant_id") or "")
            feature_ids = []
            if not structure_features.empty:
                matched = structure_features[
                    structure_features["variant_id"].astype(str) == variant_id
                ]
                feature_ids = [
                    str(value) for value in matched["feature_id"].tolist() if str(value).strip()
                ]
            normalized.at[index, "structure_feature_ids"] = feature_ids
        return self._normalize_sample_variants_table(normalized, None)

    def _filter_rows_by_document(
        self,
        frame: pd.DataFrame | None,
        document_id: str,
    ) -> pd.DataFrame:
        if frame is None or frame.empty or "document_id" not in frame.columns:
            return pd.DataFrame(columns=frame.columns if frame is not None else [])
        return frame[frame["document_id"].astype(str) == str(document_id)]

    def _group_table_rows(
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
        normalized = normalize_backbone_value(value)
        if normalized is None:
            return None
        if isinstance(normalized, bool):
            return str(normalized).lower()
        if isinstance(normalized, int):
            return normalized
        if isinstance(normalized, float):
            if pd.isna(normalized):
                return None
            if normalized.is_integer():
                return int(normalized)
            return normalized
        text = str(normalized).strip()
        if not text:
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
            parsed = normalize_backbone_value(value)
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
        observation: pd.Series,
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

    def _group_sections_by_document(
        self,
        sections: pd.DataFrame,
    ) -> dict[str, list[dict[str, Any]]]:
        if sections is None or sections.empty:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for _, row in sections.iterrows():
            document_id = str(row.get("paper_id") or row.get("document_id") or row.get("id") or "")
            grouped.setdefault(document_id, []).append(dict(row))
        return grouped

    def _group_table_cells_by_document(
        self,
        table_cells: pd.DataFrame,
    ) -> dict[str, list[dict[str, Any]]]:
        if table_cells is None or table_cells.empty:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for _, row in table_cells.iterrows():
            document_id = str(row.get("document_id") or row.get("id") or "")
            grouped.setdefault(document_id, []).append(dict(row))
        return grouped

    def _normalize_cards_table(
        self,
        cards: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if cards is None or cards.empty:
            return pd.DataFrame(
                columns=[
                    "evidence_id",
                    "document_id",
                    "collection_id",
                    "claim_text",
                    "claim_type",
                    "evidence_source_type",
                    "evidence_anchors",
                    "material_system",
                    "condition_context",
                    "confidence",
                    "traceability_status",
                ]
            )

        normalized = cards.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        if "evidence_anchors" in normalized.columns:
            normalized["evidence_anchors"] = normalized["evidence_anchors"].apply(self._normalize_object)
        if "material_system" in normalized.columns:
            normalized["material_system"] = normalized["material_system"].apply(
                self._normalize_material_system_payload
            )
        if "condition_context" in normalized.columns:
            normalized["condition_context"] = normalized["condition_context"].apply(
                self._normalize_condition_context_payload
            )
        if "confidence" in normalized.columns:
            normalized["confidence"] = normalized["confidence"].apply(
                lambda value: round(float(value or 0.0), 2)
            )
        return normalized[
            [
                "evidence_id",
                "document_id",
                "collection_id",
                "claim_text",
                "claim_type",
                "evidence_source_type",
                "evidence_anchors",
                "material_system",
                "condition_context",
                "confidence",
                "traceability_status",
            ]
        ]

    def _serialize_card_row(self, row: pd.Series) -> dict[str, Any]:
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
        sections = content.get("sections") if isinstance(content.get("sections"), list) else []
        section_id = self._normalize_scalar_text(anchor.get("section_id"))
        section = self._find_section_by_id(section_id, sections) if section_id else None

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
            section = section or self._find_section_for_char_range(explicit_char_range, sections)
            section_id = section_id or (
                self._normalize_scalar_text(section.get("section_id")) if section else None
            )
            return {
                **anchor,
                "section_id": section_id,
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
                "section_id": section_id,
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
            if section is None:
                section = self._find_section_by_snippet_id(snippet_id, sections)
            if section is None:
                section = self._find_section_for_quote(match_text, sections)

            if section is not None:
                local_index = str(section.get("text") or "").find(match_text)
                if local_index >= 0 and section.get("start_offset") is not None:
                    section_start = self._safe_int(section.get("start_offset"))
                    resolved_char_range = {
                        "start": section_start + local_index,
                        "end": section_start + local_index + len(match_text),
                    }
                    section_id = self._normalize_scalar_text(section.get("section_id")) or section_id

            if resolved_char_range is None and full_text:
                global_index = full_text.find(match_text)
                if global_index >= 0:
                    resolved_char_range = {
                        "start": global_index,
                        "end": global_index + len(match_text),
                    }
                    section = section or self._find_section_for_char_range(resolved_char_range, sections)
                    section_id = (
                        self._normalize_scalar_text(section.get("section_id")) if section else section_id
                    ) or section_id

        if resolved_char_range is not None:
            return {
                **anchor,
                "section_id": section_id,
                "char_range": resolved_char_range,
                "bbox": None,
                "locator_type": "char_range",
                "locator_confidence": "medium" if snippet_text else "high",
                "quote": match_text,
                "quote_span": match_text,
            }

        if section is None:
            section = self._find_section_by_snippet_id(snippet_id, sections)
        section_id = section_id or (
            self._normalize_scalar_text(section.get("section_id")) if section else None
        )
        if section_id is None:
            return None

        return {
            **anchor,
            "section_id": section_id,
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
        text_units: pd.DataFrame | None,
        document_id: str,
    ) -> dict[str, dict[str, Any]]:
        if text_units is None or text_units.empty:
            return {}

        lookup: dict[str, dict[str, Any]] = {}
        for _, row in text_units.iterrows():
            text_unit_id = self._normalize_scalar_text(row.get("id"))
            if text_unit_id is None:
                continue
            document_ids = self._normalize_list(row.get("document_ids"))
            if document_ids and str(document_id) not in document_ids:
                continue
            lookup[text_unit_id] = dict(row)
        return lookup

    def _find_section_by_id(
        self,
        section_id: str | None,
        sections: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not section_id:
            return None
        for section in sections:
            if self._normalize_scalar_text(section.get("section_id")) == section_id:
                return section
        return None

    def _find_section_by_snippet_id(
        self,
        snippet_id: str | None,
        sections: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not snippet_id:
            return None
        for section in sections:
            if snippet_id in self._normalize_list(section.get("text_unit_ids")):
                return section
        return None

    def _find_section_for_quote(
        self,
        quote: str,
        sections: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for section in sections:
            if quote and quote in str(section.get("text") or ""):
                return section
        return None

    def _find_section_for_char_range(
        self,
        char_range: dict[str, int],
        sections: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        start = self._safe_int(char_range.get("start"))
        end = self._safe_int(char_range.get("end"))
        if start is None or end is None:
            return None
        for section in sections:
            section_start = self._safe_int(section.get("start_offset"))
            section_end = self._safe_int(section.get("end_offset"))
            if section_start is None or section_end is None:
                continue
            if section_start <= start and end <= section_end:
                return section
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
        return normalize_backbone_value(value)

    def _normalize_list(self, value: Any) -> list[str]:
        normalized = self._normalize_object(value)
        if normalized is None:
            return []
        if isinstance(normalized, list):
            return [str(item) for item in normalized if str(item).strip()]
        return [str(normalized)]

    def _normalize_sample_variants_table(
        self,
        sample_variants: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if sample_variants is None or sample_variants.empty:
            return pd.DataFrame(columns=_SAMPLE_VARIANT_COLUMNS)

        normalized = sample_variants.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        if "domain_profile" not in normalized.columns:
            normalized["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
        records = []
        for _, row in normalized.iterrows():
            payload = dict(row)
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
        return pd.DataFrame(records, columns=_SAMPLE_VARIANT_COLUMNS)

    def _normalize_measurement_results_table(
        self,
        measurement_results: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if measurement_results is None or measurement_results.empty:
            return pd.DataFrame(columns=_MEASUREMENT_RESULT_COLUMNS)

        normalized = measurement_results.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        if "domain_profile" not in normalized.columns:
            normalized["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
        records = []
        for _, row in normalized.iterrows():
            payload = dict(row)
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
            records.append(MeasurementResult.from_mapping(payload).to_record())
        return pd.DataFrame(records, columns=_MEASUREMENT_RESULT_COLUMNS)

    def _normalize_characterization_table(
        self,
        characterization: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if characterization is None or characterization.empty:
            return pd.DataFrame(columns=_CHARACTERIZATION_COLUMNS)

        normalized = characterization.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        records = []
        for _, row in normalized.iterrows():
            payload = dict(row)
            payload["condition_context"] = self._normalize_condition_context_payload(
                row.get("condition_context")
            )
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            records.append(CharacterizationObservation.from_mapping(payload).to_record())
        return pd.DataFrame(records, columns=_CHARACTERIZATION_COLUMNS)

    def _normalize_structure_features_table(
        self,
        structure_features: pd.DataFrame,
    ) -> pd.DataFrame:
        if structure_features is None or structure_features.empty:
            return pd.DataFrame(columns=_STRUCTURE_FEATURE_COLUMNS)

        records = []
        for _, row in structure_features.iterrows():
            payload = dict(row)
            payload["source_observation_ids"] = self._normalize_list(
                row.get("source_observation_ids")
            )
            records.append(StructureFeature.from_mapping(payload).to_record())
        return pd.DataFrame(records, columns=_STRUCTURE_FEATURE_COLUMNS)

    def _normalize_test_conditions_table(
        self,
        test_conditions: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if test_conditions is None or test_conditions.empty:
            return pd.DataFrame(columns=_TEST_CONDITION_COLUMNS)

        normalized = test_conditions.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        if "domain_profile" not in normalized.columns:
            normalized["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
        records = []
        for _, row in normalized.iterrows():
            payload = dict(row)
            payload["condition_payload"] = self._normalize_condition_payload(
                row.get("condition_payload")
            )
            payload["missing_fields"] = self._normalize_list(row.get("missing_fields"))
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            records.append(TestCondition.from_mapping(payload).to_record())
        return pd.DataFrame(records, columns=_TEST_CONDITION_COLUMNS)

    def _normalize_baseline_references_table(
        self,
        baseline_references: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if baseline_references is None or baseline_references.empty:
            return pd.DataFrame(columns=_BASELINE_REFERENCE_COLUMNS)

        normalized = baseline_references.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        if "domain_profile" not in normalized.columns:
            normalized["domain_profile"] = CORE_NEUTRAL_DOMAIN_PROFILE
        records = []
        for _, row in normalized.iterrows():
            payload = dict(row)
            payload["evidence_anchor_ids"] = self._normalize_list(
                row.get("evidence_anchor_ids")
            )
            records.append(BaselineReference.from_mapping(payload).to_record())
        return pd.DataFrame(records, columns=_BASELINE_REFERENCE_COLUMNS)

    def _resolve_output_dir(self, collection_id: str) -> Path:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            artifacts = None
        if artifacts and artifacts.get("output_path"):
            return Path(str(artifacts["output_path"])).expanduser().resolve()
        return self.collection_service.get_paths(collection_id).output_dir.resolve()


__all__ = [
    "EvidenceCardNotFoundError",
    "EvidenceCardsNotReadyError",
    "EvidenceCardService",
]
