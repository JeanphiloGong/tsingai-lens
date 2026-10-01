# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Document inventory loading helpers."""

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from infra.source.hashing import gen_sha512_hash
from infra.source.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)


async def load_document_inventory(
    config: Any,
    storage: FileStorage,
) -> pd.DataFrame:
    """Load the configured document inventory from file storage."""
    logger.info("loading input from root_dir=%s", config.storage.base_dir)
    file_type = _normalize_enum_value(config.file_type)
    if file_type != "document":
        raise ValueError(f"Unknown input type {file_type}; expected document")
    return await load_documents(config, storage)


async def load_documents(config: Any, storage: FileStorage) -> pd.DataFrame:
    """Load mixed document inventories from storage without flattening binaries."""

    async def load_file(path: str, group: dict[str, Any] | None = None) -> pd.DataFrame:
        group = group or {}
        suffix = Path(path).suffix.lower()
        new_item = {
            **group,
            "source_path": path,
            "source_type": suffix.lstrip("."),
        }
        if suffix == ".txt":
            new_item["text"] = await storage.get(path, encoding=config.encoding)
        elif suffix == ".pdf":
            new_item["text"] = None
        else:
            raise ValueError(f"unsupported document input: {path}")
        new_item["id"] = gen_sha512_hash(
            {"source_path": path, "title": str(Path(path).name)},
            ["source_path", "title"],
        )
        new_item["title"] = str(Path(path).name)
        new_item["creation_date"] = await storage.get_creation_date(path)
        return pd.DataFrame([new_item])

    return await load_files(load_file, config, storage)


async def load_files(
    loader: Any,
    config: Any,
    storage: FileStorage,
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
    load_failures: list[dict[str, str]] = []
    for file, group in files:
        try:
            files_loaded.append(await loader(file, group))
        except Exception as exc:  # noqa: BLE001
            failure = {
                "source_path": str(file),
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            load_failures.append(failure)
            logger.warning(
                "Source input could not be loaded source_path=%s error_type=%s",
                file,
                type(exc).__name__,
                exc_info=True,
            )

    logger.info(
        "Found %d %s files, loading %d", len(files), file_type, len(files_loaded)
    )
    if not files_loaded:
        raise RuntimeError(
            f"All {len(load_failures)} {file_type} input files failed to load."
        )
    result = pd.concat(files_loaded)
    result.attrs["load_failures"] = load_failures
    logger.info("Total number of unfiltered %s rows: %d", file_type, len(result))
    return result


def _normalize_enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))
