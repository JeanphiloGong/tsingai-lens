from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from domain.ports import ArtifactRepository, CollectionPaths, CollectionRepository
from domain.source import ArtifactStatusRecord, CollectionRecord, empty_import_manifest
from infra.source.ingestion import (
    NormalizedImportBatch,
    SourceAdapter,
    SourceAdapterRequest,
    normalize_upload,
)
from infra.persistence.factory import (
    build_artifact_repository,
    build_collection_repository,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectionService:
    """File-backed collection registry for the application layer."""

    def __init__(
        self,
        root_dir: Path | None = None,
        repository: CollectionRepository | None = None,
        artifact_repository: ArtifactRepository | None = None,
    ) -> None:
        self.repository = repository or build_collection_repository(root_dir)
        self.artifact_repository = (
            artifact_repository
            or build_artifact_repository(
                self.repository.root_dir,
                backend=self.repository.backend_name,
            )
        )
        self.root_dir = self.repository.root_dir

    def get_paths(self, collection_id: str) -> CollectionPaths:
        return self.repository.get_paths(collection_id)

    def create_collection(
        self,
        name: str,
        description: str | None = None,
    ) -> dict:
        collection_id = f"col_{uuid4().hex[:12]}"
        now = _now_iso()
        record = CollectionRecord.create(
            collection_id=collection_id,
            name=name,
            description=description,
            now_iso=now,
        ).to_record()
        paths = self.repository.create_collection_dirs(collection_id)
        self.repository.write_collection(collection_id, record)
        self.repository.write_files(collection_id, [])
        self.artifact_repository.write(
            collection_id,
            ArtifactStatusRecord.empty(
                collection_id=collection_id,
                output_path=str(paths.output_dir),
                updated_at=now,
            ).to_record(),
        )
        return record

    def list_collections(self) -> list[dict]:
        items: list[dict] = []
        for collection_id, record in self.repository.list_collection_records():
            record = CollectionRecord.from_mapping(
                record,
                collection_id,
                now_iso=_now_iso(),
            ).to_record()
            items.append(record)
        return items

    def get_collection(self, collection_id: str) -> dict:
        record = self.repository.read_collection(collection_id)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        normalized = CollectionRecord.from_mapping(
            record,
            collection_id,
            now_iso=_now_iso(),
        ).to_record()
        if normalized != record:
            self.repository.write_collection(collection_id, normalized)
        return normalized

    def update_collection(self, collection_id: str, **fields) -> dict:
        record = dict(self.get_collection(collection_id))
        record.update(fields)
        record["updated_at"] = _now_iso()
        normalized = CollectionRecord.from_mapping(
            record,
            collection_id,
            now_iso=record["updated_at"],
        ).to_record()
        self.repository.write_collection(collection_id, normalized)
        return normalized

    def delete_collection(self, collection_id: str) -> dict:
        paths = self.get_paths(collection_id)
        target_dir = paths.collection_dir
        if not self.repository.collection_exists(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")

        resolved_root = self.root_dir.resolve()
        resolved_target = target_dir.resolve()
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("invalid collection path") from exc
        if target_dir.is_symlink():
            raise ValueError("collection path cannot be a symlink")

        self.repository.delete_collection_dir(collection_id)
        return {
            "collection_id": collection_id,
            "deleted_at": _now_iso(),
        }

    def list_files(self, collection_id: str) -> list[dict]:
        files = self.repository.read_files(collection_id)
        if files is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return files

    def get_import_manifest(self, collection_id: str) -> dict[str, Any]:
        self.get_collection(collection_id)
        manifest = self.repository.read_import_manifest(collection_id)
        if manifest is None:
            return empty_import_manifest(collection_id)
        return manifest

    def register_goal_brief_handoff(
        self,
        collection_id: str,
        research_brief: dict[str, Any],
        coverage_assessment: dict[str, Any],
        *,
        source_channels: list[str] | None = None,
    ) -> dict[str, Any]:
        self.get_collection(collection_id)
        manifest = self.get_import_manifest(collection_id)
        handoff = {
            "handoff_id": f"handoff_{uuid4().hex[:12]}",
            "kind": "goal_brief",
            "status": "awaiting_source_material",
            "created_at": _now_iso(),
            "source_channels": list(source_channels or ["upload"]),
            "goal_context": {
                "research_brief": dict(research_brief),
                "coverage_assessment": dict(coverage_assessment),
            },
        }
        manifest["handoffs"].append(handoff)
        self.repository.write_import_manifest(collection_id, manifest)
        return handoff

    def import_from_adapter(
        self,
        collection_id: str,
        adapter: SourceAdapter,
        raw_locator: str,
        *,
        goal_context: dict[str, Any] | None = None,
        max_documents: int | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> list[dict]:
        if not self.repository.collection_exists(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")

        request = SourceAdapterRequest(
            collection_id=collection_id,
            raw_locator=raw_locator,
            goal_context=dict(goal_context) if goal_context else None,
            max_documents=max_documents,
            constraints=dict(constraints or {}),
        )
        batch = adapter.fetch(request)
        self._validate_adapter_batch(adapter, batch)
        return self.import_normalized_batch(collection_id, batch)

    def import_normalized_batch(
        self,
        collection_id: str,
        batch: NormalizedImportBatch,
    ) -> list[dict]:
        if not self.repository.collection_exists(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        if not batch.documents:
            raise ValueError("normalized import batch must include at least one document")

        files = self.repository.read_files(collection_id) or []
        text_by_source_document = self._group_text_units(batch)
        created_records: list[dict] = []
        paths = self.repository.get_paths(collection_id)

        for document in batch.documents:
            stored_filename = document.stored_filename or f"{uuid4().hex}_{Path(document.original_filename).name}"
            payload = self._build_import_payload(
                document=document,
                source_document_id=document.source_document_id,
                text_by_source_document=text_by_source_document,
            )
            stored_path = self.repository.write_input_file(
                collection_id,
                stored_filename,
                payload,
            )
            created_records.append(
                {
                    "file_id": f"file_{uuid4().hex[:12]}",
                    "collection_id": collection_id,
                    "original_filename": document.original_filename,
                    "stored_filename": stored_filename,
                    "stored_path": str(stored_path),
                    "media_type": document.media_type,
                    "status": "stored",
                    "size_bytes": len(payload),
                    "created_at": _now_iso(),
                }
            )

        files.extend(created_records)
        self.repository.write_files(collection_id, files)
        manifest = self.get_import_manifest(collection_id)
        manifest["imports"].append(
            self._build_manifest_import_entry(
                collection_dir=paths.collection_dir,
                batch=batch,
                created_records=created_records,
            )
        )
        self.repository.write_import_manifest(collection_id, manifest)
        self.update_collection(collection_id, paper_count=len(files), status="ready")
        return created_records

    def add_file(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
    ) -> dict:
        if not self.repository.collection_exists(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        batch = normalize_upload(
            filename=filename,
            content=content,
            media_type=media_type,
        )
        imported = self.import_normalized_batch(collection_id, batch)
        if not imported:
            raise ValueError("normalized upload produced no importable documents")
        return imported[0]

    def _group_text_units(
        self,
        batch: NormalizedImportBatch,
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[tuple[int, str]]] = {}
        for text_unit in batch.text_units:
            grouped.setdefault(text_unit.source_document_id, []).append(
                (int(text_unit.sequence), text_unit.text)
            )
        return {
            source_document_id: [
                text
                for _, text in sorted(items, key=lambda item: item[0])
            ]
            for source_document_id, items in grouped.items()
        }

    def _build_import_payload(
        self,
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
                f"normalized import missing text payload for source document: {source_document_id}"
            )
        return "\n".join(parts).encode("utf-8")

    def _validate_adapter_batch(
        self,
        adapter: SourceAdapter,
        batch: NormalizedImportBatch,
    ) -> None:
        if not isinstance(batch, NormalizedImportBatch):
            raise TypeError("source adapter must return NormalizedImportBatch")

        expected_channel = str(getattr(adapter, "channel", "") or "").strip()
        expected_adapter_name = str(getattr(adapter, "adapter_name", "") or "").strip()
        expected_adapter_version = getattr(adapter, "adapter_version", None)

        if expected_channel and batch.source_metadata.channel != expected_channel:
            raise ValueError("source adapter batch channel does not match adapter contract")
        if expected_adapter_name and batch.source_metadata.adapter_name != expected_adapter_name:
            raise ValueError("source adapter batch adapter_name does not match adapter contract")
        if expected_adapter_version is not None and (
            batch.source_metadata.adapter_version != expected_adapter_version
        ):
            raise ValueError("source adapter batch adapter_version does not match adapter contract")

    def _build_manifest_import_entry(
        self,
        *,
        collection_dir: Path,
        batch: NormalizedImportBatch,
        created_records: list[dict],
    ) -> dict[str, Any]:
        if len(created_records) != len(batch.documents):
            raise ValueError("normalized import record count does not match document count")
        text_units_by_source_document: dict[str, list[dict[str, Any]]] = {}
        for text_unit in batch.text_units:
            text_units_by_source_document.setdefault(
                text_unit.source_document_id,
                [],
            ).append(
                {
                    "text_unit_id": text_unit.text_unit_id,
                    "sequence": int(text_unit.sequence),
                    "page_ref": text_unit.page_ref,
                    "char_count": int(text_unit.char_count),
                }
            )

        documents: list[dict[str, Any]] = []
        for document, record in zip(batch.documents, created_records):
            stored_path = Path(str(record["stored_path"])).resolve()
            try:
                storage_relpath = str(stored_path.relative_to(collection_dir))
            except ValueError:
                storage_relpath = document.storage_relpath
            documents.append(
                {
                    "source_document_id": document.source_document_id,
                    "origin_channel": document.origin_channel,
                    "original_filename": document.original_filename,
                    "stored_filename": record["stored_filename"],
                    "stored_path": str(stored_path),
                    "storage_relpath": storage_relpath,
                    "media_type": record.get("media_type"),
                    "checksum": document.checksum,
                    "language": document.language,
                    "ingest_status": document.ingest_status,
                    "text_units": sorted(
                        text_units_by_source_document.get(
                            document.source_document_id,
                            [],
                        ),
                        key=lambda item: item["sequence"],
                    ),
                }
            )

        return {
            "import_id": f"imp_{uuid4().hex[:12]}",
            "channel": batch.source_metadata.channel,
            "adapter_name": batch.source_metadata.adapter_name,
            "adapter_version": batch.source_metadata.adapter_version,
            "raw_locator": batch.source_metadata.raw_locator,
            "goal_context": dict(batch.source_metadata.goal_context)
            if batch.source_metadata.goal_context
            else None,
            "warnings": list(batch.source_metadata.warnings),
            "ingested_at": batch.source_metadata.ingested_at,
            "documents": documents,
        }
