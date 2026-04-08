"""Legacy compatibility wrapper for query use cases."""

from __future__ import annotations

import application.query as application_query

from api.schemas import QueryRequest, QueryResponse


async def query_index(payload: QueryRequest) -> QueryResponse:
    """Delegate to the application-layer query implementation."""
    return await application_query.query_index(payload)
