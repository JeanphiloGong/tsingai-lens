import base64
import json
import mimetypes
from uuid import uuid4

from fitz import extra

from config import DOCUMENTS_DIR, IMAGES_DIR, STATIC_IMAGE_URL
from domain.document import MetaInfo
from domain.graph import DocumentMeta, ImageAsset
from services.file_service import FileService
from services.graphrag_service import GraphService
from services.llm_client import LLMClient

from utils.chunker import chunk_pages
from utils.keywords import extract_keywords
from utils.loader import load_file
import logging

logger = logging.getLogger(__name__)

class IngestionWorkflow:
    def __init__(
            self, 
            file_svc: FileService, 
            graph_svc: GraphService,
            llm: LLMClient
            ):
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
            metadata: str | None
            ):
        try:
            self.file_svc.update_status(doc_id, "processing", "处理中")
            dest_path = DOCUMENTS_DIR / stored_filename
            pages, images = load_file(dest_path)

            doc_tags = [t.strip() for t in tags.split(",")] if tags else []
            extra_metadata = json.loads(metadata) if metadata else {}

            # 构建图结构
            chunked = chunk_pages(pages)
            self.graph_svc.ingest_chunks(chunked, doc_id=doc_id, source=original_name)

            # 摘要关键词
            full_text = "\n".join(f for _, t in pages)
            keywords = extract_keywords(full_text)
            snapshot = self.graph_svc.snapshot()
            summary = self.llm.summarize(full_text[:3000]) if full_text else ""

            # 保存图片
            saved_images = self._save_images(doc_id, images)

            # 写入meta
            meta = DocumentMeta(
                    keywords=keywords,
                    graph={
                        "nodes": snapshot.get("nodes", []),
                        "edges": snapshot.get("edges", []),
                        },
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

            # 记录tags
            meta.info.filename = original_name

            self.file_svc.update_meta(doc_id, meta)
            self.file_svc.update_status(doc_id, "completed", "处理完成")
        except Exception as e:
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
