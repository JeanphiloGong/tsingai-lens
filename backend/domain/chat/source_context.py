"""A source excerpt selected by a researcher for one Chat message."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from domain.chat.resource_ref import ChatResourceRef, _required_text


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
        for field_name in (
            "collection_id",
            "document_id",
            "document_title",
            "source_kind",
            "source_ref",
            "quote",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if self.heading_path is not None:
            object.__setattr__(
                self,
                "heading_path",
                _required_text(self.heading_path, "heading_path"),
            )
        if self.page is not None and self.page < 1:
            raise ValueError("page must be positive")
        object.__setattr__(self, "quote_truncated", bool(self.quote_truncated))
        if self.source_digest is not None:
            digest = _required_text(self.source_digest, "source_digest").lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("source_digest must be a SHA-256 hex digest")
            object.__setattr__(self, "source_digest", digest)
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
