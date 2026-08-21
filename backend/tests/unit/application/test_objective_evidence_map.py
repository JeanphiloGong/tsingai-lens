from __future__ import annotations

from dataclasses import replace

import pytest

from application.core.objectives.evidence_map import build_objective_evidence_map
from domain.core import (
    DocumentProfile,
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)


def _objective(*, published_version: int | None = 1) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "How does heat treatment affect tensile strength?",
            "material_scope": ["Alloy A"],
            "variables": ["heat treatment temperature"],
            "outcomes": ["ultimate tensile strength"],
            "seed_document_ids": ["paper-1", "paper-2", "paper-3"],
            "confidence": 0.9,
            "confirmation_status": "confirmed",
            "active_analysis_version": published_version,
            "published_analysis_version": published_version,
        }
    )


def _analysis() -> ObjectiveAnalysis:
    return ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="objective-analysis.v2",
        model_name="model-1",
        prompt_versions={},
        status="succeeded",
        phase="completed",
        processed_document_count=3,
        total_document_count=3,
    )


def _evidence(
    evidence_id: str,
    document_id: str,
    *,
    direction: str,
    source_ref: str,
) -> ObjectiveEvidence:
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "evidence_id": evidence_id,
            "document_id": document_id,
            "source_kind": "table",
            "source_ref": source_ref,
            "source_excerpt": "Heat-treatment results from Table 7.",
            "page_numbers": [20],
            "evidence_role": (
                "direct_result" if direction == "decrease" else "contradictory_result"
            ),
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "heat treatment temperature",
                    "baseline_value": "as-built",
                    "target_value": "800 C",
                }
            ],
            "comparison": {
                "baseline_label": "as-built",
                "target_label": "800 C",
                "axis_names": ["heat treatment temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "ultimate tensile strength",
                "direction": direction,
                "result_text": "Ultimate tensile strength changed after treatment.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Alloy A"}],
                "sample": [],
                "process": [],
                "test": [],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


def _contribution(
    document_id: str,
    *,
    status: str = "analyzed",
    disposition: str = "comparable_evidence",
) -> PaperContribution:
    failed = status == "failed"
    return PaperContribution.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "document_id": document_id,
            "analysis_status": status,
            "relevance": "high",
            "paper_role": "primary_experiment",
            "exclusion_reason": "provider timeout" if failed else None,
            "confidence": 0.8,
            "evidence_disposition": disposition,
            "routed_source_count": 1,
            "extracted_source_count": 0 if failed else 1,
            "comparable_evidence_count": 0 if failed else 1,
            "failed_source_count": 1 if failed else 0,
            "evidence_disposition_reason": "provider timeout" if failed else None,
        }
    )


def _finding(evidence: tuple[ObjectiveEvidence, ...]) -> Finding:
    contributions = (
        {
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "supporting_evidence_ids": ["evidence-1", "evidence-2"],
        },
        {
            "document_id": "paper-2",
            "analysis_status": "analyzed",
            "contradicting_evidence_ids": ["evidence-3"],
        },
        {
            "document_id": "paper-3",
            "analysis_status": "failed",
        },
    )
    return Finding.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "finding_id": "finding-1",
            "statement": "Heat treatment generally decreased tensile strength.",
            "factors": ["heat treatment temperature"],
            "outcome": "ultimate tensile strength",
            "direction": "decrease",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "conflict",
            "certainty": Finding.certainty_for("conflict", evidence),
            "mechanisms": [],
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Alloy A"}],
                "sample": [],
                "process": [],
                "test": [],
            },
            "limitations": ["One paper reported the opposite direction."],
            "paper_contributions": contributions,
        }
    )


def test_evidence_map_projects_published_scientific_and_source_lineage() -> None:
    evidence = (
        _evidence("evidence-1", "paper-1", direction="decrease", source_ref="table-7"),
        _evidence("evidence-2", "paper-1", direction="decrease", source_ref="table-7"),
        _evidence("evidence-3", "paper-2", direction="increase", source_ref="table-2"),
    )
    payload = build_objective_evidence_map(
        objective=_objective(),
        analysis=_analysis(),
        contributions=(
            _contribution("paper-1"),
            _contribution("paper-2"),
            _contribution(
                "paper-3",
                status="failed",
                disposition="extraction_failed",
            ),
        ),
        findings=(_finding(evidence),),
        evidence_records=evidence,
        profiles=(
            DocumentProfile.from_mapping(
                {
                    "collection_id": "collection-1",
                    "document_id": "paper-1",
                    "title": "Heat treatment study A",
                    "doc_type": "experimental",
                    "confidence": 0.9,
                }
            ),
            DocumentProfile.from_mapping(
                {
                    "collection_id": "collection-1",
                    "document_id": "paper-2",
                    "title": "Heat treatment study B",
                    "doc_type": "experimental",
                    "confidence": 0.9,
                }
            ),
        ),
    )

    assert payload["projection_version"] == "objective-evidence-map.v1"
    assert payload["analysis_version"] == 1
    assert payload["complete"] is True
    assert payload["coverage"] == {
        "total_document_count": 3,
        "analyzed_document_count": 2,
        "excluded_document_count": 0,
        "failed_document_count": 1,
        "direct_evidence_document_count": 2,
        "finding_count": 1,
        "evidence_count": 3,
        "source_count": 2,
        "unlinked_evidence_count": 0,
    }

    nodes_by_type = {
        node_type: [node for node in payload["nodes"] if node["type"] == node_type]
        for node_type in ("objective", "finding", "evidence", "source", "document")
    }
    assert len(nodes_by_type["objective"]) == 1
    assert len(nodes_by_type["finding"]) == 1
    assert len(nodes_by_type["evidence"]) == 3
    assert len(nodes_by_type["source"]) == 2
    assert len(nodes_by_type["document"]) == 3
    assert nodes_by_type["document"][0]["label"] == "Heat treatment study A"
    assert any(
        node["document_id"] == "paper-3"
        and node["analysis_status"] == "failed"
        and node["evidence_disposition"] == "extraction_failed"
        for node in nodes_by_type["document"]
    )

    relations = [edge["relation"] for edge in payload["edges"]]
    assert relations.count("supports") == 2
    assert relations.count("contradicts") == 1
    assert relations.count("extracted_from") == 3
    assert relations.count("reported_in") == 2
    assert relations.count("includes_document") == 3
    assert "contradicts" not in [
        edge["relation"]
        for edge in payload["edges"]
        if edge["target"].endswith("paper-3")
    ]


def test_evidence_map_rejects_an_unpublished_or_cross_version_projection() -> None:
    evidence = (_evidence("evidence-1", "paper-1", direction="decrease", source_ref="table-7"),)

    with pytest.raises(ValueError, match="published analysis"):
        build_objective_evidence_map(
            objective=_objective(published_version=None),
            analysis=_analysis(),
            contributions=(),
            findings=(),
            evidence_records=evidence,
            profiles=(),
        )

    with pytest.raises(ValueError, match="published analysis version"):
        build_objective_evidence_map(
            objective=_objective(),
            analysis=replace(_analysis(), analysis_version=2),
            contributions=(),
            findings=(),
            evidence_records=(),
            profiles=(),
        )
