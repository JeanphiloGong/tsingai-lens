from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceReferenceCandidate,
    SourceReferenceEntry,
    SourceReferenceMention,
    SourceReferenceSet,
)


_REFERENCE_HEADING_PATTERN = re.compile(
    r"^(references|bibliography|works cited|literature cited)\s*$",
    re.IGNORECASE,
)
_NUMBERED_REFERENCE_PATTERN = re.compile(
    r"^\s*(?:\[(?P<bracket>\d+)\]|(?P<plain>\d+)[.)])\s+(?P<body>.+)\s*$",
    re.DOTALL,
)
_YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")
_DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[^\s,;]+", re.IGNORECASE)
_CITATION_PATTERN = re.compile(r"\[(?P<body>\d+(?:\s*(?:,\s*|\s*-\s*)\d+)*)\]")
_SPACE_PATTERN = re.compile(r"\s+")


class SourceReferenceExtractionService:
    """Extract citation metadata from Source structure artifacts."""

    def extract(self, artifacts: SourceArtifactSet) -> SourceReferenceSet:
        entries = self._extract_entries(artifacts.blocks)
        mentions = self._extract_mentions(artifacts.blocks, entries)
        return SourceReferenceSet(
            entries=tuple(entries),
            mentions=tuple(mentions),
            candidates=tuple(self._build_candidates(entries, mentions)),
        )

    def _extract_entries(
        self,
        blocks: Iterable[SourceBlock],
    ) -> list[SourceReferenceEntry]:
        entries: list[SourceReferenceEntry] = []
        blocks_by_document: dict[str, list[SourceBlock]] = defaultdict(list)
        for block in blocks:
            blocks_by_document[block.document_id].append(block)

        for document_id, document_blocks in blocks_by_document.items():
            document_blocks.sort(key=lambda block: block.block_order)
            in_reference_section = False
            for block in document_blocks:
                text = _normalize_text(block.text)
                if not text:
                    continue
                if self._is_reference_heading(block):
                    in_reference_section = True
                    continue
                if in_reference_section and self._is_new_non_reference_heading(block):
                    break
                if not in_reference_section:
                    continue
                entry = self._entry_from_block(
                    document_id=document_id,
                    block=block,
                    sequence=len(entries) + 1,
                )
                if entry is not None:
                    entries.append(entry)
        return entries

    def _extract_mentions(
        self,
        blocks: Iterable[SourceBlock],
        entries: list[SourceReferenceEntry],
    ) -> list[SourceReferenceMention]:
        entry_by_key = {
            (entry.document_id, entry.reference_index): entry
            for entry in entries
            if entry.reference_index
        }
        mentions: list[SourceReferenceMention] = []
        blocks_by_document: dict[str, list[SourceBlock]] = defaultdict(list)
        for block in blocks:
            blocks_by_document[block.document_id].append(block)

        for document_id, document_blocks in blocks_by_document.items():
            in_reference_section = False
            for block in sorted(document_blocks, key=lambda item: item.block_order):
                if self._is_reference_heading(block):
                    in_reference_section = True
                    continue
                if in_reference_section and self._is_new_non_reference_heading(block):
                    in_reference_section = False
                if in_reference_section:
                    continue

                for match in _CITATION_PATTERN.finditer(block.text):
                    for number in _expand_citation_numbers(match.group("body")):
                        entry = entry_by_key.get((document_id, number))
                        mentions.append(
                            SourceReferenceMention(
                                mention_id=(
                                    f"mention-{document_id}-"
                                    f"{block.block_id}-{len(mentions) + 1:04d}"
                                ),
                                document_id=document_id,
                                reference_id=entry.reference_id if entry else None,
                                citation_marker=f"[{number}]",
                                context_text=_context_window(block.text, match.start()),
                                source_block_id=block.block_id,
                                page=block.page,
                                char_start=match.start(),
                                char_end=match.end(),
                                confidence=0.9 if entry else 0.6,
                                metadata={"raw_marker": match.group(0)},
                            )
                        )
        return mentions

    def _build_candidates(
        self,
        entries: list[SourceReferenceEntry],
        mentions: list[SourceReferenceMention],
    ) -> list[SourceReferenceCandidate]:
        mentions_by_reference: dict[str, list[SourceReferenceMention]] = defaultdict(list)
        for mention in mentions:
            if mention.reference_id:
                mentions_by_reference[mention.reference_id].append(mention)

        candidates: list[SourceReferenceCandidate] = []
        for entry in entries:
            reference_mentions = mentions_by_reference.get(entry.reference_id, [])
            representative = reference_mentions[0] if reference_mentions else None
            candidates.append(
                SourceReferenceCandidate(
                    candidate_id=f"cand-{entry.reference_id}",
                    reference_id=entry.reference_id,
                    status="metadata_only",
                    relevance_score=_candidate_score(entry, reference_mentions),
                    relevance_reason=_candidate_reason(entry, reference_mentions),
                    cited_by_document_id=entry.document_id,
                    mention_count=len(reference_mentions),
                    representative_context=(
                        representative.context_text if representative else None
                    ),
                    resolved_doi=entry.doi,
                    resolved_url=f"https://doi.org/{entry.doi}" if entry.doi else None,
                    metadata={"source": "citation_reference_extraction"},
                )
            )
        candidates.sort(
            key=lambda candidate: (
                -candidate.relevance_score,
                candidate.reference_id,
            )
        )
        return candidates

    def _is_reference_heading(self, block: SourceBlock) -> bool:
        if str(block.block_type) != "heading":
            return False
        return bool(_REFERENCE_HEADING_PATTERN.match(_normalize_text(block.text)))

    def _is_new_non_reference_heading(self, block: SourceBlock) -> bool:
        return str(block.block_type) == "heading" and not self._is_reference_heading(block)

    def _entry_from_block(
        self,
        *,
        document_id: str,
        block: SourceBlock,
        sequence: int,
    ) -> SourceReferenceEntry | None:
        text = _normalize_text(block.text)
        match = _NUMBERED_REFERENCE_PATTERN.match(text)
        if not match:
            return None
        reference_index = match.group("bracket") or match.group("plain")
        raw_reference = f"[{reference_index}] {match.group('body')}".strip()
        doi = _extract_doi(raw_reference)
        return SourceReferenceEntry(
            reference_id=f"ref-{document_id}-{int(reference_index):04d}",
            document_id=document_id,
            raw_reference=raw_reference,
            reference_index=reference_index,
            title=_extract_title(match.group("body")),
            authors_text=_extract_authors(match.group("body")),
            year=_extract_year(raw_reference),
            doi=doi,
            source_block_id=block.block_id,
            page=block.page,
            confidence=0.85,
            metadata={"sequence": sequence},
        )


