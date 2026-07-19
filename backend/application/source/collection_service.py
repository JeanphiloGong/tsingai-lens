from __future__ import annotations

import base64
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from domain.ports import CollectionPaths, CollectionRepository
from domain.source import (
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
    empty_import_manifest,
)
from domain.source.ports import ObjectStore
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from infra.source.ingestion import (
    NormalizedImportBatch,
    NormalizedImportDocument,
    SourceAdapter,
    SourceAdapterRequest,
    normalize_upload,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentSourceUnavailableError(RuntimeError):
    """Raised when a document exists but its original source file cannot be served."""

    def __init__(
        self,
        collection_id: str,
        document_id: str,
        *,
        code: str = "document_source_unavailable",
        message: str = "The original source file is not available for this document.",
    ) -> None:
        self.collection_id = collection_id
        self.document_id = document_id
        self.code = code
        self.message = message
        super().__init__(message)


class CollectionService:
    """Application operations over collection metadata and its file workspace."""

    def __init__(
        self,
        repository: CollectionRepository,
        workspace: FileCollectionWorkspace,
        object_store: ObjectStore | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.root_dir = self.workspace.root_dir
        self.object_store = object_store or FileObjectStore(self.root_dir)

    def get_paths(self, collection_id: str) -> CollectionPaths:
        return self.workspace.get_paths(collection_id)

    # define a method for creating a document collection
    def create_collection(
        self,
        name: str,
        description: str | None = None,
        owner_user_id: str = "local-user",
    ) -> dict:
        collection_id = f"col_{uuid4().hex[:12]}"
        now = _now_iso()
        record = CollectionRecord.create(
            collection_id=collection_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            now_iso=now,
        )
        self.workspace.create_collection_dirs(collection_id)
        try:
            self.repository.add_collection(record)
        except Exception:
            self.workspace.delete_collection_dir(collection_id)
            raise
        return record.to_record()

    def list_collections(self, owner_user_id: str | None = None) -> list[dict]:
        return [
            record.to_record()
            for record in self.repository.list_collections(owner_user_id)
        ]

    def get_collection(self, collection_id: str) -> dict:
        record = self.repository.read_collection(collection_id)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record.to_record()

    def get_collection_for_user(self, collection_id: str, owner_user_id: str) -> dict:
        record = self.get_collection(collection_id)
        if record["owner_user_id"] != owner_user_id:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record

    def update_collection(self, collection_id: str, **fields) -> dict:
        record = dict(self.get_collection(collection_id))
        record.update(fields)
        record["updated_at"] = _now_iso()
        normalized = CollectionRecord.from_mapping(
            record,
            collection_id,
            now_iso=record["updated_at"],
        )
        if not self.repository.update_collection(normalized):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return normalized.to_record()

    def delete_collection(self, collection_id: str) -> dict:
        paths = self.get_paths(collection_id)
        target_dir = paths.collection_dir
        if self.repository.read_collection(collection_id) is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")

        resolved_root = self.root_dir.resolve()
        resolved_target = target_dir.resolve()
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("invalid collection path") from exc
        if target_dir.is_symlink():
            raise ValueError("collection path cannot be a symlink")

        for record in self.repository.list_collection_files(collection_id):
            storage_key = self._optional_text(record.storage_key)
            stored_filename = self._optional_text(record.stored_filename)
            if (
                not storage_key
                or not stored_filename
                or storage_key
                != self._input_storage_key(collection_id, stored_filename)
            ):
                raise ValueError("invalid collection object key")
        if not self.repository.delete_collection(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        self.workspace.delete_collection_dir(collection_id)
        return {
            "collection_id": collection_id,
            "deleted_at": _now_iso(),
        }

    def delete_collection_for_user(
        self, collection_id: str, owner_user_id: str
    ) -> dict:
        self.get_collection_for_user(collection_id, owner_user_id)
        return self.delete_collection(collection_id)

    def list_files(self, collection_id: str) -> list[dict]:
        self.get_collection(collection_id)
        return [
            record.to_record()
            for record in self.repository.list_collection_files(collection_id)
        ]

    def get_import_manifest(self, collection_id: str) -> dict[str, Any]:
        self.get_collection(collection_id)
        manifest = empty_import_manifest(collection_id)
        manifest["handoffs"] = [
            record.to_record()
            for record in self.repository.list_collection_handoffs(collection_id)
        ]
        manifest["imports"] = [
            record.to_record()
            for record in self.repository.list_collection_imports(collection_id)
        ]
        return manifest

    def resolve_document_source_file(
        self,
        collection_id: str,
        document_id: str,
        *,
        source_filename: str | None = None,
    ) -> dict[str, Any]:
        self.get_collection(collection_id)
        document_key = str(document_id or "").strip()
        if not document_key:
            raise DocumentSourceUnavailableError(collection_id, document_key)

        match_keys = self._source_match_keys(document_key, source_filename)
        manifest = self.get_import_manifest(collection_id)
        manifest_documents = self._iter_manifest_documents(manifest)
        for document in manifest_documents:
            if self._source_document_record_matches(document, match_keys):
                return self._build_source_file_payload(
                    collection_id=collection_id,
                    document_id=document_key,
                    record=document,
                )

        file_matches = [
            record
            for record in self.list_files(collection_id)
            if self._source_file_record_matches(record, match_keys)
        ]
        if len(file_matches) == 1:
            return self._build_source_file_payload(
                collection_id=collection_id,
                document_id=document_key,
                record=file_matches[0],
            )
        if len(file_matches) > 1:
            raise DocumentSourceUnavailableError(
                collection_id,
                document_key,
                code="document_source_ambiguous",
                message="More than one stored source file matches this document.",
            )
        if manifest_documents:
            raise FileNotFoundError(
                f"document not found: {collection_id}/{document_key}"
            )
        raise DocumentSourceUnavailableError(collection_id, document_key)

    def register_goal_brief_handoff(
        self,
        collection_id: str,
        research_brief: dict[str, Any],
        coverage_assessment: dict[str, Any],
        *,
        source_channels: list[str] | None = None,
    ) -> dict[str, Any]:
        self.get_collection(collection_id)
        handoff = CollectionHandoffRecord(
            handoff_id=f"handoff_{uuid4().hex[:12]}",
            collection_id=collection_id,
            kind="goal_brief",
            status="awaiting_source_material",
            created_at=_now_iso(),
            source_channels=tuple(source_channels or ["upload"]),
            goal_context={
                "research_brief": dict(research_brief),
                "coverage_assessment": dict(coverage_assessment),
            },
        )
        self.repository.add_collection_handoff(handoff)
        return handoff.to_record()

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
        self.get_collection(collection_id)

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
        self.get_collection(collection_id)
        if not batch.documents:
            raise ValueError(
                "normalized import batch must include at least one document"
            )

        text_by_source_document = self._group_text_units(batch)
        created_files: list[CollectionFileRecord] = []

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
                created_files.append(
                    CollectionFileRecord(
                        file_id=f"file_{uuid4().hex[:12]}",
                        collection_id=collection_id,
                        object_id=f"obj_{uuid4().hex[:12]}",
                        object_kind="source_input",
                        original_filename=document.original_filename,
                        stored_filename=stored_filename,
                        storage_key=storage_key,
                        sha256=payload_sha256,
                        media_type=document.media_type,
                        status="stored",
                        size_bytes=len(payload),
                        created_at=_now_iso(),
                    )
                )
            import_record = self._build_import_record(
                batch=batch,
                created_files=created_files,
            )
            self.repository.add_collection_import(
                import_record,
                updated_at=_now_iso(),
            )
        except Exception:
            try:
                registered_keys = {
                    record.storage_key
                    for record in self.repository.list_collection_files(collection_id)
                }
            except Exception:
                registered_keys = {record.storage_key for record in created_files}
            for record in created_files:
                if record.storage_key not in registered_keys:
                    self.object_store.delete(record.storage_key)
            raise
        return [record.to_record() for record in created_files]

    def add_file(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
    ) -> dict:
        self.get_collection(collection_id)
        batch = normalize_upload(
            filename=filename,
            content=content,
            media_type=media_type,
        )
        imported = self.import_normalized_batch(collection_id, batch)
        if not imported:
            raise ValueError("normalized upload produced no importable documents")
        return imported[0]

    def _input_storage_key(self, collection_id: str, stored_filename: str) -> str:
        return f"{collection_id}/input/{stored_filename}"

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
                text for _, text in sorted(items, key=lambda item: item[0])
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

    def _build_import_record(
        self,
        *,
        batch: NormalizedImportBatch,
        created_files: list[CollectionFileRecord],
    ) -> CollectionImportRecord:
        if len(created_files) != len(batch.documents):
            raise ValueError(
                "normalized import record count does not match document count"
            )
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

        documents: list[CollectionImportDocumentRecord] = []
        for document, file_record in zip(batch.documents, created_files):
            documents.append(
                CollectionImportDocumentRecord(
                    source_document_id=document.source_document_id,
                    origin_channel=document.origin_channel,
                    file=file_record,
                    language=document.language,
                    ingest_status=document.ingest_status,
                    text_units=tuple(
                        sorted(
                            text_units_by_source_document.get(
                                document.source_document_id,
                                [],
                            ),
                            key=lambda item: item["sequence"],
                        )
                    ),
                )
            )

        return CollectionImportRecord(
            import_id=f"imp_{uuid4().hex[:12]}",
            collection_id=created_files[0].collection_id,
            channel=batch.source_metadata.channel,
            adapter_name=batch.source_metadata.adapter_name,
            adapter_version=batch.source_metadata.adapter_version,
            raw_locator=batch.source_metadata.raw_locator,
            goal_context=(
                dict(batch.source_metadata.goal_context)
                if batch.source_metadata.goal_context
                else None
            ),
            warnings=tuple(batch.source_metadata.warnings),
            ingested_at=batch.source_metadata.ingested_at,
            documents=tuple(documents),
        )

    def _iter_manifest_documents(
        self, manifest: dict[str, Any]
    ) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        imports = manifest.get("imports")
        if not isinstance(imports, list):
            return documents
        for import_record in imports:
            if not isinstance(import_record, dict):
                continue
            import_documents = import_record.get("documents")
            if not isinstance(import_documents, list):
                continue
            documents.extend(
                document for document in import_documents if isinstance(document, dict)
            )
        return documents

    def _source_file_record_matches(
        self,
        record: dict[str, Any],
        match_keys: set[str],
    ) -> bool:
        candidates = (
            record.get("source_document_id"),
            record.get("document_id"),
            record.get("original_filename"),
            record.get("stored_filename"),
            record.get("storage_key"),
            Path(str(record.get("storage_key") or "")).name,
        )
        return any(
            self._source_match_value(candidate) in match_keys
            for candidate in candidates
        )

    def _source_document_record_matches(
        self,
        record: dict[str, Any],
        match_keys: set[str],
    ) -> bool:
        candidates = (
            record.get("source_document_id"),
            record.get("original_filename"),
            record.get("stored_filename"),
            record.get("storage_key"),
            Path(str(record.get("storage_key") or "")).name,
        )
        return any(
            self._source_match_value(candidate) in match_keys
            for candidate in candidates
        )

    def _source_match_keys(
        self,
        document_id: str,
        source_filename: str | None,
    ) -> set[str]:
        keys = {
            self._source_match_value(document_id),
            self._source_match_value(source_filename),
            self._source_match_value(Path(str(source_filename or "")).name),
        }
        return {key for key in keys if key}

    def _source_match_value(self, value: Any) -> str:
        return str(value or "").strip()

    def _build_source_file_payload(
        self,
        *,
        collection_id: str,
        document_id: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        storage_key = self._optional_text(record.get("storage_key"))
        expected_sha256 = self._optional_text(record.get("sha256"))
        if not storage_key or not expected_sha256:
            raise DocumentSourceUnavailableError(collection_id, document_id)
        stored_filename = self._optional_text(record.get("stored_filename"))
        if not stored_filename or storage_key != self._input_storage_key(
            collection_id, stored_filename
        ):
            raise DocumentSourceUnavailableError(
                collection_id,
                document_id,
                code="document_source_path_invalid",
                message="The stored source file path is not safe to serve.",
            )
        try:
            content = self.object_store.read(storage_key, expected_sha256)
        except FileNotFoundError as exc:
            raise DocumentSourceUnavailableError(collection_id, document_id) from exc
        except ValueError as exc:
            if str(exc) == "invalid storage key":
                raise DocumentSourceUnavailableError(
                    collection_id,
                    document_id,
                    code="document_source_path_invalid",
                    message="The stored source file path is not safe to serve.",
                ) from exc
            raise DocumentSourceUnavailableError(
                collection_id,
                document_id,
                code="document_source_integrity_failed",
                message="The stored source file failed its integrity check.",
            ) from exc
        filename = (
            self._optional_text(record.get("original_filename"))
            or stored_filename
            or Path(storage_key).name
        )
        return {
            "content": content,
            "filename": filename,
            "media_type": self._optional_text(record.get("media_type")),
            "source_document_id": self._optional_text(record.get("source_document_id"))
            or document_id,
        }

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
