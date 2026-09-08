"""PostgreSQL persistence for current document profiles."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import DocumentProfile
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_profile import DocumentProfileRow


class PostgresDocumentProfileRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(self, collection_id: str, profile: DocumentProfile) -> None:
        async with self.session_factory.begin() as session:
            document = await session.get(Document, profile.document_id)
            if document is None or document.collection_id != collection_id:
                raise FileNotFoundError(
                    "collection document not found: "
                    f"{collection_id}/{profile.document_id}"
                )
            row = await session.get(DocumentProfileRow, profile.document_id)
            if row is None:
                session.add(_to_row(profile))
                return
            row.title = profile.title
            row.doc_type = profile.doc_type
            row.profile_warnings = list(profile.profile_warnings)
            row.confidence = profile.confidence
            if profile.source_fingerprint is not None:
                row.source_fingerprint = profile.source_fingerprint
            if profile.profile_version is not None:
                row.profile_version = profile.profile_version
            if profile.profile_fingerprint is not None:
                row.profile_fingerprint = profile.profile_fingerprint
            if profile.generated_at is not None:
                row.generated_at = _datetime(profile.generated_at)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(DocumentProfileRow)
                .join(Document, Document.document_id == DocumentProfileRow.document_id)
                .where(
                    DocumentProfileRow.document_id == document_id,
                    Document.collection_id == collection_id,
                )
            )
            return _from_row(row) if row is not None else None

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        if document_ids == ():
            return ()
        async with self.session_factory() as session:
            statement = (
                select(DocumentProfileRow)
                .join(Document, Document.document_id == DocumentProfileRow.document_id)
                .where(Document.collection_id == collection_id)
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentProfileRow.document_id.in_(document_ids)
                )
            rows = await session.scalars(
                statement.order_by(DocumentProfileRow.document_id)
            )
            return tuple(_from_row(row) for row in rows)


def _to_row(profile: DocumentProfile) -> DocumentProfileRow:
    return DocumentProfileRow(
        document_id=profile.document_id,
        title=profile.title,
        doc_type=profile.doc_type,
        profile_warnings=list(profile.profile_warnings),
        confidence=profile.confidence,
        source_fingerprint=profile.source_fingerprint,
        profile_version=profile.profile_version,
        profile_fingerprint=profile.profile_fingerprint,
        generated_at=_datetime(profile.generated_at) if profile.generated_at else None,
    )


def _from_row(row: DocumentProfileRow) -> DocumentProfile:
    return DocumentProfile.from_mapping(
        {
            "document_id": row.document_id,
            "title": row.title,
            "doc_type": row.doc_type,
            "profile_warnings": row.profile_warnings,
            "confidence": row.confidence,
            "source_fingerprint": row.source_fingerprint,
            "profile_version": row.profile_version,
            "profile_fingerprint": row.profile_fingerprint,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        }
    )


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


__all__ = ["PostgresDocumentProfileRepository"]
