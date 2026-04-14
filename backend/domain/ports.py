from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CollectionPaths:
    collection_dir: Path
    input_dir: Path
    output_dir: Path
    meta_path: Path
    files_path: Path
    import_manifest_path: Path
    artifacts_path: Path


class CollectionRepository(Protocol):
    backend_name: str
    root_dir: Path

    def get_paths(self, collection_id: str) -> CollectionPaths: ...

    def create_collection_dirs(self, collection_id: str) -> CollectionPaths: ...

    def collection_exists(self, collection_id: str) -> bool: ...

    def list_collection_records(self) -> list[tuple[str, dict]]: ...

    def read_collection(self, collection_id: str) -> dict | None: ...

    def write_collection(self, collection_id: str, payload: dict) -> None: ...

    def delete_collection_dir(self, collection_id: str) -> None: ...

    def read_files(self, collection_id: str) -> list[dict] | None: ...

    def write_files(self, collection_id: str, payload: list[dict]) -> None: ...

    def read_import_manifest(self, collection_id: str) -> dict | None: ...

    def write_import_manifest(self, collection_id: str, payload: dict) -> None: ...

    def write_input_file(
        self, collection_id: str, stored_filename: str, payload: bytes
    ) -> Path: ...


class TaskRepository(Protocol):
    backend_name: str
    root_dir: Path

    def read_task(self, task_id: str) -> dict | None: ...

    def write_task(self, task_id: str, payload: dict) -> None: ...

    def list_tasks(self) -> list[dict]: ...


class ArtifactRepository(Protocol):
    backend_name: str
    root_dir: Path

    def read(self, collection_id: str) -> dict | None: ...

    def write(self, collection_id: str, payload: dict) -> None: ...
