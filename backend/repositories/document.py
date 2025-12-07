import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from domain.document import Document, DocumentData, DocumentMeta, MetaInfo
from domain.graph import ImageAsset


class BaseDocumentTable(ABC):
    @abstractmethod
    def save(self, doc: Document) -> None: ...

    @abstractmethod
    def get(self, doc_id: str) -> Optional[Document]: ...

    @abstractmethod
    def list(self) -> Iterable[Document]: ...

    @abstractmethod
    def path_for(self, doc_id: str) -> Path: ...

    @abstractmethod
    def next_id(self) -> str: ...


class JsonDocumentTable(BaseDocumentTable):
    def __init__(self, index_file: Path, documents_dir: Path):
        self.index_file = Path(index_file)
        self.documents_dir = Path(documents_dir)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.index: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.index_file.exists():
            try:
                self.index = json.loads(self.index_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.index = {}
        else:
            self.index = {}

    def _save(self) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(
            json.dumps(self.index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def next_id(self) -> str:
        return str(uuid.uuid4())

    def save(self, doc: Document) -> None:
        self.index[doc.id] = {
            "id": doc.id,
            "filename": doc.filename,
            "data": {
                "status": doc.data.status,
                "status_message": doc.data.status_message,
            },
            "meta": {
                "keywords": doc.meta.keywords,
                "graph": doc.meta.graph,
                "mindmap": doc.meta.mindmap,
                "images": [self._serialize_image(img) for img in doc.meta.images],
                "info": {
                    "type": doc.meta.info.type,
                    "size": doc.meta.info.size,
                    "filename": doc.meta.info.filename,
                },
            },
            "created_at": doc.created_at.isoformat(),
            "updated_at": doc.updated_at.isoformat(),
        }
        self._save()

    def get(self, doc_id: str) -> Optional[Document]:
        rec = self.index.get(doc_id)
        if not rec:
            return None
        return self._from_record(rec)

    def list(self) -> Iterable[Document]:
        return (self._from_record(rec) for rec in self.index.values())

    def path_for(self, doc_id: str) -> Path:
        rec = self.index.get(doc_id)
        if not rec:
            raise FileNotFoundError(f"文档 {doc_id} 没有找到")
        return self.documents_dir / rec["filename"]

    def _from_record(self, rec: dict) -> Document:
        data_block = rec.get("data", {})
        meta_block = rec.get("meta", {})
        info_block = meta_block.get("info", {})
        images_block = meta_block.get("images", [])
        return Document(
            id=rec["id"],
            filename=rec["filename"],
            data=DocumentData(
                status=data_block.get("status", "pending"),
                status_message=data_block.get("status_message", ""),
            ),
            meta=DocumentMeta(
                keywords=meta_block.get("keywords", []),
                graph=meta_block.get("graph", {}),
                mindmap=meta_block.get("mindmap", {}),
                images=[self._deserialize_image(img) for img in images_block],
                info=MetaInfo(
                    type=info_block.get("type", ""),
                    size=info_block.get("size", 0),
                    filename=info_block.get("filename", ""),
                ),
            ),
            created_at=datetime.fromisoformat(rec["created_at"]),
            updated_at=datetime.fromisoformat(rec.get("updated_at", rec["created_at"])),
        )

    def _serialize_image(self, img):
        if isinstance(img, ImageAsset):
            return {
                "url": img.url,
                "mime_type": img.mime_type,
                "width": img.width,
                "height": img.height,
            }
        if is_dataclass(img):
            return asdict(img)
        if isinstance(img, dict):
            return img
        return {"url": str(img)}

    def _deserialize_image(self, img):
        if isinstance(img, ImageAsset):
            return img
        if isinstance(img, dict):
            return ImageAsset(
                url=img.get("url", ""),
                mime_type=img.get("mime_type"),
                width=img.get("width"),
                height=img.get("height"),
            )
        return ImageAsset(url=str(img))
