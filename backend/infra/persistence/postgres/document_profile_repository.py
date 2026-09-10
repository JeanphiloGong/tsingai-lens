"""PostgreSQL persistence for current document profiles."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import DocumentProfile
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_preparation import DocumentPreparationRow


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
            row = await session.get(DocumentPreparationRow, profile.document_id)
            if row is None:
                now = datetime.now(timezone.utc)
                session.add(
                    DocumentPreparationRow(
                        document_id=profile.document_id,
                        profile_json=_profile_payload(profile),
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            row.profile_json = _profile_payload(profile)
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
            return _from_row(row) if row is not None and row.profile_json else None

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
            return tuple(_from_row(row) for row in rows if row.profile_json)


def _profile_payload(profile: DocumentProfile) -> dict[str, object]:
    return profile.to_record()


def _from_row(row: DocumentPreparationRow) -> DocumentProfile:
    payload = dict(row.profile_json or {})
    payload.setdefault("document_id", row.document_id)
    return DocumentProfile.from_mapping(payload)


__all__ = ["PostgresDocumentProfileRepository"]
