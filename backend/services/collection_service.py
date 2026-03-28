from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None

from config import DATA_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CollectionPaths:
    collection_dir: Path
    input_dir: Path
    output_dir: Path
    meta_path: Path
    files_path: Path
    artifacts_path: Path


class CollectionService:
    """File-backed collection registry for the app layer."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or (DATA_DIR / "collections")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _collection_dir(self, collection_id: str) -> Path:
        return self.root_dir / collection_id

    def get_paths(self, collection_id: str) -> CollectionPaths:
        base_dir = self._collection_dir(collection_id)
        return CollectionPaths(
            collection_dir=base_dir,
            input_dir=base_dir / "input",
            output_dir=base_dir / "output",
            meta_path=base_dir / "meta.json",
            files_path=base_dir / "files.json",
            artifacts_path=base_dir / "artifacts.json",
        )

    def _read_json(self, path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

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
        paths = self.get_paths(collection_id)
        paths.collection_dir.mkdir(parents=True, exist_ok=True)
        paths.input_dir.mkdir(parents=True, exist_ok=True)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(paths.meta_path, record)
        self._write_json(paths.files_path, [])
        self._write_json(
            paths.artifacts_path,
            {
                "collection_id": collection_id,
                "output_path": str(paths.output_dir),
                "documents_ready": False,
                "graph_ready": False,
                "sections_ready": False,
                "procedure_blocks_ready": False,
                "protocol_steps_ready": False,
                "graphml_ready": False,
                "updated_at": now,
            },
        )
        return record

    def list_collections(self) -> list[dict]:
        items: list[dict] = []
        for meta_path in sorted(self.root_dir.glob("*/meta.json")):
            collection_id = meta_path.parent.name
            record = self._normalize_collection_record(
                self._read_json(meta_path, {}),
                collection_id,
            )
            items.append(record)
        return items

    def get_collection(self, collection_id: str) -> dict:
        paths = self.get_paths(collection_id)
        record = self._read_json(paths.meta_path, None)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        normalized = self._normalize_collection_record(record, collection_id)
        if normalized != record:
            self._write_json(paths.meta_path, normalized)
        return normalized

    def update_collection(self, collection_id: str, **fields) -> dict:
        paths = self.get_paths(collection_id)
        record = self.get_collection(collection_id)
        record.update(fields)
        record["updated_at"] = _now_iso()
        self._write_json(paths.meta_path, record)
        return record

    def list_files(self, collection_id: str) -> list[dict]:
        paths = self.get_paths(collection_id)
        if not paths.files_path.exists():
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return self._read_json(paths.files_path, [])

    def _pdf_to_text(self, content: bytes) -> str:
        if fitz is None:
            raise RuntimeError("PyMuPDF 未安装，无法处理 PDF")
        with fitz.open(stream=content, filetype="pdf") as doc:
            texts = [page.get_text("text") for page in doc]
        return "\n".join(texts)

    def add_file(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
    ) -> dict:
        paths = self.get_paths(collection_id)
        if not paths.meta_path.exists():
            raise FileNotFoundError(f"collection not found: {collection_id}")

        suffix = Path(filename or "").suffix.lower()
        if suffix == ".pdf":
            payload = self._pdf_to_text(content).encode("utf-8")
            stored_filename = f"{uuid4().hex}_{Path(filename).stem}.txt"
        else:
            payload = content
            stored_filename = f"{uuid4().hex}_{Path(filename).name}"

        stored_path = paths.input_dir / stored_filename
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        stored_path.write_bytes(payload)

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

        files = self._read_json(paths.files_path, [])
        files.append(file_record)
        self._write_json(paths.files_path, files)
        self.update_collection(collection_id, paper_count=len(files), status="ready")
        return file_record
