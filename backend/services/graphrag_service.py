import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

import config as config
from config import (
        DOCUMENTS_DIR
        )
from graphrag.builder import GraphBuilder
from graphrag.community import CommunityManager
from graphrag.retriever import GraphRetriever
from graph.keywords import extract_keywords
from ingest.chunker import chunk_pages
from ingest.loader import load_file
from services.document_manager import DocumentManager
from services.llm_client import LLMClient


logger = logging.getLogger(__name__)


class GraphRAGService:
    """Encapsulates document ingestion and graph-based querying."""

    def __init__(
        self,
        doc_manager: DocumentManager,
        graph_builder: GraphBuilder,
        community_manager: CommunityManager,
        llm_client: LLMClient,
        graph_retriever: GraphRetriever,
    ):
        self.doc_manager = doc_manager
        self.graph_builder = graph_builder
        self.community_manager = community_manager
        self.llm_client = llm_client
        self.graph_retriever = graph_retriever
        logger.info("初始化 GraphRAG 服务，文档目录=%s", DOCUMENTS_DIR)

    # --- metadata helpers ---
    def _meta_path(self, doc_id: str) -> Path:
        return config.DOCUMENTS_DIR / f"{doc_id}_meta.json"

    def write_meta(self, doc_id: str, data: Dict) -> None:
        path = self._meta_path(doc_id)
        logger.info("写入文档元数据，doc_id=%s，路径=%s，字段数=%s", doc_id, path, len(data))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_meta(self, doc_id: str) -> Dict:
        path = self._meta_path(doc_id)
        if path.exists():
            logger.info("读取文档元数据，doc_id=%s，路径=%s", doc_id, path)
            return json.loads(path.read_text(encoding="utf-8"))
        logger.warning("未找到文档元数据文件，doc_id=%s，路径=%s", doc_id, path)
        return {}

    # --- ingestion ---
    async def ingest_upload(self, file, tags: Optional[str], metadata: Optional[str]) -> dict:
        """
        文件处理主流程
        """
        logger.info("开始处理上传文档，文件名=%s，tags=%s，metadata=%s", file.filename, tags, metadata)
        doc_id = str(uuid4())
        stored_filename = f"{doc_id}_{file.filename}"
        dest_path = DOCUMENTS_DIR / stored_filename
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

        content = await file.read()
        logger.info("文件读取完成，doc_id=%s，目标路径=%s，字节大小=%s", doc_id, dest_path, len(content))
        dest_path.write_bytes(content)
        logger.info("文件已写入本地：%s", dest_path)

        pages, images = load_file(dest_path)
        logger.info("文件解析完成，页数=%s，图片数=%s", len(pages), len(images))

        doc_tags = [t.strip() for t in tags.split(",")] if tags else []
        extra_metadata = json.loads(metadata) if metadata else {}
        logger.info("标签解析完成，数量=%s；元数据键数=%s", len(doc_tags), len(extra_metadata))
        
        # 存储记录到本地文件，之后优化到数据库存储
        record_id = self.doc_manager.register(
            original_filename=file.filename,
            stored_filename=stored_filename,
            tags=doc_tags,
            metadata=extra_metadata,
            doc_id=doc_id,
        )
        logger.info("文档注册成功，record_id=%s", record_id)

        chunked = chunk_pages(pages)
        logger.info("文本切块完成，块数量=%s", len(chunked))

        # 构建图结构
        self.graph_builder.ingest_chunks(chunked, doc_id=doc_id, source=file.filename)
        logger.info("图结构构建完成，doc_id=%s", doc_id)

        # 更新持久化的图
        self.community_manager.rebuild()
        logger.info("社区图重建完成")

        full_text = "\n".join(t for _, t in pages)
        logger.info("拼接全文完成，长度=%s，准备提取关键词和摘要", len(full_text))

        # 获取关键词
        keywords = extract_keywords(full_text)
        graph_snapshot = {"nodes": self.community_manager.store.list_nodes(), "edges": self.community_manager.store.list_edges()}
        logger.info(
            "关键词提取完成，数量=%s；图节点数=%s，边数=%s",
            len(keywords),
            len(graph_snapshot.get("nodes", [])),
            len(graph_snapshot.get("edges", [])),
        )
        summary = self.llm_client.summarize(full_text[:3000]) if full_text else ""
        logger.info("摘要生成完成，摘要长度=%s", len(summary))

        self.write_meta(
            doc_id,
            {
                "keywords": keywords,
                "graph": graph_snapshot,
                "mindmap": {},
                "images": images,
                "summary": summary,
            },
        )
        logger.info("文档元数据已写入，doc_id=%s", doc_id)

        return {
            "id": record_id,
            "keywords": keywords,
            "graph": graph_snapshot,
            "mindmap": {},
            "summary": summary,
        }

    # --- query ---
    def query(self, query: str, mode: str = "optimize", top_k_cards: int = 5, max_edges: int = 80) -> Dict:
        logger.info(
            "开始图谱查询，query=%s，mode=%s，top_k_cards=%s，max_edges=%s",
            query,
            mode,
            top_k_cards,
            max_edges,
        )
        result = self.graph_retriever.answer(query=query, mode=mode, top_k_cards=top_k_cards, max_edges=max_edges)
        logger.info(
            "图谱查询完成，answer长度=%s，sources数量=%s",
            len(result.get("answer", "")),
            len(result.get("sources", [])) if isinstance(result.get("sources", []), list) else 0,
        )
        return result
