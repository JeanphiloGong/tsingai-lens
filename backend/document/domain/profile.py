from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal


DocumentType = Literal["experimental", "review", "mixed", "uncertain"]


@dataclass(frozen=True)
class DocumentProfile:
    """Current navigation profile produced from one prepared Source version."""

    document_id: str
    doc_type: DocumentType
    description: str
    source_fingerprint: str
    profile_fingerprint: str
    profile_version: str
    generated_at: str

    def __post_init__(self) -> None:
        if not self.document_id or not self.description.strip():
            raise ValueError("profile identity and description are required")
        if not self.source_fingerprint or not self.profile_fingerprint:
            raise ValueError("profile fingerprints are required")
        if not self.profile_version or not self.generated_at:
            raise ValueError("profile version and generated_at are required")


@dataclass(frozen=True)
class DocumentProfileSummary:
    total_documents: int
    by_doc_type: dict[str, int]
    warnings: tuple[str, ...]
    technical_failure_count: int = 0


def summarize_document_profile_workspace(
    profiles: Iterable[DocumentProfile],
) -> DocumentProfileSummary:
    normalized = tuple(profiles)
    by_doc_type = dict(
        sorted(Counter(profile.doc_type for profile in normalized).items())
    )
    warnings: list[str] = []
    review_heavy_count = by_doc_type.get("review", 0) + by_doc_type.get("mixed", 0)
    if normalized and review_heavy_count / len(normalized) >= 0.5:
        warnings.append(
            "Workspace is review-heavy or mixed; experimental evidence may require manual review."
        )
    if by_doc_type.get("uncertain", 0):
        warnings.append("Some documents remain uncertain and may need manual review.")
    return DocumentProfileSummary(
        total_documents=len(normalized),
        by_doc_type=by_doc_type,
        warnings=tuple(warnings),
    )


__all__ = [
    "DocumentProfile",
    "DocumentProfileSummary",
    "DocumentType",
    "summarize_document_profile_workspace",
]
