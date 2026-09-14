from __future__ import annotations

import pytest

from domain.core import MeasurementResult, PaperExperiment, SourceObservation


def test_source_observation_round_trips_source_grounded_fact() -> None:
    observation = SourceObservation.from_mapping(
        {
            "observation_id": "obs-1",
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "observation_role": "direct_result",
            "source_excerpt": "Elongation was 82% for the preheated sample.",
            "reported_result": {
                "outcome": "elongation",
                "value": 82,
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation was 82%.",
            },
            "confidence": 0.91,
            "evidence_anchor_ids": ["anchor-1"],
        }
    )

    assert observation.status == "unvalidated"
    assert observation.reported_result is not None
    assert observation.reported_result.value == 82
    assert observation.has_scientific_content
    assert observation.to_record()["evidence_anchor_ids"] == ["anchor-1"]


def test_source_observation_rejects_missing_provenance() -> None:
    with pytest.raises(ValueError, match="source_ref"):
        SourceObservation.from_mapping(
            {
                "observation_id": "obs-1",
                "collection_id": "col-1",
                "objective_id": "obj-1",
                "document_id": "doc-1",
                "source_kind": "table",
                "observation_role": "direct_result",
                "source_excerpt": "A result.",
                "reported_result": {
                    "outcome": "elongation",
                    "direction": "unknown",
                    "result_text": "A result.",
                },
                "confidence": 0.5,
            }
        )


def test_source_observation_accepts_extraction_record_shape() -> None:
    observation = SourceObservation.from_mapping(
        {
            "evidence_id": "evd-1",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "source_excerpt": "Yield strength was 900 MPa.",
                }
            ],
            "reported_result": {
                "outcome": "yield strength",
                "value": 900,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Yield strength was 900 MPa.",
            },
            "confidence": 0.8,
        }
    )

    assert observation.evidence_id == "evd-1"
    assert observation.collection_id == "unknown"
    assert observation.source_refs[0]["source_ref"] == "table-1"
    assert observation.source_excerpt == "Yield strength was 900 MPa."
    assert observation.to_record()["evidence_id"] == "evd-1"


def test_rejected_source_observation_can_record_read_failure_without_excerpt() -> None:
    observation = SourceObservation.from_mapping(
        {
            "evidence_id": "failed-1",
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "evidence_role": "irrelevant",
            "selection_status": "failed",
            "failure_reason": "provider unavailable",
            "status": "rejected",
            "confidence": 0,
        }
    )

    assert observation.status == "rejected"
    assert not observation.has_scientific_content


def test_paper_experiment_owns_only_same_document_facts() -> None:
    with pytest.raises(ValueError, match="belong to its document"):
        PaperExperiment(
            experiment_id="exp-1",
            collection_id="col-1",
            document_id="doc-1",
            study_id="study-1",
            measurements=(
                MeasurementResult.from_mapping(
                    {
                        "result_id": "result-1",
                        "document_id": "doc-2",
                        "collection_id": "col-1",
                        "property_normalized": "elongation",
                        "result_type": "measured",
                        "value_payload": {"value": 82},
                        "traceability_status": "direct",
                        "result_source_type": "table",
                        "epistemic_status": "directly_observed",
                    }
                ),
            ),
        )


def test_paper_experiment_round_trips_its_scientific_boundary() -> None:
    experiment = PaperExperiment.from_mapping(
        {
            "experiment_id": "exp-1",
            "collection_id": "col-1",
            "document_id": "doc-1",
            "study_id": "study-1",
            "status": "incomplete",
            "uncertainties": ["The paper does not report repetitions."],
        }
    )

    assert experiment.to_record()["status"] == "incomplete"
    assert experiment.uncertainties == ("The paper does not report repetitions.",)
