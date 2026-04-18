from __future__ import annotations

import json
import re
from urllib.parse import urlencode
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from infra.persistence.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)
from application.collections.service import CollectionService
from application.documents.input_service import (
    build_document_records,
    load_collection_inputs,
    load_sections_artifact,
    load_table_cells_artifact,
)
from application.documents.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.workspace.artifact_registry_service import ArtifactRegistryService


_EVIDENCE_CARDS_FILE = "evidence_cards.parquet"
_EVIDENCE_JSON_COLUMNS = (
    "evidence_anchors",
    "material_system",
    "condition_context",
)

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

_PROPERTY_HINTS = {
    "strength": "strength",
    "flexural": "flexural_strength",
    "modulus": "modulus",
    "hardness": "hardness",
    "conductivity": "conductivity",
    "fatigue": "fatigue_life",
    "stability": "stability",
    "porosity": "porosity",
    "density": "density",
}

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
        self.artifact_registry_service.upsert(collection_id, base_dir)

        return cards_table

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
        doc_type = str(profile.get("doc_type") or "uncertain")

        if doc_type != "review":
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
            "traceability_status": "direct",
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
        traceability_status = "direct" if text_unit_ids else "partial"
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
            "confidence": 0.74 if traceability_status == "direct" else 0.66,
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
                        "traceability_status": "direct",
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
            "traceability_status": str(row.get("traceability_status") or "missing"),
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
                    "figure_or_table": self._normalize_scalar_text(anchor.get("figure_or_table")),
                    "quote_span": quote,
                }
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
