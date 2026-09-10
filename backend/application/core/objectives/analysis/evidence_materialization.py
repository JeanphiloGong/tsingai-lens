from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
import json
import re
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.analysis.diagnostics import (
    record_analysis_diagnostic,
)
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
    _objective_missing_context_fields,
)
from application.core.objectives.analysis.source_validation import (
    _objective_source_explicitly_links_variable_to_result,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    PaperResearchMap,
    PaperSourceUnitCoverageStatus,
    ResearchObjective,
)
from domain.source import SourceDocumentTree

# Selected Source coverage replaces framing-wide mandatory coverage. Rebuild
# persisted document checkpoints so reruns cannot replay the old disposition.
OBJECTIVE_EVIDENCE_MATERIALIZATION_VERSION = "objective-evidence-materialization.v11"


_CONTRIBUTION_SUMMARY_CHARS = 320
_MATERIAL_SCOPE_DECISION_TRACE_LIMIT = 100
_SOURCE_COVERAGE_REF_LIMIT = 100


def _text(value: Any) -> str:
    return str(value or "").strip()


def _source_backed_contribution_summary(
    evidence_records: tuple[ObjectiveEvidence, ...],
) -> str | None:
    result_texts = tuple(
        dict.fromkeys(
            result_text
            for evidence in evidence_records
            if evidence.selection_status == "extracted"
            if evidence.reported_result is not None
            if (result_text := _text(evidence.reported_result.result_text))
        )
    )
    summary = " ".join(result_texts)
    return summary[:_CONTRIBUTION_SUMMARY_CHARS].rstrip() or None


def materialize_evidence(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    drafts: tuple[ExtractedEvidenceDraft, ...],
    paper_maps: tuple[PaperResearchMap, ...],
    frames: tuple[PaperAnalysisFrame, ...],
    routes: tuple[EvidenceCandidate, ...],
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
    document_trees_by_document_id: Mapping[str, SourceDocumentTree] | None = None,
) -> tuple[tuple[ObjectiveEvidence, ...], tuple[PaperContribution, ...]]:
    inspection_source_refs = _inspection_source_refs_by_document(drafts)
    selected_drafts = _objective_detail_evidence(
        drafts,
        objective_context=objective,
    )
    evidence_records = _analysis_evidence_records(
        collection_id=collection_id,
        analysis=analysis,
        objective=objective,
        drafts=selected_drafts,
        blocks_by_document_id=blocks_by_document_id,
        tables_by_document_id=tables_by_document_id,
        figures_by_document_id=figures_by_document_id,
    )
    _record_material_scope_exclusions(
        collection_id=collection_id,
        analysis=analysis,
        objective=objective,
        evidence_records=evidence_records,
    )
    contributions = _analysis_contributions(
        collection_id=collection_id,
        analysis=analysis,
        objective=objective,
        paper_maps=paper_maps,
        frames=frames,
        routes=routes,
        evidence_records=evidence_records,
        inspection_source_refs=inspection_source_refs,
        document_trees_by_document_id=document_trees_by_document_id or {},
    )
    # Framing owns the complete candidate Source partition.  Emit the final
    # ledger only when that partition is available so older/unit-only callers
    # remain readable while real analyses get one post-binding accounting
    # record per paper.
    if any(frame.source_dispositions for frame in frames):
        _record_source_coverage_ledger(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            frames=frames,
            routes=routes,
            evidence_records=evidence_records,
            inspection_source_refs=inspection_source_refs,
            document_trees_by_document_id=document_trees_by_document_id or {},
            emit_parity_snapshot=True,
        )
    target_axes = property_matching.objective_outcomes(objective)
    record_analysis_diagnostic(
        {
            "trace_type": "objective_evidence_materialization",
            "collection_id": collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": analysis.analysis_version,
            "draft_count": len(drafts),
            "failed_draft_count": sum(
                draft.selection_status == "failed" for draft in drafts
            ),
            "target_outcome_match_count": sum(
                draft.selection_status != "failed"
                and bool(target_axes)
                and _objective_evidence_matches_target_property(
                    draft,
                    target_axes=target_axes,
                )
                for draft in drafts
            ),
            "selected_draft_count": len(selected_drafts),
            "evidence_record_count": len(evidence_records),
            "paper_disposition_counts": dict(
                sorted(
                    Counter(
                        contribution.evidence_disposition or "unclassified"
                        for contribution in contributions
                    ).items()
                )
            ),
        }
    )
    return evidence_records, contributions


def _inspection_source_refs_by_document(
    drafts: tuple[ExtractedEvidenceDraft, ...],
) -> dict[str, set[tuple[str, str]]]:
    """Return source locators for reads that yielded no scientific fact.

    These transient rejected markers are deliberately excluded from durable
    Evidence, but the coverage ledger still needs to distinguish an inspected
    Source with no fact from a Source that was never read.
    """

    inspected: dict[str, set[tuple[str, str]]] = {}
    for draft in drafts:
        if (
            draft.selection_status != "rejected"
            or draft.evidence_role != "irrelevant"
            or draft.reported_result is not None
            or draft.changed_variables
            or draft.comparison is not None
            or draft.scientific_context.has_content
            or not draft.source_ref
        ):
            continue
        inspected.setdefault(draft.document_id, set()).add(
            _source_identity(draft.source_kind, draft.source_ref)
        )
    return inspected


def _source_identity(source_kind: Any, source_ref: Any) -> tuple[str, str]:
    normalized_kind = _text(source_kind)
    if normalized_kind in {"block", "section"}:
        normalized_kind = "text_window"
    normalized_ref = _text(source_ref)
    # Framing may identify a tree node while extraction/materialization uses
    # the stable artifact reference owned by that node. Treat the project's
    # deterministic node id as an alias, never as a second Source.
    if normalized_ref.startswith("node_") and "_block_" in normalized_ref:
        normalized_ref = normalized_ref.split("_block_", 1)[1]
    return normalized_kind, normalized_ref


def _source_identity_records(
    values: set[tuple[str, str]],
) -> list[dict[str, str]]:
    return [
        {"source_kind": source_kind, "source_ref": source_ref}
        for source_kind, source_ref in sorted(values)[:_SOURCE_COVERAGE_REF_LIMIT]
    ]


