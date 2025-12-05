import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from controllers.schemas import (
    DocumentDetailResponse,
    DocumentGraphResponse,
    DocumentKeywordsResponse,
    DocumentListResponse,
    DocumentUploadResponse,
    HealthResponse,
    QueryResponse,
)
from controllers import deps
from services.document_manager import DocumentManager
from services.graphrag_service import GraphRAGService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse, summary="Health check")
def health() -> Dict:
    logger.info("健康检查接口被调用")
    return {"status": "ok"}


@router.get("/documents", response_model=DocumentListResponse, summary="List documents")
def list_documents(doc_manager: DocumentManager = Depends(deps.get_doc_manager)) -> Dict:
    logger.info("请求获取文档列表")
    items = doc_manager.list()
    logger.info("文档列表返回，数量=%s", len(items))
    return {"items": items}


@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    summary="Upload document and ingest into graph",
)
async def upload_document(
    file: UploadFile = File(...),
    tags: Optional[str] = Form(default=None),
    metadata: Optional[str] = Form(default=None),
    graph_service: GraphRAGService = Depends(deps.get_graph_service),
) -> DocumentUploadResponse:
    try:
        logger.info(
            "开始上传并入图库文档，文件名=%s，标签=%s，附加元数据=%s，内容类型=%s",
            file.filename,
            tags,
            metadata,
            file.content_type,
        )
        result = await graph_service.ingest_upload(file=file, tags=tags, metadata=metadata)
    except ValueError as exc:
        logger.warning("文档上传失败，原因=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("文档上传成功，生成的文档ID=%s", result.get("doc_id"))
    return DocumentUploadResponse(**result)


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentDetailResponse,
    summary="Get document record and metadata",
)
def get_document(
    doc_id: str,
    doc_manager: DocumentManager = Depends(deps.get_doc_manager),
    graph_service: GraphRAGService = Depends(deps.get_graph_service),
) -> Dict:
    logger.info("查询文档详情，doc_id=%s", doc_id)
    record = doc_manager.get(doc_id)
    if not record:
        logger.warning("文档不存在，doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document not found")
    meta = graph_service.read_meta(doc_id)
    logger.info("文档详情获取成功，包含元数据：%s", bool(meta))
    return {"record": record, "meta": meta}


@router.get(
    "/documents/{doc_id}/keywords",
    response_model=DocumentKeywordsResponse,
    summary="Get document keywords",
)
def get_keywords(doc_id: str, graph_service: GraphRAGService = Depends(deps.get_graph_service)) -> Dict:
    logger.info("获取文档关键词，doc_id=%s", doc_id)
    meta = graph_service.read_meta(doc_id)
    if not meta:
        logger.warning("未找到文档元数据，doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document metadata not found")
    keywords = meta.get("keywords", [])
    logger.info("关键词获取成功，数量=%s", len(keywords))
    return {"keywords": keywords}


@router.get(
    "/documents/{doc_id}/graph",
    response_model=DocumentGraphResponse,
    summary="Get document graph snapshot",
)
def get_graph(doc_id: str, graph_service: GraphRAGService = Depends(deps.get_graph_service)) -> Dict:
    logger.info("获取文档图谱快照，doc_id=%s", doc_id)
    meta = graph_service.read_meta(doc_id)
    if not meta:
        logger.warning("未找到文档元数据，doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document metadata not found")
    graph_data = meta.get("graph", {}) or {}
    mindmap_data = meta.get("mindmap", {}) or {}
    logger.info(
        "图谱快照获取成功，graph字段键数=%s，mindmap字段键数=%s",
        len(graph_data) if hasattr(graph_data, "__len__") else 0,
        len(mindmap_data) if hasattr(mindmap_data, "__len__") else 0,
    )
    return {"graph": graph_data, "mindmap": mindmap_data}


@router.post("/query", response_model=QueryResponse, summary="Query graph")
async def query_documents(payload: Dict, graph_service: GraphRAGService = Depends(deps.get_graph_service)) -> QueryResponse:
    query = payload.get("query")
    if not query:
        logger.warning("查询请求缺少 query 参数")
        raise HTTPException(status_code=400, detail="Missing query")
    mode = payload.get("mode", "optimize")
    top_k_cards = int(payload.get("top_k_cards", 5))
    max_edges = int(payload.get("max_edges", 80))
    logger.info(
        "开始图谱查询，query=%s，mode=%s，top_k_cards=%s，max_edges=%s",
        query,
        mode,
        top_k_cards,
        max_edges,
    )
    result = graph_service.query(query=query, mode=mode, top_k_cards=top_k_cards, max_edges=max_edges)
    sources = result.get("sources", [])
    logger.info("图谱查询完成，返回答案长度=%s，来源数量=%s", len(result.get("answer", "")), len(sources))
    return QueryResponse(answer=result["answer"], sources=sources)
