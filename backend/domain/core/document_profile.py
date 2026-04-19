from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_MIXED,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
    DocumentType,
    PROTOCOL_EXTRACTABLE_NO,
    PROTOCOL_EXTRACTABLE_PARTIAL,
    PROTOCOL_EXTRACTABLE_UNCERTAIN,
    PROTOCOL_EXTRACTABLE_YES,
    PROTOCOL_SUITABLE_EXTRACTABILITY,
    ProtocolExtractability,
)

_REVIEW_TITLE_PATTERNS = (
    re.compile(r"\breview\b", re.IGNORECASE),
    re.compile(r"\boverview\b", re.IGNORECASE),
    re.compile(r"\bperspective\b", re.IGNORECASE),
    re.compile(r"\bprogress\b", re.IGNORECASE),
    re.compile(r"\brecent advances?\b", re.IGNORECASE),
    re.compile(r"\bsurvey\b", re.IGNORECASE),
    re.compile(r"\bmini[- ]?review\b", re.IGNORECASE),
    re.compile(r"(综述|进展|评述)"),
)

_REVIEW_TEXT_HINTS = (
    "this review",
    "we review",
    "recent advances",
    "state of the art",
    "in this perspective",
    "this overview",
    "综述",
    "进展",
    "评述",
)

_PROCEDURAL_HINTS = (
    "stir",
    "mix",
    "dissolve",
    "synthes",
    "fabricat",
    "prepare",
    "hydrothermal",
    "solvothermal",
    "calcine",
    "anneal",
    "wash",
    "dry",
    "heat",
    "cure",
    "cast",
    "filter",
    "centrifug",
    "加入",
    "搅拌",
    "溶解",
    "制备",
    "退火",
    "烧结",
    "洗涤",
    "干燥",
    "加热",
)

_CONDITION_PATTERNS = (
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:c|°c|k|f)\b", re.IGNORECASE),
    re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:rpm|wt%|vol%|mol%|m|mm|um|μm|nm)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:under|in)\s+(?:air|argon|ar|nitrogen|n2|vacuum)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class DocumentProfile:
    document_id: str
    collection_id: str
    title: str | None
    source_filename: str | None
    doc_type: DocumentType
    protocol_extractable: ProtocolExtractability
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
            protocol_extractable=str(
                payload.get("protocol_extractable") or PROTOCOL_EXTRACTABLE_UNCERTAIN
            ),
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


def analyze_document_profile(
    *,
    collection_id: str,
    document_id: str,
    title: str | None,
    source_filename: str | None,
    analysis_title: str,
    text: str,
    sections: Sequence[Mapping[str, Any]],
) -> DocumentProfile:
    lowered_text = str(text or "").lower()
    normalized_sections = [
        section for section in sections if isinstance(section, Mapping)
    ]
    method_sections = [
        section
        for section in normalized_sections
        if str(section.get("section_type") or "") == "methods"
    ]
    characterization_sections = [
        section
        for section in normalized_sections
        if str(section.get("section_type") or "") == "characterization"
    ]
    method_text = "\n".join(str(section.get("text") or "") for section in method_sections)

    review_title_hits = sum(
        1 for pattern in _REVIEW_TITLE_PATTERNS if pattern.search(str(analysis_title or ""))
    )
    review_text_hits = sum(1 for hint in _REVIEW_TEXT_HINTS if hint in lowered_text)
    procedural_hits = _count_keyword_hits(method_text or lowered_text, _PROCEDURAL_HINTS)
    condition_hits = _count_pattern_hits(method_text or text, _CONDITION_PATTERNS)

    experimental_score = 0
    review_score = 0
    signals: list[str] = []
    warnings: list[str] = []

    if method_sections:
        experimental_score += 2
        signals.append("methods_section_detected")
    else:
        warnings.append("missing_methods_section")
    if characterization_sections:
        experimental_score += 1
        signals.append("characterization_section_detected")
    if procedural_hits >= 2:
        experimental_score += 2
        signals.append("procedural_actions_detected")
    elif procedural_hits == 1:
        experimental_score += 1
        signals.append("limited_procedural_actions_detected")
    if condition_hits >= 2:
        experimental_score += 1
        signals.append("condition_markers_detected")
    elif condition_hits == 1:
        signals.append("limited_condition_markers_detected")
    else:
        warnings.append("critical_parameters_incomplete")

    if review_title_hits:
        review_score += 2
        signals.append("review_title_detected")
    if review_text_hits:
        review_score += 1
        signals.append("review_language_detected")

    if review_score >= 2 and experimental_score >= 2:
        doc_type: DocumentType = DOC_TYPE_MIXED
        warnings.append("review_contamination_detected")
    elif review_score >= 2:
        doc_type = DOC_TYPE_REVIEW
    elif experimental_score >= 3:
        doc_type = DOC_TYPE_EXPERIMENTAL
    else:
        doc_type = DOC_TYPE_UNCERTAIN
        warnings.append("document_type_uncertain")

    if not str(text or "").strip():
        warnings.append("missing_document_text")
    elif len(str(text or "").strip()) < 120:
        warnings.append("limited_document_text")

    protocol_extractable = _derive_protocol_extractable(
        doc_type=doc_type,
        method_sections_detected=bool(method_sections),
        procedural_hits=procedural_hits,
        condition_hits=condition_hits,
        review_score=review_score,
    )

    if (
        protocol_extractable
        in {PROTOCOL_EXTRACTABLE_PARTIAL, PROTOCOL_EXTRACTABLE_UNCERTAIN}
        and condition_hits == 0
    ):
        warnings.append("condition_context_weak")

    confidence = _compute_confidence(
        doc_type=doc_type,
        protocol_extractable=protocol_extractable,
        signal_count=len(set(signals)),
        warning_count=len(set(warnings)),
        review_score=review_score,
        experimental_score=experimental_score,
    )

    return DocumentProfile(
        document_id=document_id,
        collection_id=collection_id,
        title=title,
        source_filename=source_filename,
        doc_type=doc_type,
        protocol_extractable=protocol_extractable,
        protocol_extractability_signals=tuple(sorted(set(signals))),
        parsing_warnings=tuple(sorted(set(warnings))),
        confidence=confidence,
    )


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
        DOC_TYPE_MIXED, 0
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


