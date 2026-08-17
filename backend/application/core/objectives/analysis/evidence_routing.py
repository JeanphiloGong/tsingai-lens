"""Route screened Sources into the transient Objective extraction queue."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.core.objectives import property_matching
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from application.core.objectives.llm.structured_response import StructuredResponseClient
from domain.core import (
    ResearchObjective,
    normalize_objective_confidence,
    normalize_objective_terms,
)
from domain.source import SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_FRAME_TABLE_ROW_LIMIT = 3
_ROUTE_TEXT_CHARS = 900
_ROUTE_PROMPT_TEXT_CHARS = 320
_ROUTE_PROMPT_HEADER_LIMIT = 8
_ROUTE_CANDIDATE_LIMIT = 40
_ROUTE_TEXT_CANDIDATE_LIMIT = 8
_ROUTE_TEXT_HINT_LIMIT = 3
_ROUTE_TREE_TEXT_SECTION_LIMIT = 3
_OBJECTIVE_STATE_TEXT_CHARS = 220
_OBJECTIVE_EXTRACTABLE_ROUTE_ROLES = {
    "current_experimental_evidence",
    "process_or_treatment",
    "test_condition",
    "characterization",
}
_OBJECTIVE_ROUTE_ROLES = {
    "current_experimental_evidence",
    "process_or_treatment",
    "test_condition",
    "composition_or_background",
    "characterization",
    "literature_comparison",
    "modeling_or_prediction",
    "low_value_or_irrelevant",
}
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_ROUTE_MAX_COMPLETION_TOKENS = 512
_ROUTE_PROMPT_VERSION = "objective_evidence_route.v1"
_ROUTE_SYSTEM_PROMPT = """
You are routing source units for one research objective in an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is routing only, not final fact extraction.
- Return exactly one JSON object and nothing else.
- Decide only the `current_source` unit and return at most one route.
- Do not return source identity fields; the backend binds the route to the
  current source unit.
- Do not emit measurement results, sample variants, evidence anchors, or backend persistence ids.
- Do not output table schemas, column roles, join keys, join plans, source text, sample rows, explanations, or copied input JSON.
- For low-value, review, literature-comparison, composition-only, or unrelated
  units, return an empty `routes` array instead of writing a low-value route
  unless the source is explicitly frame-excluded.
- Prefer fewer, higher-confidence extractable routes over speculative coverage.
""".strip()


class StructuredEvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    role: Literal[
        "current_experimental_evidence",
        "process_or_treatment",
        "test_condition",
        "composition_or_background",
        "characterization",
        "literature_comparison",
        "modeling_or_prediction",
        "low_value_or_irrelevant",
    ] = "low_value_or_irrelevant"
    extractable: bool = False
    confidence: float = 0.0

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> str:
        normalized = (
            str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        )
        return (
            normalized
            if normalized in _OBJECTIVE_ROUTE_ROLES
            else "low_value_or_irrelevant"
        )


class StructuredEvidenceSelections(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    selections: list[StructuredEvidenceSelection] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("selections", mode="before")
    @classmethod
    def _normalize_selections(cls, value: object) -> object:
        return [] if value is None else value


def build_objective_evidence_route_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Route the current source unit for this one research objective.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with a `routes` array.\n"
        "Return at most one route for `current_source`. If it is not useful "
        "for later objective-scoped extraction, return `{\"routes\": []}`.\n"
        "Each route may contain only `role`, `extractable`, and `confidence`. "
        "Do not return `source_kind`, `source_ref`, ids, copied source text, "
        "explanations, or any nested input object.\n"
        "`role` must be one of: current_experimental_evidence, "
        "process_or_treatment, test_condition, composition_or_background, "
        "characterization, literature_comparison, modeling_or_prediction, "
        "low_value_or_irrelevant.\n"
        "Use the objective to decide whether `current_source` is direct "
        "target-outcome evidence, mediator/context evidence, or irrelevant. "
        "Treat `objective.outcomes` as the only outcomes that answer the "
        "objective. Treat `objective.mechanisms` as explanatory context unless the "
        "source explicitly links them to a target outcome.\n"
        "Use `current_experimental_evidence` only when the source unit likely "
        "contains current-work target results for the active objective.\n"
        "Use `process_or_treatment` or `test_condition` when a unit is mainly "
        "needed to bind samples, process variables, or test environments.\n"
        "Use `characterization` for microstructure, defect, phase, morphology, "
        "or grain observations tied to the active objective. Use "
        "`current_experimental_evidence` for explicit trends, best/worst "
        "conditions, or author explanations tied to target results.\n"
        "Use `low_value_or_irrelevant` with `extractable: false` only for "
        "frame-excluded tables that are passed as `current_source`."
    )
    return _ROUTE_SYSTEM_PROMPT, user_prompt


class ObjectiveEvidenceRouter:
    """Classify one screened Source for the transient extraction queue."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def route_source(self, payload: dict[str, Any]) -> StructuredEvidenceSelections:
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        system_prompt, user_prompt = build_objective_evidence_route_prompt(payload)
        response = self.response_client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredEvidenceSelections,
            max_completion_tokens=_ROUTE_MAX_COMPLETION_TOKENS,
            force_json_text=True,
            task_type="objective_evidence_route",
            prompt_version=_ROUTE_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredEvidenceSelections):
            raise TypeError("unexpected objective evidence route response type")
        return response


