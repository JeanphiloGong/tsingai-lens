"""Document identity and preparation repository."""

from __future__ import annotations

from contextlib import nullcontext

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document.domain import Document, SourceDocument
from document.repositories.source_repository import SourceRepository
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.workspace import (
    DocumentORM,
    DocumentPreparationORM,
)


class DocumentNotFound(FileNotFoundError):
    """The Document is absent or outside the requested Workspace."""


class DocumentRepository:
    def __init__(self, source_repository: SourceRepository | None = None) -> None:
        self.sources = source_repository or SourceRepository()

    async def read(
        self,
        *,
        workspace_id: str,
        document_id: str,
        source_version: str | None = None,
        db: AsyncSession | None = None,
    ) -> SourceDocument:
        context = AsyncSessionLocal() if db is None else nullcontext(db)
        async with context as session:
            document = await session.scalar(
                select(DocumentORM).where(
                    DocumentORM.document_id == document_id,
                    DocumentORM.workspace_id == workspace_id,
                )
            )
            if document is None:
                raise DocumentNotFound(document_id)
            preparation = await session.get(DocumentPreparationORM, document_id)
            if preparation is None or not preparation.artifact_json:
                raise FileNotFoundError("document_sources_not_ready")
            current_version = preparation.source_fingerprint
            if source_version is not None and source_version != current_version:
                raise ValueError("source_version_changed")
            source = await self.sources.read_document_in_session(
                workspace_id,
                document_id,
                db=session,
            )
            if source is None:
                raise FileNotFoundError("document_sources_not_ready")
            return source

    async def read_document(
        self,
        *,
        workspace_id: str,
        document_id: str,
        db: AsyncSession | None = None,
    ) -> Document:
        context = AsyncSessionLocal() if db is None else nullcontext(db)
        async with context as session:
            row = await session.scalar(
                select(DocumentORM).where(
                    DocumentORM.document_id == document_id,
                    DocumentORM.workspace_id == workspace_id,
                )
            )
            if row is None:
                raise DocumentNotFound(document_id)
            return Document(
                document_id=row.document_id,
                filename=row.filename,
                sha256=row.sha256,
                media_type=row.media_type,
                size_bytes=row.size_bytes,
            )

    async def list(
        self,
        *,
        workspace_id: str,
        document_ids: tuple[str, ...] | None,
    ) -> tuple[SourceDocument, ...]:
        return await self.sources.list(
            workspace_id=workspace_id,
            document_ids=document_ids,
        )


DocumentRepo = DocumentRepository()

__all__ = ["DocumentNotFound", "DocumentRepository", "DocumentRepo"]
