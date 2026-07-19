from __future__ import annotations

import shutil
from pathlib import Path

from config import DATA_DIR
from domain.ports import CollectionPaths
from infra.persistence.file._json import read_json, write_json


class FileCollectionWorkspace:
    """Filesystem workspace for collection-local files and outputs."""

    backend_name = "file"

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or (DATA_DIR / "collections")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def get_paths(self, collection_id: str) -> CollectionPaths:
        collection_dir = self.root_dir / collection_id
        return CollectionPaths(
            collection_dir=collection_dir,
            input_dir=collection_dir / "input",
            output_dir=collection_dir / "output",
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

    def delete_collection_dir(self, collection_id: str) -> None:
        shutil.rmtree(self.get_paths(collection_id).collection_dir)

    def read_files(self, collection_id: str) -> list[dict] | None:
        paths = self.get_paths(collection_id)
        if not paths.files_path.exists():
            return None
        return read_json(paths.files_path, [])

    def write_files(self, collection_id: str, payload: list[dict]) -> None:
        write_json(self.get_paths(collection_id).files_path, payload)

    def read_import_manifest(self, collection_id: str) -> dict | None:
        paths = self.get_paths(collection_id)
        if not paths.import_manifest_path.exists():
            return None
        return read_json(paths.import_manifest_path, None)

    def write_import_manifest(self, collection_id: str, payload: dict) -> None:
        write_json(self.get_paths(collection_id).import_manifest_path, payload)
