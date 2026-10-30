"""Serve and package original paper files for reproducible review."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Any
from zipfile import ZIP_STORED, ZipFile

from exceptions import (
    RequestInvalidException,
    ResourceConflictException,
    ResourceNotFoundException,
)

_SOURCE_ARCHIVE_MAX_MIB = 256
_SOURCE_ARCHIVE_MAX_BYTES = _SOURCE_ARCHIVE_MAX_MIB * 1024 * 1024


class DocumentSourceUnavailableError(ResourceConflictException):
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
        super().__init__(
            message,
            data={
                "code": code,
                "collection_id": collection_id,
                "document_id": document_id,
            },
        )


class CollectionSourceArchiveError(ResourceConflictException):
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
        super().__init__(
            message,
            data={
                "code": code,
                "collection_id": collection_id,
                "document_id": document_id,
            },
        )


from application.source import collection_service


async def build_source_archive(
    collection_id: str,
    document_ids: list[str],
    *,
    user_id: str,
) -> dict[str, Any]:
    """Build a bounded ZIP of original uploads for failure reproduction."""

    normalized_document_ids = document_ids
    if not normalized_document_ids or any(
        not document_id for document_id in normalized_document_ids
    ):
        raise ValueError("source archive requires at least one document_id")
    if len(normalized_document_ids) > 100:
        raise ValueError("source archive supports at most 100 document_ids")
    if len(set(normalized_document_ids)) != len(normalized_document_ids):
        raise ValueError("source archive document_ids must be unique")

    collection = await collection_service.get_collection_for_user(
        collection_id, user_id
    )
    records = collection["documents"]
    records_by_document_id = {record["document_id"]: record for record in records}
    selected_records: list[tuple[str, dict[str, Any]]] = []
    for document_id in normalized_document_ids:
        record = records_by_document_id.get(document_id)
        if record is None:
            raise ResourceNotFoundException(
                "A requested source document does not exist in this collection.",
                data={
                    "code": "collection_source_document_not_found",
                    "collection_id": collection_id,
                    "document_id": document_id,
                },
            )
        selected_records.append((document_id, record))

    selected_size_bytes = sum(
        max(int(record.get("size_bytes") or 0), 0)
        for _document_id, record in selected_records
    )
    if selected_size_bytes > _SOURCE_ARCHIVE_MAX_BYTES:
        raise RequestInvalidException(
            f"Selected source files exceed the {_SOURCE_ARCHIVE_MAX_MIB} MiB archive limit.",
            data={
                "code": "collection_source_archive_too_large",
                "collection_id": collection_id,
            },
        )

    return await asyncio.to_thread(
        _write_source_archive,
        collection_id,
        selected_records,
    )


async def resolve_document_source_file(
    collection_id: str,
    document_id: str,
    *,
    user_id: str,
    source_filename: str | None = None,
) -> dict[str, Any]:
    collection = await collection_service.get_collection_for_user(
        collection_id, user_id
    )
    document_key = document_id
    if not document_key:
        raise DocumentSourceUnavailableError(collection_id, document_key)

    match_keys = _source_match_keys(document_key, source_filename)
    document_matches = [
        record
        for record in collection["documents"]
        if _source_file_record_matches(record, match_keys)
    ]
    if len(document_matches) == 1:
        return _build_source_file_payload(
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
    raise ResourceNotFoundException(
        "Document not found in this collection.",
        data={
            "code": "document_not_found",
            "collection_id": collection_id,
            "document_id": document_key,
        },
    )


def _write_source_archive(
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
                    source = _build_source_file_payload(
                        collection_id=collection_id,
                        document_id=document_id,
                        record=record,
                    )
                except DocumentSourceUnavailableError as exc:
                    raise CollectionSourceArchiveError(
                        collection_id,
                        code=_source_archive_error_code(exc.data["code"]),
                        message=exc.message,
                        document_id=document_id,
                    ) from exc

                archive_path = (
                    f"sources/{position:03d}-"
                    f"{_safe_archive_filename(source['filename'])}"
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
        "filename": _safe_archive_filename(f"collection-{collection_id}-sources.zip"),
    }


def _source_file_record_matches(
    record: dict[str, Any],
    match_keys: set[str],
) -> bool:
    candidates = (
        record.get("document_id"),
        record.get("original_filename"),
        record.get("stored_filename"),
        record.get("storage_key"),
        Path(record.get("storage_key") or "").name,
    )
    return any(_source_match_value(candidate) in match_keys for candidate in candidates)


def _source_match_keys(
    document_id: str,
    source_filename: str | None,
) -> set[str]:
    keys = {
        _source_match_value(document_id),
        _source_match_value(source_filename),
        _source_match_value(Path(source_filename or "").name),
    }
    return {key for key in keys if key}


def _source_match_value(value: str | None) -> str:
    return (value or "").strip()


def _build_source_file_payload(
    *,
    collection_id: str,
    document_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    storage_key = record.get("storage_key")
    expected_sha256 = record.get("sha256")
    if not storage_key or not expected_sha256:
        raise DocumentSourceUnavailableError(collection_id, document_id)
    stored_filename = record.get("stored_filename")
    if not stored_filename or storage_key != _input_storage_key(
        collection_id, stored_filename
    ):
        raise DocumentSourceUnavailableError(
            collection_id,
            document_id,
            code="document_source_path_invalid",
            message="The stored source file path is not safe to serve.",
        )
    try:
        content = collection_service.object_store.read(storage_key, expected_sha256)
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
        record.get("original_filename") or stored_filename or Path(storage_key).name
    )
    return {
        "content": content,
        "filename": filename,
        "media_type": record.get("media_type"),
        "source_document_id": document_id,
    }


def _input_storage_key(collection_id: str, stored_filename: str) -> str:
    return f"{collection_id}/input/{stored_filename}"


def _safe_archive_filename(value: str) -> str:
    filename = PurePosixPath(value.replace("\\", "/")).name
    filename = "".join(
        "_" if ord(character) < 32 or character in '<>:"|?*' else character
        for character in filename
    ).strip(" .")
    return filename or "source.bin"


def _source_archive_error_code(document_source_code: str) -> str:
    return {
        "document_source_path_invalid": "collection_source_path_invalid",
        "document_source_integrity_failed": "collection_source_integrity_failed",
    }.get(document_source_code, "collection_source_file_unavailable")


__all__ = [
    "CollectionSourceArchiveError",
    "DocumentSourceUnavailableError",
    "build_source_archive",
    "resolve_document_source_file",
]
