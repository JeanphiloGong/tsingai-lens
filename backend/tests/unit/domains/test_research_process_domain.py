from __future__ import annotations

import domain.core as core_domain
import pytest
from application.core.objectives.analysis.source_extraction import (
    _observation_from_extraction,
)
from domain.core import (
    ObjectiveEvidence,
)
from domain.core.research_objective import (
    ObjectiveEvidence,
)
from domain.core.scientific_fact import (
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)


def test_observation_and_evidence_share_neutral_scientific_fact_values() -> None:
    scientific_variable = getattr(core_domain, "ScientificVariable")
    scientific_comparison = getattr(core_domain, "ScientificComparison")
    scientific_result = getattr(core_domain, "ScientificResult")
    scientific_context = getattr(core_domain, "ScientificContext")
    payload = {
        "collection_id": "col-1",
        "objective_id": "obj-1",
        "document_id": "doc-1",
        "source_kind": "table",
        "source_ref": "table-2",
        "source_excerpt": "P150 elongation increased from 72% to 82%.",
        "changed_variables": [
            {
                "name": "platform preheating",
                "baseline_value": "NP",
                "target_value": "P150",
            }
        ],
        "comparison": {
            "baseline_label": "NP",
            "target_label": "P150",
            "axis_names": ["platform preheating"],
            "comparable": True,
        },
        "reported_result": {
            "outcome": "elongation",
            "baseline_value": 72,
            "target_value": 82,
            "value": 82,
            "unit": "%",
            "direction": "increase",
            "result_text": "P150 elongation increased from 72% to 82%.",
        },
        "scientific_context": {
            "material": [{"name": "alloy", "value": "316L"}],
            "test": [{"name": "method", "value": "tensile test"}],
        },
        "confidence": 0.9,
    }

    observation = _observation_from_extraction(
        {
            **payload,
            "observation_id": "obs-1",
            "observation_role": "direct_result",
            "status": "validated",
        }
    )
    evidence = ObjectiveEvidence(
        collection_id=observation.collection_id,
        objective_id=observation.objective_id,
        analysis_version=1,
        evidence_id="evd-1",
        document_id=observation.document_id,
        source_kind=observation.source_kind,
        source_ref=observation.source_ref,
        source_excerpt=observation.source_excerpt,
        page_numbers=(),
        related_source_refs=(),
        evidence_role="direct_result",
        selection_status="extracted",
        selection_reason=None,
        changed_variables=observation.changed_variables,
        comparison=observation.comparison,
        reported_result=observation.reported_result,
        attribution_scope="isolated_effect",
        scientific_context=observation.scientific_context,
        resolution_status="resolved",
        failure_reason=None,
        confidence=observation.confidence,
    )

    for scientific_record in (observation, evidence):
        assert isinstance(scientific_record.changed_variables[0], scientific_variable)
        assert isinstance(scientific_record.comparison, scientific_comparison)
        assert isinstance(scientific_record.reported_result, scientific_result)
        assert isinstance(scientific_record.scientific_context, scientific_context)

    for evidence_owned_name in (
        "ObjectiveEvidenceAttribute",
        "ObjectiveEvidenceVariable",
        "ObjectiveEvidenceComparison",
        "ObjectiveEvidenceResult",
        "ObjectiveEvidenceContext",
    ):
        assert not hasattr(core_domain, evidence_owned_name)


def test_source_observation_ignores_legacy_anchor_ids() -> None:
    observation = _observation_from_extraction(
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
    assert not hasattr(observation, "evidence_anchor_ids")


def test_source_observation_rejects_missing_provenance() -> None:
    with pytest.raises(ValueError, match="source_ref"):
        _observation_from_extraction(
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
    observation = _observation_from_extraction(
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
    assert observation.evidence_id == "evd-1"


def test_rejected_source_observation_can_record_read_failure_without_excerpt() -> None:
    observation = _observation_from_extraction(
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


@pytest.mark.parametrize(
    "payload",
    [
        {
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "porosity",
                "value": 0.4,
                "unit": "%",
                "direction": "decrease",
                "result_text": "Porosity was 0.4%.",
            },
            "confidence": 0.8,
            "expected_id": "evd_15e62ff28a9508c537814ef6",
        },
        {
            "objective_id": "obj-1",
            "document_id": "doc-1",
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "evidence_role": "condition_context",
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Ti-6Al-4V"}]
            },
            "confidence": 0.7,
            "expected_id": "evd_e4234b70b849ef0881f593a6",
        },
    ],
)
def test_extraction_preserves_source_observation_identity(payload):
    assert (
        _observation_from_extraction(payload).observation_id == payload["expected_id"]
    )
