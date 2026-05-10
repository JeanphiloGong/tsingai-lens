# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Table read/write helpers for Source runtime scratch storage."""

import json
import logging
import math
from typing import Any, Mapping

import pandas as pd

from infra.source.runtime.storage.pipeline_storage import PipelineStorage

logger = logging.getLogger(__name__)


async def load_table_from_storage(name: str, storage: PipelineStorage) -> pd.DataFrame:
    """Load a JSON table from storage."""
    filename = f"{name}.json"
    if not await storage.has(filename):
        raise ValueError(f"Could not find {filename} in storage!")
    try:
        logger.debug("reading table from storage: %s", filename)
        payload = await storage.get(filename, as_bytes=True)
        text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        decoded = json.loads(text)
        columns = decoded.get("columns") if isinstance(decoded, dict) else None
        records = decoded.get("records") if isinstance(decoded, dict) else None
        if not isinstance(columns, list) or not isinstance(records, list):
            raise ValueError(f"invalid table payload: {filename}")
        return pd.DataFrame(records, columns=[str(column) for column in columns])
    except Exception:
        logger.exception("error loading table from storage: %s", filename)
        raise


async def write_table_to_storage(
    table: pd.DataFrame, name: str, storage: PipelineStorage
) -> None:
    """Write a JSON table to storage."""
    payload = {
        "columns": [str(column) for column in table.columns],
        "records": [
            {str(key): _jsonable(value) for key, value in row.items()}
            for row in table.to_dict(orient="records")
        ],
    }
    await storage.set(
        f"{name}.json",
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    )


async def delete_table_from_storage(name: str, storage: PipelineStorage) -> None:
    """Delete a table from storage."""
    await storage.delete(f"{name}.json")


async def storage_has_table(name: str, storage: PipelineStorage) -> bool:
    """Check if a table exists in storage."""
    return await storage.has(f"{name}.json")


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray, Mapping)):
        try:
            return _jsonable(value.tolist())
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value
