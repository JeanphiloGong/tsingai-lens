from __future__ import annotations

from typing import Protocol

from domain.core.document_profile import DocumentProfile


class DocumentProfileRepository(Protocol):
    async def replace(
        self,
        collection_id: str,
        profile: DocumentProfile,
    ) -> None: ...

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None: ...

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]: ...
