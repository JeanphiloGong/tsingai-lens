from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.ports import ArtifactRepository, CollectionPaths, CollectionRepository
from infra.ingestion.pdf_ingest import pdf_to_text
from infra.persistence.factory import (
    build_artifact_repository,
    build_collection_repository,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectionService:
    """File-backed collection registry for the application layer."""

    def __init__(
        self,
        root_dir: Path | None = None,
        repository: CollectionRepository | None = None,
        artifact_repository: ArtifactRepository | None = None,
    ) -> None:
        self.repository = repository or build_collection_repository(root_dir)
        self.artifact_repository = (
            artifact_repository
            or build_artifact_repository(
                self.repository.root_dir,
                backend=self.repository.backend_name,
            )
        )
        self.root_dir = self.repository.root_dir

    def get_paths(self, collection_id: str) -> CollectionPaths:
        return self.repository.get_paths(collection_id)

    def _normalize_collection_record(
        self,
        record: dict | None,
        collection_id: str,
    ) -> dict:
        payload = dict(record or {})
        created_at = payload.get("created_at") or _now_iso()
        updated_at = payload.get("updated_at") or created_at

        if not payload.get("collection_id"):
            payload["collection_id"] = str(payload.get("id") or collection_id)

        if "name" not in payload or payload.get("name") is None:
            payload["name"] = payload["collection_id"]
        payload.setdefault("description", None)
        payload.setdefault("status", "idle")
        payload.setdefault("default_method", "standard")
        payload["paper_count"] = int(payload.get("paper_count") or 0)
        payload["created_at"] = str(created_at)
        payload["updated_at"] = str(updated_at)
        payload.pop("id", None)
        return payload

    def create_collection(
        self,
        name: str,
        description: str | None = None,
        default_method: str = "standard",
    ) -> dict:
        collection_id = f"col_{uuid4().hex[:12]}"
        now = _now_iso()
        record = {
            "collection_id": collection_id,
            "name": name,
            "description": description,
            "status": "idle",
            "default_method": default_method,
            "paper_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        paths = self.repository.create_collection_dirs(collection_id)
        self.repository.write_collection(collection_id, record)
        self.repository.write_files(collection_id, [])
        self.artifact_repository.write(
            collection_id,
            {
                "collection_id": collection_id,
                "output_path": str(paths.output_dir),
                "documents_generated": False,
                "documents_ready": False,
                "document_profiles_generated": False,
                "document_profiles_ready": False,
                "evidence_cards_generated": False,
                "evidence_cards_ready": False,
                "comparison_rows_generated": False,
                "comparison_rows_ready": False,
                "graph_generated": False,
                "graph_ready": False,
                "sections_generated": False,
                "sections_ready": False,
                "procedure_blocks_generated": False,
                "procedure_blocks_ready": False,
                "protocol_steps_generated": False,
                "protocol_steps_ready": False,
                "graphml_generated": False,
                "graphml_ready": False,
                "updated_at": now,
            },
        )
        return record

    def list_collections(self) -> list[dict]:
        items: list[dict] = []
        for collection_id, record in self.repository.list_collection_records():
            record = self._normalize_collection_record(
                record,
                collection_id,
            )
            items.append(record)
        return items

    def get_collection(self, collection_id: str) -> dict:
        record = self.repository.read_collection(collection_id)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        normalized = self._normalize_collection_record(record, collection_id)
        if normalized != record:
            self.repository.write_collection(collection_id, normalized)
        return normalized

    def update_collection(self, collection_id: str, **fields) -> dict:
        record = self.get_collection(collection_id)
        record.update(fields)
        record["updated_at"] = _now_iso()
        self.repository.write_collection(collection_id, record)
        return record

    def delete_collection(self, collection_id: str) -> dict:
        paths = self.get_paths(collection_id)
        target_dir = paths.collection_dir
        if not self.repository.collection_exists(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")

        resolved_root = self.root_dir.resolve()
        resolved_target = target_dir.resolve()
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("invalid collection path") from exc
        if target_dir.is_symlink():
            raise ValueError("collection path cannot be a symlink")

        self.repository.delete_collection_dir(collection_id)
        return {
            "collection_id": collection_id,
            "deleted_at": _now_iso(),
        }

    def list_files(self, collection_id: str) -> list[dict]:
        files = self.repository.read_files(collection_id)
        if files is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return files

    def add_file(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
    ) -> dict:
        if not self.repository.collection_exists(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")

        suffix = Path(filename or "").suffix.lower()
        if suffix == ".pdf":
            payload = pdf_to_text(content).encode("utf-8")
            stored_filename = f"{uuid4().hex}_{Path(filename).stem}.txt"
        else:
            payload = content
            stored_filename = f"{uuid4().hex}_{Path(filename).name}"

        stored_path = self.repository.write_input_file(
            collection_id,
            stored_filename,
            payload,
        )

        file_record = {
            "file_id": f"file_{uuid4().hex[:12]}",
            "collection_id": collection_id,
            "original_filename": filename,
            "stored_filename": stored_filename,
            "stored_path": str(stored_path),
            "media_type": media_type,
            "status": "stored",
            "size_bytes": len(payload),
            "created_at": _now_iso(),
        }

        files = self.repository.read_files(collection_id) or []
        files.append(file_record)
        self.repository.write_files(collection_id, files)
        self.update_collection(collection_id, paper_count=len(files), status="ready")
        return file_record
