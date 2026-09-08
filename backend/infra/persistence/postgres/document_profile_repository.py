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

    async def replace(self, profile: DocumentProfile) -> None:
        async with self.session_factory.begin() as session:
            document = await session.get(Document, profile.document_id)
            if document is None or document.collection_id != profile.collection_id:
                raise FileNotFoundError(
                    "collection document not found: "
                    f"{profile.collection_id}/{profile.document_id}"
                )
            row = await session.get(DocumentProfileRow, profile.document_id)
            if row is None:
                session.add(_to_row(profile))
                return
            row.collection_id = profile.collection_id
            row.title = profile.title
            row.source_filename = profile.source_filename
            row.doc_type = profile.doc_type
            row.parsing_warnings = list(profile.parsing_warnings)
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
            row = await session.get(DocumentProfileRow, document_id)
            if row is None or row.collection_id != collection_id:
                return None
            return _from_row(row)

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        if document_ids == ():
            return ()
        async with self.session_factory() as session:
            statement = select(DocumentProfileRow).where(
                DocumentProfileRow.collection_id == collection_id
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
        collection_id=profile.collection_id,
        title=profile.title,
        source_filename=profile.source_filename,
        doc_type=profile.doc_type,
        parsing_warnings=list(profile.parsing_warnings),
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
            "collection_id": row.collection_id,
            "title": row.title,
            "source_filename": row.source_filename,
            "doc_type": row.doc_type,
            "parsing_warnings": row.parsing_warnings,
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
