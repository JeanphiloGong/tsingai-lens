import logging
from pathlib import Path
from typing import Optional

from domain.document import Document, DocumentMeta, MetaInfo
from repositories.document import BaseDocumentTable

logger = logging.getLogger(__name__)


class FileService:
    def __init__(self, repo: BaseDocumentTable, documents_dir: Path):
        self.repo = repo
        self.documents_dir = documents_dir
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        logger.info("初始化 FileService，documents_dir=%s", self.documents_dir)

    def save_file(self, filename: str, content: bytes) -> Path:
        path = self.documents_dir / filename
        path.write_bytes(content)
        logger.info("文件保存完成，path=%s，size=%s", path, len(content))
        return path

    def register_document(
        self,
        doc_id: str,
        stored_filename: Optional[str],
        original_filename: str,
        mime_type: str | None,
        size: int | None,
    ) -> Document:
        meta = DocumentMeta(
            info=MetaInfo(
                type=mime_type or "",
                size=size or 0,
                filename=original_filename,
            )
        )

        doc = Document(
            id=doc_id,
            filename=stored_filename or original_filename,
            meta=meta,
        )
        self.repo.save(doc)
        logger.info(
            "文档注册完成，doc_id=%s，original=%s，stored=%s",
            doc_id,
            original_filename,
            stored_filename,
        )
        return doc

    def update_status(self, doc_id: str, status: str, message: str | None = None) -> None:
        doc = self.repo.get(doc_id)
        if not doc:
            logger.warning("更新状态失败，文档不存在 doc_id=%s", doc_id)
            return
        doc.update_status(status, message)
        self.repo.save(doc)
        logger.info("更新文档状态，doc_id=%s，status=%s，message=%s", doc_id, status, message)

    def get(self, doc_id: str) -> Document | None:
        doc = self.repo.get(doc_id)
        logger.info("获取文档，doc_id=%s，存在=%s", doc_id, doc is not None)
        return doc

    def list(self) -> list[Document]:
        docs = list(self.repo.list())
        logger.info("列出文档，数量=%s", len(docs))
        return docs

    def update_meta(self, doc_id: str, meta: DocumentMeta):
        doc = self.repo.get(doc_id)
        if not doc:
            logger.warning("更新元数据失败，文档不存在 doc_id=%s", doc_id)
            return
        doc.update_meta(meta)
        self.repo.save(doc)
        logger.info("更新元数据成功，doc_id=%s", doc_id)
