import logging
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from controllers.deps.documents import get_file_service, get_ingestion_workflow
from controllers.schemas.file import FileStatusResponse, FileUploadResponse
from services.file_service import FileService
from services.workflows import IngestionWorkflow

router = APIRouter(prefix="/file", tags=["file"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=FileUploadResponse, summary="上传并入图")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    tags: Optional[str] = Form(default=None),
    metadata: Optional[str] = Form(default=None),
    workflow: IngestionWorkflow = Depends(get_ingestion_workflow),
    file_svc: FileService = Depends(get_file_service),
):
    doc_id = str(uuid4())
    stored = f"{doc_id}_{file.filename}"
    logger.info(
        "接收上传请求，doc_id=%s, filename=%s, content_type=%s, tags=%s, metadata_present=%s",
        doc_id,
        file.filename,
        file.content_type,
        tags,
        metadata is not None,
    )
    content = await file.read()
    logger.info("读取上传内容完成，doc_id=%s，字节大小=%s", doc_id, len(content))

    # 保存文件
    file_svc.save_file(stored, content)
    logger.info("文件已保存，doc_id=%s，stored_filename=%s", doc_id, stored)

    # 注册文档,初始状态content
    file_svc.register_document(
        doc_id=doc_id,
        stored_filename=stored,
        original_filename=file.filename,
        mime_type=file.content_type,
        size=len(content),
    )
    file_svc.update_status(doc_id, "pending", "等待处理")
    logger.info("文档注册成功并标记 pending，doc_id=%s", doc_id)

    # 后台处理
    background_tasks.add_task(
        workflow.process_in_background,
        doc_id,
        stored,
        file.filename,
        tags,
        metadata,
    )
    logger.info("后台处理任务已提交，doc_id=%s", doc_id)
    return {
        "id": doc_id,
        "status": "pending",
    }


@router.get("/status/{doc_id}", response_model=FileStatusResponse, summary="查询文件处理状态")
def get_status(doc_id: str, file_svc: FileService = Depends(get_file_service)):
    doc = file_svc.get(doc_id)
    if not doc:
        logger.warning("查询状态失败，未找到文档，doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="文档记录未找到")
    logger.info("返回处理状态，doc_id=%s，status=%s，message=%s", doc_id, doc.data.status, doc.data.status_message)
    return {
        "id": doc.id,
        "status": doc.data.status,
        "status_message": doc.data.status_message,
        "updated_at": doc.updated_at.isoformat(),
    }
