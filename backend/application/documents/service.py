from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from application.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)
from application.collections.service import CollectionService
from application.protocol.section_service import build_sections
from application.protocol.source_service import build_document_records, load_protocol_inputs
from application.workspace.artifact_registry_service import ArtifactRegistryService


_DOCUMENT_PROFILES_FILE = "document_profiles.parquet"
_DOCUMENT_PROFILE_JSON_COLUMNS = (
    "protocol_extractability_signals",
    "parsing_warnings",
)

_REVIEW_TITLE_PATTERNS = (
    re.compile(r"\breview\b", re.IGNORECASE),
    re.compile(r"\boverview\b", re.IGNORECASE),
    re.compile(r"\bperspective\b", re.IGNORECASE),
    re.compile(r"\bprogress\b", re.IGNORECASE),
    re.compile(r"\brecent advances?\b", re.IGNORECASE),
    re.compile(r"\bsurvey\b", re.IGNORECASE),
    re.compile(r"\bmini[- ]?review\b", re.IGNORECASE),
    re.compile(r"(综述|进展|评述)"),
)

_REVIEW_TEXT_HINTS = (
    "this review",
    "we review",
    "recent advances",
    "state of the art",
    "in this perspective",
    "this overview",
    "综述",
    "进展",
    "评述",
)

_PROCEDURAL_HINTS = (
    "stir",
    "mix",
    "dissolve",
    "synthes",
    "fabricat",
    "prepare",
    "hydrothermal",
    "solvothermal",
    "calcine",
    "anneal",
    "wash",
    "dry",
    "heat",
    "cure",
    "cast",
    "filter",
    "centrifug",
    "加入",
    "搅拌",
    "溶解",
    "制备",
    "退火",
    "烧结",
    "洗涤",
    "干燥",
    "加热",
)

_CONDITION_PATTERNS = (
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:c|°c|k|f)\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs)\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:rpm|wt%|vol%|mol%|m|mm|um|μm|nm)\b", re.IGNORECASE),
    re.compile(r"\b(?:under|in)\s+(?:air|argon|ar|nitrogen|n2|vacuum)\b", re.IGNORECASE),
)

_TITLE_FIELD_CANDIDATES = (
    "parsed_title",
    "document_title",
    "paper_title",
    "title",
)

_SOURCE_FILENAME_FIELD_CANDIDATES = (
    "source_filename",
    "original_filename",
)

_SOURCE_PATH_FIELD_CANDIDATES = (
    "source_path",
    "source_file",
    "file_path",
    "filepath",
    "path",
    "filename",
    "file_name",
    "name",
)


class DocumentProfilesNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve document profile outputs."""

    def __init__(self, collection_id: str, output_dir: Path) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"document profiles not ready: {collection_id}")


class DocumentProfileService:
    """Generate and serve collection-scoped document profile artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )

    def list_document_profiles(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        profiles = self.read_document_profiles(collection_id)
        summary = self.summarize_document_profiles(profiles)
        items = [
            self._serialize_profile_row(row)
            for _, row in profiles.iloc[offset : offset + limit].iterrows()
        ]
        return {
            "collection_id": collection_id,
            "total": len(profiles),
            "count": len(items),
            "summary": summary,
            "items": items,
        }

    def get_document_summary(self, collection_id: str) -> dict[str, Any]:
        profiles = self.read_document_profiles(collection_id)
        return self.summarize_document_profiles(profiles)

    def read_document_profiles(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        path = output_dir / _DOCUMENT_PROFILES_FILE
        if path.is_file():
            profiles = restore_frame_from_storage(
                pd.read_parquet(path),
                _DOCUMENT_PROFILE_JSON_COLUMNS,
            )
            if self._profile_rebuild_required(profiles) and (output_dir / "documents.parquet").is_file():
                profiles = self.build_document_profiles(collection_id, output_dir)
        else:
            profiles = self.build_document_profiles(collection_id, output_dir)
        return self._normalize_profiles_table(profiles, collection_id)

    def build_document_profiles(
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
            raise DocumentProfilesNotReadyError(collection_id, base_dir)

        documents, text_units = load_protocol_inputs(base_dir)
        document_records = build_document_records(documents, text_units)
        sections = build_sections(documents, text_units)
        sections_by_doc = self._group_sections_by_document(sections)
        file_lookup = self._build_collection_file_lookup(collection_id)

        rows = [
            self._profile_document_row(
                collection_id=collection_id,
                row=row,
                sections=sections_by_doc.get(str(row.get("paper_id")), []),
                file_lookup=file_lookup,
            )
            for _, row in document_records.iterrows()
        ]
        profiles = pd.DataFrame(
            rows,
            columns=[
                "document_id",
                "collection_id",
                "title",
                "source_filename",
                "doc_type",
                "protocol_extractable",
                "protocol_extractability_signals",
                "parsing_warnings",
                "confidence",
            ],
        )
        profiles = self._normalize_profiles_table(profiles, collection_id)
        base_dir.mkdir(parents=True, exist_ok=True)
        prepare_frame_for_storage(
            profiles,
            _DOCUMENT_PROFILE_JSON_COLUMNS,
        ).to_parquet(base_dir / _DOCUMENT_PROFILES_FILE, index=False)
        self.artifact_registry_service.upsert(collection_id, base_dir)
        return profiles

    def count_protocol_suitable(self, profiles: pd.DataFrame) -> int:
        normalized = self._normalize_profiles_table(profiles, None)
        return int(
            normalized["protocol_extractable"].isin(["yes", "partial"]).sum()
        )

    def _resolve_output_dir(self, collection_id: str) -> Path:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            artifacts = None
        if artifacts:
            output_path = artifacts.get("output_path")
            if output_path:
                return Path(str(output_path)).expanduser().resolve()
        return self.collection_service.get_paths(collection_id).output_dir.resolve()

    def _profile_document_row(
        self,
        collection_id: str,
        row: pd.Series,
        sections: list[dict[str, Any]],
        file_lookup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        document_id = str(row.get("paper_id") or row.get("document_id") or "")
        source_filename = self._resolve_source_filename(
            row=row,
            document_id=document_id,
            file_lookup=file_lookup or {},
        )
        title = self._resolve_document_title(
            row=row,
            document_id=document_id,
            source_filename=source_filename,
            file_lookup=file_lookup or {},
        )
        analysis_title = str(row.get("title") or document_id)
        text = str(row.get("text") or "")
        lowered_title = analysis_title.lower()
        lowered_text = text.lower()

        method_sections = [
            section for section in sections if section.get("section_type") == "methods"
        ]
        characterization_sections = [
            section
            for section in sections
            if section.get("section_type") == "characterization"
        ]
        method_text = "\n".join(str(section.get("text") or "") for section in method_sections)

        review_title_hits = sum(
            1 for pattern in _REVIEW_TITLE_PATTERNS if pattern.search(analysis_title)
        )
        review_text_hits = sum(1 for hint in _REVIEW_TEXT_HINTS if hint in lowered_text)
        procedural_hits = self._count_keyword_hits(
            method_text or lowered_text,
            _PROCEDURAL_HINTS,
        )
        condition_hits = self._count_pattern_hits(method_text or text, _CONDITION_PATTERNS)

        experimental_score = 0
        review_score = 0
        signals: list[str] = []
        warnings: list[str] = []

        if method_sections:
            experimental_score += 2
            signals.append("methods_section_detected")
        else:
            warnings.append("missing_methods_section")
        if characterization_sections:
            experimental_score += 1
            signals.append("characterization_section_detected")
        if procedural_hits >= 2:
            experimental_score += 2
            signals.append("procedural_actions_detected")
        elif procedural_hits == 1:
            experimental_score += 1
            signals.append("limited_procedural_actions_detected")
        if condition_hits >= 2:
            experimental_score += 1
            signals.append("condition_markers_detected")
        elif condition_hits == 1:
            signals.append("limited_condition_markers_detected")
        else:
            warnings.append("critical_parameters_incomplete")

        if review_title_hits:
            review_score += 2
            signals.append("review_title_detected")
        if review_text_hits:
            review_score += 1
            signals.append("review_language_detected")

        if review_score >= 2 and experimental_score >= 2:
            doc_type = "mixed"
            warnings.append("review_contamination_detected")
        elif review_score >= 2:
            doc_type = "review"
        elif experimental_score >= 3:
            doc_type = "experimental"
        else:
            doc_type = "uncertain"
            warnings.append("document_type_uncertain")

        if not text.strip():
            warnings.append("missing_document_text")
        elif len(text.strip()) < 120:
            warnings.append("limited_document_text")

        if doc_type == "review":
            protocol_extractable = "no"
        elif doc_type == "experimental":
            if method_sections and procedural_hits >= 2 and condition_hits >= 2:
                protocol_extractable = "yes"
            elif method_sections or procedural_hits > 0:
                protocol_extractable = "partial"
            else:
                protocol_extractable = "uncertain"
        elif doc_type == "mixed":
            protocol_extractable = "partial" if (method_sections or procedural_hits > 0) else "no"
        else:
            if method_sections or procedural_hits > 0:
                protocol_extractable = "partial"
            elif review_score > 0:
                protocol_extractable = "no"
            else:
                protocol_extractable = "uncertain"

        if protocol_extractable in {"partial", "uncertain"} and condition_hits == 0:
            warnings.append("condition_context_weak")

        confidence = self._compute_confidence(
            doc_type=doc_type,
            protocol_extractable=protocol_extractable,
            signal_count=len(set(signals)),
            warning_count=len(set(warnings)),
            review_score=review_score,
            experimental_score=experimental_score,
        )

        return {
            "document_id": document_id,
            "collection_id": collection_id,
            "title": title,
            "source_filename": source_filename,
            "doc_type": doc_type,
            "protocol_extractable": protocol_extractable,
            "protocol_extractability_signals": sorted(set(signals)),
            "parsing_warnings": sorted(set(warnings)),
            "confidence": confidence,
        }

    def summarize_document_profiles(self, profiles: pd.DataFrame) -> dict[str, Any]:
        normalized = self._normalize_profiles_table(profiles, None)
        total_documents = len(normalized)
        by_doc_type = dict(
            sorted(Counter(str(value) for value in normalized["doc_type"]).items())
        )
        by_protocol_extractable = dict(
            sorted(
                Counter(
                    str(value) for value in normalized["protocol_extractable"]
                ).items()
            )
        )

        warnings: list[str] = []
        review_heavy_count = by_doc_type.get("review", 0) + by_doc_type.get("mixed", 0)
        if total_documents and review_heavy_count / total_documents >= 0.5:
            warnings.append(
                "Collection is review-heavy or mixed; protocol outputs should be treated cautiously."
            )
        if total_documents and (
            by_protocol_extractable.get("yes", 0) + by_protocol_extractable.get("partial", 0)
        ) == 0:
            warnings.append("No protocol-suitable documents were detected in this collection.")
        if by_doc_type.get("uncertain", 0) > 0:
            warnings.append("Some documents remain uncertain and may need manual review.")

        return {
            "total_documents": total_documents,
            "by_doc_type": by_doc_type,
            "by_protocol_extractable": by_protocol_extractable,
            "warnings": warnings,
        }

    def _normalize_profiles_table(
        self,
        profiles: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if profiles is None or profiles.empty:
            return pd.DataFrame(
                columns=[
                    "document_id",
                    "collection_id",
                    "title",
                    "source_filename",
                    "doc_type",
                    "protocol_extractable",
                    "protocol_extractability_signals",
                    "parsing_warnings",
                    "confidence",
                ]
            )

        normalized = profiles.copy()
        for column in ("title", "source_filename"):
            if column not in normalized.columns:
                normalized[column] = None
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        for column in ("title", "source_filename"):
            normalized[column] = normalized[column].apply(self._normalize_optional_text)
        if "protocol_extractability_signals" in normalized.columns:
            normalized["protocol_extractability_signals"] = normalized[
                "protocol_extractability_signals"
            ].apply(self._normalize_string_list)
        if "parsing_warnings" in normalized.columns:
            normalized["parsing_warnings"] = normalized["parsing_warnings"].apply(
                self._normalize_string_list
            )
        if "confidence" in normalized.columns:
            normalized["confidence"] = normalized["confidence"].apply(
                lambda value: round(float(value or 0.0), 2)
            )
        return normalized[
            [
                "document_id",
                "collection_id",
                "title",
                "source_filename",
                "doc_type",
                "protocol_extractable",
                "protocol_extractability_signals",
                "parsing_warnings",
                "confidence",
            ]
        ]

    def _serialize_profile_row(self, row: pd.Series) -> dict[str, Any]:
        return {
            "document_id": str(row.get("document_id") or ""),
            "collection_id": str(row.get("collection_id") or ""),
            "title": self._normalize_optional_text(row.get("title")),
            "source_filename": self._normalize_optional_text(row.get("source_filename")),
            "doc_type": str(row.get("doc_type") or "uncertain"),
            "protocol_extractable": str(row.get("protocol_extractable") or "uncertain"),
            "protocol_extractability_signals": self._normalize_string_list(
                row.get("protocol_extractability_signals")
            ),
            "parsing_warnings": self._normalize_string_list(row.get("parsing_warnings")),
            "confidence": round(float(row.get("confidence") or 0.0), 2),
        }

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

    def _count_keyword_hits(self, text: str, keywords: tuple[str, ...]) -> int:
        lowered = str(text or "").lower()
        return sum(1 for keyword in keywords if keyword in lowered)

    def _count_pattern_hits(self, text: str, patterns: tuple[re.Pattern[str], ...]) -> int:
        source = str(text or "")
        return sum(1 for pattern in patterns if pattern.search(source))

    def _compute_confidence(
        self,
        doc_type: str,
        protocol_extractable: str,
        signal_count: int,
        warning_count: int,
        review_score: int,
        experimental_score: int,
    ) -> float:
        base = {
            "experimental": 0.82,
            "mixed": 0.72,
            "review": 0.84,
            "uncertain": 0.56,
        }[doc_type]
        if protocol_extractable == "yes":
            base += 0.06
        elif protocol_extractable == "partial":
            base += 0.01
        elif protocol_extractable == "uncertain":
            base -= 0.04

        strength = min(signal_count, 4) * 0.02
        noise = min(warning_count, 3) * 0.03
        if review_score >= 2 and experimental_score >= 2:
            noise += 0.03
        return round(max(0.5, min(0.98, base + strength - noise)), 2)

    def _normalize_string_list(self, value: Any) -> list[str]:
        normalized = normalize_backbone_value(value)
        if normalized is None:
            return []
        if isinstance(normalized, list):
            return [str(item) for item in normalized if str(item).strip()]
        return [str(normalized)]

    def _normalize_optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def _profile_rebuild_required(self, profiles: pd.DataFrame) -> bool:
        return not {"title", "source_filename"}.issubset(set(profiles.columns))

    def _build_collection_file_lookup(self, collection_id: str) -> dict[str, Any]:
        try:
            files = self.collection_service.list_files(collection_id)
        except FileNotFoundError:
            files = []

        stored_to_source: dict[str, str] = {}
        resolved_sources: list[str] = []
        for record in files:
            original = self._normalize_optional_text(record.get("original_filename"))
            stored = self._normalize_optional_text(record.get("stored_filename"))
            if original:
                resolved_sources.append(original)
            if original and stored:
                stored_to_source[stored] = original

        single_source_filename = (
            resolved_sources[0]
            if len(resolved_sources) == 1
            else None
        )

        return {
            "stored_to_source": stored_to_source,
            "source_filenames": set(resolved_sources),
            "single_source_filename": single_source_filename,
        }

    def _resolve_document_title(
        self,
        row: pd.Series,
        document_id: str,
        source_filename: str | None,
        file_lookup: dict[str, Any],
    ) -> str | None:
        for candidate in self._iter_document_title_candidates(row):
            if candidate == document_id:
                continue
            if source_filename and candidate == source_filename:
                continue
            if candidate in file_lookup.get("stored_to_source", {}):
                continue
            if candidate in file_lookup.get("source_filenames", set()):
                continue
            return candidate
        return None

    def _resolve_source_filename(
        self,
        row: pd.Series,
        document_id: str,
        file_lookup: dict[str, Any],
    ) -> str | None:
        stored_to_source = file_lookup.get("stored_to_source", {})

        for key in _SOURCE_FILENAME_FIELD_CANDIDATES:
            candidate = self._extract_row_or_metadata_value(row, key)
            normalized = self._normalize_filename_value(candidate)
            if normalized and normalized != document_id:
                return stored_to_source.get(normalized, normalized)

        for key in _SOURCE_PATH_FIELD_CANDIDATES:
            candidate = self._extract_row_or_metadata_value(row, key)
            normalized = self._normalize_filename_value(candidate)
            if normalized and normalized != document_id:
                return stored_to_source.get(normalized, normalized)

        title_value = self._normalize_optional_text(row.get("title"))
        if title_value and title_value in stored_to_source:
            return stored_to_source[title_value]

        return file_lookup.get("single_source_filename")

    def _iter_document_title_candidates(self, row: pd.Series) -> list[str]:
        seen: set[str] = set()
        values: list[str] = []
        for key in _TITLE_FIELD_CANDIDATES:
            candidate = self._extract_row_or_metadata_value(row, key)
            normalized = self._normalize_optional_text(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                values.append(normalized)
        return values

    def _extract_row_or_metadata_value(self, row: pd.Series, key: str) -> Any:
        if key in row.index:
            value = row.get(key)
            normalized = self._normalize_optional_text(value)
            if normalized is not None:
                return normalized

        metadata = self._coerce_mapping(row.get("metadata"))
        value = metadata.get(key)
        normalized = self._normalize_optional_text(value)
        if normalized is not None:
            return normalized
        return None

    def _coerce_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        if isinstance(value, float) and pd.isna(value):
            return {}
        if not isinstance(value, str):
            return {}

        text = value.strip()
        if not text:
            return {}

        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(text)
            except (TypeError, ValueError, SyntaxError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _normalize_filename_value(self, value: Any) -> str | None:
        normalized = self._normalize_optional_text(value)
        if normalized is None:
            return None
        return Path(normalized).name or None
