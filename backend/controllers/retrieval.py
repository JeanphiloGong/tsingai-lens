"""API endpoints to trigger retrieval pipelines and manage collections."""

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import Response

from app.usecases import collections as collections_uc
from app.usecases import files as files_uc
from app.usecases import graphml as graphml_uc
from app.usecases import indexing as indexing_uc
from app.usecases import inputs as inputs_uc
from app.usecases import query as query_uc
from app.usecases import reports as reports_uc
from controllers.schemas import (
    CollectionCreateRequest,
    CollectionDeleteResponse,
    CollectionFileDeleteResponse,
    CollectionFileListResponse,
    CollectionListResponse,
    CollectionRecord,
    InputUploadResponse,
    IndexRequest,
    IndexResponse,
    QueryRequest,
    QueryResponse,
    ReportCommunityDetailResponse,
    ReportCommunityListResponse,
    ReportPatternsResponse,
)
from retrieval.config.enums import IndexingMethod

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/index", response_model=IndexResponse, summary="启动标准索引流程")
async def start_indexing(request: IndexRequest) -> IndexResponse:
    """Load config and run the standard indexing pipeline."""
    return await indexing_uc.start_indexing(request)


@router.post(
    "/collections",
    response_model=CollectionRecord,
    summary="创建集合",
)
async def create_collection(payload: CollectionCreateRequest) -> CollectionRecord:
    """Create a new collection with its own config and storage folders."""
    return collections_uc.create_collection(payload)


@router.get(
    "/collections",
    response_model=CollectionListResponse,
    summary="列出集合",
)
async def list_collections() -> CollectionListResponse:
    """List available collections."""
    return collections_uc.list_collections()


@router.delete(
    "/collections/{collection_id}",
    response_model=CollectionDeleteResponse,
    summary="删除集合",
)
async def delete_collection(collection_id: str) -> CollectionDeleteResponse:
    """Delete a collection and all stored files."""
    return collections_uc.delete_collection(collection_id)


@router.post(
    "/collections/{collection_id}/files",
    response_model=InputUploadResponse,
    summary="向集合上传文件（不触发索引）",
)
async def upload_collection_files(
    collection_id: str,
    files: list[UploadFile] = File(...),
) -> InputUploadResponse:
    """Upload files into a collection without running the indexing pipeline."""
    return await files_uc.upload_collection_files(collection_id, files)


@router.get(
    "/collections/{collection_id}/files",
    response_model=CollectionFileListResponse,
    summary="列出集合文件",
)
async def list_collection_files(collection_id: str) -> CollectionFileListResponse:
    """List input files within a collection."""
    return await files_uc.list_collection_files(collection_id)


@router.delete(
    "/collections/{collection_id}/files",
    response_model=CollectionFileDeleteResponse,
    summary="删除集合文件",
)
async def delete_collection_file(
    collection_id: str,
    key: str = Query(..., description="文件 key（如 uploads/<uuid>_<name>.txt）"),
) -> CollectionFileDeleteResponse:
    """Delete a single input file from a collection."""
    return await files_uc.delete_collection_file(collection_id, key)


@router.get(
    "/collections/{collection_id}/reports/communities",
    response_model=ReportCommunityListResponse,
    summary="列出社区报告",
)
async def list_community_reports(
    collection_id: str,
    level: int | None = Query(default=2, description="社区层级"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    min_size: int = Query(default=0, ge=0, description="最小社区规模过滤"),
    sort: str | None = Query(default="rating", description="排序字段（rating/size）"),
) -> ReportCommunityListResponse:
    """List community summaries for a collection."""
    return reports_uc.list_community_reports(
        collection_id=collection_id,
        level=level,
        limit=limit,
        offset=offset,
        min_size=min_size,
        sort=sort,
    )


@router.get(
    "/collections/{collection_id}/reports/communities/{community_id}",
    response_model=ReportCommunityDetailResponse,
    summary="社区报告详情",
)
async def get_community_report_detail(
    collection_id: str,
    community_id: str,
    level: int | None = Query(default=None, description="指定社区层级"),
    entity_limit: int = Query(default=20, ge=1, le=200, description="实体返回数量"),
    relationship_limit: int = Query(
        default=20, ge=1, le=200, description="关系返回数量"
    ),
    document_limit: int = Query(default=20, ge=1, le=200, description="文档返回数量"),
) -> ReportCommunityDetailResponse:
    """Get community report detail for a collection."""
    return reports_uc.get_community_report_detail(
        collection_id=collection_id,
        community_id=community_id,
        level=level,
        entity_limit=entity_limit,
        relationship_limit=relationship_limit,
        document_limit=document_limit,
    )


@router.get(
    "/collections/{collection_id}/reports/patterns",
    response_model=ReportPatternsResponse,
    summary="社区规律概览",
)
async def list_patterns(
    collection_id: str,
    level: int | None = Query(default=2, description="社区层级"),
    limit: int = Query(default=10, ge=1, le=50, description="返回数量"),
    sort: str | None = Query(default="rating", description="排序字段（rating/size）"),
) -> ReportPatternsResponse:
    """List pattern summaries derived from community reports."""
    return reports_uc.list_patterns(
        collection_id=collection_id,
        level=level,
        limit=limit,
        sort=sort,
    )


@router.post(
    "/index/upload",
    response_model=IndexResponse,
    summary="上传文件并启动标准索引流程",
)
async def upload_and_index(
    file: UploadFile = File(...),
    collection_id: str | None = Form(None),
    method: IndexingMethod | str = Form(IndexingMethod.Standard),
    is_update_run: bool = Form(False),
    verbose: bool = Form(False),
) -> IndexResponse:
    """Upload a document to the configured input storage and run the pipeline."""
    return await indexing_uc.upload_and_index(
        file,
        collection_id,
        method,
        is_update_run,
        verbose,
    )


@router.post(
    "/input/upload",
    response_model=InputUploadResponse,
    summary="批量上传文件到输入存储（不触发索引）",
)
async def upload_inputs(
    collection_id: str | None = Form(None),
    files: list[UploadFile] = File(...),
) -> InputUploadResponse:
    """Upload files into input storage without running the indexing pipeline."""
    return await inputs_uc.upload_inputs(collection_id, files)


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="基于索引结果进行检索问答",
)
async def query_index(payload: QueryRequest) -> QueryResponse:
    """Query indexed outputs and return an answer with optional context data."""
    return await query_uc.query_index(payload)


@router.get(
    "/graphml",
    summary="导出知识图谱 GraphML 格式",
)
async def export_graphml(
    collection_id: str | None = Query(default=None, description="集合 ID"),
    max_nodes: int = Query(
        default=200, ge=1, le=2000, description="限制返回的最大节点数以避免过大响应"
    ),
    min_weight: float = Query(
        default=0.0, ge=0.0, description="按关系权重过滤（包含阈值）"
    ),
    community_id: str | None = Query(
        default=None,
        description="社区过滤（可传 id 或 human_readable_id / community 数值）",
    ),
    include_community: bool = Query(
        default=True,
        description="是否在 GraphML 节点上包含 community 字段（用于 Gephi 分组着色）",
    ),
) -> Response:
    """
    Export the knowledge graph as GraphML for tools like Gephi.

    It supports filtering options for max_nodes, min_weight, and community_id.
    Use include_community to attach community IDs to nodes for Gephi coloring.
    """
    result = graphml_uc.export_graphml(
        collection_id,
        max_nodes,
        min_weight,
        community_id,
        include_community,
    )

    return Response(
        content=result.content,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
