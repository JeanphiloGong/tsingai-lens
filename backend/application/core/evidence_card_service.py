from __future__ import annotations

import json
import re
from urllib.parse import urlencode
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

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
    DOC_TYPE_UNCERTAIN,
    EPISTEMIC_DIRECTLY_OBSERVED,
    EPISTEMIC_INFERRED_FROM_CHARACTERIZATION,
    EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE,
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    EPISTEMIC_UNRESOLVED,
    TRACEABILITY_STATUS_DIRECT,
    TRACEABILITY_STATUS_MISSING,
    TRACEABILITY_STATUS_PARTIAL,
)
from infra.persistence.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)
from application.source.collection_service import CollectionService
from application.source.artifact_input_service import (
    build_document_records,
    load_collection_inputs,
    load_sections_artifact,
    load_table_cells_artifact,
)
from application.core.document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.source.artifact_registry_service import ArtifactRegistryService


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

_EVIDENCE_SOURCE_TYPES = {"figure", "table", "method", "text"}

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

_MECHANISM_HINTS = (
    "may be linked",
    "attributed to",
    "due to",
    "because of",
    "proposed as the cause",
)

_PROPERTY_SENTENCE_HINTS = (
    "improv",
    "increase",
    "decrease",
    "higher",
    "lower",
    "enhance",
    "reduc",
    "denser",
    "better",
)

