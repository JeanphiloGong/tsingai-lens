"""In-memory current document-profile persistence."""

from __future__ import annotations

from copy import deepcopy

from domain.core import DocumentProfile


class MemoryDocumentProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[str, DocumentProfile] = {}

    async def replace(self, profile: DocumentProfile) -> None:
        self._profiles[profile.document_id] = deepcopy(profile)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        profile = self._profiles.get(document_id)
        if profile is None or profile.collection_id != collection_id:
            return None
        return deepcopy(profile)

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        selected = set(document_ids) if document_ids is not None else None
        return tuple(
            deepcopy(profile)
            for profile in sorted(
                self._profiles.values(), key=lambda item: item.document_id
            )
            if profile.collection_id == collection_id
            and (selected is None or profile.document_id in selected)
        )


__all__ = ["MemoryDocumentProfileRepository"]
