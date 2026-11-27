from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DocumentType = Literal["experimental", "review", "mixed", "uncertain"]


@dataclass(frozen=True)
class DocumentProfile:
    """Navigation index generated from one prepared Source version."""

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
