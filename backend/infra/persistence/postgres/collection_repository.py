"""PostgreSQL persistence for the collection aggregate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from domain.source import (
    CollectionDocumentRecord,
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
    DocumentRecord,
    DocumentVersionRecord,
    collection_document_identity,
    document_identity_for_sha256,
)
from infra.persistence.postgres.models.collection import (
    Collection,
    CollectionFile,
    CollectionHandoff,
    CollectionImport,
    CollectionImportDocument,
    StoredObject,
)
from infra.persistence.postgres.models.document import (
    CollectionDocument,
    Document,
    DocumentVersion,
)


class PostgresCollectionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def add_collection(self, record: CollectionRecord) -> None:
        with self.session_factory.begin() as session:
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

    def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionRecord, ...]:
        statement = select(Collection).order_by(Collection.collection_id)
        if owner_user_id is not None:
            statement = statement.where(Collection.owner_user_id == owner_user_id)
        with self.session_factory() as session:
            return tuple(_to_record(row) for row in session.scalars(statement))

    def read_collection(self, collection_id: str) -> CollectionRecord | None:
        with self.session_factory() as session:
            row = session.get(Collection, collection_id)
            return _to_record(row) if row is not None else None

    def update_collection(self, record: CollectionRecord) -> bool:
        with self.session_factory.begin() as session:
            row = session.get(Collection, record.collection_id)
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

    def add_collection_import(
        self,
        record: CollectionImportRecord,
        *,
        updated_at: str,
    ) -> None:
        if not record.documents:
            raise ValueError("collection import must include at least one document")
        if any(
            document.file.collection_id != record.collection_id
            for document in record.documents
        ):
            raise ValueError("collection import file belongs to another collection")

        with self.session_factory.begin() as session:
            collection = session.get(
                Collection,
                record.collection_id,
                with_for_update=True,
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {record.collection_id}")
            next_file_order = (
                int(
                    session.scalar(
                        select(
                            func.coalesce(func.max(CollectionFile.file_order), -1)
                        ).where(CollectionFile.collection_id == record.collection_id)
                    )
                )
                + 1
            )
            next_import_order = (
                int(
                    session.scalar(
                        select(
                            func.coalesce(func.max(CollectionImport.import_order), -1)
                        ).where(CollectionImport.collection_id == record.collection_id)
                    )
                )
                + 1
            )

            session.add(
                CollectionImport(
                    import_id=record.import_id,
                    collection_id=record.collection_id,
                    channel=record.channel,
                    adapter_name=record.adapter_name,
                    adapter_version=record.adapter_version,
                    raw_locator=record.raw_locator,
                    goal_context=(
                        dict(record.goal_context)
                        if record.goal_context is not None
                        else None
                    ),
                    warnings=list(record.warnings),
                    ingested_at=_datetime(record.ingested_at),
                    import_order=next_import_order,
                )
            )
            object_rows: list[StoredObject] = []
            file_rows: list[CollectionFile] = []
            document_rows: list[CollectionImportDocument] = []
            for document_order, document in enumerate(record.documents):
                file_record = document.file
                document_id, document_version_id = document_identity_for_sha256(
                    file_record.sha256
                )
                collection_document_id = collection_document_identity(
                    record.collection_id,
                    document_id,
                )
                if session.get(Document, document_id) is None:
                    session.add(
                        Document(
                            document_id=document_id,
                            created_at=_datetime(file_record.created_at),
                        )
                    )
                if session.get(DocumentVersion, document_version_id) is None:
                    session.add(
                        DocumentVersion(
                            document_version_id=document_version_id,
                            document_id=document_id,
                            sha256=file_record.sha256,
                            media_type=file_record.media_type,
                            created_at=_datetime(file_record.created_at),
                        )
                    )
                if session.get(CollectionDocument, collection_document_id) is None:
                    session.add(
                        CollectionDocument(
                            collection_document_id=collection_document_id,
                            collection_id=record.collection_id,
                            document_id=document_id,
                            document_version_id=document_version_id,
                            created_at=_datetime(file_record.created_at),
                        )
                    )
                object_rows.append(
                    StoredObject(
                        object_id=file_record.object_id,
                        object_kind=file_record.object_kind,
                        storage_key=file_record.storage_key,
                        sha256=file_record.sha256,
                        size_bytes=file_record.size_bytes,
                        media_type=file_record.media_type,
                        document_version_id=document_version_id,
                        created_at=_datetime(file_record.created_at),
                    )
                )
                file_rows.append(
                    CollectionFile(
                        file_id=file_record.file_id,
                        collection_id=file_record.collection_id,
                        object_id=file_record.object_id,
                        collection_document_id=collection_document_id,
                        original_filename=file_record.original_filename,
                        stored_filename=file_record.stored_filename,
                        status=file_record.status,
                        document_id=file_record.document_id,
                        file_order=next_file_order + document_order,
                        created_at=_datetime(file_record.created_at),
                    )
                )
                document_rows.append(
                    CollectionImportDocument(
                        file_id=file_record.file_id,
                        collection_id=record.collection_id,
                        import_id=record.import_id,
                        source_document_id=document.source_document_id,
                        origin_channel=document.origin_channel,
                        language=document.language,
                        ingest_status=document.ingest_status,
                        text_units=[dict(item) for item in document.text_units],
                        document_order=document_order,
                    )
                )

            session.add_all(object_rows)
            session.flush()
            session.add_all(file_rows)
            session.flush()
            session.add_all(document_rows)

            session.flush()
            collection.paper_count = int(
                session.scalar(
                    select(func.count(CollectionDocument.collection_document_id)).where(
                        CollectionDocument.collection_id == record.collection_id
                    )
                )
            )
            collection.status = "ready"
            collection.updated_at = _datetime(updated_at)

    def read_document(self, document_id: str) -> DocumentRecord | None:
        with self.session_factory() as session:
            row = session.get(Document, document_id)
            return _to_document_record(row) if row is not None else None

    def read_document_version(
        self,
        document_version_id: str,
    ) -> DocumentVersionRecord | None:
        with self.session_factory() as session:
            row = session.get(DocumentVersion, document_version_id)
            return _to_document_version_record(row) if row is not None else None

    def list_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[CollectionDocumentRecord, ...]:
        statement = (
            select(CollectionDocument)
            .where(CollectionDocument.collection_id == collection_id)
            .order_by(
                CollectionDocument.created_at,
                CollectionDocument.collection_document_id,
            )
        )
        with self.session_factory() as session:
            return tuple(
                _to_collection_document_record(row)
                for row in session.scalars(statement)
            )

    def list_collection_files(
        self,
        collection_id: str,
    ) -> tuple[CollectionFileRecord, ...]:
        statement = (
            select(CollectionFile, StoredObject)
            .join(StoredObject, CollectionFile.object_id == StoredObject.object_id)
            .where(CollectionFile.collection_id == collection_id)
            .order_by(CollectionFile.file_order)
        )
        with self.session_factory() as session:
            return tuple(
                _to_file_record(file_row, object_row)
                for file_row, object_row in session.execute(statement)
            )

    def list_collection_imports(
        self,
        collection_id: str,
    ) -> tuple[CollectionImportRecord, ...]:
        import_statement = (
            select(CollectionImport)
            .where(CollectionImport.collection_id == collection_id)
            .order_by(CollectionImport.import_order)
        )
        document_statement = (
            select(CollectionImportDocument, CollectionFile, StoredObject)
            .join(
                CollectionFile,
                CollectionImportDocument.file_id == CollectionFile.file_id,
            )
            .join(StoredObject, CollectionFile.object_id == StoredObject.object_id)
            .where(CollectionImportDocument.collection_id == collection_id)
            .order_by(
                CollectionImportDocument.import_id,
                CollectionImportDocument.document_order,
            )
        )
        with self.session_factory() as session:
            import_rows = tuple(session.scalars(import_statement))
            documents_by_import: dict[
                str,
                list[CollectionImportDocumentRecord],
            ] = {}
            for document_row, file_row, object_row in session.execute(
                document_statement
            ):
                documents_by_import.setdefault(document_row.import_id, []).append(
                    _to_import_document(document_row, file_row, object_row)
                )
            return tuple(
                _to_import_record(
                    import_row,
                    tuple(documents_by_import.get(import_row.import_id, ())),
                )
                for import_row in import_rows
            )

    def add_collection_handoff(self, record: CollectionHandoffRecord) -> None:
        with self.session_factory.begin() as session:
            collection = session.get(
                Collection,
                record.collection_id,
                with_for_update=True,
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {record.collection_id}")
            next_handoff_order = (
                int(
                    session.scalar(
                        select(
                            func.coalesce(func.max(CollectionHandoff.handoff_order), -1)
                        ).where(CollectionHandoff.collection_id == record.collection_id)
                    )
                )
                + 1
            )
            session.add(
                CollectionHandoff(
                    handoff_id=record.handoff_id,
                    collection_id=record.collection_id,
                    kind=record.kind,
                    status=record.status,
                    created_at=_datetime(record.created_at),
                    source_channels=list(record.source_channels),
                    goal_context=dict(record.goal_context),
                    handoff_order=next_handoff_order,
                )
            )

    def list_collection_handoffs(
        self,
        collection_id: str,
    ) -> tuple[CollectionHandoffRecord, ...]:
        statement = (
            select(CollectionHandoff)
            .where(CollectionHandoff.collection_id == collection_id)
            .order_by(CollectionHandoff.handoff_order)
        )
        with self.session_factory() as session:
            return tuple(_to_handoff_record(row) for row in session.scalars(statement))

    def delete_collection(self, collection_id: str) -> bool:
        with self.session_factory.begin() as session:
            row = session.get(Collection, collection_id)
            if row is None:
                return False
            object_ids = tuple(
                session.scalars(
                    select(CollectionFile.object_id).where(
                        CollectionFile.collection_id == collection_id
                    )
                )
            )
            memberships = tuple(
                session.scalars(
                    select(CollectionDocument).where(
                        CollectionDocument.collection_id == collection_id
                    )
                )
            )
            document_version_ids = {
                membership.document_version_id for membership in memberships
            }
            document_ids = {membership.document_id for membership in memberships}
            session.execute(
                delete(CollectionImportDocument).where(
                    CollectionImportDocument.collection_id == collection_id
                )
            )
            session.execute(
                delete(CollectionHandoff).where(
                    CollectionHandoff.collection_id == collection_id
                )
            )
            session.execute(
                delete(CollectionImport).where(
                    CollectionImport.collection_id == collection_id
                )
            )
            session.execute(
                delete(CollectionFile).where(
                    CollectionFile.collection_id == collection_id
                )
            )
            if object_ids:
                session.execute(
                    delete(StoredObject).where(StoredObject.object_id.in_(object_ids))
                )
            session.execute(
                delete(CollectionDocument).where(
                    CollectionDocument.collection_id == collection_id
                )
            )
            session.flush()
            for document_version_id in document_version_ids:
                has_membership = session.scalar(
                    select(func.count(CollectionDocument.collection_document_id)).where(
                        CollectionDocument.document_version_id == document_version_id
                    )
                )
                has_object = session.scalar(
                    select(func.count(StoredObject.object_id)).where(
                        StoredObject.document_version_id == document_version_id
                    )
                )
                if not has_membership and not has_object:
                    version = session.get(DocumentVersion, document_version_id)
                    if version is not None:
                        session.delete(version)
            session.flush()
            for document_id in document_ids:
                has_version = session.scalar(
                    select(func.count(DocumentVersion.document_version_id)).where(
                        DocumentVersion.document_id == document_id
                    )
                )
                if not has_version:
                    document = session.get(Document, document_id)
                    if document is not None:
                        session.delete(document)
            session.delete(row)
            return True


def _to_record(row: Collection) -> CollectionRecord:
    return CollectionRecord(
        collection_id=row.collection_id,
        owner_user_id=row.owner_user_id,
        name=row.name,
        description=row.description,
        status=row.status,
        paper_count=row.paper_count,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _to_document_record(row: Document) -> DocumentRecord:
    return DocumentRecord(
        document_id=row.document_id,
        created_at=_iso(row.created_at),
    )


def _to_document_version_record(row: DocumentVersion) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        document_version_id=row.document_version_id,
        document_id=row.document_id,
        sha256=row.sha256,
        media_type=row.media_type,
        created_at=_iso(row.created_at),
    )


def _to_collection_document_record(
    row: CollectionDocument,
) -> CollectionDocumentRecord:
    return CollectionDocumentRecord(
        collection_document_id=row.collection_document_id,
        collection_id=row.collection_id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        created_at=_iso(row.created_at),
    )


def _to_file_record(
    file_row: CollectionFile,
    object_row: StoredObject,
) -> CollectionFileRecord:
    return CollectionFileRecord(
        file_id=file_row.file_id,
        collection_id=file_row.collection_id,
        object_id=object_row.object_id,
        object_kind=object_row.object_kind,
        original_filename=file_row.original_filename,
        stored_filename=file_row.stored_filename,
        storage_key=object_row.storage_key,
        sha256=object_row.sha256,
        media_type=object_row.media_type,
        status=file_row.status,
        size_bytes=object_row.size_bytes,
        created_at=_iso(file_row.created_at),
        document_id=file_row.document_id,
    )


def _to_import_document(
    document_row: CollectionImportDocument,
    file_row: CollectionFile,
    object_row: StoredObject,
) -> CollectionImportDocumentRecord:
    return CollectionImportDocumentRecord(
        source_document_id=document_row.source_document_id,
        origin_channel=document_row.origin_channel,
        file=_to_file_record(file_row, object_row),
        language=document_row.language,
        ingest_status=document_row.ingest_status,
        text_units=tuple(dict(item) for item in document_row.text_units),
    )


def _to_import_record(
    row: CollectionImport,
    documents: tuple[CollectionImportDocumentRecord, ...],
) -> CollectionImportRecord:
    return CollectionImportRecord(
        import_id=row.import_id,
        collection_id=row.collection_id,
        channel=row.channel,
        adapter_name=row.adapter_name,
        adapter_version=row.adapter_version,
        raw_locator=row.raw_locator,
        goal_context=dict(row.goal_context) if row.goal_context is not None else None,
        warnings=tuple(str(item) for item in row.warnings),
        ingested_at=_iso(row.ingested_at),
        documents=documents,
    )


def _to_handoff_record(row: CollectionHandoff) -> CollectionHandoffRecord:
    return CollectionHandoffRecord(
        handoff_id=row.handoff_id,
        collection_id=row.collection_id,
        kind=row.kind,
        status=row.status,
        created_at=_iso(row.created_at),
        source_channels=tuple(str(item) for item in row.source_channels),
        goal_context=dict(row.goal_context),
    )


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
