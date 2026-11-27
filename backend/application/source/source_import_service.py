"""Validate, store, and register an uploaded Document in a Workspace."""

from __future__ import annotations

from infra.persistence.file import object_store as object_store_module

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from document.domain.document import Document
from exceptions import RequestInvalidException, ResourceConflictException
from infra.source.ingestion.upload_validation import validate_upload
from repositories.workspace_repository import (
    DocumentContentAlreadyExists,
    StoredDocument,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


from application.source import workspace_service
from repositories.workspace_repository import WorkspaceRepo


async def add_document(
    workspace_id: str,
    filename: str,
    content: bytes,
    media_type: str | None = None,
    *,
    user_id: str,
    reuse_existing: bool = False,
) -> StoredDocument:
    object_store = object_store_module.Store
    await workspace_service.get_workspace_for_user(workspace_id, user_id)

    filename = Path(filename or "upload.bin").name or "upload.bin"
    media_type = (str(media_type).strip() or None) if media_type else None
    try:
        await asyncio.to_thread(validate_upload, filename, content, media_type)
    except ValueError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "upload_invalid"}
        ) from exc

    document_id = f"doc_{uuid4().hex[:12]}"
    storage_key = f"{workspace_id}/input/{document_id}"
    digest = sha256(content).hexdigest()
    now = _now_iso()
    record = StoredDocument(
        document=Document(
            document_id=document_id,
            filename=filename,
            sha256=digest,
            media_type=media_type,
            size_bytes=len(content),
        ),
        storage_key=storage_key,
        status="stored",
        parser_version=None,
        document_analysis_version=None,
        source_fingerprint=None,
        profile_fingerprint=None,
        preparation_fingerprint=None,
        created_at=now,
        updated_at=now,
    )
    object_store.write(storage_key, content, digest)
    try:
        await WorkspaceRepo.add_documents(
            workspace_id,
            (record,),
            updated_at=_now_iso(),
        )
    except Exception as exc:
        try:
            current = await WorkspaceRepo.read_workspace(workspace_id)
        except Exception:
            current = None
        documents = current.documents if current is not None else ()
        # Registration may have committed before the caller received an error.
        if not any(existing.storage_key == storage_key for existing in documents):
            object_store.delete(storage_key)
        if reuse_existing and isinstance(exc, DocumentContentAlreadyExists):
            for existing in documents:
                if existing.document.sha256 == digest:
                    return existing
        if isinstance(exc, DocumentContentAlreadyExists):
            raise ResourceConflictException(
                "Document content already exists in this workspace.",
                data={
                    "code": "document_content_already_exists",
                    "workspace_id": workspace_id,
                },
            ) from exc
        raise
    return record


__all__ = ["add_document"]
