from __future__ import annotations

from pathlib import Path

from infra.graphrag import collection_store
from retrieval.api import query as query_api
from retrieval.config.enums import SearchMethod
from retrieval.utils.storage import load_table_from_storage, storage_has_table


async def load_query_runtime(
    collection_id: str | None,
) -> tuple[object, str, Path, object]:
    config, resolved_collection_id = collection_store.load_collection_config(collection_id)
    base_dir = Path(getattr(config.output, "base_dir", config.root_dir))
    return config, resolved_collection_id, base_dir, config.output


async def execute_source_query(
    *,
    config: object,
    output_storage: object,
    method: SearchMethod,
    query: str,
    response_type: str | None,
    verbose: bool,
    community_level: int | None,
    dynamic_community_selection: bool,
) -> tuple[object, object]:
    if method == SearchMethod.GLOBAL:
        entities = await load_table_from_storage("entities", output_storage)
        communities = await load_table_from_storage("communities", output_storage)
        community_reports = await load_table_from_storage(
            "community_reports",
            output_storage,
        )
        return await query_api.global_search(
            config=config,
            entities=entities,
            communities=communities,
            community_reports=community_reports,
            community_level=community_level,
            dynamic_community_selection=dynamic_community_selection,
            response_type=response_type,
            query=query,
            verbose=verbose,
        )

    if method == SearchMethod.LOCAL:
        entities = await load_table_from_storage("entities", output_storage)
        communities = await load_table_from_storage("communities", output_storage)
        community_reports = await load_table_from_storage(
            "community_reports",
            output_storage,
        )
        text_units = await load_table_from_storage("text_units", output_storage)
        relationships = await load_table_from_storage("relationships", output_storage)
        covariates = None
        if await storage_has_table("covariates", output_storage):
            covariates = await load_table_from_storage("covariates", output_storage)
        return await query_api.local_search(
            config=config,
            entities=entities,
            communities=communities,
            community_reports=community_reports,
            text_units=text_units,
            relationships=relationships,
            covariates=covariates,
            community_level=community_level,
            response_type=response_type,
            query=query,
            verbose=verbose,
        )

    if method == SearchMethod.DRIFT:
        entities = await load_table_from_storage("entities", output_storage)
        communities = await load_table_from_storage("communities", output_storage)
        community_reports = await load_table_from_storage(
            "community_reports",
            output_storage,
        )
        text_units = await load_table_from_storage("text_units", output_storage)
        relationships = await load_table_from_storage("relationships", output_storage)
        return await query_api.drift_search(
            config=config,
            entities=entities,
            communities=communities,
            community_reports=community_reports,
            text_units=text_units,
            relationships=relationships,
            community_level=community_level,
            response_type=response_type,
            query=query,
            verbose=verbose,
        )

    if method == SearchMethod.BASIC:
        text_units = await load_table_from_storage("text_units", output_storage)
        return await query_api.basic_search(
            config=config,
            text_units=text_units,
            query=query,
            verbose=verbose,
        )

    raise ValueError(f"unsupported source query method: {method}")


__all__ = [
    "execute_source_query",
    "load_query_runtime",
]
