from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from infra.source.ingestion.pdf_ingest import pdf_to_text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class NormalizedImportDocument:
    """Pre-Core source-document record emitted by ingestion adapters."""

    source_document_id: str
    origin_channel: str
    original_filename: str
    media_type: str | None
    stored_filename: str | None = None
    storage_relpath: str | None = None
    checksum: str | None = None
    language: str | None = None
    ingest_status: str = "normalized"


@dataclass(frozen=True)
class NormalizedImportTextUnit:
    """Pre-Core normalized text payload associated with a source document."""

    text_unit_id: str
    source_document_id: str
    sequence: int
    text: str
    page_ref: str | None = None
    char_count: int = 0


@dataclass(frozen=True)
class NormalizedImportSourceMetadata:
    """Batch-level provenance for a normalized import payload."""

    channel: str
    adapter_name: str
    ingested_at: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    adapter_version: str | None = None
    raw_locator: str | None = None
    goal_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class NormalizedImportBatch:
    """Shared pre-Core handoff shape for Source & Collection Builder."""

    documents: tuple[NormalizedImportDocument, ...]
    text_units: tuple[NormalizedImportTextUnit, ...]
    source_metadata: NormalizedImportSourceMetadata

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for later collection import."""
        return asdict(self)


def normalize_upload(
    filename: str,
    content: bytes,
    media_type: str | None = None,
    *,
    channel: str = "upload",
    adapter_name: str = "upload",
    adapter_version: str | None = None,
    goal_context: dict[str, Any] | None = None,
) -> NormalizedImportBatch:
    """Normalize one upload into the shared pre-Core import handoff."""

    normalized_filename = Path(filename or "upload.bin").name or "upload.bin"
    suffix = Path(normalized_filename).suffix.lower()
    normalized_media_type = str(media_type).strip() or None if media_type else None
    warnings: list[str] = []

    text = _normalize_upload_text(
        filename=normalized_filename,
        content=content,
        media_type=normalized_media_type,
    )
    if not text.strip():
        warnings.append("normalized_text_empty")

    source_document_id = f"srcdoc_{uuid4().hex[:12]}"
    checksum = hashlib.sha256(content).hexdigest()
    document = NormalizedImportDocument(
        source_document_id=source_document_id,
        origin_channel=channel,
        original_filename=normalized_filename,
        media_type=normalized_media_type,
        stored_filename=_build_normalized_storage_name(normalized_filename, suffix),
        storage_relpath=None,
        checksum=checksum,
        language=None,
        ingest_status="normalized",
    )
    text_unit = NormalizedImportTextUnit(
        text_unit_id=f"textu_{uuid4().hex[:12]}",
        source_document_id=source_document_id,
        sequence=0,
        text=text,
        page_ref=None,
        char_count=len(text),
    )
    metadata = NormalizedImportSourceMetadata(
        channel=channel,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        ingested_at=_now_iso(),
        warnings=tuple(warnings),
        raw_locator=normalized_filename,
        goal_context=dict(goal_context) if goal_context else None,
    )
    return NormalizedImportBatch(
        documents=(document,),
        text_units=(text_unit,),
        source_metadata=metadata,
    )


def _normalize_upload_text(
    *,
    filename: str,
    content: bytes,
    media_type: str | None,
) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return pdf_to_text(content)

    if _is_text_upload(filename=filename, media_type=media_type):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("text upload must be valid UTF-8") from exc

    raise ValueError(f"unsupported upload type for normalization: {filename}")


def _is_text_upload(*, filename: str, media_type: str | None) -> bool:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".csv", ".tsv", ".json"}:
        return True
    if media_type and media_type.startswith("text/"):
        return True
    if media_type in {"application/json", "application/xml"}:
        return True
    return False


def _build_normalized_storage_name(filename: str, suffix: str) -> str:
    base_name = Path(filename).stem
    normalized_suffix = ".txt" if suffix == ".pdf" else Path(filename).suffix
    return f"{uuid4().hex}_{base_name}{normalized_suffix}"
