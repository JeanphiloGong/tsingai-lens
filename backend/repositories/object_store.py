from __future__ import annotations

from typing import Protocol


class ObjectStore(Protocol):
    def write(self, storage_key: str, payload: bytes, sha256: str) -> None: ...

    def read(self, storage_key: str, sha256: str) -> bytes: ...

    def delete(self, storage_key: str) -> None: ...
