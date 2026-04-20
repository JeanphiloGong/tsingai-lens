from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from domain.core.document_profile import (
    DocumentProfile,
    summarize_document_profile_collection,
)
from domain.shared.enums import (
    DOC_TYPE_UNCERTAIN,
    PROTOCOL_EXTRACTABLE_UNCERTAIN,
    PROTOCOL_SUITABLE_EXTRACTABILITY,
)
from infra.persistence.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)
from application.source.collection_service import CollectionService
from application.core.core_semantic_version import (
    core_semantic_rebuild_required,
    purge_stale_core_semantic_artifacts,
    write_core_semantic_manifest,
)
from application.core.llm_structured_extractor import (
    CoreLLMStructuredExtractor,
    build_default_core_llm_structured_extractor,
)
from application.source.artifact_input_service import (
    build_document_records,
    load_collection_inputs,
    load_sections_artifact,
)
from application.source.artifact_registry_service import ArtifactRegistryService

logger = logging.getLogger(__name__)


_DOCUMENT_PROFILES_FILE = "document_profiles.parquet"
_DOCUMENT_PROFILE_JSON_COLUMNS = (
    "protocol_extractability_signals",
    "parsing_warnings",
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


class DocumentContentNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve document content."""

    def __init__(self, collection_id: str, output_dir: Path) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"document content not ready: {collection_id}")


class DocumentNotFoundError(FileNotFoundError):
    """Raised when one document cannot be resolved inside a collection."""

    def __init__(self, collection_id: str, document_id: str) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        super().__init__(f"document not found: {collection_id}/{document_id}")


class DocumentProfileService:
    """Generate and serve collection-scoped document profile artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        structured_extractor: CoreLLMStructuredExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self._structured_extractor = structured_extractor

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

    def get_document_profile(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        profiles = self.read_document_profiles(collection_id)
        matched = profiles[profiles["document_id"].astype(str) == str(document_id)]
        if matched.empty:
            raise DocumentNotFoundError(collection_id, document_id)
        return self._serialize_profile_row(matched.iloc[0])

    def get_document_content(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        output_dir = self._resolve_output_dir(collection_id)
        documents_path = output_dir / "documents.parquet"
        if not documents_path.is_file():
            raise DocumentContentNotReadyError(collection_id, output_dir)

        documents, text_units = load_collection_inputs(output_dir)
        try:
            sections = load_sections_artifact(output_dir)
        except FileNotFoundError as exc:
            raise DocumentContentNotReadyError(collection_id, output_dir) from exc
        document_records = build_document_records(documents, text_units)
        matched = document_records[
            document_records["paper_id"].astype(str) == str(document_id)
        ]
        if matched.empty:
            raise DocumentNotFoundError(collection_id, document_id)

        row = matched.iloc[0]
        sections_by_doc = self._group_sections_by_document(sections)
        profile = self._find_profile_row(collection_id, document_id)
        file_lookup = self._build_collection_file_lookup(collection_id)

        full_text = str(row.get("text") or "").strip()
        section_payload = self._build_document_content_sections(
            full_text=full_text,
            sections=sections_by_doc.get(str(document_id), []),
        )
        if not full_text and section_payload:
            full_text = "\n\n".join(
                section["text"] for section in section_payload if str(section.get("text") or "").strip()
            ).strip()

        title = self._normalize_optional_text(profile.get("title")) if profile else None
        if title is None:
            source_filename = self._resolve_source_filename(row, document_id, file_lookup)
            title = self._resolve_document_title(row, document_id, source_filename, file_lookup)
        else:
            source_filename = self._normalize_optional_text(profile.get("source_filename"))
        if source_filename is None:
            source_filename = self._resolve_source_filename(row, document_id, file_lookup)

        warnings: list[str] = []
        if not full_text:
            warnings.append("missing_document_text")
        if not section_payload:
            warnings.append("section_structure_missing")

        return {
            "collection_id": collection_id,
            "document_id": str(document_id),
            "title": title,
            "source_filename": source_filename,
            "content_text": full_text,
            "sections": section_payload,
            "warnings": warnings,
        }

    def read_document_profiles(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        path = output_dir / _DOCUMENT_PROFILES_FILE
        if path.is_file():
            profiles = restore_frame_from_storage(
                pd.read_parquet(path),
                _DOCUMENT_PROFILE_JSON_COLUMNS,
            )
            if (
                self._profile_rebuild_required(profiles)
                or core_semantic_rebuild_required(output_dir)
            ) and (output_dir / "documents.parquet").is_file():
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
        purge_stale_core_semantic_artifacts(base_dir)
        documents_path = base_dir / "documents.parquet"
        if not documents_path.is_file():
            raise DocumentProfilesNotReadyError(collection_id, base_dir)

        documents, text_units = load_collection_inputs(base_dir)
        try:
            sections = load_sections_artifact(base_dir)
        except FileNotFoundError as exc:
            raise DocumentProfilesNotReadyError(collection_id, base_dir) from exc
        document_records = build_document_records(documents, text_units)
        sections_by_doc = self._group_sections_by_document(sections)
        file_lookup = self._build_collection_file_lookup(collection_id)
        logger.info(
            "Document profile build started collection_id=%s document_count=%s section_count=%s",
            collection_id,
            len(document_records),
            len(sections),
        )

        rows: list[dict[str, Any]] = []
        for _, row in document_records.iterrows():
            document_id = str(row.get("paper_id") or row.get("document_id") or "")
            document_sections = sections_by_doc.get(document_id, [])
            profiled = self._profile_document_row(
                collection_id=collection_id,
                row=row,
                sections=document_sections,
                file_lookup=file_lookup,
            )
            logger.info(
                "Document profile extracted collection_id=%s document_id=%s doc_type=%s protocol_extractable=%s section_count=%s warning_count=%s",
                collection_id,
                document_id,
                profiled.get("doc_type"),
                profiled.get("protocol_extractable"),
                len(document_sections),
                len(profiled.get("parsing_warnings", [])),
            )
            rows.append(profiled)
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
        write_core_semantic_manifest(base_dir)
        self.artifact_registry_service.upsert(collection_id, base_dir)
        logger.info(
            "Document profile build finished collection_id=%s profile_count=%s protocol_candidate_count=%s",
            collection_id,
            len(profiles),
            self.count_protocol_suitable(profiles),
        )
        return profiles

    def _get_structured_extractor(self) -> CoreLLMStructuredExtractor:
        if self._structured_extractor is None:
            self._structured_extractor = build_default_core_llm_structured_extractor()
        return self._structured_extractor

    def count_protocol_suitable(self, profiles: pd.DataFrame) -> int:
        normalized = self._normalize_profiles_table(profiles, None)
        return int(normalized["protocol_extractable"].isin(list(PROTOCOL_SUITABLE_EXTRACTABILITY)).sum())

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
        profile_payload = {
            "collection_id": collection_id,
            "document_id": document_id,
            "title": title,
            "source_filename": source_filename,
            "analysis_title": analysis_title,
            "representative_text": text[:12000],
            "sections": [
                {
                    "section_id": str(section.get("section_id") or ""),
                    "section_type": str(section.get("section_type") or ""),
                    "heading": self._normalize_optional_text(section.get("heading")),
                    "text": str(section.get("text") or "")[:4000],
                }
                for section in sections
                if isinstance(section, dict)
            ],
        }
        extracted = self._get_structured_extractor().extract_document_profile(
            profile_payload
        )
        normalized = DocumentProfile.from_mapping(
            {
                "document_id": document_id,
                "collection_id": collection_id,
                "title": title,
                "source_filename": source_filename,
                "doc_type": str(extracted.doc_type or DOC_TYPE_UNCERTAIN),
                "protocol_extractable": str(
                    extracted.protocol_extractable or PROTOCOL_EXTRACTABLE_UNCERTAIN
                ),
                "protocol_extractability_signals": list(
                    extracted.protocol_extractability_signals
                ),
                "parsing_warnings": list(extracted.parsing_warnings),
                "confidence": extracted.confidence,
            }
        )
        return normalized.to_record()

    def summarize_document_profiles(self, profiles: pd.DataFrame) -> dict[str, Any]:
        normalized = self._normalize_profiles_table(profiles, None)
        summary = summarize_document_profile_collection(
            DocumentProfile.from_mapping(dict(row))
            for _, row in normalized.iterrows()
        )
        return summary.to_payload()

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
            "doc_type": str(row.get("doc_type") or DOC_TYPE_UNCERTAIN),
            "protocol_extractable": str(
                row.get("protocol_extractable") or PROTOCOL_EXTRACTABLE_UNCERTAIN
            ),
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
            document_id = str(
                row.get("paper_id")
                or row.get("document_id")
                or row.get("id")
                or ""
            )
            grouped.setdefault(document_id, []).append(dict(row))
        return grouped

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

    def _find_profile_row(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        try:
            profiles = self.read_document_profiles(collection_id)
        except DocumentProfilesNotReadyError:
            return None

        if profiles.empty:
            return None

        matched = profiles[profiles["document_id"].astype(str) == str(document_id)]
        if matched.empty:
            return None
        return dict(matched.iloc[0])

    def _build_document_content_sections(
        self,
        full_text: str,
        sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ordered_sections = sorted(
            (section for section in sections if isinstance(section, dict)),
            key=lambda item: self._safe_int(item.get("order"), default=0),
        )
        payload: list[dict[str, Any]] = []
        cursor = 0

        for index, section in enumerate(ordered_sections, start=1):
            section_text = str(section.get("text") or "").strip()
            if not section_text:
                continue

            start_offset, end_offset = self._locate_text_span(
                full_text,
                section_text,
                cursor,
            )
            if end_offset is not None:
                cursor = end_offset

            payload.append(
                {
                    "section_id": str(section.get("section_id") or f"section_{index}"),
                    "heading": self._normalize_optional_text(section.get("heading")),
                    "section_type": self._normalize_optional_text(section.get("section_type")),
                    "order": self._safe_int(section.get("order"), default=index),
                    "text": section_text,
                    "text_unit_ids": self._normalize_string_list(section.get("text_unit_ids")),
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                }
            )

        if payload:
            return payload

        if full_text.strip():
            return [
                {
                    "section_id": "document_body",
                    "heading": "Document body",
                    "section_type": "full_text",
                    "order": 1,
                    "text": full_text,
                    "text_unit_ids": [],
                    "start_offset": 0,
                    "end_offset": len(full_text),
                }
            ]
        return []

    def _locate_text_span(
        self,
        full_text: str,
        target_text: str,
        start_index: int = 0,
    ) -> tuple[int | None, int | None]:
        source = str(full_text or "")
        target = str(target_text or "").strip()
        if not source or not target:
            return (None, None)

        index = source.find(target, max(start_index, 0))
        if index < 0 and start_index > 0:
            index = source.find(target)
        if index < 0 and len(target) > 60:
            short_target = target[: min(len(target), 160)].strip()
            if short_target:
                index = source.find(short_target, max(start_index, 0))
                if index < 0 and start_index > 0:
                    index = source.find(short_target)
                if index >= 0:
                    return (index, index + len(short_target))
        if index < 0:
            return (None, None)
        return (index, index + len(target))

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

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
