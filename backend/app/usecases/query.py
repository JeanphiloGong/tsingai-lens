"""Query use cases for indexed outputs."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

from app.services import collection_store
from controllers.schemas import QueryRequest, QueryResponse
from retrieval.api import query as query_api
from retrieval.config.enums import SearchMethod
from retrieval.utils.api import create_storage_from_config, reformat_context_data
from retrieval.utils.storage import load_table_from_storage, storage_has_table

logger = logging.getLogger(__name__)


async def query_index(payload: QueryRequest) -> QueryResponse:
    """Query indexed outputs and return an answer with optional context data."""
    if not payload.query:
        raise HTTPException(status_code=400, detail="query 不能为空")

    config, collection_id = collection_store.load_collection_config(payload.collection_id)
    base_dir = Path(getattr(config.output, "base_dir", config.root_dir))
    output_storage = create_storage_from_config(config.output)

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
        if method == SearchMethod.GLOBAL:
            entities = await load_table_from_storage("entities", output_storage)
            communities = await load_table_from_storage("communities", output_storage)
            community_reports = await load_table_from_storage(
                "community_reports", output_storage
            )
            response, context_data = await query_api.global_search(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                community_level=payload.community_level,
                dynamic_community_selection=payload.dynamic_community_selection,
                response_type=payload.response_type,
                query=payload.query,
                verbose=payload.verbose,
            )
        elif method == SearchMethod.LOCAL:
            entities = await load_table_from_storage("entities", output_storage)
            communities = await load_table_from_storage("communities", output_storage)
            community_reports = await load_table_from_storage(
                "community_reports", output_storage
            )
            text_units = await load_table_from_storage("text_units", output_storage)
            relationships = await load_table_from_storage("relationships", output_storage)
            covariates = None
            if await storage_has_table("covariates", output_storage):
                covariates = await load_table_from_storage("covariates", output_storage)
            response, context_data = await query_api.local_search(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                text_units=text_units,
                relationships=relationships,
                covariates=covariates,
                community_level=community_level,
                response_type=payload.response_type,
                query=payload.query,
                verbose=payload.verbose,
            )
        elif method == SearchMethod.DRIFT:
            entities = await load_table_from_storage("entities", output_storage)
            communities = await load_table_from_storage("communities", output_storage)
            community_reports = await load_table_from_storage(
                "community_reports", output_storage
            )
            text_units = await load_table_from_storage("text_units", output_storage)
            relationships = await load_table_from_storage("relationships", output_storage)
            response, context_data = await query_api.drift_search(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                text_units=text_units,
                relationships=relationships,
                community_level=community_level,
                response_type=payload.response_type,
                query=payload.query,
                verbose=payload.verbose,
            )
        elif method == SearchMethod.BASIC:
            text_units = await load_table_from_storage("text_units", output_storage)
            response, context_data = await query_api.basic_search(
                config=config,
                text_units=text_units,
                query=payload.query,
                verbose=payload.verbose,
            )
        else:
            raise HTTPException(status_code=400, detail="不支持的检索方法")
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
