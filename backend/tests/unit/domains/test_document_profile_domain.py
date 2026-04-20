from __future__ import annotations

from domain.core.document_profile import (
    DocumentProfile,
    summarize_document_profile_collection,
)
from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
    PROTOCOL_EXTRACTABLE_NO,
    PROTOCOL_EXTRACTABLE_PARTIAL,
    PROTOCOL_EXTRACTABLE_UNCERTAIN,
    PROTOCOL_EXTRACTABLE_YES,
)


def test_document_profile_from_mapping_normalizes_identity_and_lists() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-exp",
            "collection_id": "col-1",
            "title": "Composite Processing Study",
            "source_filename": "paper.txt",
            "doc_type": "experimental",
            "protocol_extractable": "yes",
            "protocol_extractability_signals": ["methods_section_detected", "condition_markers_detected"],
            "parsing_warnings": [],
            "confidence": 0.91,
        }
    )

    assert profile.document_id == "doc-exp"
    assert profile.title == "Composite Processing Study"
    assert profile.source_filename == "paper.txt"
    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL
    assert profile.protocol_extractable == PROTOCOL_EXTRACTABLE_YES
    assert profile.protocol_extractability_signals == (
        "methods_section_detected",
        "condition_markers_detected",
    )


def test_document_profile_from_mapping_coerces_invalid_llm_status_values() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-bad",
            "collection_id": "col-1",
            "doc_type": "research_article",
            "protocol_extractable": "Laser-TIG hybrid additive manufacturing produced finer grains.",
            "protocol_extractability_signals": [
                "methods_section_detected",
                "procedural_actions_detected",
                "condition_markers_detected",
            ],
            "parsing_warnings": [],
        }
    )

    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL
    assert profile.protocol_extractable == PROTOCOL_EXTRACTABLE_YES


def test_document_profile_from_mapping_falls_back_to_partial_for_mixed_review_contamination() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-mixed",
            "collection_id": "col-1",
            "doc_type": "article",
            "protocol_extractable": "not_a_status",
            "protocol_extractability_signals": ["methods_section_detected"],
            "parsing_warnings": ["review_contamination_detected"],
        }
    )

    assert profile.doc_type == "mixed"
    assert profile.protocol_extractable == PROTOCOL_EXTRACTABLE_PARTIAL


def test_summarize_document_profile_collection_emits_collection_warnings() -> None:
    review_profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-review",
            "collection_id": "col-1",
            "doc_type": DOC_TYPE_REVIEW,
            "protocol_extractable": PROTOCOL_EXTRACTABLE_NO,
        }
    )
    uncertain_profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-uncertain",
            "collection_id": "col-1",
            "doc_type": DOC_TYPE_UNCERTAIN,
            "protocol_extractable": PROTOCOL_EXTRACTABLE_UNCERTAIN,
        }
    )

    summary = summarize_document_profile_collection([review_profile, uncertain_profile])

    assert summary.total_documents == 2
    assert summary.by_doc_type == {
        DOC_TYPE_REVIEW: 1,
        DOC_TYPE_UNCERTAIN: 1,
    }
    assert summary.by_protocol_extractable == {
        PROTOCOL_EXTRACTABLE_NO: 1,
        PROTOCOL_EXTRACTABLE_UNCERTAIN: 1,
    }
    assert (
        "Collection is review-heavy or mixed; protocol outputs should be treated cautiously."
        in summary.warnings
    )
    assert "No protocol-suitable documents were detected in this collection." in summary.warnings
    assert "Some documents remain uncertain and may need manual review." in summary.warnings
