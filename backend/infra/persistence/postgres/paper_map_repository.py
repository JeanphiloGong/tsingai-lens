"""PostgreSQL persistence for current document Paper Maps."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import PaperResearchMap
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.paper_map import PaperMapRow


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
            row = await session.get(PaperMapRow, paper_map.document_id)
            if row is None:
                session.add(_to_row(paper_map))
                return
            _replace_row(row, paper_map)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperResearchMap | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(PaperMapRow)
                .join(Document, Document.document_id == PaperMapRow.document_id)
                .where(
                    PaperMapRow.document_id == document_id,
                    Document.collection_id == collection_id,
                )
            )
            return _from_row(row) if row is not None else None

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        if document_ids == ():
            return ()
        async with self.session_factory() as session:
            statement = (
                select(PaperMapRow)
                .join(Document, Document.document_id == PaperMapRow.document_id)
                .where(Document.collection_id == collection_id)
            )
            if document_ids is not None:
                statement = statement.where(PaperMapRow.document_id.in_(document_ids))
            rows = await session.scalars(statement.order_by(PaperMapRow.document_id))
            return tuple(_from_row(row) for row in rows)


def _payload(paper_map: PaperResearchMap) -> dict[str, object]:
    payload = paper_map.to_record()
    for field_name in (
        "document_id",
        "input_fingerprint",
        "map_version",
        "generated_at",
    ):
        payload.pop(field_name, None)
    return payload


def _to_row(paper_map: PaperResearchMap) -> PaperMapRow:
    return PaperMapRow(
        document_id=paper_map.document_id,
        input_fingerprint=paper_map.input_fingerprint,
        map_version=paper_map.map_version,
        generated_at=(
            _datetime(paper_map.generated_at) if paper_map.generated_at else None
        ),
        payload=_payload(paper_map),
    )


def _replace_row(row: PaperMapRow, paper_map: PaperResearchMap) -> None:
    row.input_fingerprint = paper_map.input_fingerprint
    row.map_version = paper_map.map_version
    row.generated_at = (
        _datetime(paper_map.generated_at) if paper_map.generated_at else None
    )
    row.payload = _payload(paper_map)


def _from_row(row: PaperMapRow) -> PaperResearchMap:
    return PaperResearchMap.from_mapping(
        {
            **row.payload,
            "document_id": row.document_id,
            "input_fingerprint": row.input_fingerprint,
            "map_version": row.map_version,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        }
    )


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


__all__ = ["PostgresPaperMapRepository"]
