from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    """Uploaded Document identity and immutable file metadata."""

    document_id: str
    filename: str
    sha256: str
    media_type: str | None
    size_bytes: int