_TEMP_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:c|°c|k|f)\b", re.IGNORECASE)
_TIME_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs)\b",
    re.IGNORECASE,
)
_ATMOSPHERE_PATTERN = re.compile(
    r"\b(?:under|in)\s+(air|argon|ar|nitrogen|n2|vacuum)\b", re.IGNORECASE
)
_TABLE_NUMERIC_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_TABLE_SAMPLE_HEADER_HINTS = ("sample", "group", "variant", "condition")
_TABLE_BASELINE_HEADER_HINTS = ("baseline", "control", "reference")
_TABLE_VARIANT_HEADER_HINTS = (
    "current",
    "power",
    "speed",
    "heating",
    "beam",
    "strategy",
    "temperature",
    "orientation",
    "direction",
    "content",
    "wt%",
    "vol%",
    "loading",
    "ratio",
)
_OBSERVED_VALUE_PATTERN = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*(nm|um|μm|mm|cm|m2/g|m\^2/g|m²/g|mpa|gpa|pa|%)\b",
    re.IGNORECASE,
)
_RANGE_VALUE_PATTERN = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*(?:-|to|–)\s*([-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_CLAIM_VALUE_PATTERN = re.compile(
    r"\b(?:of|to|at)\s+([-+]?\d+(?:\.\d+)?)\s*([A-Za-z%/0-9\-\^²·]+)?",
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
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )

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

        cards: list[dict[str, Any]] = []
        for _, row in document_records.iterrows():
            document_id = str(row.get("paper_id") or "")
            profile = profile_by_doc.get(document_id)
            if not profile:
                continue
            title = str(row.get("title") or document_id)
            text = str(row.get("text") or "")
            doc_sections = sections_by_doc.get(document_id, [])
            cards.extend(
                self._build_cards_for_document(
                    collection_id=collection_id,
                    document_id=document_id,
                    title=title,
                    text=text,
                    text_unit_ids=self._normalize_list(row.get("text_unit_ids")),
                    profile=profile,
                    sections=doc_sections,
                    table_cells=table_cells_by_doc.get(document_id, []),
                )
            )

        cards_table = pd.DataFrame(
            cards,
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
        )
        cards_table = self._normalize_cards_table(cards_table, collection_id)

        base_dir.mkdir(parents=True, exist_ok=True)
        prepare_frame_for_storage(
            cards_table,
            _EVIDENCE_JSON_COLUMNS,
        ).to_parquet(base_dir / _EVIDENCE_CARDS_FILE, index=False)
        self._persist_core_artifacts(
            base_dir=base_dir,
            collection_id=collection_id,
            cards_table=cards_table,
            sections_by_doc=sections_by_doc,
            table_cells_by_doc=table_cells_by_doc,
        )
        self.artifact_registry_service.upsert(collection_id, base_dir)

        return cards_table

    def _persist_core_artifacts(
        self,
        *,
        base_dir: Path,
        collection_id: str,
        cards_table: pd.DataFrame,
        sections_by_doc: dict[str, list[dict[str, Any]]],
        table_cells_by_doc: dict[str, list[dict[str, Any]]],
    ) -> None:
        characterization = self._build_characterization_observations(
            collection_id=collection_id,
            cards_table=cards_table,
            sections_by_doc=sections_by_doc,
            table_cells_by_doc=table_cells_by_doc,
        )
        test_conditions = self._build_test_conditions(cards_table, collection_id)
        baseline_references = self._build_baseline_references(cards_table, collection_id)
        sample_variants = self._build_sample_variants(
            collection_id=collection_id,
            cards_table=cards_table,
            table_cells_by_doc=table_cells_by_doc,
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
        measurement_results = self._build_measurement_results(
            collection_id=collection_id,
            cards_table=cards_table,
            sample_variants=sample_variants,
            characterization=characterization,
            structure_features=structure_features,
            test_conditions=test_conditions,
            baseline_references=baseline_references,
        )

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

    def _build_characterization_observations(
        self,
        *,
        collection_id: str,
        cards_table: pd.DataFrame,
        sections_by_doc: dict[str, list[dict[str, Any]]],
        table_cells_by_doc: dict[str, list[dict[str, Any]]],
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
                                "confidence": 0.84 if observed_value is not None else 0.78,
                                "epistemic_status": EPISTEMIC_DIRECTLY_OBSERVED,
                            }
                        ).to_record()
                    )

        for document_id, table_cells in table_cells_by_doc.items():
            grouped_rows: dict[tuple[str, int], list[dict[str, Any]]] = {}
            for cell in table_cells:
                table_id = str(cell.get("table_id") or "").strip()
                row_index = self._safe_int(cell.get("row_index"))
                if not table_id or row_index is None or row_index <= 0:
                    continue
                grouped_rows.setdefault((table_id, row_index), []).append(cell)

            for (_table_id, _row_index), row_cells in grouped_rows.items():
                summary = self._build_table_row_summary(row_cells)
                methods = self._extract_characterization_methods(summary)
                if not methods:
                    continue
                observed_value, observed_unit = self._extract_observed_value_and_unit(summary)
                for method in methods:
                    rows.append(
                        CharacterizationObservation.from_mapping(
                            {
                                "observation_id": f"obs_{uuid4().hex[:12]}",
                                "document_id": str(document_id),
                                "collection_id": collection_id,
                                "variant_id": None,
                                "characterization_type": method.lower(),
                                "observation_text": summary,
                                "observed_value": observed_value,
                                "observed_unit": observed_unit,
                                "condition_context": self._normalize_condition_context_payload({}),
                                "evidence_anchor_ids": [],
                                "confidence": 0.68,
                                "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
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

    def _build_test_conditions(
        self,
        cards_table: pd.DataFrame,
        collection_id: str,
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        dedupe: set[tuple[str, str, str, str]] = set()
        if cards_table is None or cards_table.empty:
            return self._normalize_test_conditions_table(
                pd.DataFrame(columns=_TEST_CONDITION_COLUMNS),
                collection_id,
            )

        for _, row in cards_table.iterrows():
            condition_context = self._normalize_condition_context_payload(
                row.get("condition_context")
            )
            process_context = condition_context.get("process", {})
            test_context = condition_context.get("test", {})
            payload = {
                "method": test_context.get("method"),
                "methods": self._normalize_list(test_context.get("methods")),
                "temperatures_c": list(process_context.get("temperatures_c") or []),
                "durations": list(process_context.get("durations") or []),
                "atmosphere": process_context.get("atmosphere"),
            }
            payload = {
                key: value
                for key, value in payload.items()
                if value not in (None, "", [], {})
            }
            if not payload:
                continue

            property_type = self._infer_property_type_from_card(
                claim_type=str(row.get("claim_type") or ""),
                claim_text=str(row.get("claim_text") or ""),
            )
            template_type = self._infer_condition_template_type(property_type)
            scope_level = self._infer_condition_scope_level(
                str(row.get("evidence_source_type") or "")
            )
            missing_fields = self._infer_missing_condition_fields(
                payload=payload,
                template_type=template_type,
                scope_level=scope_level,
            )
            condition_completeness = self._infer_condition_completeness(
                payload=payload,
                missing_fields=missing_fields,
            )
            dedupe_key = (
                str(row.get("document_id") or ""),
                property_type,
                scope_level,
                json.dumps(payload, sort_keys=True, ensure_ascii=False),
            )
            if dedupe_key in dedupe:
                continue
            dedupe.add(dedupe_key)
            rows.append(
                TestCondition.from_mapping(
                    {
                        "test_condition_id": f"tc_{uuid4().hex[:12]}",
                        "document_id": str(row.get("document_id") or ""),
                        "collection_id": collection_id,
                        "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                        "property_type": property_type,
                        "template_type": template_type,
                        "scope_level": scope_level,
                        "condition_payload": payload,
                        "condition_completeness": condition_completeness,
                        "missing_fields": missing_fields,
                        "evidence_anchor_ids": self._extract_anchor_ids(
                            row.get("evidence_anchors")
                        ),
                        "confidence": 0.82 if condition_completeness == "complete" else 0.72,
                        "epistemic_status": (
                            EPISTEMIC_NORMALIZED_FROM_EVIDENCE
                            if condition_completeness != "unresolved"
                            else EPISTEMIC_UNRESOLVED
                        ),
                    }
                ).to_record()
            )

        return self._normalize_test_conditions_table(
            pd.DataFrame(rows, columns=_TEST_CONDITION_COLUMNS),
            collection_id,
        )

    def _build_baseline_references(
        self,
        cards_table: pd.DataFrame,
        collection_id: str,
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        dedupe: set[tuple[str, str, str]] = set()
        if cards_table is None or cards_table.empty:
            return self._normalize_baseline_references_table(
                pd.DataFrame(columns=_BASELINE_REFERENCE_COLUMNS),
                collection_id,
            )

        for _, row in cards_table.iterrows():
            condition_context = self._normalize_condition_context_payload(
                row.get("condition_context")
            )
            baseline_label = str(
                (condition_context.get("baseline") or {}).get("control") or ""
            ).strip()
            if not baseline_label:
                continue

            baseline_scope = self._infer_baseline_scope(
                str(row.get("evidence_source_type") or "")
            )
            dedupe_key = (
                str(row.get("document_id") or ""),
                baseline_label.lower(),
                baseline_scope,
            )
            if dedupe_key in dedupe:
                continue
            dedupe.add(dedupe_key)

            baseline_type = self._classify_baseline_type(baseline_label)
            epistemic_status = (
                EPISTEMIC_NORMALIZED_FROM_EVIDENCE
                if self._baseline_label_is_explicit(baseline_label)
                else EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE
            )
            rows.append(
                BaselineReference.from_mapping(
                    {
                        "baseline_id": f"base_{uuid4().hex[:12]}",
                        "document_id": str(row.get("document_id") or ""),
                        "collection_id": collection_id,
                        "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                        "variant_id": None,
                        "baseline_type": baseline_type,
                        "baseline_label": baseline_label,
                        "baseline_scope": baseline_scope,
                        "evidence_anchor_ids": self._extract_anchor_ids(
                            row.get("evidence_anchors")
                        ),
                        "confidence": (
                            0.8
                            if epistemic_status == EPISTEMIC_NORMALIZED_FROM_EVIDENCE
                            else 0.64
                        ),
                        "epistemic_status": epistemic_status,
                    }
                ).to_record()
            )

        return self._normalize_baseline_references_table(
            pd.DataFrame(rows, columns=_BASELINE_REFERENCE_COLUMNS),
            collection_id,
        )

    def _build_sample_variants(
        self,
        *,
        collection_id: str,
        cards_table: pd.DataFrame,
        table_cells_by_doc: dict[str, list[dict[str, Any]]],
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        dedupe: set[tuple[str, str, str, str]] = set()
        document_ids = set(table_cells_by_doc)
        if cards_table is not None and not cards_table.empty:
            document_ids.update(cards_table["document_id"].astype(str).tolist())

        for document_id in sorted(document_ids):
            document_cards = self._filter_rows_by_document(cards_table, document_id)
            host_material_system = self._resolve_host_material_system(document_cards)
            document_process_context = self._merge_process_contexts(document_cards)
            table_rows = self._group_table_rows(table_cells_by_doc.get(document_id, []))
            table_variant_count = 0

            for (table_id, row_index), row_cells in table_rows.items():
                ordered_cells = sorted(
                    row_cells,
                    key=lambda item: self._safe_int(item.get("col_index")) or 0,
                )
                sample_label = self._resolve_table_sample_label(ordered_cells)
                variable_header, variable_value = self._resolve_table_variant_axis(ordered_cells)
                if not sample_label and variable_header is None:
                    continue
                variant_label = (
                    sample_label
                    or f"{variable_header}: {variable_value}"
                    if variable_header and variable_value is not None
                    else None
                )
                if not variant_label:
                    continue
                variable_axis_type = self._infer_variable_axis_type(variable_header)
                dedupe_key = (
                    str(document_id),
                    str(variant_label).strip().lower(),
                    str(variable_axis_type or "").strip().lower(),
                    str(variable_value if variable_value is not None else "").strip().lower(),
                )
                if dedupe_key in dedupe:
                    continue
                dedupe.add(dedupe_key)
                row_summary = self._build_table_row_summary(ordered_cells)
                rows.append(
                    SampleVariant.from_mapping(
                        {
                            "variant_id": f"var_{uuid4().hex[:12]}",
                            "document_id": str(document_id),
                            "collection_id": collection_id,
                            "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                            "variant_label": variant_label,
                            "host_material_system": host_material_system,
                            "composition": host_material_system.get("composition"),
                            "variable_axis_type": variable_axis_type,
                            "variable_value": self._normalize_variant_value(variable_value),
                            "process_context": self._build_variant_process_context(
                                document_process_context=document_process_context,
                                variable_axis_type=variable_axis_type,
                                variable_value=variable_value,
                            ),
                            "profile_payload": {
                                "source_kind": "table_row",
                                "table_id": table_id,
                                "row_index": row_index,
                                "row_summary": row_summary,
                                "variable_header": variable_header,
                                "baseline_label": (
                                    self._resolve_table_baseline(ordered_cells) or {}
                                ).get("control"),
                            },
                            "structure_feature_ids": [],
                            "source_anchor_ids": self._collect_table_row_anchor_ids(
                                document_cards,
                                table_id=table_id,
                                row_summary=row_summary,
                                sample_label=sample_label,
                            ),
                            "confidence": (
                                0.86 if sample_label and variable_value is not None else 0.76
                            ),
                            "epistemic_status": EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
                        }
                    ).to_record()
                )
                table_variant_count += 1

            non_table_property_cards = document_cards[
                (document_cards["claim_type"].astype(str) == "property")
                & (document_cards["evidence_source_type"].astype(str) != "table")
            ] if not document_cards.empty else pd.DataFrame(columns=document_cards.columns)
            if table_variant_count == 0 or not non_table_property_cards.empty:
                default_variant = self._build_default_sample_variant(
                    collection_id=collection_id,
                    document_id=document_id,
                    document_cards=document_cards,
                    host_material_system=host_material_system,
                    document_process_context=document_process_context,
                )
                if default_variant is not None:
                    dedupe_key = (
                        str(document_id),
                        str(default_variant["variant_label"]).strip().lower(),
                        str(default_variant["variable_axis_type"] or "").strip().lower(),
                        str(default_variant["variable_value"] or "").strip().lower(),
                    )
                    if dedupe_key not in dedupe:
                        dedupe.add(dedupe_key)
                        rows.append(default_variant)

        return self._normalize_sample_variants_table(
            pd.DataFrame(rows, columns=_SAMPLE_VARIANT_COLUMNS),
            collection_id,
        )

    def _attach_variant_ids_to_characterization(
        self,
        characterization: pd.DataFrame,
        sample_variants: pd.DataFrame,
    ) -> pd.DataFrame:
        if characterization is None or characterization.empty:
            return self._normalize_characterization_table(characterization, None)

        normalized = characterization.copy()
        for index, row in normalized.iterrows():
            matched_variant_id = self._match_variant_id_from_text(
                document_id=str(row.get("document_id") or ""),
                text=str(row.get("observation_text") or ""),
                sample_variants=sample_variants,
            )
            if matched_variant_id:
                normalized.at[index, "variant_id"] = matched_variant_id
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
            matched_variant_id = self._match_variant_id_from_label(
                document_id=str(row.get("document_id") or ""),
                label=str(row.get("baseline_label") or ""),
                sample_variants=sample_variants,
            )
            if matched_variant_id:
                normalized.at[index, "variant_id"] = matched_variant_id
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
            document_id = str(row.get("document_id") or "")
            feature_ids = self._collect_related_structure_feature_ids(
                document_id=document_id,
                variant_id=variant_id or None,
                structure_features=structure_features,
                sample_variants=sample_variants,
            )
            normalized.at[index, "structure_feature_ids"] = feature_ids
        return self._normalize_sample_variants_table(normalized, None)

    def _build_measurement_results(
        self,
        *,
        collection_id: str,
        cards_table: pd.DataFrame,
        sample_variants: pd.DataFrame,
        characterization: pd.DataFrame,
        structure_features: pd.DataFrame,
        test_conditions: pd.DataFrame,
        baseline_references: pd.DataFrame,
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        if cards_table is None or cards_table.empty:
            return self._normalize_measurement_results_table(
                pd.DataFrame(columns=_MEASUREMENT_RESULT_COLUMNS),
                collection_id,
            )

        property_cards = cards_table[cards_table["claim_type"].astype(str) == "property"]
        for _, row in property_cards.iterrows():
            document_id = str(row.get("document_id") or "")
            claim_text = str(row.get("claim_text") or "").strip()
            property_normalized = self._infer_property_type_from_card(
                claim_type=str(row.get("claim_type") or ""),
                claim_text=claim_text,
            )
            result_type = self._infer_result_type(
                claim_text=claim_text,
                property_normalized=property_normalized,
            )
            value_payload, unit = self._build_result_value_payload(
                claim_text=claim_text,
                result_type=result_type,
            )
            if not value_payload:
                continue

            variant_id = self._resolve_variant_id_for_card(
                card_row=row,
                sample_variants=sample_variants,
            )
            rows.append(
                MeasurementResult.from_mapping(
                    {
                        "result_id": f"res_{uuid4().hex[:12]}",
                        "document_id": document_id,
                        "collection_id": collection_id,
                        "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                        "variant_id": variant_id,
                        "property_normalized": property_normalized,
                        "result_type": result_type,
                        "value_payload": value_payload,
                        "unit": unit,
                        "test_condition_id": self._resolve_test_condition_id(
                            card_row=row,
                            property_normalized=property_normalized,
                            test_conditions=test_conditions,
                        ),
                        "baseline_id": self._resolve_baseline_id(
                            card_row=row,
                            baseline_references=baseline_references,
                        ),
                        "structure_feature_ids": self._collect_related_structure_feature_ids(
                            document_id=document_id,
                            variant_id=variant_id,
                            structure_features=structure_features,
                            sample_variants=sample_variants,
                        ),
                        "characterization_observation_ids": self._collect_related_characterization_ids(
                            document_id=document_id,
                            variant_id=variant_id,
                            characterization=characterization,
                            sample_variants=sample_variants,
                        ),
                        "evidence_anchor_ids": self._extract_anchor_ids(
                            row.get("evidence_anchors")
                        ),
                        "traceability_status": str(
                            row.get("traceability_status") or TRACEABILITY_STATUS_MISSING
                        ),
                        "result_source_type": str(row.get("evidence_source_type") or "text"),
                        "epistemic_status": (
                            EPISTEMIC_DIRECTLY_OBSERVED
                            if str(row.get("evidence_source_type") or "") == "table"
                            else EPISTEMIC_NORMALIZED_FROM_EVIDENCE
                        ),
                    }
                ).to_record()
            )

        return self._normalize_measurement_results_table(
            pd.DataFrame(rows, columns=_MEASUREMENT_RESULT_COLUMNS),
            collection_id,
        )

    def _filter_rows_by_document(
        self,
        frame: pd.DataFrame | None,
        document_id: str,
    ) -> pd.DataFrame:
        if frame is None or frame.empty or "document_id" not in frame.columns:
            return pd.DataFrame(columns=frame.columns if frame is not None else [])
        return frame[frame["document_id"].astype(str) == str(document_id)]

    def _resolve_host_material_system(
        self,
        document_cards: pd.DataFrame,
    ) -> dict[str, Any]:
        if document_cards is not None and not document_cards.empty:
            for _, row in document_cards.iterrows():
                material_system = self._normalize_material_system_payload(
                    row.get("material_system")
                )
                if material_system.get("family") != "unspecified material system":
                    return material_system
        return self._normalize_material_system_payload({})

    def _merge_process_contexts(
        self,
        document_cards: pd.DataFrame,
    ) -> dict[str, Any]:
        merged = {
            "temperatures_c": [],
            "durations": [],
            "atmosphere": None,
        }
        if document_cards is None or document_cards.empty:
            return merged

        for _, row in document_cards.iterrows():
            context = self._normalize_condition_context_payload(row.get("condition_context"))
            process = context.get("process", {})
            for value in process.get("temperatures_c") or []:
                if value not in merged["temperatures_c"]:
                    merged["temperatures_c"].append(value)
            for value in process.get("durations") or []:
                if value not in merged["durations"]:
                    merged["durations"].append(value)
            if merged["atmosphere"] is None and process.get("atmosphere"):
                merged["atmosphere"] = process.get("atmosphere")
        return merged

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

    def _resolve_table_variant_axis(
        self,
        row_cells: list[dict[str, Any]],
    ) -> tuple[str | None, Any]:
        for cell in row_cells:
            header = str(cell.get("header_path") or "").strip()
            if not header:
                continue
            if self._is_table_sample_header(header) or self._is_table_baseline_header(header):
                continue
            if self._infer_property_type_from_header(header) != "qualitative":
                continue
            cell_text = str(cell.get("cell_text") or "").strip()
            if not cell_text:
                continue
            return header, cell_text
        return None, None

    def _infer_property_type_from_header(
        self,
        header: str,
    ) -> str:
        lowered = str(header or "").lower()
        for token, normalized in _PROPERTY_HINTS:
            if token in lowered:
                return normalized
        return "qualitative"

    def _infer_variable_axis_type(
        self,
        header: str | None,
    ) -> str:
        lowered = str(header or "").strip().lower()
        if not lowered:
            return "unspecified_variant_axis"
        if "current" in lowered:
            return "induction_current"
        if "beam" in lowered and "strategy" in lowered:
            return "beam_strategy"
        if "heating" in lowered:
            return "in_situ_heating"
        if "temperature" in lowered:
            return "temperature"
        if "power" in lowered:
            return "laser_power"
        if "speed" in lowered:
            return "scan_speed"
        if "orientation" in lowered:
            return "specimen_orientation"
        if "direction" in lowered:
            return "build_direction"
        if any(token in lowered for token in ("wt%", "vol%", "content", "loading", "ratio")):
            return "composition_loading"
        normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        return normalized or "unspecified_variant_axis"

    def _normalize_variant_value(self, value: Any) -> Any:
        text = str(value or "").strip()
        if not text:
            return None
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
            return float(text)
        return text

    def _build_variant_process_context(
        self,
        *,
        document_process_context: dict[str, Any],
        variable_axis_type: str,
        variable_value: Any,
    ) -> dict[str, Any]:
        payload = dict(document_process_context)
        if variable_axis_type in {
            "induction_current",
            "beam_strategy",
            "in_situ_heating",
            "temperature",
            "laser_power",
            "scan_speed",
            "specimen_orientation",
            "build_direction",
        } and variable_value not in (None, ""):
            payload[variable_axis_type] = self._normalize_variant_value(variable_value)
        return self._normalize_condition_payload(payload)

    def _collect_table_row_anchor_ids(
        self,
        document_cards: pd.DataFrame,
        *,
        table_id: str,
        row_summary: str,
        sample_label: str | None,
    ) -> list[str]:
        if document_cards is None or document_cards.empty:
            return []
        anchor_ids: list[str] = []
        table_cards = document_cards[
            document_cards["evidence_source_type"].astype(str) == "table"
        ]
        for _, row in table_cards.iterrows():
            claim_text = str(row.get("claim_text") or "")
            anchors = self._normalize_evidence_anchors_payload(row.get("evidence_anchors"))
            for anchor in anchors:
                if str(anchor.get("figure_or_table") or "") != str(table_id):
                    continue
                anchor_quote = str(anchor.get("quote_span") or anchor.get("quote") or "")
                label_match = sample_label and sample_label.lower() in claim_text.lower()
                summary_match = row_summary and anchor_quote == row_summary
                if not label_match and not summary_match:
                    continue
                anchor_id = self._normalize_scalar_text(anchor.get("anchor_id"))
                if anchor_id and anchor_id not in anchor_ids:
                    anchor_ids.append(anchor_id)
        return anchor_ids

    def _build_default_sample_variant(
        self,
        *,
        collection_id: str,
        document_id: str,
        document_cards: pd.DataFrame,
        host_material_system: dict[str, Any],
        document_process_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if document_cards is None or document_cards.empty:
            return None
        variant_label = str(host_material_system.get("family") or document_id).strip()
        if not variant_label:
            return None
        return SampleVariant.from_mapping(
            {
                "variant_id": f"var_{uuid4().hex[:12]}",
                "document_id": str(document_id),
                "collection_id": collection_id,
                "domain_profile": CORE_NEUTRAL_DOMAIN_PROFILE,
                "variant_label": variant_label,
                "host_material_system": host_material_system,
                "composition": host_material_system.get("composition"),
                "variable_axis_type": None,
                "variable_value": None,
                "process_context": self._normalize_condition_payload(document_process_context),
                "profile_payload": {"source_kind": "document_default"},
                "structure_feature_ids": [],
                "source_anchor_ids": self._collect_document_anchor_ids(document_cards),
                "confidence": 0.62,
                "epistemic_status": EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE,
            }
        ).to_record()

    def _collect_document_anchor_ids(
        self,
        document_cards: pd.DataFrame,
    ) -> list[str]:
        anchor_ids: list[str] = []
        if document_cards is None or document_cards.empty:
            return anchor_ids
        for _, row in document_cards.iterrows():
            for anchor_id in self._extract_anchor_ids(row.get("evidence_anchors")):
                if anchor_id not in anchor_ids:
                    anchor_ids.append(anchor_id)
        return anchor_ids

    def _match_variant_id_from_text(
        self,
        *,
        document_id: str,
        text: str,
        sample_variants: pd.DataFrame,
    ) -> str | None:
        document_variants = self._filter_rows_by_document(sample_variants, document_id)
        if document_variants.empty:
            return None

        non_default = document_variants[
            document_variants["profile_payload"].apply(
                lambda payload: str((self._normalize_object(payload) or {}).get("source_kind") or "")
                != "document_default"
            )
        ]
        lowered = str(text or "").lower()
        matches: list[str] = []
        for _, row in non_default.iterrows():
            variant_id = self._normalize_scalar_text(row.get("variant_id"))
            if variant_id is None:
                continue
            label = str(row.get("variant_label") or "").strip().lower()
            if label and label in lowered:
                matches.append(variant_id)
                continue
            variable_value = row.get("variable_value")
            if isinstance(variable_value, str) and variable_value.strip().lower() in lowered:
                matches.append(variant_id)
        unique_matches = list(dict.fromkeys(matches))
        if len(unique_matches) == 1:
            return unique_matches[0]
        if len(non_default) == 1:
            return self._normalize_scalar_text(non_default.iloc[0].get("variant_id"))
        if len(non_default) == 0 and len(document_variants) == 1:
            return self._normalize_scalar_text(document_variants.iloc[0].get("variant_id"))
        return None

    def _match_variant_id_from_label(
        self,
        *,
        document_id: str,
        label: str,
        sample_variants: pd.DataFrame,
    ) -> str | None:
        lowered = str(label or "").strip().lower()
        if not lowered:
            return None
        document_variants = self._filter_rows_by_document(sample_variants, document_id)
        if document_variants.empty:
            return None
        matched = document_variants[
            document_variants["variant_label"].astype(str).str.lower() == lowered
        ]
        if len(matched) == 1:
            return self._normalize_scalar_text(matched.iloc[0].get("variant_id"))
        return None

    def _resolve_variant_id_for_card(
        self,
        *,
        card_row: pd.Series,
        sample_variants: pd.DataFrame,
    ) -> str | None:
        document_id = str(card_row.get("document_id") or "")
        source_type = str(card_row.get("evidence_source_type") or "")
        claim_text = str(card_row.get("claim_text") or "")
        if source_type != "table":
            return self._match_variant_id_from_text(
                document_id=document_id,
                text=claim_text,
                sample_variants=sample_variants,
            )

        document_variants = self._filter_rows_by_document(sample_variants, document_id)
        if document_variants.empty:
            return None

        anchors = self._normalize_evidence_anchors_payload(card_row.get("evidence_anchors"))
        table_id = None
        row_summary = None
        if anchors:
            table_id = str(anchors[0].get("figure_or_table") or "").strip() or None
            row_summary = str(anchors[0].get("quote_span") or anchors[0].get("quote") or "").strip() or None

        candidates = document_variants[
            document_variants["profile_payload"].apply(
                lambda payload: str((self._normalize_object(payload) or {}).get("table_id") or "")
                == str(table_id or "")
            )
        ] if table_id else document_variants.iloc[0:0]
        if not candidates.empty:
            for _, variant in candidates.iterrows():
                variant_id = self._normalize_scalar_text(variant.get("variant_id"))
                label = str(variant.get("variant_label") or "").strip().lower()
                profile_payload = self._normalize_object(variant.get("profile_payload")) or {}
                candidate_summary = str(profile_payload.get("row_summary") or "").strip()
                if label and label in claim_text.lower():
                    return variant_id
                if row_summary and candidate_summary and row_summary == candidate_summary:
                    return variant_id
            if len(candidates) == 1:
                return self._normalize_scalar_text(candidates.iloc[0].get("variant_id"))

        return self._match_variant_id_from_text(
            document_id=document_id,
            text=claim_text,
            sample_variants=sample_variants,
        )

    def _resolve_test_condition_id(
        self,
        *,
        card_row: pd.Series,
        property_normalized: str,
        test_conditions: pd.DataFrame,
    ) -> str | None:
        document_id = str(card_row.get("document_id") or "")
        document_conditions = self._filter_rows_by_document(test_conditions, document_id)
        if document_conditions.empty:
            return None

        property_conditions = document_conditions[
            document_conditions["property_type"].astype(str) == str(property_normalized)
        ]
        payload = self._build_condition_payload_from_card(card_row)
        if payload:
            payload_text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            exact_matches = property_conditions[
                property_conditions["condition_payload"].apply(
                    lambda value: json.dumps(
                        self._normalize_condition_payload(value),
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    == payload_text
                )
            ]
            if len(exact_matches) == 1:
                return self._normalize_scalar_text(exact_matches.iloc[0].get("test_condition_id"))
        if len(property_conditions) == 1:
            return self._normalize_scalar_text(property_conditions.iloc[0].get("test_condition_id"))
        if len(document_conditions) == 1:
            return self._normalize_scalar_text(document_conditions.iloc[0].get("test_condition_id"))
        return None

    def _build_condition_payload_from_card(
        self,
        card_row: pd.Series,
    ) -> dict[str, Any]:
        condition_context = self._normalize_condition_context_payload(
            card_row.get("condition_context")
        )
        process_context = condition_context.get("process", {})
        test_context = condition_context.get("test", {})
        payload = {
            "method": test_context.get("method"),
            "methods": self._normalize_list(test_context.get("methods")),
            "temperatures_c": list(process_context.get("temperatures_c") or []),
            "durations": list(process_context.get("durations") or []),
            "atmosphere": process_context.get("atmosphere"),
        }
        return {
            key: value
            for key, value in payload.items()
            if value not in (None, "", [], {})
        }

    def _resolve_baseline_id(
        self,
        *,
        card_row: pd.Series,
        baseline_references: pd.DataFrame,
    ) -> str | None:
        document_id = str(card_row.get("document_id") or "")
        document_baselines = self._filter_rows_by_document(baseline_references, document_id)
        if document_baselines.empty:
            return None

        condition_context = self._normalize_condition_context_payload(
            card_row.get("condition_context")
        )
        baseline_label = str(
            (condition_context.get("baseline") or {}).get("control") or ""
        ).strip()
        if baseline_label:
            matched = document_baselines[
                document_baselines["baseline_label"].astype(str).str.lower()
                == baseline_label.lower()
            ]
            if len(matched) == 1:
                return self._normalize_scalar_text(matched.iloc[0].get("baseline_id"))
        if len(document_baselines) == 1:
            return self._normalize_scalar_text(document_baselines.iloc[0].get("baseline_id"))
        return None

    def _collect_related_structure_feature_ids(
        self,
        *,
        document_id: str,
        variant_id: str | None,
        structure_features: pd.DataFrame,
        sample_variants: pd.DataFrame,
    ) -> list[str]:
        return self._collect_related_ids(
            frame=structure_features,
            document_id=document_id,
            variant_id=variant_id,
            id_column="feature_id",
            sample_variants=sample_variants,
        )

    def _collect_related_characterization_ids(
        self,
        *,
        document_id: str,
        variant_id: str | None,
        characterization: pd.DataFrame,
        sample_variants: pd.DataFrame,
    ) -> list[str]:
        return self._collect_related_ids(
            frame=characterization,
            document_id=document_id,
            variant_id=variant_id,
            id_column="observation_id",
            sample_variants=sample_variants,
        )

    def _collect_related_ids(
        self,
        *,
        frame: pd.DataFrame,
        document_id: str,
        variant_id: str | None,
        id_column: str,
        sample_variants: pd.DataFrame,
    ) -> list[str]:
        document_rows = self._filter_rows_by_document(frame, document_id)
        if document_rows.empty or id_column not in document_rows.columns:
            return []

        if variant_id:
            specific = document_rows[
                document_rows["variant_id"].astype(str) == str(variant_id)
            ]
            if not specific.empty:
                return [str(value) for value in specific[id_column].tolist() if str(value).strip()]
            if self._count_non_default_variants(document_id, sample_variants) <= 1:
                generic = document_rows[
                    document_rows["variant_id"].isna()
                    | (document_rows["variant_id"].astype(str) == "")
                    | (document_rows["variant_id"].astype(str) == "None")
                ]
                return [str(value) for value in generic[id_column].tolist() if str(value).strip()]
            return []

        if self._count_non_default_variants(document_id, sample_variants) <= 1:
            generic = document_rows[
                document_rows["variant_id"].isna()
                | (document_rows["variant_id"].astype(str) == "")
                | (document_rows["variant_id"].astype(str) == "None")
            ]
            return [str(value) for value in generic[id_column].tolist() if str(value).strip()]
        return []

    def _count_non_default_variants(
        self,
        document_id: str,
        sample_variants: pd.DataFrame,
    ) -> int:
        document_variants = self._filter_rows_by_document(sample_variants, document_id)
        if document_variants.empty:
            return 0
        count = 0
        for _, row in document_variants.iterrows():
            payload = self._normalize_object(row.get("profile_payload")) or {}
            if str(payload.get("source_kind") or "") != "document_default":
                count += 1
        return count

    def _infer_result_type(
        self,
        *,
        claim_text: str,
        property_normalized: str,
    ) -> str:
        lowered = str(claim_text or "").lower()
        if property_normalized == "retention" or "retention" in lowered:
            return "retention"
        if _RANGE_VALUE_PATTERN.search(claim_text):
            return "range"
        if any(token in lowered for token in ("optimal", "optimum", "best")):
            return "optimum"
        if any(token in lowered for token in ("fit", "fitted", "arrhenius", "tauc")):
            return "fitted_value"
        if (
            any(token in lowered for token in ("increased", "decreased", "higher", "lower"))
            and _CLAIM_VALUE_PATTERN.search(claim_text) is None
        ):
            return "trend"
        return "scalar"

    def _build_result_value_payload(
        self,
        *,
        claim_text: str,
        result_type: str,
    ) -> tuple[dict[str, Any], str | None]:
        range_match = _RANGE_VALUE_PATTERN.search(claim_text)
        if result_type == "range" and range_match is not None:
            return (
                {
                    "min": float(range_match.group(1)),
                    "max": float(range_match.group(2)),
                    "statement": claim_text,
                },
                self._resolve_claim_unit(claim_text),
            )

        value, unit = self._extract_claim_value_and_unit(claim_text)
        if result_type == "retention":
            if value is None:
                return ({}, unit)
            return (
                {
                    "retention_percent": value,
                    "statement": claim_text,
                },
                unit or "%",
            )
        if result_type == "trend":
            direction = "increase" if "increase" in claim_text.lower() or "higher" in claim_text.lower() else "decrease"
            payload: dict[str, Any] = {
                "direction": direction,
                "statement": claim_text,
            }
            if value is not None:
                payload["value"] = value
            return payload, unit
        if result_type in {"optimum", "fitted_value"}:
            payload = {"statement": claim_text}
            if value is not None:
                payload["value"] = value
            return payload, unit
        if value is None:
            return ({}, unit)
        return (
            {
                "value": value,
                "statement": claim_text,
            },
            unit,
        )

    def _extract_claim_value_and_unit(
        self,
        claim_text: str,
    ) -> tuple[float | None, str | None]:
        match = _CLAIM_VALUE_PATTERN.search(claim_text)
        if match is not None:
            return float(match.group(1)), self._normalize_unit_text(match.group(2))

        matches = list(re.finditer(r"([-+]?\d+(?:\.\d+)?)(?:\s*([A-Za-z%/0-9\-\^²·]+))?", claim_text))
        if not matches:
            return None, self._resolve_claim_unit(claim_text)
        last = matches[-1]
        return float(last.group(1)), self._normalize_unit_text(last.group(2)) or self._resolve_claim_unit(claim_text)

    def _resolve_claim_unit(self, claim_text: str) -> str | None:
        unit_match = re.search(r"\(([^)]+)\)", claim_text)
        if unit_match:
            return self._normalize_unit_text(unit_match.group(1))
        explicit = re.search(r"\b(MPa|GPa|Pa|%|S/cm|mS/cm|W/mK|wt%|vol%)\b", claim_text, re.IGNORECASE)
        if explicit:
            return self._normalize_unit_text(explicit.group(1))
        return None

    def _normalize_unit_text(self, value: Any) -> str | None:
        text = str(value or "").strip().strip(".,;:")
        return text or None

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

    def _build_cards_for_document(
        self,
        collection_id: str,
        document_id: str,
        title: str,
        text: str,
        text_unit_ids: list[str],
        profile: dict[str, Any],
        sections: list[dict[str, Any]],
        table_cells: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        material_system = self._infer_material_system(title, text)
        doc_type = str(profile.get("doc_type") or DOC_TYPE_UNCERTAIN)

        if doc_type != DOC_TYPE_REVIEW:
            for section in sections:
                section_type = str(section.get("section_type") or "")
                if section_type == "methods":
                    cards.append(
                        self._build_section_card(
                            collection_id,
                            document_id,
                            material_system,
                            section,
                            claim_type="process",
                            claim_text=self._first_sentence(section.get("text"))
                            or "The document reports a process route.",
                            confidence=0.82,
                        )
                    )
                    break
            for section in sections:
                section_type = str(section.get("section_type") or "")
                if section_type == "characterization":
                    methods = self._extract_characterization_methods(section.get("text"))
                    cards.append(
                        self._build_section_card(
                            collection_id,
                            document_id,
                            material_system,
                            section,
                            claim_type="characterization",
                            claim_text=self._build_characterization_claim(methods)
                            or self._first_sentence(section.get("text"))
                            or "The document reports characterization evidence.",
                            confidence=0.78,
                        )
                    )
                    break

            cards.extend(
                self._build_table_property_cards(
                    collection_id=collection_id,
                    document_id=document_id,
                    material_system=material_system,
                    table_cells=table_cells,
                )
            )

        candidate_sentence = self._find_claim_sentence(text)
        if candidate_sentence:
            claim_type = (
                "mechanism"
                if any(hint in candidate_sentence.lower() for hint in _MECHANISM_HINTS)
                else "property"
            )
            cards.append(
                self._build_text_claim_card(
                    collection_id=collection_id,
                    document_id=document_id,
                    material_system=material_system,
                    claim_text=candidate_sentence,
                    full_text=text,
                    text_unit_ids=text_unit_ids,
                    claim_type=claim_type,
                )
            )

        return cards

    def _build_section_card(
        self,
        collection_id: str,
        document_id: str,
        material_system: dict[str, Any],
        section: dict[str, Any],
        claim_type: str,
        claim_text: str,
        confidence: float,
    ) -> dict[str, Any]:
        section_text = str(section.get("text") or "")
        section_id = str(section.get("section_id") or "")
        snippet_ids = self._normalize_list(section.get("text_unit_ids"))
        evidence_anchors = [
            {
                "anchor_id": f"anchor_{uuid4().hex[:12]}",
                "source_type": "method",
                "section_id": section_id or None,
                "block_id": None,
                "snippet_id": snippet_ids[0] if snippet_ids else None,
                "figure_or_table": None,
                "quote_span": self._first_sentence(section_text) or section_text[:240] or None,
            }
        ]
        return {
            "evidence_id": f"ev_{uuid4().hex[:12]}",
            "document_id": document_id,
            "collection_id": collection_id,
            "claim_text": claim_text,
            "claim_type": claim_type,
            "evidence_source_type": "method",
            "evidence_anchors": evidence_anchors,
            "material_system": self._normalize_material_system_payload(material_system),
            "condition_context": self._normalize_condition_context_payload({
                "process": self._extract_process_context(section_text),
                "baseline": {},
                "test": self._extract_test_context(section_text),
            }),
            "confidence": round(confidence, 2),
            "traceability_status": TRACEABILITY_STATUS_DIRECT,
        }

    def _build_text_claim_card(
        self,
        collection_id: str,
        document_id: str,
        material_system: dict[str, Any],
        claim_text: str,
        full_text: str,
        text_unit_ids: list[str],
        claim_type: str,
    ) -> dict[str, Any]:
        baseline = self._extract_baseline_context(claim_text)
        test_context = self._extract_test_context(full_text)
        evidence_anchors = [
            {
                "anchor_id": f"anchor_{uuid4().hex[:12]}",
                "source_type": "text",
                "section_id": None,
                "block_id": None,
                "snippet_id": text_unit_ids[0] if text_unit_ids else None,
                "figure_or_table": None,
                "quote_span": claim_text,
            }
        ]
        traceability_status = (
            TRACEABILITY_STATUS_DIRECT if text_unit_ids else TRACEABILITY_STATUS_PARTIAL
        )
        return {
            "evidence_id": f"ev_{uuid4().hex[:12]}",
            "document_id": document_id,
            "collection_id": collection_id,
            "claim_text": claim_text,
            "claim_type": claim_type,
            "evidence_source_type": "text",
            "evidence_anchors": evidence_anchors,
            "material_system": self._normalize_material_system_payload(material_system),
            "condition_context": self._normalize_condition_context_payload({
                "process": self._extract_process_context(full_text),
                "baseline": baseline,
                "test": test_context,
            }),
            "confidence": (
                0.74 if traceability_status == TRACEABILITY_STATUS_DIRECT else 0.66
            ),
            "traceability_status": traceability_status,
        }

    def _build_table_property_cards(
        self,
        *,
        collection_id: str,
        document_id: str,
        material_system: dict[str, Any],
        table_cells: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not table_cells:
            return []

        grouped_rows: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for cell in table_cells:
            table_id = str(cell.get("table_id") or "").strip()
            row_index = self._safe_int(cell.get("row_index"))
            if not table_id or row_index is None or row_index <= 0:
                continue
            grouped_rows.setdefault((table_id, row_index), []).append(cell)

        cards: list[dict[str, Any]] = []
        for (table_id, _row_index), row_cells in grouped_rows.items():
            ordered_cells = sorted(
                (cell for cell in row_cells if isinstance(cell, dict)),
                key=lambda item: self._safe_int(item.get("col_index")) or 0,
            )
            sample_label = self._resolve_table_sample_label(ordered_cells)
            baseline = self._resolve_table_baseline(ordered_cells)
            row_summary = self._build_table_row_summary(ordered_cells)

            for cell in ordered_cells:
                header = str(cell.get("header_path") or "").strip()
                if not header:
                    continue
                if self._is_table_sample_header(header) or self._is_table_baseline_header(header):
                    continue
                if self._infer_property_type_from_header(header) == "qualitative":
                    continue

                cell_text = str(cell.get("cell_text") or "").strip()
                numeric_value = self._extract_table_numeric_value(cell_text)
                if numeric_value is None:
                    continue

                unit = self._resolve_table_unit(cell)
                claim_text = self._build_table_property_claim(
                    sample_label=sample_label,
                    header=header,
                    numeric_value=numeric_value,
                    unit=unit,
                )
                cards.append(
                    {
                        "evidence_id": f"ev_{uuid4().hex[:12]}",
                        "document_id": document_id,
                        "collection_id": collection_id,
                        "claim_text": claim_text,
                        "claim_type": "property",
                        "evidence_source_type": "table",
                        "evidence_anchors": [
                            {
                                "anchor_id": f"anchor_{uuid4().hex[:12]}",
                                "source_type": "table",
                                "section_id": None,
                                "block_id": None,
                                "snippet_id": None,
                                "figure_or_table": table_id,
                                "quote_span": row_summary or claim_text,
                            }
                        ],
                        "material_system": self._normalize_material_system_payload(material_system),
                        "condition_context": self._normalize_condition_context_payload(
                            {
                                "process": {},
                                "baseline": baseline,
                                "test": {},
                            }
                        ),
                        "confidence": 0.8 if unit else 0.74,
                        "traceability_status": TRACEABILITY_STATUS_DIRECT,
                    }
                )

        return cards

    def _infer_material_system(self, title: str, text: str) -> dict[str, Any]:
        source = f"{title} {text}".lower()
        family = None
        composition = None
        if "carbon fiber" in source:
            family = "carbon fiber composite"
        elif "epoxy" in source and "sio2" in source:
            family = "epoxy/SiO2 composite"
            composition = "epoxy + SiO2"
        elif "epoxy" in source and "composite" in source:
            family = "epoxy composite"
        elif "composite" in source:
            family = "composite"
        elif title.strip():
            family = title.strip()
        else:
            family = "unspecified material system"
        if composition is None and title.strip() and title.strip() != family:
            composition = title.strip()
        return {"family": family, "composition": composition}

    def _resolve_table_sample_label(
        self,
        row_cells: list[dict[str, Any]],
    ) -> str | None:
        for cell in row_cells:
            header = str(cell.get("header_path") or "").strip()
            if self._is_table_sample_header(header):
                text = str(cell.get("cell_text") or "").strip()
                if text:
                    return text
        for cell in row_cells:
            header = str(cell.get("header_path") or "").strip()
            text = str(cell.get("cell_text") or "").strip()
            if not text or self._extract_table_numeric_value(text) is not None:
                continue
            if self._is_table_baseline_header(header):
                continue
            return text
        return None

    def _resolve_table_baseline(
        self,
        row_cells: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for cell in row_cells:
            header = str(cell.get("header_path") or "").strip()
            if not self._is_table_baseline_header(header):
                continue
            text = str(cell.get("cell_text") or "").strip()
            if text:
                return {"control": text}
        return {}

    def _build_table_row_summary(
        self,
        row_cells: list[dict[str, Any]],
    ) -> str:
        parts: list[str] = []
        for cell in row_cells:
            header = str(cell.get("header_path") or "").strip()
            text = str(cell.get("cell_text") or "").strip()
            if not text:
                continue
            if header:
                parts.append(f"{header}: {text}")
            else:
                parts.append(text)
        return "; ".join(parts)

    def _is_table_sample_header(self, header: str) -> bool:
        lowered = str(header or "").strip().lower()
        return any(hint in lowered for hint in _TABLE_SAMPLE_HEADER_HINTS)

    def _is_table_baseline_header(self, header: str) -> bool:
        lowered = str(header or "").strip().lower()
        return any(hint in lowered for hint in _TABLE_BASELINE_HEADER_HINTS)

    def _extract_table_numeric_value(self, cell_text: str) -> str | None:
        match = _TABLE_NUMERIC_PATTERN.search(str(cell_text or ""))
        if match is None:
            return None
        return match.group(0)

    def _resolve_table_unit(self, cell: dict[str, Any]) -> str | None:
        for candidate in (cell.get("unit_hint"), cell.get("header_path")):
            text = str(candidate or "").strip()
            if not text:
                continue
            unit_match = re.search(r"\(([^)]+)\)", text)
            if unit_match:
                return unit_match.group(1).strip() or None
            if text.lower() in {"mpa", "gpa", "pa", "%", "s/cm", "ms/cm", "w/mk", "wt%", "vol%"}:
                return text
        return None

    def _build_table_property_claim(
        self,
        *,
        sample_label: str | None,
        header: str,
        numeric_value: str,
        unit: str | None,
    ) -> str:
        subject = sample_label or "Sample"
        property_label = header
        if unit:
            return f"{subject} reported {property_label} of {numeric_value} {unit}."
        return f"{subject} reported {property_label} of {numeric_value}."

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

    def _infer_property_type_from_card(
        self,
        *,
        claim_type: str,
        claim_text: str,
    ) -> str:
        lowered = str(claim_text or "").lower()
        for token, normalized in _PROPERTY_HINTS:
            if token in lowered:
                return normalized
        if claim_type == "characterization":
            return "characterization"
        if claim_type == "process":
            return "process_route"
        return claim_type or "qualitative"

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

    def _infer_condition_scope_level(
        self,
        evidence_source_type: str,
    ) -> str:
        source_type = str(evidence_source_type or "").strip()
        if source_type == "table":
            return "table"
        if source_type == "method":
            return "experiment"
        return "measurement"

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

    def _infer_baseline_scope(
        self,
        evidence_source_type: str,
    ) -> str:
        source_type = str(evidence_source_type or "").strip()
        if source_type == "table":
            return "table"
        return "measurement"

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

    def _baseline_label_is_explicit(
        self,
        baseline_label: str,
    ) -> bool:
        lowered = str(baseline_label or "").lower()
        return any(
            token in lowered
            for token in (
                "baseline",
                "control",
                "reference",
                "benchmark",
                "literature",
                "without",
            )
        )

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

    def _extract_process_context(self, text: Any) -> dict[str, Any]:
        source = str(text or "")
        temperatures = [float(match.group(1)) for match in _TEMP_PATTERN.finditer(source)]
        durations = [match.group(0) for match in _TIME_PATTERN.finditer(source)]
        atmosphere = None
        match = _ATMOSPHERE_PATTERN.search(source)
        if match:
            atmosphere = match.group(1)
        context: dict[str, Any] = {}
        if temperatures:
            context["temperatures_c"] = temperatures
        if durations:
            context["durations"] = durations
        if atmosphere:
            context["atmosphere"] = atmosphere
        return context

    def _extract_test_context(self, text: Any) -> dict[str, Any]:
        source = str(text or "")
        methods = self._extract_characterization_methods(source)
        context: dict[str, Any] = {}
        if methods:
            context["methods"] = methods
            if len(methods) == 1:
                context["method"] = methods[0]
        return context

    def _extract_baseline_context(self, sentence: str) -> dict[str, Any]:
        lowered = sentence.lower()
        baseline: dict[str, Any] = {}
        if "relative to" in lowered:
            baseline["control"] = sentence.split("relative to", 1)[1].strip(" .")
        elif "than the" in lowered:
            baseline["control"] = sentence.split("than the", 1)[1].strip(" .")
        elif "than" in lowered:
            baseline["control"] = sentence.split("than", 1)[1].strip(" .")
        return baseline

    def _extract_characterization_methods(self, text: Any) -> list[str]:
        source = str(text or "")
        return [method for method in _CHARACTERIZATION_METHODS if method.lower() in source.lower()]

    def _build_characterization_claim(self, methods: list[str]) -> str | None:
        if not methods:
            return None
        joined = ", ".join(methods)
        return f"The document reports characterization using {joined}."

    def _find_claim_sentence(self, text: str) -> str | None:
        sentences = self._split_sentences(text)
        for sentence in sentences:
            lowered = sentence.lower()
            if any(hint in lowered for hint in _PROPERTY_SENTENCE_HINTS):
                return sentence
        return None

    def _split_sentences(self, text: str) -> list[str]:
        chunks = re.split(r"(?<=[\.\!\?])\s+|\n+", str(text or ""))
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def _first_sentence(self, text: Any) -> str | None:
        sentences = self._split_sentences(str(text or ""))
        return sentences[0] if sentences else None

    def _group_sections_by_document(
        self,
        sections: pd.DataFrame,
    ) -> dict[str, list[dict[str, Any]]]:
        if sections is None or sections.empty:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for _, row in sections.iterrows():
            document_id = str(
                row.get("paper_id")
                or row.get("document_id")
                or row.get("id")
                or ""
            )
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
        locator_type = str(anchor.get("locator_type") or "section")
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
                    locator_type = "char_range"
                    locator_confidence = "high"

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
                    locator_type = "char_range"
                    locator_confidence = "medium"

        if resolved_char_range is not None:
            return {
                **anchor,
                "section_id": section_id,
                "char_range": resolved_char_range,
                "bbox": None,
                "locator_type": "char_range",
                "locator_confidence": locator_confidence,
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
                "family": text or "unspecified material system",
                "composition": None,
            }
        family = str(payload.get("family") or "").strip() or "unspecified material system"
        composition = str(payload.get("composition") or "").strip() or None
        return {
            "family": family,
            "composition": composition,
        }

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

    def _normalize_object(self, value: Any) -> Any:
        return normalize_backbone_value(value)

    def _normalize_list(self, value: Any) -> list[str]:
        normalized = self._normalize_object(value)
        if normalized is None:
            return []
        if isinstance(normalized, list):
            return [str(item) for item in normalized if str(item).strip()]
        return [str(normalized)]
