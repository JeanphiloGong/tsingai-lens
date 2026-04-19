# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Source runtime input loading helpers."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pandas as pd

from infra.source.runtime.hashing import gen_sha512_hash
from infra.source.runtime.storage.pipeline_storage import PipelineStorage

logger = logging.getLogger(__name__)


async def create_input(
    config: Any,
    storage: PipelineStorage,
) -> pd.DataFrame:
    """Instantiate input data for the Source runtime."""
    logger.info("loading input from root_dir=%s", config.storage.base_dir)

    loaders: dict[str, Callable[..., Awaitable[pd.DataFrame]]] = {
        "text": load_text,
        "csv": load_csv,
        "json": load_json,
    }
    file_type = _normalize_enum_value(config.file_type)
    if file_type not in loaders:
        raise ValueError(f"Unknown input type {file_type}")

    result = await loaders[file_type](config, storage)
    if config.metadata:
        if all(col in result.columns for col in config.metadata):
            result["metadata"] = result[config.metadata].apply(
                lambda row: row.to_dict(), axis=1
            )
        else:
            raise ValueError("One or more metadata columns not found in the DataFrame.")
        result[config.metadata] = result[config.metadata].astype(str)

    return cast("pd.DataFrame", result)


async def load_text(config: Any, storage: PipelineStorage) -> pd.DataFrame:
    """Load text inputs from storage."""

    async def load_file(path: str, group: dict[str, Any] | None = None) -> pd.DataFrame:
        group = group or {}
        text = await storage.get(path, encoding=config.encoding)
        new_item = {**group, "text": text}
        new_item["id"] = gen_sha512_hash(new_item, new_item.keys())
        new_item["title"] = str(Path(path).name)
        new_item["creation_date"] = await storage.get_creation_date(path)
        return pd.DataFrame([new_item])

    return await load_files(load_file, config, storage)


async def load_csv(config: Any, storage: PipelineStorage) -> pd.DataFrame:
    """Load csv inputs from storage."""
    logger.info("Loading csv files from %s", config.storage.base_dir)

    async def load_file(path: str, group: dict[str, Any] | None) -> pd.DataFrame:
        group = group or {}
        buffer = BytesIO(await storage.get(path, as_bytes=True))
        data = pd.read_csv(buffer, encoding=config.encoding)
        additional_keys = group.keys()
        if additional_keys:
            data[[*additional_keys]] = data.apply(
                lambda _row: pd.Series([group[key] for key in additional_keys]), axis=1
            )

        data = process_data_columns(data, config, path)
        creation_date = await storage.get_creation_date(path)
        data["creation_date"] = data.apply(lambda _: creation_date, axis=1)
        return data

    return await load_files(load_file, config, storage)


async def load_json(config: Any, storage: PipelineStorage) -> pd.DataFrame:
    """Load json inputs from storage."""
    logger.info("Loading json files from %s", config.storage.base_dir)

    async def load_file(path: str, group: dict[str, Any] | None) -> pd.DataFrame:
        group = group or {}
        text = await storage.get(path, encoding=config.encoding)
        as_json = json.loads(text)
        rows = as_json if isinstance(as_json, list) else [as_json]
        data = pd.DataFrame(rows)

        additional_keys = group.keys()
        if additional_keys:
            data[[*additional_keys]] = data.apply(
                lambda _row: pd.Series([group[key] for key in additional_keys]), axis=1
            )

        data = process_data_columns(data, config, path)
        creation_date = await storage.get_creation_date(path)
        data["creation_date"] = data.apply(lambda _: creation_date, axis=1)
        return data

    return await load_files(load_file, config, storage)


async def load_files(
    loader: Any,
    config: Any,
    storage: PipelineStorage,
) -> pd.DataFrame:
    """Load files from storage and apply a loader function."""
    files = list(
        storage.find(
            re.compile(config.file_pattern),
            file_filter=config.file_filter,
        )
    )

    file_type = _normalize_enum_value(config.file_type)
    if not files:
        raise ValueError(f"No {file_type} files found in {config.storage.base_dir}")

    files_loaded = []
    for file, group in files:
        try:
            files_loaded.append(await loader(file, group))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Warning! Error loading file %s. Skipping...", file)
            logger.warning("Error: %s", exc)

    logger.info(
        "Found %d %s files, loading %d", len(files), file_type, len(files_loaded)
    )
    result = pd.concat(files_loaded)
    logger.info("Total number of unfiltered %s rows: %d", file_type, len(result))
    return result


def process_data_columns(
    documents: pd.DataFrame, config: Any, path: str
) -> pd.DataFrame:
    """Process configured data columns of a DataFrame."""
    if "id" not in documents.columns:
        documents["id"] = documents.apply(
            lambda row: gen_sha512_hash(row, row.keys()), axis=1
        )
    if config.text_column is not None and "text" not in documents.columns:
        if config.text_column not in documents.columns:
            logger.warning(
                "text_column %s not found in input file %s",
                config.text_column,
                path,
            )
        else:
            documents["text"] = documents.apply(lambda row: row[config.text_column], axis=1)
    if config.title_column is not None:
        if config.title_column not in documents.columns:
            logger.warning(
                "title_column %s not found in input file %s",
                config.title_column,
                path,
            )
        else:
            documents["title"] = documents.apply(
                lambda row: row[config.title_column], axis=1
            )
    else:
        documents["title"] = documents.apply(lambda _: path, axis=1)
    return documents


def _normalize_enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))
