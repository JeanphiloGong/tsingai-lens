from __future__ import annotations

from application.source.reference_extraction_service import (
    SourceReferenceExtractionService,
)
from domain.source import SourceArtifactSet, SourceBlock


def test_source_reference_extraction_builds_entries_mentions_and_candidates():
    artifacts = SourceArtifactSet(
        blocks=(
            SourceBlock(
                block_id="blk-title",
                document_id="doc-1",
                block_type="title",
                text="LPBF 316L Study",
                block_order=0,
            ),
            SourceBlock(
                block_id="blk-body-1",
                document_id="doc-1",
                block_type="paragraph",
                text="Prior LPBF 316L work [1] reported porosity effects.",
                block_order=1,
                page=2,
            ),
            SourceBlock(
                block_id="blk-body-2",
                document_id="doc-1",
                block_type="paragraph",
                text="Related studies [1, 2] also discuss scanning speed.",
                block_order=2,
                page=2,
            ),
            SourceBlock(
                block_id="blk-ref-heading",
                document_id="doc-1",
                block_type="heading",
                text="References",
                block_order=3,
                page=12,
                heading_level=1,
            ),
            SourceBlock(
                block_id="blk-ref-1",
                document_id="doc-1",
                block_type="paragraph",
                text=(
                    "[1] Smith A. Additive manufacturing of 316L stainless steel. "
                    "Acta Mater. 2024. doi:10.1000/example."
                ),
                block_order=4,
                page=12,
            ),
            SourceBlock(
                block_id="blk-ref-2",
                document_id="doc-1",
                block_type="paragraph",
                text=(
                    "[2] Chen B. Scan speed effects in LPBF metals. "
                    "Materials Letters. 2023."
                ),
                block_order=5,
                page=12,
            ),
        )
    )

    references = SourceReferenceExtractionService().extract(artifacts)

    assert [entry.reference_id for entry in references.entries] == [
        "ref-doc-1-0001",
        "ref-doc-1-0002",
    ]
    assert references.entries[0].title == (
        "Additive manufacturing of 316L stainless steel"
    )
    assert references.entries[0].doi == "10.1000/example"
    assert references.entries[1].year == 2023
    assert [
        (mention.reference_id, mention.citation_marker)
        for mention in references.mentions
    ] == [
        ("ref-doc-1-0001", "[1]"),
        ("ref-doc-1-0001", "[1]"),
        ("ref-doc-1-0002", "[2]"),
    ]
    assert "reported porosity" in references.mentions[0].context_text
    assert [candidate.reference_id for candidate in references.candidates] == [
        "ref-doc-1-0001",
        "ref-doc-1-0002",
    ]
    assert references.candidates[0].mention_count == 2
    assert references.candidates[0].status == "metadata_only"


def test_source_reference_extraction_ignores_reference_section_citation_markers():
    artifacts = SourceArtifactSet(
        blocks=(
            SourceBlock(
                block_id="blk-body",
                document_id="doc-1",
                block_type="paragraph",
                text="This paragraph has a range citation [1-3].",
                block_order=1,
            ),
            SourceBlock(
                block_id="blk-ref-heading",
                document_id="doc-1",
                block_type="heading",
                text="Bibliography",
                block_order=2,
            ),
            SourceBlock(
                block_id="blk-ref-1",
                document_id="doc-1",
                block_type="paragraph",
                text="[1] First Author. First Paper. Journal. 2021.",
                block_order=3,
            ),
            SourceBlock(
                block_id="blk-ref-2",
                document_id="doc-1",
                block_type="paragraph",
                text="[2] Second Author. Second Paper. Journal. 2022.",
                block_order=4,
            ),
            SourceBlock(
                block_id="blk-ref-3",
                document_id="doc-1",
                block_type="paragraph",
                text="[3] Third Author. Third Paper. Journal. 2023.",
                block_order=5,
            ),
        )
    )

    references = SourceReferenceExtractionService().extract(artifacts)

    assert len(references.entries) == 3
    assert [
        (mention.reference_id, mention.citation_marker)
        for mention in references.mentions
    ] == [
        ("ref-doc-1-0001", "[1]"),
        ("ref-doc-1-0002", "[2]"),
        ("ref-doc-1-0003", "[3]"),
    ]
    assert {candidate.mention_count for candidate in references.candidates} == {1}
