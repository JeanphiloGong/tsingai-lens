from __future__ import annotations

from hashlib import sha1
from typing import Any, Iterable

from domain.core import (
    DocumentProfile,
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)


PROJECTION_VERSION = "objective-evidence-map.v1"


def build_objective_evidence_map(
    *,
    objective: ResearchObjective,
    analysis: ObjectiveAnalysis,
    contributions: tuple[PaperContribution, ...],
    findings: tuple[Finding, ...],
    evidence_records: tuple[ObjectiveEvidence, ...],
    profiles: tuple[DocumentProfile, ...],
) -> dict[str, Any]:
    """Project one published Objective analysis into a read-only evidence map."""

    version = objective.published_analysis_version
    if version is None:
        raise ValueError("objective has no published analysis")
    expected = (objective.collection_id, objective.objective_id, version)
    if analysis.key != expected:
        raise ValueError("analysis is not the Objective published analysis version")
    for record in (*contributions, *findings, *evidence_records):
        if record.key[:3] != expected:
            raise ValueError("evidence map record crosses the published analysis version")

    objective_node_id = f"objective:{objective.objective_id}"
    nodes: list[dict[str, Any]] = [
        {
            "id": objective_node_id,
            "type": "objective",
            "label": objective.question,
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": list(objective.material_scope),
            "variables": list(objective.variables),
            "outcomes": list(objective.outcomes),
        }
    ]
    edges: list[dict[str, Any]] = []

    profiles_by_document_id = {item.document_id: item for item in profiles}
    contributions_by_document_id = {
        item.document_id: item for item in contributions
    }
    document_ids = _ordered_unique(
        (
            *(item.document_id for item in contributions),
            *(item.document_id for item in evidence_records),
        )
    )
    for document_id in document_ids:
        contribution = contributions_by_document_id.get(document_id)
        profile = profiles_by_document_id.get(document_id)
        document_node_id = f"document:{document_id}"
        nodes.append(
            {
                "id": document_node_id,
                "type": "document",
                "label": (
                    (profile.title or profile.source_filename)
                    if profile is not None
                    else document_id
                ),
                "document_id": document_id,
                "analysis_status": (
                    contribution.analysis_status if contribution is not None else "analyzed"
                ),
                "evidence_disposition": (
                    contribution.evidence_disposition
                    if contribution is not None
                    else None
                ),
                "evidence_disposition_reason": (
                    contribution.evidence_disposition_reason
                    if contribution is not None
                    else None
                ),
            }
        )
        edges.append(
            _edge(
                source=objective_node_id,
                target=document_node_id,
                relation="includes_document",
            )
        )

    evidence_by_id = {item.evidence_id: item for item in evidence_records}
    linked_evidence_ids: list[str] = []
    source_nodes: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_document_edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    for finding in findings:
        finding_node_id = f"finding:{finding.finding_id}"
        nodes.append(
            {
                "id": finding_node_id,
                "type": "finding",
                "label": finding.statement,
                "finding_id": finding.finding_id,
                "statement": finding.statement,
                "factors": list(finding.factors),
                "outcome": finding.outcome,
                "direction": finding.direction,
                "assertion_strength": finding.assertion_strength,
                "synthesis_status": finding.synthesis_status,
                "certainty": finding.certainty,
                "limitations": list(finding.limitations),
            }
        )
        edges.append(
            _edge(
                source=objective_node_id,
                target=finding_node_id,
                relation="has_finding",
            )
        )

        for relation, evidence_ids in (
            ("supports", finding.supporting_evidence_ids),
            ("contradicts", finding.contradicting_evidence_ids),
            ("contextualizes", finding.context_evidence_ids),
        ):
            for evidence_id in evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    raise ValueError(
                        f"finding references missing evidence: {evidence_id}"
                    )
                evidence_node_id = f"evidence:{evidence_id}"
                if evidence_id not in linked_evidence_ids:
                    linked_evidence_ids.append(evidence_id)
                    nodes.append(_evidence_node(evidence))
                    source_key = (
                        evidence.document_id,
                        evidence.source_kind,
                        evidence.source_ref,
                    )
                    source_node = source_nodes.setdefault(
                        source_key,
                        _source_node(evidence),
                    )
                    source_node["evidence_ids"].append(evidence_id)
                    edges.append(
                        _edge(
                            source=evidence_node_id,
                            target=source_node["id"],
                            relation="extracted_from",
                        )
                    )
                    source_document_edges.setdefault(
                        source_key,
                        _edge(
                            source=source_node["id"],
                            target=f"document:{evidence.document_id}",
                            relation="reported_in",
                        ),
                    )
                edges.append(
                    _edge(
                        source=finding_node_id,
                        target=evidence_node_id,
                        relation=relation,
                        condition_boundary=(
                            evidence_id in finding.condition_boundary_evidence_ids
                        ),
                    )
                )

    nodes.extend(source_nodes.values())
    edges.extend(source_document_edges.values())

    linked_evidence_set = set(linked_evidence_ids)
    direct_document_ids = {
        evidence_by_id[evidence_id].document_id
        for finding in findings
        for evidence_id in (
            *finding.supporting_evidence_ids,
            *finding.contradicting_evidence_ids,
        )
    }
    failed_document_count = sum(
        item.analysis_status == "failed" for item in contributions
    )
    return {
        "collection_id": objective.collection_id,
        "objective_id": objective.objective_id,
        "analysis_version": version,
        "projection_version": PROJECTION_VERSION,
        "complete": failed_document_count == 0,
        "nodes": nodes,
        "edges": edges,
        "coverage": {
            "total_document_count": len(contributions),
            "analyzed_document_count": sum(
                item.analysis_status == "analyzed" for item in contributions
            ),
            "excluded_document_count": sum(
                item.analysis_status == "excluded" for item in contributions
            ),
            "failed_document_count": failed_document_count,
            "direct_evidence_document_count": len(direct_document_ids),
            "finding_count": len(findings),
            "evidence_count": len(evidence_records),
            "source_count": len(source_nodes),
            "unlinked_evidence_count": len(
                set(evidence_by_id) - linked_evidence_set
            ),
        },
    }


