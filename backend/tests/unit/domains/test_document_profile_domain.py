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
            "title": "Composite Processing Study",
            "doc_type": "experimental",
            "profile_warnings": [],
            "confidence": 0.91,
        }
    )

    assert profile.document_id == "doc-exp"
    assert profile.title == "Composite Processing Study"
    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL
    assert set(profile.to_record()) == {
        "document_id",
        "title",
        "doc_type",
        "profile_warnings",
        "confidence",
        "profile_status",
        "source_fingerprint",
        "profile_version",
        "profile_fingerprint",
        "generated_at",
    }


def test_document_profile_from_mapping_coerces_invalid_doc_type() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-bad",
            "doc_type": "research_article",
            "profile_warnings": [],
        }
    )

    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL


def test_document_profile_from_mapping_does_not_infer_doc_type_from_warnings() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-mixed",
            "doc_type": "article",
            "profile_warnings": ["review_contamination_detected"],
        }
    )

    assert profile.doc_type == DOC_TYPE_UNCERTAIN


def test_summarize_document_profile_collection_emits_collection_warnings() -> None:
    review_profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-review",
            "doc_type": DOC_TYPE_REVIEW,
        }
    )
    uncertain_profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-uncertain",
            "doc_type": DOC_TYPE_UNCERTAIN,
        }
    )

    summary = summarize_document_profile_collection([review_profile, uncertain_profile])

    assert summary.total_documents == 2
    assert summary.by_doc_type == {
        DOC_TYPE_REVIEW: 1,
        DOC_TYPE_UNCERTAIN: 1,
    }
    assert summary.technical_failure_count == 0
    assert (
        "Collection is review-heavy or mixed; experimental evidence may require manual review."
        in summary.warnings
    )
    assert "Some documents remain uncertain and may need manual review." in summary.warnings


def test_summarize_document_profile_collection_separates_technical_failure() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-failed",
            "doc_type": "uncertain",
            "profile_warnings": ["document_profile_extraction_failed"],
            "profile_status": "extraction_failed",
        }
    )

    summary = summarize_document_profile_collection([profile])

    assert summary.technical_failure_count == 1
    assert "Some document profiles failed technical extraction and need retry." in summary.warnings


def test_document_profile_migrates_legacy_failure_warning_to_failure_status() -> None:
    profile = DocumentProfile.from_mapping(
        {
            "document_id": "doc-legacy-failed",
            "doc_type": "uncertain",
            "profile_warnings": ["document_profile_extraction_failed"],
        }
    )

    assert profile.profile_status == "extraction_failed"
