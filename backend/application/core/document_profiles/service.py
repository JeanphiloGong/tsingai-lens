from __future__ import annotations

from asyncio import to_thread
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
    PROFILE_STATUS_EXTRACTION_FAILED,
    PROFILE_STATUS_COMPLETED,
    summarize_document_profile_collection,
)
from application.repositories.document_profile_repository import (
    DocumentProfileRepository,
)
from application.repositories.source_artifact_repository import SourceArtifactRepository
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
    """Generate and serve each document's current profile."""

    def __init__(
        self,
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        document_profile_repository: DocumentProfileRepository,
        document_profile_extractor: DocumentProfileExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._document_profile_extractor = document_profile_extractor
        self.document_profile_repository = document_profile_repository
        self.source_artifact_repository = source_artifact_repository

    async def list_document_profiles(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 51,
        query: str | None = None,
        doc_type: str | None = None,
        has_warnings: bool | None = None,
    ) -> dict[str, Any]:
        profiles = await self.read_document_profiles(collection_id)
        summary = self.summarize_document_profiles(profiles)
        normalized_query = str(query or "").strip().casefold()
        normalized_doc_type = str(doc_type or "").strip().casefold()
        matched_profiles = tuple(
            profile
            for profile in profiles
            if (
                not normalized_query
                or normalized_query
                in " ".join(
                    value
                    for value in (profile.title,)
                    if value
                ).casefold()
            )
            and (not normalized_doc_type or profile.doc_type == normalized_doc_type)
            and (
                has_warnings is None
                or bool(profile.profile_warnings) is has_warnings
            )
        )
        items = [
            profile.to_record()
            for profile in matched_profiles[offset : offset + limit]
        ]
        return {
            "collection_id": collection_id,
            "total": len(matched_profiles),
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
        await self.collection_service.get_collection(collection_id)
        profile = await self.read_document_profile(collection_id, document_id)
        if profile is not None:
            return profile.to_record()
        if not await self.document_profile_repository.list_collection(collection_id):
            raise DocumentProfilesNotReadyError(collection_id)
        raise DocumentNotFoundError(collection_id, document_id)

    async def get_document_content(
        self,
        collection_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        collection = await self.collection_service.get_collection(collection_id)
        document = await self.source_artifact_repository.read_document(
            collection_id,
            document_id,
        )
        if document is None:
            if not await self.source_artifact_repository.has_documents(collection_id):
                raise DocumentContentNotReadyError(collection_id)
            raise DocumentNotFoundError(collection_id, document_id)

        profile = await self.read_document_profile(collection_id, document_id)
        file_lookup = self._build_collection_file_lookup(collection)

        full_text = self._document_text(document)
        block_payload = self._build_document_content_blocks(
            full_text=full_text,
            blocks=list(document.blocks),
        )
        if not full_text and block_payload:
            full_text = "\n\n".join(
                block["text"] for block in block_payload if str(block.get("text") or "").strip()
            ).strip()

        title = profile.title if profile else None
        source_filename = self._resolve_source_filename(document, file_lookup)
        if title is None:
            title = self._resolve_document_title(document, source_filename, file_lookup)

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
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        await self.collection_service.get_collection(collection_id)

        profiles = await self.document_profile_repository.list_collection(
            collection_id,
            document_ids,
        )

        if profiles:
            return profiles
        raise DocumentProfilesNotReadyError(collection_id)

    async def read_document_profile(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        return await self.document_profile_repository.read(
            collection_id,
            document_id,
        )

    async def build_document_profile(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile:
        collection = await self.collection_service.get_collection(collection_id)
        document = await self.source_artifact_repository.read_document(
            collection_id,
            document_id,
        )
        if document is None:
            exc = FileNotFoundError(
                f"source artifacts not ready: {collection_id}/{document_id}"
            )
            raise DocumentProfilesNotReadyError(collection_id) from exc
        file_lookup = self._build_collection_file_lookup(collection)
        logger.info(
            "Document profile build started collection_id=%s document_id=%s block_count=%s",
            collection_id,
            document_id,
            len(document.blocks),
        )
        profile = await to_thread(
            self._profile_document,
            collection_id=collection_id,
            document=document,
            file_lookup=file_lookup,
        )
        await self.document_profile_repository.replace(collection_id, profile)
        logger.info(
            "Document profile build finished collection_id=%s document_id=%s doc_type=%s warning_count=%s",
            collection_id,
            document_id,
            profile.doc_type,
            len(profile.profile_warnings),
        )
        return profile

    def _get_document_profile_extractor(self) -> DocumentProfileExtractor:
        if self._document_profile_extractor is None:
            self._document_profile_extractor = build_default_document_profile_extractor()
        return self._document_profile_extractor

    @staticmethod
    def _document_text(document: SourceDocument) -> str:
        return (document.text or "").strip() or "\n\n".join(
            unit.text.strip()
            for unit in document.text_units
            if unit.text and unit.text.strip()
        )

    def _profile_document(
        self,
        collection_id: str,
        document: SourceDocument,
        file_lookup: dict[str, Any],
    ) -> DocumentProfile:
        document_id = document.document_id
        source_filename = self._resolve_source_filename(document, file_lookup)
        title = self._resolve_document_title(
            document=document,
            source_filename=source_filename,
            file_lookup=file_lookup,
        )
        profile_payload = self._build_document_profile_payload(
            title=title,
            source_filename=source_filename,
            full_text=self._document_text(document),
            blocks=list(document.blocks),
        )
        if self._document_profile_payload_is_insufficient(profile_payload):
            return DocumentProfile(
                document_id=document_id,
                title=title,
                doc_type=DOC_TYPE_UNCERTAIN,
                profile_warnings=("insufficient_content",),
                confidence=0.0,
                profile_status=PROFILE_STATUS_COMPLETED,
            )

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
                "as uncertain collection_id=%s document_id=%s trace=%s",
                collection_id,
                document_id,
                json.dumps(
                    diagnostic,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            )
            return DocumentProfile(
                document_id=document_id,
                title=title,
                doc_type=DOC_TYPE_UNCERTAIN,
                profile_warnings=("document_profile_extraction_failed",),
                confidence=0.0,
                profile_status=PROFILE_STATUS_EXTRACTION_FAILED,
            )
        profile_warnings = list(extracted.profile_warnings)
        if extracted.doc_type == DOC_TYPE_UNCERTAIN and "classification_uncertain" not in profile_warnings:
            profile_warnings.append("classification_uncertain")
        return DocumentProfile.from_mapping(
            {
                "document_id": document_id,
                "title": title,
                "doc_type": str(extracted.doc_type or DOC_TYPE_UNCERTAIN),
                "profile_warnings": profile_warnings,
                "confidence": extracted.confidence,
                "profile_status": PROFILE_STATUS_COMPLETED,
            }
        )

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

    @staticmethod
    def _build_collection_file_lookup(
        collection: Mapping[str, Any],
    ) -> dict[str, Any]:
        stored_to_source: dict[str, str] = {}
        resolved_sources: list[str] = []
        for record in collection["documents"]:
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
        document: SourceDocument,
        source_filename: str | None,
        file_lookup: dict[str, Any],
    ) -> str | None:
        for key in _TITLE_FIELD_CANDIDATES:
            candidate = (
                normalize_optional_text(document.title) if key == "title" else None
            )
            candidate = candidate or normalize_optional_text(document.metadata.get(key))
            if candidate is None or candidate == document.document_id:
                continue
            if source_filename and candidate == source_filename:
                continue
            if candidate in file_lookup["stored_to_source"]:
                continue
            if candidate in file_lookup["source_filenames"]:
                continue
            return candidate
        return None

    def _resolve_source_filename(
        self,
        document: SourceDocument,
        file_lookup: dict[str, Any],
    ) -> str | None:
        stored_to_source = file_lookup["stored_to_source"]

        for key in (
            *_SOURCE_FILENAME_FIELD_CANDIDATES,
            *_SOURCE_PATH_FIELD_CANDIDATES,
        ):
            candidate = normalize_optional_text(document.metadata.get(key))
            filename = Path(candidate).name if candidate else None
            if filename and filename != document.document_id:
                return stored_to_source.get(filename, filename)

        title_value = normalize_optional_text(document.title)
        if title_value and title_value in stored_to_source:
            return stored_to_source[title_value]

        return file_lookup["single_source_filename"]
