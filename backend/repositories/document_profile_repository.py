"""PostgreSQL repository for document profile."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core.document_profile import DocumentProfile
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)


class DocumentProfileRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(self, collection_id: str, profile: DocumentProfile) -> None:
        next_profile = {
            "document_id": profile.document_id,
            "title": profile.title,
            "doc_type": profile.doc_type,
            "profile_warnings": list(profile.profile_warnings),
            "confidence": round(profile.confidence, 2),
            "profile_status": profile.profile_status,
            "source_fingerprint": profile.source_fingerprint,
            "profile_version": profile.profile_version,
            "profile_fingerprint": profile.profile_fingerprint,
            "generated_at": profile.generated_at,
        }
        async with self.session_factory.begin() as session:
            document = await session.get(Document, profile.document_id)
            if document is None or document.collection_id != collection_id:
                raise FileNotFoundError(
                    "collection document not found: "
                    f"{collection_id}/{profile.document_id}"
                )
            row = await session.get(DocumentPreparationRow, profile.document_id)
            if row is None:
                now = datetime.now(timezone.utc)
                session.add(
                    DocumentPreparationRow(
                        document_id=profile.document_id,
                        profile_json=next_profile,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            row.profile_json = next_profile
            row.updated_at = datetime.now(timezone.utc)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(
                    DocumentPreparationRow.document_id == document_id,
                    Document.collection_id == collection_id,
                )
            )
            if row is None or not row.profile_json:
                return None
            payload = row.profile_json
            profile = DocumentProfile(
                document_id=row.document_id,
                title=payload["title"],
                doc_type=payload["doc_type"],
                profile_warnings=tuple(payload["profile_warnings"]),
                confidence=payload["confidence"],
                profile_status=payload["profile_status"],
                source_fingerprint=payload["source_fingerprint"],
                profile_version=payload["profile_version"],
                profile_fingerprint=payload["profile_fingerprint"],
                generated_at=payload["generated_at"],
            )
            return profile

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        if document_ids == ():
            return ()
        async with self.session_factory() as session:
            statement = (
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(Document.collection_id == collection_id)
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentPreparationRow.document_id.in_(document_ids)
                )
            rows = await session.scalars(
                statement.order_by(DocumentPreparationRow.document_id)
            )
            profiles = []
            for row in rows:
                if not row.profile_json:
                    continue
                payload = row.profile_json
                profile = DocumentProfile(
                    document_id=row.document_id,
                    title=payload["title"],
                    doc_type=payload["doc_type"],
                    profile_warnings=tuple(payload["profile_warnings"]),
                    confidence=payload["confidence"],
                    profile_status=payload["profile_status"],
                    source_fingerprint=payload["source_fingerprint"],
                    profile_version=payload["profile_version"],
                    profile_fingerprint=payload["profile_fingerprint"],
                    generated_at=payload["generated_at"],
                )
                profiles.append(profile)
            return tuple(profiles)


__all__ = ["DocumentProfileRepository"]
