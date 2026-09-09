"""Shared pagination for immutable Objective analysis records."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar


RecordT = TypeVar("RecordT")
_PAGE_SIZE = 500


async def list_all_evidence(
    repository: Any,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    error_message: str = "objective Evidence pagination did not advance",
) -> tuple[RecordT, ...]:
    return await _list_all(
        lambda *, offset, limit: repository.list_evidence(
            collection_id,
            objective_id,
            analysis_version,
            offset=offset,
            limit=limit,
        ),
        error_message=error_message,
    )


async def list_all_findings(
    repository: Any,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    error_message: str = "objective Finding pagination did not advance",
) -> tuple[RecordT, ...]:
    return await _list_all(
        lambda *, offset, limit: repository.list_findings(
            collection_id,
            objective_id,
            analysis_version,
            offset=offset,
            limit=limit,
        ),
        error_message=error_message,
    )


async def _list_all(
    fetch_page: Callable[..., Awaitable[tuple[list[RecordT], int]]],
    *,
    error_message: str,
) -> tuple[RecordT, ...]:
    records: list[RecordT] = []
    while True:
        page, total = await fetch_page(offset=len(records), limit=_PAGE_SIZE)
        records.extend(page)
        if len(records) >= total:
            return tuple(records)
        if not page:
            raise RuntimeError(error_message)


__all__ = ["list_all_evidence", "list_all_findings"]
