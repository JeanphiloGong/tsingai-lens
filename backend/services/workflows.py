import base64
import json
import logging
import mimetypes
from pathlib import Path
from uuid import uuid4

from config import DOCUMENTS_DIR, IMAGES_DIR, STATIC_IMAGE_URL
from domain.document import MetaInfo, DocumentMeta
from domain.graph import ImageAsset
from services.file_service import FileService
from services.graphrag_service import GraphService
from services.llm_client import LLMClient
from utils.chunker import chunk_pages
from utils.keywords import extract_keywords
from utils.loader import load_file

logger = logging.getLogger(__name__)


class IngestionWorkflow:
    def __init__(self, file_svc: FileService, graph_svc: GraphService, llm: LLMClient):
        self.file_svc = file_svc
        self.graph_svc = graph_svc
        self.llm = llm
        self.logger = logging.getLogger(__name__)

    def process_in_background(
        self,
        doc_id: str,
        stored_filename: str,
        original_name: str,
        tags: str | None,
        metadata: str | None,
    ):
        try:
            self.logger.info("后台处理开始，doc_id=%s, stored=%s, original=%s", doc_id, stored_filename, original_name)
            self.file_svc.update_status(doc_id, "processing", "处理中")
            dest_path: Path = DOCUMENTS_DIR / stored_filename
            pages, images = load_file(dest_path)
            self.logger.info("文件解析完成，doc_id=%s，页数=%s，图片数=%s", doc_id, len(pages), len(images))

            doc_tags = [t.strip() for t in tags.split(",")] if tags else []
            extra_metadata = json.loads(metadata) if metadata else {}
            self.logger.info("标签解析完成，数量=%s，附加元数据键数=%s", len(doc_tags), len(extra_metadata))

            chunked = chunk_pages(pages)
            self.logger.info("文本切块完成，块数=%s", len(chunked))
            self.graph_svc.ingest_chunks(chunked, doc_id=doc_id, source=original_name)
            self.logger.info("构图完成，doc_id=%s", doc_id)

            full_text = "\n".join(t for _, t in pages)
            keywords = extract_keywords(full_text)
            snapshot = self.graph_svc.snapshot()
            summary = self.llm.summarize(full_text[:3000]) if full_text else ""
            self.logger.info(
                "摘要/关键词完成，keywords=%s，summary_len=%s，nodes=%s，edges=%s",
                len(keywords),
                len(summary),
                len(snapshot.get("nodes", [])),
                len(snapshot.get("edges", [])),
            )

            saved_images = self._save_images(doc_id, images)
            meta = DocumentMeta(
                keywords=keywords,
                graph={"nodes": snapshot.get("nodes", []), "edges": snapshot.get("edges", [])},
                mindmap={},
                images=saved_images,
                info=MetaInfo(
                    type=dest_path.suffix,
                    size=dest_path.stat().st_size if dest_path.exists() else 0,
                    filename=original_name,
                ),
            )
            if extra_metadata:
                meta.graph["extra"] = extra_metadata

            self.file_svc.update_meta(doc_id, meta)
            self.file_svc.update_status(doc_id, "completed", "处理完成")
            self.logger.info("后台处理结束，doc_id=%s，状态=completed", doc_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("后台处理失败, doc_id=%s", doc_id)
            self.file_svc.update_status(doc_id, "failed", str(e))

    def _save_images(self, doc_id: str, images: list) -> list[ImageAsset]:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        saved: list[ImageAsset] = []
        for idx, img in enumerate(images):
            if isinstance(img, bytes):
                data_bytes, mime = img, "image/jpeg"
            elif isinstance(img, str):
                data_bytes, mime = base64.b64decode(img), "image/jpeg"
            else:
                data_bytes = base64.b64decode(img.get("data"))
                mime = img.get("mime_type") or "image/jpeg"

            ext = mimetypes.guess_extension(mime) or ".jpg"
            fname = f"{doc_id}_img{idx}{ext}"
            path = IMAGES_DIR / fname
            path.write_bytes(data_bytes)
            saved.append(ImageAsset(url=f"{STATIC_IMAGE_URL}/{fname}", mime_type=mime))
            self.logger.info("保存图片，doc_id=%s，文件=%s，mime=%s", doc_id, fname, mime)
        return saved
