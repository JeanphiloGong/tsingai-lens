"""PostgreSQL persistence for the collection aggregate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.source import Collection as CollectionAggregate
from domain.source import Document as CollectionDocumentData
from infra.persistence.postgres.models.collection import (
    Collection,
    CollectionFile,
    StoredObject,
)
from infra.persistence.postgres.models.build import CollectionBuild
from infra.persistence.postgres.models.comparison import (
    CollectionComparableResultRecord,
    ComparableResultRecord,
    ComparisonBuild,
    PairwiseComparisonRelationRecord,
    comparable_result_anchor_links,
    comparable_result_evidence_links,
    comparable_result_feature_links,
    comparable_result_observation_links,
    pairwise_comparison_anchor_links,
)
from infra.persistence.postgres.models.document import (
    CollectionDocument,
    Document,
    DocumentVersion,
)
from infra.persistence.postgres.models.evaluation import (
    EvaluationGoldSetRecord,
    EvaluationPredictionSnapshotRecord,
    EvaluationRunRecord,
)
from infra.persistence.postgres.models.objective import (
    ObjectiveAnalysisRecord,
    ObjectiveBuild,
    ObjectivePaperContributionRecord,
    ObjectivePaperSkim,
    ObjectiveResearchRecord,
    objective_build_candidates,
    objective_document_scope,
    objective_finding_evidence_links,
    objective_finding_relation_evidence_links,
)
from infra.persistence.postgres.models.chat import ChatSessionRow
from infra.persistence.postgres.models.objective_workspace import ObjectiveExperimentPlan
from infra.persistence.postgres.models.source import (
    SourceDocument,
    SourceReferenceCandidate,
    SourceReferenceEntry,
    SourceReferenceMention,
    SourceReferenceResolution,
)


class PostgresCollectionRepository:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    async def add_collection(self, record: CollectionAggregate) -> None:
        async with self.session_factory.begin() as session:
            session.add(
                Collection(
                    collection_id=record.collection_id,
                    owner_user_id=record.owner_user_id,
                    name=record.name,
                    description=record.description,
                    status=record.status,
                    paper_count=record.paper_count,
                    created_at=_datetime(record.created_at),
                    updated_at=_datetime(record.updated_at),
                )
            )

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionAggregate, ...]:
        statement = select(Collection).order_by(Collection.collection_id)
        if owner_user_id is not None:
            statement = statement.where(Collection.owner_user_id == owner_user_id)
        async with self.session_factory() as session:
            rows = tuple(await session.scalars(statement))
            records: list[CollectionAggregate] = []
            for row in rows:
                documents = await _documents_for_collection(
                    session,
                    row.collection_id,
                )
                records.append(_to_record(row, documents))
            return tuple(records)

    async def read_collection(
        self, collection_id: str
    ) -> CollectionAggregate | None:
        async with self.session_factory() as session:
            row = await session.get(Collection, collection_id)
            if row is None:
                return None
            return _to_record(
                row,
                await _documents_for_collection(session, collection_id),
            )

    async def update_collection(self, record: CollectionAggregate) -> bool:
        async with self.session_factory.begin() as session:
            row = await session.get(Collection, record.collection_id)
            if row is None:
                return False
            row.owner_user_id = record.owner_user_id
            row.name = record.name
            row.description = record.description
            row.status = record.status
            row.paper_count = record.paper_count
            row.created_at = _datetime(record.created_at)
            row.updated_at = _datetime(record.updated_at)
            return True

    async def add_documents(
        self,
        collection_id: str,
        documents: tuple[CollectionDocumentData, ...],
        *,
        updated_at: str,
    ) -> None:
        if not documents:
            raise ValueError("at least one document is required")

        async with self.session_factory.begin() as session:
            collection = await session.get(
                Collection,
                collection_id,
                with_for_update=True,
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {collection_id}")
            existing_documents = await _documents_for_collection(
                session,
                collection_id,
            )
            existing_ids = {
                document.document_id for document in existing_documents
            }
            existing_hashes = {document.sha256 for document in existing_documents}
            document_ids = [document.document_id for document in documents]
            document_hashes = [document.sha256 for document in documents]
            if len(set(document_ids)) != len(document_ids) or any(
                document_id in existing_ids for document_id in document_ids
            ):
                raise ValueError("document already exists")
            if len(set(document_hashes)) != len(document_hashes) or any(
                digest in existing_hashes for digest in document_hashes
            ):
                raise ValueError("document content already exists in collection")
            next_file_order = (
                int(
                    await session.scalar(
                        select(
                            func.coalesce(func.max(CollectionFile.file_order), -1)
                        ).where(CollectionFile.collection_id == collection_id)
                    )
                )
                + 1
            )
            object_rows: list[StoredObject] = []
            file_rows: list[CollectionFile] = []
            for document_order, document in enumerate(documents):
                canonical_document_id, document_version_id = _content_identity(
                    document.sha256
                )
                membership_id = _membership_identity(
                    collection_id,
                    canonical_document_id,
                )
                if await session.get(Document, canonical_document_id) is None:
                    session.add(
                        Document(
                            document_id=canonical_document_id,
                            created_at=_datetime(document.created_at),
                        )
                    )
                if (
                    await session.get(DocumentVersion, document_version_id)
                    is None
                ):
                    session.add(
                        DocumentVersion(
                            document_version_id=document_version_id,
                            document_id=canonical_document_id,
                            sha256=document.sha256,
                            media_type=document.media_type,
                            created_at=_datetime(document.created_at),
                        )
                    )
                if (
                    await session.get(
                        CollectionDocument, membership_id
                    )
                    is None
                ):
                    session.add(
                        CollectionDocument(
                            collection_document_id=membership_id,
                            collection_id=collection_id,
                            document_id=canonical_document_id,
                            document_version_id=document_version_id,
                            created_at=_datetime(document.created_at),
                        )
                    )
                object_id = _object_identity(document.document_id)
                object_rows.append(
                    StoredObject(
                        object_id=object_id,
                        object_kind="source_input",
                        storage_key=document.storage_key,
                        sha256=document.sha256,
                        size_bytes=document.size_bytes,
                        media_type=document.media_type,
                        document_version_id=document_version_id,
                        created_at=_datetime(document.created_at),
                    )
                )
                file_rows.append(
                    CollectionFile(
                        file_id=document.document_id,
                        collection_id=collection_id,
                        object_id=object_id,
                        collection_document_id=membership_id,
                        original_filename=document.original_filename,
                        stored_filename=document.stored_filename,
                        status=document.status,
                        document_id=document.document_id,
                        file_order=next_file_order + document_order,
                        created_at=_datetime(document.created_at),
                    )
                )

            session.add_all(object_rows)
            await session.flush()
            session.add_all(file_rows)
            await session.flush()
            collection.paper_count = int(
                await session.scalar(
                    select(func.count(CollectionFile.file_id)).where(
                        CollectionFile.collection_id == collection_id
                    )
                )
            )
            collection.status = "ready"
            collection.updated_at = _datetime(updated_at)

    async def delete_collection(self, collection_id: str) -> bool:
        async with self.session_factory.begin() as session:
            row = await session.get(Collection, collection_id)
            if row is None:
                return False
            object_ids = tuple(
                await session.scalars(
                    select(CollectionFile.object_id).where(
                        CollectionFile.collection_id == collection_id
                    )
                )
            )
            memberships = tuple(
                await session.scalars(
                    select(CollectionDocument).where(
                        CollectionDocument.collection_id == collection_id
                    )
                )
            )
            document_version_ids = {
                membership.document_version_id for membership in memberships
            }
            document_ids = {membership.document_id for membership in memberships}
            build_ids = tuple(
                await session.scalars(
                    select(CollectionBuild.build_id).where(
                        CollectionBuild.collection_id == collection_id
                    )
                )
            )

            # Remove collection-scoped derived records before their RESTRICTed
            # source/build parents. Everything remains in this transaction.
            await session.execute(
                delete(objective_finding_relation_evidence_links).where(
                    objective_finding_relation_evidence_links.c.collection_id
                    == collection_id
                )
            )
            await session.execute(
                delete(objective_finding_evidence_links).where(
                    objective_finding_evidence_links.c.collection_id == collection_id
                )
            )
            await session.execute(
                delete(ObjectivePaperContributionRecord).where(
                    ObjectivePaperContributionRecord.collection_id == collection_id
                )
            )
            await session.execute(
                delete(ObjectiveAnalysisRecord).where(
                    ObjectiveAnalysisRecord.collection_id == collection_id
                )
            )
            await session.execute(
                delete(objective_build_candidates).where(
                    objective_build_candidates.c.collection_id == collection_id
                )
            )
            await session.execute(
                delete(objective_document_scope).where(
                    objective_document_scope.c.collection_id == collection_id
                )
            )
            await session.execute(
                delete(ObjectivePaperSkim).where(
                    ObjectivePaperSkim.collection_id == collection_id
                )
            )
            await session.execute(
                delete(ObjectiveBuild).where(
                    ObjectiveBuild.collection_id == collection_id
                )
            )
            await session.execute(
                delete(ObjectiveExperimentPlan).where(
                    ObjectiveExperimentPlan.collection_id == collection_id
                )
            )
            await session.execute(
                delete(ChatSessionRow).where(
                    ChatSessionRow.collection_id == collection_id
                )
            )
            await session.execute(
                delete(ObjectiveResearchRecord).where(
                    ObjectiveResearchRecord.collection_id == collection_id
                )
            )

            for table in (
                pairwise_comparison_anchor_links,
                comparable_result_anchor_links,
                comparable_result_evidence_links,
                comparable_result_feature_links,
                comparable_result_observation_links,
            ):
                if build_ids:
                    await session.execute(delete(table).where(table.c.build_id.in_(build_ids)))
            if build_ids:
                await session.execute(
                    delete(CollectionComparableResultRecord).where(
                        CollectionComparableResultRecord.build_id.in_(build_ids)
                    )
                )
                await session.execute(
                    delete(PairwiseComparisonRelationRecord).where(
                        PairwiseComparisonRelationRecord.build_id.in_(build_ids)
                    )
                )
                await session.execute(
                    delete(ComparableResultRecord).where(
                        ComparableResultRecord.build_id.in_(build_ids)
                    )
                )
                await session.execute(
                    delete(ComparisonBuild).where(
                        ComparisonBuild.build_id.in_(build_ids)
                    )
                )

            await session.execute(
                delete(EvaluationRunRecord).where(
                    EvaluationRunRecord.collection_id == collection_id
                )
            )
            await session.execute(
                delete(EvaluationGoldSetRecord).where(
                    EvaluationGoldSetRecord.collection_id == collection_id
                )
            )
            await session.execute(
                delete(EvaluationPredictionSnapshotRecord).where(
                    EvaluationPredictionSnapshotRecord.collection_id
                    == collection_id
                )
            )
            await session.execute(
                delete(SourceReferenceCandidate).where(
                    SourceReferenceCandidate.collection_id == collection_id
                )
            )
            await session.execute(
                delete(SourceReferenceResolution).where(
                    SourceReferenceResolution.collection_id == collection_id
                )
            )
            await session.execute(
                delete(SourceReferenceMention).where(
                    SourceReferenceMention.collection_id == collection_id
                )
            )
            await session.execute(
                delete(SourceReferenceEntry).where(
                    SourceReferenceEntry.collection_id == collection_id
                )
            )
            await session.execute(
                delete(SourceDocument).where(
                    SourceDocument.collection_id == collection_id
                )
            )
            await session.execute(
                delete(CollectionBuild).where(
                    CollectionBuild.collection_id == collection_id
                )
            )
            await session.execute(
                delete(CollectionFile).where(
                    CollectionFile.collection_id == collection_id
                )
            )
            if object_ids:
                await session.execute(
                    delete(StoredObject).where(StoredObject.object_id.in_(object_ids))
                )
            await session.execute(
                delete(CollectionDocument).where(
                    CollectionDocument.collection_id == collection_id
                )
            )
            await session.flush()
            for document_version_id in document_version_ids:
                has_membership = await session.scalar(
                    select(func.count(CollectionDocument.collection_document_id)).where(
                        CollectionDocument.document_version_id == document_version_id
                    )
                )
                has_object = await session.scalar(
                    select(func.count(StoredObject.object_id)).where(
                        StoredObject.document_version_id == document_version_id
                    )
                )
                if not has_membership and not has_object:
                    version = await session.get(DocumentVersion, document_version_id)
                    if version is not None:
                        await session.delete(version)
            await session.flush()
            for document_id in document_ids:
                has_version = await session.scalar(
                    select(func.count(DocumentVersion.document_version_id)).where(
                        DocumentVersion.document_id == document_id
                    )
                )
                if not has_version:
                    document = await session.get(Document, document_id)
                    if document is not None:
                        await session.delete(document)
            await session.delete(row)
            return True


def _to_record(
    row: Collection,
    documents: tuple[CollectionDocumentData, ...],
) -> CollectionAggregate:
    return CollectionAggregate(
        collection_id=row.collection_id,
        owner_user_id=row.owner_user_id,
        name=row.name,
        description=row.description,
        status=row.status,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        documents=documents,
    )


def _to_document(
    file_row: CollectionFile,
    object_row: StoredObject,
) -> CollectionDocumentData:
    return CollectionDocumentData(
        document_id=file_row.file_id,
        original_filename=file_row.original_filename,
        stored_filename=file_row.stored_filename,
        storage_key=object_row.storage_key,
        sha256=object_row.sha256,
        media_type=object_row.media_type,
        status=file_row.status,
        size_bytes=object_row.size_bytes,
        created_at=_iso(file_row.created_at),
    )


async def _documents_for_collection(
    session: AsyncSession,
    collection_id: str,
) -> tuple[CollectionDocumentData, ...]:
    rows = await session.execute(
        select(CollectionFile, StoredObject)
        .join(StoredObject, CollectionFile.object_id == StoredObject.object_id)
        .where(CollectionFile.collection_id == collection_id)
        .order_by(CollectionFile.file_order)
    )
    return tuple(_to_document(file_row, object_row) for file_row, object_row in rows)


def _content_identity(sha256: str) -> tuple[str, str]:
    digest = str(sha256).strip().lower()
    if len(digest) != 64:
        raise ValueError("document content hash must be a lowercase SHA-256")
    return (
        f"doc_{uuid5(NAMESPACE_URL, f'lens:document:{digest}').hex}",
        f"docver_{uuid5(NAMESPACE_URL, f'lens:document-version:{digest}').hex}",
    )


def _membership_identity(collection_id: str, document_id: str) -> str:
    return (
        "coldoc_"
        + uuid5(
            NAMESPACE_URL,
            f"lens:collection-document:{collection_id}:{document_id}",
        ).hex
    )


def _object_identity(document_id: str) -> str:
    return f"obj_{uuid5(NAMESPACE_URL, f'lens:object:{document_id}').hex[:24]}"


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


__all__ = ["PostgresCollectionRepository"]
