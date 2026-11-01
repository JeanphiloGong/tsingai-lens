"""A source excerpt selected by a researcher for one Chat message."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from domain.chat.resource_ref import ChatResourceRef


@dataclass(frozen=True)
class ChatSourceContext:
    resource_ref: ChatResourceRef
    collection_id: str
    document_id: str
    document_title: str
    source_kind: str
    source_ref: str
    page: int | None
    quote: str
    heading_path: str | None = None
    quote_truncated: bool = False
    source_digest: str | None = None

    def __post_init__(self) -> None:
        if self.page is not None and self.page < 1:
            raise ValueError("page must be positive")
        if self.resource_ref.resource_type != "source":
            raise ValueError("source context requires a source resource reference")
        expected_resource_id = f"{self.document_id}:{self.source_ref}"
        if self.resource_ref.resource_id != expected_resource_id:
            raise ValueError("source context resource identity does not match its Source")
        if self.resource_ref.href is not None:
            parsed = urlsplit(self.resource_ref.href)
            expected_path = (
                f"/collections/{self.collection_id}/documents/{self.document_id}"
            )
            if parsed.scheme or parsed.netloc or parsed.path != expected_path:
                raise ValueError("source context href does not match its document")

__all__ = ["ChatSourceContext"]
