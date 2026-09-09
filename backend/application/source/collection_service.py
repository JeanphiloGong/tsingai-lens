from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from domain.ports import CollectionPaths, CollectionRepository
from domain.source import Collection, Document
from domain.source.ports import ObjectStore
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from infra.source.ingestion import (
    NormalizedImportBatch,
    NormalizedImportDocument,
    SourceAdapter,
    SourceAdapterRequest,
    normalize_upload,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectionService:
    """Application operations over a collection and its current documents."""

    def __init__(
        self,
        repository: CollectionRepository,
        workspace: FileCollectionWorkspace,
        object_store: ObjectStore | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.root_dir = self.workspace.root_dir
        self.object_store = object_store or FileObjectStore(self.root_dir)

    def get_paths(self, collection_id: str) -> CollectionPaths:
        return self.workspace.get_paths(collection_id)

    def write_figure_asset(
        self,
        collection_id: str,
        document_id: str,
        asset_path: str,
        payload: bytes,
        expected_sha256: str,
    ) -> str:
        suffix = PurePosixPath(str(asset_path)).suffix.lower()
        storage_key = self._figure_storage_key(
            collection_id,
            document_id,
            expected_sha256,
            suffix,
        )
        self.object_store.write(storage_key, payload, expected_sha256)
        return storage_key

    def read_figure_asset(
        self,
        collection_id: str,
        storage_key: str,
        expected_sha256: str,
    ) -> bytes:
        key = PurePosixPath(str(storage_key))
        if (
            len(key.parts) != 6
            or key.parts[:3]
            != (
                str(collection_id),
                "objects",
                "source",
            )
            or key.parts[4] != "figures"
        ):
            raise ValueError("invalid figure storage key")
        expected_key = self._figure_storage_key(
            collection_id,
            key.parts[3],
            expected_sha256,
            key.suffix.lower(),
        )
        if str(key) != expected_key:
            raise ValueError("invalid figure storage key")
        try:
            return self.object_store.read(storage_key, expected_sha256)
        except ValueError as exc:
            raise OSError("figure object verification failed") from exc

    # define a method for creating a document collection
    async def create_collection(
        self,
        name: str,
        description: str | None = None,
        owner_user_id: str = "local-user",
    ) -> dict:
        collection_id = f"col_{uuid4().hex[:12]}"
        now = _now_iso()
        record = Collection.create(
            collection_id=collection_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            now_iso=now,
        )
        self.workspace.create_collection_dirs(collection_id)
        try:
            await self.repository.add_collection(record)
        except Exception:
            self.workspace.delete_collection_dir(collection_id)
            raise
        return record.to_record()

    async def list_collections(
        self, owner_user_id: str | None = None
    ) -> list[dict]:
        return [
            record.to_record()
            for record in await self.repository.list_collections(owner_user_id)
        ]

    async def get_collection(self, collection_id: str) -> dict:
        record = await self.repository.read_collection(collection_id)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record.to_record()

    async def get_collection_for_user(
        self, collection_id: str, owner_user_id: str
    ) -> dict:
        record = await self.get_collection(collection_id)
        if record["owner_user_id"] != owner_user_id:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record

    # define a method that return a single document record
    async def get_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> Document:
        record = await self.repository.read_document(collection_id, document_id)
        if record is None:
            raise FileNotFoundError(
                f"document not found: {collection_id}/{document_id}"
            )
        return record

    async def update_document_preparation(
        self,
        collection_id: str,
        document_id: str,
        *,
        status: str,
        preparation_fingerprint: str | None = None,
        source_fingerprint: str | None = None,
        profile_fingerprint: str | None = None,
        parser_version: str | None = None,
        document_analysis_version: str | None = None,
    ) -> Document:
        current = await self.get_document(collection_id, document_id)
        updated = replace(
            current,
            status=str(status),
            updated_at=_now_iso(),
            preparation_fingerprint=(
                preparation_fingerprint
                if preparation_fingerprint is not None
                else current.preparation_fingerprint
            ),
            source_fingerprint=(
                source_fingerprint
                if source_fingerprint is not None
                else current.source_fingerprint
            ),
            profile_fingerprint=(
                profile_fingerprint
                if profile_fingerprint is not None
                else current.profile_fingerprint
            ),
            parser_version=(
                parser_version if parser_version is not None else current.parser_version
            ),
            document_analysis_version=(
                document_analysis_version
                if document_analysis_version is not None
                else current.document_analysis_version
            ),
        )
        if not await self.repository.update_document(updated):
            raise FileNotFoundError(
                f"document not found: {collection_id}/{document_id}"
            )
        return updated

    async def update_collection(self, collection_id: str, **fields) -> dict:
        current = await self.repository.read_collection(collection_id)
        if current is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        allowed_fields = {
            key: value
            for key, value in fields.items()
            if key in {"name", "description", "status"}
        }
        normalized = replace(current, **allowed_fields, updated_at=_now_iso())
        if not await self.repository.update_collection(normalized):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return await self.get_collection(collection_id)

    async def delete_collection(self, collection_id: str) -> dict:
        paths = self.get_paths(collection_id)
        target_dir = paths.collection_dir
        collection = await self.repository.read_collection(collection_id)
        if collection is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")

        resolved_root = self.root_dir.resolve()
        resolved_target = target_dir.resolve()
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("invalid collection path") from exc
        if target_dir.is_symlink():
            raise ValueError("collection path cannot be a symlink")

        for record in collection.documents:
            storage_key = self._optional_text(record.storage_key)
            stored_filename = self._optional_text(record.stored_filename)
            if (
                not storage_key
                or not stored_filename
                or storage_key
                != self._input_storage_key(collection_id, stored_filename)
            ):
                raise ValueError("invalid collection object key")
        if not await self.repository.delete_collection(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        self.workspace.delete_collection_dir(collection_id)
        return {
            "collection_id": collection_id,
            "deleted_at": _now_iso(),
        }

    async def delete_collection_for_user(
        self, collection_id: str, owner_user_id: str
    ) -> dict:
        await self.get_collection_for_user(collection_id, owner_user_id)
        return await self.delete_collection(collection_id)

    async def import_from_adapter(
        self,
        collection_id: str,
        adapter: SourceAdapter,
        raw_locator: str,
        *,
        goal_context: dict[str, Any] | None = None,
        max_documents: int | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> list[dict]:
        await self.get_collection(collection_id)

        request = SourceAdapterRequest(
            collection_id=collection_id,
            raw_locator=raw_locator,
            goal_context=dict(goal_context) if goal_context else None,
            max_documents=max_documents,
            constraints=dict(constraints or {}),
        )
        batch = adapter.fetch(request)
        self._validate_adapter_batch(adapter, batch)
        return await self.import_normalized_batch(collection_id, batch)

    async def import_normalized_batch(
        self,
        collection_id: str,
        batch: NormalizedImportBatch,
    ) -> list[dict]:
        await self.get_collection(collection_id)
        if not batch.documents:
            raise ValueError(
                "normalized import batch must include at least one document"
            )

        text_by_source_document = self._group_text_units(batch)
        created_documents: list[Document] = []

        try:
            for document in batch.documents:
                stored_filename = document.stored_filename or (
                    f"{uuid4().hex}_{Path(document.original_filename).name}"
                )
                payload = self._build_import_payload(
                    document=document,
                    source_document_id=document.source_document_id,
                    text_by_source_document=text_by_source_document,
                )
                storage_key = self._input_storage_key(collection_id, stored_filename)
                payload_sha256 = sha256(payload).hexdigest()
                self.object_store.write(storage_key, payload, payload_sha256)
                created_documents.append(
                    Document(
                        document_id=f"doc_{uuid4().hex[:12]}",
                        original_filename=document.original_filename,
                        stored_filename=stored_filename,
                        storage_key=storage_key,
                        sha256=payload_sha256,
                        media_type=document.media_type,
                        status="stored",
                        size_bytes=len(payload),
                        created_at=_now_iso(),
                        updated_at=_now_iso(),
                    )
                )
            await self.repository.add_documents(
                collection_id,
                tuple(created_documents),
                updated_at=_now_iso(),
            )
        except Exception:
            try:
                current = await self.repository.read_collection(collection_id)
                registered_keys = {
                    record.storage_key
                    for record in (current.documents if current is not None else ())
                }
            except Exception:
                registered_keys = set()
            for record in created_documents:
                if record.storage_key not in registered_keys:
                    self.object_store.delete(record.storage_key)
            raise
        return [record.to_record() for record in created_documents]

    async def add_document(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
    ) -> dict:
        await self.get_collection(collection_id)
        batch = await asyncio.to_thread(
            normalize_upload,
            filename=filename,
            content=content,
            media_type=media_type,
        )
        imported = await self.import_normalized_batch(collection_id, batch)
        if not imported:
            raise ValueError("normalized upload produced no importable documents")
        return imported[0]

    def _input_storage_key(self, collection_id: str, stored_filename: str) -> str:
        return f"{collection_id}/input/{stored_filename}"

    @staticmethod
    def _figure_storage_key(
        collection_id: str,
        document_id: str,
        sha256: str,
        suffix: str,
    ) -> str:
        collection_key = str(collection_id).strip()
        document_key = str(document_id).strip()
        digest = str(sha256).strip()
        extension = str(suffix).strip().lower()
        if (
            not collection_key
            or not document_key
            or any(character in collection_key + document_key for character in "/\\")
            or not extension.startswith(".")
            or not extension[1:].isalnum()
            or len(extension) > 10
        ):
            raise ValueError("invalid figure storage key")
        return (
            f"{collection_key}/objects/source/{document_key}/figures/{digest}{extension}"
        )

    def _group_text_units(
        self,
        batch: NormalizedImportBatch,
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[tuple[int, str]]] = {}
        for text_unit in batch.text_units:
            grouped.setdefault(text_unit.source_document_id, []).append(
                (int(text_unit.sequence), text_unit.text)
            )
        return {
            source_document_id: [
                text for _, text in sorted(items, key=lambda item: item[0])
            ]
            for source_document_id, items in grouped.items()
        }

    def _build_import_payload(
        self,
        document: NormalizedImportDocument,
        source_document_id: str,
        text_by_source_document: dict[str, list[str]],
    ) -> bytes:
        encoded_payload = str(document.storage_payload_base64 or "").strip()
        if encoded_payload:
            return base64.b64decode(encoded_payload)

        parts = [
            text.strip()
            for text in text_by_source_document.get(source_document_id, [])
            if text and text.strip()
        ]
        if not parts:
            raise ValueError(
                f"normalized import missing text payload for source document: {source_document_id}"
            )
        return "\n".join(parts).encode("utf-8")

    def _validate_adapter_batch(
        self,
        adapter: SourceAdapter,
        batch: NormalizedImportBatch,
    ) -> None:
        if not isinstance(batch, NormalizedImportBatch):
            raise TypeError("source adapter must return NormalizedImportBatch")

        expected_channel = str(getattr(adapter, "channel", "") or "").strip()
        expected_adapter_name = str(getattr(adapter, "adapter_name", "") or "").strip()
        expected_adapter_version = getattr(adapter, "adapter_version", None)

        if expected_channel and batch.source_metadata.channel != expected_channel:
            raise ValueError(
                "source adapter batch channel does not match adapter contract"
            )
        if (
            expected_adapter_name
            and batch.source_metadata.adapter_name != expected_adapter_name
        ):
            raise ValueError(
                "source adapter batch adapter_name does not match adapter contract"
            )
        if expected_adapter_version is not None and (
            batch.source_metadata.adapter_version != expected_adapter_version
        ):
            raise ValueError(
                "source adapter batch adapter_version does not match adapter contract"
            )

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
