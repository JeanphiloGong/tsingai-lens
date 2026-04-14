from __future__ import annotations

import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from config import DATA_DIR
from domain.ports import CollectionPaths


class MemoryCollectionRepository:
    """Memory-backed persistence for collection metadata and uploaded files."""

    backend_name = "memory"

    def __init__(self, root_dir: Path | None = None) -> None:
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if root_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="lens-collections-")
            root_dir = Path(self._temp_dir.name)
        self.root_dir = Path(root_dir or (DATA_DIR / "collections")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._collections: dict[str, dict] = {}
        self._files: dict[str, list[dict]] = {}
        self._import_manifests: dict[str, dict] = {}

    def get_paths(self, collection_id: str) -> CollectionPaths:
        collection_dir = self.root_dir / collection_id
        return CollectionPaths(
            collection_dir=collection_dir,
            input_dir=collection_dir / "input",
            output_dir=collection_dir / "output",
            meta_path=collection_dir / "meta.json",
            files_path=collection_dir / "files.json",
            import_manifest_path=collection_dir / "import_manifest.json",
            artifacts_path=collection_dir / "artifacts.json",
        )

    def create_collection_dirs(self, collection_id: str) -> CollectionPaths:
        paths = self.get_paths(collection_id)
        paths.collection_dir.mkdir(parents=True, exist_ok=True)
        paths.input_dir.mkdir(parents=True, exist_ok=True)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        return paths

    def collection_exists(self, collection_id: str) -> bool:
        return collection_id in self._collections

    def list_collection_records(self) -> list[tuple[str, dict]]:
        return [
            (collection_id, deepcopy(record))
            for collection_id, record in sorted(self._collections.items())
        ]

    def read_collection(self, collection_id: str) -> dict | None:
        record = self._collections.get(collection_id)
        return deepcopy(record) if record is not None else None

    def write_collection(self, collection_id: str, payload: dict) -> None:
        self.create_collection_dirs(collection_id)
        self._collections[collection_id] = deepcopy(payload)

    def delete_collection_dir(self, collection_id: str) -> None:
        self._collections.pop(collection_id, None)
        self._files.pop(collection_id, None)
        self._import_manifests.pop(collection_id, None)
        shutil.rmtree(self.get_paths(collection_id).collection_dir, ignore_errors=True)

    def read_files(self, collection_id: str) -> list[dict] | None:
        if collection_id not in self._collections and collection_id not in self._files:
            return None
        return deepcopy(self._files.get(collection_id, []))

    def write_files(self, collection_id: str, payload: list[dict]) -> None:
        self.create_collection_dirs(collection_id)
        self._files[collection_id] = deepcopy(payload)

    def read_import_manifest(self, collection_id: str) -> dict | None:
        payload = self._import_manifests.get(collection_id)
        return deepcopy(payload) if payload is not None else None

    def write_import_manifest(self, collection_id: str, payload: dict) -> None:
        self.create_collection_dirs(collection_id)
        self._import_manifests[collection_id] = deepcopy(payload)

    def write_input_file(
        self, collection_id: str, stored_filename: str, payload: bytes
    ) -> Path:
        paths = self.create_collection_dirs(collection_id)
        stored_path = paths.input_dir / stored_filename
        stored_path.write_bytes(payload)
        return stored_path