def _normalize_text(value: str) -> str:
    return _SPACE_PATTERN.sub(" ", value or "").strip()


def _expand_citation_numbers(value: str) -> list[str]:
    numbers: list[str] = []
    for part in re.split(r"\s*,\s*", value):
        if "-" not in part:
            numbers.append(part.strip())
            continue
        start_text, end_text = re.split(r"\s*-\s*", part, maxsplit=1)
        start = int(start_text)
        end = int(end_text)
        numbers.extend(str(number) for number in range(start, end + 1))
    return numbers


def _context_window(text: str, position: int, radius: int = 120) -> str:
    start = max(position - radius, 0)
    end = min(position + radius, len(text))
    return _normalize_text(text[start:end])


def _extract_year(value: str) -> int | None:
    match = _YEAR_PATTERN.search(value)
    return int(match.group(1)) if match else None


def _extract_doi(value: str) -> str | None:
    match = _DOI_PATTERN.search(value)
    if not match:
        return None
    return match.group(0).rstrip(".").lower()


def _extract_title(value: str) -> str | None:
    parts = [part.strip() for part in value.split(".") if part.strip()]
    if len(parts) < 2:
        return None
    for part in parts[1:]:
        if not _YEAR_PATTERN.fullmatch(part) and not part.lower().startswith("doi"):
            return part
    return None


def _extract_authors(value: str) -> str | None:
    parts = [part.strip() for part in value.split(".") if part.strip()]
    return parts[0] if parts else None


def _candidate_score(
    entry: SourceReferenceEntry,
    mentions: list[SourceReferenceMention],
) -> float:
    score = 0.2
    score += min(len(mentions), 5) * 0.12
    if entry.doi:
        score += 0.15
    if entry.title:
        score += 0.1
    return min(score, 1.0)


def _candidate_reason(
    entry: SourceReferenceEntry,
    mentions: list[SourceReferenceMention],
) -> str:
    pieces = [f"cited {len(mentions)} time(s) in {entry.document_id}"]
    if entry.doi:
        pieces.append("DOI present")
    if entry.title:
        pieces.append("title parsed")
    return "; ".join(pieces)
