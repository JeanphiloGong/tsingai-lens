"""Validate, store, and register an uploaded Document in a Collection."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from application.source.collection_service import document_details
from domain.source import Document
from exceptions import RequestInvalidException, ResourceConflictException
from infra.source.ingestion.upload_validation import validate_upload
from repositories.collection_repository import (
    DocumentContentAlreadyExists,
    StoredDocument,
)
from repositories.object_store import ObjectStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


from application.source import collection_service
from repositories.collection_repository import CollectionRepo


async def add_document(
    collection_id: str,
    filename: str,
    content: bytes,
    media_type: str | None = None,
    *,
    user_id: str,
    reuse_existing: bool = False,
    object_store: ObjectStore,
) -> dict:
    await collection_service.get_collection_for_user(collection_id, user_id)

    filename = Path(filename or "upload.bin").name or "upload.bin"
    media_type = (str(media_type).strip() or None) if media_type else None
    try:
        await asyncio.to_thread(validate_upload, filename, content, media_type)
    except ValueError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "upload_invalid"}
        ) from exc

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
    object_store.write(storage_key, content, digest)
    try:
        await CollectionRepo.add_documents(
            collection_id,
            (record,),
            updated_at=_now_iso(),
        )
    except Exception as exc:
        try:
            current = await CollectionRepo.read_collection(collection_id)
        except Exception:
            current = None
        documents = current.documents if current is not None else ()
        # Registration may have committed before the caller received an error.
        if not any(existing.storage_key == storage_key for existing in documents):
            object_store.delete(storage_key)
        if reuse_existing and isinstance(exc, DocumentContentAlreadyExists):
            for existing in documents:
                if existing.document.sha256 == digest:
                    return document_details(existing)
        if isinstance(exc, DocumentContentAlreadyExists):
            raise ResourceConflictException(
                "Document content already exists in this collection.",
                data={
                    "code": "document_content_already_exists",
                    "collection_id": collection_id,
                },
            ) from exc
        raise
    return document_details(record)


__all__ = ["add_document"]
