from __future__ import annotations

from asyncio import to_thread
import ast
import json
import logging
import math
from pathlib import Path
from typing import Any, Mapping

from application.core.document_profiles.extraction import (
    DocumentProfileExtractionError,
    DocumentProfileExtractor,
    build_default_document_profile_extractor,
)
from application.source.collection_service import CollectionService
from domain.core.document_profile import (
    DocumentProfile,
    summarize_document_profile_collection,
)
from domain.ports import PaperFactRepository, SourceArtifactRepository
from domain.source import SourceBlock, SourceDocument, normalize_optional_text
from domain.shared.enums import (
    DOC_TYPE_UNCERTAIN,
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

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"document profiles not ready: {collection_id}")


class DocumentContentNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve document content."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
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
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        paper_fact_repository: PaperFactRepository,
        document_profile_extractor: DocumentProfileExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._document_profile_extractor = document_profile_extractor
        self.paper_fact_repository = paper_fact_repository
        self.source_artifact_repository = source_artifact_repository

    async def list_document_profiles(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 51,
    ) -> dict[str, Any]:
        profiles = await self.read_document_profiles(collection_id)
        summary = self.summarize_document_profiles(profiles)
        items = [
            profile.to_record()
            for profile in profiles[offset : offset + limit]
        ]
        return {
            "collection_id": collection_id,
            "total": len(profiles),
            "count": len(items),
            "summary": summary,
            "items": items,
        }

    async def get_document_summary(self, collection_id: str) -> dict[str, Any]:
        profiles = await self.read_document_profiles(collection_id)
        return self.summarize_document_profiles(profiles)

    async def get_document_profile(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        profiles = await self.read_document_profiles(collection_id)
        for profile in profiles:
            if profile.document_id == document_id:
                return profile.to_record()
        raise DocumentNotFoundError(collection_id, document_id)

    async def get_document_content(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        await self.collection_service.get_collection(collection_id)
        try:
            documents = await self._load_source_documents(collection_id)
        except FileNotFoundError as exc:
            raise DocumentContentNotReadyError(collection_id) from exc

        document_records = self._build_document_records(documents)
        row = next(
            (
                record
                for record in document_records
                if record["paper_id"] == document_id
            ),
            None,
        )
        if row is None:
            raise DocumentNotFoundError(collection_id, document_id)

        blocks_by_doc = {
            document.document_id: list(document.blocks)
            for document in documents
        }
        profile = await self._find_profile(collection_id, document_id)
        file_lookup = await self._build_collection_file_lookup(collection_id)

        full_text = str(row.get("text") or "").strip()
        block_payload = self._build_document_content_blocks(
            full_text=full_text,
            blocks=blocks_by_doc.get(document_id, []),
        )
        if not full_text and block_payload:
            full_text = "\n\n".join(
                block["text"] for block in block_payload if str(block.get("text") or "").strip()
            ).strip()

        title = profile.title if profile else None
        if title is None:
            source_filename = self._resolve_source_filename(row, document_id, file_lookup)
            title = self._resolve_document_title(row, document_id, source_filename, file_lookup)
        else:
            source_filename = profile.source_filename
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

    async def read_document_profiles(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> tuple[DocumentProfile, ...]:
        await self.collection_service.get_collection(collection_id)
        # Profile reads never regenerate missing build artifacts.
        facts = await self.paper_fact_repository.read(
            collection_id, build_id=build_id
        )
        if facts.document_profiles:
            return facts.document_profiles
        raise DocumentProfilesNotReadyError(collection_id)

    async def build_document_profiles(
        self,
        collection_id: str,
        *,
        build_id: str,
    ) -> tuple[DocumentProfile, ...]:
        await self.collection_service.get_collection(collection_id)
        try:
            documents = await self._load_source_documents(
                collection_id, build_id=build_id
            )
        except FileNotFoundError as exc:
            raise DocumentProfilesNotReadyError(collection_id) from exc
        document_records = self._build_document_records(documents)
        blocks_by_doc = {
            document.document_id: list(document.blocks)
            for document in documents
        }
        file_lookup = await self._build_collection_file_lookup(collection_id)
        logger.info(
            "Document profile build started collection_id=%s document_count=%s block_count=%s",
            collection_id,
            len(document_records),
            sum(len(document.blocks) for document in documents),
        )

        profiles: list[DocumentProfile] = []
        for row in document_records:
            document_id = str(row.get("paper_id") or row.get("document_id") or "")
            document_blocks = blocks_by_doc.get(document_id, [])
            profiled = await to_thread(
                self._profile_document_row,
                collection_id=collection_id,
                build_id=build_id,
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
        document_profiles = tuple(profiles)
        await self.paper_fact_repository.replace_document_profiles(
            collection_id,
            build_id,
            document_profiles,
        )
        logger.info(
            "Document profile build finished collection_id=%s profile_count=%s",
            collection_id,
            len(document_profiles),
        )
        return document_profiles

    def _get_document_profile_extractor(self) -> DocumentProfileExtractor:
        if self._document_profile_extractor is None:
            self._document_profile_extractor = build_default_document_profile_extractor()
        return self._document_profile_extractor

    async def _load_source_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        documents = (
            await self.source_artifact_repository.read_collection_documents(
                collection_id,
                build_id=build_id,
            )
            if build_id is not None
            else await self.source_artifact_repository.read_collection_documents(
                collection_id
            )
        )
        if not documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return documents

    def _build_document_records(
        self,
        documents: tuple[SourceDocument, ...],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for document in documents:
            text = str(document.text or "").strip()
            if not text and document.text_units:
                text = "\n\n".join(
                    str(text_unit.text or "").strip()
                    for text_unit in document.text_units
                    if str(text_unit.text or "").strip()
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
        build_id: str,
        row: Mapping[str, Any],
        blocks: list[SourceBlock],
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

        extractor = self._get_document_profile_extractor()
        try:
            extracted = extractor.extract_document_profile(profile_payload)
        except DocumentProfileExtractionError:
            trace = extractor.consume_last_trace() or {}
            diagnostic = {
                key: trace[key]
                for key in (
                    "task_type",
                    "prompt_version",
                    "model",
                    "extraction_mode",
                    "trace_status",
                    "elapsed_s",
                    "error",
                    "attempts",
                )
                if key in trace
            }
            logger.warning(
                "Document profile classification unavailable; preserving document "
                "as uncertain collection_id=%s build_id=%s document_id=%s trace=%s",
                collection_id,
                build_id,
                document_id,
                json.dumps(
                    diagnostic,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            )
            return DocumentProfile.from_mapping(
                {
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "title": title,
                    "source_filename": source_filename,
                    "doc_type": DOC_TYPE_UNCERTAIN,
                    "parsing_warnings": ["document_profile_extraction_failed"],
                    "confidence": 0.0,
                }
            ).to_record()
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
        blocks: list[SourceBlock],
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
        lead_text = normalize_optional_text(payload.get("abstract_or_lead_text"))
        headings = [
            str(item).strip()
            for item in payload.get("headings", [])
            if str(item).strip()
        ]
        return lead_text is None and not headings

    def _collect_document_profile_headings(
        self,
        blocks: list[SourceBlock],
    ) -> list[str]:
        headings: list[str] = []
        seen: set[str] = set()
        for block in self._ordered_profile_blocks(blocks):
            if block.block_type != "heading":
                continue
            heading = normalize_optional_text(block.text)
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
        blocks: list[SourceBlock],
        full_text: str,
    ) -> str | None:
        ordered_blocks = self._ordered_profile_blocks(blocks)
        for block in ordered_blocks:
            if block.block_type in {"heading", "title"}:
                continue
            heading_path = block.heading_path or ""
            block_text = normalize_optional_text(block.text)
            if block_text is None:
                continue
            if any(marker in heading_path.casefold() for marker in _PROFILE_FRONT_MATTER_HEADINGS):
                return block_text[:_PROFILE_LEAD_TEXT_LIMIT]

        lead_chunks: list[str] = []
        total_length = 0
        for block in ordered_blocks:
            if block.block_type in {"heading", "title"}:
                continue
            block_text = normalize_optional_text(block.text)
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

        normalized_full_text = normalize_optional_text(full_text)
        if normalized_full_text is None:
            return None
        return normalized_full_text[:_PROFILE_LEAD_TEXT_LIMIT]

    def _ordered_profile_blocks(
        self,
        blocks: list[SourceBlock],
    ) -> list[SourceBlock]:
        return sorted(blocks, key=lambda block: block.block_order)

    def summarize_document_profiles(
        self,
        profiles: tuple[DocumentProfile, ...],
    ) -> dict[str, Any]:
        summary = summarize_document_profile_collection(profiles)
        return summary.to_payload()

    async def _find_profile(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        try:
            profiles = await self.read_document_profiles(collection_id)
        except DocumentProfilesNotReadyError:
            return None

        for profile in profiles:
            if profile.document_id == document_id:
                return profile
        return None

    def _build_document_content_blocks(
        self,
        full_text: str,
        blocks: list[SourceBlock],
    ) -> list[dict[str, Any]]:
        ordered_blocks = self._ordered_profile_blocks(blocks)
        payload: list[dict[str, Any]] = []

        for index, block in enumerate(ordered_blocks, start=1):
            block_text = block.text.strip()
            if not block_text:
                continue

            payload.append(
                {
                    "block_id": block.block_id or f"block_{index}",
                    "block_type": block.block_type,
                    "heading_path": block.heading_path,
                    "heading_level": block.heading_level or 0,
                    "order": block.block_order,
                    "text": block_text,
                    "text_unit_ids": list(block.text_unit_ids),
                    "page": self._normalize_page(block.page),
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
                    "page": None,
                }
            ]
        return []

    def _normalize_page(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        page = int(number)
        return page if page > 0 and page == number else None

    async def _build_collection_file_lookup(
        self, collection_id: str
    ) -> dict[str, Any]:
        try:
            files = await self.collection_service.list_files(collection_id)
        except FileNotFoundError:
            files = []

        stored_to_source: dict[str, str] = {}
        resolved_sources: list[str] = []
        for record in files:
            original = normalize_optional_text(record.get("original_filename"))
            stored = normalize_optional_text(record.get("stored_filename"))
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

        for key in (
            *_SOURCE_FILENAME_FIELD_CANDIDATES,
            *_SOURCE_PATH_FIELD_CANDIDATES,
        ):
            candidate = self._extract_row_or_metadata_value(row, key)
            filename = Path(candidate).name if candidate else None
            if filename and filename != document_id:
                return stored_to_source.get(filename, filename)

        title_value = normalize_optional_text(row.get("title"))
        if title_value and title_value in stored_to_source:
            return stored_to_source[title_value]

        return file_lookup.get("single_source_filename")

    def _iter_document_title_candidates(self, row: Mapping[str, Any]) -> list[str]:
        seen: set[str] = set()
        values: list[str] = []
        for key in _TITLE_FIELD_CANDIDATES:
            candidate = self._extract_row_or_metadata_value(row, key)
            if candidate and candidate not in seen:
                seen.add(candidate)
                values.append(candidate)
        return values

    def _extract_row_or_metadata_value(
        self,
        row: Mapping[str, Any],
        key: str,
    ) -> str | None:
        if key in row:
            value = row.get(key)
            normalized = normalize_optional_text(value)
            if normalized is not None:
                return normalized

        metadata = self._coerce_mapping(row.get("metadata"))
        value = metadata.get(key)
        normalized = normalize_optional_text(value)
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
