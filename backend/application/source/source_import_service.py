"""Validate, store, and register an uploaded Document in a Collection."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from application.repositories.collection_repository import (
    CollectionRepository,
    StoredDocument,
)
from application.repositories.object_store import ObjectStore
from application.source.collection_service import document_details
from domain.source import Document
from infra.source.ingestion.upload_validation import validate_upload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceImportService:
    """Own original-file storage and Document registration."""

    def __init__(
        self,
        repository: CollectionRepository,
        object_store: ObjectStore,
    ) -> None:
        self.repository = repository
        self.object_store = object_store

    async def add_document(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
        *,
        reuse_existing: bool = False,
    ) -> dict:
        if await self.repository.read_collection(collection_id) is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")

        filename = Path(filename or "upload.bin").name or "upload.bin"
        media_type = (str(media_type).strip() or None) if media_type else None
        await asyncio.to_thread(validate_upload, filename, content, media_type)

        path = Path(filename)
        stored_filename = f"{uuid4().hex}_{path.stem}{path.suffix.lower() or '.bin'}"
        storage_key = f"{collection_id}/input/{stored_filename}"
        digest = sha256(content).hexdigest()
        record = StoredDocument(
            document=Document(
                document_id=f"doc_{uuid4().hex[:12]}",
                original_filename=filename,
                sha256=digest,
                media_type=media_type,
                status="stored",
                size_bytes=len(content),
            ),
            stored_filename=stored_filename,
            storage_key=storage_key,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self.object_store.write(storage_key, content, digest)
        try:
            await self.repository.add_documents(
                collection_id, (record,), updated_at=_now_iso(),
            )
        except Exception as exc:
            try:
                current = await self.repository.read_collection(collection_id)
            except Exception:
                current = None
            documents = current.documents if current is not None else ()
            # Registration may have committed before the caller received an error.
            if not any(existing.storage_key == storage_key for existing in documents):
                self.object_store.delete(storage_key)
            if (
                reuse_existing
                and isinstance(exc, ValueError)
                and str(exc) == "document content already exists in collection"
            ):
                for existing in documents:
                    if existing.document.sha256 == digest:
                        return document_details(existing)
            raise
        return document_details(record)


__all__ = ["SourceImportService"]