def _derive_protocol_extractable(
    *,
    doc_type: DocumentType,
    method_sections_detected: bool,
    procedural_hits: int,
    condition_hits: int,
    review_score: int,
) -> ProtocolExtractability:
    if doc_type == DOC_TYPE_REVIEW:
        return PROTOCOL_EXTRACTABLE_NO
    if doc_type == DOC_TYPE_EXPERIMENTAL:
        if method_sections_detected and procedural_hits >= 2 and condition_hits >= 2:
            return PROTOCOL_EXTRACTABLE_YES
        if method_sections_detected or procedural_hits > 0:
            return PROTOCOL_EXTRACTABLE_PARTIAL
        return PROTOCOL_EXTRACTABLE_UNCERTAIN
    if doc_type == DOC_TYPE_MIXED:
        if method_sections_detected or procedural_hits > 0:
            return PROTOCOL_EXTRACTABLE_PARTIAL
        return PROTOCOL_EXTRACTABLE_NO
    if method_sections_detected or procedural_hits > 0:
        return PROTOCOL_EXTRACTABLE_PARTIAL
    if review_score > 0:
        return PROTOCOL_EXTRACTABLE_NO
    return PROTOCOL_EXTRACTABLE_UNCERTAIN


def _count_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    lowered = str(text or "").lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def _count_pattern_hits(text: str, patterns: tuple[re.Pattern[str], ...]) -> int:
    source = str(text or "")
    return sum(1 for pattern in patterns if pattern.search(source))


def _compute_confidence(
    *,
    doc_type: DocumentType,
    protocol_extractable: ProtocolExtractability,
    signal_count: int,
    warning_count: int,
    review_score: int,
    experimental_score: int,
) -> float:
    base = {
        DOC_TYPE_EXPERIMENTAL: 0.82,
        DOC_TYPE_MIXED: 0.72,
        DOC_TYPE_REVIEW: 0.84,
        DOC_TYPE_UNCERTAIN: 0.56,
    }[doc_type]
    if protocol_extractable == PROTOCOL_EXTRACTABLE_YES:
        base += 0.06
    elif protocol_extractable == PROTOCOL_EXTRACTABLE_PARTIAL:
        base += 0.01
    elif protocol_extractable == PROTOCOL_EXTRACTABLE_UNCERTAIN:
        base -= 0.04

    strength = min(signal_count, 4) * 0.02
    noise = min(warning_count, 3) * 0.03
    if review_score >= 2 and experimental_score >= 2:
        noise += 0.03
    return round(max(0.5, min(0.98, base + strength - noise)), 2)


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return tuple(items)
    text = str(value).strip()
    return (text,) if text else ()


__all__ = [
    "DocumentProfile",
    "DocumentProfileSummary",
    "analyze_document_profile",
    "summarize_document_profile_collection",
]
