from __future__ import annotations

from fastapi import APIRouter

from application.query import service as query_service
from controllers.schemas.query import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse, summary="基于索引结果进行检索问答")
async def query_index(payload: QueryRequest) -> QueryResponse:
    return await query_service.query_index(payload)
