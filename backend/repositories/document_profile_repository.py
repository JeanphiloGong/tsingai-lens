"""PostgreSQL repository for document profile."""

from __future__ import annotations

from contextlib import nullcontext
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from domain.core.document_profile import DocumentProfile
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.workspace import (
    DocumentORM,
    DocumentPreparationORM,
)
from sqlalchemy import select


class DocumentProfileRepository:
    async def replace(
        self,
        workspace_id: str,
        profile: DocumentProfile,
        *,
        db: AsyncSession | None = None,
    ) -> None:
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
        async with AsyncSessionLocal.begin() if db is None else nullcontext(db) as db:
            document = await db.get(DocumentORM, profile.document_id, with_for_update=True)
            if document is None or document.workspace_id != workspace_id:
                raise FileNotFoundError(
                    f"workspace document not found: {workspace_id}/{profile.document_id}"
                )
            row = await db.get(DocumentPreparationORM, profile.document_id, with_for_update=True)
            if row is None:
                now = datetime.now(timezone.utc)
                db.add(
                    DocumentPreparationORM(
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
        workspace_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
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

    async def list_workspace(
        self,
        workspace_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        if document_ids == ():
            return ()
        async with AsyncSessionLocal() as db:
            statement = (
                select(DocumentPreparationORM)
                .join(
                    DocumentORM,
                    DocumentORM.document_id == DocumentPreparationORM.document_id,
                )
                .where(DocumentORM.workspace_id == workspace_id)
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentPreparationORM.document_id.in_(document_ids)
                )
            rows = await db.scalars(
                statement.order_by(DocumentPreparationORM.document_id)
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


DocumentProfileRepo = DocumentProfileRepository()
