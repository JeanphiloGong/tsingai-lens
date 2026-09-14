import pytest

from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import SourceObservation


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


def test_source_observation_requires_current_identity_fields() -> None:
    with pytest.raises(ValueError, match="objective_id"):
        SourceObservation.from_mapping({"paper_id": "doc_legacy"})


def test_source_observation_does_not_accept_legacy_anchor_only_payload() -> None:
    with pytest.raises(ValueError, match="objective_id"):
        SourceObservation.from_mapping({"anchor_ids": ["anchor_legacy"]})