def _researcher_decision_packet_audit(
    evidence_records: tuple[ObjectiveEvidence, ...],
) -> dict[str, Any]:
    """Bind the exact downstream Evidence packet without logging paper text."""

    packet_records = [evidence.to_record() for evidence in evidence_records]
    encoded_packet = json.dumps(
        packet_records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    ordered_source_refs: list[dict[str, Any]] = []
    seen_locators: set[str] = set()
    locator_fields = (
        "page",
        "row_index",
        "col_index",
        "start_row",
        "end_row",
        "start_col",
        "end_col",
        "cell_id",
    )

    def add_locator(locator: Mapping[str, Any]) -> None:
        source_kind, source_ref = _source_identity(
            locator.get("source_kind"),
            locator.get("source_ref"),
        )
        if not source_ref:
            return
        identity = {
            "source_kind": source_kind,
            "source_ref": source_ref,
            **{
                field: locator[field]
                for field in locator_fields
                if locator.get(field) not in (None, "")
            },
        }
        key = json.dumps(
            _identity_value(identity),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        if key in seen_locators:
            return
        seen_locators.add(key)
        ordered_source_refs.append(identity)

    for evidence in evidence_records:
        primary_kind, primary_ref = _source_identity(
            evidence.source_kind,
            evidence.source_ref,
        )
        primary_locators = tuple(
            locator
            for locator in evidence.related_source_refs
            if _source_identity(
                locator.get("source_kind"),
                locator.get("source_ref"),
            )
            == (primary_kind, primary_ref)
            and any(
                locator.get(field) not in (None, "")
                for field in locator_fields[1:]
            )
        )
        if primary_locators:
            for locator in primary_locators:
                add_locator(locator)
        else:
            add_locator(
                {
                    "source_kind": primary_kind,
                    "source_ref": primary_ref,
                    "page": evidence.page_numbers[0]
                    if evidence.page_numbers
                    else None,
                }
            )
        for locator in evidence.related_source_refs:
            if locator in primary_locators:
                continue
            add_locator(locator)

    visible_sources = ordered_source_refs[:_SOURCE_COVERAGE_REF_LIMIT]
    visible_evidence_ids = [
        evidence.evidence_id
        for evidence in evidence_records[:_SOURCE_COVERAGE_REF_LIMIT]
    ]
    return {
        "decision_packet_sha256": sha256(encoded_packet).hexdigest(),
        "decision_packet_evidence_count": len(evidence_records),
        "decision_packet_evidence_ids": visible_evidence_ids,
        "decision_packet_evidence_ids_truncated": (
            len(evidence_records) > len(visible_evidence_ids)
        ),
        "decision_packet_source_count": len(ordered_source_refs),
        "decision_packet_source_refs": visible_sources,
        "decision_packet_source_refs_truncated": (
            len(ordered_source_refs) > len(visible_sources)
        ),
    }


def _objective_result_missing_field_families(
    *,
    objective: ResearchObjective,
    evidence: ObjectiveEvidence,
) -> frozenset[str]:
    """Return the shared context families a researcher still needs."""

    return _objective_missing_context_fields(evidence, objective)


def _record_source_coverage_ledger(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    frames: tuple[PaperAnalysisFrame, ...],
    routes: tuple[EvidenceCandidate, ...],
    evidence_records: tuple[ObjectiveEvidence, ...],
    inspection_source_refs: Mapping[str, set[tuple[str, str]]] | None = None,
    document_trees_by_document_id: Mapping[str, SourceDocumentTree] | None = None,
    emit_parity_snapshot: bool = False,
) -> None:
    """Record post-binding Source coverage without treating candidates as facts.

    This is an internal trace used to audit information parity.  A candidate
    becomes inspected only when it has a materialized Evidence record,
    including a failed record.  Scientific closure is computed from grounded
    result records after same-paper reconstruction; routing or lexical matches
    alone cannot make it true.
    """

    evidence_by_document: dict[str, list[ObjectiveEvidence]] = {}
    for evidence in evidence_records:
        evidence_by_document.setdefault(evidence.document_id, []).append(evidence)

    document_trees_by_document_id = document_trees_by_document_id or {}
    inspection_source_refs = inspection_source_refs or {}
    ledger_records: list[dict[str, Any]] = []
    for frame in frames:
        document_evidence = tuple(evidence_by_document.get(frame.document_id, ()))
        frame_source_scope = _frame_source_scope_refs(
            frame=frame,
            document_tree=document_trees_by_document_id.get(frame.document_id),
        )
        framed_sources = set(frame_source_scope)
        relevant_sources = {
            source_ref
            for source_ref, is_relevant in frame_source_scope.items()
            if is_relevant
        }
        routed_sources = {
            _source_identity(route.source_kind, route.source_ref)
            for route in routes
            if route.document_id == frame.document_id
            and route.extractable
            and route.source_ref
        }
        candidate_sources = framed_sources | routed_sources
        relevant_sources |= routed_sources
        inspected_sources = {
            _source_identity(evidence.source_kind, evidence.source_ref)
            for evidence in document_evidence
            if evidence.source_ref
        }
        inspected_sources.update(inspection_source_refs.get(frame.document_id, set()))
        result_evidence = tuple(
            evidence
            for evidence in document_evidence
            if evidence.evidence_role in {"direct_result", "contradictory_result"}
            and evidence.reported_result is not None
            and FindingSynthesisService.evidence_matches_objective_axes(
                objective,
                evidence,
            )
        )
        context_evidence = tuple(
            evidence
            for evidence in document_evidence
            if evidence.reported_result is None
            and evidence.evidence_role not in {"irrelevant"}
            and evidence.selection_status != "failed"
        )
        failed_evidence = tuple(
            evidence
            for evidence in document_evidence
            if evidence.selection_status == "failed"
        )
        missing_by_result = {
            evidence.evidence_id: _objective_result_missing_field_families(
                objective=objective,
                evidence=evidence,
            )
            for evidence in result_evidence
        }
        missing_fields = sorted(
            {field for fields in missing_by_result.values() for field in fields}
        )
        # Framing relevance is a navigation/recall prior. Routes are the
        # mandatory inspection set; Evidence records, including failures, are
        # the inspection ledger.
        uninspected_sources = routed_sources - inspected_sources
        closed_result_count = sum(not fields for fields in missing_by_result.values())
        source_grounded_result_count = sum(
            bool(evidence.source_excerpt and evidence.source_ref)
            and evidence.selection_status == "extracted"
            for evidence in result_evidence
        )
        critical_failed_evidence = tuple(
            evidence
            for evidence in failed_evidence
            if evidence.evidence_role in {"direct_result", "contradictory_result"}
        )
        closure_complete = bool(result_evidence) and not (
            missing_fields or uninspected_sources or critical_failed_evidence
        )
        failed_source_refs = {
            _source_identity(item.source_kind, item.source_ref)
            for item in failed_evidence
        }
        ledger = {
            "trace_type": "objective_source_coverage_ledger",
            "collection_id": collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": analysis.analysis_version,
            "document_id": frame.document_id,
            "paper_role": frame.paper_role,
            "candidate_source_count": len(candidate_sources),
            "relevant_source_count": len(relevant_sources),
            "routed_source_count": len(routed_sources),
            "inspected_source_count": len(inspected_sources),
            "result_source_count": len(
                {
                    _source_identity(item.source_kind, item.source_ref)
                    for item in result_evidence
                }
            ),
            "context_source_count": len(
                {
                    _source_identity(item.source_kind, item.source_ref)
                    for item in context_evidence
                }
            ),
            "technical_failure_count": len(failed_evidence),
            "uninspected_source_count": len(uninspected_sources),
            "result_count": len(result_evidence),
            "source_grounded_result_count": source_grounded_result_count,
            "closed_result_count": closed_result_count,
            "incomplete_result_count": len(result_evidence) - closed_result_count,
            "missing_field_families": missing_fields,
            "coverage_complete": bool(routed_sources) and not uninspected_sources,
            "closure_complete": closure_complete,
            "closure_basis": "post_materialization_same_paper_binding",
            "result_source_refs": _source_identity_records(
                {
                    _source_identity(item.source_kind, item.source_ref)
                    for item in result_evidence
                }
            ),
            "context_source_refs": _source_identity_records(
                {
                    _source_identity(item.source_kind, item.source_ref)
                    for item in context_evidence
                }
            ),
            "uninspected_source_refs": _source_identity_records(uninspected_sources),
            "candidate_source_refs": _source_identity_records(candidate_sources),
            "relevant_source_refs": _source_identity_records(relevant_sources),
            "inspected_source_refs": _source_identity_records(inspected_sources),
            "technical_failure_source_refs": _source_identity_records(
                failed_source_refs
            ),
            "technical_failure_details": [
                {
                    "source_kind": item.source_kind,
                    "source_ref": item.source_ref,
                    "reason": item.failure_reason,
                }
                for item in failed_evidence
            ],
            **_researcher_decision_packet_audit(document_evidence),
        }
        record_analysis_diagnostic(ledger)
        ledger_records.append(ledger)
    if emit_parity_snapshot:
        _record_researcher_information_parity_snapshot(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            ledger_records=tuple(ledger_records),
        )


def _record_researcher_information_parity_snapshot(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    ledger_records: tuple[Mapping[str, Any], ...],
) -> None:
    """Summarize whether the run exposed the context a researcher needs.

    This is deliberately an internal audit record.  Candidate Sources are
    navigation inputs, inspected Sources are the actual reading trajectory,
    and closure is only true after grounded result binding.  The snapshot
    makes those distinctions explicit without changing a scientific result or
    promoting a technical failure to a paper conclusion.
    """

    papers: list[dict[str, Any]] = []
    for ledger in ledger_records:
        missing_fields = {
            str(value).strip()
            for value in ledger.get("missing_field_families") or ()
            if str(value).strip()
        }
        result_count = int(ledger.get("result_count") or 0)
        technical_failure_count = int(ledger.get("technical_failure_count") or 0)
        closure_complete = bool(ledger.get("closure_complete"))
        if technical_failure_count:
            disposition = "extraction_failed"
        elif not result_count:
            disposition = "no_grounded_evidence"
        elif missing_fields or not closure_complete:
            disposition = "needs_context"
        elif not bool(ledger.get("coverage_complete")):
            disposition = "needs_context"
        else:
            disposition = "decision_ready"

        field_coverage = {
            "material": "material" not in missing_fields and result_count > 0,
            "variables": "variable" not in missing_fields and result_count > 0,
            "comparison": "comparison" not in missing_fields and result_count > 0,
            "outcome": result_count > 0,
            "process": "process" not in missing_fields and result_count > 0,
            "sample": "sample" not in missing_fields and result_count > 0,
            "test": "test" not in missing_fields and result_count > 0,
        }
        technical_failures = [
            dict(value)
            for value in ledger.get("technical_failure_details") or ()
            if isinstance(value, Mapping)
            and str(value.get("source_ref") or "").strip()
        ]
        packet_audit = {
            key: ledger[key]
            for key in (
                "decision_packet_sha256",
                "decision_packet_evidence_count",
                "decision_packet_evidence_ids",
                "decision_packet_evidence_ids_truncated",
                "decision_packet_source_count",
                "decision_packet_source_refs",
                "decision_packet_source_refs_truncated",
            )
            if key in ledger
        }
        papers.append(
            {
                "document_id": str(ledger.get("document_id") or ""),
                "paper_role": str(ledger.get("paper_role") or ""),
                "visible_source_refs": list(ledger.get("candidate_source_refs") or ()),
                "inspected_source_refs": list(ledger.get("inspected_source_refs") or ()),
                "uninspected_candidate_refs": list(
                    ledger.get("uninspected_source_refs") or ()
                ),
                "field_coverage": field_coverage,
                "missing_field_families": sorted(missing_fields),
                "technical_failures": technical_failures,
                "result_count": result_count,
                "closed_result_count": int(ledger.get("closed_result_count") or 0),
                "closure_complete": closure_complete,
                "final_disposition": disposition,
                **packet_audit,
            }
        )

    has_decision_ready = any(item["final_disposition"] == "decision_ready" for item in papers)
    has_grounded_result = any(int(item["result_count"]) > 0 for item in papers)
    has_technical_failure = any(item["technical_failures"] for item in papers)
    if has_decision_ready:
        final_disposition = "decision_ready"
    elif has_grounded_result:
        final_disposition = "needs_context"
    elif has_technical_failure:
        final_disposition = "extraction_failed"
    else:
        final_disposition = "no_grounded_evidence"

    record_analysis_diagnostic(
        {
            "trace_type": "researcher_information_parity",
            "collection_id": collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": analysis.analysis_version,
            "objective": objective.question,
            "papers": papers,
            "paper_count": len(papers),
            "final_disposition": final_disposition,
            "scientific_conclusion_allowed": final_disposition == "decision_ready",
            "technical_failure_count": sum(
                len(item["technical_failures"]) for item in papers
            ),
        }
    )


def _record_material_scope_exclusions(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    evidence_records: tuple[ObjectiveEvidence, ...],
) -> None:
    if not objective.material_scope:
        return
    exclusions: list[tuple[ObjectiveEvidence, str]] = []
    for evidence in evidence_records:
        if (
            evidence.reported_result is None
            or not evidence.changed_variables
            or evidence.evidence_role
            not in {"direct_result", "contradictory_result"}
        ):
            continue
        if not FindingSynthesisService.evidence_matches_objective_axes(
            objective,
            evidence,
        ):
            continue
        status = FindingSynthesisService.material_scope_status(objective, evidence)
        if status in {"matched", "not_required"}:
            continue
        exclusions.append((evidence, status))

    for evidence, status in exclusions[:_MATERIAL_SCOPE_DECISION_TRACE_LIMIT]:
        record_analysis_diagnostic(
            {
                "trace_type": "objective_material_scope_decision",
                "collection_id": collection_id,
                "objective_id": objective.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_id": evidence.document_id,
                "source_kind": evidence.source_kind,
                "source_ref": evidence.source_ref,
                "objective_material_scope": list(objective.material_scope),
                "evidence_material_scope": [
                    attribute.value
                    for attribute in evidence.scientific_context.material
                    if attribute.value not in (None, "")
                ],
                "scope_status": status,
                "disposition": "excluded_from_comparison",
            }
        )
    omitted_count = len(exclusions) - _MATERIAL_SCOPE_DECISION_TRACE_LIMIT
    if omitted_count > 0:
        record_analysis_diagnostic(
            {
                "trace_type": "objective_material_scope_decision_summary",
                "collection_id": collection_id,
                "objective_id": objective.objective_id,
                "analysis_version": analysis.analysis_version,
                "recorded_count": _MATERIAL_SCOPE_DECISION_TRACE_LIMIT,
                "omitted_count": omitted_count,
                "omitted_scope_status_counts": dict(
                    sorted(
                        Counter(
                            status
                            for _evidence, status in exclusions[
                                _MATERIAL_SCOPE_DECISION_TRACE_LIMIT:
                            ]
                        ).items()
                    )
                ),
            }
        )


def _objective_detail_evidence(
    evidence_items: tuple[ExtractedEvidenceDraft, ...],
    *,
    objective_context: ResearchObjective | None,
) -> tuple[ExtractedEvidenceDraft, ...]:
    if (
        objective_context is None
        or not objective_context.outcomes
        or not evidence_items
    ):
        return evidence_items
    target_axes = property_matching.objective_outcomes(objective_context)
    if not target_axes:
        return evidence_items

    # This is a relevance boundary, not a completeness boundary.  A researcher
    # keeps Methods, sample, process, and test Sources beside a result while
    # resolving it.  Dropping those drafts here makes the later same-paper
    # reconstruction impossible and turns "needs context" into "no result".
    context_roles = {
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
    }
    retained: list[ExtractedEvidenceDraft] = []
    seen_ids: set[str] = set()
    for unit in evidence_items:
        if unit.evidence_id in seen_ids:
            continue
        keep = unit.selection_status == "failed"
        if not keep and unit.reported_result is not None:
            # Scope controls Finding eligibility, not whether a Source-backed
            # fact exists.  Keep neighboring outcomes in the bundle so the
            # researcher can audit them or form a later Objective.
            keep = True
            if not _objective_evidence_matches_target_property(
                unit,
                target_axes=target_axes,
            ):
                payload = unit.to_record()
                payload["comparison"] = None
                payload["attribution_scope"] = "descriptive_only"
                payload["selection_reason"] = (
                    "Source-backed result retained for audit, but its outcome is "
                    "outside the confirmed Objective outcome scope; excluded from "
                    "Finding comparison."
                )
                unit = ExtractedEvidenceDraft.from_mapping(payload)
        if not keep and unit.reported_result is None:
            # Context is useful even when it has not yet completed a result.
            # It must carry a Source and a context role (or an explicit
            # candidate/selected state) so unrelated empty model responses are
            # not promoted into the Objective Evidence Bundle.
            keep = unit.evidence_role in context_roles or (
                unit.selection_status in {"candidate", "selected"}
                and bool(unit.selection_reason)
            )
        if keep:
            retained.append(unit)
            seen_ids.add(unit.evidence_id)
    return tuple(retained)


def _objective_evidence_matches_target_property(
    unit: ExtractedEvidenceDraft,
    *,
    target_axes: tuple[str, ...],
) -> bool:
    if unit.reported_result is None:
        return False
    return property_matching.outcome_matches_objective_scope(
        unit.reported_result.outcome,
        target_axes,
    )


def rebind_persisted_evidence(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    evidence_records: tuple[ObjectiveEvidence, ...],
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
) -> tuple[ObjectiveEvidence, ...]:
    """Reapply current Objective scope to a reusable Evidence checkpoint.

    A document checkpoint stores source-local scientific facts so a retry does
    not need another model call.  It must not, however, freeze the Objective
    axis interpretation that happened when the checkpoint was first written.
    Rebinding therefore reruns the deterministic Source-backed canonicalization
    against the current Objective and immutable Source artifacts.  If an old
    locator can no longer be resolved, the original fact is retained with the
    new analysis version; missing proof is safer than silently inventing a new
    binding.
    """

    rebound: list[ObjectiveEvidence] = []
    for evidence in evidence_records:
        versioned_original = evidence
        if evidence.analysis_version != analysis.analysis_version:
            versioned_original = replace(
                evidence,
                analysis_version=analysis.analysis_version,
            )
        if evidence.selection_status == "failed":
            rebound.append(versioned_original)
            continue

        payload = evidence.to_record()
        source_refs = [dict(ref) for ref in evidence.related_source_refs]
        primary_identity = _source_identity(evidence.source_kind, evidence.source_ref)
        if not any(
            _source_identity(ref.get("source_kind"), ref.get("source_ref"))
            == primary_identity
            for ref in source_refs
            if isinstance(ref, Mapping)
        ):
            source_refs.insert(
                0,
                {
                    "source_kind": evidence.source_kind,
                    "source_ref": evidence.source_ref,
                    "source_excerpt": evidence.source_excerpt,
                },
            )
        payload["source_refs"] = source_refs
        payload["evidence_anchor_ids"] = list(evidence.anchor_ids)
        draft = ExtractedEvidenceDraft.from_mapping(payload)
        source_excerpts_by_locator = _source_excerpts_by_locator(
            draft,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
            figures_by_document_id=figures_by_document_id,
        )
        try:
            canonical = _canonical_objective_evidence_axes(
                draft,
                objective=objective,
                source_excerpts_by_locator=source_excerpts_by_locator,
            )
        except ValueError as exc:
            record_analysis_diagnostic(
                {
                    "trace_type": "objective_source_axis_rebind_failed",
                    "collection_id": collection_id,
                    "objective_id": objective.objective_id,
                    "analysis_version": analysis.analysis_version,
                    "document_id": evidence.document_id,
                    "evidence_id": evidence.evidence_id,
                    "reason": f"ValueError: {exc}"[:1000],
                    "disposition": "preserved_source_fact",
                }
            )
            rebound.append(versioned_original)
            continue

        updated = evidence.to_record()
        updated["analysis_version"] = analysis.analysis_version
        updated["changed_variables"] = [
            item.to_record() for item in canonical.changed_variables
        ]
        updated["comparison"] = (
            canonical.comparison.to_record() if canonical.comparison is not None else None
        )
        updated["reported_result"] = (
            canonical.reported_result.to_record()
            if canonical.reported_result is not None
            else None
        )
        updated["attribution_scope"] = canonical.attribution_scope
        updated["selection_reason"] = canonical.selection_reason
        updated["resolution_status"] = canonical.resolution_status
        updated["failure_reason"] = canonical.failure_reason
        # Keep every previously persisted locator and add any locator supplied
        # by the immutable Source store.  The Source lineage remains the same
        # scientific claim, even when its Objective axis is rebound.
        updated["related_source_refs"] = _merge_source_reference_records(
            evidence.related_source_refs,
            canonical.source_refs,
        )
        try:
            rebound.append(ObjectiveEvidence.from_mapping(updated))
        except ValueError as exc:
            record_analysis_diagnostic(
                {
                    "trace_type": "objective_source_axis_rebind_failed",
                    "collection_id": collection_id,
                    "objective_id": objective.objective_id,
                    "analysis_version": analysis.analysis_version,
                    "document_id": evidence.document_id,
                    "evidence_id": evidence.evidence_id,
                    "reason": f"ValueError: {exc}"[:1000],
                    "disposition": "preserved_source_fact",
                }
            )
            rebound.append(versioned_original)
    return tuple(rebound)


def rebind_persisted_contribution(
    *,
    contribution: PaperContribution,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    evidence_records: tuple[ObjectiveEvidence, ...],
) -> PaperContribution:
    """Recompute contribution accounting from the rebound Evidence set.

    A document checkpoint stores both Evidence and its paper-level summary.
    Objective-axis binding is deterministic and may change when a later
    analysis version resolves a Source-defined factor.  Reusing the old
    contribution unchanged would then publish contradictory state (for
    example, comparable Evidence alongside ``no_comparable_evidence``).
    Route counts and warnings remain checkpoint facts; only fields derived
    from the Evidence records are projected again.
    """

    document_evidence = tuple(
        evidence
        for evidence in evidence_records
        if evidence.document_id == contribution.document_id
    )
    payload = contribution.to_record()
    # Older document checkpoints predate the coverage ledger and legitimately
    # contain none of its accounting fields.  Do not manufacture a partially
    # populated ledger while rebinding those records: the domain model accepts
    # the legacy shape, whereas a mixture of old ``None`` values and newly
    # derived counts is invalid and would turn a recoverable retry into a
    # failed analysis.
    coverage_fields = (
        "evidence_disposition",
        "routed_source_count",
        "extracted_source_count",
        "comparable_evidence_count",
        "failed_source_count",
    )
    if not all(payload.get(field) is not None for field in coverage_fields):
        payload["analysis_version"] = analysis.analysis_version
        return PaperContribution.from_mapping(payload)

    comparable_count = sum(
        FindingSynthesisService.is_synthesizable_result_evidence(
            objective,
            evidence,
        )
        for evidence in document_evidence
    )
    evidence_status_counts = tuple(
        sorted(Counter(evidence.evidence_status for evidence in document_evidence).items())
    )

    payload["analysis_version"] = analysis.analysis_version
    payload["comparable_evidence_count"] = comparable_count
    payload["evidence_status_counts"] = {
        status: count for status, count in evidence_status_counts
    }

    # A checkpoint with no route or incomplete coverage carries information
    # that cannot be inferred from its Evidence records.  Only re-project the
    # comparable/no-comparable pair whose meaning is entirely Evidence-based.
    if contribution.evidence_disposition in {
        "no_comparable_evidence",
        "comparable_evidence",
    }:
        if comparable_count:
            payload["evidence_disposition"] = "comparable_evidence"
            failed_count = contribution.failed_source_count or 0
            payload["evidence_disposition_reason"] = (
                f"{failed_count} selected source(s) failed extraction; "
                "comparable Evidence survived."
                if failed_count
                else None
            )
        else:
            payload["evidence_disposition"] = "no_comparable_evidence"
            payload["evidence_disposition_reason"] = (
                contribution.evidence_disposition_reason
                or "Selected sources produced no comparable direct result for this Objective."
            )

    rebound = PaperContribution.from_mapping(payload)
    record_analysis_diagnostic(
        {
            "trace_type": "objective_contribution_rebind",
            "collection_id": contribution.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": analysis.analysis_version,
            "document_id": contribution.document_id,
            "previous_disposition": contribution.evidence_disposition,
            "new_disposition": rebound.evidence_disposition,
            "previous_comparable_evidence_count": contribution.comparable_evidence_count,
            "new_comparable_evidence_count": rebound.comparable_evidence_count,
            "evidence_status_counts": dict(evidence_status_counts),
        }
    )
    return rebound


def _merge_source_reference_records(
    existing: tuple[dict[str, Any], ...],
    incoming: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reference in (*existing, *incoming):
        if not isinstance(reference, Mapping):
            continue
        identity = json.dumps(
            _identity_value(dict(reference)),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(dict(reference))
    return tuple(merged)


def _analysis_contributions(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    paper_maps: tuple[PaperResearchMap, ...],
    frames: tuple[PaperAnalysisFrame, ...],
    routes: tuple[EvidenceCandidate, ...],
    evidence_records: tuple[ObjectiveEvidence, ...],
    inspection_source_refs: Mapping[str, set[tuple[str, str]]] | None = None,
    document_trees_by_document_id: Mapping[str, SourceDocumentTree] | None = None,
) -> tuple[PaperContribution, ...]:
    paper_maps_by_document_id = {
        paper_map.document_id: paper_map for paper_map in paper_maps
    }
    routed_sources_by_document: dict[str, set[tuple[str, str]]] = {}
    for route in routes:
        if not route.extractable or route.role == "low_value_or_irrelevant":
            continue
        routed_sources_by_document.setdefault(route.document_id, set()).add(
            (route.source_kind, route.source_ref)
        )
    evidence_by_document: dict[str, list[ObjectiveEvidence]] = {}
    for evidence in evidence_records:
        evidence_by_document.setdefault(evidence.document_id, []).append(evidence)
        routed_sources_by_document.setdefault(evidence.document_id, set()).add(
            (evidence.source_kind, evidence.source_ref)
        )

    document_trees_by_document_id = document_trees_by_document_id or {}
    inspection_source_refs = inspection_source_refs or {}
    contributions: list[PaperContribution] = []
    for frame in frames:
        document_evidence = tuple(evidence_by_document.get(frame.document_id, ()))
        routed_sources = routed_sources_by_document.get(frame.document_id, set())
        excluded_by_frame = (
            frame.relevance == "irrelevant" or frame.paper_role == "irrelevant"
        )
        excluded_without_deep_reading = not routed_sources and not document_evidence
        excluded = excluded_by_frame or excluded_without_deep_reading
        # Adaptive context expansion adds routes during extraction. Those
        # routes are intentionally not returned in the first-pass `routes`
        # argument, so use the post-materialization Source set (which includes
        # every extracted or failed Source) for the inspected ledger.
        routed_source_refs = {
            _source_identity(source_kind, source_ref)
            for source_kind, source_ref in routed_sources
        }
        inspected_source_refs = {
            _source_identity(evidence.source_kind, evidence.source_ref)
            for evidence in document_evidence
            if evidence.source_ref
        }
        inspected_source_refs.update(
            inspection_source_refs.get(frame.document_id, set())
        )
        uninspected_source_count = len(routed_source_refs - inspected_source_refs)
        extracted_sources = {
            (evidence.source_kind, evidence.source_ref)
            for evidence in document_evidence
            if evidence.selection_status == "extracted"
        }
        failed_sources = {
            (evidence.source_kind, evidence.source_ref)
            for evidence in document_evidence
            if evidence.selection_status == "failed"
        }
        comparable_evidence_count = sum(
            FindingSynthesisService.is_synthesizable_result_evidence(
                objective,
                evidence,
            )
            for evidence in document_evidence
        )
        if excluded:
            analysis_status = "excluded"
            evidence_disposition = "excluded"
            routed_source_count = 0
            extracted_source_count = 0
            comparable_evidence_count = 0
            failed_source_count = 0
            uninspected_source_count = 0
            evidence_reason = (
                frame.screening_note or "Paper is not relevant to this objective."
                if excluded_by_frame
                else "No Source in this paper entered Objective deep reading."
            )
        else:
            routed_source_count = len(routed_sources)
            extracted_source_count = len(extracted_sources)
            failed_source_count = len(failed_sources)
            if uninspected_source_count > 0:
                analysis_status = "analyzed"
                evidence_disposition = "coverage_incomplete"
                evidence_reason = (
                    f"{uninspected_source_count} selected Source(s) were not "
                    "inspected for this Objective."
                )
            elif routed_source_count == 0:
                analysis_status = "analyzed"
                evidence_disposition = "no_routable_evidence"
                evidence_reason = (
                    "No source in this paper was selected for Objective extraction."
                )
            elif extracted_source_count == 0 and failed_source_count > 0:
                analysis_status = "failed"
                evidence_disposition = "extraction_failed"
                evidence_reason = (
                    f"{failed_source_count} selected source(s) failed extraction."
                )
            elif comparable_evidence_count == 0:
                analysis_status = "analyzed"
                evidence_disposition = "no_comparable_evidence"
                evidence_reason = (
                    "Selected sources produced no comparable direct result for "
                    "this Objective."
                )
            else:
                analysis_status = "analyzed"
                evidence_disposition = "comparable_evidence"
                evidence_reason = (
                    f"{failed_source_count} selected source(s) failed extraction; "
                    "comparable Evidence survived."
                    if failed_source_count
                    else None
                )
        evidence_status_counts = tuple(
            sorted(
                Counter(evidence.evidence_status for evidence in document_evidence).items()
            )
        )
        fallback_source_count = sum(
            disposition.disposition == "fallback_relevant"
            for disposition in frame.source_dispositions
        )
        routing_fallback_source_count = len(
            {
                (route.source_kind, route.source_ref)
                for route in routes
                if route.document_id == frame.document_id and route.used_fallback
            }
        )
        paper_map = paper_maps_by_document_id.get(frame.document_id)
        paper_map_failure_count = sum(
            coverage.status is PaperSourceUnitCoverageStatus.EXTRACTION_FAILED
            for coverage in (
                paper_map.source_unit_coverage if paper_map is not None else ()
            )
        )
        warnings: list[str] = []
        if fallback_source_count:
            warnings.append(
                f"{fallback_source_count} Source unit(s) used conservative "
                "paper framing fallback."
            )
        if routing_fallback_source_count:
            warnings.append(
                f"{routing_fallback_source_count} Source unit(s) used deterministic "
                "evidence routing fallback."
            )
        if paper_map_failure_count:
            warnings.append(
                f"{paper_map_failure_count} PaperResearchMap Source unit(s) failed "
                "extraction before Objective analysis."
            )
        if failed_source_count:
            warnings.append(
                f"{failed_source_count} selected source(s) failed extraction."
            )
        if uninspected_source_count:
            warnings.append(
                f"{uninspected_source_count} selected Source(s) were not "
                "inspected for this Objective."
            )
        contributions.append(
            PaperContribution(
                collection_id=collection_id,
                objective_id=analysis.objective_id,
                analysis_version=analysis.analysis_version,
                document_id=frame.document_id,
                analysis_status=analysis_status,
                relevance=frame.relevance,
                paper_role=frame.paper_role,
                contribution_summary=(
                    None
                    if excluded
                    else _source_backed_contribution_summary(document_evidence)
                ),
                material_match=frame.material_match,
                changed_variables=frame.changed_variables,
                measured_property_scope=frame.measured_property_scope,
                test_environment_scope=frame.test_environment_scope,
                exclusion_reason=evidence_reason if excluded else None,
                warnings=tuple(warnings),
                confidence=1.0 if frame.relevance == "high" else 0.7,
                evidence_disposition=evidence_disposition,
                routed_source_count=routed_source_count,
                extracted_source_count=extracted_source_count,
                comparable_evidence_count=comparable_evidence_count,
                failed_source_count=failed_source_count,
                uninspected_source_count=uninspected_source_count,
                evidence_disposition_reason=evidence_reason,
                evidence_status_counts=evidence_status_counts,
                inspected_source_refs=tuple(
                    {
                        "source_kind": source_kind,
                        "source_ref": source_ref,
                        "source_digest": None,
                    }
                    for source_kind, source_ref in sorted(inspected_source_refs)
                    if source_kind in {"text_window", "table", "figure"}
                ),
            )
        )
    return tuple(contributions)


def _frame_source_route_key(*, source_kind: str, source_ref: str) -> tuple[str, str]:
    """Normalize framing's section/block identity to the extraction route key."""

    return _source_identity(source_kind, source_ref)


def _frame_source_scope_refs(
    *,
    frame: PaperAnalysisFrame,
    document_tree: SourceDocumentTree | None,
) -> dict[tuple[str, str], bool]:
    """Resolve framing units to the concrete Sources a researcher would read.

    Framing may select a section node. Extraction then reads its paragraph,
    caption, table, or figure children because those are the stable artifact
    references used by Evidence. The ledger must compare those same identities
    so a section is not reported as unread after its children were inspected.
    """

    scope: dict[tuple[str, str], bool] = {}

    def add_node_source(node: Any) -> None:
        source_ref = _text(getattr(node, "source_ref_id", ""))
        if not source_ref:
            return
        source_kind = _text(getattr(node, "source_ref_kind", ""))
        if source_kind in {"block", "section", "text", "text_window"}:
            source_kind = "text_window"
        scope[_source_identity(source_kind, source_ref)] = True

    def section_children(node: Any) -> set[tuple[str, str]]:
        child_scope: set[tuple[str, str]] = set()
        child_ids = tuple(getattr(node, "child_ids", ()) or ())
        for child_id in child_ids:
            child = document_tree.nodes.get(child_id) if document_tree else None
            if child is None:
                continue
            node_type = _text(getattr(child, "node_type", ""))
            if node_type in {"section", "references_section"}:
                child_scope.update(section_children(child))
                continue
            source_ref = _text(getattr(child, "source_ref_id", ""))
            if not source_ref:
                continue
            source_kind = _text(getattr(child, "source_ref_kind", ""))
            if source_kind in {"block", "section", "text", "text_window"}:
                source_kind = "text_window"
            child_scope.add(_source_identity(source_kind, source_ref))
        return child_scope

    for disposition in frame.source_dispositions:
        source_kind = _text(disposition.source_kind)
        source_ref = _text(disposition.source_ref)
        if not source_kind or not source_ref:
            continue
        normalized = _source_identity(source_kind, source_ref)
        if disposition.is_relevant and source_kind.casefold() == "section" and document_tree:
            section_node = document_tree.nodes.get(source_ref)
            if section_node is None:
                section_node = document_tree.node_for_source_ref("block", source_ref)
            children = section_children(section_node) if section_node is not None else set()
            if children:
                for child_ref in children:
                    scope[child_ref] = True
                continue
        scope[normalized] = disposition.is_relevant
    return scope


def _analysis_evidence_records(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    drafts: tuple[ExtractedEvidenceDraft, ...],
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
) -> tuple[ObjectiveEvidence, ...]:
    records: list[ObjectiveEvidence] = []
    seen_evidence_ids: set[str] = set()
    scientific_fact_indexes: dict[str, int] = {}
    for source_draft in drafts:
        source_excerpts_by_locator = _source_excerpts_by_locator(
            source_draft,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
            figures_by_document_id=figures_by_document_id,
        )
        try:
            draft = _canonical_objective_evidence_axes(
                source_draft,
                objective=objective,
                source_excerpts_by_locator=source_excerpts_by_locator,
            )
        except ValueError as exc:
            payload = source_draft.to_record()
            payload.update(
                {
                    "evidence_role": "irrelevant",
                    "selection_status": "failed",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                    "resolution_status": "unknown",
                    "failure_reason": f"ValueError: {exc}"[:1000],
                    "confidence": 0.0,
                }
            )
            draft = ExtractedEvidenceDraft.from_mapping(payload)
        source = _canonical_evidence_source(
            draft,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
            figures_by_document_id=figures_by_document_id,
        )
        if source is None:
            raise RuntimeError(
                "Evidence Source cannot be resolved: "
                f"evidence_id={draft.evidence_id} "
                f"document_id={draft.document_id} "
                f"source_kind={draft.source_kind} "
                f"source_ref={draft.source_ref}"
            )
        recovered_draft = _recover_source_explicit_objective_factors(
            draft,
            objective=objective,
            source_excerpt=source["source_excerpt"],
            source_kind=source["source_kind"],
            source_ref=source["source_ref"],
        )
        if recovered_draft != draft:
            draft = recovered_draft
            source = _canonical_evidence_source(
                draft,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                figures_by_document_id=figures_by_document_id,
            )
            if source is None:
                raise RuntimeError(
                    "Recovered Evidence Source cannot be resolved: "
                    f"evidence_id={draft.evidence_id} "
                    f"document_id={draft.document_id} "
                    f"source_kind={draft.source_kind} "
                    f"source_ref={draft.source_ref}"
                )
        if draft.evidence_id in seen_evidence_ids:
            continue
        seen_evidence_ids.add(draft.evidence_id)
        evidence_role = _canonical_evidence_role(draft)
        selection_status = draft.selection_status
        selection_reason = draft.selection_reason
        resolution_status = draft.resolution_status
        if (
            selection_status == "extracted"
            and draft.reported_result is None
            and not draft.changed_variables
            and draft.comparison is None
            and not draft.scientific_context.has_content
        ):
            # A selected Source can be valid context even when the model did
            # not resolve a field from it.  Keep the Source as a researcher-
            # actionable needs-context record instead of failing materialization.
            selection_status = "candidate"
            selection_reason = selection_reason or (
                "Source selected for Objective context but no source-grounded "
                "fields were resolved."
            )
            resolution_status = "unresolved"
        candidate = ObjectiveEvidence(
            collection_id=collection_id,
            objective_id=analysis.objective_id,
            analysis_version=analysis.analysis_version,
            evidence_id=draft.evidence_id[:128],
            document_id=draft.document_id,
            source_kind=source["source_kind"],
            source_ref=source["source_ref"],
            source_excerpt=source["source_excerpt"],
            page_numbers=source["page_numbers"],
            related_source_refs=source["related_source_refs"],
            evidence_role=evidence_role,
            selection_status=selection_status,
            selection_reason=selection_reason,
            changed_variables=draft.changed_variables,
            comparison=draft.comparison,
            reported_result=draft.reported_result,
            attribution_scope=draft.attribution_scope,
            scientific_context=draft.scientific_context,
            anchor_ids=draft.evidence_anchor_ids,
            resolution_status=(
                resolution_status
                if selection_status == "failed"
                else (
                    resolution_status
                    if resolution_status in {"resolved", "partial"}
                    else "partial"
                )
            ),
            failure_reason=draft.failure_reason,
            confidence=draft.confidence,
            related_source_refs_explicit=True,
        )
        context_gaps = _objective_missing_context_fields(candidate, objective)
        if candidate.selection_status == "extracted" and context_gaps:
            # Model resolution is not scientific closure. Preserve the
            # source-backed result, but make an open same-paper context
            # visible to every downstream consumer.
            payload = candidate.to_record()
            payload["resolution_status"] = "partial"
            if candidate.attribution_scope in {"isolated_effect", "joint_effect"}:
                payload["attribution_scope"] = (
                    "descriptive_only"
                    if not candidate.changed_variables
                    or "variable" in context_gaps
                    or "comparison" in context_gaps
                    else "association_only"
                )
            gap_note = (
                "Research context remains open; missing same-paper fields: "
                + ", ".join(sorted(context_gaps))
                + "."
            )
            payload["selection_reason"] = (
                f"{candidate.selection_reason or 'Source-backed result retained.'} "
                f"{gap_note}"
            ).strip()
            candidate = ObjectiveEvidence.from_mapping(payload)
        # Model retries and same-paper rereads can return the same fact with a
        # different generated id or a differently worded context expansion.
        # Evidence identity follows the source-grounded claim, not the provider
        # attempt.  Context-only Sources retain their context in the identity,
        # because one table or Methods Source may contain several independent
        # condition facts; a result Source instead coalesces equivalent reads
        # and keeps the richer record plus the unioned lineage.
        scientific_identity = _scientific_fact_identity(candidate)
        duplicate_index = scientific_fact_indexes.get(scientific_identity)
        if duplicate_index is None:
            scientific_fact_indexes[scientific_identity] = len(records)
            records.append(candidate)
            continue
        records[duplicate_index] = _merge_duplicate_evidence(
            records[duplicate_index],
            candidate,
        )
    return tuple(records)


def _scientific_fact_identity(evidence: ObjectiveEvidence) -> str:
    """Return a stable identity for one Source-local scientific fact.

    Route reasons, generated ids, excerpts from related Sources, confidence,
    and same-paper context wording are not fact identity.  For context-only
    records the structured context is retained so distinct facts from one
    Source do not collapse into one row.
    """

    variables = sorted(
        (
            _identity_value(variable.name),
            _identity_value(variable.baseline_value),
            _identity_value(variable.target_value),
            _identity_value(variable.unit),
        )
        for variable in evidence.changed_variables
    )
    result = evidence.reported_result.to_record() if evidence.reported_result else None
    comparison = evidence.comparison.to_record() if evidence.comparison else None
    payload: dict[str, Any] = {
        "document_id": _identity_value(evidence.document_id),
        "source_kind": _identity_value(_source_identity(evidence.source_kind, "")[0]),
        "source_ref": _identity_value(
            _source_identity(evidence.source_kind, evidence.source_ref)[1]
        ),
        "evidence_role": _identity_value(evidence.evidence_role),
        "changed_variables": variables,
        "comparison": _identity_value(comparison),
        "reported_result": _identity_value(result),
        "attribution_scope": _identity_value(evidence.attribution_scope),
    }
    source_local_slots = sorted(
        {
            json.dumps(
                _identity_value(
                    {
                        field: locator[field]
                        for field in (
                            "row_index",
                            "col_index",
                            "start_row",
                            "end_row",
                            "start_col",
                            "end_col",
                            "cell_id",
                        )
                        if locator.get(field) not in (None, "")
                    }
                ),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for locator in evidence.related_source_refs
            if _source_identity(
                locator.get("source_kind"),
                locator.get("source_ref"),
            )
            == _source_identity(evidence.source_kind, evidence.source_ref)
            and any(
                locator.get(field) not in (None, "")
                for field in (
                    "row_index",
                    "col_index",
                    "start_row",
                    "end_row",
                    "start_col",
                    "end_col",
                    "cell_id",
                )
            )
        }
    )
    if source_local_slots:
        payload["source_local_slots"] = source_local_slots
    if evidence.reported_result is None:
        payload["scientific_context"] = _identity_value(
            evidence.scientific_context.to_record()
        )
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _identity_value(value: Any) -> Any:
    """Normalize labels for identity without changing persisted Evidence."""

    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, Mapping):
        return {
            str(key): _identity_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_identity_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_identity_value(item) for item in value)
    return value


def _merge_duplicate_evidence(
    existing: ObjectiveEvidence,
    candidate: ObjectiveEvidence,
) -> ObjectiveEvidence:
    """Keep one fact while preserving the strongest record and all locators."""

    preferred = max(
        (existing, candidate),
        key=lambda item: (
            item.selection_status == "extracted",
            item.resolution_status == "resolved",
            item.comparison is not None and item.comparison.comparable,
            sum(
                len(getattr(item.scientific_context, section))
                for section in ("material", "sample", "process", "test")
            ),
            item.confidence,
        ),
    )
    related_source_refs: list[dict[str, Any]] = []
    seen_locators: set[str] = set()
    for item in (existing, candidate):
        for locator in item.related_source_refs:
            identity = json.dumps(
                _identity_value(locator),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if identity in seen_locators:
                continue
            seen_locators.add(identity)
            related_source_refs.append(dict(locator))
    payload = preferred.to_record()
    payload["evidence_id"] = existing.evidence_id
    payload["related_source_refs"] = related_source_refs
    payload["anchor_ids"] = list(
        dict.fromkeys((*existing.anchor_ids, *candidate.anchor_ids))
    )
    return ObjectiveEvidence.from_mapping(payload)


def _recover_source_explicit_objective_factors(
    draft: ExtractedEvidenceDraft,
    *,
    objective: ResearchObjective,
    source_excerpt: str,
    source_kind: str,
    source_ref: str,
) -> ExtractedEvidenceDraft:
    """Recover omitted factor names from the exact Source being materialized.

    Some result responses contain a valid reported outcome and direction but
    omit ``changed_variables``.  The Source excerpt is already resolved at
    this point, so a factor can be restored only when its confirmed Objective
    label is explicitly present there.  Endpoint values remain unknown; this
    produces an association-level record and cannot unlock strict comparison.
    """

    result = draft.reported_result
    if (
        draft.selection_status == "failed"
        or result is None
        or draft.changed_variables
        or draft.evidence_role not in {"direct_result", "contradictory_result"}
        or not source_excerpt.strip()
        or not property_matching.outcome_matches_objective_scope(
            result.outcome,
            objective.outcomes,
        )
    ):
        return draft

    mentioned_factors = tuple(
        objective_variable
        for objective_variable in objective.variables
        if property_matching.source_text_mentions_objective_variable(
            source_excerpt,
            objective_variable,
        )
        and _objective_source_explicitly_links_variable_to_result(
            variable=objective_variable,
            outcome=result.outcome,
            result_text=result.result_text,
            source_text=source_excerpt,
            source={"source_kind": source_kind},
        )
    )
    if not mentioned_factors:
        return draft

    payload = draft.to_record()
    payload["changed_variables"] = [
        {
            "name": objective_variable,
            "baseline_value": None,
            "target_value": None,
            "unit": None,
        }
        for objective_variable in mentioned_factors
    ]
    # An unresolved comparison is a valid source-backed observation, but it is
    # not an attribution.  Keep ``not_attributable`` so the domain invariant
    # and the scientific meaning agree; only a comparison that is absent (or
    # already comparable) may be retained as an association.
    if (
        draft.attribution_scope == "not_attributable"
        and (draft.comparison is None or draft.comparison.comparable)
        and result.direction not in {"unknown", "mixed"}
    ):
        payload["attribution_scope"] = "association_only"
    payload["resolution_status"] = "partial"
    payload["selection_reason"] = (
        f"{draft.selection_reason or 'Source-backed result retained.'} "
        "The confirmed Objective factor was explicitly mentioned in the linked "
        "Source; comparison endpoints remain unresolved."
    ).strip()
    source_refs = [dict(ref) for ref in payload.get("source_refs", [])]
    matching_ref = next(
        (
            ref
            for ref in source_refs
            if str(ref.get("source_kind") or "") == source_kind
            and str(ref.get("source_ref") or "") == source_ref
        ),
        None,
    )
    if matching_ref is None:
        source_refs.append(
            {
                "source_kind": source_kind,
                "source_ref": source_ref,
                "supports": ["changed_variables"],
            }
        )
    else:
        matching_ref["supports"] = list(
            dict.fromkeys(
                (
                    *(str(value) for value in matching_ref.get("supports", ())),
                    "changed_variables",
                )
            )
        )
    payload["source_refs"] = source_refs
    return ExtractedEvidenceDraft.from_mapping(payload)


def _canonical_objective_evidence_axes(
    draft: ExtractedEvidenceDraft,
    *,
    objective: ResearchObjective,
    source_excerpts_by_locator: Mapping[tuple[str, str], str] | None = None,
) -> ExtractedEvidenceDraft:
    if draft.selection_status == "failed":
        return draft

    payload = draft.to_record()
    recorded_source_bindings: set[tuple[str, str]] = set()

    def canonical(value: Any, axes: tuple[str, ...]) -> tuple[str, str | None]:
        resolved = property_matching.resolve_objective_axis(value, axes)
        if resolved is None and axes is objective.variables:
            resolved = _resolve_source_defined_objective_axis(
                draft,
                source_label=value,
                objective_axes=axes,
                source_excerpts_by_locator=source_excerpts_by_locator,
            )
            source_key = _text(value)
            if resolved is not None and (source_key, resolved) not in recorded_source_bindings:
                recorded_source_bindings.add((source_key, resolved))
                record_analysis_diagnostic(
                    {
                        "trace_type": "objective_source_axis_binding",
                        "collection_id": objective.collection_id,
                        "objective_id": objective.objective_id,
                        "document_id": draft.document_id,
                        "evidence_id": draft.evidence_id,
                        "source_axis": source_key,
                        "objective_axis": resolved,
                        "binding_basis": "same_paper_source_definition",
                        "source_refs": [
                            {
                                "source_kind": _source_identity(
                                    ref.get("source_kind"),
                                    ref.get("source_ref"),
                                )[0],
                                "source_ref": _source_identity(
                                    ref.get("source_kind"),
                                    ref.get("source_ref"),
                                )[1],
                            }
                            for ref in draft.source_refs
                            if isinstance(ref, Mapping)
                            and _source_ref_supports_axis_binding(ref)
                        ],
                    }
                )
        return resolved or str(value or "").strip(), resolved

    canonical_variables: list[dict[str, Any]] = []
    objective_variable_indexes: dict[str, int] = {}
    for variable in payload["changed_variables"]:
        variable = dict(variable)
        variable["name"], resolved = canonical(
            variable.get("name"),
            objective.variables,
        )
        if resolved is None:
            canonical_variables.append(variable)
            continue
        axis_key = property_matching.axis_key(resolved)
        existing_index = objective_variable_indexes.get(axis_key)
        if existing_index is None:
            objective_variable_indexes[axis_key] = len(canonical_variables)
            canonical_variables.append(variable)
            continue
        existing = canonical_variables[existing_index]
        for field in ("baseline_value", "target_value", "unit"):
            current = existing.get(field)
            candidate = variable.get(field)
            if current in (None, ""):
                if candidate not in (None, ""):
                    existing[field] = candidate
                continue
            if candidate in (None, ""):
                continue
            if str(current).strip().casefold() != str(candidate).strip().casefold():
                raise ValueError(
                    f"conflicting values for Objective axis {resolved}: {field}"
                )
    payload["changed_variables"] = canonical_variables
    comparison = payload.get("comparison")
    if isinstance(comparison, dict):
        comparison["axis_names"] = list(
            dict.fromkeys(
                canonical(axis, objective.variables)[0]
                for axis in comparison.get("axis_names") or ()
            )
        )
    result = payload.get("reported_result")
    if isinstance(result, dict):
        source_outcome = result.get("outcome")
        canonical_outcome = canonical(source_outcome, objective.outcomes)[1]
        if canonical_outcome is None:
            broad_matches = tuple(
                axis
                for axis in objective.outcomes
                if property_matching.outcome_matches_objective_scope(
                    source_outcome,
                    (axis, *property_matching.broad_outcome_expansions(axis)),
                )
            )
            if len(broad_matches) == 1:
                canonical_outcome = broad_matches[0]
        result["outcome"] = canonical_outcome or str(source_outcome or "").strip()
    if (
        payload.get("attribution_scope") == "joint_effect"
        and len(canonical_variables) == 1
    ):
        payload["attribution_scope"] = "isolated_effect"
    return ExtractedEvidenceDraft.from_mapping(payload)


def _resolve_source_defined_objective_axis(
    draft: ExtractedEvidenceDraft,
    *,
    source_label: Any,
    objective_axes: tuple[str, ...],
    source_excerpts_by_locator: Mapping[tuple[str, str], str] | None = None,
) -> str | None:
    """Resolve a source-specific factor only from an explicit paper mapping.

    A model may use a narrower label than the confirmed Objective (for example,
    a temperature field for an intervention described as platform preheating).
    Vocabulary can suggest that relationship, but it cannot establish it.  We
    therefore require one same-paper Source bundle that:

    * is explicitly marked as supporting a changed variable or comparison axis;
    * names exactly one Objective axis in the Source text; and
    * contains both comparison endpoints (or the extracted endpoint values).

    This is deliberately generic.  It does not know a material, process, group
    label, or domain synonym.  The Source remains the authority and the
    original model label is retained when the proof is absent or ambiguous.
    """

    if not objective_axes or not draft.source_refs or draft.comparison is None:
        return None

    comparison = draft.comparison
    endpoint_values = (
        comparison.baseline_label,
        comparison.target_label,
    )
    if any(not _text(value) for value in endpoint_values):
        endpoint_values = (
            next(
                (
                    variable.baseline_value
                    for variable in draft.changed_variables
                    if variable.baseline_value not in (None, "")
                ),
                None,
            ),
            next(
                (
                    variable.target_value
                    for variable in draft.changed_variables
                    if variable.target_value not in (None, "")
                ),
                None,
            ),
        )
    if any(value in (None, "") for value in endpoint_values):
        return None
    if _source_axis_endpoint_key(endpoint_values[0]) == _source_axis_endpoint_key(
        endpoint_values[1]
    ):
        return None

    source_excerpts_by_locator = source_excerpts_by_locator or {}
    supported_texts = tuple(
        source_text
        for ref in draft.source_refs
        if isinstance(ref, Mapping)
        and _source_ref_supports_axis_binding(ref)
        if (
            source_text := _text(ref.get("source_excerpt"))
            or _text(
                source_excerpts_by_locator.get(
                    _source_identity(
                        ref.get("source_kind"),
                        ref.get("source_ref"),
                    )
                )
            )
        )
    )
    if not supported_texts:
        return None
    combined_text = "\n".join(supported_texts)
    candidates = tuple(
        axis
        for axis in objective_axes
        if property_matching.source_text_mentions_axis(combined_text, axis)
        and any(
            property_matching.source_text_mentions_axis(text, axis)
            and _source_text_mentions_value(text, endpoint_values[0])
            and _source_text_mentions_value(text, endpoint_values[1])
            for text in supported_texts
        )
    )
    if len(candidates) != 1:
        return None

    # Keep the source label in the proof record.  This prevents a broad
    # Objective theme from silently replacing a precise factor merely because
    # both happen to occur in the same paper.
    source_label_text = _text(source_label)
    if not source_label_text:
        return None
    if not any(
        _source_text_mentions_value(text, source_label_text)
        or property_matching.source_text_mentions_axis(text, source_label_text)
        for text in supported_texts
    ):
        # A derived field can be absent from the prose when the paper defines
        # the comparison directly by group labels.  In that case the explicit
        # Objective axis plus both endpoints is sufficient; no guessed alias is
        # introduced.
        pass
    return candidates[0]


def _source_excerpts_by_locator(
    draft: ExtractedEvidenceDraft,
    *,
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
) -> dict[tuple[str, str], str]:
    """Resolve model-owned locators against the immutable prepared document."""

    excerpts: dict[tuple[str, str], str] = {}
    for ref in draft.source_refs:
        if not isinstance(ref, Mapping):
            continue
        source_kind, source_ref = _source_identity(
            ref.get("source_kind"),
            ref.get("source_ref"),
        )
        if not source_ref:
            continue
        supplied_excerpt = _text(ref.get("source_excerpt"))
        if supplied_excerpt:
            excerpts[(source_kind, source_ref)] = supplied_excerpt
            continue
        located = _source_excerpt_for_locator(
            document_id=draft.document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
            figures_by_document_id=figures_by_document_id,
        )
        if located is not None and (excerpt := _text(located.get("source_excerpt"))):
            excerpts[(source_kind, source_ref)] = excerpt
    return excerpts


def _source_ref_supports_axis_binding(ref: Mapping[str, Any]) -> bool:
    supports = {
        _text(value)
        for value in ref.get("supports", ())
        if _text(value)
    }
    return bool(
        supports
        & {
            "changed_variables",
            "comparison.axis_names",
            "condition_join",
        }
    )


def _source_axis_endpoint_key(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _source_text_mentions_value(text: str, value: Any) -> bool:
    """Match a Source endpoint without treating it as a substring accident."""

    value_text = " ".join(str(value or "").strip().split())
    source_text = " ".join(str(text or "").split())
    if not value_text or not source_text:
        return False
    pattern = re.escape(value_text).replace(r"\ ", r"\s+")
    return re.search(
        rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])",
        source_text,
        flags=re.IGNORECASE,
    ) is not None


def _canonical_evidence_source(
    draft: ExtractedEvidenceDraft,
    *,
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
) -> dict[str, Any] | None:
    primary_kind = (
        "text_window"
        if draft.source_kind in {"block", "text"}
        else draft.source_kind
    )
    primary = _source_excerpt_for_locator(
        document_id=draft.document_id,
        source_kind=primary_kind,
        source_ref=draft.source_ref,
        blocks_by_document_id=blocks_by_document_id,
        tables_by_document_id=tables_by_document_id,
        figures_by_document_id=figures_by_document_id,
    )
    if primary is not None:
        primary = {
            **primary,
            "source_ref": draft.source_ref,
        }
    candidates = [
        *[dict(value) for value in draft.source_refs],
        {
            "source_kind": draft.source_kind,
            "source_ref": draft.source_ref,
        },
    ]
    related: list[dict[str, Any]] = []
    seen_locators: set[tuple[Any, ...]] = set()
    table_excerpts_by_locator: dict[tuple[str, str], list[str]] = {}
    table_fact_excerpts_by_locator: dict[tuple[str, str], list[str]] = {}
    for candidate in candidates:
        source_kind = _text(candidate.get("source_kind"))
        source_ref = _text(candidate.get("source_ref"))
        if not source_ref:
            continue
        normalized_kind = (
            "text_window" if source_kind in {"block", "text"} else source_kind
        )
        located = _source_excerpt_for_locator(
            document_id=draft.document_id,
            source_kind=normalized_kind,
            source_ref=source_ref,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
            figures_by_document_id=figures_by_document_id,
        )
        locator = {
            key: value
            for key, value in candidate.items()
            if key != "source_excerpt" and value not in (None, "", [], {})
        }
        locator["source_kind"] = normalized_kind or "text_window"
        locator["source_ref"] = source_ref
        page = candidate.get("page") or (located or {}).get("page")
        if page not in (None, ""):
            locator["page"] = page
        locator_key = (
            locator["source_kind"],
            locator["source_ref"],
            locator.get("row_index"),
            locator.get("col_index"),
        )
        is_bare_duplicate = (
            locator.get("row_index") is None
            and locator.get("col_index") is None
            and any(
                item.get("source_kind") == locator["source_kind"]
                and item.get("source_ref") == locator["source_ref"]
                for item in related
            )
        )
        if locator_key not in seen_locators and not is_bare_duplicate:
            seen_locators.add(locator_key)
            related.append(locator)
        candidate_excerpt = _text(candidate.get("source_excerpt"))
        if normalized_kind == "table" and candidate_excerpt:
            table_excerpts = table_excerpts_by_locator.setdefault(
                (normalized_kind, source_ref),
                [],
            )
            if candidate_excerpt not in table_excerpts:
                table_excerpts.append(candidate_excerpt)
            supports = {
                str(value).strip()
                for value in candidate.get("supports", ())
                if str(value).strip()
            }
            if candidate.get("col_index") is not None or not any(
                value.startswith("scientific_context.") for value in supports
            ):
                fact_excerpts = table_fact_excerpts_by_locator.setdefault(
                    (normalized_kind, source_ref),
                    [],
                )
                if candidate_excerpt not in fact_excerpts:
                    fact_excerpts.append(candidate_excerpt)
        if located is None:
            continue
        supports_paged_context = (
            draft.reported_result is None
            and draft.comparison is None
            and not draft.changed_variables
            and any(
                str(value).startswith("scientific_context.")
                for value in candidate.get("supports", ())
            )
        )
        if (
            primary is not None
            and not primary.get("page")
            and located.get("page")
            and normalized_kind == "text_window"
            and supports_paged_context
        ):
            # Imported filenames help screening but are not an inspectable
            # scientific passage. Once the same fact is grounded in a paged
            # Abstract or Methods Source, that passage owns the durable jump.
            primary = {
                **located,
                "source_kind": located["source_kind"],
                "source_ref": source_ref,
                "page": located["page"],
            }
            continue
        if primary is None:
            primary = {
                **located,
                "source_kind": located["source_kind"],
                "source_ref": source_ref,
                "page": located["page"],
            }
    if primary is None:
        return None
    source_excerpt = primary["source_excerpt"]
    if primary["source_kind"] == "table":
        primary_table_key = (primary["source_kind"], primary["source_ref"])
        primary_table_excerpts = table_fact_excerpts_by_locator.get(
            primary_table_key,
            [],
        ) or table_excerpts_by_locator.get(
            primary_table_key,
            [],
        )
        if primary_table_excerpts:
            source_excerpt = "\n".join(primary_table_excerpts)[:12_000]
    # One Evidence locator names one inspectable primary Source. Same-paper
    # methods, other tables, figures, and row bindings remain explicit lineage
    # in related_source_refs; concatenating them here would make the excerpt
    # look like text from a Source that never contained it.
    return {
        "source_kind": primary["source_kind"],
        "source_ref": primary["source_ref"],
        "source_excerpt": source_excerpt,
        "page_numbers": ((primary["page"],) if primary["page"] else ()),
        "related_source_refs": tuple(related),
    }


def _source_excerpt_for_locator(
    *,
    document_id: str,
    source_kind: str,
    source_ref: str,
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
) -> dict[str, Any] | None:
    if source_kind == "text_window":
        for block in blocks_by_document_id.get(document_id, []):
            if str(getattr(block, "block_id", "")) == source_ref:
                text = str(getattr(block, "text", "")).strip()
                if text:
                    return {
                        "source_kind": "text_window",
                        "source_excerpt": text[:12_000],
                        "page": getattr(block, "page", None),
                    }
    elif source_kind == "table":
        for table in tables_by_document_id.get(document_id, []):
            if str(getattr(table, "table_id", "")) == source_ref:
                record = table.to_record()
                text = str(
                    record.get("table_markdown")
                    or record.get("table_text")
                    or record.get("caption_text")
                    or ""
                ).strip()
                if text:
                    return {
                        "source_kind": "table",
                        "source_excerpt": text[:12_000],
                        "page": getattr(table, "page", None),
                    }
    elif source_kind == "figure":
        for figure in figures_by_document_id.get(document_id, []):
            if str(getattr(figure, "figure_id", "")) == source_ref:
                text = str(getattr(figure, "caption_text", "") or "").strip()
                if text:
                    return {
                        "source_kind": "figure",
                        "source_excerpt": text[:12_000],
                        "page": getattr(figure, "page", None),
                    }
    return None


def _canonical_evidence_role(draft: ExtractedEvidenceDraft) -> str:
    role = _text(draft.evidence_role)
    if role in {
        "direct_result",
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
        "contradictory_result",
        "irrelevant",
    }:
        return role
    return "irrelevant"
