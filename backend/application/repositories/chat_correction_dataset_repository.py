"""Persistence contract for immutable Chat correction dataset manifests."""

from __future__ import annotations

from typing import Protocol

from domain.evaluation import ChatCorrectionDatasetManifest


class ChatCorrectionDatasetRepository(Protocol):
    backend_name: str

    async def save_manifest(
        self, manifest: ChatCorrectionDatasetManifest
    ) -> ChatCorrectionDatasetManifest: ...

    async def read_manifest_for_user(
        self, dataset_id: str, user_id: str
    ) -> ChatCorrectionDatasetManifest | None: ...

    async def list_manifests_for_user(
        self,
        user_id: str,
        *,
        collection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatCorrectionDatasetManifest, ...]: ...


__all__ = ["ChatCorrectionDatasetRepository"]