@dataclass(frozen=True)
class EvidenceCandidate:
    """Transient source-selection decision keyed by its stable Source locator."""

    objective_id: str
    document_id: str
    source_kind: str
    source_ref: str
    role: str
    extractable: bool
    reason: str | None
    table_schema: dict[str, Any]
    column_roles: dict[str, Any]
    join_plan: dict[str, Any]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvidenceCandidate":
        return cls(
            objective_id=_text(payload.get("objective_id")),
            document_id=_text(payload.get("document_id")),
            source_kind=_text(payload.get("source_kind")) or "text_window",
            source_ref=_text(payload.get("source_ref")),
            role=_text(payload.get("role")) or "low_value_or_irrelevant",
            extractable=bool(payload.get("extractable")),
            reason=_optional_text(payload.get("reason")),
            table_schema=_mapping(payload.get("table_schema")),
            column_roles=_mapping(payload.get("column_roles")),
            join_plan=_mapping(payload.get("join_plan")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "role": self.role,
            "extractable": self.extractable,
            "reason": self.reason,
            "table_schema": dict(self.table_schema),
            "column_roles": dict(self.column_roles),
            "join_plan": dict(self.join_plan),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SourceSelectionHint:
    """Transient table-selection hint used only during one analysis run."""

    table_id: str
    document_id: str
    caption_text: str | None
    role: str
    strength: str | None
    matched_outcomes: tuple[str, ...]
    matched_variables: tuple[str, ...]
    reason: str | None

    def __post_init__(self) -> None:
        if not self.table_id:
            raise ValueError("source selection hint requires table_id")
        if self.role not in {"result_table", "condition_context"}:
            raise ValueError(f"unsupported source selection hint role: {self.role}")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceSelectionHint":
        return cls(
            table_id=_text(payload.get("table_id")),
            document_id=_text(payload.get("document_id")),
            caption_text=_optional_text(payload.get("caption_text")),
            role=_text(payload.get("role")),
            strength=_optional_text(payload.get("strength")),
            matched_outcomes=normalize_objective_terms(payload.get("matched_outcomes")),
            matched_variables=normalize_objective_terms(
                payload.get("matched_variables")
            ),
            reason=_optional_text(payload.get("reason")),
        )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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


def route_sources(
    *,
    collection_id: str,
    evidence_router: ObjectiveEvidenceRouter,
    objectives: tuple[ResearchObjective, ...],
    objective_paper_frames: tuple[PaperAnalysisFrame, ...],
    blocks_by_document_id: dict[str, list[Any]],
    tables_by_document_id: dict[str, list[Any]],
    document_trees_by_document_id: dict[str, SourceDocumentTree],
    progress_callback: ProgressCallback | None = None,
) -> tuple[EvidenceCandidate, ...]:
    objective_by_id = {objective.objective_id: objective for objective in objectives}
    all_tables = tuple(
        table
        for document_tables in tables_by_document_id.values()
        for table in document_tables
    )
    routing_hints_by_objective_id = {
        objective.objective_id: _build_objective_table_routing_hints(
            objective,
            tables=all_tables,
        )
        for objective in objectives
    }
    routes: list[EvidenceCandidate] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    logger.info(
        "Research objective evidence routing started collection_id=%s frame_count=%s",
        collection_id,
        len(objective_paper_frames),
    )
    frame_count = len(objective_paper_frames)
    document_metadata = _progress_document_metadata(
        document_trees_by_document_id=document_trees_by_document_id,
    )
    for frame_position, frame in enumerate(objective_paper_frames, start=1):
        frame_document_metadata = document_metadata.get(frame.document_id, {})
        _notify_progress(
            progress_callback,
            phase="objective_evidence_routing_started",
            current=frame_position,
            total=frame_count,
            unit="frames",
            message="Routing source blocks and tables for objective-scoped extraction.",
            active_document_id=frame.document_id,
            active_document_title=frame_document_metadata.get("title"),
            active_source_filename=frame_document_metadata.get("source_filename"),
            active_objective_id=frame.objective_id,
        )
        logger.info(
            "Research objective evidence routing frame started collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s relevance=%s completed_frames=%s remaining_frames=%s",
            collection_id,
            frame.objective_id,
            frame.document_id,
            frame.document_id,
            frame_position,
            frame_count,
            frame.relevance,
            frame_position - 1,
            max(frame_count - frame_position + 1, 0),
        )
        if frame.relevance == "irrelevant":
            logger.info(
                "Research objective evidence routing frame skipped collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s reason=irrelevant completed_frames=%s remaining_frames=%s",
                collection_id,
                frame.objective_id,
                frame.document_id,
                frame.document_id,
                frame_position,
                frame_count,
                frame_position,
                max(frame_count - frame_position, 0),
            )
            continue
        objective = objective_by_id.get(frame.objective_id)
        if objective is None:
            logger.info(
                "Research objective evidence routing frame skipped collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s reason=missing_objective completed_frames=%s remaining_frames=%s",
                collection_id,
                frame.objective_id,
                frame.document_id,
                frame.document_id,
                frame_position,
                frame_count,
                frame_position,
                max(frame_count - frame_position, 0),
            )
            continue
        objective_context = objective
        source_candidates = _build_route_source_candidates(
            frame=frame,
            objective_context=objective_context,
            blocks=blocks_by_document_id.get(frame.document_id, []),
            tables=tables_by_document_id.get(frame.document_id, []),
            document_tree=document_trees_by_document_id.get(frame.document_id),
        )
        if not source_candidates:
            logger.info(
                "Research objective evidence routing frame finished collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s source_candidate_count=0 route_count=0 extractable_route_count=0 completed_frames=%s remaining_frames=%s",
                collection_id,
                frame.objective_id,
                frame.document_id,
                frame.document_id,
                frame_position,
                frame_count,
                frame_position,
                max(frame_count - frame_position, 0),
            )
            continue
        frame_route_count_before = len(routes)
        candidate_by_key = {
            (candidate["source_kind"], candidate["source_ref"]): candidate
            for candidate in source_candidates
        }
        for candidate in source_candidates:
            if candidate.get("frame_status") == "excluded":
                route_key = (
                    frame.objective_id,
                    frame.document_id,
                    str(candidate.get("source_kind") or ""),
                    str(candidate.get("source_ref") or ""),
                    "low_value_or_irrelevant",
                )
                if route_key not in seen:
                    seen.add(route_key)
                    routes.append(
                        EvidenceCandidate.from_mapping(
                            {
                                "objective_id": frame.objective_id,
                                "document_id": frame.document_id,
                                "source_kind": candidate.get("source_kind"),
                                "source_ref": candidate.get("source_ref"),
                                "role": "low_value_or_irrelevant",
                                "extractable": False,
                                "reason": "Excluded by objective paper frame.",
                                "table_schema": _route_table_schema_record(
                                    candidate=candidate,
                                ),
                                "column_roles": {},
                                "join_plan": {},
                                "confidence": 0.7,
                            }
                        )
                    )
                continue
            payload = {
                "collection_id": collection_id,
                "objective": _route_prompt_objective_record(objective),
                "paper_frame": _route_prompt_paper_frame_record(frame),
                "tree_position": _route_tree_position(candidate),
                "document_state": _empty_objective_document_state(),
                "current_source": _route_prompt_current_source(candidate),
            }
            try:
                parsed = evidence_router.route_source(payload)
                route_records = [item.model_dump() for item in parsed.selections[:1]]
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Research objective evidence routing model failed; using deterministic route collection_id=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s",
                    collection_id,
                    frame.objective_id,
                    frame.document_id,
                    candidate.get("source_kind"),
                    candidate.get("source_ref"),
                    exc_info=True,
                )
                route_records = [
                    _build_deterministic_objective_route_record(
                        objective_context=objective_context,
                        candidate=candidate,
                    )
                ]
            for record in route_records:
                source_kind = str(candidate.get("source_kind") or "")
                source_ref = str(candidate.get("source_ref") or "")
                route_candidate = candidate_by_key.get((source_kind, source_ref))
                if route_candidate is None:
                    continue
                record = _finalize_objective_route_record(
                    record=record,
                    frame=frame,
                    objective_context=objective_context,
                    route_candidate=route_candidate,
                )
                role = str(record.get("role") or "low_value_or_irrelevant")
                route_key = (
                    frame.objective_id,
                    frame.document_id,
                    source_kind,
                    source_ref,
                    role,
                )
                if route_key in seen:
                    continue
                seen.add(route_key)
                routes.append(EvidenceCandidate.from_mapping(record))
        _append_objective_context_hint_routes(
            routes=routes,
            seen=seen,
            frame=frame,
            objective_context=objective_context,
            routing_hints=routing_hints_by_objective_id.get(
                frame.objective_id,
                (),
            ),
            candidate_by_key=candidate_by_key,
        )
        _append_ranked_text_hint_routes(
            routes=routes,
            seen=seen,
            frame=frame,
            objective_context=objective_context,
            source_candidates=source_candidates,
        )
        frame_routes = routes[frame_route_count_before:]
        logger.info(
            "Research objective evidence routing frame finished collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s source_candidate_count=%s route_count=%s extractable_route_count=%s completed_frames=%s remaining_frames=%s",
            collection_id,
            frame.objective_id,
            frame.document_id,
            frame.document_id,
            frame_position,
            frame_count,
            len(source_candidates),
            len(frame_routes),
            sum(1 for route in frame_routes if route.extractable),
            frame_position,
            max(frame_count - frame_position, 0),
        )
    logger.info(
        "Research objective evidence routing finished collection_id=%s route_count=%s",
        collection_id,
        len(routes),
    )
    return tuple(routes)


def _build_deterministic_objective_route_record(
    *,
    objective_context: ResearchObjective | None,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_role = _route_candidate_evidence_role(
        objective_context=objective_context,
        candidate=candidate,
    )
    if evidence_role == "direct_support":
        role = "current_experimental_evidence"
        extractable = True
    elif evidence_role == "mediator_context":
        role = "characterization"
        extractable = False
    elif evidence_role == "background_context":
        role = "process_or_treatment"
        extractable = True
    else:
        role = "low_value_or_irrelevant"
        extractable = False
    return {
        "role": role,
        "extractable": extractable,
        "reason": "Deterministic route built after model routing failed.",
        "confidence": 0.62 if extractable else 0.55,
    }


def _finalize_objective_route_record(
    *,
    record: dict[str, Any],
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective | None,
    route_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    finalized = dict(record)
    if route_candidate.get("frame_status") == "excluded":
        finalized["role"] = "low_value_or_irrelevant"
        finalized["extractable"] = False
    evidence_role = _route_candidate_evidence_role(
        objective_context=objective_context,
        candidate=route_candidate,
    )
    finalized = _apply_route_evidence_role(
        record=finalized,
        evidence_role=evidence_role,
    )
    source_kind = str(route_candidate.get("source_kind") or "")
    source_ref = str(route_candidate.get("source_ref") or "")
    finalized.update(
        {
            "objective_id": frame.objective_id,
            "document_id": frame.document_id,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "table_schema": _route_table_schema_record(
                candidate=dict(route_candidate),
            ),
            "extractable": _normalize_route_extractable(finalized),
        }
    )
    if source_kind == "table":
        table_schema = _route_table_schema_record(candidate=dict(route_candidate))
        role = str(finalized.get("role") or "low_value_or_irrelevant")
        finalized.update(
            {
                "column_roles": (
                    _objective_context_hint_column_roles(
                        objective_context=objective_context,
                        hint_role=(
                            "result_table"
                            if role == "current_experimental_evidence"
                            else "condition_context"
                        ),
                        table_schema=table_schema,
                    )
                    if objective_context is not None
                    else {}
                ),
            }
        )
    else:
        finalized.update({"column_roles": {}})
    return finalized


def _append_objective_context_hint_routes(
    *,
    routes: list[EvidenceCandidate],
    seen: set[tuple[str, str, str, str, str]],
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective | None,
    routing_hints: tuple[SourceSelectionHint, ...],
    candidate_by_key: dict[tuple[str, str], dict[str, Any]],
) -> None:
    if objective_context is None:
        return
    for hint in routing_hints:
        table_id = hint.table_id
        if not table_id:
            continue
        document_id = hint.document_id
        if document_id and document_id != frame.document_id:
            continue
        candidate = candidate_by_key.get(("table", table_id))
        if candidate is None:
            continue
        role = _objective_context_hint_route_role(hint)
        if role is None:
            continue
        route_key = (
            frame.objective_id,
            frame.document_id,
            "table",
            table_id,
            role,
        )
        if route_key in seen:
            continue
        seen.add(route_key)
        table_schema = _route_table_schema_record(candidate=candidate)
        routes.append(
            EvidenceCandidate.from_mapping(
                {
                    "objective_id": frame.objective_id,
                    "document_id": frame.document_id,
                    "source_kind": "table",
                    "source_ref": table_id,
                    "role": role,
                    "extractable": True,
                    "reason": hint.reason
                    or "Selected from objective context routing hints.",
                    "table_schema": table_schema,
                    "column_roles": _objective_context_hint_column_roles(
                        objective_context=objective_context,
                        hint_role=hint.role,
                        table_schema=table_schema,
                    ),
                    "join_plan": {},
                    "confidence": objective_context.confidence,
                }
            )
        )


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


def _route_prompt_current_source(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    source_kind = str(candidate.get("source_kind") or "")
    if source_kind == "table":
        table_schema = (
            candidate.get("table_schema")
            if isinstance(candidate.get("table_schema"), dict)
            else {}
        )
        column_headers = (
            table_schema.get("column_headers")
            if isinstance(table_schema.get("column_headers"), (list, tuple))
            else ()
        )
        return {
            "source_kind": "table",
            "source_ref": str(candidate.get("source_ref") or ""),
            "frame_status": str(candidate.get("frame_status") or ""),
            "caption_text": str(candidate.get("caption_text") or "")[
                :_ROUTE_PROMPT_TEXT_CHARS
            ],
            "heading_path": candidate.get("heading_path"),
            "column_headers": [
                str(header)[:_OBJECTIVE_STATE_TEXT_CHARS]
                for header in column_headers[:_ROUTE_PROMPT_HEADER_LIMIT]
                if str(header).strip()
            ],
            "row_count": table_schema.get("row_count"),
            "col_count": table_schema.get("col_count"),
        }
    return {
        "source_kind": source_kind or "text_window",
        "source_ref": str(candidate.get("source_ref") or ""),
        "frame_status": str(candidate.get("frame_status") or ""),
        "section_label": candidate.get("section_label"),
        "block_type": candidate.get("block_type"),
        "text_hint": str(candidate.get("text") or "")[:_ROUTE_PROMPT_TEXT_CHARS],
    }


def _objective_context_hint_route_role(
    hint: SourceSelectionHint,
) -> str | None:
    role = hint.role
    if role == "result_table":
        return "current_experimental_evidence"
    if role == "condition_context":
        return "process_or_treatment"
    return None


def _objective_context_hint_column_roles(
    *,
    objective_context: ResearchObjective,
    hint_role: str,
    table_schema: dict[str, Any],
) -> dict[str, str]:
    roles: dict[str, str] = {}
    for header in table_schema.get("column_headers", ()):
        header_text = str(header or "").strip()
        if not header_text:
            continue
        header_key = _objective_column_key(header_text)
        if header_key == "condition_number":
            roles[header_text] = "sample_condition"
        elif header_key in {"sample", "sample_number"}:
            roles[header_text] = "sample_id"
        elif _objective_value_column_is_statistical(header_text):
            roles[header_text] = "statistical_measure"
        elif _objective_header_matches_any_axis(
            header_text,
            objective_context.outcomes,
        ) or (
            hint_role == "result_table"
            and header_key == "relative_density"
            and any(
                axis in {"densification", "microstructure"}
                for axis in objective_context.outcomes
            )
        ):
            roles[header_text] = "target_property"
        elif _objective_header_matches_any_axis(
            header_text,
            objective_context.variables,
        ) or _objective_header_looks_process_variable(header_text):
            roles[header_text] = "process_variable"
    return roles


def _append_ranked_text_hint_routes(
    *,
    routes: list[EvidenceCandidate],
    seen: set[tuple[str, str, str, str, str]],
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective | None,
    source_candidates: list[dict[str, Any]],
) -> None:
    existing_refs = {
        route.source_ref
        for route in routes
        if route.objective_id == frame.objective_id
        and route.document_id == frame.document_id
        and route.source_kind == "text_window"
    }
    ranked_candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, candidate in enumerate(source_candidates):
        if candidate.get("source_kind") != "text_window":
            continue
        source_ref = str(candidate.get("source_ref") or "").strip()
        if not source_ref or source_ref in existing_refs:
            continue
        ranked_candidates.append(
            (
                -_text_hint_route_priority(candidate),
                index,
                candidate,
            )
        )
    ranked_candidates.sort()
    added = 0
    for _, _, candidate in ranked_candidates:
        source_ref = str(candidate.get("source_ref") or "").strip()
        evidence_role = _route_candidate_evidence_role(
            objective_context=objective_context,
            candidate=candidate,
        )
        if evidence_role == "irrelevant":
            continue
        role = _text_hint_route_role(
            frame=frame,
            candidate=candidate,
            evidence_role=evidence_role,
        )
        extractable = evidence_role in {"direct_support", "background_context"}
        route_key = (
            frame.objective_id,
            frame.document_id,
            "text_window",
            source_ref,
            role,
        )
        if route_key in seen:
            continue
        seen.add(route_key)
        routes.append(
            EvidenceCandidate.from_mapping(
                {
                    "objective_id": frame.objective_id,
                    "document_id": frame.document_id,
                    "source_kind": "text_window",
                    "source_ref": source_ref,
                    "role": role,
                    "extractable": extractable,
                    "reason": (
                        "High-scoring objective text candidate retained as "
                        f"{evidence_role}."
                    ),
                    "join_plan": {"evidence_role": evidence_role},
                    "table_schema": {},
                    "column_roles": {},
                    "confidence": 0.62,
                }
            )
        )
        added += 1
        if added >= _ROUTE_TEXT_HINT_LIMIT:
            break


def _text_hint_route_priority(candidate: dict[str, Any]) -> int:
    section_key = _objective_column_key(str(candidate.get("section_label") or ""))
    priority = 0
    if "conclusion" in section_key:
        priority += 8
    if section_key.startswith(("3_", "4_")):
        priority += 6
    if candidate.get("block_type") == "figure_caption":
        priority += 2
    if "abstract" in section_key:
        priority -= 3
    text = str(candidate.get("text") or "").casefold()
    if any(
        phrase in text
        for phrase in (
            "compared with",
            "comparing",
            "decreased",
            "exhibited",
            "formation of",
            "formed",
            "higher than",
            "increased",
            "lower than",
            "observed",
            "resulted in",
            "resulted into",
        )
    ):
        priority += 8
    if any(
        token in text
        for token in (
            "microstructure",
            "grain",
            "dendrite",
            "defect",
            "porosity",
            "sem",
        )
    ):
        priority += 2
    if any(
        phrase in text
        for phrase in (
            "aims to",
            "following conclusions can be drawn",
            "was investigated",
        )
    ):
        priority -= 8
    return priority


def _text_hint_route_role(
    *,
    frame: PaperAnalysisFrame,
    candidate: dict[str, Any],
    evidence_role: str = "direct_support",
) -> str:
    if evidence_role == "background_context":
        return "process_or_treatment"
    if evidence_role == "mediator_context":
        return "characterization"
    text = " ".join(
        str(value or "")
        for value in (
            candidate.get("section_label"),
            candidate.get("text"),
            *frame.measured_property_scope,
        )
    ).casefold()
    if any(
        token in text
        for token in (
            "microstructure",
            "grain",
            "dendrite",
            "defect",
            "morphology",
            "porosity",
            "phase",
            "sem",
        )
    ):
        return "characterization"
    return "current_experimental_evidence"


def _route_candidate_evidence_role(
    *,
    objective_context: ResearchObjective | None,
    candidate: Mapping[str, Any],
) -> str:
    if objective_context is None:
        return "direct_support"
    text = _route_candidate_text(candidate)
    if not text:
        return "irrelevant"
    target_axes = objective_context.outcomes
    mechanisms = objective_context.mechanisms
    context_axes = (
        *objective_context.material_scope,
        *objective_context.constraints,
    )
    variable_axes = objective_context.variables
    if _route_text_mentions_any_axis(text, target_axes):
        return "direct_support"
    if _route_text_mentions_any_axis(text, mechanisms):
        return "mediator_context"
    if _route_text_mentions_any_axis(text, (*variable_axes, *context_axes)):
        return "background_context"
    return "irrelevant"


def _apply_route_evidence_role(
    *,
    record: dict[str, Any],
    evidence_role: str,
) -> dict[str, Any]:
    updated = dict(record)
    join_plan = dict(updated.get("join_plan") or {})
    join_plan["evidence_role"] = evidence_role
    updated["join_plan"] = join_plan
    if evidence_role == "direct_support":
        updated["role"] = "current_experimental_evidence"
        updated["extractable"] = True
    elif evidence_role == "irrelevant":
        updated["role"] = "low_value_or_irrelevant"
        updated["extractable"] = False
    elif evidence_role == "mediator_context":
        updated["role"] = "characterization"
        updated["extractable"] = False
    elif evidence_role == "background_context":
        updated["role"] = "process_or_treatment"
    return updated


def _route_candidate_text(candidate: Mapping[str, Any]) -> str:
    table_schema = candidate.get("table_schema")
    column_headers = (
        table_schema.get("column_headers")
        if isinstance(table_schema, Mapping)
        else candidate.get("column_headers")
    )
    return " ".join(
        str(value or "")
        for value in (
            candidate.get("section_label"),
            candidate.get("caption_text"),
            candidate.get("heading_path"),
            candidate.get("text"),
            " ".join(str(item) for item in column_headers or []),
        )
        if str(value or "").strip()
    )


def _route_text_mentions_any_axis(
    text: str,
    axes: Iterable[str],
) -> bool:
    return any(property_matching.source_text_mentions_axis(text, axis) for axis in axes)


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


def _objective_header_looks_process_variable(header: str) -> bool:
    header_key = _objective_column_key(header)
    return any(
        token in header_key
        for token in (
            "duration",
            "energy",
            "hatch",
            "laser",
            "power",
            "scan",
            "speed",
            "temperature",
        )
    )


def _objective_value_column_is_statistical(value: str) -> bool:
    text = " ".join(
        str(value or "").lower().replace("_", " ").replace("-", " ").split()
    )
    return any(
        term in text
        for term in ("standard deviation", "std", "sd", "variance", "error bar")
    )


def _objective_column_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _split_property_unit(value: str) -> tuple[str, str | None]:
    text = str(value or "").strip()
    text = re.sub(r"\s*>\s*(?=[\[(])", " ", text).strip()
    if text.endswith("]") and "[" in text:
        name, _, suffix = text.rpartition("[")
        unit = suffix[:-1].strip()
        return name.strip() or text, unit or None
    if text.endswith(")") and "(" in text:
        name, _, suffix = text.rpartition("(")
        unit = suffix[:-1].strip()
        return name.strip() or text, unit or None
    return text, None


def _build_route_source_candidates(
    *,
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective,
    blocks: list[Any],
    tables: list[Any],
    document_tree: SourceDocumentTree | None = None,
) -> list[dict[str, Any]]:
    candidates_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    table_by_id = {
        str(getattr(table, "table_id", "") or ""): table
        for table in tables
        if str(getattr(table, "table_id", "") or "")
    }
    for table_id in (*frame.relevant_tables, *frame.excluded_tables):
        table = table_by_id.get(table_id)
        if table is None:
            continue
        table_schema = _build_route_table_schema(table)
        candidate = {
            "source_kind": "table",
            "source_ref": table_id,
            "frame_status": (
                "excluded" if table_id in frame.excluded_tables else "relevant"
            ),
            "caption_text": getattr(table, "caption_text", None),
            "heading_path": getattr(table, "heading_path", None),
            "table_schema": table_schema,
            "sample_rows": table_schema["sample_rows"],
        }
        candidates_by_key[("table", table_id)] = _attach_route_tree_position(
            candidate,
            document_tree=document_tree,
        )
    if document_tree is not None:
        text_candidates = _build_tree_route_text_candidates(
            frame=frame,
            objective_context=objective_context,
            blocks=blocks,
            document_tree=document_tree,
        )
    else:
        text_candidate_limit = max(
            _ROUTE_CANDIDATE_LIMIT - len(candidates_by_key),
            0,
        )
        text_candidates = _build_ranked_route_text_candidates(
            frame=frame,
            objective_context=objective_context,
            blocks=blocks,
            limit=text_candidate_limit,
        )
    for candidate in text_candidates:
        source_ref = str(candidate.get("source_ref") or "")
        if not source_ref:
            continue
        candidates_by_key[("text_window", source_ref)] = _attach_route_tree_position(
            candidate,
            document_tree=document_tree,
        )
    candidates = _sort_route_candidates_by_tree(
        candidates_by_key.values(),
        document_tree=document_tree,
    )
    if document_tree is not None:
        return candidates
    return candidates[:_ROUTE_CANDIDATE_LIMIT]


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


def _sort_route_candidates_by_tree(
    candidates: Iterable[dict[str, Any]],
    *,
    document_tree: SourceDocumentTree | None,
) -> list[dict[str, Any]]:
    ordered = list(candidates)
    if document_tree is None:
        return ordered
    return sorted(
        ordered,
        key=lambda candidate: (
            _route_candidate_order(candidate),
            str(candidate.get("source_kind") or ""),
            str(candidate.get("source_ref") or ""),
        ),
    )


def _route_candidate_order(candidate: dict[str, Any]) -> int:
    tree_position = candidate.get("tree_position")
    if isinstance(tree_position, dict):
        order = tree_position.get("order")
        if order is not None:
            try:
                return int(order)
            except (TypeError, ValueError):
                pass
    return 900_000


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


def order_routes_for_extraction(
    routes: tuple[EvidenceCandidate, ...],
    *,
    document_trees_by_document_id: dict[str, SourceDocumentTree],
) -> tuple[EvidenceCandidate, ...]:
    routes_by_document: dict[tuple[str, str], list[EvidenceCandidate]] = {}
    for route in routes:
        routes_by_document.setdefault(
            (route.objective_id, route.document_id),
            [],
        ).append(route)
    ordered_groups = tuple(
        tuple(
            sorted(
                document_routes,
                key=lambda route: (
                    _route_tree_order(
                        route,
                        document_trees_by_document_id=(document_trees_by_document_id),
                    ),
                    route.source_ref,
                ),
            )
        )
        for _key, document_routes in sorted(routes_by_document.items())
    )
    return tuple(
        group[position]
        for position in range(max((len(group) for group in ordered_groups), default=0))
        for group in ordered_groups
        if position < len(group)
    )


def _route_tree_order(
    route: EvidenceCandidate,
    *,
    document_trees_by_document_id: dict[str, SourceDocumentTree],
) -> int:
    document_tree = document_trees_by_document_id.get(route.document_id)
    if document_tree is None:
        return 900_000
    source_ref_kind = (
        "block" if route.source_kind == "text_window" else route.source_kind
    )
    node = _tree_node_for_route_source(
        document_tree=document_tree,
        source_ref_kind=source_ref_kind,
        source_ref_id=route.source_ref,
    )
    if node is None:
        return 900_000
    return int(getattr(node, "order", 900_000) or 900_000)


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


def _empty_objective_document_state() -> dict[str, Any]:
    return {
        "schema_version": "objective_document_state.v2",
        "evidence_counts_by_role": {},
        "prior_evidence": [],
    }


def _build_ranked_route_text_candidates(
    *,
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective,
    blocks: list[Any],
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    scored_candidates: list[tuple[int, int, dict[str, Any]]] = []
    selected_source_refs = set(frame.relevant_text_source_refs)
    for block in sorted(
        blocks,
        key=lambda item: int(getattr(item, "block_order", 0) or 0),
    ):
        block_id = str(getattr(block, "block_id", "") or "")
        text = str(getattr(block, "text", "") or "").strip()
        block_type = str(getattr(block, "block_type", "") or "")
        section_label = _block_section_label(block)
        if (
            not block_id
            or not text
            or not any(char.isalpha() for char in text)
            or block_type not in {"paragraph", "list_item", "figure_caption"}
        ):
            continue
        if selected_source_refs and block_id not in selected_source_refs:
            continue
        score = _route_text_candidate_score(
            frame=frame,
            objective_context=objective_context,
            block_type=block_type,
            section_label=section_label,
            text=text,
        )
        if score <= 0:
            continue
        scored_candidates.append(
            (
                -score,
                int(getattr(block, "block_order", 0) or 0),
                {
                    "source_kind": "text_window",
                    "source_ref": block_id,
                    "frame_status": "relevant",
                    "section_label": section_label,
                    "block_type": block_type,
                    "text": text[:_ROUTE_TEXT_CHARS],
                },
            )
        )
    scored_candidates.sort()
    return [
        candidate
        for _, _, candidate in scored_candidates[
            : min(limit, _ROUTE_TEXT_CANDIDATE_LIMIT)
        ]
    ]


def _build_tree_route_text_candidates(
    *,
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective,
    blocks: list[Any],
    document_tree: SourceDocumentTree,
) -> list[dict[str, Any]]:
    block_by_id = {
        str(getattr(block, "block_id", "") or ""): block
        for block in blocks
        if str(getattr(block, "block_id", "") or "")
    }
    restrict_to_frame_sections = _route_text_candidates_use_frame_sections(frame)
    scored_candidates: list[tuple[int, int, dict[str, Any]]] = []
    for node in _document_tree_nodes_in_order(document_tree):
        if _tree_node_in_reference_branch(document_tree, node):
            continue
        if str(getattr(node, "source_ref_kind", "") or "").strip() != "block":
            continue
        block_type = _route_text_node_block_type(node)
        if block_type not in {"paragraph", "list_item", "figure_caption"}:
            continue
        source_ref = str(getattr(node, "source_ref_id", "") or "").strip()
        block = block_by_id.get(source_ref)
        if not source_ref:
            source_ref = str(getattr(node, "node_id", "") or "").strip()
        text = (
            str(getattr(block, "text", "") or "").strip() if block is not None else ""
        )
        if not text:
            text = str(getattr(node, "text", "") or "").strip()
        if not source_ref or not text or not any(char.isalpha() for char in text):
            continue
        section_label = _tree_section_label_for_route_node(
            document_tree=document_tree,
            node=node,
            block=block,
        )
        if restrict_to_frame_sections:
            if frame.relevant_text_source_refs:
                if not _route_tree_source_matches_frame(
                    document_tree=document_tree,
                    node=node,
                    frame=frame,
                ):
                    continue
            elif not _route_section_matches_frame(
                section_label=section_label,
                frame=frame,
            ):
                continue
        score = _route_text_candidate_score(
            frame=frame,
            objective_context=objective_context,
            block_type=block_type,
            section_label=section_label,
            text=text,
        )
        if score <= 0:
            continue
        scored_candidates.append(
            (
                -score,
                int(getattr(node, "order", 900_000) or 900_000),
                {
                    "source_kind": "text_window",
                    "source_ref": source_ref,
                    "frame_status": "relevant",
                    "section_label": section_label,
                    "block_type": block_type,
                    "text": text[:_ROUTE_TEXT_CHARS],
                },
            )
        )
    scored_candidates = _bounded_tree_route_text_candidates(
        frame=frame,
        objective_context=objective_context,
        scored_candidates=scored_candidates,
    )
    return [
        candidate
        for _, _, candidate in sorted(
            scored_candidates,
            key=lambda item: (
                item[1],
                str(item[2].get("source_ref") or ""),
            ),
        )
    ]


def _bounded_tree_route_text_candidates(
    *,
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective,
    scored_candidates: list[tuple[int, int, dict[str, Any]]],
) -> list[tuple[int, int, dict[str, Any]]]:
    if len(scored_candidates) <= _ROUTE_TEXT_CANDIDATE_LIMIT:
        return scored_candidates
    if not (frame.relevance == "high" and frame.paper_role == "primary_experiment"):
        return sorted(scored_candidates)[:_ROUTE_TEXT_CANDIDATE_LIMIT]
    selected: dict[tuple[str, str], tuple[int, int, dict[str, Any]]] = {}
    selected_keys: set[tuple[str, str]] = set()
    section_counts: dict[str, int] = {}
    direct_result_candidates = [
        item
        for item in sorted(scored_candidates)
        if _route_text_candidate_is_direct_result(
            objective_context=objective_context,
            candidate=item[2],
        )
    ]
    for item in direct_result_candidates:
        candidate = item[2]
        source_key = (
            str(candidate.get("source_kind") or ""),
            str(candidate.get("source_ref") or ""),
        )
        selected[source_key] = item
        selected_keys.add(source_key)
        section_key = _objective_column_key(candidate.get("section_label"))
        section_counts[section_key] = section_counts.get(section_key, 0) + 1
        if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT // 2:
            break
    for item in sorted(scored_candidates):
        candidate = item[2]
        source_key = (
            str(candidate.get("source_kind") or ""),
            str(candidate.get("source_ref") or ""),
        )
        if source_key in selected_keys:
            continue
        section_key = _objective_column_key(candidate.get("section_label"))
        if section_counts.get(section_key, 0) >= _ROUTE_TREE_TEXT_SECTION_LIMIT:
            continue
        selected[source_key] = item
        selected_keys.add(source_key)
        section_counts[section_key] = section_counts.get(section_key, 0) + 1
        if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT // 2:
            break
    ordered_candidates = sorted(
        scored_candidates,
        key=lambda item: (
            item[1],
            str(item[2].get("source_ref") or ""),
        ),
    )
    for item in _evenly_spaced_tree_route_candidates(
        ordered_candidates,
        _ROUTE_TEXT_CANDIDATE_LIMIT - len(selected),
    ):
        candidate = item[2]
        source_key = (
            str(candidate.get("source_kind") or ""),
            str(candidate.get("source_ref") or ""),
        )
        if source_key in selected_keys:
            continue
        selected[source_key] = item
        selected_keys.add(source_key)
        if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT:
            break
    for item in sorted(scored_candidates):
        candidate = item[2]
        source_key = (
            str(candidate.get("source_kind") or ""),
            str(candidate.get("source_ref") or ""),
        )
        if source_key in selected_keys:
            continue
        selected[source_key] = item
        selected_keys.add(source_key)
        if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT:
            break
    return list(selected.values())


def _route_text_candidate_is_direct_result(
    *,
    objective_context: ResearchObjective,
    candidate: Mapping[str, Any],
) -> bool:
    text = str(candidate.get("text") or "")
    if not text:
        return False
    mentions_variable = any(
        property_matching.source_text_mentions_axis(text, axis)
        for axis in objective_context.variables
    )
    mentions_outcome = any(
        property_matching.source_text_mentions_axis(text, axis)
        for axis in objective_context.outcomes
    )
    if not mentions_outcome:
        return False
    text_haystack = text.casefold()
    if not mentions_variable:
        text_tokens = property_matching.axis_tokens(text_haystack)
        outcome_tokens = set().union(
            *(
                property_matching.axis_tokens(property_matching.axis_key(axis))
                for axis in objective_context.outcomes
            )
        )
        mentions_variable = any(
            any(
                len(token) >= 4
                and token not in {"base", "plate"}
                and token not in outcome_tokens
                and token in text_tokens
                for token in property_matching.axis_tokens(
                    property_matching.axis_key(axis)
                )
            )
            for axis in objective_context.variables
        )
    has_result_comparison = any(
        phrase in text_haystack
        for phrase in (
            "compared with",
            "compared to",
            "comparing",
            "decreased",
            "diminish",
            "exhibited",
            "higher than",
            "increased",
            "lower than",
            "not significantly influence",
            "observed",
            "prevent",
            "prohibit",
            "reduc",
            "resulted in",
            "resulted into",
            "significant effect",
            "unchanged",
        )
    )
    return has_result_comparison and (
        mentions_variable or "compared" in text_haystack or "comparing" in text_haystack
    )


def _evenly_spaced_tree_route_candidates(
    candidates: list[tuple[int, int, dict[str, Any]]],
    limit: int,
) -> list[tuple[int, int, dict[str, Any]]]:
    if limit <= 0:
        return []
    if limit >= len(candidates):
        return candidates
    if limit == 1:
        return [candidates[-1]]
    selected: list[tuple[int, int, dict[str, Any]]] = []
    seen_indexes: set[int] = set()
    last_index = len(candidates) - 1
    for position in range(limit):
        index = round(position * last_index / (limit - 1))
        if index in seen_indexes:
            continue
        selected.append(candidates[index])
        seen_indexes.add(index)
    return selected


def _route_text_candidates_use_frame_sections(
    frame: PaperAnalysisFrame,
) -> bool:
    if frame.relevant_text_source_refs:
        return True
    if not frame.relevant_sections:
        return False
    if frame.relevance == "high" and frame.paper_role == "primary_experiment":
        return False
    return True


def _route_tree_source_matches_frame(
    *,
    document_tree: SourceDocumentTree,
    node: Any,
    frame: PaperAnalysisFrame,
) -> bool:
    selected_source_refs = set(frame.relevant_text_source_refs)
    current = node
    while current is not None:
        if any(
            str(value or "").strip() in selected_source_refs
            for value in (
                getattr(current, "node_id", None),
                getattr(current, "source_ref_id", None),
            )
        ):
            return True
        parent_id = getattr(current, "parent_id", None)
        current = document_tree.nodes.get(parent_id) if parent_id else None
    return False


def _route_section_matches_frame(
    *,
    section_label: str,
    frame: PaperAnalysisFrame,
) -> bool:
    section_key = _objective_column_key(section_label)
    if not section_key:
        return False
    return any(
        section_key == frame_key
        or section_key.endswith(f"_{frame_key}")
        or frame_key.endswith(f"_{section_key}")
        for frame_key in (
            _objective_column_key(section) for section in frame.relevant_sections
        )
        if frame_key
    )


def _route_text_node_block_type(node: Any) -> str:
    node_type = str(getattr(node, "node_type", "") or "")
    if node_type == "caption":
        source_ref_kind = str(getattr(node, "source_ref_kind", "") or "")
        return "figure_caption" if source_ref_kind == "figure" else "paragraph"
    return node_type


def _tree_section_label_for_route_node(
    *,
    document_tree: SourceDocumentTree,
    node: Any,
    block: Any | None,
) -> str:
    if block is not None:
        section_label = _block_section_label(block)
        if section_label:
            return section_label
    section_path = _tree_node_section_path(
        document_tree=document_tree,
        node=node,
    )
    if section_path:
        return " > ".join(section_path)
    return "Unsectioned"


def _route_text_candidate_score(
    *,
    frame: PaperAnalysisFrame,
    objective_context: ResearchObjective,
    block_type: str,
    section_label: str,
    text: str,
) -> int:
    text_haystack = text.casefold()
    if "references" in _objective_column_key(section_label):
        return 0
    score = 0
    for term in (*objective_context.material_scope, *frame.material_match):
        term_text = str(term or "").strip().casefold()
        if term_text and term_text in text_haystack:
            score += 1
    objective_axis_keys = {
        property_matching.axis_key(term)
        for term in (*objective_context.variables, *objective_context.outcomes)
    }
    for term in (*objective_context.variables, *objective_context.outcomes):
        if property_matching.source_text_mentions_axis(text, term):
            score += 4
    for term in (*frame.changed_variables, *frame.measured_property_scope):
        if property_matching.axis_key(
            term
        ) not in objective_axis_keys and property_matching.source_text_mentions_axis(
            text, term
        ):
            score += 1
    for term in frame.test_environment_scope:
        term_text = str(term or "").strip().casefold()
        if term_text and term_text in text_haystack:
            score += 2
    score += _route_text_numeric_mechanism_score(
        section_label=section_label,
        text=text,
    )
    section_key = _objective_column_key(section_label)
    if section_key.startswith(("3_", "4_")) or "conclusion" in section_key:
        score += 3
    if block_type in {"figure_caption", "list_item"}:
        score += 1
    if any(
        token in text_haystack
        for token in (
            "affect",
            "compared",
            "comparison",
            "exhibited",
            "observed",
            "result",
            "showed",
        )
    ):
        score += 2
    if any(
        token in text_haystack
        for token in (
            "fabricated",
            "processed",
            "treated",
            "treatment",
        )
    ):
        score += 2
    return score if score >= 4 else 0


def _route_text_numeric_mechanism_score(
    *,
    section_label: str,
    text: str,
) -> int:
    if not _NUMBER_PATTERN.search(text):
        return 0
    haystack = " ".join(
        part
        for part in (
            str(section_label or "").casefold(),
            str(text or "").casefold(),
        )
        if part
    )
    if not any(
        token in haystack
        for token in (
            "cooling rate",
            "thermal gradient",
            "thermal simulation",
            "melt pool",
            "width to depth",
            "width/depth",
            "residual stress",
            "recrystallization",
        )
    ):
        return 0
    score = 4
    if any(token in haystack for token in ("microstructure", "thermal", "stress")):
        score += 1
    return score


def _build_route_table_schema(table: Any) -> dict[str, Any]:
    matrix = tuple(getattr(table, "table_matrix", ()) or ())
    return {
        "table_id": str(getattr(table, "table_id", "") or ""),
        "caption_text": getattr(table, "caption_text", None),
        "heading_path": getattr(table, "heading_path", None),
        "column_headers": [
            str(value) for value in getattr(table, "column_headers", ()) or ()
        ],
        "row_count": int(getattr(table, "row_count", 0) or 0),
        "col_count": int(getattr(table, "col_count", 0) or 0),
        "sample_rows": [
            [str(cell) for cell in row]
            for row in matrix[:_FRAME_TABLE_ROW_LIMIT]
            if isinstance(row, (list, tuple))
        ],
    }


def _route_table_schema_record(
    *,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if candidate.get("source_kind") != "table":
        return {}
    candidate_schema = candidate.get("table_schema")
    return dict(candidate_schema) if isinstance(candidate_schema, dict) else {}


def _normalize_route_extractable(record: dict[str, Any]) -> bool:
    role = str(record.get("role") or "").strip()
    if role == "low_value_or_irrelevant":
        return False
    if role in _OBJECTIVE_EXTRACTABLE_ROUTE_ROLES:
        return True
    return bool(record.get("extractable"))


def _block_section_label(block: Any) -> str:
    block_type = str(getattr(block, "block_type", "") or "")
    if block_type == "heading":
        heading = str(getattr(block, "text", "") or "").strip()
        if heading:
            return heading
    section_label = str(getattr(block, "heading_path", "") or "").strip()
    return section_label or "Unsectioned"


def _build_objective_table_routing_hints(
    objective: ResearchObjective,
    *,
    tables: tuple[Any, ...],
) -> tuple[SourceSelectionHint, ...]:
    hints: list[SourceSelectionHint] = []
    excluded_document_ids = set(objective.excluded_document_ids)
    for table in tables:
        document_id = str(getattr(table, "document_id", "") or "")
        if document_id in excluded_document_ids:
            continue
        table_text = _objective_table_search_text(table)
        property_search_pieces = [
            " ".join(str(value) for value in getattr(table, "column_headers", ()) or ())
        ]
        for row in tuple(getattr(table, "table_matrix", ()) or ())[:6]:
            if isinstance(row, (list, tuple)):
                property_search_pieces.append(" ".join(str(cell) for cell in row))
        property_table_text = " ".join(
            piece for piece in property_search_pieces if piece.strip()
        )
        matched_outcomes = [
            axis
            for axis in objective.outcomes
            if property_matching.source_text_mentions_axis(
                property_table_text,
                axis,
            )
        ]
        matched_variable_axes = [
            axis
            for axis in objective.variables
            if property_matching.source_text_mentions_axis(table_text, axis)
        ]
        if matched_outcomes:
            role = "result_table"
            strength = (
                "strong"
                if matched_variable_axes or len(matched_outcomes) > 1
                else "medium"
            )
        elif matched_variable_axes:
            role = "condition_context"
            strength = "strong" if len(matched_variable_axes) > 1 else "medium"
        else:
            continue
        hints.append(
            SourceSelectionHint.from_mapping(
                {
                    "table_id": str(getattr(table, "table_id", "") or ""),
                    "document_id": document_id,
                    "caption_text": getattr(table, "caption_text", None),
                    "role": role,
                    "strength": strength,
                    "matched_outcomes": matched_outcomes,
                    "matched_variables": matched_variable_axes,
                    "reason": _build_objective_table_routing_reason(
                        role,
                        matched_variable_axes=matched_variable_axes,
                    ),
                }
            )
        )
    return tuple(hints)


def _objective_table_search_text(table: Any) -> str:
    pieces = [
        str(getattr(table, "caption_text", "") or ""),
        " ".join(str(value) for value in getattr(table, "column_headers", ()) or ()),
    ]
    for row in tuple(getattr(table, "table_matrix", ()) or ())[:6]:
        if isinstance(row, (list, tuple)):
            pieces.append(" ".join(str(cell) for cell in row))
    return " ".join(piece for piece in pieces if piece.strip())


def _build_objective_table_routing_reason(
    role: str,
    *,
    matched_variable_axes: list[str],
) -> str:
    if role == "result_table":
        if matched_variable_axes:
            return (
                "Table contains target property columns and variable process columns."
            )
        return "Table contains target property columns."
    return "Table contains variable process columns and can provide condition context."


def _document_tree_nodes_in_order(
    document_tree: SourceDocumentTree,
) -> list[Any]:
    return sorted(
        document_tree.nodes.values(),
        key=lambda node: (int(getattr(node, "order", 0) or 0), node.node_id),
    )


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
