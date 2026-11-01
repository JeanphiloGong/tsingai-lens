import pytest

from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.source_screening import (
    PaperFrameSourceDisposition,
    PaperAnalysisFrame,
)
from domain.core import SourceObservation


def test_paper_analysis_frame_does_not_accept_legacy_paper_id() -> None:
    with pytest.raises(TypeError, match="paper_id"):
        PaperAnalysisFrame(paper_id='doc_legacy')


def test_paper_analysis_frame_preserves_source_disposition_provenance() -> None:
    frame = PaperAnalysisFrame(
        objective_id='obj-density',
        document_id='paper-1',
        relevance='uncertain',
        paper_role='uncertain',
        screening_note=None,
        material_match=(),
        changed_variables=(),
        measured_property_scope=(),
        test_environment_scope=(),
        relevant_sections=(),
        relevant_text_source_refs=(),
        relevant_tables=(),
        excluded_tables=(),
        source_dispositions=(
            PaperFrameSourceDisposition(
                source_unit_id='frame-section-results',
                source_kind='section',
                source_ref='results',
                disposition='repaired_relevant',
                accounting_errors=("missing_source_unit_ids=['frame-section-results']",),
            ),
        ),
    )

    assert frame.source_dispositions[0].is_relevant
    assert frame.source_dispositions[0].accounting_errors == (
        "missing_source_unit_ids=['frame-section-results']",
    )


def test_evidence_candidate_does_not_accept_legacy_paper_id() -> None:
    with pytest.raises(TypeError, match="paper_id"):
        EvidenceCandidate(paper_id='doc_legacy')


def test_source_observation_requires_current_identity_fields() -> None:
    with pytest.raises(TypeError, match="paper_id"):
        SourceObservation(paper_id="doc_legacy")


def test_source_observation_does_not_accept_legacy_anchor_only_payload() -> None:
    with pytest.raises(TypeError, match="anchor_ids"):
        SourceObservation(anchor_ids=["anchor_legacy"])
