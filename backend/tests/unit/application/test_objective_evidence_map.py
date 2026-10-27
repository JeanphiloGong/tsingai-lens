from __future__ import annotations

from dataclasses import replace
from typing import Mapping

import pytest
from application.core.objectives.evidence_map import build_objective_evidence_map
from domain.core import (
    DocumentProfile,
    Finding,
    ObjectiveEvidence,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    PAPER_CONTRIBUTION_STATUSES,
    Finding,
    FindingPaperContribution,
)
from domain.core.finding import _certainty as finding_certainty
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _strings as finding_strings
from domain.core.finding import _text as finding_text
from domain.core.research_objective import (
    EVIDENCE_ROLE_VALUES,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)
from domain.core.research_objective import (
    _non_negative_int_or_none as objective_non_negative_int_or_none,
)
from domain.core.research_objective import (
    _positive_int_or_none,
)
from domain.core.research_objective import _scoped_id as objective_scoped_id
from domain.core.scientific_fact import (
    SCIENTIFIC_RESULT_DIRECTIONS,
    ScientificAttribute,
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)
from domain.core.scientific_fact import _choice as scientific_choice
from repositories.objective_repository import ObjectiveAnalysis


def _objective(*, published_version: int | None = 1) -> ResearchObjective:
    return ResearchObjective(
        collection_id="collection-1",
        objective_id="objective-1",
        question="How does heat treatment affect tensile strength?",
        material_scope=("Alloy A",),
        variables=("heat treatment temperature",),
        outcomes=("ultimate tensile strength",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("paper-1", "paper-2", "paper-3"),
        excluded_document_ids=(),
        confidence=0.9,
        reason=None,
        confirmation_status="confirmed",
        active_analysis_version=_positive_int_or_none(published_version),
        published_analysis_version=_positive_int_or_none(published_version),
    )


def _analysis() -> ObjectiveAnalysis:
    return ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_inputs=tuple(
            PreparedDocumentInput(
                document_id=f"paper-{index}",
                preparation_fingerprint=f"fingerprint-paper-{index}",
            )
            for index in range(1, 4)
        ),
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
    return ObjectiveEvidence(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        evidence_id=finding_text(evidence_id)
        or objective_scoped_id(
            "oev",
            "collection-1",
            "objective-1",
            1,
            finding_text(document_id) or "",
            "table",
            finding_text(source_ref) or "",
            finding_choice(
                "direct_result" if direction == "decrease" else "contradictory_result",
                EVIDENCE_ROLE_VALUES,
                "irrelevant",
            ),
            (
                ScientificResult(
                    outcome="ultimate tensile strength",
                    value=None,
                    unit=None,
                    direction=scientific_choice(
                        direction, SCIENTIFIC_RESULT_DIRECTIONS, "unknown"
                    ),
                    result_text="Ultimate tensile strength changed after treatment.",
                ).outcome
                if ScientificResult(
                    outcome="ultimate tensile strength",
                    value=None,
                    unit=None,
                    direction=scientific_choice(
                        direction, SCIENTIFIC_RESULT_DIRECTIONS, "unknown"
                    ),
                    result_text="Ultimate tensile strength changed after treatment.",
                )
                is not None
                else None
            ),
        ),
        document_id=finding_text(document_id) or "",
        source_kind="table",
        source_ref=finding_text(source_ref) or "",
        source_excerpt="Heat-treatment results from Table 7.",
        page_numbers=(20,),
        related_source_refs=(),
        evidence_role=finding_choice(
            "direct_result" if direction == "decrease" else "contradictory_result",
            EVIDENCE_ROLE_VALUES,
            "irrelevant",
        ),
        selection_status="extracted",
        selection_reason=None,
        changed_variables=(
            ScientificVariable(
                name="heat treatment temperature",
                baseline_value="as-built",
                target_value="800 C",
            ),
        ),
        comparison=ScientificComparison(
            baseline_label="as-built",
            target_label="800 C",
            axis_names=("heat treatment temperature",),
            comparable=True,
        ),
        reported_result=ScientificResult(
            outcome="ultimate tensile strength",
            value=None,
            unit=None,
            direction=scientific_choice(
                direction, SCIENTIFIC_RESULT_DIRECTIONS, "unknown"
            ),
            result_text="Ultimate tensile strength changed after treatment.",
        ),
        attribution_scope="isolated_effect",
        scientific_context=ScientificContext(
            material=(ScientificAttribute(name="alloy", value="Alloy A"),)
        ),
        resolution_status="resolved",
        failure_reason=None,
        confidence=0.9,
    )


def _contribution(
    document_id: str,
    *,
    status: str = "analyzed",
    disposition: str = "comparable_evidence",
) -> PaperContribution:
    failed = status == "failed"
    return PaperContribution(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_id=finding_text(document_id) or "",
        analysis_status=finding_choice(status, PAPER_CONTRIBUTION_STATUSES, "pending"),
        relevance="high",
        paper_role="primary_experiment",
        contribution_summary=None,
        material_match=(),
        changed_variables=(),
        measured_property_scope=(),
        test_environment_scope=(),
        exclusion_reason=finding_text("provider timeout" if failed else None),
        warnings=(),
        confidence=0.8,
        evidence_disposition=finding_text(disposition),
        routed_source_count=1,
        extracted_source_count=objective_non_negative_int_or_none(0 if failed else 1),
        comparable_evidence_count=objective_non_negative_int_or_none(
            0 if failed else 1
        ),
        failed_source_count=objective_non_negative_int_or_none(1 if failed else 0),
        evidence_disposition_reason=finding_text(
            "provider timeout" if failed else None
        ),
    )


def _needs_context_evidence(
    evidence_id: str,
    document_id: str,
    *,
    source_ref: str,
) -> ObjectiveEvidence:
    return ObjectiveEvidence(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        evidence_id=finding_text(evidence_id)
        or objective_scoped_id(
            "oev",
            "collection-1",
            "objective-1",
            1,
            finding_text(document_id) or "",
            "text_window",
            finding_text(source_ref) or "",
            "direct_result",
            None,
        ),
        document_id=finding_text(document_id) or "",
        source_kind="text_window",
        source_ref=finding_text(source_ref) or "",
        source_excerpt="Porosity was measured after the heat-treatment experiments.",
        page_numbers=(8,),
        related_source_refs=(),
        evidence_role="direct_result",
        selection_status="candidate",
        selection_reason="Target outcome mentioned but needs same-paper context.",
        changed_variables=(),
        comparison=None,
        reported_result=None,
        attribution_scope="not_attributable",
        scientific_context=ScientificContext(),
        resolution_status="unresolved",
        failure_reason=None,
        confidence=0.5,
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
    return Finding(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        finding_id="finding-1",
        statement="Heat treatment generally decreased tensile strength.",
        factors=("heat treatment temperature",),
        outcome="ultimate tensile strength",
        direction="decrease",
        assertion_strength="associative",
        attribution_scope=finding_choice(
            "isolated_effect",
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        synthesis_status="conflict",
        certainty=finding_certainty(Finding.certainty_for("conflict", evidence)),
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(
            material=(ScientificAttribute(name="alloy", value="Alloy A"),)
        ),
        limitations=("One paper reported the opposite direction.",),
        paper_contributions=tuple(
            (
                FindingPaperContribution(
                    document_id=finding_text(item.get("document_id")) or "",
                    analysis_status=finding_choice(
                        item.get("analysis_status"),
                        PAPER_CONTRIBUTION_STATUSES,
                        "pending",
                    ),
                    supporting_evidence_ids=finding_strings(
                        item.get("supporting_evidence_ids")
                    ),
                    contradicting_evidence_ids=finding_strings(
                        item.get("contradicting_evidence_ids")
                    ),
                    context_evidence_ids=finding_strings(
                        item.get("context_evidence_ids")
                    ),
                    condition_boundary_evidence_ids=finding_strings(
                        item.get("condition_boundary_evidence_ids")
                    ),
                )
                for item in tuple(
                    (
                        dict(item)
                        for item in (
                            contributions
                            if isinstance(contributions, (list, tuple))
                            else ()
                        )
                        if isinstance(item, Mapping)
                    )
                )
            )
        ),
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
            DocumentProfile(
                document_id="paper-1",
                title="Heat treatment study A",
                doc_type="experimental",
                confidence=0.9,
                profile_warnings=(),
            ),
            DocumentProfile(
                document_id="paper-2",
                title="Heat treatment study B",
                doc_type="experimental",
                confidence=0.9,
                profile_warnings=(),
            ),
        ),
    )

    assert payload["projection_version"] == "objective-evidence-map.v1"
    assert payload["analysis_version"] == 1
    assert payload["complete"] is False
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
        "evidence_status_counts": {"comparable": 3},
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


def test_evidence_map_is_complete_for_scientific_abstention() -> None:
    contribution = PaperContribution(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_id="paper-1",
        analysis_status="analyzed",
        relevance="high",
        paper_role="primary_experiment",
        contribution_summary=None,
        material_match=(),
        changed_variables=(),
        measured_property_scope=(),
        test_environment_scope=(),
        exclusion_reason=None,
        warnings=(),
        confidence=0.8,
        evidence_disposition="no_routable_evidence",
        routed_source_count=0,
        extracted_source_count=0,
        comparable_evidence_count=0,
        failed_source_count=0,
        evidence_disposition_reason="No source in this paper was selected for Objective extraction.",
    )
    payload = build_objective_evidence_map(
        objective=_objective(),
        analysis=_analysis(),
        contributions=(contribution,),
        findings=(),
        evidence_records=(),
        profiles=(),
    )

    assert payload["complete"] is True
    assert payload["coverage"]["failed_document_count"] == 0
    assert payload["coverage"]["direct_evidence_document_count"] == 0


def test_evidence_map_keeps_unlinked_needs_context_evidence_with_source_lineage() -> None:
    evidence = _needs_context_evidence(
        "evidence-context-1",
        "paper-1",
        source_ref="block-results-4",
    )
    contribution = PaperContribution(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_id="paper-1",
        analysis_status="analyzed",
        relevance="high",
        paper_role="primary_experiment",
        contribution_summary=None,
        material_match=(),
        changed_variables=(),
        measured_property_scope=(),
        test_environment_scope=(),
        exclusion_reason=None,
        warnings=(),
        confidence=0.8,
        evidence_disposition="no_comparable_evidence",
        routed_source_count=1,
        extracted_source_count=0,
        comparable_evidence_count=0,
        failed_source_count=0,
        evidence_disposition_reason="Selected sources need same-paper context before comparison.",
        evidence_status_counts=(("needs_context", 1),),
    )

    payload = build_objective_evidence_map(
        objective=_objective(),
        analysis=_analysis(),
        contributions=(contribution,),
        findings=(),
        evidence_records=(evidence,),
        profiles=(),
    )

    evidence_nodes = [
        node for node in payload["nodes"] if node["type"] == "evidence"
    ]
    source_nodes = [node for node in payload["nodes"] if node["type"] == "source"]
    assert len(evidence_nodes) == 1
    assert evidence_nodes[0]["evidence_status"] == "needs_context"
    assert evidence_nodes[0]["evidence_status_reason"] == (
        "Target outcome mentioned but needs same-paper context."
    )
    assert len(source_nodes) == 1
    assert source_nodes[0]["evidence_ids"] == ["evidence-context-1"]
    assert payload["coverage"]["unlinked_evidence_count"] == 1
    assert payload["coverage"]["evidence_status_counts"] == {"needs_context": 1}

    lineage_edges = [
        (edge["relation"], edge["source"], edge["target"])
        for edge in payload["edges"]
        if edge["relation"] in {"extracted_from", "reported_in"}
    ]
    assert len(lineage_edges) == 2
    assert lineage_edges[0][0] == "extracted_from"
    assert lineage_edges[1][0] == "reported_in"


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
