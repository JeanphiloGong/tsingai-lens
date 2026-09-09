from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from application.repositories.collection_repository import (
    CollectionRepository,
    CollectionSummary,
)
from domain.source import Collection, Document
from application.repositories.object_store import ObjectStore
from infra.persistence.file.collection_workspace import CollectionPaths
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore


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
    ) -> tuple[CollectionSummary, ...]:
        return await self.repository.list_collections(owner_user_id)

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

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
