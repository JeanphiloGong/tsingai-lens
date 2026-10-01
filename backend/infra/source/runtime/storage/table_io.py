# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Write Source artifact tables to parser scratch storage."""

import json
import math
from typing import Any, Mapping

import pandas as pd

from infra.source.runtime.storage.file_pipeline_storage import FilePipelineStorage


async def write_table_to_storage(
    table: pd.DataFrame, name: str, storage: FilePipelineStorage
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
