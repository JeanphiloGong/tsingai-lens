from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any
from uuid import uuid4

from domain.chat.permissions import change_permission
from domain.source import Collection
from exceptions import ResourceConflictException, ResourceNotFoundException
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from repositories.collection_repository import (
    PermissionRevisionConflict,
    StoredCollection,
    StoredDocument,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def document_details(record: StoredDocument) -> dict[str, Any]:
    return {
        **asdict(record.document),
        "stored_filename": record.stored_filename,
        "storage_key": record.storage_key,
        "created_at": record.created_at,
        "updated_at": record.updated_at or record.created_at,
    }


def collection_details(record: StoredCollection) -> dict[str, Any]:
    return {
        **asdict(record.collection),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "paper_count": len(record.documents),
        "documents": [document_details(document) for document in record.documents],
    }


from repositories.collection_repository import CollectionRepo

workspace: FileCollectionWorkspace | None = None
root_dir: Path | None = None
object_store: FileObjectStore | None = None


def configure_file_resources(root: Path) -> None:
    """Attach the process-owned collection workspace after application startup."""

    global workspace, root_dir, object_store
    workspace = FileCollectionWorkspace(root)
    root_dir = workspace.root_dir
    object_store = FileObjectStore(root_dir)


def write_figure_asset(
    collection_id: str,
    document_id: str,
    asset_path: str,
    payload: bytes,
    expected_sha256: str,
) -> str:
    suffix = PurePosixPath(str(asset_path)).suffix.lower()
    storage_key = _figure_storage_key(
        collection_id,
        document_id,
        expected_sha256,
        suffix,
    )
    object_store.write(storage_key, payload, expected_sha256)
    return storage_key


def read_figure_asset(
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
    expected_key = _figure_storage_key(
        collection_id,
        key.parts[3],
        expected_sha256,
        key.suffix.lower(),
    )
    if str(key) != expected_key:
        raise ValueError("invalid figure storage key")
    try:
        return object_store.read(storage_key, expected_sha256)
    except ValueError as exc:
        raise OSError("figure object verification failed") from exc


async def create_collection(
    name: str,
    description: str | None = None,
    owner_user_id: str = "local-user",
) -> dict:
    collection_id = f"col_{uuid4().hex[:12]}"
    now = _now_iso()
    record = StoredCollection(
        collection=Collection(
            collection_id=collection_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            status="idle",
        ),
        created_at=now,
        updated_at=now,
    )
    workspace.create_collection_dirs(collection_id)
    try:
        await CollectionRepo.add_collection(record)
    except Exception:
        workspace.delete_collection_dir(collection_id)
        raise
    return collection_details(record)


async def get_collection(collection_id: str) -> dict:
    record = await CollectionRepo.read_collection(collection_id)
    if record is None:
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    return collection_details(record)


async def get_collection_for_user(collection_id: str, owner_user_id: str) -> dict:
    record = await get_collection(collection_id)
    if record["owner_user_id"] != owner_user_id:
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    return record


async def get_agent_default_permission_for_user(
    collection_id: str, owner_user_id: str
) -> dict[str, Any]:
    if not await CollectionRepo.collection_belongs_to_user(
        collection_id,
        owner_user_id,
    ):
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    permission = {
        "mode": "confirm",
        "actions": [],
        "expires_at": None,
        "revision": 0,
    }
    saved = await CollectionRepo.read_agent_default_permission(collection_id)
    if saved:
        permission.update(saved)
    return permission


async def set_agent_default_permission_for_user(
    collection_id: str,
    owner_user_id: str,
    *,
    mode: str,
    actions: list[str],
    all_actions: bool = False,
    expires_at: str | None,
    expected_revision: int,
) -> dict[str, Any]:
    await get_collection_for_user(collection_id, owner_user_id)
    current = {
        "mode": "confirm",
        "actions": [],
        "expires_at": None,
        "revision": 0,
    }
    saved = await CollectionRepo.read_agent_default_permission(collection_id)
    if saved:
        current.update(saved)
    try:
        updated = change_permission(
            current,
            mode=mode,
            actions=actions,
            all_actions=all_actions,
            expires_at=expires_at,
            expected_revision=expected_revision,
        )
    except ValueError as exc:
        raise ResourceConflictException(
            str(exc),
            data={"code": str(exc), "collection_id": collection_id},
        ) from exc
    try:
        saved = await CollectionRepo.set_agent_default_permission(
            collection_id,
            updated,
            expected_revision=current["revision"],
        )
    except PermissionRevisionConflict as exc:
        raise ResourceConflictException(
            "Permission changed. Reload before saving.",
            data={
                "code": "permission_revision_conflict",
                "collection_id": collection_id,
            },
        ) from exc
    if not saved:
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    return updated


async def get_document(
    collection_id: str,
    document_id: str,
) -> StoredDocument:
    record = await CollectionRepo.read_document(collection_id, document_id)
    if record is None:
        raise ResourceNotFoundException(
            f"document not found: {collection_id}/{document_id}",
            data={
                "code": "document_not_found",
                "collection_id": collection_id,
                "document_id": document_id,
            },
        )
    return record


async def update_document_preparation(
    collection_id: str,
    document_id: str,
    *,
    status: str,
    preparation_fingerprint: str | None = None,
    source_fingerprint: str | None = None,
    profile_fingerprint: str | None = None,
    parser_version: str | None = None,
    document_analysis_version: str | None = None,
) -> StoredDocument:
    current = await get_document(collection_id, document_id)
    document = current.document
    updated = replace(
        current,
        updated_at=_now_iso(),
        document=replace(
            document,
            status=str(status),
            preparation_fingerprint=(
                preparation_fingerprint
                if preparation_fingerprint is not None
                else document.preparation_fingerprint
            ),
            source_fingerprint=(
                source_fingerprint
                if source_fingerprint is not None
                else document.source_fingerprint
            ),
            profile_fingerprint=(
                profile_fingerprint
                if profile_fingerprint is not None
                else document.profile_fingerprint
            ),
            parser_version=(
                parser_version
                if parser_version is not None
                else document.parser_version
            ),
            document_analysis_version=(
                document_analysis_version
                if document_analysis_version is not None
                else document.document_analysis_version
            ),
        ),
    )
    if not await CollectionRepo.update_document(updated):
        raise ResourceNotFoundException(
            f"document not found: {collection_id}/{document_id}",
            data={
                "code": "document_not_found",
                "collection_id": collection_id,
                "document_id": document_id,
            },
        )
    return updated


async def update_collection(collection_id: str, **fields) -> dict:
    current = await CollectionRepo.read_collection(collection_id)
    if current is None:
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    allowed_fields = {
        key: value
        for key, value in fields.items()
        if key in {"name", "description", "status"}
    }
    normalized = replace(
        current,
        collection=replace(current.collection, **allowed_fields),
        updated_at=_now_iso(),
    )
    if not await CollectionRepo.update_collection(normalized):
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    return await get_collection(collection_id)


async def delete_collection(collection_id: str) -> dict:
    paths = workspace.get_paths(collection_id)
    target_dir = paths.collection_dir
    collection = await CollectionRepo.read_collection(collection_id)
    if collection is None:
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )

    resolved_root = root_dir.resolve()
    resolved_target = target_dir.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("invalid collection path") from exc
    if target_dir.is_symlink():
        raise ValueError("collection path cannot be a symlink")

    for record in collection.documents:
        storage_key = record.storage_key
        stored_filename = record.stored_filename
        if (
            not storage_key
            or not stored_filename
            or storage_key != _input_storage_key(collection_id, stored_filename)
        ):
            raise ValueError("invalid collection object key")
    if not await CollectionRepo.delete_collection(collection_id):
        raise ResourceNotFoundException(
            f"collection not found: {collection_id}",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    workspace.delete_collection_dir(collection_id)
    return {
        "collection_id": collection_id,
        "deleted_at": _now_iso(),
    }


async def delete_collection_for_user(collection_id: str, owner_user_id: str) -> dict:
    await get_collection_for_user(collection_id, owner_user_id)
    return await delete_collection(collection_id)


def _input_storage_key(collection_id: str, stored_filename: str) -> str:
    return f"{collection_id}/input/{stored_filename}"


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
    return f"{collection_key}/objects/source/{document_key}/figures/{digest}{extension}"
