"""PostgreSQL persistence for current document Paper Maps."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import PaperResearchMap
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_preparation import DocumentPreparationRow


class PostgresPaperMapRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(self, collection_id: str, paper_map: PaperResearchMap) -> None:
        async with self.session_factory.begin() as session:
            document = await session.get(Document, paper_map.document_id)
            if document is None or document.collection_id != collection_id:
                raise FileNotFoundError(
                    f"collection document not found: {collection_id}/{paper_map.document_id}"
                )
            row = await session.scalar(
                select(DocumentPreparationRow)
                .join(
                    Document,
                    Document.document_id == DocumentPreparationRow.document_id,
                )
                .where(
                    DocumentPreparationRow.document_id == paper_map.document_id,
                    Document.collection_id == collection_id,
                )
            )
            if row is None or not row.profile_json:
                raise FileNotFoundError(
                    f"document profile not found: {collection_id}/{paper_map.document_id}"
                )
            _replace_row(row, paper_map)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperResearchMap | None:
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
            return _from_row(row) if row is not None and row.paper_map_payload else None

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperResearchMap, ...]:
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
            return tuple(_from_row(row) for row in rows if row.paper_map_payload)


def _payload(paper_map: PaperResearchMap) -> dict[str, object]:
    return paper_map.to_record()


def _replace_row(row: DocumentPreparationRow, paper_map: PaperResearchMap) -> None:
    row.paper_map_payload = _payload(paper_map)


def _from_row(row: DocumentPreparationRow) -> PaperResearchMap:
    payload = dict(row.paper_map_payload or {})
    payload.setdefault("document_id", row.document_id)
    return PaperResearchMap.from_mapping(payload)


__all__ = ["PostgresPaperMapRepository"]
