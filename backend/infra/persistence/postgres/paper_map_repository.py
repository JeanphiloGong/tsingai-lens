"""PostgreSQL persistence for current document Paper Maps."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import PaperSkim
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.paper_map import PaperMapRow


class PostgresPaperMapRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(self, collection_id: str, paper_map: PaperSkim) -> None:
        async with self.session_factory.begin() as session:
            document = await session.get(Document, paper_map.document_id)
            if document is None or document.collection_id != collection_id:
                raise FileNotFoundError(
                    f"collection document not found: {collection_id}/{paper_map.document_id}"
                )
            row = await session.get(PaperMapRow, paper_map.document_id)
            if row is None:
                session.add(
                    PaperMapRow(
                        document_id=paper_map.document_id,
                        collection_id=collection_id,
                        payload=paper_map.to_record(),
                    )
                )
                return
            row.collection_id = collection_id
            row.payload = paper_map.to_record()

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperSkim | None:
        async with self.session_factory() as session:
            row = await session.get(PaperMapRow, document_id)
            if row is None or row.collection_id != collection_id:
                return None
            return PaperSkim.from_mapping(row.payload)

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperSkim, ...]:
        if document_ids == ():
            return ()
        async with self.session_factory() as session:
            statement = select(PaperMapRow).where(
                PaperMapRow.collection_id == collection_id
            )
            if document_ids is not None:
                statement = statement.where(PaperMapRow.document_id.in_(document_ids))
            rows = await session.scalars(statement.order_by(PaperMapRow.document_id))
            return tuple(PaperSkim.from_mapping(row.payload) for row in rows)


__all__ = ["PostgresPaperMapRepository"]
