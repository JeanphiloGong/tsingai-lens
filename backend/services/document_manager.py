import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class DocumentManager:
    def __init__(self, index_file: Path, documents_dir: Path):
        self.index_file = Path(index_file)
        self.documents_dir = Path(documents_dir)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.index: Dict[str, Dict] = {}
        self._load()

    def _load(self) -> None:
        if self.index_file.exists():
            try:
                self.index = json.loads(self.index_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.index = {}

    def _save(self) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(json.dumps(self.index, ensure_ascii=False, indent=2), encoding="utf-8")

    def register(
        self,
        original_filename: str,
        stored_filename: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        doc_id: Optional[str] = None,
    ) -> str:
        doc_id = doc_id or str(uuid.uuid4())
        stored = stored_filename or original_filename
        record = {
            "id": doc_id,
            "filename": stored,
            "original_filename": original_filename,
            "tags": tags or [],
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        self.index[doc_id] = record
        self._save()
        return doc_id

    def get(self, doc_id: str) -> Optional[Dict]:
        return self.index.get(doc_id)

    def list(self) -> List[Dict]:
        return list(self.index.values())

    def path_for(self, doc_id: str) -> Path:
        record = self.index.get(doc_id)
        if not record:
            raise FileNotFoundError(f"Document {doc_id} not found")
        return self.documents_dir / record["filename"]
