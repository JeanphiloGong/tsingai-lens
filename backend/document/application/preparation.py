"""Document-owned preparation steps used by Pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from document.domain import DocumentProfile
from document.repositories.document_repository import DocumentRepository
from document.repositories.profile_repository import ProfileRepository
from document.repositories.source_repository import SourceRepository


@dataclass(frozen=True)
class PreparationResult:
    document_id: str
    source_fingerprint: str
    profile: DocumentProfile | None = None


class DocumentPreparation:
    def __init__(
        self,
        repository: DocumentRepository,
        artifacts: SourceRepository,
        profiles: ProfileRepository,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.profiles = profiles

    async def parse_source(
        self,
        *,
        workspace_id: str,
        document_id: str,
        parsed: Any,
        db: AsyncSession | None = None,
    ) -> PreparationResult:
        if parsed.document_id != document_id:
            raise ValueError("source document identity mismatch")
        source_fingerprint = str(parsed.metadata.get("source_fingerprint") or "")
        if not source_fingerprint:
            raise ValueError("source fingerprint is required")
        await self.artifacts.replace_document(workspace_id, parsed, db=db)
        return PreparationResult(
            document_id=document_id,
            source_fingerprint=source_fingerprint,
        )

    async def save_profile(
        self,
        *,
        workspace_id: str,
        document_id: str,
        source_version: str,
        profile: DocumentProfile,
        db: AsyncSession,
    ) -> PreparationResult:
        if profile.document_id != document_id:
            raise ValueError("profile document identity mismatch")
        if profile.source_fingerprint != source_version:
            raise ValueError("profile source version mismatch")
        source = await self.repository.read(
            workspace_id=workspace_id,
            document_id=document_id,
            source_version=source_version,
            db=db,
        )
        await self.profiles.replace(workspace_id, profile, db=db)
        return PreparationResult(
            document_id=source.document_id,
            source_fingerprint=source_version,
            profile=profile,
        )
