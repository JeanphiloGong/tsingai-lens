from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Any
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

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


_SOURCE_ARCHIVE_MAX_MIB = 256
_SOURCE_ARCHIVE_MAX_BYTES = _SOURCE_ARCHIVE_MAX_MIB * 1024 * 1024


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


class CollectionSourceArchiveError(RuntimeError):
    """Raised when selected original files cannot form a safe source archive."""

    def __init__(
        self,
        collection_id: str,
        *,
        code: str,
        message: str,
        file_id: str | None = None,
    ) -> None:
        self.collection_id = collection_id
        self.file_id = file_id
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

    def write_figure_asset(
        self,
        collection_id: str,
        build_id: str,
        asset_path: str,
        payload: bytes,
        expected_sha256: str,
    ) -> str:
        suffix = PurePosixPath(str(asset_path)).suffix.lower()
        storage_key = self._figure_storage_key(
            collection_id,
            build_id,
            expected_sha256,
            suffix,
        )
        self.object_store.write(storage_key, payload, expected_sha256)
        return storage_key

    def read_figure_asset(
        self,
        collection_id: str,
        storage_key: str,
        expected_sha256: str,
    ) -> bytes:
        key = PurePosixPath(str(storage_key))
        if (
            len(key.parts) != 6
            or key.parts[:3]
            != (
                str(collection_id),
                "objects",
                "source",
            )
            or key.parts[4] != "figures"
        ):
            raise ValueError("invalid figure storage key")
        expected_key = self._figure_storage_key(
            collection_id,
            key.parts[3],
            expected_sha256,
            key.suffix.lower(),
        )
        if str(key) != expected_key:
            raise ValueError("invalid figure storage key")
        try:
            return self.object_store.read(storage_key, expected_sha256)
        except ValueError as exc:
            raise OSError("figure object verification failed") from exc

    # define a method for creating a document collection
    async def create_collection(
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
            await self.repository.add_collection(record)
        except Exception:
            self.workspace.delete_collection_dir(collection_id)
            raise
        return record.to_record()

    async def list_collections(
        self, owner_user_id: str | None = None
    ) -> list[dict]:
        return [
            record.to_record()
            for record in await self.repository.list_collections(owner_user_id)
        ]

    async def get_collection(self, collection_id: str) -> dict:
        record = await self.repository.read_collection(collection_id)
        if record is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record.to_record()

    async def get_collection_for_user(
        self, collection_id: str, owner_user_id: str
    ) -> dict:
        record = await self.get_collection(collection_id)
        if record["owner_user_id"] != owner_user_id:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return record

    async def update_collection(self, collection_id: str, **fields) -> dict:
        record = dict(await self.get_collection(collection_id))
        record.update(fields)
        record["updated_at"] = _now_iso()
        normalized = CollectionRecord.from_mapping(
            record,
            collection_id,
            now_iso=record["updated_at"],
        )
        if not await self.repository.update_collection(normalized):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return normalized.to_record()

    async def delete_collection(self, collection_id: str) -> dict:
        paths = self.get_paths(collection_id)
        target_dir = paths.collection_dir
        if await self.repository.read_collection(collection_id) is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")

        resolved_root = self.root_dir.resolve()
        resolved_target = target_dir.resolve()
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("invalid collection path") from exc
        if target_dir.is_symlink():
            raise ValueError("collection path cannot be a symlink")

        for record in await self.repository.list_collection_files(collection_id):
            storage_key = self._optional_text(record.storage_key)
            stored_filename = self._optional_text(record.stored_filename)
            if (
                not storage_key
                or not stored_filename
                or storage_key
                != self._input_storage_key(collection_id, stored_filename)
            ):
                raise ValueError("invalid collection object key")
        if not await self.repository.delete_collection(collection_id):
            raise FileNotFoundError(f"collection not found: {collection_id}")
        self.workspace.delete_collection_dir(collection_id)
        return {
            "collection_id": collection_id,
            "deleted_at": _now_iso(),
        }

    async def delete_collection_for_user(
        self, collection_id: str, owner_user_id: str
    ) -> dict:
        await self.get_collection_for_user(collection_id, owner_user_id)
        return await self.delete_collection(collection_id)

    async def list_files(self, collection_id: str) -> list[dict]:
        await self.get_collection(collection_id)
        return [
            record.to_record()
            for record in await self.repository.list_collection_files(
                collection_id
            )
        ]

    async def build_source_archive(
        self,
        collection_id: str,
        file_ids: list[str],
    ) -> dict[str, Any]:
        """Build a bounded ZIP of original uploads for failure reproduction."""

        normalized_file_ids = [str(file_id).strip() for file_id in file_ids]
        if not normalized_file_ids or any(
            not file_id for file_id in normalized_file_ids
        ):
            raise ValueError("source archive requires at least one file_id")
        if len(normalized_file_ids) > 100:
            raise ValueError("source archive supports at most 100 file_ids")
        if len(set(normalized_file_ids)) != len(normalized_file_ids):
            raise ValueError("source archive file_ids must be unique")

        records = await self.list_files(collection_id)
        records_by_file_id = {
            str(record.get("file_id") or "").strip(): record for record in records
        }
        selected_records: list[tuple[str, dict[str, Any]]] = []
        for file_id in normalized_file_ids:
            record = records_by_file_id.get(file_id)
            if record is None:
                raise CollectionSourceArchiveError(
                    collection_id,
                    code="collection_source_file_not_found",
                    message=(
                        "A requested source file does not exist in this collection."
                    ),
                    file_id=file_id,
                )
            selected_records.append((file_id, record))

        selected_size_bytes = sum(
            max(int(record.get("size_bytes") or 0), 0)
            for _file_id, record in selected_records
        )
        if selected_size_bytes > _SOURCE_ARCHIVE_MAX_BYTES:
            raise CollectionSourceArchiveError(
                collection_id,
                code="collection_source_archive_too_large",
                message=(
                    "Selected source files exceed the "
                    f"{_SOURCE_ARCHIVE_MAX_MIB} MiB archive limit."
                ),
            )

        return await asyncio.to_thread(
            self._write_source_archive,
            collection_id,
            selected_records,
        )

    def _write_source_archive(
        self,
        collection_id: str,
        selected_records: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Verify source bytes and write the archive outside the event loop."""

        archive_file = SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
        try:
            manifest_files: list[dict[str, Any]] = []
            with ZipFile(
                archive_file,
                mode="w",
                compression=ZIP_STORED,
                allowZip64=True,
            ) as archive:
                for position, (file_id, record) in enumerate(
                    selected_records,
                    start=1,
                ):
                    try:
                        source = self._build_source_file_payload(
                            collection_id=collection_id,
                            document_id=file_id,
                            record=record,
                        )
                    except DocumentSourceUnavailableError as exc:
                        raise CollectionSourceArchiveError(
                            collection_id,
                            code=self._source_archive_error_code(exc.code),
                            message=exc.message,
                            file_id=file_id,
                        ) from exc

                    archive_path = (
                        f"sources/{position:03d}-"
                        f"{self._safe_archive_filename(source['filename'])}"
                    )
                    content = source["content"]
                    archive.writestr(archive_path, content)
                    manifest_record: dict[str, Any] = {
                        "file_id": file_id,
                        "archive_path": archive_path,
                        "original_filename": source["filename"],
                        "media_type": source.get("media_type"),
                        "size_bytes": len(content),
                        "sha256": record.get("sha256"),
                        "status": record.get("status"),
                        "created_at": record.get("created_at"),
                    }
                    if record.get("document_id"):
                        manifest_record["document_id"] = record["document_id"]
                    manifest_files.append(manifest_record)

                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "schema_version": 1,
                            "collection_id": collection_id,
                            "files": manifest_files,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ).encode("utf-8"),
                )
            archive_file.seek(0)
        except Exception:
            archive_file.close()
            raise

        return {
            "file": archive_file,
            "filename": self._safe_archive_filename(
                f"collection-{collection_id}-sources.zip"
            ),
        }

    async def get_import_manifest(self, collection_id: str) -> dict[str, Any]:
        await self.get_collection(collection_id)
        manifest = empty_import_manifest(collection_id)
        manifest["handoffs"] = [
            record.to_record()
            for record in await self.repository.list_collection_handoffs(
                collection_id
            )
        ]
        manifest["imports"] = [
            record.to_record()
            for record in await self.repository.list_collection_imports(
                collection_id
            )
        ]
        return manifest

    async def resolve_document_source_file(
        self,
        collection_id: str,
        document_id: str,
        *,
        source_filename: str | None = None,
    ) -> dict[str, Any]:
        await self.get_collection(collection_id)
        document_key = str(document_id or "").strip()
        if not document_key:
            raise DocumentSourceUnavailableError(collection_id, document_key)

        match_keys = self._source_match_keys(document_key, source_filename)
        manifest = await self.get_import_manifest(collection_id)
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
            for record in await self.list_files(collection_id)
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

    async def register_goal_brief_handoff(
        self,
        collection_id: str,
        research_brief: dict[str, Any],
        coverage_assessment: dict[str, Any],
        *,
        source_channels: list[str] | None = None,
    ) -> dict[str, Any]:
        await self.get_collection(collection_id)
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
        await self.repository.add_collection_handoff(handoff)
        return handoff.to_record()

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
        await self.get_collection(collection_id)

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
        await self.get_collection(collection_id)
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
            await self.repository.add_collection_import(
                import_record,
                updated_at=_now_iso(),
            )
        except Exception:
            try:
                registered_keys = {
                    record.storage_key
                    for record in await self.repository.list_collection_files(
                        collection_id
                    )
                }
            except Exception:
                registered_keys = {record.storage_key for record in created_files}
            for record in created_files:
                if record.storage_key not in registered_keys:
                    self.object_store.delete(record.storage_key)
            raise
        return [record.to_record() for record in created_files]

    async def add_file(
        self,
        collection_id: str,
        filename: str,
        content: bytes,
        media_type: str | None = None,
    ) -> dict:
        await self.get_collection(collection_id)
        batch = normalize_upload(
            filename=filename,
            content=content,
            media_type=media_type,
        )
        imported = await self.import_normalized_batch(collection_id, batch)
        if not imported:
            raise ValueError("normalized upload produced no importable documents")
        return imported[0]

    def _input_storage_key(self, collection_id: str, stored_filename: str) -> str:
        return f"{collection_id}/input/{stored_filename}"

    @staticmethod
    def _figure_storage_key(
        collection_id: str,
        build_id: str,
        sha256: str,
        suffix: str,
    ) -> str:
        collection_key = str(collection_id).strip()
        build_key = str(build_id).strip()
        digest = str(sha256).strip()
        extension = str(suffix).strip().lower()
        if (
            not collection_key
            or not build_key
            or any(character in collection_key + build_key for character in "/\\")
            or not extension.startswith(".")
            or not extension[1:].isalnum()
            or len(extension) > 10
        ):
            raise ValueError("invalid figure storage key")
        return (
            f"{collection_key}/objects/source/{build_key}/figures/{digest}{extension}"
        )

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

    @staticmethod
    def _safe_archive_filename(value: Any) -> str:
        filename = PurePosixPath(str(value or "").replace("\\", "/")).name
        filename = "".join(
            "_" if ord(character) < 32 or character in '<>:"|?*' else character
            for character in filename
        ).strip(" .")
        return filename or "source.bin"

    @staticmethod
    def _source_archive_error_code(document_source_code: str) -> str:
        return {
            "document_source_path_invalid": "collection_source_path_invalid",
            "document_source_integrity_failed": "collection_source_integrity_failed",
        }.get(document_source_code, "collection_source_file_unavailable")

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
