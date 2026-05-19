from __future__ import annotations

from domain.core.document_profile import (
    DocumentProfile,
    summarize_document_profile_collection,
)
from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
)


def test_document_profile_from_mapping_normalizes_identity_and_lists() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-exp",
            "collection_id": "col-1",
            "title": "Composite Processing Study",
            "source_filename": "paper.txt",
            "doc_type": "experimental",
            "parsing_warnings": [],
            "confidence": 0.91,
        }
    )

    assert profile.document_id == "doc-exp"
    assert profile.title == "Composite Processing Study"
    assert profile.source_filename == "paper.txt"
    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL


def test_document_profile_from_mapping_coerces_invalid_doc_type() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-bad",
            "collection_id": "col-1",
            "doc_type": "research_article",
            "parsing_warnings": [],
        }
    )

    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL


def test_document_profile_from_mapping_does_not_infer_doc_type_from_warnings() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-mixed",
            "collection_id": "col-1",
            "doc_type": "article",
            "parsing_warnings": ["review_contamination_detected"],
        }
    )

    assert profile.doc_type == DOC_TYPE_UNCERTAIN


def test_summarize_document_profile_collection_emits_collection_warnings() -> None:
    review_profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-review",
            "collection_id": "col-1",
            "doc_type": DOC_TYPE_REVIEW,
        }
    )
    uncertain_profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-uncertain",
            "collection_id": "col-1",
            "doc_type": DOC_TYPE_UNCERTAIN,
        }
    )

    summary = summarize_document_profile_collection([review_profile, uncertain_profile])

    assert summary.total_documents == 2
    assert summary.by_doc_type == {
        DOC_TYPE_REVIEW: 1,
        DOC_TYPE_UNCERTAIN: 1,
    }
    assert (
        "Collection is review-heavy or mixed; experimental evidence may require manual review."
        in summary.warnings
    )
    assert "Some documents remain uncertain and may need manual review." in summary.warnings
