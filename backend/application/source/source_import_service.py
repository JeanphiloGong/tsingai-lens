"""Import uploaded or externally normalized papers into a Collection."""

from __future__ import annotations

import asyncio
import base64
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from application.repositories.collection_repository import CollectionRepository
from domain.source import Document
from application.repositories.object_store import ObjectStore
from infra.source.ingestion import (
    NormalizedImportBatch,
    NormalizedImportDocument,
    SourceAdapter,
    SourceAdapterRequest,
    normalize_upload,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceImportService:
    """Own upload normalization and registration of imported Documents."""

    def __init__(
        self,
        repository: CollectionRepository,
        object_store: ObjectStore,
    ) -> None:
        self.repository = repository
        self.object_store = object_store

    async def add_document(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
    ) -> dict:
        await self._get_collection(collection_id)
        batch = await asyncio.to_thread(
            normalize_upload,
            filename=filename,
            content=content,
            media_type=media_type,
        )
        imported = await self.import_normalized_batch(collection_id, batch)
        if not imported:
            raise ValueError("normalized upload produced no importable documents")
        return imported[0]

    async def import_from_adapter(
        self,
        collection_id: str,
        adapter: SourceAdapter,
        raw_locator: str,
        *,
        goal_context: dict[str, Any] | None = None,
        max_documents: int | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> list[dict]:
        await self._get_collection(collection_id)
        request = SourceAdapterRequest(
            collection_id=collection_id,
            raw_locator=raw_locator,
            goal_context=dict(goal_context) if goal_context else None,
            max_documents=max_documents,
            constraints=dict(constraints or {}),
        )
        batch = adapter.fetch(request)
        self._validate_adapter_batch(adapter, batch)
        return await self.import_normalized_batch(collection_id, batch)

    async def import_normalized_batch(
        self,
        collection_id: str,
        batch: NormalizedImportBatch,
    ) -> list[dict]:
        await self._get_collection(collection_id)
        if not batch.documents:
            raise ValueError(
                "normalized import batch must include at least one document"
            )

        text_by_source_document = self._group_text_units(batch)
        created_documents: list[Document] = []
        try:
            for document in batch.documents:
                stored_filename = document.stored_filename or (
                    f"{uuid4().hex}_{Path(document.original_filename).name}"
                )
                payload = self._build_import_payload(
                    document=document,
                    source_document_id=document.source_document_id,
                    text_by_source_document=text_by_source_document,
                )
                storage_key = self._input_storage_key(collection_id, stored_filename)
                payload_sha256 = sha256(payload).hexdigest()
                self.object_store.write(storage_key, payload, payload_sha256)
                created_documents.append(
                    Document(
                        document_id=f"doc_{uuid4().hex[:12]}",
                        original_filename=document.original_filename,
                        stored_filename=stored_filename,
                        storage_key=storage_key,
                        sha256=payload_sha256,
                        media_type=document.media_type,
                        status="stored",
                        size_bytes=len(payload),
                        created_at=_now_iso(),
                        updated_at=_now_iso(),
                    )
                )
            await self.repository.add_documents(
                collection_id,
                tuple(created_documents),
                updated_at=_now_iso(),
            )
        except Exception:
            try:
                current = await self.repository.read_collection(collection_id)
                registered_keys = {
                    record.storage_key
                    for record in (current.documents if current is not None else ())
                }
            except Exception:
                registered_keys = set()
            for record in created_documents:
                if record.storage_key not in registered_keys:
                    self.object_store.delete(record.storage_key)
            raise
        return [record.to_record() for record in created_documents]

    async def _get_collection(self, collection_id: str) -> dict[str, Any]:
        record = await self.repository.read_collection(collection_id)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record.to_record()

    @staticmethod
    def _input_storage_key(collection_id: str, stored_filename: str) -> str:
        return f"{collection_id}/input/{stored_filename}"

    @staticmethod
    def _group_text_units(
        batch: NormalizedImportBatch,
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[tuple[int, str]]] = {}
        for text_unit in batch.text_units:
            grouped.setdefault(text_unit.source_document_id, []).append(
                (int(text_unit.sequence), text_unit.text)
            )
        return {
            source_document_id: [
                text for _, text in sorted(items, key=lambda item: item[0])
            ]
            for source_document_id, items in grouped.items()
        }

    @staticmethod
    def _build_import_payload(
        document: NormalizedImportDocument,
        source_document_id: str,
        text_by_source_document: dict[str, list[str]],
    ) -> bytes:
        encoded_payload = str(document.storage_payload_base64 or "").strip()
        if encoded_payload:
            return base64.b64decode(encoded_payload)
        parts = [
            text.strip()
            for text in text_by_source_document.get(source_document_id, [])
            if text and text.strip()
        ]
        if not parts:
            raise ValueError(
                "normalized import missing text payload for source document: "
                f"{source_document_id}"
            )
        return "\n".join(parts).encode("utf-8")

    @staticmethod
    def _validate_adapter_batch(
        adapter: SourceAdapter,
        batch: NormalizedImportBatch,
    ) -> None:
        if not isinstance(batch, NormalizedImportBatch):
            raise TypeError("source adapter must return NormalizedImportBatch")
        expected_channel = str(getattr(adapter, "channel", "") or "").strip()
        expected_adapter_name = str(getattr(adapter, "adapter_name", "") or "").strip()
        expected_adapter_version = getattr(adapter, "adapter_version", None)
        if expected_channel and batch.source_metadata.channel != expected_channel:
            raise ValueError(
                "source adapter batch channel does not match adapter contract"
            )
        if (
            expected_adapter_name
            and batch.source_metadata.adapter_name != expected_adapter_name
        ):
            raise ValueError(
                "source adapter batch adapter_name does not match adapter contract"
            )
        if expected_adapter_version is not None and (
            batch.source_metadata.adapter_version != expected_adapter_version
        ):
            raise ValueError(
                "source adapter batch adapter_version does not match adapter contract"
            )


__all__ = ["SourceImportService"]
