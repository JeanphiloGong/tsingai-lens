from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    document_id: str
    original_filename: str
    sha256: str
    media_type: str | None
    status: str
    size_bytes: int
    parser_version: str | None = None
    document_analysis_version: str | None = None
    source_fingerprint: str | None = None
    profile_fingerprint: str | None = None
    preparation_fingerprint: str | None = None


@dataclass(frozen=True)
class Collection:
    collection_id: str
    owner_user_id: str
    name: str
    description: str | None
    status: str


__all__ = ["Collection", "Document"]
