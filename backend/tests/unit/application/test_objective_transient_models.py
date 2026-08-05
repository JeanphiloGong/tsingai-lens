from application.core.objectives.evidence_extraction import ExtractedEvidenceDraft
from application.core.objectives.evidence_routing import EvidenceCandidate
from application.core.objectives.research_objective_service import PaperAnalysisFrame


def test_paper_analysis_frame_does_not_accept_legacy_paper_id() -> None:
    frame = PaperAnalysisFrame.from_mapping({"paper_id": "doc_legacy"})

    assert frame.document_id == ""


def test_evidence_candidate_does_not_accept_legacy_paper_id() -> None:
    candidate = EvidenceCandidate.from_mapping({"paper_id": "doc_legacy"})

    assert candidate.document_id == ""


def test_extracted_evidence_draft_does_not_accept_legacy_paper_id() -> None:
    draft = ExtractedEvidenceDraft.from_mapping({"paper_id": "doc_legacy"})

    assert draft.document_id == ""


def test_extracted_evidence_draft_does_not_accept_legacy_anchor_ids() -> None:
    draft = ExtractedEvidenceDraft.from_mapping({"anchor_ids": ["anchor_legacy"]})

    assert draft.evidence_anchor_ids == ()
