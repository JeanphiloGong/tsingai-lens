from __future__ import annotations

import logging

from fastapi import HTTPException

from application.source.query_runtime_service import (
    execute_source_query,
    load_query_runtime,
)
from controllers.schemas.query import QueryRequest, QueryResponse
from retrieval.config.enums import SearchMethod
from retrieval.utils.api import create_storage_from_config, reformat_context_data

logger = logging.getLogger(__name__)


async def query_index(payload: QueryRequest) -> QueryResponse:
    """Query indexed outputs and return an answer with optional context data."""
    if not payload.query:
        raise HTTPException(status_code=400, detail="query 不能为空")

    config, collection_id, base_dir, source_output_config = await load_query_runtime(
        payload.collection_id
    )
    output_storage = create_storage_from_config(source_output_config)

    try:
        method = (
            SearchMethod(payload.method)
            if isinstance(payload.method, str)
            else payload.method
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支持的检索方法") from exc
    community_level = payload.community_level if payload.community_level is not None else 2

    try:
        response, context_data = await execute_source_query(
            config=config,
            output_storage=output_storage,
            method=method,
            query=payload.query,
            response_type=payload.response_type,
            verbose=payload.verbose,
            community_level=community_level,
            dynamic_community_selection=payload.dynamic_community_selection,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Query execution failed")
        raise HTTPException(status_code=500, detail=f"查询执行失败: {exc}") from exc

    context_payload = None
    if payload.include_context:
        if isinstance(context_data, dict):
            context_payload = reformat_context_data(context_data)
        else:
            context_payload = context_data  # type: ignore[assignment]

    return QueryResponse(
        answer=response,
        method=str(method),
        collection_id=collection_id,
        output_path=str(base_dir),
        context_data=context_payload,
    )


__all__ = ["query_index"]
