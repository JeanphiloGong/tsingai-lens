from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from application.core.objectives.evidence_extraction import ExtractedEvidenceDraft
from application.core.objectives.evidence_routing import EvidenceCandidate


def test_paper_analysis_frame_does_not_accept_legacy_paper_id() -> None:
    frame = PaperAnalysisFrame.from_mapping({"paper_id": "doc_legacy"})

    assert frame.document_id == ""


def test_paper_analysis_frame_round_trips_source_disposition_provenance() -> None:
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_dispositions": [
                {
                    "source_unit_id": "frame-section-results",
                    "source_kind": "section",
                    "source_ref": "results",
                    "disposition": "repaired_relevant",
                    "accounting_errors": [
                        "missing_source_unit_ids=['frame-section-results']"
                    ],
                }
            ],
        }
    )

    assert frame.source_dispositions[0].is_relevant
    assert PaperAnalysisFrame.from_mapping(frame.to_record()) == frame


def test_evidence_candidate_does_not_accept_legacy_paper_id() -> None:
    candidate = EvidenceCandidate.from_mapping({"paper_id": "doc_legacy"})

    assert candidate.document_id == ""


def test_extracted_evidence_draft_does_not_accept_legacy_paper_id() -> None:
    draft = ExtractedEvidenceDraft.from_mapping({"paper_id": "doc_legacy"})

    assert draft.document_id == ""


def test_extracted_evidence_draft_does_not_accept_legacy_anchor_ids() -> None:
    draft = ExtractedEvidenceDraft.from_mapping({"anchor_ids": ["anchor_legacy"]})

    assert draft.evidence_anchor_ids == ()
