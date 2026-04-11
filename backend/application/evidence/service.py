from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from application.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)
from application.collections.service import CollectionService
from application.documents.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.protocol.section_service import build_sections
from application.protocol.source_service import build_document_records, load_protocol_inputs
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


class EvidenceCardsNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve evidence cards."""

    def __init__(self, collection_id: str, output_dir: Path) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"evidence cards not ready: {collection_id}")


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

        documents, text_units = load_protocol_inputs(base_dir)
        document_records = build_document_records(documents, text_units)
        sections = build_sections(documents, text_units)
        sections_by_doc = self._group_sections_by_document(sections)

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

        if not cards_table.empty:
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
            grouped.setdefault(str(row.get("paper_id") or ""), []).append(dict(row))
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
        return {
            "evidence_id": str(row.get("evidence_id") or ""),
            "document_id": str(row.get("document_id") or ""),
            "collection_id": str(row.get("collection_id") or ""),
            "claim_text": str(row.get("claim_text") or ""),
            "claim_type": str(row.get("claim_type") or "qualitative"),
            "evidence_source_type": str(row.get("evidence_source_type") or "text"),
            "evidence_anchors": self._normalize_object(row.get("evidence_anchors")) or [],
            "material_system": self._normalize_material_system_payload(row.get("material_system")),
            "condition_context": self._normalize_condition_context_payload(row.get("condition_context")),
            "confidence": round(float(row.get("confidence") or 0.0), 2),
            "traceability_status": str(row.get("traceability_status") or "missing"),
        }

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
