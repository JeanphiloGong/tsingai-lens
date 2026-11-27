"""PostgreSQL repository for workspace."""

from __future__ import annotations

from contextlib import nullcontext

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from domain.source import Workspace as WorkspaceAggregate
from domain.source import Document as DocumentAggregate
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.workspace import (
    WorkspaceORM,
    DocumentORM,
    DocumentPreparationORM,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class StoredDocument:
    document: DocumentAggregate
    storage_key: str
    created_at: str
    updated_at: str | None = None
    status: str = "stored"
    parser_version: str | None = None
    document_analysis_version: str | None = None
    source_fingerprint: str | None = None
    profile_fingerprint: str | None = None
    preparation_fingerprint: str | None = None


@dataclass(frozen=True)
class StoredWorkspace:
    workspace: WorkspaceAggregate
    created_at: str
    updated_at: str
    documents: tuple[StoredDocument, ...] = ()


@dataclass(frozen=True)
class WorkspaceDocumentSummary:
    document_id: str
    filename: str
    media_type: str | None
    status: str
    size_bytes: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceSummary:
    workspace_id: str
    name: str
    description: str | None
    status: str
    created_at: str
    updated_at: str
    documents: tuple[WorkspaceDocumentSummary, ...]


class DocumentContentAlreadyExists(ValueError):
    """The workspace already contains the uploaded content digest."""


class WorkspaceRepository:
    async def add_workspace(self, record: StoredWorkspace) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            db.add(
                WorkspaceORM(
                    workspace_id=record.workspace.workspace_id,
                    owner_user_id=record.workspace.owner_user_id,
                    name=record.workspace.name,
                    description=record.workspace.description,
                    status=record.workspace.status,
                    created_at=_datetime(record.created_at),
                    updated_at=_datetime(record.updated_at),
                )
            )
            await db.flush()

    async def list_workspaces(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[WorkspaceSummary, ...]:
        statement = select(
            WorkspaceORM.workspace_id,
            WorkspaceORM.name,
            WorkspaceORM.description,
            WorkspaceORM.status,
            WorkspaceORM.created_at,
            WorkspaceORM.updated_at,
        ).order_by(WorkspaceORM.created_at)
        if owner_user_id is not None:
            statement = statement.where(WorkspaceORM.owner_user_id == owner_user_id)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(statement)).all()
            if not rows:
                return ()
            documents_by_workspace: dict[str, list[WorkspaceDocumentSummary]] = {
                row.workspace_id: [] for row in rows
            }
            documents = await db.execute(
                select(
                    DocumentORM.workspace_id,
                    DocumentORM.document_id,
                    DocumentORM.filename,
                    DocumentORM.media_type,
                    DocumentORM.status,
                    DocumentORM.size_bytes,
                    DocumentORM.created_at,
                    DocumentORM.updated_at,
                )
                .where(DocumentORM.workspace_id.in_(documents_by_workspace))
                .order_by(DocumentORM.document_order)
            )
            for document in documents:
                documents_by_workspace[document.workspace_id].append(
                    WorkspaceDocumentSummary(
                        document_id=document.document_id,
                        filename=document.filename,
                        media_type=document.media_type,
                        status=document.status,
                        size_bytes=document.size_bytes,
                        created_at=_iso(document.created_at),
                        updated_at=_iso(document.updated_at),
                    )
                )
            return tuple(
                WorkspaceSummary(
                    workspace_id=row.workspace_id,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    documents=tuple(documents_by_workspace[row.workspace_id]),
                )
                for row in rows
            )

    async def read_workspace(
        self,
        workspace_id: str,
    ) -> StoredWorkspace | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(WorkspaceORM, workspace_id)
            if row is None:
                return None
            return StoredWorkspace(
                workspace=WorkspaceAggregate(
                    workspace_id=row.workspace_id,
                    owner_user_id=row.owner_user_id,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                ),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                documents=await load_workspace_documents(db, workspace_id),
            )

    async def workspace_belongs_to_user(
        self, workspace_id: str, owner_user_id: str
    ) -> bool:
        statement = select(WorkspaceORM.workspace_id).where(
            WorkspaceORM.workspace_id == workspace_id,
            WorkspaceORM.owner_user_id == owner_user_id,
        )
        async with AsyncSessionLocal() as db:
            return await db.scalar(statement) is not None

    async def read_document(
        self,
        workspace_id: str,
        document_id: str,
        *,
        db: AsyncSession | None = None,
    ) -> StoredDocument | None:
        async with AsyncSessionLocal() if db is None else nullcontext(db) as db:
            row = (
                await db.execute(
                    select(DocumentORM, DocumentPreparationORM)
                    .outerjoin(
                        DocumentPreparationORM,
                        DocumentPreparationORM.document_id == DocumentORM.document_id,
                    )
                    .where(
                        DocumentORM.workspace_id == workspace_id,
                        DocumentORM.document_id == document_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            document, preparation = row
            profile = dict(preparation.profile_json or {}) if preparation else {}
            source_fingerprint = preparation.source_fingerprint if preparation else None
            profile_fingerprint = profile.get("profile_fingerprint")
            return StoredDocument(
                document=DocumentAggregate(
                    document_id=document.document_id,
                    filename=document.filename,
                    sha256=document.sha256,
                    media_type=document.media_type,
                    size_bytes=document.size_bytes,
                ),
                storage_key=document.storage_key,
                status=document.status,
                parser_version=preparation.parser_version if preparation else None,
                document_analysis_version=profile.get("profile_version"),
                source_fingerprint=source_fingerprint,
                profile_fingerprint=profile_fingerprint,
                preparation_fingerprint=profile_fingerprint or source_fingerprint,
                created_at=_iso(document.created_at),
                updated_at=_iso(document.updated_at),
            )


    async def update_workspace(self, record: StoredWorkspace) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(WorkspaceORM, record.workspace.workspace_id)
            if row is None:
                return False
            row.owner_user_id = record.workspace.owner_user_id
            row.name = record.workspace.name
            row.description = record.workspace.description
            row.status = record.workspace.status
            row.updated_at = _datetime(record.updated_at)
            return True

    async def add_documents(
        self,
        workspace_id: str,
        documents: tuple[StoredDocument, ...],
        *,
        updated_at: str,
    ) -> None:
        if not documents:
            raise ValueError("at least one document is required")
        async with AsyncSessionLocal() as db, db.begin():
            workspace = await db.get(
                WorkspaceORM,
                workspace_id,
                with_for_update=True,
            )
            if workspace is None:
                raise FileNotFoundError(f"workspace not found: {workspace_id}")
            existing_ids = set(
                await db.scalars(
                    select(DocumentORM.document_id).where(
                        DocumentORM.workspace_id == workspace_id
                    )
                )
            )
            existing_hashes = set(
                await db.scalars(
                    select(DocumentORM.sha256).where(
                        DocumentORM.workspace_id == workspace_id
                    )
                )
            )
            if len({item.document.document_id for item in documents}) != len(
                documents
            ) or any(item.document.document_id in existing_ids for item in documents):
                raise ValueError("document already exists")
            if len({item.document.sha256 for item in documents}) != len(
                documents
            ) or any(item.document.sha256 in existing_hashes for item in documents):
                raise DocumentContentAlreadyExists(
                    "document content already exists in workspace"
                )
            next_order = (
                int(
                    await db.scalar(
                        select(
                            func.coalesce(func.max(DocumentORM.document_order), -1)
                        ).where(DocumentORM.workspace_id == workspace_id)
                    )
                )
                + 1
            )
            db.add_all(
                DocumentORM(
                    document_id=item.document.document_id,
                    workspace_id=workspace_id,
                    filename=item.document.filename,
                    storage_key=item.storage_key,
                    sha256=item.document.sha256,
                    media_type=item.document.media_type,
                    status=item.status,
                    size_bytes=item.document.size_bytes,
                    document_order=next_order + position,
                    created_at=_datetime(item.created_at),
                    updated_at=_datetime(item.updated_at or item.created_at),
                )
                for position, item in enumerate(documents)
            )
            workspace.status = "uploaded"
            workspace.updated_at = _datetime(updated_at)

    async def update_document(
        self, record: StoredDocument, *, db: AsyncSession | None = None
    ) -> bool:
        async with AsyncSessionLocal.begin() if db is None else nullcontext(db) as db:
            document = record.document
            row = await db.get(DocumentORM, document.document_id)
            if row is None:
                return False
            row.filename = document.filename
            row.storage_key = record.storage_key
            row.sha256 = document.sha256
            row.media_type = document.media_type
            row.status = record.status
            row.size_bytes = document.size_bytes
            row.updated_at = _datetime(record.updated_at or record.created_at)
            return True


    async def delete_workspace(self, workspace_id: str) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(WorkspaceORM, workspace_id)
            if row is None:
                return False
            await db.delete(row)
            return True


async def load_workspace_documents(
    db: AsyncSession,
    workspace_id: str,
) -> tuple[StoredDocument, ...]:
    rows = await db.execute(
        select(DocumentORM, DocumentPreparationORM)
        .outerjoin(
            DocumentPreparationORM,
            DocumentPreparationORM.document_id == DocumentORM.document_id,
        )
        .where(DocumentORM.workspace_id == workspace_id)
        .order_by(DocumentORM.document_order)
    )
    documents = []
    for document, preparation in rows:
        profile = dict(preparation.profile_json or {}) if preparation else {}
        source_fingerprint = preparation.source_fingerprint if preparation else None
        profile_fingerprint = profile.get("profile_fingerprint")
        documents.append(
            StoredDocument(
                document=DocumentAggregate(
                    document_id=document.document_id,
                    filename=document.filename,
                    sha256=document.sha256,
                    media_type=document.media_type,
                    size_bytes=document.size_bytes,
                ),
                storage_key=document.storage_key,
                status=document.status,
                parser_version=preparation.parser_version if preparation else None,
                document_analysis_version=profile.get("profile_version"),
                source_fingerprint=source_fingerprint,
                profile_fingerprint=profile_fingerprint,
                # The source identity remains usable until profiling completes.
                preparation_fingerprint=profile_fingerprint or source_fingerprint,
                created_at=_iso(document.created_at),
                updated_at=_iso(document.updated_at),
            )
        )
    return tuple(documents)


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        parsed = datetime.fromisoformat(
            f"{text[:-1]}+00:00" if text.endswith("Z") else text
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


__all__ = ["WorkspaceRepository"]


WorkspaceRepo = WorkspaceRepository()
