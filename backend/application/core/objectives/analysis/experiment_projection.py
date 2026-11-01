"""Project fixed experiment graphs into existing scientific read values.

Queries return Finding, ObjectiveEvidence and paper coverage derived from
immutable revisions and selections without writing a second scientific ledger.
The Evidence map constructs its graph output directly from those same values.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    replace,
)
from hashlib import sha1
from typing import Any, Mapping

from application.core.objectives.analysis import experiment_query_service
from domain.core.finding import Finding, FindingPaperContribution
from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
    SourceReference,
)
from domain.core.research_objective import (
    ObjectiveEvidence,
    PaperContribution,
)
from domain.core.scientific_fact import (
    ScientificComparison,
    ScientificContext,
    ScientificResult,
)

from .experiment_query_service import ExperimentAnalysisBundle


@dataclass(frozen=True)
class _ProjectionState:
    collection_id: str
    objective_id: str
    analysis_version: int
    bundle: ExperimentAnalysisBundle
    revisions_by_identity: Mapping[tuple[str, int], PaperExperimentRevision]
    selections_by_id: Mapping[str, Any]
    evidence_ids_by_selection: Mapping[str, tuple[str, ...]]
    contributions_by_document: Mapping[str, PaperContribution]
    evidence_by_id: Mapping[str, ObjectiveEvidence]


from repositories.objective_repository import ObjectiveRepo


async def list_analysis_findings(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[tuple[Finding, ...], int]:
    state = await _state(collection_id, objective_id, analysis_version)
    records = tuple(
        _project_finding(finding, state) for finding in state.bundle.findings
    )
    records = tuple(
        sorted(
            records,
            key=lambda item: (
                item.display_rank,
                item.finding_id,
            ),
        )
    )
    start = max(0, offset)
    page_size = max(1, min(limit, 200))
    return records[start : start + page_size], len(records)


async def read_analysis_finding(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
) -> Finding | None:
    state = await _state(collection_id, objective_id, analysis_version)
    finding = next(
        (item for item in state.bundle.findings if item.finding_id == finding_id),
        None,
    )
    return _project_finding(finding, state) if finding is not None else None


async def list_analysis_evidence(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    finding_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[tuple[ObjectiveEvidence, ...], int]:
    state = await _state(collection_id, objective_id, analysis_version)
    allowed: set[str] | None = None
    if finding_id is not None:
        finding = next(
            (item for item in state.bundle.findings if item.finding_id == finding_id),
            None,
        )
        if finding is None:
            return (), 0
        allowed = {
            evidence_id
            for selection_id in finding.selection_ids
            for evidence_id in state.evidence_ids_by_selection.get(selection_id, ())
        }
    records = tuple(
        item
        for evidence_id, item in sorted(state.evidence_by_id.items())
        if allowed is None or evidence_id in allowed
    )
    start = max(0, offset)
    page_size = max(1, min(limit, 500))
    return records[start : start + page_size], len(records)


async def list_analysis_contributions(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> tuple[PaperContribution, ...]:
    state = await _state(collection_id, objective_id, analysis_version)
    return tuple(
        replace(value, uninspected_source_count=record["uninspected_source_count"])
        for value, record in _project_contributions(state, state.bundle.selections)
    )


def _project_contributions(
    state: _ProjectionState,
    selections: Any,
    *,
    include_links: bool = False,
) -> tuple[tuple[PaperContribution, dict[str, Any]], ...]:
    """Keep coverage metadata while replacing legacy Evidence ids.

    PaperContribution describes which papers were inspected, including
    excluded or failed papers. It is not a second scientific-fact store.
    The experiment graph supplies the current evidence ids for selected
    records; the coverage rows remain available for the legacy response.
    """
    contribution_by_document = {
        document_id: {
            "collection_id": value.collection_id,
            "objective_id": value.objective_id,
            "analysis_version": value.analysis_version,
            "document_id": value.document_id,
            "analysis_status": value.analysis_status,
            "relevance": value.relevance,
            "paper_role": value.paper_role,
            "contribution_summary": value.contribution_summary,
            "material_match": list(value.material_match),
            "changed_variables": list(value.changed_variables),
            "measured_property_scope": list(value.measured_property_scope),
            "test_environment_scope": list(value.test_environment_scope),
            "exclusion_reason": value.exclusion_reason,
            "warnings": list(value.warnings),
            "confidence": value.confidence,
            "evidence_disposition": value.evidence_disposition,
            "routed_source_count": value.routed_source_count,
            "extracted_source_count": value.extracted_source_count,
            "comparable_evidence_count": value.comparable_evidence_count,
            "failed_source_count": value.failed_source_count,
            "uninspected_source_count": value.uninspected_source_count,
            "evidence_disposition_reason": value.evidence_disposition_reason,
            "evidence_status_counts": {
                status: count for status, count in value.evidence_status_counts
            },
            "inspected_source_refs": [
                {
                    "source_kind": source_ref.source_kind,
                    "source_ref": source_ref.source_ref,
                    "source_digest": source_ref.source_digest,
                }
                for source_ref in value.inspected_source_refs
            ],
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "context_evidence_ids": [],
            "condition_boundary_evidence_ids": [],
        }
        for document_id, value in state.contributions_by_document.items()
    }
    initialized_documents: set[str] = set()
    for selection in selections:
        revision = state.revisions_by_identity.get(
            (selection.experiment_id, selection.experiment_version)
        )
        if revision is None:
            continue
        evidence_ids = state.evidence_ids_by_selection.get(selection.selection_id, ())
        if revision.document_id not in initialized_documents:
            contribution = contribution_by_document.setdefault(
                revision.document_id,
                _new_experiment_contribution(
                    collection_id=state.collection_id,
                    objective_id=selection.objective_id,
                    analysis_version=selection.analysis_version,
                    document_id=revision.document_id,
                    scope_description=revision.scope_description,
                    outcome=selection.outcome,
                ),
            )
            _reset_experiment_accounting(contribution)
            initialized_documents.add(revision.document_id)
        else:
            contribution = contribution_by_document[revision.document_id]
        measured_scope = list(contribution.get("measured_property_scope") or ())
        if selection.outcome not in measured_scope:
            measured_scope.append(selection.outcome)
        contribution["measured_property_scope"] = measured_scope
        contribution["contribution_summary"] = (
            contribution.get("contribution_summary") or revision.scope_description
        )
        for evidence_id in evidence_ids:
            if evidence_id not in contribution["supporting_evidence_ids"]:
                contribution["supporting_evidence_ids"].append(evidence_id)
            evidence = state.evidence_by_id[evidence_id]
            contribution["routed_source_count"] += 1
            contribution["extracted_source_count"] += 1
            status = experiment_evidence_disposition(evidence)[0]
            status_counts = contribution["evidence_status_counts"]
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "comparable":
                contribution["comparable_evidence_count"] += 1
        if contribution["comparable_evidence_count"] == 0:
            contribution["evidence_disposition"] = "no_comparable_evidence"
            contribution["evidence_disposition_reason"] = (
                "The experiment contains selected results but no comparable paper-internal relation."
            )
        else:
            contribution["evidence_disposition"] = "comparable_evidence"
            contribution["evidence_disposition_reason"] = None
    records = tuple(
        contribution_by_document[key] for key in sorted(contribution_by_document)
    )
    projected = []
    for record in records:
        document_id = record["document_id"]
        original = state.contributions_by_document.get(document_id)
        if document_id not in initialized_documents:
            value = original
        else:
            accounting = {
                "analysis_status": "analyzed",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "exclusion_reason": None,
                "contribution_summary": record["contribution_summary"],
                "measured_property_scope": tuple(record["measured_property_scope"]),
                "evidence_disposition": record["evidence_disposition"],
                "routed_source_count": record["routed_source_count"],
                "extracted_source_count": record["extracted_source_count"],
                "comparable_evidence_count": record["comparable_evidence_count"],
                "failed_source_count": 0,
                "evidence_disposition_reason": record["evidence_disposition_reason"],
                "evidence_status_counts": tuple(
                    sorted(record["evidence_status_counts"].items())
                ),
            }
            if original is not None:
                value = replace(original, **accounting)
            else:
                value = PaperContribution(
                    collection_id=state.collection_id,
                    objective_id=state.objective_id,
                    analysis_version=state.analysis_version,
                    document_id=document_id,
                    material_match=(),
                    changed_variables=(),
                    test_environment_scope=(),
                    warnings=(),
                    confidence=1.0,
                    uninspected_source_count=0,
                    **accounting,
                )
        response = (
            record
            if include_links
            else {
                key: field
                for key, field in record.items()
                if key not in _CONTRIBUTION_LINK_FIELDS
            }
        )
        projected.append((value, response))
    return tuple(projected)


async def read_analysis_records(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> tuple[
    tuple[Finding, ...],
    tuple[ObjectiveEvidence, ...],
    tuple[PaperContribution, ...],
]:
    """Return typed findings, evidence and paper coverage for internal readers."""

    state = await _state(collection_id, objective_id, analysis_version)
    findings = tuple(
        _project_finding(finding, state) for finding in state.bundle.findings
    )
    evidence = tuple(item for _, item in sorted(state.evidence_by_id.items()))
    contributions = tuple(
        value for value, _ in _project_contributions(state, state.bundle.selections)
    )
    return findings, evidence, contributions


async def build_evidence_map(
    *,
    objective: Any,
    analysis: Any,
    profiles: tuple[Any, ...] = (),
) -> dict[str, Any]:
    """Build the existing graph response without reading legacy facts."""

    version = objective.published_analysis_version
    if version is None or analysis.analysis_version != version:
        raise ValueError("analysis is not the Objective published analysis version")
    state = await _state(objective.collection_id, objective.objective_id, version)
    findings = tuple(
        _project_finding(finding, state) for finding in state.bundle.findings
    )
    evidence = tuple(item for _, item in sorted(state.evidence_by_id.items()))
    contributions = tuple(
        record for _, record in _project_contributions(state, state.bundle.selections)
    )
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
    profiles_by_document_id = {
        item.document_id: item for item in profiles
    }
    contribution_by_document = {
        str(item.get("document_id") or ""): item for item in contributions
    }
    document_ids = _ordered_unique(
        [
            *(str(item.get("document_id") or "") for item in contributions),
            *(item.document_id for item in evidence),
        ]
    )
    for document_id in document_ids:
        contribution = contribution_by_document.get(document_id)
        profile = profiles_by_document_id.get(document_id)
        title = profile.title if profile is not None else None
        document_node_id = f"document:{document_id}"
        nodes.append(
            {
                "id": document_node_id,
                "type": "document",
                "label": str(title or document_id),
                "document_id": document_id,
                "analysis_status": (
                    contribution.get("analysis_status")
                    if contribution is not None
                    else "analyzed"
                ),
                "evidence_disposition": (
                    contribution.get("evidence_disposition")
                    if contribution is not None
                    else None
                ),
                "evidence_disposition_reason": (
                    contribution.get("evidence_disposition_reason")
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

    evidence_by_id = {item.evidence_id: item for item in evidence}
    linked_evidence_ids: set[str] = set()
    source_nodes: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_document_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in evidence:
        evidence_id = item.evidence_id
        evidence_node_id = f"evidence:{evidence_id}"
        result = item.reported_result
        status, reason = experiment_evidence_disposition(item)
        nodes.append(
            {
                "id": evidence_node_id,
                "type": "evidence",
                "label": str(
                    result.result_text
                    if result is not None
                    else item.source_excerpt or evidence_id
                ),
                "evidence_id": evidence_id,
                "document_id": item.document_id,
                "evidence_role": item.evidence_role,
                "attribution_scope": item.attribution_scope,
                "evidence_status": status,
                "evidence_status_reason": reason,
                "confidence": item.confidence,
                "direction": (
                    result.direction
                    if result is not None
                    else None
                ),
                "outcome": (
                    result.outcome
                    if result is not None
                    else None
                ),
                "source_excerpt": item.source_excerpt,
            }
        )
        source_key = (
            item.document_id,
            item.source_kind,
            item.source_ref,
        )
        source_id = sha1("\x1f".join(source_key).encode("utf-8")).hexdigest()[:20]
        source_node = source_nodes.setdefault(
            source_key,
            {
                "id": f"source:{source_id}",
                "type": "source",
                "label": f"{source_key[1].replace('_', ' ').title()} · {source_key[2]}",
                "document_id": source_key[0],
                "source_kind": source_key[1],
                "source_ref": source_key[2],
                "source_excerpt": item.source_excerpt,
                "page_numbers": list(item.page_numbers),
                "evidence_ids": [],
            },
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
                target=f"document:{source_key[0]}",
                relation="reported_in",
            ),
        )
    nodes.extend(source_nodes.values())
    nodes.extend(
        {
            "id": f"finding:{item.finding_id}",
            "type": "finding",
            "label": item.statement or item.finding_id,
            "finding_id": item.finding_id,
            "statement": item.statement,
            "factors": list(item.factors),
            "outcome": item.outcome,
            "direction": item.direction,
            "assertion_strength": item.assertion_strength,
            "synthesis_status": item.synthesis_status,
            "certainty": item.certainty,
            "limitations": list(item.limitations),
        }
        for item in findings
    )
    for item in findings:
        finding_node_id = f"finding:{item.finding_id}"
        edges.append(
            _edge(
                source=objective_node_id,
                target=finding_node_id,
                relation="has_finding",
            )
        )
        contributions_for_finding = item.paper_contributions
        for relation, evidence_groups in (
            ("supports", (paper.supporting_evidence_ids for paper in contributions_for_finding)),
            ("contradicts", (paper.contradicting_evidence_ids for paper in contributions_for_finding)),
            ("contextualizes", (paper.context_evidence_ids for paper in contributions_for_finding)),
        ):
            for evidence_ids in evidence_groups:
                for evidence_id in evidence_ids:
                    if evidence_id not in evidence_by_id:
                        raise ValueError(
                            f"finding references missing evidence: {evidence_id}"
                        )
                    linked_evidence_ids.add(evidence_id)
                    edges.append(
                        _edge(
                            source=finding_node_id,
                            target=f"evidence:{evidence_id}",
                            relation=relation,
                            condition_boundary=False,
                        )
                    )
    direct_document_ids = {
        evidence_by_id[evidence_id].document_id
        for item in findings
        for contribution in item.paper_contributions
        for evidence_id in contribution.supporting_evidence_ids
        if evidence_id in evidence_by_id
    }
    status_counts: dict[str, int] = {}
    for item in evidence:
        status = experiment_evidence_disposition(item)[0]
        status_counts[status] = status_counts.get(status, 0) + 1
    nodes.extend(source_document_edges.values())
    failed_document_count = sum(
        item.get("analysis_status") == "failed" for item in contributions
    )
    return {
        "collection_id": objective.collection_id,
        "objective_id": objective.objective_id,
        "analysis_version": version,
        "projection_version": "objective-evidence-map.v1",
        "complete": failed_document_count == 0,
        "nodes": nodes,
        "edges": edges,
        "coverage": {
            "total_document_count": len(contributions),
            "analyzed_document_count": sum(
                item.get("analysis_status") == "analyzed" for item in contributions
            ),
            "excluded_document_count": sum(
                item.get("analysis_status") == "excluded" for item in contributions
            ),
            "failed_document_count": failed_document_count,
            "direct_evidence_document_count": len(direct_document_ids),
            "finding_count": len(findings),
            "evidence_count": len(evidence),
            "source_count": len(source_nodes),
            "unlinked_evidence_count": len(set(evidence_by_id) - linked_evidence_ids),
            "evidence_status_counts": dict(sorted(status_counts.items())),
        },
    }


async def _state(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> _ProjectionState:
    bundle = await experiment_query_service.read_analysis_bundle(
        collection_id,
        objective_id,
        analysis_version,
    )
    revisions_by_identity = {
        (item.revision.experiment_id, item.revision.experiment_version): item.revision
        for item in bundle.revisions
    }
    selections_by_id = {item.selection_id: item for item in bundle.selections}
    evidence_by_id: dict[str, ObjectiveEvidence] = {}
    evidence_ids_by_selection: dict[str, tuple[str, ...]] = {}
    for selection in bundle.selections:
        revision = revisions_by_identity.get(
            (selection.experiment_id, selection.experiment_version)
        )
        if revision is None:
            raise ValueError(
                "selection references a missing experiment revision: "
                f"{selection.experiment_id}/{selection.experiment_version}"
            )
        evidence_ids: list[str] = []
        for key in selection.measurement_keys:
            measurement = _by_key(revision.measurements, "measurement_key", key)
            if measurement is None:
                raise ValueError(f"selection references missing measurement: {key}")
            value = _measurement_record(
                collection_id,
                objective_id,
                analysis_version,
                selection,
                revision,
                measurement,
            )
            evidence_by_id[value.evidence_id] = value
            evidence_ids.append(value.evidence_id)
        for key in selection.comparison_keys:
            comparison = _by_key(revision.comparisons, "comparison_key", key)
            if comparison is None:
                raise ValueError(f"selection references missing comparison: {key}")
            value = _comparison_record(
                collection_id,
                objective_id,
                analysis_version,
                selection,
                revision,
                comparison,
            )
            evidence_by_id[value.evidence_id] = value
            evidence_ids.append(value.evidence_id)
        evidence_ids_by_selection[selection.selection_id] = tuple(
            dict.fromkeys(evidence_ids)
        )
    return _ProjectionState(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        bundle=bundle,
        revisions_by_identity=revisions_by_identity,
        selections_by_id=selections_by_id,
        evidence_by_id=evidence_by_id,
        evidence_ids_by_selection=evidence_ids_by_selection,
        contributions_by_document=await _load_contributions(
            collection_id,
            objective_id,
            analysis_version,
        ),
    )


async def _load_contributions(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> dict[str, PaperContribution]:
    records = await ObjectiveRepo.list_contributions(
        collection_id, objective_id, analysis_version
    )
    return {item.document_id: item for item in records}


def _project_finding(
    finding: Finding, state: _ProjectionState
) -> Finding:
    selected = []
    for selection_id in finding.selection_ids:
        selection = state.selections_by_id.get(selection_id)
        if selection is None:
            raise ValueError(f"finding references unknown selection: {selection_id}")
        revision = state.revisions_by_identity.get(
            (selection.experiment_id, selection.experiment_version)
        )
        if revision is None:
            raise ValueError(f"finding selection has no revision: {selection_id}")
        selected.append(selection)
    contributions = _project_contributions(state, selected, include_links=True)
    if not contributions:
        raise ValueError(f"finding has no projectable selections: {finding.finding_id}")
    papers = tuple(
        FindingPaperContribution(
            document_id=value.document_id,
            analysis_status=value.analysis_status,
            supporting_evidence_ids=tuple(view["supporting_evidence_ids"]),
            contradicting_evidence_ids=tuple(view["contradicting_evidence_ids"]),
            context_evidence_ids=tuple(view["context_evidence_ids"]),
            condition_boundary_evidence_ids=tuple(
                view["condition_boundary_evidence_ids"]
            ),
        )
        for value, view in contributions
    )
    projected = replace(
        finding,
        synthesis_status=(
            "insufficient_confirmation"
            if finding.synthesis_status == "single_study" else finding.synthesis_status
        ),
        selection_ids=(),
        comparison_group_ids=(),
        paper_contributions=papers,
    )
    return projected


def _measurement_record(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    selection: Any,
    revision: PaperExperimentRevision,
    measurement: ExperimentMeasurementResult,
) -> ObjectiveEvidence:
    source_refs = _source_refs(
        measurement.source_refs,
        measurement.binding_source_refs,
        revision.source_refs,
    )
    variant = _by_key(revision.variants, "variant_key", measurement.variant_key)
    test = _by_key(revision.test_conditions, "test_key", measurement.test_key)
    value = _scalar(measurement.value)
    result_text = measurement.result_text or (
        f"{measurement.outcome}: {value} {measurement.unit or ''}".strip()
    )
    evidence_id = _evidence_id(
        selection.selection_id, "measurement", measurement.measurement_key
    )
    status = (
        "descriptive"
        if measurement.binding_status in {"direct", "derived"}
        else "needs_context"
    )
    evidence = ObjectiveEvidence(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        evidence_id=evidence_id,
        document_id=revision.document_id,
        source_kind=source_refs[0].source_kind,
        source_ref=source_refs[0].source_ref,
        source_excerpt=source_refs[0].quote,
        page_numbers=(),
        related_source_refs=tuple(
            {
                "document_id": item.document_id,
                "source_fingerprint": item.source_fingerprint,
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
                "quote": item.quote,
            }
            for item in source_refs[1:]
        ),
        related_source_refs_explicit=True,
        evidence_role="direct_result",
        selection_status="extracted",
        selection_reason="; ".join(selection.reasons) or None,
        changed_variables=(),
        comparison=None,
        reported_result=ScientificResult(
            outcome=measurement.outcome,
            value=value,
            unit=measurement.unit,
            direction="unknown",
            result_text=result_text,
            result_kind=measurement.result_kind,
        ),
        attribution_scope="descriptive_only",
        scientific_context=_scientific_context(variant, test),
        resolution_status="resolved" if status == "descriptive" else "partial",
        failure_reason=None,
        confidence=_confidence(measurement.binding_status),
    )
    return evidence


def _comparison_record(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    selection: Any,
    revision: PaperExperimentRevision,
    comparison: ExperimentComparison,
) -> ObjectiveEvidence:
    source_refs = _source_refs(
        comparison.source_refs,
        comparison.binding_source_refs,
        revision.source_refs,
    )
    baseline = _by_key(
        revision.measurements,
        "measurement_key",
        comparison.baseline_measurement_keys[0],
    )
    target = _by_key(
        revision.measurements,
        "measurement_key",
        comparison.target_measurement_keys[0],
    )
    if baseline is None or target is None:
        raise ValueError(
            f"comparison has missing measurement: {comparison.comparison_key}"
        )
    baseline_value = _scalar(baseline.value)
    target_value = _scalar(target.value)
    comparable = comparison.status == "ready"
    attribution = comparison.attribution_scope
    if attribution == "undetermined":
        attribution = "not_attributable"
    evidence_id = _evidence_id(
        selection.selection_id, "comparison", comparison.comparison_key
    )
    result_text = comparison.reported_statement or (
        f"{baseline.result_text or baseline_value} -> "
        f"{target.result_text or target_value}"
    )
    evidence = ObjectiveEvidence(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        evidence_id=evidence_id,
        document_id=revision.document_id,
        source_kind=source_refs[0].source_kind,
        source_ref=source_refs[0].source_ref,
        source_excerpt=source_refs[0].quote,
        page_numbers=(),
        related_source_refs=tuple(
            {
                "document_id": item.document_id,
                "source_fingerprint": item.source_fingerprint,
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
                "quote": item.quote,
            }
            for item in source_refs[1:]
        ),
        related_source_refs_explicit=True,
        evidence_role="direct_result",
        selection_status="extracted",
        selection_reason="; ".join(selection.reasons) or None,
        changed_variables=comparison.changed_variables,
        comparison=ScientificComparison(
            baseline_label=_variant_label(revision, comparison.baseline_variant_key),
            target_label=_variant_label(revision, comparison.target_variant_key),
            axis_names=tuple(item.name for item in comparison.changed_variables),
            comparable=comparable,
            incomparability_reasons=comparison.reasons if not comparable else (),
        ),
        reported_result=ScientificResult(
            outcome=comparison.outcome,
            value=target_value,
            unit=target.unit or baseline.unit,
            direction=comparison.direction,
            result_text=result_text,
            result_kind="observed",
            baseline_value=baseline_value,
            target_value=target_value,
        ),
        attribution_scope=attribution,
        scientific_context=_scientific_context(
            _by_key(revision.variants, "variant_key", comparison.target_variant_key),
            _by_key(revision.test_conditions, "test_key", target.test_key),
        ),
        resolution_status="resolved" if comparable else "partial",
        failure_reason=None,
        confidence=_confidence(comparison.relation_status),
    )
    return evidence


def _by_key(items: Any, field_name: str, key: str | None) -> Any | None:
    if not key:
        return None
    return next(
        (item for item in items if getattr(item, field_name, None) == key), None
    )


_CONTRIBUTION_LINK_FIELDS = (
    "supporting_evidence_ids",
    "contradicting_evidence_ids",
    "context_evidence_ids",
    "condition_boundary_evidence_ids",
)



def _new_experiment_contribution(
    *,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    document_id: str,
    scope_description: str,
    outcome: str,
) -> dict[str, Any]:
    return {
        "collection_id": collection_id,
        "objective_id": objective_id,
        "analysis_version": analysis_version,
        "document_id": document_id,
        "analysis_status": "analyzed",
        "relevance": "high",
        "paper_role": "primary_experiment",
        "contribution_summary": scope_description,
        "material_match": [],
        "changed_variables": [],
        "measured_property_scope": [outcome],
        "test_environment_scope": [],
        "exclusion_reason": None,
        "warnings": [],
        "confidence": 1.0,
        "evidence_disposition": "no_comparable_evidence",
        "routed_source_count": 0,
        "extracted_source_count": 0,
        "comparable_evidence_count": 0,
        "failed_source_count": 0,
        "uninspected_source_count": 0,
        "evidence_disposition_reason": None,
        "evidence_status_counts": {},
        "inspected_source_refs": [],
        **{field_name: [] for field_name in _CONTRIBUTION_LINK_FIELDS},
    }


def _reset_experiment_accounting(record: dict[str, Any]) -> None:
    """Reset counters before overlaying the new experiment evidence IDs."""

    record["analysis_status"] = "analyzed"
    record["relevance"] = "high"
    record["paper_role"] = "primary_experiment"
    record["exclusion_reason"] = None
    record["evidence_disposition"] = "no_comparable_evidence"
    record["routed_source_count"] = 0
    record["extracted_source_count"] = 0
    record["comparable_evidence_count"] = 0
    record["failed_source_count"] = 0
    record["uninspected_source_count"] = 0
    record["evidence_disposition_reason"] = None
    record["evidence_status_counts"] = {}
    for field_name in _CONTRIBUTION_LINK_FIELDS:
        record[field_name] = []


def _source_refs(*groups: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    seen: set[tuple[str, str, str]] = set()
    result: list[SourceReference] = []
    for group in groups:
        for item in group:
            key = (item.document_id, item.source_kind, item.source_ref)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    if not result:
        raise ValueError(
            "experiment record has no source reference for compatibility projection"
        )
    return tuple(result)


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _variant_label(revision: PaperExperimentRevision, key: str) -> str:
    variant = _by_key(revision.variants, "variant_key", key)
    return variant.variant_label if variant is not None else key


def _evidence_id(selection_id: str, kind: str, key: str) -> str:
    digest = sha1(f"{selection_id}\x1f{kind}\x1f{key}".encode("utf-8")).hexdigest()[:24]
    return f"experiment-evidence-{digest}"


def _confidence(status: str) -> float:
    return {
        "direct": 1.0,
        "derived": 0.85,
        "bound": 1.0,
        "uncertain": 0.5,
        "conflict": 0.25,
    }.get(status, 0.5)


def experiment_evidence_disposition(evidence: ObjectiveEvidence) -> tuple[str, str]:
    """Render the established experiment read disposition from scientific facts."""
    if evidence.comparison is not None:
        if evidence.comparison.comparable:
            return "comparable", "The paper reports a source-grounded comparison."
        return (
            "non_comparable",
            "; ".join(evidence.comparison.incomparability_reasons)
            or "The paper comparison lacks sufficient context.",
        )
    if evidence.resolution_status == "resolved":
        return (
            "descriptive",
            "The selected experiment reports this outcome without a paper-internal comparison.",
        )
    return "needs_context", "The selected measurement has incomplete binding context."


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


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


__all__ = [
    "list_analysis_findings",
    "read_analysis_finding",
    "list_analysis_evidence",
    "list_analysis_contributions",
    "read_analysis_records",
    "experiment_evidence_disposition",
    "build_evidence_map",
]


def _scientific_context(
    variant: ExperimentalVariant | None, test: ExperimentTestCondition | None
) -> ScientificContext:
    return ScientificContext(
        material=variant.subject_attributes if variant else (),
        sample=variant.state if variant else (),
        process=variant.intervention_attributes if variant else (),
        test=test.parameters if test else (),
    )
