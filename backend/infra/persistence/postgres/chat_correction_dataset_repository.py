"""PostgreSQL persistence for immutable Chat correction dataset manifests."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.evaluation import ChatCorrectionDatasetManifest
from infra.persistence.postgres.models.chat_correction_dataset import (
    ChatCorrectionDatasetManifestRow,
)


class PostgresChatCorrectionDatasetRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save_manifest(
        self, manifest: ChatCorrectionDatasetManifest
    ) -> ChatCorrectionDatasetManifest:
        async with self.session_factory.begin() as session:
            existing = await session.get(
                ChatCorrectionDatasetManifestRow,
                manifest.dataset_id,
                with_for_update=True,
            )
            if existing is None:
                existing = await session.scalar(
                    select(ChatCorrectionDatasetManifestRow).where(
                        ChatCorrectionDatasetManifestRow.owner_id == manifest.owner_id,
                        ChatCorrectionDatasetManifestRow.manifest_digest == manifest.digest,
                    )
                )
            if existing is not None:
                saved = _manifest_record(existing)
                if (
                    saved.owner_id != manifest.owner_id
                    or saved.collection_id != manifest.collection_id
                    or saved.digest != manifest.digest
                ):
                    raise ValueError("dataset identity cannot be reassigned")
                return saved
            row = ChatCorrectionDatasetManifestRow(
                dataset_id=manifest.dataset_id,
                owner_id=manifest.owner_id,
                collection_id=manifest.collection_id,
                manifest=manifest.to_record(),
                manifest_digest=manifest.digest,
                provenance_digest=manifest.provenance_digest,
                row_count=manifest.row_count,
                excluded_count=manifest.excluded_count,
                created_at=_datetime(manifest.created_at),
            )
            session.add(row)
            await session.flush()
            return _manifest_record(row)

    async def read_manifest_for_user(
        self, dataset_id: str, user_id: str
    ) -> ChatCorrectionDatasetManifest | None:
        async with self.session_factory() as session:
            row = await session.get(ChatCorrectionDatasetManifestRow, dataset_id)
            if row is None or row.owner_id != user_id:
                return None
            return _manifest_record(row)

    async def list_manifests_for_user(
        self,
        user_id: str,
        *,
        collection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatCorrectionDatasetManifest, ...]:
        statement = (
            select(ChatCorrectionDatasetManifestRow)
            .where(ChatCorrectionDatasetManifestRow.owner_id == user_id)
            .order_by(
                ChatCorrectionDatasetManifestRow.created_at,
                ChatCorrectionDatasetManifestRow.dataset_id,
            )
            .offset(max(0, int(offset)))
            .limit(max(1, min(int(limit), 200)))
        )
        if collection_id:
            statement = statement.where(
                ChatCorrectionDatasetManifestRow.collection_id == collection_id
            )
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_manifest_record(row) for row in rows)


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _manifest_record(row: ChatCorrectionDatasetManifestRow) -> ChatCorrectionDatasetManifest:
    payload = dict(row.manifest or {})
    payload.setdefault("dataset_id", row.dataset_id)
    payload.setdefault("owner_id", row.owner_id)
    payload.setdefault("collection_id", row.collection_id)
    payload.setdefault("digest", row.manifest_digest)
    payload.setdefault("created_at", _iso(row.created_at))
    return ChatCorrectionDatasetManifest.from_mapping(payload)


__all__ = ["PostgresChatCorrectionDatasetRepository"]
