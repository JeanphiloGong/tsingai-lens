from __future__ import annotations

from typing import Mapping

import domain.core as core_domain
import pytest
from application.core.objectives.analysis.source_extraction import (
    _observation_from_extraction,
)
from domain.core import (
    ObjectiveEvidence,
)
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _datetime_or_none as finding_datetime_or_none
from domain.core.finding import _text as finding_text
from domain.core.research_objective import (
    EVIDENCE_ORIGINS,
    SOURCE_KIND_VALUES,
    ObjectiveEvidence,
)
from domain.core.research_objective import (
    _positive_int_or_none as objective_positive_int_or_none,
)
from domain.core.research_objective import _positive_ints as objective_positive_ints
from domain.core.research_objective import (
    normalize_objective_confidence,
    normalize_objective_terms,
)
from domain.core.scientific_fact import (
    SCIENTIFIC_CONTEXT_SCOPES,
    SCIENTIFIC_RESULT_DIRECTIONS,
    SCIENTIFIC_RESULT_KINDS,
    ScientificAttribute,
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)
from domain.core.scientific_fact import _choice as scientific_choice
from domain.core.scientific_fact import _scientific_scalar as scientific_scalar
from domain.core.scientific_fact import _terms as scientific_terms
from domain.core.scientific_fact import _text as scientific_text


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
        collection_id=finding_text(payload.get("collection_id", None)) or "",
        objective_id=finding_text(payload.get("objective_id", None)) or "",
        analysis_version=1,
        evidence_id="evd-1",
        document_id=finding_text(payload.get("document_id", None)) or "",
        source_kind=finding_choice(
            payload.get("source_kind", None), SOURCE_KIND_VALUES, "text_window"
        ),
        source_ref=finding_text(payload.get("source_ref", None)) or "",
        source_excerpt=finding_text(payload.get("source_excerpt", None)) or "",
        page_numbers=objective_positive_ints(payload.get("page_numbers", None)),
        related_source_refs=tuple(
            (
                dict(item)
                for item in (
                    payload.get("related_source_refs", None)
                    if isinstance(
                        payload.get("related_source_refs", None), (list, tuple)
                    )
                    else ()
                )
                if isinstance(item, Mapping)
            )
        ),
        evidence_role="direct_result",
        selection_status="extracted",
        selection_reason=finding_text(payload.get("selection_reason", None)),
        changed_variables=tuple(
            (
                ScientificVariable(
                    name=scientific_text(item.get("name")) or "",
                    baseline_value=scientific_scalar(item.get("baseline_value")),
                    target_value=scientific_scalar(item.get("target_value")),
                    unit=scientific_text(item.get("unit")),
                )
                for item in (
                    payload.get("changed_variables", None)
                    if isinstance(payload.get("changed_variables", None), (list, tuple))
                    else ()
                )
                if isinstance(item, Mapping)
            )
        ),
        comparison=(
            ScientificComparison(
                baseline_label=scientific_text(
                    {
                        **payload,
                        "analysis_version": 1,
                        "evidence_id": "evd-1",
                        "evidence_role": "direct_result",
                        "selection_status": "extracted",
                        "attribution_scope": "isolated_effect",
                        "resolution_status": "resolved",
                    }["comparison"].get("baseline_label")
                )
                or "",
                target_label=scientific_text(
                    {
                        **payload,
                        "analysis_version": 1,
                        "evidence_id": "evd-1",
                        "evidence_role": "direct_result",
                        "selection_status": "extracted",
                        "attribution_scope": "isolated_effect",
                        "resolution_status": "resolved",
                    }["comparison"].get("target_label")
                )
                or "",
                axis_names=scientific_terms(
                    {
                        **payload,
                        "analysis_version": 1,
                        "evidence_id": "evd-1",
                        "evidence_role": "direct_result",
                        "selection_status": "extracted",
                        "attribution_scope": "isolated_effect",
                        "resolution_status": "resolved",
                    }["comparison"].get("axis_names")
                ),
                comparable={
                    **payload,
                    "analysis_version": 1,
                    "evidence_id": "evd-1",
                    "evidence_role": "direct_result",
                    "selection_status": "extracted",
                    "attribution_scope": "isolated_effect",
                    "resolution_status": "resolved",
                }["comparison"].get("comparable")
                is True,
                incomparability_reasons=scientific_terms(
                    {
                        **payload,
                        "analysis_version": 1,
                        "evidence_id": "evd-1",
                        "evidence_role": "direct_result",
                        "selection_status": "extracted",
                        "attribution_scope": "isolated_effect",
                        "resolution_status": "resolved",
                    }["comparison"].get("incomparability_reasons")
                ),
            )
            if isinstance(payload.get("comparison", None), Mapping)
            else None
        ),
        reported_result=(
            ScientificResult(
                outcome=scientific_text(
                    payload.get("reported_result", None).get("outcome")
                )
                or "",
                value=scientific_scalar(
                    payload.get("reported_result", None).get("value")
                ),
                unit=scientific_text(payload.get("reported_result", None).get("unit")),
                direction=scientific_choice(
                    payload.get("reported_result", None).get("direction"),
                    SCIENTIFIC_RESULT_DIRECTIONS,
                    "unknown",
                ),
                result_text=scientific_text(
                    payload.get("reported_result", None).get("result_text")
                )
                or "",
                baseline_value=scientific_scalar(
                    payload.get("reported_result", None).get("baseline_value")
                ),
                target_value=scientific_scalar(
                    payload.get("reported_result", None).get("target_value")
                ),
                result_kind=scientific_choice(
                    payload.get("reported_result", None).get("result_kind"),
                    SCIENTIFIC_RESULT_KINDS,
                    "observed",
                ),
            )
            if isinstance(payload.get("reported_result", None), Mapping)
            else None
        ),
        attribution_scope="isolated_effect",
        scientific_context=(
            ScientificContext(
                material=tuple(
                    (
                        ScientificAttribute(
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
                            ),
                        )
                        for attribute in (
                            {
                                **payload,
                                "analysis_version": 1,
                                "evidence_id": "evd-1",
                                "evidence_role": "direct_result",
                                "selection_status": "extracted",
                                "attribution_scope": "isolated_effect",
                                "resolution_status": "resolved",
                            }["scientific_context"].get("material")
                            if isinstance(
                                {
                                    **payload,
                                    "analysis_version": 1,
                                    "evidence_id": "evd-1",
                                    "evidence_role": "direct_result",
                                    "selection_status": "extracted",
                                    "attribution_scope": "isolated_effect",
                                    "resolution_status": "resolved",
                                }["scientific_context"].get("material"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
                sample=tuple(
                    (
                        ScientificAttribute(
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
                            ),
                        )
                        for attribute in (
                            {
                                **payload,
                                "analysis_version": 1,
                                "evidence_id": "evd-1",
                                "evidence_role": "direct_result",
                                "selection_status": "extracted",
                                "attribution_scope": "isolated_effect",
                                "resolution_status": "resolved",
                            }["scientific_context"].get("sample")
                            if isinstance(
                                {
                                    **payload,
                                    "analysis_version": 1,
                                    "evidence_id": "evd-1",
                                    "evidence_role": "direct_result",
                                    "selection_status": "extracted",
                                    "attribution_scope": "isolated_effect",
                                    "resolution_status": "resolved",
                                }["scientific_context"].get("sample"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
                process=tuple(
                    (
                        ScientificAttribute(
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
                            ),
                        )
                        for attribute in (
                            {
                                **payload,
                                "analysis_version": 1,
                                "evidence_id": "evd-1",
                                "evidence_role": "direct_result",
                                "selection_status": "extracted",
                                "attribution_scope": "isolated_effect",
                                "resolution_status": "resolved",
                            }["scientific_context"].get("process")
                            if isinstance(
                                {
                                    **payload,
                                    "analysis_version": 1,
                                    "evidence_id": "evd-1",
                                    "evidence_role": "direct_result",
                                    "selection_status": "extracted",
                                    "attribution_scope": "isolated_effect",
                                    "resolution_status": "resolved",
                                }["scientific_context"].get("process"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
                test=tuple(
                    (
                        ScientificAttribute(
                            name=scientific_text(attribute.get("name")) or "",
                            value=(
                                scientific_scalar(attribute.get("value"))
                                if scientific_scalar(attribute.get("value")) is not None
                                else ""
                            ),
                            unit=scientific_text(attribute.get("unit")),
                            context_scope=scientific_choice(
                                attribute.get("context_scope"),
                                SCIENTIFIC_CONTEXT_SCOPES,
                                "unknown",
                            ),
                            applies_to_outcomes=scientific_terms(
                                attribute.get("applies_to_outcomes")
                            ),
                        )
                        for attribute in (
                            {
                                **payload,
                                "analysis_version": 1,
                                "evidence_id": "evd-1",
                                "evidence_role": "direct_result",
                                "selection_status": "extracted",
                                "attribution_scope": "isolated_effect",
                                "resolution_status": "resolved",
                            }["scientific_context"].get("test")
                            if isinstance(
                                {
                                    **payload,
                                    "analysis_version": 1,
                                    "evidence_id": "evd-1",
                                    "evidence_role": "direct_result",
                                    "selection_status": "extracted",
                                    "attribution_scope": "isolated_effect",
                                    "resolution_status": "resolved",
                                }["scientific_context"].get("test"),
                                (list, tuple),
                            )
                            else ()
                        )
                        if isinstance(attribute, Mapping)
                    )
                ),
            )
            if isinstance(payload.get("scientific_context", None), Mapping)
            else ScientificContext()
        ),
        resolution_status="resolved",
        failure_reason=finding_text(payload.get("failure_reason", None)),
        confidence=normalize_objective_confidence(payload.get("confidence", None)),
        related_source_refs_explicit="related_source_refs"
        in {
            **payload,
            "analysis_version": 1,
            "evidence_id": "evd-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "attribution_scope": "isolated_effect",
            "resolution_status": "resolved",
        },
        origin=finding_choice(
            payload.get("origin", None), EVIDENCE_ORIGINS, "system_generated"
        ),
        source_analysis_version=objective_positive_int_or_none(
            payload.get("source_analysis_version", None)
        ),
        supersedes_evidence_id=finding_text(
            payload.get("supersedes_evidence_id", None)
        ),
        superseded_by_evidence_id=finding_text(
            payload.get("superseded_by_evidence_id", None)
        ),
        created_by_user_id=finding_text(payload.get("created_by_user_id", None)),
        created_by_tool_call_id=finding_text(
            payload.get("created_by_tool_call_id", None)
        ),
        created_at=finding_datetime_or_none(payload.get("created_at", None)),
        authoring_note=finding_text(payload.get("authoring_note", None)),
        warnings=normalize_objective_terms(payload.get("warnings", None)),
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
