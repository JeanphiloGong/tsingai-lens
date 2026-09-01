"""A source excerpt selected by a researcher for one Chat message."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
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

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChatSourceContext":
        resource_payload = payload.get("resource_ref")
        if not isinstance(resource_payload, Mapping):
            raise ValueError("source context requires resource_ref")
        page = payload.get("page")
        return cls(
            resource_ref=ChatResourceRef.from_mapping(resource_payload),
            collection_id=str(payload.get("collection_id") or ""),
            document_id=str(payload.get("document_id") or ""),
            document_title=str(payload.get("document_title") or ""),
            source_kind=str(payload.get("source_kind") or ""),
            source_ref=str(payload.get("source_ref") or ""),
            page=int(page) if page is not None else None,
            quote=str(payload.get("quote") or ""),
            heading_path=(
                str(payload["heading_path"])
                if payload.get("heading_path") is not None
                else None
            ),
            quote_truncated=bool(payload.get("quote_truncated", False)),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "resource_ref": self.resource_ref.to_record(),
            "collection_id": self.collection_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "page": self.page,
            "quote": self.quote,
            "heading_path": self.heading_path,
            "quote_truncated": self.quote_truncated,
        }


__all__ = ["ChatSourceContext"]
