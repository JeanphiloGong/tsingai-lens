"""Extract source-local facts for one confirmed ResearchObjective."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Callable, Mapping

from openai import APIConnectionError, APIStatusError

from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_routing import (
    EvidenceCandidate,
    order_routes_for_extraction,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from application.core.objectives.analysis.source_validation import (
    _objective_column_key,
    _objective_route_source_refs,
    _objective_row_matches_headers,
    _objective_table_matrix_rows,
    _objective_table_row_values,
    _split_property_unit,
    validate_source_fact,
)
from application.core.objectives.extraction import ObjectiveExtractor
from application.core.paper_facts.extraction import (
    PaperFactsExtractor,
    build_default_paper_facts_extractor,
)
from domain.core import (
    ObjectiveEvidenceComparison,
    ObjectiveEvidenceContext,
    ObjectiveEvidenceResult,
    ObjectiveEvidenceVariable,
    ResearchObjective,
    normalize_objective_confidence,
    normalize_objective_terms,
)
from domain.source import SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_ROUTE_PROMPT_TEXT_CHARS = 320
_ROUTE_PROMPT_HEADER_LIMIT = 8
_OBJECTIVE_STATE_ITEM_LIMIT = 12
_OBJECTIVE_STATE_TEXT_CHARS = 220
_OBJECTIVE_EVIDENCE_TEXT_CHARS = 6000
_OBJECTIVE_EVIDENCE_PROMPT_TEXT_CHARS = 1800
_OBJECTIVE_EVIDENCE_PROMPT_TABLE_ROWS = 8
_OBJECTIVE_EVIDENCE_PROMPT_TABLE_CELLS = 80
_OBJECTIVE_NON_RESULT_VALUE_COLUMN_TERMS = (
    "standard deviation",
    "std",
    "sd",
    "variance",
    "error bar",
    "condition number",
    "sample number",
)
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _provider_is_temporarily_unavailable(error: Exception) -> bool:
    if isinstance(error, APIConnectionError):
        return True
    if not isinstance(error, APIStatusError):
        return False
    status_code = int(error.status_code)
    return status_code in {408, 409, 429} or status_code >= 500


@dataclass(frozen=True)
class ExtractedEvidenceDraft:
    """Transient structured extraction before Source text is attached."""

    evidence_id: str
    objective_id: str
    document_id: str
    source_kind: str | None
    source_ref: str | None
    evidence_role: str | None
    selection_reason: str | None
    selection_status: str
    changed_variables: tuple[ObjectiveEvidenceVariable, ...]
    comparison: ObjectiveEvidenceComparison | None
    reported_result: ObjectiveEvidenceResult | None
    attribution_scope: str
    scientific_context: ObjectiveEvidenceContext
    source_refs: tuple[dict[str, Any], ...]
    evidence_anchor_ids: tuple[str, ...]
    resolution_status: str
    failure_reason: str | None
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExtractedEvidenceDraft":
        source_refs = _mapping_tuple(payload.get("source_refs"))
        first_source_ref = source_refs[0] if source_refs else {}
        objective_id = _text(payload.get("objective_id"))
        document_id = _text(payload.get("document_id"))
        source_kind = _optional_text(
            payload.get("source_kind") or first_source_ref.get("source_kind")
        )
        source_ref = _optional_text(
            payload.get("source_ref") or first_source_ref.get("source_ref")
        )
        evidence_role = _optional_text(
            payload.get("evidence_role") or first_source_ref.get("evidence_role")
        )
        reported_result_payload = payload.get("reported_result")
        reported_result = (
            ObjectiveEvidenceResult.from_mapping(reported_result_payload)
            if isinstance(reported_result_payload, Mapping)
            else None
        )
        evidence_id = _optional_text(payload.get("evidence_id"))
        if evidence_id is None:
            identity = json.dumps(
                [
                    objective_id,
                    document_id,
                    evidence_role,
                    source_refs,
                    payload.get("changed_variables"),
                    payload.get("comparison"),
                    payload.get("reported_result"),
                ],
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            evidence_id = f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        return cls(
            evidence_id=evidence_id,
            objective_id=objective_id,
            document_id=document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            evidence_role=evidence_role,
            selection_reason=_optional_text(
                payload.get("selection_reason")
                or first_source_ref.get("selection_reason")
            ),
            selection_status=_text(payload.get("selection_status")) or "extracted",
            changed_variables=tuple(
                ObjectiveEvidenceVariable.from_mapping(item)
                for item in payload.get("changed_variables", ())
                if isinstance(item, Mapping)
            ),
            comparison=(
                ObjectiveEvidenceComparison.from_mapping(payload["comparison"])
                if isinstance(payload.get("comparison"), Mapping)
                else None
            ),
            reported_result=reported_result,
            attribution_scope=_text(payload.get("attribution_scope"))
            or "not_attributable",
            scientific_context=(
                ObjectiveEvidenceContext.from_mapping(payload["scientific_context"])
                if isinstance(payload.get("scientific_context"), Mapping)
                else ObjectiveEvidenceContext()
            ),
            source_refs=source_refs,
            evidence_anchor_ids=normalize_objective_terms(
                payload.get("evidence_anchor_ids")
            ),
            resolution_status=_text(payload.get("resolution_status")) or "unknown",
            failure_reason=_optional_text(payload.get("failure_reason")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "evidence_role": self.evidence_role,
            "selection_reason": self.selection_reason,
            "selection_status": self.selection_status,
            "changed_variables": [item.to_record() for item in self.changed_variables],
            "comparison": self.comparison.to_record() if self.comparison else None,
            "reported_result": (
                self.reported_result.to_record() if self.reported_result else None
            ),
            "attribution_scope": self.attribution_scope,
            "scientific_context": self.scientific_context.to_record(),
            "source_refs": [dict(item) for item in self.source_refs],
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "resolution_status": self.resolution_status,
            "failure_reason": self.failure_reason,
            "confidence": self.confidence,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def extract_source_facts(
    *,
    collection_id: str,
    extractor: ObjectiveExtractor,
    paper_facts_extractor: PaperFactsExtractor | None = None,
    objectives: tuple[ResearchObjective, ...],
    objective_paper_frames: tuple[PaperAnalysisFrame, ...],
    objective_evidence_routes: tuple[EvidenceCandidate, ...],
    blocks_by_document_id: dict[str, list[Any]],
    tables_by_document_id: dict[str, list[Any]],
    document_trees_by_document_id: dict[str, SourceDocumentTree],
    table_cells_by_document_id: dict[str, list[Any]] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[ExtractedEvidenceDraft, ...]:
    objective_by_id = {objective.objective_id: objective for objective in objectives}
    frame_by_key = {
        (frame.objective_id, frame.document_id): frame
        for frame in objective_paper_frames
    }
    extractable_routes = order_routes_for_extraction(
        tuple(
            route
            for route in objective_evidence_routes
            if route.extractable and route.role != "low_value_or_irrelevant"
        ),
        document_trees_by_document_id=document_trees_by_document_id,
    )
    logger.info(
        "Research objective evidence extraction started collection_id=%s route_count=%s extractable_route_count=%s",
        collection_id,
        len(objective_evidence_routes),
        len(extractable_routes),
    )
    units: list[ExtractedEvidenceDraft] = []
    seen: set[str] = set()
    document_state_units: dict[tuple[str, str], list[ExtractedEvidenceDraft]] = {}
    llm_evidence_unavailable: dict[tuple[str, str], Exception] = {}
    llm_table_repair_unavailable: dict[tuple[str, str], Exception] = {}
    resolved_paper_facts_extractor = paper_facts_extractor
    document_metadata = _progress_document_metadata(
        document_trees_by_document_id=document_trees_by_document_id,
    )
    for route_position, route in enumerate(extractable_routes, start=1):
        document_key = (route.objective_id, route.document_id)
        route_document_metadata = document_metadata.get(route.document_id, {})
        _notify_progress(
            progress_callback,
            phase="objective_evidence_extraction_started",
            current=route_position,
            total=len(extractable_routes),
            unit="selections",
            message="Extracting objective evidence from selected sources.",
            active_document_id=route.document_id,
            active_document_title=route_document_metadata.get("title"),
            active_source_filename=route_document_metadata.get("source_filename"),
            active_objective_id=route.objective_id,
        )
        objective = objective_by_id.get(route.objective_id)
        if objective is None:
            logger.info(
                "Research objective evidence extraction route skipped collection_id=%s source_ref=%s reason=missing_objective route_position=%s route_count=%s",
                collection_id,
                route.source_ref,
                route_position,
                len(extractable_routes),
            )
            continue
        source = _build_objective_route_source_payload(
            route=route,
            blocks=blocks_by_document_id.get(route.document_id, []),
            tables=tables_by_document_id.get(route.document_id, []),
            document_tree=document_trees_by_document_id.get(route.document_id),
            table_cells=(
                table_cells_by_document_id.get(route.document_id, [])
                if table_cells_by_document_id is not None
                else []
            ),
        )
        if not source:
            raise RuntimeError(
                "selected Evidence Source is missing: "
                f"objective_id={route.objective_id} "
                f"document_id={route.document_id} "
                f"source_kind={route.source_kind} "
                f"source_ref={route.source_ref}"
            )
        objective_context = objective_by_id.get(route.objective_id)
        tree_position = _route_tree_position(
            _source_candidate_from_route(
                route=route,
                source=source,
                document_tree=document_trees_by_document_id.get(route.document_id),
            )
        )
        prior_document_state = _objective_document_state_payload(
            document_state_units.get((route.objective_id, route.document_id), [])
        )
        payload = {
            "collection_id": collection_id,
            "objective": _route_prompt_objective_record(objective),
            "paper_frame": _route_prompt_paper_frame_record(
                frame_by_key[(route.objective_id, route.document_id)]
            )
            if (route.objective_id, route.document_id) in frame_by_key
            else {},
            "evidence_route": _objective_evidence_prompt_route_record(route),
            "tree_position": tree_position,
            "document_state": prior_document_state,
            "source": _objective_evidence_prompt_source(source),
        }
        if (
            resolved_paper_facts_extractor is None
            and _objective_table_source_needs_llm_structural_repair(
                route=route,
                source=source,
            )
        ):
            resolved_paper_facts_extractor = build_default_paper_facts_extractor()
        source, table_repair_error = _repair_objective_table_source_if_needed(
            collection_id=collection_id,
            route=route,
            source=source,
            paper_facts_extractor=resolved_paper_facts_extractor,
            unavailable_error=llm_table_repair_unavailable.get(document_key),
        )
        if table_repair_error is not None and _provider_is_temporarily_unavailable(
            table_repair_error
        ):
            llm_table_repair_unavailable.setdefault(
                document_key,
                table_repair_error,
            )
        payload["source"] = _objective_evidence_prompt_source(source)
        route_unit_start = len(units)
        if (
            table_repair_error is not None
            and _objective_table_source_needs_llm_structural_repair(
                route=route,
                source=source,
            )
        ):
            failed_unit = _failed_objective_evidence_draft(
                route=route,
                error=table_repair_error,
            )
            if failed_unit.evidence_id not in seen:
                seen.add(failed_unit.evidence_id)
                units.append(failed_unit)
            continue
        route_records = _objective_table_matrix_evidence_records(
            route=route,
            source=source,
            objective_context=objective_context,
        )
        needs_structural_repair = _objective_table_source_needs_llm_structural_repair(
            route=route,
            source=source,
        ) and not (
            source.get("table_matrix_structural_repair_applied") and route_records
        )
        needs_model_extraction = (
            not route_records or needs_structural_repair
        ) and not _objective_table_route_should_skip_llm_fallback(route)
        if needs_model_extraction:
            extraction_error = llm_evidence_unavailable.get(document_key)
            if extraction_error is None:
                try:
                    parsed = extractor.extract_objective_evidence(payload)
                    llm_route_records = tuple(
                        record
                        for item in parsed.extractions
                        for record in validate_source_fact(
                            route=route,
                            source=source,
                            objective_context=objective_context,
                            extracted_record=item.model_dump(),
                        )
                    )
                except Exception as exc:
                    extraction_error = exc
                    provider_unavailable = _provider_is_temporarily_unavailable(exc)
                    if provider_unavailable:
                        llm_evidence_unavailable[document_key] = exc
                    logger.exception(
                        "Research objective evidence extraction route failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s completed_routes=%s remaining_routes=%s provider_unavailable=%s",
                        collection_id,
                        route.source_ref,
                        route.objective_id,
                        route.document_id,
                        route.source_kind,
                        route.source_ref,
                        route_position,
                        len(extractable_routes),
                        route_position - 1,
                        max(len(extractable_routes) - route_position, 0),
                        provider_unavailable,
                    )
                else:
                    route_records = _objective_merge_table_repair_records(
                        deterministic_records=route_records,
                        llm_records=llm_route_records,
                    )
            if extraction_error is not None:
                failed_unit = _failed_objective_evidence_draft(
                    route=route,
                    error=extraction_error,
                )
                if failed_unit.evidence_id not in seen:
                    seen.add(failed_unit.evidence_id)
                    units.append(failed_unit)
                if not route_records:
                    continue
        for record in route_records:
            unit = ExtractedEvidenceDraft.from_mapping(record)
            if not _objective_evidence_has_payload(unit):
                continue
            if unit.evidence_id in seen:
                continue
            seen.add(unit.evidence_id)
            units.append(unit)
            document_state_units.setdefault(
                (unit.objective_id, unit.document_id),
                [],
            ).append(unit)
        logger.info(
            "Research objective evidence extraction route finished collection_id=%s source_ref=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s extractions=%s completed_routes=%s remaining_routes=%s",
            collection_id,
            route.source_ref,
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
            route_position,
            len(extractable_routes),
            len(units) - route_unit_start,
            route_position,
            max(len(extractable_routes) - route_position, 0),
        )
    for unit in _build_objective_method_family_test_condition_units(
        objectives=objectives,
        objective_paper_frames=objective_paper_frames,
        blocks_by_document_id=blocks_by_document_id,
    ):
        if not _objective_evidence_has_payload(unit):
            continue
        if unit.evidence_id in seen:
            continue
        seen.add(unit.evidence_id)
        units.append(unit)
    logger.info(
        "Research objective evidence extraction finished collection_id=%s objective_extractions=%s",
        collection_id,
        len(units),
    )
    return tuple(units)


def _notify_progress(
    progress_callback: ProgressCallback | None,
    **progress_detail: Any,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(progress_detail)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Research objective progress callback failed phase=%s",
            progress_detail.get("phase"),
        )


def _progress_document_metadata(
    *,
    document_trees_by_document_id: dict[str, SourceDocumentTree],
) -> dict[str, dict[str, str | None]]:
    return {
        document_id: {
            "title": str(tree.root.title or "").strip() or None,
            "source_filename": None,
        }
        for document_id, tree in document_trees_by_document_id.items()
    }


def _route_prompt_objective_record(
    objective: ResearchObjective,
) -> dict[str, Any]:
    return {
        "objective_id": objective.objective_id,
        "question": objective.question,
        "material_scope": list(objective.material_scope),
        "variables": list(objective.variables),
        "outcomes": list(objective.outcomes),
        "mechanisms": list(objective.mechanisms),
        "constraints": list(objective.constraints),
        "requested_comparator": objective.requested_comparator,
    }


def _route_prompt_paper_frame_record(
    frame: PaperAnalysisFrame,
) -> dict[str, Any]:
    return {
        "document_id": frame.document_id,
        "objective_id": frame.objective_id,
        "relevance": frame.relevance,
        "paper_role": frame.paper_role,
        "material_match": list(frame.material_match),
        "changed_variables": list(frame.changed_variables),
        "measured_property_scope": list(frame.measured_property_scope),
        "test_environment_scope": list(frame.test_environment_scope),
    }


def _objective_header_matches_any_axis(
    header: str,
    axes: tuple[str, ...],
) -> bool:
    property_name, _unit = _split_property_unit(header)
    normalized_property = property_matching.normalize_property_label(property_name)
    if normalized_property and any(
        property_matching.axis_values_match(normalized_property, axis) for axis in axes
    ):
        return True
    if any(property_matching.axis_values_match(header, axis) for axis in axes):
        return True
    header_key = _objective_column_key(header)
    if not header_key:
        return False
    for axis in axes:
        axis_key = _objective_column_key(axis)
        if not axis_key:
            continue
        if axis_key in header_key or header_key in axis_key:
            return True
    return False


def _failed_objective_evidence_draft(
    *,
    route: EvidenceCandidate,
    error: Exception,
) -> ExtractedEvidenceDraft:
    identity = "|".join(
        (
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
            "failed",
        )
    )
    reason = f"{error.__class__.__name__}: {str(error) or 'extraction failed'}"
    return ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": (
                f"oev_failed_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
            ),
            "objective_id": route.objective_id,
            "document_id": route.document_id,
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "evidence_role": "irrelevant",
            "selection_status": "failed",
            "selection_reason": route.reason,
            "attribution_scope": "not_attributable",
            "source_refs": [
                {
                    "source_kind": route.source_kind,
                    "source_ref": route.source_ref,
                }
            ],
            "resolution_status": "unknown",
            "failure_reason": reason[:1000],
            "confidence": 0.0,
        }
    )


def _objective_table_route_should_skip_llm_fallback(
    route: EvidenceCandidate,
) -> bool:
    return route.source_kind == "table"


def _repair_objective_table_source_if_needed(
    *,
    collection_id: str,
    route: EvidenceCandidate,
    source: dict[str, Any],
    paper_facts_extractor: PaperFactsExtractor | None,
    unavailable_error: Exception | None = None,
) -> tuple[dict[str, Any], Exception | None]:
    if not _objective_table_source_needs_llm_structural_repair(
        route=route,
        source=source,
    ):
        return source, None
    if unavailable_error is not None:
        return source, unavailable_error
    repair_payload = _build_objective_table_matrix_repair_payload(
        route=route,
        source=source,
    )
    try:
        if paper_facts_extractor is None:
            raise RuntimeError("table repair extractor is unavailable")
        parsed = paper_facts_extractor.repair_table_matrix(repair_payload)
    except Exception as exc:
        logger.exception(
            "Research objective table matrix repair failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_ref=%s",
            collection_id,
            route.source_ref,
            route.objective_id,
            route.document_id,
            route.source_ref,
        )
        return source, exc
    repaired_matrix = _validated_objective_repaired_table_matrix(
        source=source,
        repaired_table_matrix=getattr(parsed, "repaired_table_matrix", None),
    )
    if not repaired_matrix:
        return source, ValueError("table matrix repair returned no usable matrix")
    original_matrix = _normalized_objective_table_matrix(source.get("table_matrix"))
    repaired_matrix, residual_repairs = (
        _cleanup_objective_repaired_table_matrix_residual_fragments(
            original_matrix=original_matrix,
            repaired_matrix=repaired_matrix,
            column_headers=source.get("column_headers", ()),
        )
    )
    if (
        repaired_matrix == original_matrix
        and _objective_table_matrix_has_structural_fragments(original_matrix)
    ):
        return source, ValueError(
            "table matrix repair left the fragmented matrix unchanged"
        )
    if _objective_table_matrix_has_structural_fragments(repaired_matrix):
        return source, ValueError(
            "table matrix repair returned a structurally fragmented matrix"
        )
    repaired_source = dict(source)
    repaired_source["raw_table_matrix"] = source.get("table_matrix", [])
    repaired_source["table_matrix"] = repaired_matrix
    repaired_source["table_matrix_structural_repair_applied"] = True
    repairs = getattr(parsed, "repairs", None)
    repair_records = []
    if repairs:
        repair_records.extend(
            repair_item.model_dump()
            if hasattr(repair_item, "model_dump")
            else repair_item
            for repair_item in repairs
        )
    repair_records.extend(residual_repairs)
    if repair_records:
        repaired_source["table_matrix_repairs"] = repair_records
    warnings = getattr(parsed, "warnings", None)
    if warnings:
        repaired_source["table_matrix_repair_warnings"] = [
            str(warning) for warning in warnings if str(warning).strip()
        ]
    return repaired_source, None


def _build_objective_table_matrix_repair_payload(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
) -> dict[str, Any]:
    compact_source = {
        "source_kind": source.get("source_kind"),
        "source_ref": source.get("source_ref"),
        "document_id": source.get("document_id"),
        "page": source.get("page"),
        "caption_text": source.get("caption_text"),
        "heading_path": source.get("heading_path"),
        "column_headers": [
            str(value)
            for value in source.get("column_headers", ())
            if str(value).strip()
        ],
        "table_matrix": _normalized_objective_table_matrix(source.get("table_matrix")),
        "table_cells": _compact_objective_table_cells_for_repair(source),
    }
    return {
        "table_role": route.role,
        "repair_focus": [
            "repair parser-split cells",
            "preserve table width",
            "preserve numeric result cells exactly",
        ],
        "source": {
            key: value
            for key, value in compact_source.items()
            if value not in (None, "", [], {})
        },
    }


def _compact_objective_table_cells_for_repair(
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    cells = source.get("table_cells")
    if not isinstance(cells, list):
        return []
    fragmented_columns = {
        cell.get("col_index")
        for cell in cells
        if isinstance(cell, dict)
        and _objective_cell_text_looks_structurally_fragmented(
            str(cell.get("cell_text") or "")
        )
    }
    if not fragmented_columns:
        return []
    compact_cells: list[dict[str, Any]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        col_index = cell.get("col_index")
        if col_index not in fragmented_columns and col_index != 0:
            continue
        compact_cells.append(
            {
                "row_index": cell.get("row_index"),
                "col_index": col_index,
                "header_path": cell.get("header_path"),
                "cell_text": str(cell.get("cell_text") or ""),
            }
        )
    return compact_cells


def _validated_objective_repaired_table_matrix(
    *,
    source: dict[str, Any],
    repaired_table_matrix: Any,
) -> list[list[str]]:
    if not isinstance(repaired_table_matrix, list) or not repaired_table_matrix:
        return []
    headers = [
        str(header).strip()
        for header in source.get("column_headers", ())
        if str(header).strip()
    ]
    expected_width = len(headers)
    repaired_rows: list[list[str]] = []
    for row in repaired_table_matrix:
        if not isinstance(row, (list, tuple)):
            return []
        repaired_row = [str(cell).strip() for cell in row]
        if expected_width and len(repaired_row) != expected_width:
            return []
        repaired_rows.append(repaired_row)
    if expected_width and not _objective_row_matches_headers(
        tuple(repaired_rows[0]),
        tuple(headers),
    ):
        repaired_rows.insert(0, headers)
    return repaired_rows


def _normalized_objective_table_matrix(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [
        [str(cell).strip() for cell in row]
        for row in value
        if isinstance(row, (list, tuple))
    ]


def _cleanup_objective_repaired_table_matrix_residual_fragments(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
    column_headers: Any,
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    if not original_matrix or not repaired_matrix:
        return repaired_matrix, []
    headers = [str(value).strip() for value in column_headers or ()]
    cleaned_matrix: list[list[str]] = []
    repairs: list[dict[str, Any]] = []
    for row_index, repaired_row in enumerate(repaired_matrix):
        original_row = (
            original_matrix[row_index] if row_index < len(original_matrix) else []
        )
        cleaned_row: list[str] = []
        for col_index, repaired_cell in enumerate(repaired_row):
            original_cell = (
                original_row[col_index] if col_index < len(original_row) else ""
            )
            cleaned_cell = _cleanup_objective_repaired_cell_residual_prefix(
                original_cell=original_cell,
                repaired_cell=repaired_cell,
            )
            cleaned_row.append(cleaned_cell)
            if cleaned_cell != repaired_cell:
                repairs.append(
                    {
                        "row_index": row_index,
                        "column": (
                            headers[col_index]
                            if col_index < len(headers)
                            else str(col_index)
                        ),
                        "before": repaired_cell,
                        "after": cleaned_cell,
                        "reason": (
                            "Removed a leading closing-fragment prefix that "
                            "belonged to the previous parser-split row label."
                        ),
                    }
                )
        cleaned_matrix.append(cleaned_row)
    return cleaned_matrix, repairs


def _cleanup_objective_repaired_cell_residual_prefix(
    *,
    original_cell: str,
    repaired_cell: str,
) -> str:
    original = " ".join(str(original_cell or "").split())
    repaired = " ".join(str(repaired_cell or "").split())
    if not original or not repaired:
        return repaired_cell
    if not _objective_cell_text_looks_structurally_fragmented(original):
        return repaired_cell
    match = re.match(r"^([^\s()[\]{}|]{1,32}\))\s+(.+)$", original)
    if match is None:
        return repaired_cell
    prefix = f"{match.group(1)} "
    original_remainder = match.group(2).strip()
    if not _objective_cell_text_looks_structurally_fragmented(original_remainder):
        return repaired_cell
    if not repaired.startswith(prefix):
        return repaired_cell
    candidate = repaired[len(prefix) :].strip()
    if not candidate:
        return repaired_cell
    if _objective_cell_text_looks_structurally_fragmented(candidate):
        return repaired_cell
    return candidate


def _objective_table_matrix_has_structural_fragments(
    table_matrix: list[list[str]],
) -> bool:
    return any(
        _objective_cell_text_looks_structurally_fragmented(cell)
        for row in table_matrix
        for cell in row
    )


def _objective_table_source_needs_llm_structural_repair(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
) -> bool:
    if route.source_kind != "table":
        return False
    if route.role not in {"current_experimental_evidence", "process_or_treatment"}:
        return False
    matrix = source.get("table_matrix")
    if isinstance(matrix, list) and _objective_table_matrix_has_structural_fragments(
        _normalized_objective_table_matrix(matrix)
    ):
        return True
    cells = source.get("table_cells")
    if not isinstance(cells, list):
        return False
    return any(
        _objective_cell_text_looks_structurally_fragmented(
            str(cell.get("cell_text") or "")
        )
        for cell in cells
        if isinstance(cell, dict)
    )


def _objective_cell_text_looks_structurally_fragmented(text: str) -> bool:
    value = " ".join(str(text or "").split())
    if not value:
        return False
    if value.count("(") != value.count(")"):
        return True
    if value.count("[") != value.count("]"):
        return True
    if value.endswith(("/", "(", "[", "{")):
        return True
    if value.startswith((")", "]", "}")):
        return True
    return False


def _objective_merge_table_repair_records(
    *,
    deterministic_records: tuple[dict[str, Any], ...],
    llm_records: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return deterministic_records or llm_records


def _build_objective_method_family_test_condition_units(
    *,
    objectives: tuple[ResearchObjective, ...],
    objective_paper_frames: tuple[PaperAnalysisFrame, ...],
    blocks_by_document_id: dict[str, list[Any]],
) -> tuple[ExtractedEvidenceDraft, ...]:
    context_by_objective_id = {context.objective_id: context for context in objectives}
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for frame in objective_paper_frames:
        if frame.relevance == "irrelevant":
            continue
        objective_context = context_by_objective_id.get(frame.objective_id)
        families = property_matching.objective_method_families(objective_context)
        if not families:
            continue
        blocks = blocks_by_document_id.get(frame.document_id, [])
        for family in families:
            key = (frame.objective_id, frame.document_id, family)
            if key in seen:
                continue
            candidate = _objective_method_family_candidate(
                family=family,
                blocks=blocks,
            )
            if candidate is None:
                continue
            block, quote, payload = candidate
            seen.add(key)
            source_ref = str(getattr(block, "block_id", "") or "")
            source_ref_payload = {
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "test_condition",
                "page": getattr(block, "page", None),
            }
            records.append(
                {
                    "evidence_id": _objective_method_family_unit_id(
                        objective_id=frame.objective_id,
                        document_id=frame.document_id,
                        family=family,
                    ),
                    "objective_id": frame.objective_id,
                    "document_id": frame.document_id,
                    "evidence_role": "condition_context",
                    "selection_reason": quote,
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                    "scientific_context": {
                        "material": [],
                        "sample": [],
                        "process": [],
                        "test": [
                            {"name": "method_family", "value": family},
                            *(
                                {"name": key, "value": value}
                                for key, value in payload.items()
                            ),
                        ],
                    },
                    "source_refs": (
                        {
                            key: value
                            for key, value in source_ref_payload.items()
                            if value not in (None, "", [], {})
                        },
                    ),
                    "resolution_status": "resolved",
                    "confidence": 0.86,
                }
            )
    return tuple(ExtractedEvidenceDraft.from_mapping(record) for record in records)


def _objective_method_family_candidate(
    *,
    family: str,
    blocks: list[Any],
) -> tuple[Any, str, dict[str, Any]] | None:
    best: tuple[int, int, Any, str, dict[str, Any]] | None = None
    for position, block in enumerate(blocks):
        text = str(getattr(block, "text", "") or "").strip()
        if not text:
            continue
        combined_text = " ".join(
            part
            for part in (
                str(getattr(block, "heading_path", "") or "").strip(),
                text,
            )
            if part
        )
        score = _score_objective_method_family_window(
            family=family,
            text=combined_text,
        )
        if score <= 0:
            continue
        quote = _select_objective_method_family_quote(
            text,
            family=family,
        )
        if not quote:
            continue
        payload = _build_objective_method_family_condition_payload(
            family=family,
            text=text,
        )
        if not payload:
            continue
        candidate = (score, -position, block, quote, payload)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    _, _, block, quote, payload = best
    return block, quote, payload


def _score_objective_method_family_window(
    *,
    family: str,
    text: str,
) -> int:
    lowered = text.casefold()
    if family == "tensile_mechanics":
        terms = (
            ("tensile", 4),
            ("stress-strain", 3),
            ("yield strength", 2),
            ("ultimate tensile", 2),
            ("astm e8", 4),
            ("instron", 4),
            ("strain rate", 2),
        )
    elif family == "microhardness":
        terms = (
            ("microhardness", 4),
            ("vickers", 4),
            ("hardness", 2),
            ("wilson", 3),
            ("holding time", 2),
            ("readings", 2),
        )
    elif family == "density_porosity_microstructure":
        terms = (
            ("sem", 3),
            ("imagej", 4),
            ("porosity", 3),
            ("relative density", 3),
            ("microstructure", 2),
            ("magnification", 2),
            ("horizontal", 1),
            ("vertical", 1),
        )
    else:
        return 0
    return sum(weight for term, weight in terms if term in lowered)


def _build_objective_method_family_condition_payload(
    *,
    family: str,
    text: str,
) -> dict[str, Any]:
    if family == "tensile_mechanics":
        payload: dict[str, Any] = {
            "method": "tensile testing",
            "methods": ["tensile testing"],
            "test_method": "tensile testing",
            "standard": _extract_first_pattern(
                text,
                r"\bASTM\s*E8M?\b",
            ),
            "instrument": _extract_first_pattern(
                text,
                r"\bINSTRON\b[^.;,\n]*",
            ),
            "strain_rate_s-1": _extract_first_pattern(
                text,
                r"\b\d+(?:\.\d+)?\s*mm\s*/\s*min\b",
            ),
            "specimen_geometry": (
                "Fig. 2" if re.search(r"\bFig\.\s*2\b", text, re.IGNORECASE) else None
            ),
            "sample_orientation": _extract_orientation_phrase(text),
            "details": _compact_condition_details(text),
        }
    elif family == "microhardness":
        payload = {
            "method": "Vickers microhardness",
            "methods": ["Vickers microhardness"],
            "test_method": "Vickers microhardness",
            "instrument": _extract_first_pattern(
                text,
                r"\b(?:Vickers\s+)?microhardness[^.;\n]*",
            ),
            "load": _extract_first_pattern(text, r"\b\d+(?:\.\d+)?\s*N\b"),
            "holding_time": _extract_first_pattern(
                text,
                r"\b\d+(?:\.\d+)?\s*s\b",
            ),
            "readings_per_sample": _extract_first_pattern(
                text,
                r"\b\d+\s+(?:readings|measurements)\b[^.;\n]*",
            ),
            "sample_orientation": _extract_orientation_phrase(text),
            "details": _compact_condition_details(text),
        }
    else:
        payload = {
            "method": "SEM / ImageJ",
            "methods": _dedupe_preserving_order(
                [
                    method
                    for method in ("SEM", "ImageJ")
                    if method.casefold() in text.casefold()
                ]
            )
            or ["SEM / ImageJ"],
            "test_method": "SEM / ImageJ",
            "instrument": _extract_first_pattern(
                text,
                r"\bFEI[-\s]INSPECT\s*50\s*SEM\b",
            )
            or ("SEM" if re.search(r"\bSEM\b", text, re.IGNORECASE) else None),
            "section_orientation": _extract_section_orientation_phrase(text),
            "surface_state": _extract_surface_preparation_phrase(text),
            "magnification": _extract_first_pattern(
                text,
                r"\b\d+(?:\.\d+)?\s*[xX]\s*(?:-|to)\s*\d+(?:\.\d+)?\s*[xX]\b",
            ),
            "details": _compact_condition_details(text),
        }
    return {
        key: value for key, value in payload.items() if value not in (None, "", [], {})
    }


def _select_objective_method_family_quote(
    text: str,
    *,
    family: str,
) -> str | None:
    terms = {
        "tensile_mechanics": ("tensile", "astm", "instron", "stress-strain"),
        "microhardness": ("microhardness", "vickers", "hardness", "wilson"),
        "density_porosity_microstructure": (
            "sem",
            "imagej",
            "porosity",
            "relative density",
            "microstructure",
        ),
    }.get(family, ())
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+", normalized_text):
        if any(term in sentence.casefold() for term in terms):
            return sentence[:900].strip()
    return normalized_text[:900].strip()


def _extract_first_pattern(
    text: str,
    pattern: str,
) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip()


def _extract_orientation_phrase(text: str) -> str | None:
    lowered = text.casefold()
    if "horizontally" in lowered and "substrate" in lowered:
        return "all blocks built horizontally on substrate"
    if "horizontal" in lowered and "vertical" in lowered:
        return "horizontal and vertical sections"
    if "horizontal" in lowered:
        return "horizontal"
    if "vertical" in lowered:
        return "vertical"
    return None


def _extract_section_orientation_phrase(text: str) -> str | None:
    lowered = text.casefold()
    if "horizontal" in lowered and "vertical" in lowered:
        return "horizontal and vertical sections"
    return _extract_orientation_phrase(text)


def _extract_surface_preparation_phrase(text: str) -> str | None:
    parts = []
    grit = _extract_first_pattern(
        text,
        r"\b\d+\s*[-]\s*\d+\s*grit\b",
    )
    if grit:
        parts.append(grit)
    silica = _extract_first_pattern(
        text,
        r"\bcolloidal\s+silica\b[^.;\n]*",
    )
    if silica:
        parts.append(silica)
    return "; ".join(parts) if parts else None


def _compact_condition_details(text: str) -> str | None:
    normalized = " ".join(str(text or "").split())
    return normalized[:1000].strip() or None


def _objective_method_family_unit_id(
    *,
    objective_id: str,
    document_id: str,
    family: str,
) -> str:
    seed = "|".join(("method_family", objective_id, document_id, family))
    return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def _objective_numeric_match_tokens(value: Any) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _NUMBER_PATTERN.finditer(str(value or "").replace(",", "")):
        number_text = match.group(0)
        number = _coerce_number(number_text)
        if number is None:
            continue
        if number.is_integer():
            tokens.append(str(int(number)))
        else:
            tokens.append(("%f" % number).rstrip("0").rstrip("."))
    return tuple(tokens)


def _build_objective_route_source_payload(
    *,
    route: EvidenceCandidate,
    blocks: list[Any],
    tables: list[Any],
    document_tree: SourceDocumentTree | None = None,
    table_cells: list[Any] | None = None,
) -> dict[str, Any]:
    if route.source_kind == "table":
        table = next(
            (
                candidate
                for candidate in tables
                if str(getattr(candidate, "table_id", "") or "") == route.source_ref
            ),
            None,
        )
        if table is None:
            return {}
        cells = tuple(
            cell
            for cell in table_cells or []
            if str(getattr(cell, "table_id", "") or "") == route.source_ref
        )
        return {
            "source_kind": "table",
            "source_ref": route.source_ref,
            "document_id": route.document_id,
            "page": getattr(table, "page", None),
            "caption_text": getattr(table, "caption_text", None),
            "heading_path": getattr(table, "heading_path", None),
            "column_headers": [
                str(value) for value in getattr(table, "column_headers", ()) or ()
            ],
            "table_matrix": [
                [str(cell) for cell in row]
                for row in getattr(table, "table_matrix", ()) or ()
                if isinstance(row, (list, tuple))
            ],
            "table_cells": [
                {
                    "row_index": getattr(cell, "row_index", None),
                    "col_index": getattr(cell, "col_index", None),
                    "header_path": getattr(cell, "header_path", None),
                    "cell_text": str(getattr(cell, "cell_text", "") or ""),
                }
                for cell in sorted(
                    cells,
                    key=lambda item: (
                        getattr(item, "row_index", 0),
                        getattr(item, "col_index", 0),
                    ),
                )
            ],
        }
    if route.source_kind == "text_window":
        source_block_id = _route_text_block_id(
            route=route,
            document_tree=document_tree,
        )
        block = next(
            (
                candidate
                for candidate in blocks
                if str(getattr(candidate, "block_id", "") or "") == source_block_id
            ),
            None,
        )
        if block is None:
            return _build_objective_tree_text_source_payload(
                route=route,
                document_tree=document_tree,
            )
        text = str(getattr(block, "text", "") or "").strip()
        return {
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "document_id": route.document_id,
            "page": getattr(block, "page", None),
            "block_type": getattr(block, "block_type", None),
            "heading_path": getattr(block, "heading_path", None),
            "text": text[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
        }
    return {}


def _route_text_block_id(
    *,
    route: EvidenceCandidate,
    document_tree: SourceDocumentTree | None,
) -> str:
    if document_tree is None:
        return route.source_ref
    node = _tree_node_for_route_source(
        document_tree=document_tree,
        source_ref_kind="block",
        source_ref_id=route.source_ref,
    )
    if node is None:
        return route.source_ref
    source_ref_id = str(getattr(node, "source_ref_id", "") or "").strip()
    return source_ref_id or route.source_ref


def _build_objective_tree_text_source_payload(
    *,
    route: EvidenceCandidate,
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    if document_tree is None:
        return {}
    node = _tree_node_for_route_source(
        document_tree=document_tree,
        source_ref_kind="block",
        source_ref_id=route.source_ref,
    )
    if node is None or _tree_node_in_reference_branch(document_tree, node):
        return {}
    text = str(getattr(node, "text", "") or "").strip()
    if not text:
        return {}
    section_path = _tree_node_section_path(
        document_tree=document_tree,
        node=node,
    )
    return {
        "source_kind": "text_window",
        "source_ref": route.source_ref,
        "document_id": route.document_id,
        "page": getattr(node, "page_start", None),
        "block_type": _route_text_node_block_type(node),
        "heading_path": " > ".join(section_path) if section_path else None,
        "text": text[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
    }


def _objective_table_matrix_evidence_records(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
) -> tuple[dict[str, Any], ...]:
    if route.source_kind != "table":
        return ()
    headers, data_rows = _objective_table_matrix_rows(source)
    if not headers or not data_rows:
        return ()
    if route.role == "current_experimental_evidence":
        return _objective_result_table_matrix_records(
            route=route,
            source=source,
            objective_context=objective_context,
            headers=headers,
            data_rows=data_rows,
        )
    if route.role == "process_or_treatment":
        process_records = _objective_process_table_matrix_records(
            route=route,
            source=source,
            objective_context=objective_context,
            headers=headers,
            data_rows=data_rows,
        )
        recover_result_columns = bool(
            _objective_route_result_columns(
                route,
                objective_context=objective_context,
            )
            or (objective_context is not None and objective_context.outcomes)
        )
        result_records = (
            _objective_result_table_matrix_records(
                route=route,
                source=source,
                objective_context=objective_context,
                headers=headers,
                data_rows=data_rows,
            )
            if recover_result_columns
            else ()
        )
        return (*process_records, *result_records)
    return ()








def _objective_result_table_matrix_records(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
    headers: tuple[str, ...],
    data_rows: tuple[tuple[int, tuple[str, ...]], ...],
) -> tuple[dict[str, Any], ...]:
    result_columns = _objective_route_result_columns(
        route,
        objective_context=objective_context,
    )
    if objective_context is not None:
        result_columns.update(
            header
            for header in headers
            if not _objective_value_column_is_non_result(header)
            and _objective_result_column_matches_target(
                header,
                objective_context=objective_context,
            )
        )
    if not result_columns:
        return ()

    records: list[dict[str, Any]] = []
    for row_index, row in data_rows:
        row_values = _objective_table_row_values(headers=headers, row=row)
        row_attributes = _objective_table_row_attributes(
            route=route,
            row_values=row_values,
            result_columns=result_columns,
            objective_context=objective_context,
        )
        if _objective_result_table_row_is_reference_context(
            route=route,
            row_values=row_values,
            result_columns=result_columns,
        ):
            continue
        row_attributes = _objective_table_row_attributes_with_sample_number(
            row_attributes=row_attributes,
            row_index=row_index,
        )
        for result_column in result_columns:
            raw_value = row_values.get(result_column)
            if raw_value in (None, ""):
                continue
            property_source = _objective_result_column_property_label(
                route=route,
                result_column=result_column,
                objective_context=objective_context,
            )
            _column_property, unit = _split_property_unit(result_column)
            outcome = (
                property_matching.normalize_objective_unit_property(
                    property_source,
                    objective_context=objective_context,
                )
                or property_source
            )
            numeric_value = _coerce_result_cell_number(raw_value)
            records.append(
                {
                    "evidence_id": _objective_matrix_unit_id(
                        route=route,
                        row_index=row_index,
                        column=result_column,
                    ),
                    "objective_id": route.objective_id,
                    "document_id": route.document_id,
                    "evidence_role": "direct_result",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": {
                        "outcome": outcome,
                        "value": numeric_value,
                        "unit": unit,
                        "direction": "unknown",
                        "result_text": (
                            f"{outcome} = {raw_value}" + (f" {unit}" if unit else "")
                        ),
                    },
                    "attribution_scope": "descriptive_only",
                    "scientific_context": {
                        "material": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["material"].items()
                        ],
                        "sample": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["sample"].items()
                        ],
                        "process": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["process"].items()
                        ],
                        "test": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["test"].items()
                        ],
                    },
                    "source_refs": _objective_route_source_refs(
                        route=route,
                        source=source,
                        row_index=row_index,
                        col_index=headers.index(result_column),
                        header_path=result_column,
                        source_excerpt=" | ".join(
                            f"{header}: {row_values[header]}"
                            for header in headers
                            if header in row_values
                        ),
                    ),
                    "resolution_status": "resolved",
                    "confidence": route.confidence,
                }
            )
    return tuple(records)


def _objective_process_table_matrix_records(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
    headers: tuple[str, ...],
    data_rows: tuple[tuple[int, tuple[str, ...]], ...],
) -> tuple[dict[str, Any], ...]:
    result_columns = _objective_route_result_columns(route)
    records: list[dict[str, Any]] = []
    for row_index, row in data_rows:
        row_values = _objective_table_row_values(headers=headers, row=row)
        row_attributes = _objective_table_row_attributes(
            route=route,
            row_values=row_values,
            result_columns=result_columns,
            objective_context=objective_context,
        )
        row_attributes = _objective_table_row_attributes_with_sample_number(
            row_attributes=row_attributes,
            row_index=row_index,
        )
        if (
            not row_attributes["material"]
            and not row_attributes["process"]
            and not row_attributes["test"]
        ):
            continue
        records.append(
            {
                "evidence_id": _objective_matrix_unit_id(
                    route=route,
                    row_index=row_index,
                    column="scientific_context",
                ),
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [
                        {"name": key, "value": value}
                        for key, value in row_attributes["material"].items()
                    ],
                    "sample": [
                        {"name": key, "value": value}
                        for key, value in row_attributes["sample"].items()
                    ],
                    "process": [
                        {"name": key, "value": value}
                        for key, value in row_attributes["process"].items()
                    ],
                    "test": [
                        {"name": key, "value": value}
                        for key, value in row_attributes["test"].items()
                    ],
                },
                "source_refs": _objective_route_source_refs(
                    route=route,
                    source=source,
                    row_index=row_index,
                    source_excerpt=" | ".join(
                        f"{header}: {row_values[header]}"
                        for header in headers
                        if header in row_values
                    ),
                ),
                "resolution_status": "resolved",
                "confidence": route.confidence,
            }
        )
    return tuple(records)




def _objective_table_row_attributes(
    *,
    route: EvidenceCandidate,
    row_values: dict[str, str],
    result_columns: set[str],
    objective_context: ResearchObjective | None,
) -> dict[str, dict[str, str]]:
    material_attributes: dict[str, str] = {}
    sample_attributes: dict[str, str] = {}
    process_attributes: dict[str, str] = {}
    test_attributes: dict[str, str] = {}
    for column, value in row_values.items():
        role = str(route.column_roles.get(column) or "").lower()
        column_key = _objective_column_key(column)
        is_objective_symbol_axis = bool(
            objective_context is not None
            and column not in result_columns
            and not _objective_value_column_is_non_result(column)
            and property_matching.process_column_axis_keys(column)
            and _objective_label_matches_variables(
                column,
                objective_context=objective_context,
            )
        )
        if is_objective_symbol_axis:
            process_attributes[
                _objective_process_attribute_label(
                    column=column,
                    role=role,
                    objective_context=objective_context,
                )
            ] = value
        elif any(
            term in role for term in ("material", "alloy", "composition")
        ) or column_key in {
            "material",
            "material_system",
            "alloy",
            "alloy_name",
            "alloy_type",
            "composition",
        }:
            material_attributes[column] = value
        elif "sample" in role or _objective_table_column_is_sample_key(column_key):
            sample_attributes[column] = value
        elif column in result_columns or _objective_value_column_is_non_result(column):
            continue
        elif _objective_table_column_is_process_attribute(
            route=route,
            column=column,
            role=role,
            objective_context=objective_context,
        ):
            process_attributes[
                _objective_process_attribute_label(
                    column=column,
                    role=role,
                    objective_context=objective_context,
                )
            ] = value
        elif (
            "test" in role
            or "condition" in role
            or column_key in {"test", "test_no", "test_number"}
        ):
            if route.role == "current_experimental_evidence":
                sample_attributes[column] = value
            test_attributes[column] = value
    return {
        "material": material_attributes,
        "sample": sample_attributes,
        "process": process_attributes,
        "test": test_attributes,
    }


def _objective_process_attribute_label(
    *,
    column: str,
    role: str,
    objective_context: ResearchObjective | None,
) -> str:
    if objective_context is not None:
        symbol_axes = {
            axis
            for axis in property_matching.process_column_axis_keys(column)
            if any(
                property_matching.axis_values_match(axis, objective_axis)
                for objective_axis in objective_context.variables
            )
        }
        if len(symbol_axes) == 1:
            return next(iter(symbol_axes))
    role_label = property_matching.normalize_property_label(role)
    if (
        role_label
        and property_matching.process_role_is_specific(role_label)
        and (
            objective_context is None
            or _objective_label_matches_variables(
                role_label,
                objective_context=objective_context,
            )
        )
    ):
        return role_label
    return column


def _objective_table_column_is_process_attribute(
    *,
    route: EvidenceCandidate,
    column: str,
    role: str,
    objective_context: ResearchObjective | None,
) -> bool:
    role_text = str(role or "").strip()
    if "process" in role_text or "variable" in role_text:
        return True
    if objective_context is not None:
        for label in (column, role_text):
            if _objective_label_matches_variables(
                label,
                objective_context=objective_context,
            ):
                return True
    return route.role == "process_or_treatment" and objective_context is None


def _objective_label_matches_variables(
    label: Any,
    *,
    objective_context: ResearchObjective,
) -> bool:
    label_text = str(label or "").strip()
    if not label_text:
        return False
    label_axis_keys = property_matching.process_column_axis_keys(label_text)
    label_tokens = property_matching.axis_tokens(property_matching.axis_key(label_text))
    for axis in objective_context.variables:
        axis_text = str(axis or "").strip()
        if not axis_text:
            continue
        axis_key = property_matching.normalize_property_label(axis_text)
        if axis_key and any(
            label_axis_key == axis_key
            or property_matching.axis_label_is_mentioned(label_axis_key, axis_key)
            for label_axis_key in label_axis_keys
        ):
            return True
        if (
            property_matching.axis_values_match(label_text, axis_text)
            or property_matching.axis_label_is_mentioned(label_text, axis_text)
            or property_matching.axis_label_is_mentioned(axis_text, label_text)
        ):
            return True
        axis_tokens = property_matching.axis_tokens(
            property_matching.axis_key(axis_text)
        )
        if len(label_tokens & axis_tokens) >= 2:
            return True
    return False


def _objective_result_table_row_is_reference_context(
    *,
    route: EvidenceCandidate,
    row_values: dict[str, str],
    result_columns: set[str],
) -> bool:
    if route.role != "current_experimental_evidence":
        return False
    context_values = tuple(
        str(value).strip()
        for column, value in row_values.items()
        if column not in result_columns
        and not _objective_value_column_is_non_result(column)
        and str(value).strip()
    )
    if not context_values:
        return False
    context_text = " ".join(context_values)
    if re.search(r"\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\]", context_text):
        return True
    normalized = context_text.casefold()
    return any(
        marker in normalized
        for marker in (
            "literature",
            "previous study",
            "previous work",
            "reference material",
            "reference sample",
        )
    )


def _objective_table_row_attributes_with_sample_number(
    *,
    row_attributes: dict[str, dict[str, str]],
    row_index: int,
) -> dict[str, dict[str, str]]:
    sample_attributes = dict(row_attributes["sample"])
    if _objective_sample_attributes_have_explicit_number(sample_attributes):
        return row_attributes
    if (
        sample_attributes
        and not _objective_sample_attributes_need_row_number(sample_attributes)
        and _objective_sample_attributes_have_stable_label(sample_attributes)
    ):
        return row_attributes
    if not sample_attributes and not (
        row_attributes["material"]
        or row_attributes["process"]
        or row_attributes["test"]
    ):
        return row_attributes
    sample_attributes["sample_number"] = str(row_index)
    return {
        "material": row_attributes["material"],
        "sample": sample_attributes,
        "process": row_attributes["process"],
        "test": row_attributes["test"],
    }


def _objective_sample_attributes_have_explicit_number(
    sample_attributes: dict[str, Any],
) -> bool:
    for key, value in sample_attributes.items():
        text = str(value).strip()
        if not text:
            continue
        column_key = _objective_column_key(str(key))
        if column_key in {
            "case",
            "condition",
            "condition_no",
            "condition_number",
            "id",
            "no",
            "sample_no",
            "sample_number",
            "specimen",
            "specimen_id",
            "specimens",
        }:
            return True
        if column_key in {"sample", "sample_id"} and (
            re.fullmatch(r"0*\d+", text)
            or re.search(r"\bS0*\d+\b", text, flags=re.IGNORECASE)
            or re.search(r"\bsample\s*#?\s*0*\d+\b", text, flags=re.IGNORECASE)
        ):
            return True
    return False


def _objective_sample_attributes_need_row_number(
    sample_attributes: dict[str, Any],
) -> bool:
    for value in sample_attributes.values():
        tokens = [
            token
            for token in _objective_numeric_match_tokens(value)
            if token not in {"1", "-1"}
        ]
        if len(set(tokens)) >= 2:
            return True
    return False


def _objective_sample_attributes_have_stable_label(
    sample_attributes: dict[str, Any],
) -> bool:
    for key in sample_attributes:
        column_key = _objective_column_key(str(key))
        if column_key in {
            "id",
            "label",
            "material",
            "printed_316l",
            "sample",
            "sample_id",
            "sample_label",
        }:
            return True
        if "sample" in column_key and "condition" not in column_key:
            return True
    return False


def _objective_table_column_is_sample_key(column_key: str) -> bool:
    return column_key in {
        "case",
        "condition",
        "condition_no",
        "condition_number",
        "id",
        "no",
        "printed_316l",
        "sample",
        "sample_id",
        "sample_no",
        "sample_number",
        "specimen",
        "specimen_id",
        "specimens",
    }


def _objective_matrix_unit_id(
    *,
    route: EvidenceCandidate,
    row_index: int,
    column: str,
) -> str:
    seed = "|".join((route.source_ref, str(row_index), column))
    return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"




























def _objective_route_result_columns(
    route: EvidenceCandidate,
    *,
    objective_context: ResearchObjective | None = None,
) -> set[str]:
    result_columns: set[str] = set()
    for column, role in route.column_roles.items():
        column_text = str(column)
        if _objective_value_column_is_non_result(column_text):
            continue
        role_text = str(role or "").strip().lower()
        if any(
            token in role_text
            for token in ("result", "target", "measurement", "property")
        ):
            if _objective_result_column_matches_target(
                column_text,
                objective_context=objective_context,
            ):
                result_columns.add(column_text)
            continue
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and _objective_column_key(role_text) == "current_experimental_evidence"
            and _objective_result_column_is_specific_metric(column_text)
        ):
            result_columns.add(column_text)
            continue
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and _objective_header_matches_any_axis(
                column_text,
                objective_context.outcomes,
            )
        ):
            result_columns.add(column_text)
            continue
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and _objective_column_key(column_text) == "relative_density"
            and any(
                axis in {"densification", "microstructure"}
                for axis in objective_context.outcomes
            )
        ):
            result_columns.add(column_text)
            continue
        role_label = property_matching.normalize_property_label(role_text)
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and role_label
            and property_matching.property_label_matches_target(
                role_label,
                target_axes=property_matching.objective_outcomes(objective_context),
            )
        ):
            result_columns.add(column_text)
    return result_columns


def _objective_result_column_property_label(
    *,
    route: EvidenceCandidate,
    result_column: str,
    objective_context: ResearchObjective | None,
) -> str:
    role_label = property_matching.normalize_property_label(
        route.column_roles.get(result_column)
    )
    if (
        role_label
        and objective_context is not None
        and property_matching.result_role_is_specific_property(role_label)
        and property_matching.property_label_matches_target(
            role_label,
            target_axes=property_matching.objective_outcomes(objective_context),
        )
    ):
        return role_label
    property_name, _unit = _split_property_unit(result_column)
    return (
        property_matching.normalize_property_label(property_name)
        or str(property_name or result_column).strip()
    )


def _objective_result_column_is_specific_metric(column_text: str) -> bool:
    property_name, _unit = _split_property_unit(column_text)
    tokens = property_matching.axis_tokens(property_name)
    if not tokens:
        return False
    return bool(tokens & {"coefficient", "distance", "index", "score"})


def _objective_result_column_matches_target(
    column_text: str,
    *,
    objective_context: ResearchObjective | None,
) -> bool:
    if objective_context is None or not objective_context.outcomes:
        return True
    property_name, _unit = _split_property_unit(column_text)
    normalized = (
        property_matching.normalize_property_label(property_name) or property_name
    )
    target_axes = property_matching.objective_outcomes(objective_context)
    if property_matching.property_label_matches_target(
        normalized,
        target_axes=target_axes,
    ):
        return True
    if property_matching.density_property_matches_structural_target(
        normalized,
        target_axes=target_axes,
    ):
        return True
    if normalized in target_axes:
        return True
    return any(
        property_matching.axis_label_is_mentioned(normalized, axis)
        or property_matching.axis_label_is_mentioned(column_text, axis)
        for axis in target_axes
    )


def _objective_value_column_is_non_result(value: str) -> bool:
    text = " ".join(
        str(value or "").lower().replace("_", " ").replace("-", " ").split()
    )
    if not text:
        return True
    return any(term in text for term in _OBJECTIVE_NON_RESULT_VALUE_COLUMN_TERMS)






def _coerce_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    scientific_match = re.search(
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:[xX\u00d7]\s*10)\s*\^?\s*([-+]?\d+)",
        text,
    )
    if scientific_match is not None:
        return float(scientific_match.group(1)) * (10 ** int(scientific_match.group(2)))
    match = _NUMBER_PATTERN.search(text)
    if match is None:
        return None
    return float(match.group(0))


def _coerce_result_cell_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    matches = list(_NUMBER_PATTERN.finditer(text))
    if len(matches) >= 2:
        leading_prefix = text[: matches[0].start()]
        between_first_and_second = text[matches[0].end() : matches[1].start()]
        if "(" in leading_prefix and ")" in between_first_and_second:
            return float(matches[1].group(0))
    return _coerce_number(text)




def _objective_evidence_has_payload(
    unit: ExtractedEvidenceDraft,
) -> bool:
    return bool(
        unit.changed_variables
        or unit.comparison is not None
        or unit.reported_result is not None
        or unit.scientific_context.has_content
    )


def _dedupe_preserving_order(
    values: list[str | None],
) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _attach_route_tree_position(
    candidate: dict[str, Any],
    *,
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    tree_position = _route_candidate_tree_position(
        candidate,
        document_tree=document_tree,
    )
    if not tree_position:
        return candidate
    return {
        **candidate,
        "tree_position": tree_position,
    }


def _route_candidate_tree_position(
    candidate: dict[str, Any],
    *,
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    source_kind = str(candidate.get("source_kind") or "")
    source_ref = str(candidate.get("source_ref") or "")
    source_ref_kind = "block" if source_kind == "text_window" else source_kind
    node = (
        _tree_node_for_route_source(
            document_tree=document_tree,
            source_ref_kind=source_ref_kind,
            source_ref_id=source_ref,
        )
        if document_tree is not None and source_ref and source_ref_kind
        else None
    )
    if node is not None:
        return _tree_position_payload(
            document_tree=document_tree,
            node=node,
        )
    heading_path = candidate.get("heading_path")
    return {
        "node_id": None,
        "node_type": source_kind or None,
        "section_path": _heading_path_parts(heading_path),
        "source_ref_kind": source_kind or None,
        "source_ref_id": source_ref or None,
        "order": None,
        "page_start": None,
        "page_end": None,
    }


def _route_tree_position(candidate: dict[str, Any]) -> dict[str, Any]:
    tree_position = candidate.get("tree_position")
    if isinstance(tree_position, dict):
        return dict(tree_position)
    return {
        "node_id": None,
        "node_type": candidate.get("source_kind"),
        "section_path": _heading_path_parts(candidate.get("heading_path")),
        "source_ref_kind": candidate.get("source_kind"),
        "source_ref_id": candidate.get("source_ref"),
        "order": None,
        "page_start": candidate.get("page"),
        "page_end": candidate.get("page"),
    }


def _tree_position_payload(
    *,
    document_tree: SourceDocumentTree,
    node: Any,
) -> dict[str, Any]:
    return {
        "node_id": getattr(node, "node_id", None),
        "node_type": str(getattr(node, "node_type", "") or "") or None,
        "section_path": _tree_node_section_path(
            document_tree=document_tree,
            node=node,
        ),
        "source_ref_kind": getattr(node, "source_ref_kind", None),
        "source_ref_id": getattr(node, "source_ref_id", None),
        "order": getattr(node, "order", None),
        "page_start": getattr(node, "page_start", None),
        "page_end": getattr(node, "page_end", None),
    }


def _tree_node_section_path(
    *,
    document_tree: SourceDocumentTree,
    node: Any,
) -> list[str]:
    heading_path = tuple(getattr(node, "heading_path", ()) or ())
    if heading_path:
        return [str(part) for part in heading_path if str(part).strip()]
    titles: list[str] = []
    parent_id = getattr(node, "parent_id", None)
    while parent_id:
        parent = document_tree.nodes.get(parent_id)
        if parent is None:
            break
        if parent.node_type in {"section", "references_section"}:
            title = str(getattr(parent, "title", "") or "").strip()
            if title:
                titles.append(title)
        parent_id = getattr(parent, "parent_id", None)
    return list(reversed(titles))


def _heading_path_parts(heading_path: Any) -> list[str]:
    if isinstance(heading_path, (list, tuple)):
        return [str(part).strip() for part in heading_path if str(part).strip()]
    return [part.strip() for part in str(heading_path or "").split(">") if part.strip()]


def _tree_node_for_route_source(
    *,
    document_tree: SourceDocumentTree,
    source_ref_kind: str,
    source_ref_id: str,
) -> Any | None:
    node = document_tree.node_for_source_ref(source_ref_kind, source_ref_id)
    if node is not None:
        return node
    return document_tree.nodes.get(source_ref_id)


def _source_candidate_from_route(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    candidate = {
        "source_kind": route.source_kind,
        "source_ref": route.source_ref,
        "heading_path": source.get("heading_path"),
        "page": source.get("page"),
    }
    return _attach_route_tree_position(
        candidate,
        document_tree=document_tree,
    )


def _objective_evidence_prompt_route_record(
    route: EvidenceCandidate,
) -> dict[str, Any]:
    return {
        "objective_id": route.objective_id,
        "document_id": route.document_id,
        "source_kind": route.source_kind,
        "source_ref": route.source_ref,
        "role": route.role,
        "extractable": route.extractable,
        "reason": route.reason,
        "column_roles": dict(route.column_roles),
        "join_plan": dict(route.join_plan),
        "confidence": route.confidence,
    }


def _objective_evidence_prompt_source(
    source: dict[str, Any],
) -> dict[str, Any]:
    source_kind = str(source.get("source_kind") or "")
    if source_kind == "table":
        compact_cells = _objective_evidence_prompt_table_cells(source)
        payload = {
            "source_kind": "table",
            "source_ref": str(source.get("source_ref") or ""),
            "document_id": source.get("document_id"),
            "page": source.get("page"),
            "caption_text": str(source.get("caption_text") or "")[
                :_ROUTE_PROMPT_TEXT_CHARS
            ],
            "heading_path": source.get("heading_path"),
            "column_headers": [
                str(value)[:_OBJECTIVE_STATE_TEXT_CHARS]
                for value in source.get("column_headers", []) or []
                if str(value).strip()
            ],
            "table_cells": compact_cells,
        }
        if not compact_cells:
            payload["table_matrix"] = _objective_evidence_prompt_table_matrix(source)
        return payload
    if source_kind == "text_window":
        return {
            "source_kind": "text_window",
            "source_ref": str(source.get("source_ref") or ""),
            "document_id": source.get("document_id"),
            "page": source.get("page"),
            "block_type": source.get("block_type"),
            "heading_path": source.get("heading_path"),
            "text": str(source.get("text") or "")[
                :_OBJECTIVE_EVIDENCE_PROMPT_TEXT_CHARS
            ],
        }
    return dict(source)


def _objective_evidence_prompt_table_matrix(
    source: dict[str, Any],
) -> list[list[str]]:
    matrix = source.get("table_matrix")
    if not isinstance(matrix, list):
        return []
    rows: list[list[str]] = []
    for row in matrix[:_OBJECTIVE_EVIDENCE_PROMPT_TABLE_ROWS]:
        if not isinstance(row, (list, tuple)):
            continue
        rows.append(
            [
                str(cell)[:_OBJECTIVE_STATE_TEXT_CHARS]
                for cell in row[:_ROUTE_PROMPT_HEADER_LIMIT]
            ]
        )
    return rows


def _objective_evidence_prompt_table_cells(
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    cells = source.get("table_cells")
    if not isinstance(cells, list):
        return []
    compact_cells: list[dict[str, Any]] = []
    for cell in cells[:_OBJECTIVE_EVIDENCE_PROMPT_TABLE_CELLS]:
        if not isinstance(cell, dict):
            continue
        compact_cells.append(
            {
                "row_index": cell.get("row_index"),
                "col_index": cell.get("col_index"),
                "header_path": cell.get("header_path"),
                "cell_text": str(cell.get("cell_text") or "")[
                    :_OBJECTIVE_STATE_TEXT_CHARS
                ],
            }
        )
    return compact_cells


def _empty_objective_document_state() -> dict[str, Any]:
    return {
        "schema_version": "objective_document_state.v2",
        "evidence_counts_by_role": {},
        "prior_evidence": [],
    }


def _objective_document_state_payload(
    units: list[ExtractedEvidenceDraft],
) -> dict[str, Any]:
    if not units:
        return _empty_objective_document_state()
    counts_by_role: dict[str, int] = {}
    for unit in units:
        role = unit.evidence_role or "irrelevant"
        counts_by_role[role] = counts_by_role.get(role, 0) + 1
    prior_evidence: list[dict[str, Any]] = []
    for unit in units[-_OBJECTIVE_STATE_ITEM_LIMIT:]:
        prior_evidence.append(
            {
                "evidence_role": unit.evidence_role,
                "outcome": (
                    unit.reported_result.outcome if unit.reported_result else None
                ),
                "attribution_scope": unit.attribution_scope,
                "resolution_status": unit.resolution_status,
                "source_refs": [dict(ref) for ref in unit.source_refs[:2]],
            }
        )
    return {
        "schema_version": "objective_document_state.v2",
        "evidence_counts_by_role": counts_by_role,
        "prior_evidence": prior_evidence,
    }


def _route_text_node_block_type(node: Any) -> str:
    node_type = str(getattr(node, "node_type", "") or "")
    if node_type == "caption":
        source_ref_kind = str(getattr(node, "source_ref_kind", "") or "")
        return "figure_caption" if source_ref_kind == "figure" else "paragraph"
    return node_type


def _tree_node_in_reference_branch(
    document_tree: SourceDocumentTree,
    node: Any,
) -> bool:
    current = node
    while current is not None:
        if current.node_type in {"references_section", "reference_entry"}:
            return True
        if getattr(current, "semantic_role", None) == "references":
            return True
        parent_id = getattr(current, "parent_id", None)
        current = document_tree.nodes.get(parent_id) if parent_id else None
    return False
