from __future__ import annotations

from domain.core.document_profile import (
    analyze_document_profile,
    summarize_document_profile_collection,
)
from domain.shared.enums import (
    DOC_TYPE_EXPERIMENTAL,
    DOC_TYPE_MIXED,
    DOC_TYPE_REVIEW,
    DOC_TYPE_UNCERTAIN,
    PROTOCOL_EXTRACTABLE_NO,
    PROTOCOL_EXTRACTABLE_PARTIAL,
    PROTOCOL_EXTRACTABLE_UNCERTAIN,
    PROTOCOL_EXTRACTABLE_YES,
)


def test_analyze_document_profile_classifies_experimental_document() -> None:
    profile = analyze_document_profile(
        collection_id="col-1",
        document_id="doc-exp",
        title="Composite Processing Study",
        source_filename=None,
        analysis_title="Composite Processing Study",
        text=(
            "Experimental Section\n"
            "Powders were mixed in ethanol, stirred for 2 h, dried at 80 C, "
            "and annealed at 600 C under argon.\n"
            "Characterization\n"
            "XRD and SEM were used to characterize the resulting powders."
        ),
        sections=[
            {
                "section_type": "methods",
                "text": (
                    "Powders were mixed in ethanol, stirred for 2 h, dried at 80 C, "
                    "and annealed at 600 C under argon."
                ),
            },
            {
                "section_type": "characterization",
                "text": "XRD and SEM were used to characterize the resulting powders.",
            },
        ],
    )

    assert profile.doc_type == DOC_TYPE_EXPERIMENTAL
    assert profile.protocol_extractable == PROTOCOL_EXTRACTABLE_YES
    assert "methods_section_detected" in profile.protocol_extractability_signals
    assert "characterization_section_detected" in profile.protocol_extractability_signals
    assert "procedural_actions_detected" in profile.protocol_extractability_signals
    assert "condition_markers_detected" in profile.protocol_extractability_signals


def test_analyze_document_profile_classifies_review_document() -> None:
    profile = analyze_document_profile(
        collection_id="col-1",
        document_id="doc-review",
        title="A Review of Conductive Ceramic Fillers",
        source_filename=None,
        analysis_title="A Review of Conductive Ceramic Fillers",
        text=(
            "This review summarizes recent advances in conductive ceramic fillers "
            "and discusses the state of the art across epoxy systems."
        ),
        sections=[],
    )

    assert profile.doc_type == DOC_TYPE_REVIEW
    assert profile.protocol_extractable == PROTOCOL_EXTRACTABLE_NO
    assert "review_title_detected" in profile.protocol_extractability_signals
    assert "review_language_detected" in profile.protocol_extractability_signals
    assert "missing_methods_section" in profile.parsing_warnings


def test_analyze_document_profile_classifies_mixed_document() -> None:
    profile = analyze_document_profile(
        collection_id="col-1",
        document_id="doc-mixed",
        title="Review and Experimental Notes on Coatings",
        source_filename=None,
        analysis_title="Review and Experimental Notes on Coatings",
        text=(
            "This review also reports a validation study.\n"
            "Experimental Section\n"
            "Solutions were mixed and heated at 90 C for 4 h.\n"
            "Characterization\n"
            "SEM was used to inspect the coating."
        ),
        sections=[
            {
                "section_type": "methods",
                "text": "Solutions were mixed and heated at 90 C for 4 h.",
            },
            {
                "section_type": "characterization",
                "text": "SEM was used to inspect the coating.",
            },
        ],
    )

    assert profile.doc_type == DOC_TYPE_MIXED
    assert profile.protocol_extractable == PROTOCOL_EXTRACTABLE_PARTIAL
    assert "review_contamination_detected" in profile.parsing_warnings


def test_summarize_document_profile_collection_emits_collection_warnings() -> None:
    review_profile = analyze_document_profile(
        collection_id="col-1",
        document_id="doc-review",
        title="A Review of Cathode Stability",
        source_filename=None,
        analysis_title="A Review of Cathode Stability",
        text="This review summarizes recent advances in cycle stability studies.",
        sections=[],
    )
    uncertain_profile = analyze_document_profile(
        collection_id="col-1",
        document_id="doc-uncertain",
        title="Cathode Stability Note",
        source_filename=None,
        analysis_title="Cathode Stability Note",
        text="A short note about cathode stability trends.",
        sections=[],
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
