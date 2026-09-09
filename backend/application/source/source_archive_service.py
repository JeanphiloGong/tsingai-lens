"""Serve and package original paper files for reproducible review."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Any
from zipfile import ZIP_STORED, ZipFile

from domain.ports import CollectionRepository
from domain.source.ports import ObjectStore


_SOURCE_ARCHIVE_MAX_MIB = 256
_SOURCE_ARCHIVE_MAX_BYTES = _SOURCE_ARCHIVE_MAX_MIB * 1024 * 1024


class DocumentSourceUnavailableError(RuntimeError):
    """Raised when a document exists but its original source is unavailable."""

    def __init__(
        self,
        collection_id: str,
        document_id: str,
        *,
        code: str = "document_source_unavailable",
        message: str = "The original source file is not available for this document.",
    ) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        self.code = code
        self.message = message
        super().__init__(message)


class CollectionSourceArchiveError(RuntimeError):
    """Raised when selected original files cannot form a safe archive."""

    def __init__(
        self,
        collection_id: str,
        *,
        code: str,
        message: str,
        document_id: str | None = None,
    ) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        self.code = code
        self.message = message
        super().__init__(message)


class SourceArchiveService:
    """Read original uploads and build bounded reproduction archives."""

    def __init__(
        self,
        repository: CollectionRepository,
        object_store: ObjectStore,
    ) -> None:
        self.repository = repository
        self.object_store = object_store

    async def build_source_archive(
        self,
        collection_id: str,
        document_ids: list[str],
    ) -> dict[str, Any]:
        """Build a bounded ZIP of original uploads for failure reproduction."""

        normalized_document_ids = [
            str(document_id).strip() for document_id in document_ids
        ]
        if not normalized_document_ids or any(
            not document_id for document_id in normalized_document_ids
        ):
            raise ValueError("source archive requires at least one document_id")
        if len(normalized_document_ids) > 100:
            raise ValueError("source archive supports at most 100 document_ids")
        if len(set(normalized_document_ids)) != len(normalized_document_ids):
            raise ValueError("source archive document_ids must be unique")

        collection = await self._get_collection(collection_id)
        records = collection["documents"]
        records_by_document_id = {
            str(record.get("document_id") or "").strip(): record for record in records
        }
        selected_records: list[tuple[str, dict[str, Any]]] = []
        for document_id in normalized_document_ids:
            record = records_by_document_id.get(document_id)
            if record is None:
                raise CollectionSourceArchiveError(
                    collection_id,
                    code="collection_source_document_not_found",
                    message=(
                        "A requested source document does not exist in this collection."
                    ),
                    document_id=document_id,
                )
            selected_records.append((document_id, record))

        selected_size_bytes = sum(
            max(int(record.get("size_bytes") or 0), 0)
            for _document_id, record in selected_records
        )
        if selected_size_bytes > _SOURCE_ARCHIVE_MAX_BYTES:
            raise CollectionSourceArchiveError(
                collection_id,
                code="collection_source_archive_too_large",
                message=(
                    "Selected source files exceed the "
                    f"{_SOURCE_ARCHIVE_MAX_MIB} MiB archive limit."
                ),
            )

        return await asyncio.to_thread(
            self._write_source_archive,
            collection_id,
            selected_records,
        )

    async def resolve_document_source_file(
        self,
        collection_id: str,
        document_id: str,
        *,
        source_filename: str | None = None,
    ) -> dict[str, Any]:
        collection = await self._get_collection(collection_id)
        document_key = str(document_id or "").strip()
        if not document_key:
            raise DocumentSourceUnavailableError(collection_id, document_key)

        match_keys = self._source_match_keys(document_key, source_filename)
        document_matches = [
            record
            for record in collection["documents"]
            if self._source_file_record_matches(record, match_keys)
        ]
        if len(document_matches) == 1:
            return self._build_source_file_payload(
                collection_id=collection_id,
                document_id=document_key,
                record=document_matches[0],
            )
        if len(document_matches) > 1:
            raise DocumentSourceUnavailableError(
                collection_id,
                document_key,
                code="document_source_ambiguous",
                message="More than one stored source file matches this document.",
            )
        raise FileNotFoundError(f"document not found: {collection_id}/{document_key}")

    async def _get_collection(self, collection_id: str) -> dict[str, Any]:
        record = await self.repository.read_collection(collection_id)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record.to_record()

    def _write_source_archive(
        self,
        collection_id: str,
        selected_records: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Verify source bytes and write the archive outside the event loop."""

        archive_file = SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
        try:
            manifest_files: list[dict[str, Any]] = []
            with ZipFile(
                archive_file,
                mode="w",
                compression=ZIP_STORED,
                allowZip64=True,
            ) as archive:
                for position, (document_id, record) in enumerate(
                    selected_records,
                    start=1,
                ):
                    try:
                        source = self._build_source_file_payload(
                            collection_id=collection_id,
                            document_id=document_id,
                            record=record,
                        )
                    except DocumentSourceUnavailableError as exc:
                        raise CollectionSourceArchiveError(
                            collection_id,
                            code=self._source_archive_error_code(exc.code),
                            message=exc.message,
                            document_id=document_id,
                        ) from exc

                    archive_path = (
                        f"sources/{position:03d}-"
                        f"{self._safe_archive_filename(source['filename'])}"
                    )
                    content = source["content"]
                    archive.writestr(archive_path, content)
                    manifest_files.append(
                        {
                            "document_id": document_id,
                            "archive_path": archive_path,
                            "original_filename": source["filename"],
                            "media_type": source.get("media_type"),
                            "size_bytes": len(content),
                            "sha256": record.get("sha256"),
                            "status": record.get("status"),
                            "created_at": record.get("created_at"),
                        }
                    )

                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "schema_version": 1,
                            "collection_id": collection_id,
                            "documents": manifest_files,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ).encode("utf-8"),
                )
            archive_file.seek(0)
        except Exception:
            archive_file.close()
            raise

        return {
            "file": archive_file,
            "filename": self._safe_archive_filename(
                f"collection-{collection_id}-sources.zip"
            ),
        }

    def _source_file_record_matches(
        self,
        record: dict[str, Any],
        match_keys: set[str],
    ) -> bool:
        candidates = (
            record.get("document_id"),
            record.get("original_filename"),
            record.get("stored_filename"),
            record.get("storage_key"),
            Path(str(record.get("storage_key") or "")).name,
        )
        return any(
            self._source_match_value(candidate) in match_keys
            for candidate in candidates
        )

    def _source_match_keys(
        self,
        document_id: str,
        source_filename: str | None,
    ) -> set[str]:
        keys = {
            self._source_match_value(document_id),
            self._source_match_value(source_filename),
            self._source_match_value(Path(str(source_filename or "")).name),
        }
        return {key for key in keys if key}

    @staticmethod
    def _source_match_value(value: Any) -> str:
        return str(value or "").strip()

    def _build_source_file_payload(
        self,
        *,
        collection_id: str,
        document_id: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        storage_key = self._optional_text(record.get("storage_key"))
        expected_sha256 = self._optional_text(record.get("sha256"))
        if not storage_key or not expected_sha256:
            raise DocumentSourceUnavailableError(collection_id, document_id)
        stored_filename = self._optional_text(record.get("stored_filename"))
        if not stored_filename or storage_key != self._input_storage_key(
            collection_id, stored_filename
        ):
            raise DocumentSourceUnavailableError(
                collection_id,
                document_id,
                code="document_source_path_invalid",
                message="The stored source file path is not safe to serve.",
            )
        try:
            content = self.object_store.read(storage_key, expected_sha256)
        except FileNotFoundError as exc:
            raise DocumentSourceUnavailableError(collection_id, document_id) from exc
        except ValueError as exc:
            if str(exc) == "invalid storage key":
                raise DocumentSourceUnavailableError(
                    collection_id,
                    document_id,
                    code="document_source_path_invalid",
                    message="The stored source file path is not safe to serve.",
                ) from exc
            raise DocumentSourceUnavailableError(
                collection_id,
                document_id,
                code="document_source_integrity_failed",
                message="The stored source file failed its integrity check.",
            ) from exc
        filename = (
            self._optional_text(record.get("original_filename"))
            or stored_filename
            or Path(storage_key).name
        )
        return {
            "content": content,
            "filename": filename,
            "media_type": self._optional_text(record.get("media_type")),
            "source_document_id": document_id,
        }

    @staticmethod
    def _input_storage_key(collection_id: str, stored_filename: str) -> str:
        return f"{collection_id}/input/{stored_filename}"

    @staticmethod
    def _safe_archive_filename(value: Any) -> str:
        filename = PurePosixPath(str(value or "").replace("\\", "/")).name
        filename = "".join(
            "_" if ord(character) < 32 or character in '<>:"|?*' else character
            for character in filename
        ).strip(" .")
        return filename or "source.bin"

    @staticmethod
    def _source_archive_error_code(document_source_code: str) -> str:
        return {
            "document_source_path_invalid": "collection_source_path_invalid",
            "document_source_integrity_failed": "collection_source_integrity_failed",
        }.get(document_source_code, "collection_source_file_unavailable")

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = [
    "CollectionSourceArchiveError",
    "DocumentSourceUnavailableError",
    "SourceArchiveService",
]
