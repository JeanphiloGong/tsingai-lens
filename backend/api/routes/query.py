from __future__ import annotations

from fastapi import APIRouter

import application.query as query_uc
from api.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse, summary="基于索引结果进行检索问答")
async def query_index(payload: QueryRequest) -> QueryResponse:
    return await query_uc.query_index(payload)

