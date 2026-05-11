from __future__ import annotations

import ast
import json
import logging
import math
from pathlib import Path
from typing import Any, Mapping

from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from domain.core.document_profile import (
    DocumentProfile,
    summarize_document_profile_collection,
)
from domain.ports import CoreFactRepository, SourceArtifactRepository
from domain.source import SourceArtifactSet
from domain.shared.enums import (
    DOC_TYPE_UNCERTAIN,
)
from domain.shared.record_normalization import normalize_record_value
from infra.persistence.factory import (
    build_core_fact_repository,
    build_source_artifact_repository,
)
from .llm.extractor import (
    CoreLLMStructuredExtractor,
    build_default_core_llm_structured_extractor,
)

logger = logging.getLogger(__name__)


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

_PROFILE_HEADINGS_LIMIT = 8
_PROFILE_LEAD_SECTION_LIMIT = 3
_PROFILE_LEAD_TEXT_LIMIT = 3000
_PROFILE_FRONT_MATTER_HEADINGS = (
    "abstract",
    "summary",
    "introduction",
    "background",
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
        core_fact_repository: CoreFactRepository | None = None,
        source_artifact_repository: SourceArtifactRepository | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self._structured_extractor = structured_extractor
        self.core_fact_repository = (
            core_fact_repository
            or build_core_fact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.source_artifact_repository = (
            source_artifact_repository
            or build_source_artifact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
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
            self._serialize_profile_record(profile)
            for profile in profiles[offset : offset + limit]
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
        for profile in profiles:
            if str(profile.document_id) == str(document_id):
                return self._serialize_profile_record(profile)
        raise DocumentNotFoundError(collection_id, document_id)

    def get_document_content(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        output_dir = self._resolve_output_dir(collection_id)
        try:
            artifacts = self._load_source_artifacts(collection_id)
        except FileNotFoundError as exc:
            raise DocumentContentNotReadyError(collection_id, output_dir) from exc

        document_records = self._build_document_records(artifacts)
        row = next(
            (
                record
                for record in document_records
                if str(record.get("paper_id") or "") == str(document_id)
            ),
            None,
        )
        if row is None:
            raise DocumentNotFoundError(collection_id, document_id)

        blocks_by_doc = self._group_blocks_by_document(artifacts)
        profile = self._find_profile_row(collection_id, document_id)
        file_lookup = self._build_collection_file_lookup(collection_id)

        full_text = str(row.get("text") or "").strip()
        block_payload = self._build_document_content_blocks(
            full_text=full_text,
            blocks=blocks_by_doc.get(str(document_id), []),
        )
        if not full_text and block_payload:
            full_text = "\n\n".join(
                block["text"] for block in block_payload if str(block.get("text") or "").strip()
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
        if not block_payload:
            warnings.append("block_structure_missing")

        return {
            "collection_id": collection_id,
            "document_id": str(document_id),
            "title": title,
            "source_filename": source_filename,
            "content_text": full_text,
            "blocks": block_payload,
            "warnings": warnings,
        }

    def read_document_profiles(self, collection_id: str) -> tuple[DocumentProfile, ...]:
        output_dir = self._resolve_output_dir(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if facts.document_profiles:
            return self._normalize_profile_records(
                facts.document_profiles,
                collection_id,
            )
        return self.build_document_profiles(collection_id, output_dir)

    def build_document_profiles(
        self,
        collection_id: str,
        output_dir: str | Path | None = None,
    ) -> tuple[DocumentProfile, ...]:
        base_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else self._resolve_output_dir(collection_id)
        )
        try:
            artifacts = self._load_source_artifacts(collection_id)
        except FileNotFoundError as exc:
            raise DocumentProfilesNotReadyError(collection_id, base_dir) from exc
        document_records = self._build_document_records(artifacts)
        blocks_by_doc = self._group_blocks_by_document(artifacts)
        file_lookup = self._build_collection_file_lookup(collection_id)
        logger.info(
            "Document profile build started collection_id=%s document_count=%s block_count=%s",
            collection_id,
            len(document_records),
            len(artifacts.blocks),
        )

        profiles: list[DocumentProfile] = []
        for row in document_records:
            document_id = str(row.get("paper_id") or row.get("document_id") or "")
            document_blocks = blocks_by_doc.get(document_id, [])
            profiled = self._profile_document_row(
                collection_id=collection_id,
                row=row,
                blocks=document_blocks,
                file_lookup=file_lookup,
            )
            logger.info(
                "Document profile extracted collection_id=%s document_id=%s doc_type=%s block_count=%s warning_count=%s",
                collection_id,
                document_id,
                profiled.get("doc_type"),
                len(document_blocks),
                len(profiled.get("parsing_warnings", [])),
            )
            profiles.append(DocumentProfile.from_mapping(profiled))
        normalized_profiles = self._normalize_profile_records(
            profiles,
            collection_id,
        )
        self.core_fact_repository.replace_collection_document_profiles(
            collection_id,
            normalized_profiles,
        )
        self.artifact_registry_service.upsert(collection_id, base_dir)
        logger.info(
            "Document profile build finished collection_id=%s profile_count=%s",
            collection_id,
            len(normalized_profiles),
        )
        return normalized_profiles

    def _get_structured_extractor(self) -> CoreLLMStructuredExtractor:
        if self._structured_extractor is None:
            self._structured_extractor = build_default_core_llm_structured_extractor()
        return self._structured_extractor

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

    def _load_source_artifacts(self, collection_id: str) -> SourceArtifactSet:
        artifacts = self.source_artifact_repository.read_collection_artifacts(
            collection_id
        )
        if not artifacts.documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return artifacts

    def _build_document_records(
        self,
        artifacts: SourceArtifactSet,
    ) -> list[dict[str, Any]]:
        text_unit_lookup = {
            text_unit.text_unit_id: text_unit
            for text_unit in artifacts.text_units
            if text_unit.text_unit_id
        }
        records: list[dict[str, Any]] = []
        for document in artifacts.documents:
            text = str(document.text or "").strip()
            if not text and document.text_unit_ids:
                text = "\n\n".join(
                    str(text_unit_lookup[text_unit_id].text or "").strip()
                    for text_unit_id in document.text_unit_ids
                    if text_unit_id in text_unit_lookup
                    and str(text_unit_lookup[text_unit_id].text or "").strip()
                )
            records.append(
                {
                    "paper_id": document.document_id,
                    "document_id": document.document_id,
                    "title": document.title,
                    "text": text,
                    "text_unit_ids": list(document.text_unit_ids),
                    "creation_date": document.creation_date,
                    "metadata": dict(document.metadata),
                    "source_filename": document.metadata.get("source_filename"),
                    "original_filename": document.metadata.get("original_filename"),
                    "stored_filename": document.metadata.get("stored_filename"),
                }
            )
        return records

    def _profile_document_row(
        self,
        collection_id: str,
        row: Mapping[str, Any],
        blocks: list[dict[str, Any]],
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
        profile_payload = self._build_document_profile_payload(
            title=title,
            source_filename=source_filename,
            full_text=str(row.get("text") or ""),
            blocks=blocks,
        )
        if self._document_profile_payload_is_insufficient(profile_payload):
            return DocumentProfile.from_mapping(
                {
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "title": title,
                    "source_filename": source_filename,
                    "doc_type": DOC_TYPE_UNCERTAIN,
                    "parsing_warnings": ["insufficient_content"],
                    "confidence": 0.0,
                }
            ).to_record()

        extracted = self._get_structured_extractor().extract_document_profile(
            profile_payload
        )
        parsing_warnings = list(extracted.parsing_warnings)
        if extracted.doc_type == DOC_TYPE_UNCERTAIN and "classification_uncertain" not in parsing_warnings:
            parsing_warnings.append("classification_uncertain")
        normalized = DocumentProfile.from_mapping(
            {
                "document_id": document_id,
                "collection_id": collection_id,
                "title": title,
                "source_filename": source_filename,
                "doc_type": str(extracted.doc_type or DOC_TYPE_UNCERTAIN),
                "parsing_warnings": parsing_warnings,
                "confidence": extracted.confidence,
            }
        )
        return normalized.to_record()

    def _build_document_profile_payload(
        self,
        *,
        title: str | None,
        source_filename: str | None,
        full_text: str,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "title": title,
            "source_filename": source_filename,
            "abstract_or_lead_text": self._select_document_profile_lead_text(
                blocks,
                full_text,
            ),
            "headings": self._collect_document_profile_headings(blocks),
        }

    def _document_profile_payload_is_insufficient(
        self,
        payload: dict[str, Any],
    ) -> bool:
        lead_text = self._normalize_optional_text(payload.get("abstract_or_lead_text"))
        headings = [
            str(item).strip()
            for item in payload.get("headings", [])
            if str(item).strip()
        ]
        return lead_text is None and not headings

    def _collect_document_profile_headings(
        self,
        blocks: list[dict[str, Any]],
    ) -> list[str]:
        headings: list[str] = []
        seen: set[str] = set()
        for block in self._ordered_profile_blocks(blocks):
            if str(block.get("block_type") or "") != "heading":
                continue
            heading = self._normalize_optional_text(block.get("text"))
            if heading is None:
                continue
            normalized_heading = heading.casefold()
            if normalized_heading in seen:
                continue
            seen.add(normalized_heading)
            headings.append(heading)
            if len(headings) >= _PROFILE_HEADINGS_LIMIT:
                break
        return headings

    def _select_document_profile_lead_text(
        self,
        blocks: list[dict[str, Any]],
        full_text: str,
    ) -> str | None:
        ordered_blocks = self._ordered_profile_blocks(blocks)
        for block in ordered_blocks:
            if str(block.get("block_type") or "") in {"heading", "title"}:
                continue
            heading_path = self._normalize_optional_text(block.get("heading_path")) or ""
            block_text = self._normalize_optional_text(block.get("text"))
            if block_text is None:
                continue
            if any(marker in heading_path.casefold() for marker in _PROFILE_FRONT_MATTER_HEADINGS):
                return block_text[:_PROFILE_LEAD_TEXT_LIMIT]

        lead_chunks: list[str] = []
        total_length = 0
        for block in ordered_blocks:
            if str(block.get("block_type") or "") in {"heading", "title"}:
                continue
            block_text = self._normalize_optional_text(block.get("text"))
            if block_text is None:
                continue
            lead_chunks.append(block_text)
            total_length += len(block_text)
            if (
                len(lead_chunks) >= _PROFILE_LEAD_SECTION_LIMIT
                or total_length >= _PROFILE_LEAD_TEXT_LIMIT
            ):
                break

        if lead_chunks:
            return "\n\n".join(lead_chunks)[:_PROFILE_LEAD_TEXT_LIMIT]

        normalized_full_text = self._normalize_optional_text(full_text)
        if normalized_full_text is None:
            return None
        return normalized_full_text[:_PROFILE_LEAD_TEXT_LIMIT]

    def _ordered_profile_blocks(
        self,
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return sorted(
            (block for block in blocks if isinstance(block, dict)),
            key=lambda item: self._safe_int(item.get("block_order"), default=0),
        )

    def summarize_document_profiles(
        self,
        profiles: tuple[DocumentProfile, ...],
    ) -> dict[str, Any]:
        summary = summarize_document_profile_collection(profiles)
        return summary.to_payload()

    def _normalize_profile_records(
        self,
        profiles: tuple[DocumentProfile, ...] | list[DocumentProfile],
        collection_id: str | None,
    ) -> tuple[DocumentProfile, ...]:
        normalized: list[DocumentProfile] = []
        for profile in profiles:
            payload = profile.to_record()
            if collection_id is not None and not payload.get("collection_id"):
                payload["collection_id"] = collection_id
            normalized.append(DocumentProfile.from_mapping(payload))
        return tuple(normalized)

    def _serialize_profile_record(self, profile: DocumentProfile) -> dict[str, Any]:
        return profile.to_record()

    def _group_blocks_by_document(
        self,
        artifacts: SourceArtifactSet,
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for block in artifacts.blocks:
            document_id = str(block.document_id or "")
            grouped.setdefault(document_id, []).append(block.to_record())
        return grouped

    def _normalize_string_list(self, value: Any) -> list[str]:
        normalized = normalize_record_value(value)
        if normalized is None:
            return []
        if isinstance(normalized, list):
            return [str(item) for item in normalized if str(item).strip()]
        return [str(normalized)]

    def _normalize_optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        text = str(value).strip()
        return text or None

    def _find_profile_row(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        try:
            profiles = self.read_document_profiles(collection_id)
        except DocumentProfilesNotReadyError:
            return None

        for profile in profiles:
            if str(profile.document_id) == str(document_id):
                return profile.to_record()
        return None

    def _build_document_content_blocks(
        self,
        full_text: str,
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ordered_blocks = sorted(
            (block for block in blocks if isinstance(block, dict)),
            key=lambda item: self._safe_int(item.get("block_order"), default=0),
        )
        payload: list[dict[str, Any]] = []
        cursor = 0

        for index, block in enumerate(ordered_blocks, start=1):
            block_text = str(block.get("text") or "").strip()
            if not block_text:
                continue

            start_offset, end_offset = self._locate_text_span(
                full_text,
                block_text,
                cursor,
            )
            if end_offset is not None:
                cursor = end_offset

            payload.append(
                {
                    "block_id": str(block.get("block_id") or f"block_{index}"),
                    "block_type": self._normalize_optional_text(block.get("block_type")),
                    "heading_path": self._normalize_optional_text(block.get("heading_path")),
                    "heading_level": self._safe_int(block.get("heading_level"), default=0),
                    "order": self._safe_int(block.get("block_order"), default=index),
                    "text": block_text,
                    "text_unit_ids": self._normalize_string_list(block.get("text_unit_ids")),
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "page": self._normalize_page(block.get("page")),
                    "bbox": self._normalize_bbox_payload(block.get("bbox")),
                    "char_range": self._normalize_char_range_payload(
                        block.get("char_range")
                    ),
                }
            )

        if payload:
            return payload

        if full_text.strip():
            return [
                {
                    "block_id": "document_body",
                    "block_type": "full_text",
                    "heading_path": None,
                    "heading_level": 0,
                    "order": 1,
                    "text": full_text,
                    "text_unit_ids": [],
                    "start_offset": 0,
                    "end_offset": len(full_text),
                    "page": None,
                    "bbox": None,
                    "char_range": None,
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

    def _normalize_page(self, value: Any) -> int | None:
        number = self._finite_float(value)
        if number is None:
            return None
        page = int(number)
        return page if page > 0 and page == number else None

    def _normalize_char_range_payload(self, value: Any) -> dict[str, int] | None:
        payload = self._normalize_object_payload(value)
        if payload is None:
            return None

        start = self._whole_number(payload.get("start"))
        end = self._whole_number(payload.get("end"))
        if start is None or end is None or start < 0 or end < start:
            return None
        return {"start": start, "end": end}

    def _normalize_bbox_payload(self, value: Any) -> dict[str, float | str | None] | None:
        payload = self._normalize_object_payload(value)
        if payload is None:
            return None

        x0 = self._finite_float(payload.get("x0", payload.get("l")))
        y0 = self._finite_float(payload.get("y0", payload.get("t")))
        x1 = self._finite_float(payload.get("x1", payload.get("r")))
        y1 = self._finite_float(payload.get("y1", payload.get("b")))
        if x0 is None or y0 is None or x1 is None or y1 is None:
            return None

        return {
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "coord_origin": self._normalize_optional_text(payload.get("coord_origin")),
        }

    def _normalize_object_payload(self, value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if not isinstance(value, str):
            return None

        text = value.strip()
        if not text:
            return None

        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(text)
            except (TypeError, ValueError, SyntaxError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _whole_number(self, value: Any) -> int | None:
        number = self._finite_float(value)
        if number is None:
            return None
        whole = int(number)
        return whole if number == whole else None

    def _finite_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

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
        row: Mapping[str, Any],
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
        row: Mapping[str, Any],
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

    def _iter_document_title_candidates(self, row: Mapping[str, Any]) -> list[str]:
        seen: set[str] = set()
        values: list[str] = []
        for key in _TITLE_FIELD_CANDIDATES:
            candidate = self._extract_row_or_metadata_value(row, key)
            normalized = self._normalize_optional_text(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                values.append(normalized)
        return values

    def _extract_row_or_metadata_value(self, row: Mapping[str, Any], key: str) -> Any:
        if key in row:
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
        if isinstance(value, float) and math.isnan(value):
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
