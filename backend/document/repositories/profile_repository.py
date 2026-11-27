"""PostgreSQL persistence for the Document navigation Profile."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document.domain import DocumentProfile
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.workspace import (
    DocumentORM,
    DocumentPreparationORM,
)


class ProfileRepository:
    async def replace(
        self,
        workspace_id: str,
        profile: DocumentProfile,
        *,
        db: AsyncSession | None = None,
    ) -> None:
        payload = {
            "document_id": profile.document_id,
            "doc_type": profile.doc_type,
            "description": profile.description,
            "source_fingerprint": profile.source_fingerprint,
            "profile_fingerprint": profile.profile_fingerprint,
            "profile_version": profile.profile_version,
            "generated_at": profile.generated_at,
        }
        context = AsyncSessionLocal.begin() if db is None else nullcontext(db)
        async with context as session:
            document = await session.get(
                DocumentORM,
                profile.document_id,
                with_for_update=True,
            )
            if document is None or document.workspace_id != workspace_id:
                raise FileNotFoundError("document_not_found")
            row = await session.get(
                DocumentPreparationORM,
                profile.document_id,
                with_for_update=True,
            )
            now = datetime.now(timezone.utc)
            if row is None:
                session.add(
                    DocumentPreparationORM(
                        document_id=profile.document_id,
                        profile_json=payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            row.profile_json = payload
            row.updated_at = now

    async def read(
        self,
        workspace_id: str,
        document_id: str,
        *,
        db: AsyncSession | None = None,
    ) -> DocumentProfile | None:
        context = AsyncSessionLocal() if db is None else nullcontext(db)
        async with context as session:
            row = await session.scalar(
                select(DocumentPreparationORM)
                .join(
                    DocumentORM,
                    DocumentORM.document_id == DocumentPreparationORM.document_id,
                )
                .where(
                    DocumentPreparationORM.document_id == document_id,
                    DocumentORM.workspace_id == workspace_id,
                )
            )
            return _profile_from_row(row)

    async def list_workspace(
        self,
        workspace_id: str,
        document_ids: tuple[str, ...] | None = None,
        *,
        db: AsyncSession | None = None,
    ) -> tuple[DocumentProfile, ...]:
        if document_ids == ():
            return ()
        context = AsyncSessionLocal() if db is None else nullcontext(db)
        async with context as session:
            statement = (
                select(DocumentPreparationORM)
                .join(
                    DocumentORM,
                    DocumentORM.document_id == DocumentPreparationORM.document_id,
                )
                .where(DocumentORM.workspace_id == workspace_id)
                .order_by(DocumentPreparationORM.document_id)
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentPreparationORM.document_id.in_(document_ids)
                )
            rows = await session.scalars(statement)
            return tuple(
                profile
                for row in rows
                if (profile := _profile_from_row(row)) is not None
            )


def _profile_from_row(row: DocumentPreparationORM | None) -> DocumentProfile | None:
    if row is None or not row.profile_json:
        return None
    payload = row.profile_json
    return DocumentProfile(
        document_id=row.document_id,
        doc_type=payload["doc_type"],
        description=payload["description"],
        source_fingerprint=payload["source_fingerprint"],
        profile_fingerprint=payload["profile_fingerprint"],
        profile_version=payload["profile_version"],
        generated_at=payload["generated_at"],
    )


ProfileRepo = ProfileRepository()

__all__ = ["ProfileRepository", "ProfileRepo"]
