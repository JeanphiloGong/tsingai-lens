from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from domain.ports import ArtifactRepository, CollectionRepository, TaskRepository
from infra.persistence.file import (
    FileArtifactRepository,
    FileCollectionRepository,
    FileTaskRepository,
)
from infra.persistence.memory import (
    MemoryArtifactRepository,
    MemoryCollectionRepository,
    MemoryTaskRepository,
)

DEFAULT_PERSISTENCE_BACKEND = "file"


@dataclass(frozen=True)
class PersistenceBundle:
    collection_repository: CollectionRepository
    task_repository: TaskRepository
    artifact_repository: ArtifactRepository


def resolve_persistence_backend(backend: str | None = None) -> str:
    resolved = (backend or os.getenv("LENS_PERSISTENCE_BACKEND") or DEFAULT_PERSISTENCE_BACKEND)
    normalized = resolved.strip().lower()
    if normalized not in {"file", "memory", "mysql"}:
        raise ValueError(f"unsupported persistence backend: {resolved}")
    return normalized


def build_collection_repository(
    root_dir: Path | None = None,
    backend: str | None = None,
) -> CollectionRepository:
    resolved = resolve_persistence_backend(backend)
    if resolved == "file":
        return FileCollectionRepository(root_dir)
    if resolved == "memory":
        return MemoryCollectionRepository(root_dir)
    raise NotImplementedError("mysql persistence adapters are not implemented yet")


def build_task_repository(
    root_dir: Path | None = None,
    backend: str | None = None,
) -> TaskRepository:
    resolved = resolve_persistence_backend(backend)
    if resolved == "file":
        return FileTaskRepository(root_dir)
    if resolved == "memory":
        return MemoryTaskRepository(root_dir)
    raise NotImplementedError("mysql persistence adapters are not implemented yet")


def build_artifact_repository(
    root_dir: Path | None = None,
    backend: str | None = None,
) -> ArtifactRepository:
    resolved = resolve_persistence_backend(backend)
    if resolved == "file":
        return FileArtifactRepository(root_dir)
    if resolved == "memory":
        return MemoryArtifactRepository(root_dir)
    raise NotImplementedError("mysql persistence adapters are not implemented yet")


def build_persistence_bundle(
    collections_root: Path | None = None,
    tasks_root: Path | None = None,
    backend: str | None = None,
) -> PersistenceBundle:
    collection_repository = build_collection_repository(
        root_dir=collections_root,
        backend=backend,
    )
    return PersistenceBundle(
        collection_repository=collection_repository,
        task_repository=build_task_repository(
            root_dir=tasks_root,
            backend=backend,
        ),
        artifact_repository=build_artifact_repository(
            root_dir=collection_repository.root_dir,
            backend=backend,
        ),
    )
