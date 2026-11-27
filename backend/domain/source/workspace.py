from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    document_id: str
    filename: str
    sha256: str
    media_type: str | None
    size_bytes: int


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    owner_user_id: str
    name: str
    description: str | None
    status: str


__all__ = ["Workspace", "Document"]
