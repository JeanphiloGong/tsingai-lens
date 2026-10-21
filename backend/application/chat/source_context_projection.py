"""Application projections for researcher-selected Chat source context."""

from __future__ import annotations

from typing import Any

from domain.chat import ChatSourceContext


def source_context_record(source: ChatSourceContext) -> dict[str, Any]:
    """Build the provider/feedback record without exposing serialization on the domain object."""
    return {
        "resource_ref": {
            "resource_type": source.resource_ref.resource_type,
            "resource_id": source.resource_ref.resource_id,
            "href": source.resource_ref.href,
        },
        "collection_id": source.collection_id,
        "document_id": source.document_id,
        "document_title": source.document_title,
        "source_kind": source.source_kind,
        "source_ref": source.source_ref,
        "page": source.page,
        "quote": source.quote,
        "heading_path": source.heading_path,
        "quote_truncated": source.quote_truncated,
        "source_digest": source.source_digest,
    }