def _evidence_node(evidence: ObjectiveEvidence) -> dict[str, Any]:
    result = evidence.reported_result
    return {
        "id": f"evidence:{evidence.evidence_id}",
        "type": "evidence",
        "label": (
            result.result_text if result is not None else evidence.source_excerpt
        ),
        "evidence_id": evidence.evidence_id,
        "document_id": evidence.document_id,
        "evidence_role": evidence.evidence_role,
        "attribution_scope": evidence.attribution_scope,
        "confidence": evidence.confidence,
        "direction": result.direction if result is not None else None,
        "outcome": result.outcome if result is not None else None,
        "source_excerpt": evidence.source_excerpt,
    }


def _source_node(evidence: ObjectiveEvidence) -> dict[str, Any]:
    source_key = "\x1f".join(
        (evidence.document_id, evidence.source_kind, evidence.source_ref)
    )
    return {
        "id": f"source:{sha1(source_key.encode('utf-8')).hexdigest()[:20]}",
        "type": "source",
        "label": f"{evidence.source_kind.replace('_', ' ').title()} · {evidence.source_ref}",
        "document_id": evidence.document_id,
        "source_kind": evidence.source_kind,
        "source_ref": evidence.source_ref,
        "source_excerpt": evidence.source_excerpt,
        "page_numbers": list(evidence.page_numbers),
        "evidence_ids": [],
    }


def _edge(
    *,
    source: str,
    target: str,
    relation: str,
    condition_boundary: bool = False,
) -> dict[str, Any]:
    edge_id = sha1(f"{source}\x1f{relation}\x1f{target}".encode("utf-8")).hexdigest()
    return {
        "id": f"edge:{edge_id[:24]}",
        "source": source,
        "target": target,
        "relation": relation,
        "condition_boundary": condition_boundary,
    }


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = ["PROJECTION_VERSION", "build_objective_evidence_map"]
