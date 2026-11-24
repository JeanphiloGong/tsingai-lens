from __future__ import annotations

from infra.persistence.file import workspace_files

from sqlalchemy.ext.asyncio import AsyncSession

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from domain.chat.permissions import change_permission
from domain.source import Workspace
from exceptions import ResourceConflictException, ResourceNotFoundException
from repositories.workspace_repository import (
    PermissionRevisionConflict,
    StoredWorkspace,
    StoredDocument,
)
from repositories.object_store import ObjectStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


from repositories.workspace_repository import WorkspaceRepo


def write_figure_asset(
    workspace_id: str,
    document_id: str,
    asset_path: str,
    payload: bytes,
    expected_sha256: str,
    *,
    object_store: ObjectStore,
) -> str:
    suffix = PurePosixPath(str(asset_path)).suffix.lower()
    storage_key = _figure_storage_key(
        workspace_id,
        document_id,
        expected_sha256,
        suffix,
    )
    object_store.write(storage_key, payload, expected_sha256)
    return storage_key


def read_figure_asset(
    workspace_id: str,
    storage_key: str,
    expected_sha256: str,
    *,
    object_store: ObjectStore,
) -> bytes:
    key = PurePosixPath(str(storage_key))
    if (
        len(key.parts) != 6
        or key.parts[:3]
        != (
            str(workspace_id),
            "objects",
            "source",
        )
        or key.parts[4] != "figures"
    ):
        raise ValueError("invalid figure storage key")
    expected_key = _figure_storage_key(
        workspace_id,
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


async def create_workspace(
    name: str,
    description: str | None=None,
    owner_user_id: str='local-user',
) -> StoredWorkspace:
    workspace = workspace_files.Workspace
    workspace_id = f"col_{uuid4().hex[:12]}"
    now = _now_iso()
    record = StoredWorkspace(
        workspace=Workspace(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            status="idle",
        ),
        created_at=now,
        updated_at=now,
    )
    workspace.create_workspace_dirs(workspace_id)
    try:
        await WorkspaceRepo.add_workspace(record)
    except Exception:
        workspace.delete_workspace_dir(workspace_id)
        raise
    return record


async def get_workspace(workspace_id: str) -> StoredWorkspace:
    record = await WorkspaceRepo.read_workspace(workspace_id)
    if record is None:
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )
    return record


async def get_workspace_for_user(workspace_id: str, owner_user_id: str) -> StoredWorkspace:
    record = await get_workspace(workspace_id)
    if record.workspace.owner_user_id != owner_user_id:
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )
    return record


async def get_agent_default_permission_for_user(
    workspace_id: str, owner_user_id: str
) -> dict[str, Any]:
    if not await WorkspaceRepo.workspace_belongs_to_user(
        workspace_id,
        owner_user_id,
    ):
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )
    permission = {
        "mode": "confirm",
        "actions": [],
        "expires_at": None,
        "revision": 0,
    }
    saved = await WorkspaceRepo.read_agent_default_permission(workspace_id)
    if saved:
        permission.update(saved)
    return permission


async def set_agent_default_permission_for_user(
    workspace_id: str,
    owner_user_id: str,
    *,
    mode: str,
    actions: list[str],
    all_actions: bool = False,
    expires_at: str | None,
    expected_revision: int,
) -> dict[str, Any]:
    await get_workspace_for_user(workspace_id, owner_user_id)
    current = {
        "mode": "confirm",
        "actions": [],
        "expires_at": None,
        "revision": 0,
    }
    saved = await WorkspaceRepo.read_agent_default_permission(workspace_id)
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
            data={"code": str(exc), "workspace_id": workspace_id},
        ) from exc
    try:
        saved = await WorkspaceRepo.set_agent_default_permission(
            workspace_id,
            updated,
            expected_revision=current["revision"],
        )
    except PermissionRevisionConflict as exc:
        raise ResourceConflictException(
            "Permission changed. Reload before saving.",
            data={
                "code": "permission_revision_conflict",
                "workspace_id": workspace_id,
            },
        ) from exc
    if not saved:
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )
    return updated


