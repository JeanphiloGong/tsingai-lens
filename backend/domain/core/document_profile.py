from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from domain.shared.enums import (
    DOC_TYPE_MIXED,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
    PROTOCOL_SUITABLE_EXTRACTABILITY,
)


@dataclass(frozen=True)
class DocumentProfile:
    document_id: str
    collection_id: str
    title: str | None
    source_filename: str | None
    doc_type: str
    protocol_extractable: str
    protocol_extractability_signals: tuple[str, ...]
    parsing_warnings: tuple[str, ...]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentProfile":
        return cls(
            document_id=str(payload.get("document_id") or ""),
            collection_id=str(payload.get("collection_id") or ""),
            title=_normalize_optional_text(payload.get("title")),
            source_filename=_normalize_optional_text(payload.get("source_filename")),
            doc_type=str(payload.get("doc_type") or DOC_TYPE_UNCERTAIN),
            protocol_extractable=str(payload.get("protocol_extractable") or "uncertain"),
            protocol_extractability_signals=_normalize_string_tuple(
                payload.get("protocol_extractability_signals")
            ),
            parsing_warnings=_normalize_string_tuple(payload.get("parsing_warnings")),
            confidence=round(float(payload.get("confidence") or 0.0), 2),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "title": self.title,
            "source_filename": self.source_filename,
            "doc_type": self.doc_type,
            "protocol_extractable": self.protocol_extractable,
            "protocol_extractability_signals": list(self.protocol_extractability_signals),
            "parsing_warnings": list(self.parsing_warnings),
            "confidence": round(float(self.confidence), 2),
        }


@dataclass(frozen=True)
class DocumentProfileSummary:
    total_documents: int
    by_doc_type: dict[str, int]
    by_protocol_extractable: dict[str, int]
    warnings: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "total_documents": self.total_documents,
            "by_doc_type": dict(self.by_doc_type),
            "by_protocol_extractable": dict(self.by_protocol_extractable),
            "warnings": list(self.warnings),
        }


def summarize_document_profile_collection(
    profiles: Iterable[DocumentProfile],
) -> DocumentProfileSummary:
    normalized = list(profiles)
    total_documents = len(normalized)
    by_doc_type = dict(
        sorted(Counter(profile.doc_type for profile in normalized).items())
    )
    by_protocol_extractable = dict(
        sorted(Counter(profile.protocol_extractable for profile in normalized).items())
    )

    warnings: list[str] = []
    review_heavy_count = by_doc_type.get(DOC_TYPE_REVIEW, 0) + by_doc_type.get(
        DOC_TYPE_MIXED,
        0,
    )
    if total_documents and review_heavy_count / total_documents >= 0.5:
        warnings.append(
            "Collection is review-heavy or mixed; protocol outputs should be treated cautiously."
        )
    if total_documents and not any(
        by_protocol_extractable.get(value, 0) > 0
        for value in PROTOCOL_SUITABLE_EXTRACTABILITY
    ):
        warnings.append("No protocol-suitable documents were detected in this collection.")
    if by_doc_type.get(DOC_TYPE_UNCERTAIN, 0) > 0:
        warnings.append("Some documents remain uncertain and may need manual review.")

    return DocumentProfileSummary(
        total_documents=total_documents,
        by_doc_type=by_doc_type,
        by_protocol_extractable=by_protocol_extractable,
        warnings=tuple(warnings),
    )


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    if hasattr(value, "tolist") and not isinstance(value, (dict, bytes)):
        converted = value.tolist()
        if converted is not value:
            return _normalize_string_tuple(converted)
    text = str(value).strip()
    return (text,) if text else ()


__all__ = [
    "DocumentProfile",
    "DocumentProfileSummary",
    "summarize_document_profile_collection",
]
