from __future__ import annotations

from typing import Any, Mapping

from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    PaperSkim,
    PaperSourceUnitCoverageStatus,
    ResearchObjective,
)

def _text(value: Any) -> str:
    return str(value or "").strip()


def materialize_evidence(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    drafts: tuple[ExtractedEvidenceDraft, ...],
    paper_skims: tuple[PaperSkim, ...],
    frames: tuple[PaperAnalysisFrame, ...],
    routes: tuple[EvidenceCandidate, ...],
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
) -> tuple[tuple[ObjectiveEvidence, ...], tuple[PaperContribution, ...]]:
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
    contributions = _analysis_contributions(
        collection_id=collection_id,
        analysis=analysis,
        objective=objective,
        paper_skims=paper_skims,
        frames=frames,
        routes=routes,
        evidence_records=evidence_records,
    )
    return evidence_records, contributions


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

    failed_units = tuple(
        unit for unit in evidence_items if unit.selection_status == "failed"
    )
    target_units = tuple(
        unit
        for unit in evidence_items
        if unit.selection_status != "failed"
        if _objective_evidence_matches_target_property(
            unit,
            target_axes=target_axes,
        )
    )
    if not target_units:
        return failed_units

    target_document_ids = {unit.document_id for unit in target_units}
    selected_ids = {unit.evidence_id for unit in (*failed_units, *target_units)}
    selected = [*failed_units, *target_units]
    for unit in evidence_items:
        if unit.evidence_id in selected_ids or unit.reported_result is not None:
            continue
        if unit.document_id in target_document_ids:
            selected.append(unit)
            selected_ids.add(unit.evidence_id)
    return tuple(selected)


def _objective_evidence_matches_target_property(
    unit: ExtractedEvidenceDraft,
    *,
    target_axes: tuple[str, ...],
) -> bool:
    if unit.reported_result is None:
        return False
    return property_matching.property_matches_target_axes(
        unit.reported_result.outcome,
        target_axes=target_axes,
    )


def _analysis_contributions(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    paper_skims: tuple[PaperSkim, ...],
    frames: tuple[PaperAnalysisFrame, ...],
    routes: tuple[EvidenceCandidate, ...],
    evidence_records: tuple[ObjectiveEvidence, ...],
) -> tuple[PaperContribution, ...]:
    paper_skims_by_document_id = {
        paper_skim.document_id: paper_skim for paper_skim in paper_skims
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

    contributions: list[PaperContribution] = []
    for frame in frames:
        excluded = frame.relevance == "irrelevant" or frame.paper_role == "irrelevant"
        document_evidence = tuple(evidence_by_document.get(frame.document_id, ()))
        routed_sources = routed_sources_by_document.get(frame.document_id, set())
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
            FindingSynthesisService.is_comparable_result_evidence(
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
            evidence_reason = frame.background or (
                "Paper is not relevant to this objective."
            )
        else:
            routed_source_count = len(routed_sources)
            extracted_source_count = len(extracted_sources)
            failed_source_count = len(failed_sources)
            if routed_source_count == 0:
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
        fallback_source_count = sum(
            disposition.disposition == "fallback_relevant"
            for disposition in frame.source_dispositions
        )
        paper_skim = paper_skims_by_document_id.get(frame.document_id)
        paper_skim_failure_count = sum(
            coverage.status is PaperSourceUnitCoverageStatus.EXTRACTION_FAILED
            for coverage in (
                paper_skim.source_unit_coverage if paper_skim is not None else ()
            )
        )
        warnings: list[str] = []
        if fallback_source_count:
            warnings.append(
                f"{fallback_source_count} Source unit(s) used conservative "
                "paper framing fallback."
            )
        if paper_skim_failure_count:
            warnings.append(
                f"{paper_skim_failure_count} PaperSkim Source unit(s) failed "
                "extraction before Objective analysis."
            )
        if failed_source_count:
            warnings.append(
                f"{failed_source_count} selected source(s) failed extraction."
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
                contribution_summary=frame.background,
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
                evidence_disposition_reason=evidence_reason,
            )
        )
    return tuple(contributions)


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
    for source_draft in drafts:
        try:
            draft = _canonical_objective_evidence_axes(
                source_draft,
                objective=objective,
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
        if draft.evidence_id in seen_evidence_ids:
            continue
        seen_evidence_ids.add(draft.evidence_id)
        evidence_role = _canonical_evidence_role(draft)
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
            selection_status=draft.selection_status,
            selection_reason=draft.selection_reason,
            changed_variables=draft.changed_variables,
            comparison=draft.comparison,
            reported_result=draft.reported_result,
            attribution_scope=draft.attribution_scope,
            scientific_context=draft.scientific_context,
            anchor_ids=draft.evidence_anchor_ids,
            resolution_status=(
                draft.resolution_status
                if draft.selection_status == "failed"
                else (
                    draft.resolution_status
                    if draft.resolution_status in {"resolved", "partial"}
                    else "partial"
                )
            ),
            failure_reason=draft.failure_reason,
            confidence=draft.confidence,
        )
        records.append(candidate)
    return tuple(records)


def _canonical_objective_evidence_axes(
    draft: ExtractedEvidenceDraft,
    *,
    objective: ResearchObjective,
) -> ExtractedEvidenceDraft:
    if draft.selection_status == "failed":
        return draft

    payload = draft.to_record()

    def canonical(value: Any, axes: tuple[str, ...]) -> tuple[str, str | None]:
        resolved = property_matching.resolve_objective_axis(value, axes)
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
                if property_matching.property_matches_target_axes(
                    source_outcome,
                    target_axes=(
                        axis,
                        *property_matching.broad_outcome_expansions(axis),
                    ),
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


def _canonical_evidence_source(
    draft: ExtractedEvidenceDraft,
    *,
    blocks_by_document_id: Mapping[str, list[Any]],
    tables_by_document_id: Mapping[str, list[Any]],
    figures_by_document_id: Mapping[str, list[Any]],
) -> dict[str, Any] | None:
    candidates = [
        *[dict(value) for value in draft.source_refs],
        {
            "source_kind": draft.source_kind,
            "source_ref": draft.source_ref,
        },
    ]
    related: list[dict[str, Any]] = []
    seen_locators: set[tuple[Any, ...]] = set()
    excerpts: list[str] = []
    primary: dict[str, Any] | None = None
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
        if located is None:
            continue
        if primary is None:
            primary = {
                "source_kind": located["source_kind"],
                "source_ref": source_ref,
                "page": located["page"],
            }
        excerpt = _text(candidate.get("source_excerpt"))
        if not excerpt and not excerpts:
            excerpt = located["source_excerpt"]
        if excerpt and excerpt not in excerpts:
            excerpts.append(excerpt)
    if primary is None or not excerpts:
        return None
    return {
        "source_kind": primary["source_kind"],
        "source_ref": primary["source_ref"],
        "source_excerpt": "\n".join(excerpts)[:12_000],
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
