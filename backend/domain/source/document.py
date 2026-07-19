from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import NAMESPACE_URL, uuid5


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    created_at: str


@dataclass(frozen=True)
class DocumentVersionRecord:
    document_version_id: str
    document_id: str
    sha256: str
    media_type: str | None
    created_at: str


@dataclass(frozen=True)
class CollectionDocumentRecord:
    collection_document_id: str
    collection_id: str
    document_id: str
    document_version_id: str
    created_at: str


def document_identity_for_sha256(sha256: str) -> tuple[str, str]:
    digest = str(sha256)
    if _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("document content hash must be a lowercase SHA-256")
    return (
        f"doc_{uuid5(NAMESPACE_URL, f'lens:document:{digest}').hex}",
        f"docver_{uuid5(NAMESPACE_URL, f'lens:document-version:{digest}').hex}",
    )


def collection_document_identity(collection_id: str, document_id: str) -> str:
    return f"coldoc_{uuid5(NAMESPACE_URL, f'lens:collection-document:{collection_id}:{document_id}').hex}"


__all__ = [
    "CollectionDocumentRecord",
    "DocumentRecord",
    "DocumentVersionRecord",
    "collection_document_identity",
    "document_identity_for_sha256",
]