async def get_document(
    workspace_id: str,
    document_id: str,
    *,
    db: AsyncSession | None = None,
) -> StoredDocument:
    record = await WorkspaceRepo.read_document(workspace_id, document_id, db=db)
    if record is None:
        raise ResourceNotFoundException(
            f"document not found: {workspace_id}/{document_id}",
            data={
                "code": "document_not_found",
                "workspace_id": workspace_id,
                "document_id": document_id,
            },
        )
    return record


async def update_document_preparation(
    workspace_id: str,
    document_id: str,
    *,
    status: str,
    preparation_fingerprint: str | None = None,
    source_fingerprint: str | None = None,
    profile_fingerprint: str | None = None,
    parser_version: str | None = None,
    document_analysis_version: str | None = None,
    db: AsyncSession | None = None,
) -> StoredDocument:
    current = await get_document(workspace_id, document_id, db=db)
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
    if not await WorkspaceRepo.update_document(updated, db=db):
        raise ResourceNotFoundException(
            f"document not found: {workspace_id}/{document_id}",
            data={
                "code": "document_not_found",
                "workspace_id": workspace_id,
                "document_id": document_id,
            },
        )
    return updated


async def update_workspace(workspace_id: str, **fields) -> StoredWorkspace:
    current = await WorkspaceRepo.read_workspace(workspace_id)
    if current is None:
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )
    allowed_fields = {
        key: value
        for key, value in fields.items()
        if key in {"name", "description", "status"}
    }
    normalized = replace(
        current,
        workspace=replace(current.workspace, **allowed_fields),
        updated_at=_now_iso(),
    )
    if not await WorkspaceRepo.update_workspace(normalized):
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )
    return await get_workspace(workspace_id)


async def delete_workspace(
    workspace_id: str,
) -> dict:
    workspace = workspace_files.Workspace
    paths = workspace.get_paths(workspace_id)
    target_dir = paths.workspace_dir
    workspace = await WorkspaceRepo.read_workspace(workspace_id)
    if workspace is None:
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )

    resolved_root = workspace.root_dir.resolve()
    resolved_target = target_dir.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("invalid workspace path") from exc
    if target_dir.is_symlink():
        raise ValueError("workspace path cannot be a symlink")

    for record in workspace.documents:
        storage_key = record.storage_key
        stored_filename = record.stored_filename
        if (
            not storage_key
            or not stored_filename
            or storage_key != _input_storage_key(workspace_id, stored_filename)
        ):
            raise ValueError("invalid workspace object key")
    if not await WorkspaceRepo.delete_workspace(workspace_id):
        raise ResourceNotFoundException(
            f"workspace not found: {workspace_id}",
            data={"code": "workspace_not_found", "workspace_id": workspace_id},
        )
    workspace.delete_workspace_dir(workspace_id)
    return {
        "workspace_id": workspace_id,
        "deleted_at": _now_iso(),
    }


async def delete_workspace_for_user(
    workspace_id: str,
    owner_user_id: str,
) -> dict:
    await get_workspace_for_user(workspace_id, owner_user_id)
    return await delete_workspace(workspace_id)


def _input_storage_key(workspace_id: str, stored_filename: str) -> str:
    return f"{workspace_id}/input/{stored_filename}"


def _figure_storage_key(
    workspace_id: str,
    document_id: str,
    sha256: str,
    suffix: str,
) -> str:
    workspace_key = str(workspace_id).strip()
    document_key = str(document_id).strip()
    digest = str(sha256).strip()
    extension = str(suffix).strip().lower()
    if (
        not workspace_key
        or not document_key
        or any(character in workspace_key + document_key for character in "/\\")
        or not extension.startswith(".")
        or not extension[1:].isalnum()
        or len(extension) > 10
    ):
        raise ValueError("invalid figure storage key")
    return f"{workspace_key}/objects/source/{document_key}/figures/{digest}{extension}"
