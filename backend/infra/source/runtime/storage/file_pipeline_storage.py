# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""File-backed storage used by the Source runtime."""

import logging
import os
import re
import shutil
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import aiofiles
from aiofiles.os import remove
from aiofiles.ospath import exists

from infra.source.runtime.storage.pipeline_storage import (
    PipelineStorage,
    get_timestamp_formatted_with_local_tz,
)

logger = logging.getLogger(__name__)


class FilePipelineStorage(PipelineStorage):
    """File-backed Source runtime storage."""

    _root_dir: str
    _encoding: str

    def __init__(self, **kwargs: Any) -> None:
        self._root_dir = kwargs.get("base_dir", "")
        self._encoding = kwargs.get("encoding", "utf-8")
        logger.debug("Creating file storage at %s", self._root_dir)
        Path(self._root_dir).mkdir(parents=True, exist_ok=True)

    def find(
        self,
        file_pattern: re.Pattern[str],
        base_dir: str | None = None,
        file_filter: dict[str, Any] | None = None,
        max_count: int = -1,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Find files in storage using a pattern and optional filter."""

        def item_filter(item: dict[str, Any]) -> bool:
            if file_filter is None:
                return True
            return all(re.search(value, item[key]) for key, value in file_filter.items())

        search_path = Path(self._root_dir) / (base_dir or "")
        all_files = list(search_path.rglob("**/*"))
        num_loaded = 0
        for file in all_files:
            match = file_pattern.search(f"{file}")
            if match is None:
                continue
            groups = match.groupdict()
            if not item_filter(groups):
                continue
            filename = f"{file}".replace(self._root_dir, "")
            if filename.startswith(os.sep):
                filename = filename[1:]
            yield filename, groups
            num_loaded += 1
            if max_count > 0 and num_loaded >= max_count:
                break

    async def get(
        self, key: str, as_bytes: bool | None = False, encoding: str | None = None
    ) -> Any:
        file_path = join_path(self._root_dir, key)
        if await self.has(key):
            return await self._read_file(file_path, as_bytes, encoding)
        if await exists(key):
            return await self._read_file(key, as_bytes, encoding)
        return None

    async def _read_file(
        self,
        path: str | Path,
        as_bytes: bool | None = False,
        encoding: str | None = None,
    ) -> Any:
        read_type = "rb" if as_bytes else "r"
        encoding = None if as_bytes else (encoding or self._encoding)
        async with aiofiles.open(
            path,
            cast("Any", read_type),
            encoding=encoding,
        ) as handle:
            return await handle.read()

    async def set(self, key: str, value: Any, encoding: str | None = None) -> None:
        is_bytes = isinstance(value, bytes)
        write_type = "wb" if is_bytes else "w"
        encoding = None if is_bytes else encoding or self._encoding
        file_path = join_path(self._root_dir, key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(
            file_path,
            cast("Any", write_type),
            encoding=encoding,
        ) as handle:
            await handle.write(value)

    async def has(self, key: str) -> bool:
        return await exists(join_path(self._root_dir, key))

    async def delete(self, key: str) -> None:
        if await self.has(key):
            await remove(join_path(self._root_dir, key))

    async def clear(self) -> None:
        for file in Path(self._root_dir).glob("*"):
            if file.is_dir():
                shutil.rmtree(file)
            else:
                file.unlink()

    def child(self, name: str | None) -> "PipelineStorage":
        if name is None:
            return self
        child_path = str(Path(self._root_dir) / Path(name))
        return FilePipelineStorage(base_dir=child_path, encoding=self._encoding)

    def keys(self) -> list[str]:
        return [item.name for item in Path(self._root_dir).iterdir() if item.is_file()]

    async def get_creation_date(self, key: str) -> str:
        file_path = Path(join_path(self._root_dir, key))
        creation_timestamp = file_path.stat().st_ctime
        creation_time_utc = datetime.fromtimestamp(creation_timestamp, tz=timezone.utc)
        return get_timestamp_formatted_with_local_tz(creation_time_utc)


def join_path(file_path: str, file_name: str) -> Path:
    """Join a path and a file name."""
    return Path(file_path) / Path(file_name).parent / Path(file_name).name
