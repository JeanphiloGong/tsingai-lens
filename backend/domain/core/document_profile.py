from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal

from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_MIXED,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
)


ProfileStatus = Literal["completed", "extraction_failed"]
PROFILE_STATUS_COMPLETED: ProfileStatus = "completed"
PROFILE_STATUS_EXTRACTION_FAILED: ProfileStatus = "extraction_failed"
PROFILE_EXTRACTION_FAILED_WARNING = "document_profile_extraction_failed"


@dataclass(frozen=True)
class DocumentProfile:
    document_id: str
    title: str | None
    doc_type: str
    profile_warnings: tuple[str, ...]
    confidence: float
    profile_status: ProfileStatus = PROFILE_STATUS_COMPLETED
    source_fingerprint: str | None = None
    profile_version: str | None = None
    profile_fingerprint: str | None = None
    generated_at: str | None = None


@dataclass(frozen=True)
class DocumentProfileSummary:
    total_documents: int
    by_doc_type: dict[str, int]
    warnings: tuple[str, ...]
    technical_failure_count: int


def summarize_document_profile_collection(
    profiles: Iterable[DocumentProfile],
) -> DocumentProfileSummary:
    normalized = list(profiles)
    total_documents = len(normalized)
    by_doc_type = dict(
        sorted(Counter(profile.doc_type for profile in normalized).items())
    )

    warnings: list[str] = []
    review_heavy_count = by_doc_type.get(DOC_TYPE_REVIEW, 0) + by_doc_type.get(
        DOC_TYPE_MIXED,
        0,
    )
    if total_documents and review_heavy_count / total_documents >= 0.5:
        warnings.append(
            "Collection is review-heavy or mixed; experimental evidence may require manual review."
        )
    if by_doc_type.get(DOC_TYPE_UNCERTAIN, 0) > 0:
        warnings.append("Some documents remain uncertain and may need manual review.")
    technical_failure_count = sum(
        PROFILE_EXTRACTION_FAILED_WARNING in profile.profile_warnings
        or profile.profile_status == PROFILE_STATUS_EXTRACTION_FAILED
        for profile in normalized
    )
    if technical_failure_count:
        warnings.append(
            "Some document profiles failed technical extraction and need retry."
        )

    return DocumentProfileSummary(
        total_documents=total_documents,
        by_doc_type=by_doc_type,
        warnings=tuple(warnings),
        technical_failure_count=technical_failure_count,
    )


__all__ = [
    "DocumentProfile",
    "DocumentProfileSummary",
    "PROFILE_EXTRACTION_FAILED_WARNING",
    "PROFILE_STATUS_COMPLETED",
    "PROFILE_STATUS_EXTRACTION_FAILED",
    "ProfileStatus",
    "summarize_document_profile_collection",
]
