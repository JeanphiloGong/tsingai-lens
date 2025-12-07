import logging

from fastapi import APIRouter, Depends, HTTPException

from controllers.deps.documents import get_file_service
from controllers.schemas import (
    DocumentDetailResponse,
    DocumentGraphResponse,
    DocumentKeywordsResponse,
    DocumentListResponse,
    HealthResponse,
)
from services.file_service import FileService

router = APIRouter(prefix="/graph", tags=["graph"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health():
    logger.info("graph 健康检查被调用")
    return {"status": "ok"}


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(file_svc: FileService = Depends(get_file_service)):
    logger.info("请求文档列表")
    items = []
    for d in file_svc.list():
        items.append(
            {
                "id": d.id,
                "filename": d.filename,
                "tags": getattr(d, "tags", []),
                "metadata": getattr(d, "metadata", {}),
                "created_at": d.created_at.isoformat(),
                "status": d.data.status,
                "status_message": d.data.status_message,
                "updated_at": d.updated_at.isoformat(),
                # 兼容原字段
                "original_filename": getattr(d.meta.info, "filename", ""),
            }
        )
    logger.info("文档列表返回，数量=%s", len(items))
    return {"items": items}


@router.get("/documents/{doc_id}", response_model=DocumentDetailResponse)
def get_document(doc_id: str, file_svc: FileService = Depends(get_file_service)):
    logger.info("获取文档详情，doc_id=%s", doc_id)
    doc = file_svc.get(doc_id)
    if not doc:
        logger.warning("文档未找到，doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document not found")
    meta = doc.meta
    images = []
    for img in meta.images:
        if hasattr(img, "__dict__"):
            images.append(
                {
                    "url": getattr(img, "url", ""),
                    "mime_type": getattr(img, "mime_type", None),
                    "width": getattr(img, "width", None),
                    "height": getattr(img, "height", None),
                }
            )
        else:
            images.append(img)
    meta_dict = {
        "keywords": meta.keywords,
        "graph": meta.graph,
        "mindmap": meta.mindmap,
        "images": images,
        "info": meta.info.__dict__,
    }
    logger.info("文档详情返回，doc_id=%s，元数据存在=%s", doc_id, bool(meta))
    return {
        "record": {
            "id": doc.id,
            "filename": doc.filename,
            "tags": getattr(doc, "tags", []),
            "metadata": getattr(doc, "metadata", {}),
            "created_at": doc.created_at.isoformat(),
            "status": doc.data.status,
            "status_message": doc.data.status_message,
            "updated_at": doc.updated_at.isoformat(),
            "original_filename": getattr(meta.info, "filename", ""),
        },
        "meta": meta_dict,
    }


@router.get("/documents/{doc_id}/keywords", response_model=DocumentKeywordsResponse, summary="文档关键词")
def get_keywords(doc_id: str, file_svc: FileService = Depends(get_file_service)):
    logger.info("获取文档关键词，doc_id=%s", doc_id)
    doc = file_svc.get(doc_id)
    if not doc:
        logger.warning("未找到文档，doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document not found")
    keywords = doc.meta.keywords
    logger.info("关键词返回，数量=%s", len(keywords))
    return {"keywords": keywords}


@router.get("/documents/{doc_id}/graph", response_model=DocumentGraphResponse, summary="文档图谱快照")
def get_graph(doc_id: str, file_svc: FileService = Depends(get_file_service)):
    logger.info("获取文档图谱快照，doc_id=%s", doc_id)
    doc = file_svc.get(doc_id)
    if not doc:
        logger.warning("未找到文档，doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document not found")
    meta = doc.meta
    logger.info(
        "图谱快照返回，graph节点=%s，edges=%s，mindmap_keys=%s",
        len(meta.graph.get("nodes", [])),
        len(meta.graph.get("edges", [])),
        len(meta.mindmap.keys()) if hasattr(meta.mindmap, "keys") else 0,
    )
    return {"graph": meta.graph, "mindmap": meta.mindmap}
