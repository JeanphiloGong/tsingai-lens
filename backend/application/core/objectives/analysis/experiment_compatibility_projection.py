"""Project experiment-backed records into the existing Objective read shape.

The public Objective/Finding/Evidence endpoints predate ``PaperExperiment``.
This module is a read-only boundary: it derives the old response vocabulary
from immutable experiment revisions and explicit selections without writing a
second scientific-fact ledger.  The caller can therefore switch storage and
query ownership while keeping the HTTP contract stable.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Mapping

from application.repositories.comparison_group_repository import ComparisonGroupRepository
from application.repositories.experiment_finding_repository import (
    ExperimentFindingRepository,
)
from application.repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from application.repositories.objective_repository import ObjectiveRepository
from application.repositories.paper_experiment_repository import (
    PaperExperimentRepository,
    StoredPaperExperimentRevision,
)
from domain.core.paper_experiment import (
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    ExperimentalVariant,
    PaperExperimentRevision,
    SourceReference,
)
from domain.core.scientific_fact import ScientificAttribute, ScientificVariable

from .experiment_query_service import ExperimentAnalysisBundle, ExperimentQueryService


@dataclass(frozen=True)
class _ProjectionState:
    collection_id: str
    objective_id: str
    analysis_version: int
    bundle: ExperimentAnalysisBundle
    revisions_by_identity: Mapping[tuple[str, int], PaperExperimentRevision]
    selections_by_id: Mapping[str, Any]
    evidence_by_id: Mapping[str, dict[str, Any]]
    evidence_ids_by_selection: Mapping[str, tuple[str, ...]]
    contributions_by_document: Mapping[str, dict[str, Any]]


class ExperimentCompatibilityProjection:
    """Expose stable Finding/Evidence records from the new experiment graph."""

    def __init__(
        self,
        *,
        paper_experiment_repository: PaperExperimentRepository,
        selection_repository: ObjectiveExperimentSelectionRepository,
        group_repository: ComparisonGroupRepository,
        finding_repository: ExperimentFindingRepository,
        objective_repository: ObjectiveRepository | None = None,
    ) -> None:
        self._query = ExperimentQueryService(
            paper_experiment_repository=paper_experiment_repository,
            selection_repository=selection_repository,
            group_repository=group_repository,
            finding_repository=finding_repository,
        )
        self._objective_repository = objective_repository

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        state = await self._state(collection_id, objective_id, analysis_version)
        records = tuple(
            self._finding_record(finding, state)
            for finding in state.bundle.findings
        )
        records = tuple(
            sorted(
                records,
                key=lambda item: (
                    int(item.get("display_rank") or 0),
                    str(item.get("finding_id") or ""),
                ),
            )
        )
        start = max(0, offset)
        page_size = max(1, min(limit, 200))
        return records[start : start + page_size], len(records)

    async def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> dict[str, Any] | None:
        state = await self._state(collection_id, objective_id, analysis_version)
        finding = next(
            (
                item
                for item in state.bundle.findings
                if item.finding_id == finding_id
            ),
            None,
        )
        return self._finding_record(finding, state) if finding is not None else None

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        state = await self._state(collection_id, objective_id, analysis_version)
        allowed: set[str] | None = None
        if finding_id is not None:
            finding = next(
                (
                    item
                    for item in state.bundle.findings
                    if item.finding_id == finding_id
                ),
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

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[dict[str, Any], ...]:
        state = await self._state(collection_id, objective_id, analysis_version)
        return self._project_contributions(state, state.bundle.selections)

    def _project_contributions(
        self,
        state: _ProjectionState,
        selections: Any,
        *,
        include_links: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        """Keep coverage metadata while replacing legacy Evidence ids.

        PaperContribution describes which papers were inspected, including
        excluded or failed papers. It is not a second scientific-fact store.
        The experiment graph supplies the current evidence ids for selected
        records; the coverage rows remain available for the legacy response.
        """
        contribution_by_document = {
            document_id: _reset_contribution_links(record)
            for document_id, record in state.contributions_by_document.items()
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
            contribution["contribution_summary"] = contribution.get(
                "contribution_summary"
            ) or revision.scope_description
            for evidence_id in evidence_ids:
                if evidence_id not in contribution["supporting_evidence_ids"]:
                    contribution["supporting_evidence_ids"].append(evidence_id)
                evidence = state.evidence_by_id[evidence_id]
                contribution["routed_source_count"] += 1
                contribution["extracted_source_count"] += 1
                status = str(evidence.get("evidence_status") or "descriptive")
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
            contribution_by_document[key]
            for key in sorted(contribution_by_document)
        )
        if include_links:
            return records
        return tuple(
            {
                key: value
                for key, value in record.items()
                if key not in _CONTRIBUTION_LINK_FIELDS
            }
            for record in records
        )

    async def read_analysis_records(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        """Return all projected findings and evidence for map/read callers."""

        state = await self._state(collection_id, objective_id, analysis_version)
        findings = tuple(
            self._finding_record(finding, state)
            for finding in state.bundle.findings
        )
        evidence = tuple(
            item for _, item in sorted(state.evidence_by_id.items())
        )
        return findings, evidence

    async def build_evidence_map(
        self,
        *,
        objective: Any,
        analysis: Any,
        profiles: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        """Build the existing graph response without reading legacy facts."""

        version = objective.published_analysis_version
        if version is None or analysis.analysis_version != version:
            raise ValueError("analysis is not the Objective published analysis version")
        findings, evidence = await self.read_analysis_records(
            objective.collection_id,
            objective.objective_id,
            version,
        )
        contributions = await self.list_contributions(
            objective.collection_id,
            objective.objective_id,
            version,
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
            str(_value(item, "document_id") or ""): item for item in profiles
        }
        contribution_by_document = {
            str(item.get("document_id") or ""): item for item in contributions
        }
        document_ids = _ordered_unique(
            [
                *(str(item.get("document_id") or "") for item in contributions),
                *(str(item.get("document_id") or "") for item in evidence),
            ]
        )
        for document_id in document_ids:
            contribution = contribution_by_document.get(document_id)
            profile = profiles_by_document_id.get(document_id)
            title = _value(profile, "title") if profile is not None else None
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

        evidence_by_id = {str(item.get("evidence_id")): item for item in evidence}
        linked_evidence_ids: set[str] = set()
        source_nodes: dict[tuple[str, str, str], dict[str, Any]] = {}
        source_document_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in evidence:
            evidence_id = str(item.get("evidence_id") or "")
            evidence_node_id = f"evidence:{evidence_id}"
            result = item.get("reported_result")
            nodes.append(
                {
                    "id": evidence_node_id,
                    "type": "evidence",
                    "label": str(
                        (result or {}).get("result_text")
                        if isinstance(result, Mapping)
                        else item.get("source_excerpt") or evidence_id
                    ),
                    "evidence_id": evidence_id,
                    "document_id": item.get("document_id"),
                    "evidence_role": item.get("evidence_role"),
                    "attribution_scope": item.get("attribution_scope"),
                    "evidence_status": item.get("evidence_status"),
                    "evidence_status_reason": item.get("evidence_status_reason"),
                    "confidence": item.get("confidence"),
                    "direction": (result or {}).get("direction") if isinstance(result, Mapping) else None,
                    "outcome": (result or {}).get("outcome") if isinstance(result, Mapping) else None,
                    "source_excerpt": item.get("source_excerpt") or "",
                }
            )
            source_key = (
                str(item.get("document_id") or ""),
                str(item.get("source_kind") or ""),
                str(item.get("source_ref") or ""),
            )
            source_id = sha1(
                "\x1f".join(source_key).encode("utf-8")
            ).hexdigest()[:20]
            source_node = source_nodes.setdefault(
                source_key,
                {
                    "id": f"source:{source_id}",
                    "type": "source",
                    "label": f"{source_key[1].replace('_', ' ').title()} · {source_key[2]}",
                    "document_id": source_key[0],
                    "source_kind": source_key[1],
                    "source_ref": source_key[2],
                    "source_excerpt": item.get("source_excerpt") or "",
                    "page_numbers": list(item.get("page_numbers") or ()),
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
                "id": f"finding:{item.get('finding_id')}",
                "type": "finding",
                "label": item.get("statement") or item.get("finding_id"),
                "finding_id": item.get("finding_id"),
                "statement": item.get("statement"),
                "factors": list(item.get("factors") or ()),
                "outcome": item.get("outcome"),
                "direction": item.get("direction"),
                "assertion_strength": item.get("assertion_strength"),
                "synthesis_status": item.get("synthesis_status"),
                "certainty": item.get("certainty"),
                "limitations": list(item.get("limitations") or ()),
            }
            for item in findings
        )
        for item in findings:
            finding_node_id = f"finding:{item.get('finding_id')}"
            edges.append(
                _edge(
                    source=objective_node_id,
                    target=finding_node_id,
                    relation="has_finding",
                )
            )
            contributions_for_finding = item.get("paper_contributions") or ()
            for relation, key in (
                ("supports", "supporting_evidence_ids"),
                ("contradicts", "contradicting_evidence_ids"),
                ("contextualizes", "context_evidence_ids"),
            ):
                for contribution in contributions_for_finding:
                    for evidence_id in contribution.get(key) or ():
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
            str(evidence_by_id[evidence_id].get("document_id") or "")
            for item in findings
            for contribution in item.get("paper_contributions") or ()
            for evidence_id in contribution.get("supporting_evidence_ids") or ()
            if evidence_id in evidence_by_id
        }
        status_counts: dict[str, int] = {}
        for item in evidence:
            status = str(item.get("evidence_status") or "unknown")
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
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> _ProjectionState:
        bundle = await self._query.read_analysis_bundle(
            collection_id,
            objective_id,
            analysis_version,
        )
        revisions_by_identity = {
            (item.revision.experiment_id, item.revision.experiment_version): item.revision
            for item in bundle.revisions
        }
        selections_by_id = {item.selection_id: item for item in bundle.selections}
        evidence_by_id: dict[str, dict[str, Any]] = {}
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
                record = self._measurement_record(
                    collection_id,
                    objective_id,
                    analysis_version,
                    selection,
                    revision,
                    measurement,
                )
                evidence_by_id[record["evidence_id"]] = record
                evidence_ids.append(record["evidence_id"])
            for key in selection.comparison_keys:
                comparison = _by_key(revision.comparisons, "comparison_key", key)
                if comparison is None:
                    raise ValueError(f"selection references missing comparison: {key}")
                record = self._comparison_record(
                    collection_id,
                    objective_id,
                    analysis_version,
                    selection,
                    revision,
                    comparison,
                )
                evidence_by_id[record["evidence_id"]] = record
                evidence_ids.append(record["evidence_id"])
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
            contributions_by_document=await self._load_contributions(
                collection_id,
                objective_id,
                analysis_version,
            ),
        )

    async def _load_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> dict[str, dict[str, Any]]:
        if self._objective_repository is None:
            return {}
        records = await self._objective_repository.list_contributions(
            collection_id,
            objective_id,
            analysis_version,
        )
        result: dict[str, dict[str, Any]] = {}
        for item in records:
            record = item.to_record() if hasattr(item, "to_record") else dict(item)
            document_id = str(record.get("document_id") or "")
            if document_id:
                result[document_id] = record
        return result

    def _finding_record(self, finding: Any, state: _ProjectionState) -> dict[str, Any]:
        record = finding.to_record()
        # The legacy response contract predates the explicit single-study
        # state. Preserve its meaning through the existing "insufficient
        # confirmation" bucket rather than exposing a new enum to clients.
        if record.get("synthesis_status") == "single_study":
            record["synthesis_status"] = "insufficient_confirmation"
        # Selection/group identities are internal provenance for the new graph;
        # the established Finding response never exposed them.
        record.pop("selection_ids", None)
        record.pop("comparison_group_ids", None)
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
        contributions = [
            _finding_contribution_view(item)
            for item in self._project_contributions(state, selected, include_links=True)
        ]
        if not contributions:
            raise ValueError(f"finding has no projectable selections: {finding.finding_id}")
        record["paper_contributions"] = contributions
        return record

    @classmethod
    def _measurement_record(
        cls,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        selection: Any,
        revision: PaperExperimentRevision,
        measurement: ExperimentMeasurementResult,
    ) -> dict[str, Any]:
        source_refs = _source_refs(
            measurement.source_refs,
            measurement.binding_source_refs,
            revision.source_refs,
        )
        variant = _by_key(revision.variants, "variant_key", measurement.variant_key)
        test = _by_key(revision.test_conditions, "test_key", measurement.test_key)
        context = _context_record(variant, test)
        value = _scalar(measurement.value)
        result_text = measurement.result_text or (
            f"{measurement.outcome}: {value} {measurement.unit or ''}".strip()
        )
        evidence_id = _evidence_id(selection.selection_id, "measurement", measurement.measurement_key)
        status = "descriptive" if measurement.binding_status in {"direct", "derived"} else "needs_context"
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": analysis_version,
            "evidence_id": evidence_id,
            "document_id": revision.document_id,
            "source_kind": source_refs[0].source_kind,
            "source_ref": source_refs[0].source_ref,
            "source_excerpt": source_refs[0].quote,
            "page_numbers": [],
            "related_source_refs": [item.to_record() for item in source_refs[1:]],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "selection_reason": "; ".join(selection.reasons) or None,
            "evidence_status": status,
            "evidence_status_reason": (
                "The selected experiment reports this outcome without a paper-internal comparison."
                if status == "descriptive"
                else "The selected measurement has incomplete binding context."
            ),
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": measurement.outcome,
                "result_kind": measurement.result_kind,
                "value": value,
                "baseline_value": None,
                "target_value": None,
                "unit": measurement.unit,
                "direction": "unknown",
                "result_text": result_text,
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": context,
            "resolution_status": "resolved" if status == "descriptive" else "partial",
            "failure_reason": None,
            "confidence": _confidence(measurement.binding_status),
            "supports_finding": True,
            "eligible_for_finding_authoring": True,
            "warnings": [],
            "origin": "system_generated",
            "source_analysis_version": None,
            "supersedes_evidence_id": None,
            "superseded_by_evidence_id": None,
            "created_by_user_id": None,
            "created_by_tool_call_id": None,
            "created_at": None,
            "authoring_note": None,
        }

    @classmethod
    def _comparison_record(
        cls,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        selection: Any,
        revision: PaperExperimentRevision,
        comparison: ExperimentComparison,
    ) -> dict[str, Any]:
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
        evidence_id = _evidence_id(selection.selection_id, "comparison", comparison.comparison_key)
        result_text = comparison.reported_statement or (
            f"{baseline.result_text or baseline_value} -> "
            f"{target.result_text or target_value}"
        )
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": analysis_version,
            "evidence_id": evidence_id,
            "document_id": revision.document_id,
            "source_kind": source_refs[0].source_kind,
            "source_ref": source_refs[0].source_ref,
            "source_excerpt": source_refs[0].quote,
            "page_numbers": [],
            "related_source_refs": [item.to_record() for item in source_refs[1:]],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "selection_reason": "; ".join(selection.reasons) or None,
            "evidence_status": (
                "comparable" if comparable else "non_comparable"
            ),
            "evidence_status_reason": (
                "The paper reports a source-grounded comparison."
                if comparable
                else "; ".join(comparison.reasons)
                or "The paper comparison lacks sufficient context."
            ),
            "changed_variables": [item.to_record() for item in comparison.changed_variables],
            "comparison": {
                "baseline_label": _variant_label(revision, comparison.baseline_variant_key),
                "target_label": _variant_label(revision, comparison.target_variant_key),
                "axis_names": [item.name for item in comparison.changed_variables],
                "comparable": comparable,
                "incomparability_reasons": list(comparison.reasons) if not comparable else [],
            },
            "reported_result": {
                "outcome": comparison.outcome,
                "result_kind": "observed",
                "value": target_value,
                "baseline_value": baseline_value,
                "target_value": target_value,
                "unit": target.unit or baseline.unit,
                "direction": comparison.direction,
                "result_text": result_text,
            },
            "attribution_scope": attribution,
            "scientific_context": _context_record(
                _by_key(revision.variants, "variant_key", comparison.target_variant_key),
                _by_key(
                    revision.test_conditions,
                    "test_key",
                    target.test_key,
                ),
            ),
            "resolution_status": "resolved" if comparable else "partial",
            "failure_reason": None,
            "confidence": _confidence(comparison.relation_status),
            "supports_finding": comparable,
            "eligible_for_finding_authoring": comparable,
            "warnings": [],
            "origin": "system_generated",
            "source_analysis_version": None,
            "supersedes_evidence_id": None,
            "superseded_by_evidence_id": None,
            "created_by_user_id": None,
            "created_by_tool_call_id": None,
            "created_at": None,
            "authoring_note": None,
        }


def _by_key(items: Any, field_name: str, key: str | None) -> Any | None:
    if not key:
        return None
    return next((item for item in items if getattr(item, field_name, None) == key), None)


_CONTRIBUTION_LINK_FIELDS = (
    "supporting_evidence_ids",
    "contradicting_evidence_ids",
    "context_evidence_ids",
    "condition_boundary_evidence_ids",
)


def _reset_contribution_links(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy coverage metadata without carrying obsolete Evidence identities."""

    result = deepcopy(dict(record))
    for field_name in _CONTRIBUTION_LINK_FIELDS:
        result[field_name] = []
    return result


def _finding_contribution_view(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return exactly the established Finding contribution contract."""

    return {
        "document_id": record.get("document_id"),
        "analysis_status": record.get("analysis_status") or "analyzed",
        **{
            field_name: list(record.get(field_name) or ())
            for field_name in _CONTRIBUTION_LINK_FIELDS
        },
    }


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
        raise ValueError("experiment record has no source reference for compatibility projection")
    return tuple(result)


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _context_record(
    variant: ExperimentalVariant | None,
    test: ExperimentTestCondition | None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "material": [item.to_record() for item in (variant.subject_attributes if variant else ())],
        "sample": [item.to_record() for item in (variant.state if variant else ())],
        "process": [item.to_record() for item in (variant.intervention_attributes if variant else ())],
        "test": [item.to_record() for item in (test.parameters if test else ())],
    }


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


def _value(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)


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


__all__ = ["ExperimentCompatibilityProjection"]
