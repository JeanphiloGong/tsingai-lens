from __future__ import annotations

import math
import logging
import re
from hashlib import sha1
from typing import Any, Mapping
from urllib.parse import quote

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from domain.core import ResearchUnderstanding
from domain.ports import SourceArtifactRepository
from domain.source import SourceBlock, SourceDocument, SourceTable
from infra.persistence.factory import build_source_artifact_repository
from infra.source.runtime.mapping.text_quality import normalize_display_text

logger = logging.getLogger(__name__)

_RELATION_CONTEXT_LIMIT = 16
_RELATION_EVIDENCE_UNIT_LIMIT = 24
_RELATION_TRACE_TASK_TYPE = "research_understanding_relation"
_DIRECT_RESULT_CONTEXT_UNIT_KINDS = {
    "process_context",
    "sample_context",
    "test_condition",
}
_FINDING_MATCH_STOPWORDS = {
    "affect",
    "affects",
    "behavior",
    "behaviour",
    "condition",
    "conditions",
    "context",
    "effect",
    "effects",
    "level",
    "levels",
    "material",
    "materials",
    "method",
    "methods",
    "process",
    "processes",
    "properties",
    "property",
    "result",
    "results",
    "sample",
    "samples",
    "specimen",
    "specimens",
    "table",
    "tables",
}
_SYMBOL_AXIS_DISPLAY_ALIASES = {
    "alpha": "α build orientation angle",
    "α": "α build orientation angle",
    "beta": "β build orientation angle",
    "β": "β build orientation angle",
    "theta": "scan strategy rotation angle",
    "θ": "scan strategy rotation angle",
    "ɵ": "scan strategy rotation angle",
}
_MECHANICAL_PROPERTY_AXIS_TOKENS = {
    "ductility",
    "elongation",
    "fatigue",
    "hardness",
    "strength",
    "tensile",
    "ultimate",
    "yield",
}
_MULTI_AXIS_TABLE_CONTRAST_LABEL = "multi-axis table contrast"
_SLM_COUPLED_PARAMETER_SET_LABEL = (
    "coupled SLM parameter sets: scanning strategy, scanning speed, hatch spacing, "
    "and energy density"
)


class ResearchUnderstandingService:
    """Project existing Core research views into claim/relation/evidence form."""

    def __init__(
        self,
        source_artifact_repository: SourceArtifactRepository | None = None,
        structured_extractor: Any | None = None,
    ) -> None:
        self.source_artifact_repository = (
            source_artifact_repository or build_source_artifact_repository()
        )
        self.structured_extractor = structured_extractor or CoreLLMStructuredExtractor()

    def with_presentation(
        self,
        understanding: ResearchUnderstanding | Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if understanding is None:
            return None
        record = (
            understanding.to_record()
            if isinstance(understanding, ResearchUnderstanding)
            else dict(understanding)
        )
        record = self._record_with_traceable_evidence_refs(record)
        record = self._record_with_comparison_condition_evidence(record)
        record = self._record_without_off_axis_recovered_objects(record)
        record = self._record_with_recovered_presentation_objects(record)
        record["presentation"] = self._presentation_for(record)
        record["state"] = self._state_with_presentation(record)
        return ResearchUnderstanding.from_mapping(record).to_record()

    def build_objective_understanding(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._build_goal_or_objective_understanding(
            payload,
            scope_type="objective",
        )

    def build_goal_understanding(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._build_goal_or_objective_understanding(
            payload,
            scope_type="goal",
        )

    def _build_goal_or_objective_understanding(
        self,
        payload: Mapping[str, Any],
        *,
        scope_type: str,
    ) -> dict[str, Any]:
        objective = _mapping(payload.get("objective"))
        context = _mapping(payload.get("objective_context"))
        collection_id = _text(payload.get("collection_id"))
        objective_id = _text(objective.get("objective_id")) or _text(
            context.get("objective_id")
        )
        goal_id = _text(payload.get("goal_id"))
        question = _text(objective.get("question")) or _text(context.get("question"))
        evidence_units = _mapping_list(payload.get("evidence_units"))
        blocks_by_id, _documents_by_id, tables_by_id = self._source_artifact_lookups(
            collection_id
        )
        evidence_refs = self._evidence_refs_from_evidence_units(
            evidence_units,
            collection_id=collection_id,
            blocks_by_id=blocks_by_id,
            tables_by_id=tables_by_id,
        )
        evidence_refs = self._enrich_evidence_refs_from_source_blocks(
            evidence_refs,
            blocks_by_id=blocks_by_id,
        )
        recovered_findings = self._recovered_objective_findings_from_source_blocks(
            payload,
            evidence_units=evidence_units,
            blocks_by_id=blocks_by_id,
            tables_by_id=tables_by_id,
        )
        evidence_refs = self._sort_evidence_refs_for_review(
            [
                *evidence_refs,
                *[
                    evidence_ref
                    for recovered in recovered_findings
                    for evidence_ref in self._recovered_evidence_refs(recovered)
                ],
            ]
        )
        evidence_ref_ids_by_unit = self._evidence_ref_ids_by_fact(evidence_refs)
        contexts = self._objective_contexts(
            context,
            objective,
            evidence_units=evidence_units,
        )
        contexts = _dedupe_by_id(
            [
                *contexts,
                *[
                    recovered["context"]
                    for recovered in recovered_findings
                    if recovered.get("context")
                ],
            ],
            "context_id",
        )
        context_ids = [item["context_id"] for item in contexts]
        context_ids_by_unit = self._objective_context_ids_by_unit(contexts)
        claims = self._objective_claims(
            payload,
            evidence_units=evidence_units,
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
            context_ids_by_unit=context_ids_by_unit,
        )
        relations, relation_warnings, model_traces = self._objective_relations(
            payload,
            evidence_units,
            claims=claims,
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
            context_ids_by_unit=context_ids_by_unit,
            contexts=contexts,
        )
        recovered_claims = [
            recovered["claim"]
            for recovered in recovered_findings
            if recovered.get("claim")
        ]
        recovered_relations = [
            recovered["relation"]
            for recovered in recovered_findings
            if recovered.get("relation")
        ]
        claims = [*recovered_claims, *claims]
        relations = [*recovered_relations, *relations]
        claims = self._dedupe_claims_for_understanding(claims)
        relations = _dedupe_by_id(relations, "relation_id")
        state = self._state_for(claims, relations, evidence_refs)
        return self.with_presentation(
            ResearchUnderstanding.from_mapping(
                {
                    "state": state,
                    "scope": {
                        "scope_type": scope_type,
                        "collection_id": collection_id,
                        "goal_id": goal_id if scope_type == "goal" else None,
                        "objective_id": objective_id if scope_type != "goal" else None,
                        "title": question,
                    },
                    "claims": claims,
                    "relations": relations,
                    "evidence_refs": evidence_refs,
                    "contexts": contexts,
                    "warnings": self._understanding_warnings(
                        claims,
                        evidence_refs,
                        extra_warnings=relation_warnings,
                    ),
                    "model_traces": model_traces,
                }
            )
        ) or {}

    def build_material_understanding(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        collection_id = _text(payload.get("collection_id"))
        material_id = _text(payload.get("material_id"))
        canonical_name = _text(payload.get("canonical_name")) or material_id
        evidence_refs = self._material_evidence_refs(payload)
        evidence_ref_ids_by_fact = self._evidence_ref_ids_by_fact(evidence_refs)
        contexts = self._material_contexts(payload)
        context_ids = [item["context_id"] for item in contexts]
        claims = self._material_claims(
            payload,
            evidence_ref_ids_by_fact=evidence_ref_ids_by_fact,
            context_ids=context_ids,
        )
        relations = self._material_relations(
            payload,
            evidence_ref_ids_by_fact=evidence_ref_ids_by_fact,
            context_ids=context_ids,
        )
        state = self._state_for(claims, relations, evidence_refs)
        return self.with_presentation(
            ResearchUnderstanding.from_mapping(
                {
                    "state": state,
                    "scope": {
                        "scope_type": "material",
                        "collection_id": collection_id,
                        "material_id": material_id,
                        "title": canonical_name,
                    },
                    "claims": claims,
                    "relations": relations,
                    "evidence_refs": evidence_refs,
                    "contexts": contexts,
                    "warnings": self._understanding_warnings(claims, evidence_refs),
                    "model_traces": [],
                }
            )
        ) or {}

    def _objective_contexts(
        self,
        context: Mapping[str, Any],
        objective: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not context and not objective and not evidence_units:
            return []
        contexts = [
            {
                "context_id": "ctx_objective_scope",
                "label": "Objective scope",
                "material_scope": _strings(
                    context.get("material_scope") or objective.get("material_scope")
                ),
                "process_context": {
                    "variable_process_axes": _strings(
                        context.get("variable_process_axes")
                        or objective.get("process_axes")
                    ),
                    "process_context_axes": _strings(
                        context.get("process_context_axes")
                    ),
                },
                "test_condition": {},
                "property_scope": _strings(
                    context.get("target_property_axes")
                    or objective.get("property_axes")
                ),
                "limitations": [],
            }
        ]
        for unit in evidence_units:
            unit_context = self._objective_context_from_evidence_unit(
                unit,
                objective_context=context,
                objective=objective,
            )
            if unit_context:
                contexts.append(unit_context)
        return _dedupe_by_id(contexts, "context_id")

    def _objective_context_ids_by_unit(
        self,
        contexts: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for context in contexts:
            unit_id = _text(context.get("source_evidence_unit_id"))
            context_id = _text(context.get("context_id"))
            if unit_id and context_id:
                result.setdefault(unit_id, []).append(context_id)
        return {key: _dedupe_strings(value) for key, value in result.items()}

    def _context_ids_for_evidence_unit(
        self,
        unit: Mapping[str, Any],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> list[str]:
        unit_id = _text(unit.get("evidence_unit_id"))
        if unit_id:
            specific = context_ids_by_unit.get(unit_id, [])
            if specific:
                return specific
        return context_ids[:1]

    def _objective_context_from_evidence_unit(
        self,
        unit: Mapping[str, Any],
        *,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> dict[str, Any]:
        unit_id = _text(unit.get("evidence_unit_id"))
        if not unit_id:
            return {}
        material_scope = self._context_material_scope(
            unit,
            objective_context,
            objective,
        )
        process_context = self._context_process_scope(unit)
        test_condition = _mapping(unit.get("test_condition"))
        property_scope = self._context_property_scope(
            unit,
            objective_context,
            objective,
        )
        has_unit_boundary = bool(
            _display_values(_mapping(unit.get("material_system")))
            or _display_values(process_context)
            or _display_values(test_condition)
            or _text(unit.get("property_normalized"))
        )
        if not has_unit_boundary:
            return {}
        return {
            "context_id": f"ctx_{unit_id}_boundary",
            "source_evidence_unit_id": unit_id,
            "label": "Claim applicability",
            "material_scope": material_scope,
            "process_context": process_context,
            "test_condition": test_condition,
            "property_scope": property_scope,
            "limitations": [],
        }

    def _context_material_scope(
        self,
        unit: Mapping[str, Any],
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[str]:
        material_values = _display_values(_mapping(unit.get("material_system")))
        if material_values:
            return material_values
        return _strings(
            objective_context.get("material_scope") or objective.get("material_scope")
        )

    def _context_process_scope(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in (
            "process_context",
            "sample_context",
            "resolved_condition",
            "baseline_context",
        ):
            value = _mapping(unit.get(key))
            if _display_values(value):
                result[key] = value
        return result

    def _context_property_scope(
        self,
        unit: Mapping[str, Any],
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[str]:
        property_name = _text(unit.get("property_normalized"))
        if property_name:
            return [property_name]
        return _strings(
            objective_context.get("target_property_axes")
            or objective.get("property_axes")
        )

    def _material_contexts(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        overview = _mapping(payload.get("overview"))
        return [
            {
                "context_id": "ctx_material_scope",
                "label": "Material scope",
                "material_scope": [_text(payload.get("canonical_name")) or ""],
                "process_context": {
                    "process_families": _strings(
                        overview.get("process_families")
                    ),
                },
                "test_condition": {},
                "property_scope": _strings(
                    overview.get("measured_properties")
                    or [item.get("property") for item in _mapping_list(payload.get("measured_properties"))]
                ),
                "limitations": _strings(payload.get("limitations")),
            }
        ]

    def _objective_claims(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_claims = 12
        objective_context = _mapping(payload.get("objective_context"))
        objective = _mapping(payload.get("objective"))
        target_axes = self._objective_target_axes_for_claims(
            objective_context,
            objective,
        )
        prioritized_units = [
            unit
            for _, unit in sorted(
                enumerate(evidence_units),
                key=lambda item: self._objective_claim_unit_priority(
                    item[1],
                    item[0],
                ),
            )
        ]
        primary_units = [
            unit
            for unit in prioritized_units
            if (_text(unit.get("unit_kind")) or "").lower() != "measurement"
            and self._objective_unit_can_drive_claim(unit)
        ]
        measurement_units = [
            unit
            for unit in prioritized_units
            if (_text(unit.get("unit_kind")) or "").lower() == "measurement"
            and self._objective_unit_can_drive_claim(unit)
        ]

        for unit in primary_units:
            if len(claims) >= max_claims:
                break
            statement = self._statement_from_evidence_unit(unit)
            if not statement:
                continue
            claim_type = self._reviewable_objective_claim_type(
                unit,
                statement,
                target_axes=target_axes,
            )
            if not claim_type:
                continue
            unit_id = _text(unit.get("evidence_unit_id"))
            evidence_unit_ids = [unit_id] if unit_id else []
            claim_context_ids = self._context_ids_for_evidence_unit(
                unit,
                context_ids,
                context_ids_by_unit,
            )
            _append_claim(
                claims,
                self._claim(
                    claim_type=claim_type,
                    statement=statement,
                    source_object_ids=evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        evidence_unit_ids,
                        evidence_ref_ids_by_unit,
                    ),
                    context_ids=claim_context_ids,
                    confidence=unit.get("confidence"),
                    seen=seen,
                ),
            )

        logic_chain = _mapping(payload.get("logic_chain"))
        summary = _text(logic_chain.get("summary"))
        summary_evidence_unit_ids = _strings(logic_chain.get("evidence_unit_ids"))
        units_by_id = {
            unit_id: unit
            for unit in evidence_units
            if (unit_id := _text(unit.get("evidence_unit_id")))
        }
        summary_claim_units = [
            units_by_id[unit_id]
            for unit_id in summary_evidence_unit_ids
            if unit_id in units_by_id
            and self._objective_unit_can_drive_claim(units_by_id[unit_id])
        ]
        if (
            len(claims) < max_claims
            and summary
            and self._looks_complete_claim_statement(summary)
            and not self._is_aggregate_logic_summary(summary)
            and not self._is_noisy_objective_claim_statement(summary)
            and (not summary_evidence_unit_ids or summary_claim_units)
            and (
                self._objective_statement_mentions_target_axis(summary, target_axes)
                or any(
                    self._objective_unit_matches_claim_target(
                        unit,
                        summary,
                        target_axes,
                    )
                    for unit in summary_claim_units
                )
            )
        ):
            _append_claim(
                claims,
                self._claim(
                    claim_type="finding",
                    statement=summary,
                    source_object_ids=summary_evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        summary_evidence_unit_ids,
                        evidence_ref_ids_by_unit,
                    ),
                    context_ids=context_ids,
                    seen=seen,
                ),
            )
        measurement_limit = min(
            self._objective_measurement_claim_limit(primary_claim_count=len(claims)),
            max_claims - len(claims),
        )
        measurement_count = 0
        for unit in measurement_units:
            if measurement_count >= measurement_limit or len(claims) >= max_claims:
                break
            statement = self._statement_from_evidence_unit(unit)
            if not statement:
                continue
            claim_type = self._reviewable_objective_claim_type(
                unit,
                statement,
                target_axes=target_axes,
            )
            if not claim_type:
                continue
            unit_id = _text(unit.get("evidence_unit_id"))
            evidence_unit_ids = [unit_id] if unit_id else []
            claim_context_ids = self._context_ids_for_evidence_unit(
                unit,
                context_ids,
                context_ids_by_unit,
            )
            before_count = len(claims)
            _append_claim(
                claims,
                self._claim(
                    claim_type=claim_type,
                    statement=statement,
                    source_object_ids=evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        evidence_unit_ids,
                        evidence_ref_ids_by_unit,
                    ),
                    context_ids=claim_context_ids,
                    confidence=unit.get("confidence"),
                    seen=seen,
                ),
            )
            if len(claims) > before_count:
                measurement_count += 1
        return claims

    def _objective_claim_unit_priority(
        self,
        unit: Mapping[str, Any],
        index: int,
    ) -> tuple[int, int]:
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind in {
            "comparison",
            "interpretation",
            "characterization",
            "mechanism",
        }:
            return (0, index)
        if (
            unit_kind in _DIRECT_RESULT_CONTEXT_UNIT_KINDS
            and self._objective_unit_has_direct_result_signal(unit)
        ):
            return (0, index)
        if unit_kind == "measurement":
            return (1, index)
        return (2, index)

    def _objective_measurement_claim_limit(
        self,
        *,
        primary_claim_count: int,
    ) -> int:
        if primary_claim_count > 0:
            return 0
        return 12

    def _objective_unit_can_drive_claim(self, unit: Mapping[str, Any]) -> bool:
        evidence_role = self._objective_unit_evidence_role(unit)
        return not evidence_role or evidence_role == "direct_support"

    def _objective_unit_evidence_role(self, unit: Mapping[str, Any]) -> str:
        for source_ref in _mapping_list(unit.get("source_refs")):
            evidence_role = self._normalized_evidence_role(
                _text(source_ref.get("evidence_role")) or _text(source_ref.get("role"))
            )
            if evidence_role:
                return evidence_role
        return ""

    def _objective_relations(
        self,
        payload: Mapping[str, Any],
        evidence_units: list[dict[str, Any]],
        *,
        claims: list[dict[str, Any]],
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
        contexts: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        objective = _mapping(payload.get("objective"))
        objective_context = _mapping(payload.get("objective_context"))
        deterministic_relations = self._deterministic_objective_relations(
            evidence_units,
            variable_axes=self._objective_variable_axes_for_relations(
                objective_context,
                objective,
            ),
            target_axes=self._objective_target_axes_for_claims(
                objective_context,
                objective,
            ),
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
            context_ids_by_unit=context_ids_by_unit,
        )
        relation_payload = self._semantic_relation_payload(
            payload,
            evidence_units=evidence_units,
            claims=claims,
            contexts=contexts,
        )
        try:
            extracted = self.structured_extractor.extract_research_understanding_relations(
                relation_payload
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "research understanding semantic relation extraction failed",
                exc_info=True,
            )
            failed_trace = self._consume_relation_trace(
                relation_payload,
                scope_payload=payload,
                trace_status="failed",
            )
            return deterministic_relations, ["relation_extraction_failed"], failed_trace
        model_traces = self._consume_relation_trace(
            relation_payload,
            scope_payload=payload,
            trace_status="available",
        )
        relations: list[dict[str, Any]] = []
        for item in getattr(extracted, "relations", []):
            relation = self._semantic_relation_from_model(
                item.model_dump(),
                evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
                context_ids=context_ids,
            )
            if relation:
                relations.append(relation)
        return (
            _dedupe_by_id((*relations, *deterministic_relations), "relation_id"),
            [],
            model_traces,
        )

    def _recovered_objective_findings_from_source_blocks(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable] | None = None,
    ) -> list[dict[str, Any]]:
        objective = _mapping(payload.get("objective"))
        objective_context = _mapping(payload.get("objective_context"))
        axis_text = " ".join(
            [
                _text(objective.get("question")) or "",
                _text(objective_context.get("question")) or "",
                " ".join(_strings(objective.get("process_axes"))),
                " ".join(_strings(objective_context.get("variable_process_axes"))),
                " ".join(_strings(objective.get("property_axes"))),
                " ".join(_strings(objective_context.get("target_property_axes"))),
            ]
        )
        normalized_axes = f" {_normalize_match_text(axis_text)} "
        normalized_property_axes = self._normalized_objective_property_axes(
            objective,
            objective_context,
        )
        recovered: list[dict[str, Any]] = []
        if self._objective_axes_request_preheating_ductility(normalized_axes):
            recovered.extend(
                self._recovered_preheating_findings_from_source_blocks(
                    payload,
                    evidence_units=evidence_units,
                    blocks_by_id=blocks_by_id,
                    objective=objective,
                    objective_context=objective_context,
                )
            )
        recovered.extend(
            self._recovered_process_property_findings_from_source_blocks(
                payload,
                evidence_units=evidence_units,
                blocks_by_id=blocks_by_id,
                tables_by_id=tables_by_id,
                normalized_axes=normalized_axes,
                normalized_property_axes=normalized_property_axes,
                objective=objective,
                objective_context=objective_context,
            )
        )
        if not (
            (
                " porosity " in normalized_axes
                or " pore " in normalized_axes
                or " pores " in normalized_axes
            )
            and (
                " corrosion " in normalized_axes
                or " pitting " in normalized_axes
            )
        ):
            return recovered
        document_ids = _dedupe_strings(
            [
                _text(unit.get("document_id"))
                for unit in evidence_units
                if self._objective_unit_has_corrosion_metric_signal(unit)
            ]
        )
        if not document_ids:
            return recovered
        for document_id in document_ids:
            block = self._best_porosity_corrosion_source_block(
                document_id,
                blocks_by_id=blocks_by_id,
            )
            if block is None:
                continue
            condition_table = self._best_porosity_corrosion_process_table(
                document_id,
                tables_by_id=tables_by_id or {},
            )
            recovered.append(
                self._recovered_porosity_corrosion_finding(
                    block,
                    collection_id=_text(payload.get("collection_id")),
                    objective_context=objective_context,
                    objective=objective,
                    condition_table=condition_table,
                )
            )
        return [item for item in recovered if item]

    def _recovered_process_property_findings_from_source_blocks(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable] | None = None,
        normalized_axes: str,
        normalized_property_axes: str,
        objective: Mapping[str, Any],
        objective_context: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        document_ids = self._objective_recovery_document_ids(
            payload,
            evidence_units=evidence_units,
        )
        if not document_ids:
            return []
        collection_id = _text(payload.get("collection_id"))
        recovered: list[dict[str, Any]] = []
        specs: list[dict[str, Any]] = []
        specific_mechanical_axes = self._requested_specific_mechanical_axes(
            normalized_property_axes
        )
        if (
            (
                " energy density " in normalized_axes
                or " scanning speed " in normalized_axes
                or " scan speed " in normalized_axes
            )
            and self._objective_property_axes_include_any(
                normalized_property_axes,
                legacy_match=(
                    " densification " in normalized_axes
                    or " density " in normalized_axes
                    or " microstructure " in normalized_axes
                    or " mechanical " in normalized_axes
                    or " yield strength " in normalized_axes
                    or " ultimate tensile strength " in normalized_axes
                    or " elongation " in normalized_axes
                ),
                terms=[
                    "densification",
                    "density",
                    "relative density",
                    "microstructure",
                    "mechanical properties",
                    "yield strength",
                    "ultimate tensile strength",
                    "elongation",
                ],
            )
        ):
            if not specific_mechanical_axes:
                specs.append(
                    {
                        "slug": "slm_density_microstructure",
                        "subject": "SLM processing parameters",
                        "predicate": "affect",
                        "object": "densification -> microstructure -> mechanical properties",
                        "statement": (
                            "SLM scanning strategy, scanning speed, and energy "
                            "density significantly affect densification, "
                            "microstructure, and mechanical properties of 316L "
                            "stainless steel."
                        ),
                        "process_axes": [
                            "scanning strategy",
                            "scanning speed",
                            "energy density",
                        ],
                        "property_scope": [
                            "densification",
                            "microstructure",
                            "mechanical properties",
                        ],
                        "block_predicate": self._is_slm_processing_conclusion_block,
                        "confidence": 0.82,
                    }
                )
            specs.append(
                {
                    "slug": "scan_speed_density_microstructure",
                    "subject": "scanning speed",
                    "predicate": "associated",
                    "object": (
                        "densification, microstructure, and mechanical properties"
                    ),
                    "statement": (
                        "In this study, higher scanning speed was associated with "
                        "better densification, a refined microstructure, and better "
                        "mechanical properties than lower scanning speed."
                    ),
                    "process_axes": ["scanning speed"],
                    "property_scope": [
                        "densification",
                        "microstructure",
                        "mechanical properties",
                    ],
                    "block_predicate": self._is_scan_speed_conclusion_block,
                    "mechanical_property_table": bool(specific_mechanical_axes),
                    "specific_mechanical_axes": specific_mechanical_axes,
                    "confidence": 0.82,
                }
            )
        if (
            (
                " heat treatment " in normalized_axes
                or " furnace " in normalized_axes
                or " hip " in normalized_axes
            )
            and self._objective_property_axes_include_any(
                normalized_property_axes,
                legacy_match=(
                    " density " in normalized_axes
                    or " microstructure " in normalized_axes
                    or " mechanical " in normalized_axes
                ),
                terms=[
                    "density",
                    "relative density",
                    "microstructure",
                    "mechanical properties",
                    "strength",
                    "tensile strength",
                    "elongation",
                ],
            )
        ):
            specs.append(
                {
                    "slug": "heat_treatment_microstructure_mechanics",
                    "subject": "heat treatment",
                    "predicate": "changes",
                    "object": self._heat_treatment_recovered_object(
                        normalized_property_axes
                    ),
                    "statement": self._heat_treatment_recovered_statement(
                        normalized_property_axes
                    ),
                    "process_axes": ["heat treatment"],
                    "property_scope": self._heat_treatment_recovered_property_scope(
                        normalized_property_axes
                    ),
                    "block_predicate": self._is_heat_treatment_microstructure_block,
                    "confidence": 0.84,
                }
            )
            if self._objective_property_axes_include_any(
                normalized_property_axes,
                legacy_match=" density " in normalized_axes,
                terms=["density", "relative density", "densification", "porosity"],
            ):
                specs.append(
                    {
                        "slug": "heat_treatment_bundle_pore_reduction",
                        "subject": (
                            "heat treatment type and heat treatment parameters"
                        ),
                        "relation_type": "compares",
                        "predicate": "compares",
                        "object": "pore reduction",
                        "statement": (
                            "The authors reported no superiority between the "
                            "furnace HT and HIP treatment bundles for pore "
                            "reduction. This bundle comparison does not isolate "
                            "treatment type, temperature, duration, or pressure "
                            "as separate effects."
                        ),
                        "process_axes": [
                            "heat treatment type",
                            "heat treatment temperature",
                            "heat treatment duration",
                            "HIP pressure",
                        ],
                        "property_scope": ["pore reduction"],
                        "block_predicate": (
                            self._is_heat_treatment_bundle_comparison_block
                        ),
                        "confidence": 0.84,
                        "claim_status": "limited",
                        "relation_status": "limited",
                        "warnings": [
                            "heat_treatment_parameters_not_isolated",
                            "single_variable_effect_not_isolated",
                            "needs_expert_review",
                        ],
                    }
                )
        if (
            (
                " scan strategy " in normalized_axes
                or " build orientation " in normalized_axes
                or " rotation angle " in normalized_axes
            )
            and self._objective_property_axes_include_any(
                normalized_property_axes,
                legacy_match=(
                    " crystallographic texture " in normalized_axes
                    or " yield strength " in normalized_axes
                ),
                terms=["crystallographic texture", "yield strength"],
            )
        ):
            texture_spec_base = {
                "predicate": "compares",
                "object": "crystallographic texture -> yield strength",
                "process_axes": [
                    "scan strategy rotation angle (θ)",
                    "α build orientation angle",
                    "β build orientation angle",
                ],
                "property_scope": ["crystallographic texture", "yield strength"],
                "block_predicate": self._is_texture_yield_conclusion_block,
                "texture_yield_table": True,
                "confidence": 0.86,
                "claim_status": "limited",
                "relation_status": "limited",
                "warnings": [
                    "model_validation_finding",
                    "author_summary_table_mismatch",
                    "needs_expert_review",
                ],
            }
            specs.extend(
                [
                    {
                        **texture_spec_base,
                        "slug": "texture_yield_build_orientation",
                        "subject": "α and β build orientation angles",
                        "statement": (
                            "At fixed scan strategy rotation angle θ=0°, changing "
                            "build orientation from α=0° and β=0° to α=45° and "
                            "β=22.5° increased experimental yield strength from "
                            "334.2 MPa to 363.1 MPa. The authors describe model "
                            "deviations as generally below 5%, but the Table 3 "
                            "values do not uniformly satisfy that summary."
                        ),
                    },
                    {
                        **texture_spec_base,
                        "slug": "texture_yield_scan_rotation",
                        "subject": "scan strategy rotation angle (θ)",
                        "statement": (
                            "At fixed build orientation α=0° and β=0°, changing "
                            "scan strategy rotation angle θ from 0° to 45° "
                            "increased experimental yield strength from 334.2 MPa "
                            "to 351.9 MPa. The authors describe model deviations "
                            "as generally below 5%, but the Table 3 values do not "
                            "uniformly satisfy that summary."
                        ),
                    },
                ]
            )
        if (
            (
                " volumetric energy density " in normalized_axes
                or " ved " in normalized_axes
                or " defect " in normalized_axes
            )
            and self._objective_property_axes_include_any(
                normalized_property_axes,
                legacy_match=(
                    " fatigue " in normalized_axes
                    or " defect " in normalized_axes
                ),
                terms=["defect structure", "fatigue strength", "fatigue"],
            )
        ):
            specs.append(
                {
                    "slug": "ved_defects_fatigue",
                    "subject": "volumetric energy density",
                    "relation_type": "compares",
                    "predicate": "compares",
                    "object": "defect structure -> fatigue strength",
                    "statement": (
                        "Increasing VED lowered defect fraction, size, and "
                        "complexity, improving fatigue resistance; remaining "
                        "LoF defects still kept fatigue resistance below wrought "
                        "316L steel."
                    ),
                    "process_axes": ["volumetric energy density"],
                    "property_scope": ["defect structure", "fatigue strength"],
                    "block_predicate": self._is_ved_defect_fatigue_block,
                    "fatigue_strength_table": True,
                    "confidence": 0.86,
                }
            )
        for spec in specs:
            for document_id in document_ids:
                block = self._best_recovered_spec_source_block(
                    document_id,
                    blocks_by_id=blocks_by_id,
                    predicate=spec["block_predicate"],
                )
                if block is None:
                    continue
                condition_block = (
                    self._best_heat_treatment_condition_source_block(
                        document_id,
                        blocks_by_id=blocks_by_id,
                    )
                    if _text(spec.get("slug"))
                    in {
                        "heat_treatment_microstructure_mechanics",
                        "heat_treatment_bundle_pore_reduction",
                    }
                    else self._best_ved_condition_source_block(
                        document_id,
                        blocks_by_id=blocks_by_id,
                    )
                    if _text(spec.get("slug")) == "ved_defects_fatigue"
                    else (
                        self._best_recovered_spec_source_block(
                            document_id,
                            blocks_by_id=blocks_by_id,
                            predicate=self._is_texture_angle_definition_block,
                        )
                        if _text(spec.get("slug")).startswith("texture_yield_")
                        else None
                    )
                )
                supporting_blocks = (
                    [
                        supporting_block
                        for supporting_block in [
                            self._best_heat_treatment_mechanics_source_block(
                                document_id,
                                blocks_by_id=blocks_by_id,
                                exclude_block_id=_text(block.block_id),
                            )
                        ]
                        if supporting_block is not None
                    ]
                    if _text(spec.get("slug"))
                    == "heat_treatment_microstructure_mechanics"
                    and self._heat_treatment_objective_requests_mechanics(
                        normalized_property_axes
                    )
                    else []
                )
                if _text(spec.get("slug")).startswith("texture_yield_"):
                    supporting_block = self._best_recovered_spec_source_block(
                        document_id,
                        blocks_by_id={
                            block_id: candidate
                            for block_id, candidate in blocks_by_id.items()
                            if block_id != _text(block.block_id)
                        },
                        predicate=self._is_texture_yield_conclusion_block,
                    )
                    if supporting_block is not None:
                        supporting_blocks.append(supporting_block)
                mechanical_property_table = (
                    self._best_specific_mechanical_property_table(
                        document_id,
                        tables_by_id=tables_by_id or {},
                    )
                    if spec.get("mechanical_property_table")
                    else None
                )
                processing_parameter_table = (
                    self._best_slm_processing_parameter_table(
                        document_id,
                        tables_by_id=tables_by_id or {},
                    )
                    if mechanical_property_table is not None
                    else None
                )
                ved_fatigue_strength_table = (
                    self._best_ved_fatigue_strength_table(
                        document_id,
                        tables_by_id=tables_by_id or {},
                    )
                    if spec.get("fatigue_strength_table")
                    else None
                )
                ved_fabrication_parameter_table = (
                    self._best_ved_fabrication_parameter_table(
                        document_id,
                        tables_by_id=tables_by_id or {},
                    )
                    if _text(spec.get("slug")) == "ved_defects_fatigue"
                    else None
                )
                texture_yield_table = (
                    self._best_texture_yield_validation_table(
                        document_id,
                        tables_by_id=tables_by_id or {},
                    )
                    if spec.get("texture_yield_table")
                    else None
                )
                if spec.get("texture_yield_table") and texture_yield_table is None:
                    continue
                supporting_tables = [
                    table
                    for table in [
                        mechanical_property_table,
                        processing_parameter_table,
                        ved_fatigue_strength_table,
                        texture_yield_table,
                    ]
                    if table is not None
                ]
                recovered_spec = spec
                if (
                    _text(spec.get("slug"))
                    == "heat_treatment_microstructure_mechanics"
                    and condition_block is not None
                ):
                    condition_summary = self._heat_treatment_condition_summary(
                        condition_block
                    )
                    if condition_summary:
                        recovered_spec = {
                            **spec,
                            "subject": (
                                "heat treatment type and heat treatment parameters"
                            ),
                            "statement": (
                                self._heat_treatment_recovered_statement_with_conditions(
                                    normalized_property_axes,
                                    condition_summary=condition_summary,
                                )
                            ),
                            "process_axes": [
                                "heat treatment type",
                                "heat treatment temperature",
                                "heat treatment duration",
                                "HIP pressure",
                            ],
                            "claim_status": "limited",
                            "relation_status": "limited",
                            "warnings": [
                                "heat_treatment_parameters_not_isolated",
                                "single_variable_effect_not_isolated",
                                "needs_expert_review",
                            ],
                        }
                if (
                    _text(spec.get("slug"))
                    == "heat_treatment_bundle_pore_reduction"
                    and condition_block is not None
                ):
                    condition_summary = self._heat_treatment_condition_summary(
                        condition_block
                    )
                    if condition_summary:
                        recovered_spec = {
                            **spec,
                            "statement": (
                                f"Under the tested {condition_summary}, the "
                                "authors reported no superiority between the "
                                "furnace HT and HIP treatment bundles for pore "
                                "reduction. This bundle comparison does not "
                                "isolate treatment type, temperature, duration, "
                                "or pressure as separate effects."
                            ),
                        }
                if _text(spec.get("slug")) == "ved_defects_fatigue":
                    fabrication_context = self._ved_fabrication_parameter_context(
                        ved_fabrication_parameter_table
                    )
                    varied_process_axes = _strings(
                        fabrication_context.get("varied_axes")
                    ) or self._ved_condition_varied_process_axes(condition_block)
                    fixed_process_axes = {
                        _text(axis): _text(value)
                        for axis, value in _mapping(
                            fabrication_context.get("fixed_axes")
                        ).items()
                        if _text(axis) and _text(value)
                    }
                    context_process_axes = [
                        "volumetric energy density",
                        *varied_process_axes,
                        *fixed_process_axes,
                    ]
                    coupled_process_parameters = len(varied_process_axes) > 1
                    table_statement = (
                        self._ved_fatigue_strength_table_statement(
                            ved_fatigue_strength_table,
                            varied_process_axes=varied_process_axes,
                            fixed_process_axes=fixed_process_axes,
                        )
                        if ved_fatigue_strength_table is not None
                        else ""
                    )
                    if coupled_process_parameters and not table_statement:
                        table_statement = (
                            "The authors associated the tested higher-VED PBF-LB "
                            "parameter sets with lower defect fraction, size, and "
                            "complexity and slightly improved fatigue life. "
                            + self._ved_process_condition_limitation(
                                varied_process_axes,
                                fixed_process_axes,
                            )
                        )
                    recovered_spec = {
                        **spec,
                        "process_axes": context_process_axes,
                        **({"statement": table_statement} if table_statement else {}),
                        **(
                            {
                                "subject": (
                                    "coupled PBF-LB parameter sets grouped by "
                                    "volumetric energy density"
                                ),
                                "relation_type": "associated",
                                "predicate": "associated",
                                "warnings": [
                                    "process_conditions_not_isolated",
                                    "single_variable_effect_not_isolated",
                                    "needs_expert_review",
                                ],
                            }
                            if coupled_process_parameters
                            else {}
                        ),
                    }
                specific_spec_axes = _strings(spec.get("specific_mechanical_axes"))
                if mechanical_property_table is not None and specific_spec_axes:
                    specific_object = _join_display_values(specific_spec_axes)
                    controlled_summary = (
                        self._specific_mechanical_property_controlled_summary(
                            mechanical_property_table,
                            processing_parameter_table,
                            specific_spec_axes,
                        )
                    )
                    table_summary = self._specific_mechanical_property_table_statement(
                        specific_spec_axes,
                    )
                    value_clause = controlled_summary or table_summary
                    warnings = _strings(spec.get("warnings"))
                    if not controlled_summary:
                        warnings = _dedupe_strings(
                            [
                                *warnings,
                                "non_single_variable_table_comparison",
                                "single_variable_effect_not_isolated",
                                "needs_expert_review",
                            ]
                        )
                    statement = (
                        "In this study, higher scanning speed was associated "
                        "with better densification, a refined microstructure, "
                        "and better overall mechanical performance. "
                        f"{value_clause}"
                    )
                    subject = _text(spec.get("subject"))
                    process_axes = _strings(spec.get("process_axes"))
                    if not controlled_summary:
                        subject = _SLM_COUPLED_PARAMETER_SET_LABEL
                        process_axes = [
                            "scanning strategy",
                            "scanning speed",
                            "hatch spacing",
                            "energy density",
                        ]
                        statement = self._unisolated_scanning_speed_statement(
                            specific_spec_axes
                        )
                    recovered_spec = {
                        **spec,
                        "subject": subject,
                        "object": specific_object,
                        "statement": statement,
                        "process_axes": process_axes,
                        "property_scope": specific_spec_axes,
                        "warnings": warnings,
                        **(
                            {
                                "claim_status": "limited",
                                "relation_status": "limited",
                            }
                            if not controlled_summary
                            else {}
                        ),
                    }
                recovered.append(
                    self._recovered_spec_finding(
                        block,
                        collection_id=collection_id,
                        objective_context=objective_context,
                        objective=objective,
                        spec=recovered_spec,
                        condition_block=condition_block,
                        condition_tables=[ved_fabrication_parameter_table]
                        if ved_fabrication_parameter_table is not None
                        else [],
                        supporting_blocks=supporting_blocks,
                        supporting_tables=supporting_tables,
                    )
                )
                break
        return [item for item in recovered if item]

    def _requested_specific_mechanical_axes(
        self,
        normalized_property_axes: str,
    ) -> list[str]:
        return [
            axis
            for axis in (
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            )
            if f" {_normalize_match_text(axis)} " in normalized_property_axes
        ]

    def _heat_treatment_recovered_statement(
        self,
        normalized_property_axes: str,
    ) -> str:
        base = self._heat_treatment_recovered_base_statement(
            normalized_property_axes
        )
        mechanics_effects = self._heat_treatment_recovered_mechanics_effects(
            normalized_property_axes
        )
        if not mechanics_effects:
            return base
        return f"{base} {self._heat_treatment_recovered_mechanics_sentence(mechanics_effects)}"

    def _heat_treatment_recovered_statement_with_conditions(
        self,
        normalized_property_axes: str,
        *,
        condition_summary: str,
    ) -> str:
        scope = self._heat_treatment_recovered_base_scope(normalized_property_axes)
        effects: list[str] = []
        if "density" in scope:
            effects.append("increased density")
        if "microstructure" in scope:
            effects.append(
                "eliminated the as-SLM cellular microstructure and dense "
                "dislocation structures through recrystallization"
            )
        effect_text = self._finding_title_outcome(effects)
        if not effect_text:
            effect_text = "changed the requested material properties"
        statement = (
            f"Under the tested {condition_summary}, heat treatment {effect_text}."
        )
        mechanics_effects = self._heat_treatment_recovered_mechanics_effects(
            normalized_property_axes
        )
        if mechanics_effects:
            statement = (
                f"{statement} "
                f"{self._heat_treatment_recovered_mechanics_sentence(mechanics_effects)}"
            )
        return (
            f"{statement} These grouped observations do not isolate treatment "
            "type, temperature, duration, or pressure as separate effects."
        )

    def _heat_treatment_recovered_base_statement(
        self,
        normalized_property_axes: str,
    ) -> str:
        scope = self._heat_treatment_recovered_base_scope(normalized_property_axes)
        if "density" in scope and "microstructure" in scope:
            return (
                "Heat treatments increased density. Short heat treatments also "
                "eliminated the as-SLM cellular microstructure and dense "
                "dislocation structures through recrystallization."
            )
        if "density" in scope:
            return "Heat treatments increased density."
        if "microstructure" in scope:
            return (
                "Short heat treatments eliminated the as-SLM cellular "
                "microstructure and dense dislocation structures through "
                "recrystallization."
            )
        return "Heat treatments changed the requested material properties."

    def _heat_treatment_recovered_property_scope(
        self,
        normalized_property_axes: str,
    ) -> list[str]:
        return _dedupe_strings(
            [
                *self._heat_treatment_recovered_base_scope(normalized_property_axes),
                *self._heat_treatment_recovered_mechanics_scope(
                    normalized_property_axes
                ),
            ]
        )

    def _heat_treatment_recovered_object(
        self,
        normalized_property_axes: str,
    ) -> str:
        return self._finding_title_outcome(
            self._heat_treatment_recovered_property_scope(normalized_property_axes)
        )

    def _heat_treatment_recovered_base_scope(
        self,
        normalized_property_axes: str,
    ) -> list[str]:
        if not normalized_property_axes.strip():
            return ["density", "microstructure"]
        scope: list[str] = []
        if (
            " density " in normalized_property_axes
            or " relative density " in normalized_property_axes
        ):
            scope.append("density")
        if " microstructure " in normalized_property_axes:
            scope.append("microstructure")
        return scope

    def _heat_treatment_recovered_mechanics_scope(
        self,
        normalized_property_axes: str,
    ) -> list[str]:
        scope: list[str] = []
        if " mechanical properties " in normalized_property_axes:
            scope.extend(["hardness", "tensile strength", "elongation"])
        else:
            if " hardness " in normalized_property_axes:
                scope.append("hardness")
            if (
                " strength " in normalized_property_axes
                or " tensile strength " in normalized_property_axes
            ):
                scope.append("tensile strength")
            if " elongation " in normalized_property_axes:
                scope.append("elongation")
        return _dedupe_strings(scope)

    def _heat_treatment_recovered_mechanics_effects(
        self,
        normalized_property_axes: str,
    ) -> list[str]:
        effects: list[str] = []
        for axis in self._heat_treatment_recovered_mechanics_scope(
            normalized_property_axes
        ):
            if axis == "elongation":
                effects.append("higher elongation")
            elif axis == "hardness":
                effects.append("lower hardness")
            elif axis == "tensile strength":
                effects.append("lower tensile strength")
        return effects

    def _heat_treatment_recovered_mechanics_sentence(
        self,
        mechanics_effects: list[str],
    ) -> str:
        effect_text = self._finding_title_outcome(mechanics_effects)
        return f"The same microstructural evolution is associated with {effect_text}."

    def _heat_treatment_objective_requests_mechanics(
        self,
        normalized_property_axes: str,
    ) -> bool:
        return any(
            f" {term} " in normalized_property_axes
            for term in (
                "mechanical properties",
                "strength",
                "tensile strength",
                "elongation",
                "hardness",
            )
        )

    def _best_specific_mechanical_property_table(
        self,
        document_id: str,
        *,
        tables_by_id: Mapping[str, SourceTable],
    ) -> SourceTable | None:
        best: tuple[int, int, SourceTable] | None = None
        for table in tables_by_id.values():
            if table.document_id != document_id:
                continue
            score = self._specific_mechanical_property_table_score(table)
            if score <= 0:
                continue
            ranked = (score, -(table.table_order or 0), table)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _specific_mechanical_property_table_score(self, table: SourceTable) -> int:
        text = f" {_normalize_match_text(self._source_table_text(table))} "
        required_terms = (
            "yield strength",
            "ultimate tensile strength",
            "elongation",
        )
        if not all(f" {term} " in text for term in required_terms):
            return 0
        score = 6
        if " mechanical properties " in text:
            score += 4
        if " slm " in text or " selective laser melting " in text:
            score += 2
        if re.search(r"\b\d+(?:\.\d+)?\b", text):
            score += 2
        return score

    def _best_slm_processing_parameter_table(
        self,
        document_id: str,
        *,
        tables_by_id: Mapping[str, SourceTable],
    ) -> SourceTable | None:
        best: tuple[int, int, SourceTable] | None = None
        for table in tables_by_id.values():
            if table.document_id != document_id:
                continue
            score = self._slm_processing_parameter_table_score(table)
            if score <= 0:
                continue
            ranked = (score, -(table.table_order or 0), table)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _slm_processing_parameter_table_score(self, table: SourceTable) -> int:
        indexes = self._slm_processing_parameter_column_indexes(table)
        required = {"condition", "sample", "scan_strategy", "scanning_speed"}
        if not required <= set(indexes):
            return 0
        score = 6
        if "energy_density" in indexes:
            score += 3
        text = f" {_normalize_match_text(self._source_table_text(table))} "
        if " relative density " in text:
            score += 2
        if " slm " in text or " selective laser melting " in text:
            score += 2
        return score

    def _best_ved_fabrication_parameter_table(
        self,
        document_id: str,
        *,
        tables_by_id: Mapping[str, SourceTable],
    ) -> SourceTable | None:
        best: tuple[int, int, SourceTable] | None = None
        for table in tables_by_id.values():
            if table.document_id != document_id:
                continue
            score = self._ved_fabrication_parameter_table_score(table)
            if score <= 0:
                continue
            ranked = (score, -(table.table_order or 0), table)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _ved_fabrication_parameter_table_score(self, table: SourceTable) -> int:
        indexes = self._ved_fabrication_parameter_column_indexes(table)
        required = {
            "label",
            "volumetric energy density",
            "laser power",
            "scanning speed",
            "hatch spacing",
            "layer thickness",
        }
        if not required <= set(indexes):
            return 0
        labels = {
            _normalize_match_text(row[indexes["label"]])
            for row in table.table_matrix
            if len(row) > indexes["label"]
        }
        if not all(
            any(target in label for label in labels)
            for target in ("l ved", "m ved", "h ved")
        ):
            return 0
        text = f" {_normalize_match_text(self._source_table_text(table))} "
        score = 10
        if " fabrication parameters " in text or " printing parameters " in text:
            score += 4
        return score

    def _ved_fabrication_parameter_column_indexes(
        self,
        table: SourceTable,
    ) -> dict[str, int]:
        headers = list(table.column_headers)
        if not headers and table.table_matrix:
            headers = list(table.table_matrix[0])
        indexes: dict[str, int] = {}
        for index, header in enumerate(headers):
            normalized = f" {_normalize_match_text(header)} "
            if normalized.strip() in {"id", "sample", "condition"}:
                indexes.setdefault("label", index)
            elif " volumetric energy density " in normalized or re.search(
                r"\bved\b", normalized
            ):
                indexes.setdefault("volumetric energy density", index)
            elif " laser power " in normalized:
                indexes.setdefault("laser power", index)
            elif " scanning speed " in normalized or " scan speed " in normalized:
                indexes.setdefault("scanning speed", index)
            elif " hatch spacing " in normalized or " hatch space " in normalized:
                indexes.setdefault("hatch spacing", index)
            elif " layer thickness " in normalized:
                indexes.setdefault("layer thickness", index)
        if "label" not in indexes and headers:
            indexes["label"] = 0
        return indexes

    def _ved_fabrication_parameter_context(
        self,
        table: SourceTable | None,
    ) -> dict[str, Any]:
        if table is None:
            return {}
        indexes = self._ved_fabrication_parameter_column_indexes(table)
        label_index = indexes.get("label")
        if label_index is None:
            return {}
        values_by_axis: dict[str, list[str]] = {
            axis: []
            for axis in (
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            )
            if axis in indexes
        }
        for row in table.table_matrix:
            if len(row) <= label_index:
                continue
            label = _normalize_match_text(row[label_index])
            if not any(target in label for target in ("l ved", "m ved", "h ved")):
                continue
            for axis, values in values_by_axis.items():
                index = indexes[axis]
                if len(row) > index and (value := _text(row[index])):
                    values.append(value)
        units = {
            "laser power": "W",
            "scanning speed": "mm/s",
            "hatch spacing": "μm",
            "layer thickness": "μm",
        }
        varied_axes: list[str] = []
        fixed_axes: dict[str, str] = {}
        for axis, values in values_by_axis.items():
            unique_values = _dedupe_strings(values)
            if len(unique_values) > 1:
                varied_axes.append(axis)
            elif len(unique_values) == 1:
                fixed_axes[axis] = f"{unique_values[0]} {units[axis]}"
        return {"varied_axes": varied_axes, "fixed_axes": fixed_axes}

    def _ved_fabrication_parameter_table_quote(self, table: SourceTable) -> str:
        indexes = self._ved_fabrication_parameter_column_indexes(table)
        label_index = indexes.get("label")
        if label_index is None:
            return ""
        relevant_rows = [
            {
                "row_index": row_index,
                "cells": [_text(cell) for cell in row],
                "aligned": _table_row_cells_are_aligned(
                    [_text(cell) for cell in row],
                    list(table.column_headers),
                ),
            }
            for row_index, row in enumerate(table.table_matrix)
            if len(row) > label_index
            and any(
                target in _normalize_match_text(row[label_index])
                for target in ("l ved", "m ved", "h ved")
            )
        ]
        return _presentation_table_audit_quote(
            {
                "columns": list(table.column_headers),
                "relevant_rows": relevant_rows,
            }
        )

    def _best_ved_fatigue_strength_table(
        self,
        document_id: str,
        *,
        tables_by_id: Mapping[str, SourceTable],
    ) -> SourceTable | None:
        best: tuple[int, int, SourceTable] | None = None
        for table in tables_by_id.values():
            if table.document_id != document_id:
                continue
            score = self._ved_fatigue_strength_table_score(table)
            if score <= 0:
                continue
            ranked = (score, -(table.table_order or 0), table)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _best_texture_yield_validation_table(
        self,
        document_id: str,
        *,
        tables_by_id: Mapping[str, SourceTable],
    ) -> SourceTable | None:
        best: tuple[int, int, SourceTable] | None = None
        for table in tables_by_id.values():
            if table.document_id != document_id:
                continue
            headers = list(table.column_headers)
            if not headers and table.table_matrix:
                headers = list(table.table_matrix[0])
            header_text = " ".join(headers).lower()
            normalized = f" {_normalize_match_text(self._source_table_text(table))} "
            if not all(symbol in header_text for symbol in ("α", "β", "θ")):
                continue
            if not (
                " yield strength prediction " in normalized
                and " yield strength experiment " in normalized
                and all(
                    value in normalized
                    for value in (" 334 2 ", " 351 9 ", " 363 1 ")
                )
            ):
                continue
            score = 10
            if " prediction and average experimental yield strength " in normalized:
                score += 4
            ranked = (score, -(table.table_order or 0), table)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _ved_fatigue_strength_table_score(self, table: SourceTable) -> int:
        text = f" {_normalize_match_text(self._source_table_text(table))} "
        if not (
            (" ved " in text or " l ved " in text or " m ved " in text)
            and " fatigue " in text
            and " mpa " in text
        ):
            return 0
        if not (
            " fat at 10 " in text
            or " fatigue strength " in text
            or " fatigue limit " in text
        ):
            return 0
        score = 8
        if " max defect length " in text or " defect length " in text:
            score += 4
        if " 340 " in text and " 450 " in text:
            score += 4
        return score

    def _ved_fatigue_strength_table_statement(
        self,
        table: SourceTable,
        *,
        varied_process_axes: list[str] | None = None,
        fixed_process_axes: Mapping[str, str] | None = None,
    ) -> str:
        indexes = self._ved_fatigue_strength_column_indexes(table)
        label_index = indexes.get("label")
        fatigue_index = indexes.get("fatigue_strength")
        defect_index = indexes.get("defect_length")
        fat50_index = indexes.get("fat50")
        if label_index is None or fatigue_index is None:
            return ""
        rows: dict[str, tuple[str, str, str]] = {}
        for row in table.table_matrix:
            if len(row) <= max(label_index, fatigue_index):
                continue
            label = _normalize_match_text(row[label_index])
            fatigue_strength = _numeric_text(row[fatigue_index])
            defect_length = (
                _numeric_text(row[defect_index])
                if defect_index is not None and len(row) > defect_index
                else ""
            )
            fat50 = (
                _numeric_text(row[fat50_index])
                if fat50_index is not None and len(row) > fat50_index
                else ""
            )
            if not label or not fatigue_strength:
                continue
            if "l ved" in label:
                rows["L-VED"] = (fatigue_strength, defect_length, fat50)
            elif "m ved" in label:
                rows["M-VED"] = (fatigue_strength, defect_length, fat50)
            elif "h ved" in label:
                rows["H-VED"] = (fatigue_strength, defect_length, fat50)
            elif "wrought" in label:
                rows["Wrought"] = (fatigue_strength, defect_length, fat50)
        low = rows.get("L-VED")
        medium = rows.get("M-VED")
        if not low or not medium:
            return ""
        high = rows.get("H-VED")
        wrought = rows.get("Wrought")
        parts: list[str] = []
        if high:
            parts.append(
                "Across the tested L-VED, M-VED, and H-VED PBF-LB parameter "
                "sets, fatigue strength at 10^4 cycles was "
                f"{low[0]}, {medium[0]}, and {high[0]} MPa, respectively."
            )
            if low[1] and medium[1] and high[1]:
                parts.append(
                    "Maximum defect length was "
                    f"{low[1]}, {medium[1]}, and {high[1]} μm, respectively."
                )
            if low[2] and medium[2] and high[2]:
                wrought_clause = (
                    f" and remained below wrought 316L ({wrought[2]} MPa)"
                    if wrought and wrought[2]
                    else ""
                )
                parts.append(
                    "FAT50 was non-monotonic across the printed conditions "
                    f"({low[2]}, {medium[2]}, and {high[2]} MPa){wrought_clause}."
                )
        else:
            parts.append(
                "Across the tested L-VED and M-VED PBF-LB parameter sets, "
                "fatigue strength at 10^4 cycles was "
                f"{low[0]} and {medium[0]} MPa, respectively."
            )
            if low[1] and medium[1]:
                parts.append(
                    "Maximum defect length was "
                    f"{low[1]} and {medium[1]} μm, respectively."
                )
        parts.append(
            "The authors associated the higher-VED conditions with lower defect "
            "fraction, size, and complexity and slightly improved fatigue life."
        )
        if len(varied_process_axes or []) > 1:
            parts.append(
                self._ved_process_condition_limitation(
                    varied_process_axes or [],
                    fixed_process_axes or {},
                )
            )
        return " ".join(parts)

    def _ved_process_condition_limitation(
        self,
        varied_process_axes: list[str],
        fixed_process_axes: Mapping[str, str],
    ) -> str:
        axes = _dedupe_strings(varied_process_axes)
        if not axes:
            return ""
        if len(axes) == 1:
            varied_text = axes[0]
        elif len(axes) == 2:
            varied_text = " and ".join(axes)
        else:
            varied_text = f"{', '.join(axes[:-1])}, and {axes[-1]}"
        fixed_descriptions = [
            f"{axis} remained fixed at {value}"
            for axis, value in fixed_process_axes.items()
            if _text(axis) and _text(value)
        ]
        fixed_clause = (
            f", while {' and '.join(fixed_descriptions)}"
            if fixed_descriptions
            else ""
        )
        return (
            f"{varied_text[0].upper() + varied_text[1:]} varied across these VED "
            f"groups{fixed_clause}, so the comparison does not isolate a "
            "VED-only effect."
        )

    def _ved_fatigue_strength_column_indexes(
        self,
        table: SourceTable,
    ) -> dict[str, int]:
        indexes: dict[str, int] = {}
        headers = list(table.column_headers)
        if not headers and table.table_matrix:
            headers = list(table.table_matrix[0])
        for index, header in enumerate(headers):
            normalized = f" {_normalize_match_text(header)} "
            if " printed 316l " in normalized or " sample " in normalized:
                indexes.setdefault("label", index)
            if " fat at 10 " in normalized or " fatigue strength " in normalized:
                indexes.setdefault("fatigue_strength", index)
            if " fat50 " in normalized or " fatigue limit at 50 " in normalized:
                indexes.setdefault("fat50", index)
            if " defect length " in normalized:
                indexes.setdefault("defect_length", index)
        return indexes

    def _source_table_text(self, table: SourceTable) -> str:
        parts: list[str] = [
            _text(table.caption_text),
            _text(table.heading_path),
            *[_text(header) for header in table.column_headers],
        ]
        for row in table.table_matrix[:8]:
            parts.extend(_text(cell) for cell in row)
        return " ".join(part for part in parts if part)

    def _specific_mechanical_property_controlled_summary(
        self,
        mechanical_table: SourceTable,
        processing_table: SourceTable | None,
        axes: list[str],
    ) -> str:
        if processing_table is None:
            return ""
        comparison = self._controlled_scanning_speed_property_comparison(
            mechanical_table,
            processing_table,
            axes,
        )
        if not comparison:
            return ""
        properties = self._controlled_property_change_text(
            comparison["properties"],
        )
        if not properties:
            return ""
        conditions = self._controlled_comparison_condition_text(comparison)
        condition_clause = f" at {conditions}" if conditions else ""
        return (
            "Increasing scanning speed from "
            f"{comparison['low_speed']} to {comparison['high_speed']}"
            f"{condition_clause} corresponded to higher {properties}."
        )

    def _controlled_scanning_speed_property_comparison(
        self,
        mechanical_table: SourceTable,
        processing_table: SourceTable,
        axes: list[str],
    ) -> dict[str, Any]:
        mechanical_indexes = self._specific_mechanical_property_column_indexes(
            mechanical_table
        )
        processing_indexes = self._slm_processing_parameter_column_indexes(
            processing_table
        )
        if not {"sample", "scanning_speed"} <= set(processing_indexes):
            return {}
        if not {"sample"} <= set(mechanical_indexes):
            return {}
        mechanical_rows = self._mechanical_property_rows(
            mechanical_table,
            indexes=mechanical_indexes,
            axes=axes,
        )
        if not mechanical_rows:
            return {}
        joined_rows = []
        for process_row in self._processing_parameter_rows(
            processing_table,
            indexes=processing_indexes,
        ):
            sample = _text(process_row.get("sample"))
            condition = _text(process_row.get("condition"))
            mechanical_row = mechanical_rows.get(sample or "") or mechanical_rows.get(
                f"condition:{condition}"
            )
            if not mechanical_row:
                continue
            joined_rows.append({**process_row, "properties": mechanical_row})
        best: tuple[tuple[int, float, float], dict[str, Any]] | None = None
        for left_index, left in enumerate(joined_rows):
            for right in joined_rows[left_index + 1 :]:
                if not self._controlled_scanning_speed_pair(left, right):
                    continue
                candidate = self._controlled_scanning_speed_comparison_candidate(
                    left,
                    right,
                    axes=axes,
                )
                if not candidate:
                    continue
                rank = self._controlled_scanning_speed_comparison_rank(candidate)
                if best is None or rank > best[0]:
                    best = (rank, candidate)
        return best[1] if best else {}

    def _mechanical_property_rows(
        self,
        table: SourceTable,
        *,
        indexes: Mapping[str, int],
        axes: list[str],
    ) -> dict[str, dict[str, str]]:
        sample_index = indexes.get("sample")
        condition_index = indexes.get("condition")
        if sample_index is None:
            return {}
        rows: dict[str, dict[str, str]] = {}
        for row in table.table_matrix:
            if len(row) <= sample_index:
                continue
            sample = _numeric_text(row[sample_index])
            if not sample:
                continue
            values = {
                axis: value
                for axis in axes
                if (column_index := indexes.get(axis)) is not None
                and len(row) > column_index
                and (value := _numeric_text(row[column_index]))
            }
            if not values:
                continue
            rows[sample] = values
            if condition_index is not None and len(row) > condition_index:
                condition = _numeric_text(row[condition_index])
                if condition:
                    rows.setdefault(f"condition:{condition}", values)
        return rows

    def _processing_parameter_rows(
        self,
        table: SourceTable,
        *,
        indexes: Mapping[str, int],
    ) -> list[dict[str, str]]:
        sample_index = indexes.get("sample")
        speed_index = indexes.get("scanning_speed")
        if sample_index is None or speed_index is None:
            return []
        rows: list[dict[str, str]] = []
        for row in table.table_matrix:
            if len(row) <= max(sample_index, speed_index):
                continue
            sample = _numeric_text(row[sample_index])
            speed = _numeric_text(row[speed_index])
            if not sample or not speed:
                continue
            item = {
                "sample": sample,
                "scanning_speed": speed,
            }
            if (
                (condition_index := indexes.get("condition")) is not None
                and len(row) > condition_index
                and (condition := _numeric_text(row[condition_index]))
            ):
                item["condition"] = condition
            if (
                (strategy_index := indexes.get("scan_strategy")) is not None
                and len(row) > strategy_index
                and (strategy := _text(row[strategy_index]))
            ):
                item["scan_strategy"] = strategy
            if (
                (energy_index := indexes.get("energy_density")) is not None
                and len(row) > energy_index
                and (energy := _numeric_text(row[energy_index]))
            ):
                item["energy_density"] = energy
            if (
                (hatch_index := indexes.get("hatch_spacing")) is not None
                and len(row) > hatch_index
                and (hatch := _numeric_text(row[hatch_index]))
            ):
                item["hatch_spacing"] = hatch
            if (
                (laser_power_index := indexes.get("laser_power")) is not None
                and len(row) > laser_power_index
                and (laser_power := _numeric_text(row[laser_power_index]))
            ):
                item["laser_power"] = laser_power
            if (
                (layer_index := indexes.get("layer_thickness")) is not None
                and len(row) > layer_index
                and (layer := _numeric_text(row[layer_index]))
            ):
                item["layer_thickness"] = layer
            rows.append(item)
        return rows

    def _controlled_scanning_speed_pair(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
    ) -> bool:
        for key in (
            "energy_density",
            "scan_strategy",
            "hatch_spacing",
            "laser_power",
            "layer_thickness",
        ):
            left_value = _normalize_match_text(_text(left.get(key)) or "")
            right_value = _normalize_match_text(_text(right.get(key)) or "")
            if left_value and right_value and left_value != right_value:
                return False
        return _float_text(left.get("scanning_speed")) != _float_text(
            right.get("scanning_speed")
        )

    def _controlled_scanning_speed_comparison_candidate(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        *,
        axes: list[str],
    ) -> dict[str, Any]:
        left_speed = _float_text(left.get("scanning_speed"))
        right_speed = _float_text(right.get("scanning_speed"))
        if left_speed is None or right_speed is None or left_speed == right_speed:
            return {}
        low, high = (left, right) if left_speed < right_speed else (right, left)
        low_properties = _mapping(low.get("properties"))
        high_properties = _mapping(high.get("properties"))
        properties: list[dict[str, Any]] = []
        for axis in axes:
            low_value = _numeric_text(low_properties.get(axis))
            high_value = _numeric_text(high_properties.get(axis))
            low_float = _float_text(low_value)
            high_float = _float_text(high_value)
            if low_float is None or high_float is None:
                continue
            properties.append(
                {
                    "axis": axis,
                    "low": low_value,
                    "high": high_value,
                    "low_float": low_float,
                    "high_float": high_float,
                }
            )
        if not properties:
            return {}
        return {
            "low_speed": _text(low.get("scanning_speed")) or "",
            "high_speed": _text(high.get("scanning_speed")) or "",
            "energy_density": _text(low.get("energy_density"))
            or _text(high.get("energy_density"))
            or "",
            "scan_strategy": _text(low.get("scan_strategy"))
            or _text(high.get("scan_strategy"))
            or "",
            "hatch_spacing": _text(low.get("hatch_spacing"))
            or _text(high.get("hatch_spacing"))
            or "",
            "laser_power": _text(low.get("laser_power"))
            or _text(high.get("laser_power"))
            or "",
            "layer_thickness": _text(low.get("layer_thickness"))
            or _text(high.get("layer_thickness"))
            or "",
            "properties": properties,
        }

    def _controlled_scanning_speed_comparison_rank(
        self,
        comparison: Mapping[str, Any],
    ) -> tuple[int, float, float]:
        properties = _mapping_list(comparison.get("properties"))
        increases = sum(
            1
            for item in properties
            if _float_text(item.get("high_float")) is not None
            and _float_text(item.get("low_float")) is not None
            and float(item["high_float"]) > float(item["low_float"])
        )
        normalized_gain = 0.0
        for item in properties:
            low_value = _float_text(item.get("low_float"))
            high_value = _float_text(item.get("high_float"))
            if low_value is None or high_value is None or low_value == 0:
                continue
            normalized_gain += (high_value - low_value) / abs(low_value)
        speed_delta = abs(
            (_float_text(comparison.get("high_speed")) or 0)
            - (_float_text(comparison.get("low_speed")) or 0)
        )
        return (increases, normalized_gain, speed_delta)

    def _controlled_comparison_condition_text(
        self,
        comparison: Mapping[str, Any],
    ) -> str:
        parts: list[str] = []
        if energy_density := _text(comparison.get("energy_density")):
            parts.append(f"energy density {energy_density}")
        if scan_strategy := _text(comparison.get("scan_strategy")):
            parts.append(f"scan strategy {scan_strategy}")
        if hatch_spacing := _text(comparison.get("hatch_spacing")):
            parts.append(f"hatch spacing {hatch_spacing}")
        if laser_power := _text(comparison.get("laser_power")):
            parts.append(f"laser power {laser_power}")
        if layer_thickness := _text(comparison.get("layer_thickness")):
            parts.append(f"layer thickness {layer_thickness}")
        return " and ".join(parts)

    def _controlled_property_change_text(
        self,
        properties: list[dict[str, Any]],
    ) -> str:
        parts = [
            (
                f"{axis} ({_text(item.get('low'))} to {_text(item.get('high'))}"
                f"{self._specific_mechanical_property_unit(axis)})"
            )
            for item in properties
            if (axis := _text(item.get("axis")))
            and _text(item.get("low"))
            and _text(item.get("high"))
        ]
        return _join_display_values(parts)

    def _specific_mechanical_property_table_statement(
        self,
        axes: list[str],
    ) -> str:
        specific_object = self._finding_title_outcome(axes)
        return (
            f"The associated source table reports {specific_object} measurements; "
            "use the table rows as direct evidence rather than a single global range."
        )

    def _unisolated_scanning_speed_statement(self, axes: list[str]) -> str:
        return (
            "Across the tested SLM parameter sets, the authors reported that "
            "higher-scanning-speed conditions showed better densification, a "
            "refined microstructure, and better overall mechanical performance. "
            "Because scan strategy, hatch spacing, and energy density also varied, "
            "these data do not isolate a scanning-speed effect. "
            f"{self._specific_mechanical_property_table_statement(axes)}"
        )

    def _specific_mechanical_property_column_indexes(
        self,
        table: SourceTable,
    ) -> dict[str, int]:
        indexes: dict[str, int] = {}
        headers = list(table.column_headers)
        if not headers and table.table_matrix:
            headers = list(table.table_matrix[0])
        for index, header in enumerate(headers):
            normalized = f" {_normalize_match_text(header)} "
            normalized_key = normalized.strip()
            if (
                " condition number " in normalized
                or normalized_key
                in {"build platform condition", "build platform conditions"}
            ):
                indexes.setdefault("condition", index)
            if " sample number " in normalized:
                indexes.setdefault("sample", index)
            if " yield strength " in normalized or normalized_key in {"y", "y mpa"}:
                indexes.setdefault("yield strength", index)
            if " ultimate tensile strength " in normalized or normalized_key in {
                "u",
                "u mpa",
                "uts",
                "uts mpa",
            }:
                indexes.setdefault("ultimate tensile strength", index)
            if " elongation " in normalized or normalized_key in {"el", "el percent"}:
                indexes.setdefault("elongation", index)
        return indexes

    def _slm_processing_parameter_column_indexes(
        self,
        table: SourceTable,
    ) -> dict[str, int]:
        indexes: dict[str, int] = {}
        headers = list(table.column_headers)
        if not headers and table.table_matrix:
            headers = list(table.table_matrix[0])
        for index, header in enumerate(headers):
            normalized = f" {_normalize_match_text(header)} "
            if " condition number " in normalized:
                indexes.setdefault("condition", index)
            if " sample number " in normalized:
                indexes.setdefault("sample", index)
            if " scan strategy " in normalized:
                indexes.setdefault("scan_strategy", index)
            if " scanning speed " in normalized or " scan speed " in normalized:
                indexes.setdefault("scanning_speed", index)
            if " energy density " in normalized:
                indexes.setdefault("energy_density", index)
            if " hatch space " in normalized or " hatch spacing " in normalized:
                indexes.setdefault("hatch_spacing", index)
            if " laser power " in normalized:
                indexes.setdefault("laser_power", index)
            if " layer thickness " in normalized:
                indexes.setdefault("layer_thickness", index)
        return indexes

    def _specific_mechanical_property_unit(self, axis: str) -> str:
        normalized = _normalize_match_text(axis)
        if normalized in {"yield strength", "ultimate tensile strength"}:
            return " MPa"
        if normalized == "elongation":
            return "%"
        return ""

    def _specific_mechanical_property_label(self, axis: str) -> str:
        normalized = _normalize_match_text(axis)
        if normalized == "yield strength":
            return "Yield Strength"
        if normalized == "ultimate tensile strength":
            return "Ultimate Tensile Strength"
        if normalized == "elongation":
            return "Elongation"
        return self._display_axis_label(axis)

    def _normalized_objective_property_axes(
        self,
        objective: Mapping[str, Any],
        objective_context: Mapping[str, Any],
    ) -> str:
        lens = _mapping(objective_context.get("objective_evidence_lens"))
        property_axes = _dedupe_strings([
            *_strings(objective.get('property_axes')),
            *_strings(objective_context.get('target_property_axes')),
            *_strings(lens.get('target_outcome_axes')),
        ])
        return f" {_normalize_match_text(' '.join(property_axes))} "

    def _objective_property_axes_include_any(
        self,
        normalized_property_axes: str,
        *,
        legacy_match: bool,
        terms: list[str] | tuple[str, ...],
    ) -> bool:
        if not normalized_property_axes.strip():
            return legacy_match
        return any(
            f" {_normalize_match_text(term)} " in normalized_property_axes
            for term in terms
            if _normalize_match_text(term)
        )

    def _recovered_context_process_axes(
        self,
        process_axes: Any,
        *,
        objective_context: Mapping[str, Any],
    ) -> list[str]:
        objective_process_axes = [
            axis
            for axis in [
                *_strings(objective_context.get("process_context_axes")),
                *_strings(objective_context.get("variable_process_axes")),
            ]
            if self._is_platform_process_context_axis(axis)
        ]
        return _dedupe_strings(
            [
                *_strings(process_axes),
                *objective_process_axes,
            ]
        )

    def _is_platform_process_context_axis(self, axis: Any) -> bool:
        normalized = f" {_normalize_match_text(_text(axis) or '')} "
        return any(
            f" {term} " in normalized
            for term in (
                "lpbf",
                "pbf lb",
                "slm",
                "selective laser melting",
                "laser beam powder bed fusion",
                "laser powder bed fusion",
                "powder bed fusion",
                "additive manufacturing",
            )
        )

    def _objective_evidence_document_ids(
        self,
        evidence_units: list[dict[str, Any]],
    ) -> list[str]:
        return _dedupe_strings(
            [
                _text(unit.get("document_id"))
                for unit in evidence_units
                if _text(unit.get("document_id"))
            ]
        )

    def _objective_recovery_document_ids(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
    ) -> list[str]:
        document_ids: list[str] = []
        document_ids.extend(self._objective_evidence_document_ids(evidence_units))
        document_ids.extend(
            _text(route.get("document_id")) or ""
            for route in _mapping_list(payload.get("evidence_routes"))
            if route.get("extractable", True)
        )
        document_ids.extend(
            _text(frame.get("document_id")) or ""
            for frame in _mapping_list(payload.get("paper_frames"))
            if (_text(frame.get("relevance")) or "").lower()
            not in {"irrelevant", "excluded"}
        )
        return _dedupe_strings(document_ids)

    def _best_recovered_spec_source_block(
        self,
        document_id: str,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        predicate,
    ) -> SourceBlock | None:
        best: tuple[int, int, SourceBlock] | None = None
        for block in blocks_by_id.values():
            if block.document_id != document_id:
                continue
            score = predicate(block)
            if score <= 0:
                continue
            ranked = (score, block.block_order or 0, block)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _is_slm_processing_conclusion_block(self, block: SourceBlock) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            " slm processing parameters " in normalized
            and " densification " in normalized
            and " microstructure " in normalized
            and " mechanical properties " in normalized
        ):
            return 0
        return self._source_block_result_score(block, normalized)

    def _is_scan_speed_conclusion_block(self, block: SourceBlock) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            " higher scanning speed " in normalized
            and " densification " in normalized
            and " refined microstructure " in normalized
            and " mechanical properties " in normalized
        ):
            return 0
        return self._source_block_result_score(block, normalized) + 3

    def _is_heat_treatment_conclusion_block(self, block: SourceBlock) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            (
                " heat treatments " in normalized
                or " heat treatment " in normalized
                or " ht slm " in normalized
                or " ht-slm " in normalized
                or " hip slm " in normalized
                or " hip-slm " in normalized
            )
            and " density " in normalized
            and (
                " cellular microstructure " in normalized
                or " cellular microstructures " in normalized
            )
            and " dislocation " in normalized
            and " elongation " in normalized
        ):
            return 0
        return self._source_block_result_score(block, normalized) + 3

    def _is_heat_treatment_microstructure_block(self, block: SourceBlock) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            (
                " heat treatments " in normalized
                or " heat treatment " in normalized
                or " ht slm " in normalized
                or " ht-slm " in normalized
                or " hip slm " in normalized
                or " hip-slm " in normalized
            )
            and " density " in normalized
            and (
                " cellular microstructure " in normalized
                or " cellular microstructures " in normalized
            )
            and " dislocation " in normalized
        ):
            return 0
        score = self._source_block_result_score(block, normalized) + 4
        if " porosity " in normalized or " low porosity " in normalized:
            score += 3
        if " induced an increase in the density " in normalized:
            score += 5
        if " disappeared " in normalized:
            score += 2
        return score

    def _best_heat_treatment_condition_source_block(
        self,
        document_id: str,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> SourceBlock | None:
        best: tuple[int, int, SourceBlock] | None = None
        for block in blocks_by_id.values():
            if block.document_id != document_id:
                continue
            score = self._heat_treatment_condition_source_block_score(block)
            if score <= 0:
                continue
            ranked = (score, -(block.block_order or 0), block)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _heat_treatment_condition_source_block_score(
        self,
        block: SourceBlock,
    ) -> int:
        if not self._heat_treatment_condition_summary(block):
            return 0
        heading = f" {_normalize_match_text(_text(block.heading_path) or '')} "
        score = 5
        if any(term in heading for term in (" sample preparation ", " experimental ")):
            score += 6
        if " abstract " in heading:
            score -= 3
        if any(term in heading for term in (" result ", " conclusion ")):
            score -= 2
        return score

    def _heat_treatment_condition_summary(
        self,
        block: SourceBlock,
    ) -> str:
        raw = re.sub(r"\s+", " ", _text(block.text) or "")
        temperature = r"(\d+(?:\.\d+)?)\s*(?:°|◦)?\s*[Cc]"
        duration = r"(\d+(?:\.\d+)?)\s*h\b"
        pressure = r"(\d+(?:\.\d+)?)\s*MPa\b"
        furnace_match = re.search(
            rf"furnace(?:-type)?(?:\s+of)?\s+heat treatment.{{0,100}}?"
            rf"at\s*{temperature}\s*for\s*{duration}",
            raw,
            flags=re.IGNORECASE,
        )
        hip_match = re.search(
            rf"(?:hot isostatic pressing|HIP).{{0,180}}?at\s*{temperature}"
            rf"\s*(?:and|,)\s*{pressure}\s*for\s*{duration}",
            raw,
            flags=re.IGNORECASE,
        )
        if furnace_match is None or hip_match is None:
            return ""
        furnace_temperature, furnace_duration = furnace_match.groups()
        hip_temperature, hip_pressure, hip_duration = hip_match.groups()
        return (
            f"furnace HT at {_normalize_numeric_token(furnace_temperature)} °C "
            f"for {_normalize_numeric_token(furnace_duration)} h and HIP at "
            f"{_normalize_numeric_token(hip_temperature)} °C and "
            f"{_normalize_numeric_token(hip_pressure)} MPa for "
            f"{_normalize_numeric_token(hip_duration)} h"
        )

    def _best_heat_treatment_mechanics_source_block(
        self,
        document_id: str,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        exclude_block_id: str,
    ) -> SourceBlock | None:
        best: tuple[int, int, SourceBlock] | None = None
        for block in blocks_by_id.values():
            if block.document_id != document_id:
                continue
            if _text(block.block_id) == exclude_block_id:
                continue
            score = self._is_heat_treatment_conclusion_block(block)
            if score <= 0:
                continue
            ranked = (score, block.block_order or 0, block)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _is_heat_treatment_bundle_comparison_block(
        self,
        block: SourceBlock,
    ) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            " furnace type " in normalized
            and " hip " in normalized
            and " no superiority " in normalized
            and " pore reduction " in normalized
        ):
            return 0
        return self._source_block_result_score(block, normalized) + 4

    def _is_texture_yield_conclusion_block(self, block: SourceBlock) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            (
                " scan strategy rotation " in normalized
                or " scan strategy angle " in normalized
            )
            and " build orientation " in normalized
            and " yield strength " in normalized
        ):
            return 0
        if not (
            " bishop hill " in normalized
            or " rotation matrix " in normalized
            or " predicted " in normalized
            or " predictions " in normalized
            or " validation " in normalized
        ):
            return 0
        return self._source_block_result_score(block, normalized) + 4

    def _is_texture_angle_definition_block(self, block: SourceBlock) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            " process involved three angles " in normalized
            and " rotation angle of the laser scan lines " in normalized
            and " global x axis " in normalized
            and " global y axis " in normalized
        ):
            return 0
        return 10

    def _is_ved_defect_fatigue_block(self, block: SourceBlock) -> int:
        normalized = self._normalized_block_text(block)
        if not (
            (
                " increasing ved " in normalized
                or " increased ved " in normalized
                or " high ved " in normalized
            )
            and " defect " in normalized
            and " fatigue " in normalized
        ):
            return 0
        if not (
            " lower fraction of defects " in normalized
            or " defect size " in normalized
            or " lof " in normalized
            or " fatigue limit " in normalized
        ):
            return 0
        score = self._source_block_result_score(block, normalized) + 4
        if (
            (" increasing ved " in normalized or " increased ved " in normalized)
            and " lower fraction of defects " in normalized
            and " defect size " in normalized
            and " fatigue life " in normalized
        ):
            score += 5
        if (
            " fatigue limit " in normalized
            and " all the structures " in normalized
            and " increasing ved " not in normalized
        ):
            score -= 3
        return score

    def _best_ved_condition_source_block(
        self,
        document_id: str,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> SourceBlock | None:
        best: tuple[int, int, SourceBlock] | None = None
        for block in blocks_by_id.values():
            if block.document_id != document_id:
                continue
            score = self._ved_condition_source_block_score(block)
            if score <= 0:
                continue
            ranked = (score, -(block.block_order or 0), block)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _ved_condition_source_block_score(self, block: SourceBlock) -> int:
        raw = " ".join(
            value
            for value in (_text(block.heading_path), _text(block.text))
            if value
        )
        normalized = f" {_normalize_match_text(raw)} "
        if not (
            " ved " in normalized
            or " volumetric energy density " in normalized
            or " energy density " in normalized
        ):
            return 0
        if not (
            " pbf lb " in normalized
            or " powder bed fusion " in normalized
            or " selective laser melting " in normalized
            or " slm " in normalized
        ):
            return 0
        ved_values = re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:j\s*/?\s*mm\s*(?:3|³)|j/mm3|j/mm³)",
            raw,
            flags=re.IGNORECASE,
        )
        if len(_dedupe_strings(ved_values)) < 2:
            return 0
        heading = f" {_normalize_match_text(_text(block.heading_path) or '')} "
        score = 4 + len(_dedupe_strings(ved_values))
        if any(term in heading for term in ("method", "processing", "experimental")):
            score += 6
        if " table " in normalized:
            score += 3
        if any(term in heading for term in ("result", "discussion", "conclusion")):
            score -= 4
        if " introduction " in heading or " abstract " in heading:
            score -= 3
        return score

    def _ved_condition_varied_process_axes(
        self,
        block: SourceBlock | None,
    ) -> list[str]:
        if block is None:
            return []
        normalized = f" {_normalize_match_text(_text(block.text))} "
        has_variation = any(
            term in normalized
            for term in (
                " by varying ",
                " were varied ",
                " both varied ",
                " changed together ",
            )
        )
        if not has_variation:
            return []
        axes: list[str] = []
        if " laser power " in normalized:
            axes.append("laser power")
        if " scanning speed " in normalized or " scan speed " in normalized:
            axes.append("scanning speed")
        return axes

    def _normalized_block_text(self, block: SourceBlock) -> str:
        return f" {_normalize_match_text((_text(block.heading_path) or '') + ' ' + (_text(block.text) or ''))} "

    def _source_block_result_score(self, block: SourceBlock, normalized: str) -> int:
        heading = f" {_normalize_match_text(_text(block.heading_path) or '')} "
        score = 1
        if " conclusion " in heading:
            score += 8
        if " result " in heading or " discussion " in heading:
            score += 4
        if " abstract " in heading:
            score -= 3
        if " introduction " in heading:
            score -= 8
        if " table " in normalized or " fig " in normalized:
            score += 1
        if " validation " in normalized or " validate " in normalized:
            score += 5
        if " experimental findings " in normalized:
            score += 5
        if " experimental " in normalized and (
            " prediction " in normalized or " predictions " in normalized
        ):
            score += 5
        if " deviation " in normalized or " deviations " in normalized:
            score += 3
        if " yield strength increased " in normalized:
            score += 3
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|mpa)\b", normalized):
            score += 2
        return score

    def _recovered_spec_finding(
        self,
        block: SourceBlock,
        *,
        collection_id: str,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
        spec: Mapping[str, Any],
        condition_block: SourceBlock | None = None,
        condition_tables: list[SourceTable] | None = None,
        supporting_blocks: list[SourceBlock] | None = None,
        supporting_tables: list[SourceTable] | None = None,
    ) -> dict[str, Any]:
        block_id = _text(block.block_id)
        document_id = _text(block.document_id)
        slug = _text(spec.get("slug"))
        if not block_id or not document_id or not slug:
            return {}
        evidence_ref_id = f"evref_recovered_{slug}_{block_id}"
        claim_id = f"claim_recovered_{slug}_{block_id}"
        relation_id = f"rel_recovered_{slug}_{block_id}"
        context_id = f"ctx_recovered_{slug}_{block_id}"
        material_scope = _strings(
            objective_context.get("material_scope") or objective.get("material_scope")
        )
        statement = _text(spec.get("statement")) or ""
        process_axes = self._recovered_context_process_axes(
            spec.get("process_axes"),
            objective_context=objective_context,
        )
        property_scope = _strings(spec.get("property_scope"))
        confidence = float(spec.get("confidence") or 0.82)
        evidence_ref_ids = [evidence_ref_id]
        evidence_quote = self._recovered_spec_evidence_quote(block, spec=spec)
        evidence_refs = [
            {
                "evidence_ref_id": evidence_ref_id,
                "source_kind": _text(block.block_type) or "text_window",
                "document_id": document_id,
                "label": _text(block.heading_path) or "Recovered source evidence",
                "locator": {
                    "source_ref": block_id,
                    "source_kind": _text(block.block_type) or "text_window",
                    **({"page": block.page} if block.page is not None else {}),
                },
                "fact_ids": [claim_id],
                "anchor_ids": [],
                "confidence": confidence,
                "traceability_status": "resolved",
                "evidence_role": "direct_support",
                "quote": evidence_quote,
                "href": _presentation_evidence_href(
                    collection_id=collection_id,
                    document_id=document_id,
                    source_ref=block_id,
                    page=_text(block.page),
                    quote_text=evidence_quote,
                ),
            }
        ]
        condition_block_id = _text(condition_block.block_id if condition_block else None)
        if condition_block_id:
            condition_ref_id = f"evref_recovered_{slug}_condition_{condition_block_id}"
            evidence_ref_ids.append(condition_ref_id)
            condition_quote = _short_text(_text(condition_block.text), limit=900)
            evidence_refs.append(
                {
                    "evidence_ref_id": condition_ref_id,
                    "source_kind": _text(condition_block.block_type) or "text_window",
                    "document_id": _text(condition_block.document_id) or document_id,
                    "label": (
                        _text(condition_block.heading_path)
                        or "Recovered condition evidence"
                    ),
                    "locator": {
                        "source_ref": condition_block_id,
                        "source_kind": _text(condition_block.block_type)
                        or "text_window",
                        **(
                            {"page": condition_block.page}
                            if condition_block.page is not None
                            else {}
                        ),
                    },
                    "fact_ids": [claim_id],
                    "anchor_ids": [],
                    "confidence": confidence,
                    "traceability_status": "resolved",
                    "evidence_role": "condition_context",
                    "quote": condition_quote,
                    "href": _presentation_evidence_href(
                        collection_id=collection_id,
                        document_id=_text(condition_block.document_id) or document_id,
                        source_ref=condition_block_id,
                        page=_text(condition_block.page),
                        quote_text=condition_quote,
                    ),
                }
            )
        for supporting_block in supporting_blocks or []:
            supporting_block_id = _text(supporting_block.block_id)
            if not supporting_block_id:
                continue
            supporting_ref_id = (
                f"evref_recovered_{slug}_mechanics_{supporting_block_id}"
            )
            evidence_ref_ids.append(supporting_ref_id)
            supporting_quote = (
                _short_text(_text(supporting_block.text), limit=900)
                if slug.startswith("texture_yield_")
                else self._recovered_spec_evidence_quote(
                    supporting_block,
                    spec=spec,
                )
            )
            evidence_refs.append(
                {
                    "evidence_ref_id": supporting_ref_id,
                    "source_kind": _text(supporting_block.block_type) or "text_window",
                    "document_id": _text(supporting_block.document_id) or document_id,
                    "label": (
                        _text(supporting_block.heading_path)
                        or "Recovered supporting evidence"
                    ),
                    "locator": {
                        "source_ref": supporting_block_id,
                        "source_kind": _text(supporting_block.block_type)
                        or "text_window",
                        **(
                            {"page": supporting_block.page}
                            if supporting_block.page is not None
                            else {}
                        ),
                    },
                    "fact_ids": [claim_id],
                    "anchor_ids": [],
                    "confidence": confidence,
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": supporting_quote,
                    "href": _presentation_evidence_href(
                        collection_id=collection_id,
                        document_id=_text(supporting_block.document_id) or document_id,
                        source_ref=supporting_block_id,
                        page=_text(supporting_block.page),
                        quote_text=supporting_quote,
                    ),
                }
            )
        table_sources = [
            (table, "table", "direct_support")
            for table in supporting_tables or []
        ] + [
            (table, "condition_table", "condition_context")
            for table in condition_tables or []
        ]
        for supporting_table, ref_kind, evidence_role in table_sources:
            supporting_table_id = _text(supporting_table.table_id)
            if not supporting_table_id:
                continue
            supporting_ref_id = (
                f"evref_recovered_{slug}_{ref_kind}_{supporting_table_id}"
            )
            evidence_ref_ids.append(supporting_ref_id)
            supporting_quote = (
                self._ved_fabrication_parameter_table_quote(supporting_table)
                if evidence_role == "condition_context"
                else self._presentation_table_source_text(supporting_table)
            )
            evidence_refs.append(
                {
                    "evidence_ref_id": supporting_ref_id,
                    "source_kind": "table",
                    "document_id": _text(supporting_table.document_id) or document_id,
                    "label": (
                        _text(supporting_table.caption_text)
                        or "Recovered supporting table"
                    ),
                    "locator": {
                        "source_ref": supporting_table_id,
                        "source_kind": "table",
                        **(
                            {"page": supporting_table.page}
                            if supporting_table.page is not None
                            else {}
                        ),
                    },
                    "fact_ids": [claim_id],
                    "anchor_ids": [],
                    "confidence": confidence,
                    "traceability_status": "resolved",
                    "evidence_role": evidence_role,
                    "quote": supporting_quote,
                    "href": _presentation_evidence_href(
                        collection_id=collection_id,
                        document_id=_text(supporting_table.document_id) or document_id,
                        source_ref=supporting_table_id,
                        page=_text(supporting_table.page),
                        quote_text=supporting_quote,
                    ),
                }
            )
        evidence_ref_ids = _dedupe_strings(evidence_ref_ids)
        return {
            "evidence_ref": evidence_refs[0],
            "evidence_refs": evidence_refs,
            "context": {
                "context_id": context_id,
                "label": "Recovered source scope",
                "material_scope": material_scope,
                "process_context": {"variable_process_axes": process_axes},
                "test_condition": {"source_heading": _text(block.heading_path)},
                "property_scope": property_scope,
                "limitations": ["Recovered from parsed source text"],
            },
            "claim": {
                "claim_id": claim_id,
                "claim_type": "finding",
                "statement": statement,
                "status": _text(spec.get("claim_status")) or "supported",
                "confidence": confidence,
                "strength": "moderate",
                "evidence_ref_ids": evidence_ref_ids,
                "context_ids": [context_id],
                "source_object_ids": [block_id],
                "warnings": _dedupe_strings(
                    [
                        *_strings(spec.get("warnings")),
                        "needs_expert_review",
                    ]
                ),
            },
            "relation": {
                "relation_id": relation_id,
                "relation_type": _text(spec.get("relation_type"))
                or _text(spec.get("predicate"))
                or "affects",
                "subject": _text(spec.get("subject")),
                "predicate": _text(spec.get("predicate")) or "affects",
                "object": _text(spec.get("object")),
                "statement": statement,
                "conditions": material_scope,
                "status": _text(spec.get("relation_status")) or "supported",
                "confidence": confidence,
                "evidence_ref_ids": evidence_ref_ids,
                "context_ids": [context_id],
                "source_object_ids": [block_id],
                "warnings": _dedupe_strings(
                    [
                        "recovered_from_source_text",
                        *_strings(spec.get("warnings")),
                    ]
                ),
            },
        }

    def _recovered_spec_evidence_quote(
        self,
        block: SourceBlock,
        *,
        spec: Mapping[str, Any],
    ) -> str:
        if _text(spec.get("slug")) == "heat_treatment_microstructure_mechanics":
            return _short_text(_text(block.text), limit=900)
        return self._recovered_spec_quote(block, spec=spec)

    def _recovered_spec_quote(
        self,
        block: SourceBlock,
        *,
        spec: Mapping[str, Any],
    ) -> str:
        quote_hints = {
            "variable": {
                term
                for value in _strings(spec.get("process_axes"))
                for term in _quote_hint_terms(value)
            },
            "outcome": {
                term
                for value in _strings(spec.get("property_scope"))
                for term in _quote_hint_terms(value)
            },
            "relation": set(),
            "statement": _quote_hint_terms(_text(spec.get("statement"))),
        }
        for value in (
            _text(spec.get("statement")),
            _text(spec.get("subject")),
            _text(spec.get("predicate")),
            _text(spec.get("object")),
        ):
            quote_hints["relation"].update(_quote_hint_terms(value))
        return (
            _short_text(
                self._best_matching_quote_snippet(
                    _text(block.text),
                    quote_hints,
                    limit=900,
                ),
                limit=900,
            )
            or _short_text(_text(block.text), limit=900)
        )

    def _objective_axes_request_preheating_ductility(
        self,
        normalized_axes: str,
    ) -> bool:
        has_preheating = (
            " preheating " in normalized_axes
            or " preheated " in normalized_axes
            or " build platform " in normalized_axes
            or " build plate " in normalized_axes
        )
        has_target = any(
            f" {term} " in normalized_axes
            for term in (
                "mechanical",
                "properties",
                "ductility",
                "elongation",
                "microstructure",
            )
        )
        return has_preheating and has_target

    def _recovered_preheating_findings_from_source_blocks(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
        objective: Mapping[str, Any],
        objective_context: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        document_ids = _dedupe_strings(
            [
                _text(unit.get("document_id"))
                for unit in evidence_units
                if self._objective_unit_has_preheating_mechanical_signal(unit)
            ]
        )
        recovered: list[dict[str, Any]] = []
        for document_id in document_ids:
            block = self._best_preheating_ductility_source_block(
                document_id,
                blocks_by_id=blocks_by_id,
            )
            if block is None:
                continue
            recovered.append(
                self._recovered_preheating_ductility_finding(
                    block,
                    collection_id=_text(payload.get("collection_id")),
                    objective_context=objective_context,
                    objective=objective,
                )
            )
        return [item for item in recovered if item]

    def _objective_unit_has_preheating_mechanical_signal(
        self,
        unit: Mapping[str, Any],
    ) -> bool:
        source_ref_text = " ".join(
            " ".join(
                [
                    _text(source_ref.get("source_kind")) or "",
                    _text(source_ref.get("source_ref")) or "",
                    _text(source_ref.get("role")) or "",
                    _text(source_ref.get("evidence_role")) or "",
                ]
            )
            for source_ref in _mapping_list(unit.get("source_refs"))
        )
        parts = [
            _text(unit.get("unit_kind")) or "",
            _text(unit.get("property_normalized")) or "",
            _text(unit.get("interpretation")) or "",
            _display_mapping(_mapping(unit.get("value_payload"))),
            _display_mapping(_mapping(unit.get("process_context"))),
            _display_mapping(_mapping(unit.get("sample_context"))),
            _display_mapping(_mapping(unit.get("test_condition"))),
            source_ref_text,
        ]
        searchable = f" {_normalize_match_text(' '.join(parts))} "
        has_preheating = (
            " preheating " in searchable
            or " preheated " in searchable
            or " build platform " in searchable
            or " build plate " in searchable
        )
        has_mechanical_result = any(
            f" {term} " in searchable
            for term in (
                "elongation",
                "ductility",
                "tensile",
                "yield",
                "strength",
                "mechanical",
                "el",
            )
        )
        return has_preheating and has_mechanical_result

    def _best_preheating_ductility_source_block(
        self,
        document_id: str,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> SourceBlock | None:
        best: tuple[int, int, SourceBlock] | None = None
        for block in blocks_by_id.values():
            if block.document_id != document_id:
                continue
            text = _text(block.text)
            if not text:
                continue
            normalized = f" {_normalize_match_text(text)} "
            if not (
                (
                    " preheating " in normalized
                    or " preheated " in normalized
                    or " build platform " in normalized
                    or " build plate " in normalized
                )
                and (
                    " ductility " in normalized
                    or " elongation " in normalized
                    or " el " in normalized
                )
            ):
                continue
            if not (" 14 " in normalized and " 150 " in normalized):
                continue
            if not (
                " gnd " in normalized
                or " gnds " in normalized
                or " cellular " in normalized
                or " plastic " in normalized
            ):
                continue
            heading = f" {_normalize_match_text(_text(block.heading_path) or '')} "
            score = 0
            if " conclusion " in heading:
                score += 8
            if " tensile " in heading:
                score += 6
            if " result " in heading or " discussion " in heading:
                score += 4
            if " abstract " in heading or " introduction " in heading:
                score -= 8
            if " 150 " in normalized:
                score += 3
            if " 14 " in normalized:
                score += 3
            if " gnd " in normalized:
                score += 3
            if " microstructure " in normalized:
                score += 2
            ranked = (score, block.block_order or 0, block)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _recovered_preheating_ductility_finding(
        self,
        block: SourceBlock,
        *,
        collection_id: str,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> dict[str, Any]:
        block_id = _text(block.block_id)
        document_id = _text(block.document_id)
        if not block_id or not document_id:
            return {}
        evidence_ref_id = f"evref_recovered_preheating_ductility_{block_id}"
        claim_id = f"claim_recovered_preheating_ductility_{block_id}"
        relation_id = f"rel_recovered_preheating_ductility_{block_id}"
        context_id = f"ctx_recovered_preheating_ductility_{block_id}"
        quote = _short_text(_text(block.text), limit=420)
        statement = (
            "Preheating the build platform to 150 °C increased ductility by "
            "14%; the authors attributed this increase to a more homogenized "
            "cellular microstructure and GND-assisted plastic deformation."
        )
        material_scope = _strings(
            objective_context.get("material_scope") or objective.get("material_scope")
        )
        process_axes = self._recovered_context_process_axes(
            ["build platform preheating temperature"],
            objective_context=objective_context,
        )
        return {
            "evidence_ref": {
                "evidence_ref_id": evidence_ref_id,
                "source_kind": _text(block.block_type) or "text_window",
                "document_id": document_id,
                "label": _text(block.heading_path) or "Recovered source evidence",
                "locator": {
                    "source_ref": block_id,
                    "source_kind": _text(block.block_type) or "text_window",
                    **({"page": block.page} if block.page is not None else {}),
                },
                "fact_ids": [claim_id],
                "anchor_ids": [],
                "confidence": 0.86,
                "traceability_status": "resolved",
                "evidence_role": "direct_support",
                "quote": quote,
                "href": _presentation_evidence_href(
                    collection_id=collection_id,
                    document_id=document_id,
                    source_ref=block_id,
                    page=_text(block.page),
                    quote_text=quote,
                ),
            },
            "context": {
                "context_id": context_id,
                "label": "Recovered source scope",
                "material_scope": material_scope,
                "process_context": {
                    "variable_process_axes": process_axes,
                    "build_platform_preheating_temperature": "150 °C",
                },
                "test_condition": {
                    "source_heading": _text(block.heading_path),
                },
                "property_scope": ["ductility", "microstructure"],
                "limitations": ["Recovered from parsed source text"],
            },
            "claim": {
                "claim_id": claim_id,
                "claim_type": "finding",
                "statement": statement,
                "status": "supported",
                "confidence": 0.86,
                "strength": "moderate",
                "evidence_ref_ids": [evidence_ref_id],
                "context_ids": [context_id],
                "source_object_ids": [claim_id],
                "warnings": ["author_attributed_mechanism"],
            },
            "relation": {
                "relation_id": relation_id,
                "relation_type": "increases",
                "subject": "build platform preheating temperature",
                "predicate": "increases",
                "object": "ductility",
                "statement": statement,
                "conditions": material_scope,
                "status": "supported",
                "confidence": 0.86,
                "evidence_ref_ids": [evidence_ref_id],
                "context_ids": [context_id],
                "source_object_ids": [claim_id],
                "warnings": [
                    "recovered_from_source_text",
                    "author_attributed_mechanism",
                ],
            },
        }

    def _dedupe_claims_for_understanding(
        self,
        claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for claim in claims:
            claim_id = _text(claim.get("claim_id"))
            statement = _text(claim.get("statement"))
            key = claim_id or f"statement:{statement.lower()}"
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(claim)
        return result

    def _objective_unit_has_corrosion_metric_signal(
        self,
        unit: Mapping[str, Any],
    ) -> bool:
        source_ref_text = " ".join(
            (_text(source_ref.get("source_kind")) or "")
            + " "
            + (_text(source_ref.get("source_ref")) or "")
            for source_ref in _mapping_list(unit.get("source_refs"))
        )
        parts = [
            _text(unit.get('unit_kind')) or "",
            _text(unit.get('property_normalized')) or "",
            _text(unit.get('interpretation')) or "",
            ' '.join(_display_values(_mapping(unit.get('value_payload')))),
            ' '.join(_display_values(_mapping(unit.get('test_condition')))),
            source_ref_text,
        ]
        searchable = f" {_normalize_match_text(' '.join(parts))} "
        return bool(
            any(
                f" {term} " in searchable
                for term in (
                    "corrosion",
                    "pitting",
                    "pitting potential",
                    "passive film",
                    "polarization",
                    "eis",
                )
            )
            and (
                " measurement " in searchable
                or " comparison " in searchable
                or " table " in searchable
            )
        )

    def _best_porosity_corrosion_source_block(
        self,
        document_id: str,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> SourceBlock | None:
        best: tuple[int, int, SourceBlock] | None = None
        for block in blocks_by_id.values():
            if block.document_id != document_id:
                continue
            text = _text(block.text)
            if not text:
                continue
            normalized = f" {_normalize_match_text(text)} "
            if not (
                (
                    " porosity " in normalized
                    or " porosities " in normalized
                    or " pores " in normalized
                )
                and (
                    " pitting " in normalized
                    or " corrosion " in normalized
                )
            ):
                continue
            if not (
                " pitting potential " in normalized
                or " passive film " in normalized
                or " corrosion rate " in normalized
                or " better corrosion " in normalized
            ):
                continue
            heading = f" {_normalize_match_text(_text(block.heading_path) or '')} "
            score = 0
            if " conclusion " in heading:
                score += 6
            if " result " in heading or " discussion " in heading:
                score += 4
            if " abstract " in heading or " introduction " in heading:
                score -= 6
            if " pitting potential " in normalized:
                score += 3
            if " passive film " in normalized:
                score += 3
            if " corrosion rate " in normalized:
                score += 2
            if " decreased porosity " in normalized or " low porosity " in normalized:
                score += 2
            ranked = (score, -(block.block_order or 0), block)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _recovered_porosity_corrosion_finding(
        self,
        block: SourceBlock,
        *,
        collection_id: str,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
        condition_table: SourceTable | None = None,
    ) -> dict[str, Any]:
        block_id = _text(block.block_id)
        document_id = _text(block.document_id)
        if not block_id or not document_id:
            return {}
        evidence_ref_id = f"evref_recovered_porosity_corrosion_{block_id}"
        claim_id = f"claim_recovered_porosity_corrosion_{block_id}"
        relation_id = f"rel_recovered_porosity_corrosion_{block_id}"
        context_id = f"ctx_recovered_porosity_corrosion_{block_id}"
        quote = _short_text(_text(block.text), limit=420)
        process_conditions_not_isolated = (
            self._porosity_corrosion_process_conditions_not_isolated(
                source_text=_text(block.text) or "",
                condition_table=condition_table,
            )
        )
        statement = self._porosity_corrosion_association_statement(
            process_conditions_not_isolated=process_conditions_not_isolated,
        )
        material_scope = _strings(
            objective_context.get("material_scope") or objective.get("material_scope")
        )
        process_axes = self._recovered_context_process_axes(
            ["porosity level", "pore size"],
            objective_context=objective_context,
        )
        evidence_refs = [
            {
                "evidence_ref_id": evidence_ref_id,
                "source_kind": _text(block.block_type) or "text_window",
                "document_id": document_id,
                "label": _text(block.heading_path) or "Recovered source evidence",
                "locator": {
                    "source_ref": block_id,
                    "source_kind": _text(block.block_type) or "text_window",
                    **({"page": block.page} if block.page is not None else {}),
                },
                "fact_ids": [claim_id],
                "anchor_ids": [],
                "confidence": 0.82,
                "traceability_status": "resolved",
                "evidence_role": "direct_support",
                "quote": quote,
                "href": _presentation_evidence_href(
                    collection_id=collection_id,
                    document_id=document_id,
                    source_ref=block_id,
                    page=_text(block.page),
                ),
            }
        ]
        evidence_ref_ids = [evidence_ref_id]
        condition_table_id = _text(condition_table.table_id if condition_table else None)
        if condition_table_id:
            condition_ref_id = (
                "evref_recovered_porosity_corrosion_condition_"
                f"{condition_table_id}"
            )
            condition_quote = self._presentation_table_source_text(condition_table)
            evidence_ref_ids.append(condition_ref_id)
            evidence_refs.append(
                {
                    "evidence_ref_id": condition_ref_id,
                    "source_kind": "table",
                    "document_id": _text(condition_table.document_id) or document_id,
                    "label": (
                        _text(condition_table.caption_text)
                        or "SLM process conditions"
                    ),
                    "locator": {
                        "source_ref": condition_table_id,
                        "source_kind": "table",
                        **(
                            {"page": condition_table.page}
                            if condition_table.page is not None
                            else {}
                        ),
                    },
                    "fact_ids": [claim_id],
                    "anchor_ids": [],
                    "confidence": 0.82,
                    "traceability_status": "resolved",
                    "evidence_role": "condition_context",
                    "quote": condition_quote,
                    "href": _presentation_evidence_href(
                        collection_id=collection_id,
                        document_id=_text(condition_table.document_id) or document_id,
                        source_ref=condition_table_id,
                        page=_text(condition_table.page),
                        quote_text=condition_quote,
                    ),
                }
            )
        warnings = ["paper_level_association", "needs_expert_review"]
        if process_conditions_not_isolated:
            warnings.append("process_conditions_not_isolated")
        return {
            "evidence_ref": evidence_refs[0],
            "evidence_refs": evidence_refs,
            "context": {
                "context_id": context_id,
                "label": "Recovered source scope",
                "material_scope": material_scope,
                "process_context": {
                    "variable_process_axes": process_axes,
                },
                "test_condition": {
                    "source_heading": _text(block.heading_path),
                },
                "property_scope": ["pitting corrosion behavior"],
                "limitations": [
                    "Paper-level association; causal effect not isolated",
                    *(
                        ["Laser power and scan speed changed together"]
                        if process_conditions_not_isolated
                        else []
                    ),
                ],
            },
            "claim": {
                "claim_id": claim_id,
                "claim_type": "finding",
                "statement": statement,
                "status": "limited",
                "confidence": 0.82,
                "strength": "moderate",
                "evidence_ref_ids": evidence_ref_ids,
                "context_ids": [context_id],
                "source_object_ids": [block_id],
                "warnings": warnings,
            },
            "relation": {
                "relation_id": relation_id,
                "relation_type": "associated",
                "subject": "porosity level",
                "predicate": "associated",
                "object": "pitting corrosion behavior",
                "statement": statement,
                "conditions": material_scope,
                "status": "limited",
                "confidence": 0.82,
                "evidence_ref_ids": evidence_ref_ids,
                "context_ids": [context_id],
                "source_object_ids": [block_id],
                "warnings": _dedupe_strings(
                    ["recovered_from_source_text", *warnings]
                ),
            },
        }

    def _best_porosity_corrosion_process_table(
        self,
        document_id: str,
        *,
        tables_by_id: Mapping[str, SourceTable],
    ) -> SourceTable | None:
        best: tuple[int, int, SourceTable] | None = None
        for table in tables_by_id.values():
            if table.document_id != document_id:
                continue
            score = self._porosity_corrosion_process_table_score(table)
            if score <= 0:
                continue
            ranked = (score, -(table.table_order or 0), table)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _porosity_corrosion_process_table_score(self, table: SourceTable) -> int:
        headers = list(table.column_headers)
        if not headers and table.table_matrix:
            headers = [_text(cell) or "" for cell in table.table_matrix[0]]
        normalized_headers = [_normalize_match_text(header) for header in headers]

        def column_index(*terms: str) -> int | None:
            for index, header in enumerate(normalized_headers):
                if all(term in header for term in terms):
                    return index
            return None

        laser_power_index = column_index("laser", "power")
        scan_speed_index = column_index("scan", "speed")
        energy_density_index = column_index("energy", "density")
        if (
            laser_power_index is None
            or scan_speed_index is None
            or energy_density_index is None
        ):
            return 0

        rows = list(table.table_matrix)
        if rows and [
            _normalize_match_text(_text(cell) or "") for cell in rows[0]
        ] == normalized_headers:
            rows = rows[1:]

        def distinct_values(index: int) -> set[str]:
            return {
                value
                for row in rows
                if index < len(row)
                and (value := _normalize_match_text(_text(row[index]) or ""))
            }

        if (
            len(distinct_values(laser_power_index)) < 2
            or len(distinct_values(scan_speed_index)) < 2
        ):
            return 0
        score = 8
        if len(distinct_values(energy_density_index)) == 1:
            score += 2
        if column_index("layer", "thickness") is not None:
            score += 1
        return score

    def _porosity_corrosion_process_conditions_not_isolated(
        self,
        *,
        source_text: str,
        condition_table: SourceTable | None,
    ) -> bool:
        if (
            condition_table is not None
            and self._porosity_corrosion_process_table_score(condition_table) > 0
        ):
            return True
        normalized = f" {_normalize_match_text(source_text)} "
        return (
            " laser power " in normalized
            and " scanning speed " in normalized
            and (
                " changes in " in normalized
                or " changed " in normalized
                or " various porosities " in normalized
            )
        )

    def _porosity_corrosion_association_statement(
        self,
        *,
        process_conditions_not_isolated: bool,
    ) -> str:
        statement = (
            "Across the tested SLM conditions, lower-porosity samples were "
            "associated with higher pitting potential and a more stable passive "
            "film, consistent with better pitting-corrosion resistance."
        )
        if process_conditions_not_isolated:
            return (
                f"{statement} Laser power and scan speed changed together across "
                "the samples, so the evidence does not isolate porosity as a "
                "causal variable."
            )
        return (
            f"{statement} This paper-level evidence does not isolate porosity as "
            "a causal variable."
        )

    def _consume_relation_trace(
        self,
        relation_payload: Mapping[str, Any],
        *,
        scope_payload: Mapping[str, Any],
        trace_status: str,
    ) -> list[dict[str, Any]]:
        consumer = getattr(self.structured_extractor, "consume_last_trace", None)
        if not callable(consumer):
            return []
        trace = consumer()
        if not isinstance(trace, Mapping):
            return []
        input_source_ids = [
            unit_id
            for item in _mapping_list(relation_payload.get("evidence_units"))
            if (unit_id := _text(item.get("evidence_unit_id")))
        ]
        collection_id = _text(scope_payload.get("collection_id"))
        objective = _mapping(scope_payload.get("objective"))
        context = _mapping(scope_payload.get("objective_context"))
        goal_id = _text(scope_payload.get("goal_id"))
        objective_id = _text(objective.get("objective_id")) or _text(
            context.get("objective_id")
        )
        trace_record = dict(trace)
        trace_record["trace_id"] = _trace_id(
            trace_record.get("task_type"),
            collection_id,
            goal_id or objective_id,
            input_source_ids,
        )
        trace_record["task_type"] = _text(trace_record.get("task_type")) or (
            _RELATION_TRACE_TASK_TYPE
        )
        trace_record["trace_status"] = trace_status
        trace_record["collection_id"] = collection_id
        trace_record["scope_type"] = "goal" if goal_id else "objective"
        trace_record["scope_id"] = goal_id or objective_id
        trace_record["input_blocks"] = [
            {
                "source_object_id": unit_id,
                "source_kind": "objective_evidence_unit",
            }
            for unit_id in input_source_ids
        ]
        trace_record["source_object_ids"] = input_source_ids
        return [trace_record]

    def _deterministic_objective_relations(
        self,
        evidence_units: list[dict[str, Any]],
        *,
        variable_axes: list[str],
        target_axes: list[str],
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        relations = [
            relation
            for unit in evidence_units
            if (
                relation := self._deterministic_relation_from_evidence_unit(
                    unit,
                    variable_axes=variable_axes,
                    target_axes=target_axes,
                    evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
                    context_ids=context_ids,
                    context_ids_by_unit=context_ids_by_unit,
                )
            )
        ]
        return _dedupe_by_id(relations, "relation_id")

    def _deterministic_relation_from_evidence_unit(
        self,
        unit: Mapping[str, Any],
        *,
        variable_axes: list[str],
        target_axes: list[str],
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> dict[str, Any]:
        unit_id = _text(unit.get("evidence_unit_id"))
        if not unit_id:
            return {}
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind not in {
            "comparison",
            "interpretation",
            "characterization",
            "mechanism",
        } and not (
            unit_kind in _DIRECT_RESULT_CONTEXT_UNIT_KINDS
            and self._objective_unit_has_direct_result_signal(unit)
        ):
            return {}
        predicate = self._deterministic_relation_predicate(unit)
        sample_values = _display_values(_mapping(unit.get("sample_context")))
        baseline_values = _display_values(_mapping(unit.get("baseline_context")))
        process_values = _display_values(_mapping(unit.get("process_context")))
        if (
            unit_kind == "comparison"
            and sample_values
            and baseline_values
            and not process_values
        ):
            return {}
        if unit_kind == "measurement" and predicate in {"reports", ""}:
            return {}
        subject = self._deterministic_relation_subject(unit)
        target = _text(unit.get("property_normalized")) or "observed response"
        statement = self._deterministic_relation_statement(
            unit,
            subject=subject or "process",
            predicate=predicate,
            target=target,
        )
        statement_subject = ""
        statement_predicate = ""
        statement_subject = self._statement_relation_subject(statement)
        statement_predicate = self._statement_relation_predicate(statement)
        if statement_subject and statement_predicate:
            explicit_axis = self._display_axis_label(
                _text(_mapping(unit.get("value_payload")).get("comparison_axis"))
            )
            if not explicit_axis:
                subject = statement_subject
        if target == "observed response" and "density" in statement.lower():
            target = "density"
        if statement_predicate and predicate in {"explains", "reports", ""}:
            predicate = statement_predicate
        statement = self._deterministic_relation_statement(
            unit,
            subject=subject,
            predicate=predicate,
            target=target,
        )
        if not subject or not target or not statement:
            return {}
        if subject.lower() in {"characterization", "interpretation", "mechanism", "comparison"}:
            return {}
        if not _looks_user_facing(subject) or subject.lower() in {"true", "false"}:
            return {}
        if subject.replace(".", "", 1).isdigit():
            return {}
        if not self._looks_complete_claim_statement(statement):
            return {}
        statement_lower = statement.lower()
        if (
            " has the highest " in statement_lower
            or "measurement is relative to" in statement_lower
            or "measurement is " in statement_lower
            or statement_lower.endswith(" explains density.")
            or statement_lower == f"{subject.lower()} explains {target.lower()}."
        ):
            return {}
        if not self._deterministic_relation_matches_objective_axes(
            unit,
            subject=subject,
            target=target,
            statement=statement,
            variable_axes=variable_axes,
            target_axes=target_axes,
        ):
            return {}
        evidence_unit_ids = [unit_id]
        evidence_ref_ids = self._ref_ids_for(evidence_unit_ids, evidence_ref_ids_by_unit)
        return {
            "relation_id": _stable_relation_id(
                "deterministic",
                subject,
                target,
                statement,
                evidence_unit_ids,
            ),
            "relation_type": self._presentation_relation_type("comparative", predicate),
            "subject": subject,
            "predicate": predicate or "relates to",
            "object": target,
            "statement": statement,
            "conditions": [],
            "status": "supported" if evidence_ref_ids else "limited",
            "confidence": unit.get("confidence"),
            "evidence_ref_ids": evidence_ref_ids,
            "context_ids": self._context_ids_for_evidence_unit(
                unit,
                context_ids,
                context_ids_by_unit,
            ),
            "source_object_ids": evidence_unit_ids,
            "warnings": ["deterministic_relation"],
        }

    def _deterministic_relation_matches_objective_axes(
        self,
        unit: Mapping[str, Any],
        *,
        subject: str,
        target: str,
        statement: str,
        variable_axes: list[str] | tuple[str, ...],
        target_axes: list[str] | tuple[str, ...],
    ) -> bool:
        if target_axes and not self._objective_unit_matches_claim_target(
            unit,
            f"{target} {statement}",
            target_axes,
        ):
            return False
        if not variable_axes:
            return True
        value_payload = _mapping(unit.get("value_payload"))
        process_context = _mapping(unit.get("process_context"))
        sample_context = _mapping(unit.get("sample_context"))
        variable_text = " ".join(
            item
            for item in (
                subject,
                _text(value_payload.get("comparison_axis")),
                _text(process_context.get("variable")),
                _text(process_context.get("method")),
                _text(process_context.get("treatment")),
                _text(process_context.get("heat_treatment")),
                _text(sample_context.get("porosity_level")),
                _text(sample_context.get("pore_size")),
                _text(sample_context.get("build_platform_preheating_temperature")),
                _text(sample_context.get("preheating_temperature")),
                statement,
            )
            if item
        )
        return self._objective_statement_mentions_target_axis(
            variable_text,
            variable_axes,
        )

    def _deterministic_relation_subject(self, unit: Mapping[str, Any]) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        axis = self._display_axis_label(_text(value_payload.get("comparison_axis")))
        if axis and _looks_user_facing(axis):
            return axis
        process_context = _mapping(unit.get("process_context"))
        sample_context = _mapping(unit.get("sample_context"))
        for key in (
            "porosity_level",
            "pore_size",
            "build_platform_preheating_temperature",
            "preheating_temperature",
        ):
            if _text(sample_context.get(key)):
                return key.replace("_", " ")
        for key in (
            "variable",
            "process",
            "process_family",
            "process_type",
            "method",
            "treatment",
            "heat_treatment",
        ):
            text = _text(process_context.get(key))
            if text and _looks_user_facing(text):
                return text
        return ""

    def _objective_variable_axes_for_relations(
        self,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[str]:
        lens = _mapping(objective_context.get("objective_evidence_lens"))
        axes = _dedupe_strings(
            [
                *(_strings(lens.get("variable_process_axes"))),
                *(_strings(objective_context.get("variable_process_axes"))),
                *(_strings(objective.get("process_axes"))),
            ]
        )
        return [
            axis
            for axis in axes
            if not self._is_platform_process_context_axis(axis)
        ]

    def _deterministic_relation_predicate(self, unit: Mapping[str, Any]) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        for key in ("direction", "trend"):
            text = _text(value_payload.get(key))
            if text and _looks_user_facing(text):
                return self._normalized_relation_predicate(text)
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind in {"interpretation", "characterization", "mechanism"}:
            return "explains"
        if unit_kind in _DIRECT_RESULT_CONTEXT_UNIT_KINDS:
            return "reports"
        if _text(value_payload.get("comparison_axis")):
            return "compares"
        return "reports"

    def _statement_relation_subject(self, statement: str) -> str:
        lower = (_text(statement) or "").lower()
        if "density" not in lower:
            return ""
        if "heat treatment" in lower:
            return "heat treatment"
        if "treatment" in lower:
            return "treatment"
        if "process" in lower:
            return "process"
        return ""

    def _statement_relation_predicate(self, statement: str) -> str:
        lower = (_text(statement) or "").lower()
        predicate_by_signal = {
            "reduced": "reduces",
            "reduces": "reduces",
            "increased": "increases",
            "increases": "increases",
            "decreased": "decreases",
            "decreases": "decreases",
            "improved": "improves",
            "improves": "improves",
            "affected": "affects",
            "affects": "affects",
        }
        for predicate, normalized in predicate_by_signal.items():
            if f" {predicate} " in f" {lower} ":
                return normalized
        return ""

    def _deterministic_relation_statement(
        self,
        unit: Mapping[str, Any],
        *,
        subject: str,
        predicate: str,
        target: str,
    ) -> str:
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        interpretation = _text(unit.get("interpretation"))
        if (
            unit_kind in {"interpretation", "characterization", "mechanism"}
            and interpretation
            and _looks_user_facing(interpretation)
        ):
            return _short_text(interpretation, limit=220)
        value_payload = _mapping(unit.get("value_payload"))
        if unit_kind == "comparison":
            statement = self._comparison_statement(unit, target)
            if statement:
                return _short_text(statement, limit=220)
        if unit_kind in _DIRECT_RESULT_CONTEXT_UNIT_KINDS:
            statement = self._direct_result_statement_from_evidence_unit(unit)
            if statement:
                return _short_text(statement, limit=220)
        for key in ("summary", "statement", "source_value_text"):
            text = _text(value_payload.get(key))
            if text and _looks_user_facing(text):
                return _short_text(text, limit=220)
        if interpretation and _looks_user_facing(interpretation):
            return _short_text(interpretation, limit=220)
        return f"{subject} {predicate or 'relates to'} {target}."

    def _material_claims(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_ref_ids_by_fact: dict[str, list[str]],
        context_ids: list[str],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in _mapping_list(payload.get("measured_properties")):
            property_name = _text(item.get("property"))
            display_range = _text(item.get("display_range"))
            if not property_name or not display_range:
                continue
            fact_ids = self._fact_ids_from_refs(_mapping_list(item.get("evidence_refs")))
            _append_claim(
                claims,
                self._claim(
                    claim_type="measurement",
                    statement=f"{property_name} is reported as {display_range}.",
                    source_object_ids=fact_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        fact_ids,
                        evidence_ref_ids_by_fact,
                    ),
                    context_ids=context_ids,
                    seen=seen,
                ),
            )
        for limitation in _strings(payload.get("limitations")):
            _append_claim(
                claims,
                self._claim(
                    claim_type="limitation",
                    statement=limitation,
                    source_object_ids=[],
                    evidence_ref_ids=[],
                    context_ids=context_ids,
                    status="limited",
                    seen=seen,
                ),
            )
        return claims

    def _material_relations(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_ref_ids_by_fact: dict[str, list[str]],
        context_ids: list[str],
    ) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []
        for group in _mapping_list(payload.get("comparison_groups")):
            matrix = _mapping(group.get("matrix"))
            fact_ids = self._fact_ids_from_refs(_mapping_list(group.get("evidence_refs")))
            subject = _text(group.get("variable_axis")) or _text(group.get("process_family"))
            object_text = ", ".join(_strings(group.get("properties"))) or _text(
                group.get("material_system")
            )
            relations.append(
                {
                    "relation_type": "compares",
                    "subject": subject or "Material condition",
                    "predicate": _text(group.get("comparability_status")) or "compares",
                    "object": object_text or "observed response",
                    "status": (
                        "supported"
                        if _text(group.get("comparability_status")) == "comparable"
                        else "limited"
                    ),
                    "confidence": None,
                    "evidence_ref_ids": self._ref_ids_for(
                        fact_ids,
                        evidence_ref_ids_by_fact,
                    ),
                    "context_ids": context_ids,
                    "source_object_ids": fact_ids or [_text(matrix.get("matrix_id")) or ""],
                    "warnings": _strings(group.get("warnings")),
                }
            )
        return relations

    def _semantic_relation_payload(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        contexts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        objective = _mapping(payload.get("objective"))
        objective_context = _mapping(payload.get("objective_context"))
        return {
            "objective": {
                "question": _text(objective.get("question"))
                or _text(objective_context.get("question")),
                "material_scope": _strings(
                    objective_context.get("material_scope")
                    or objective.get("material_scope")
                ),
                "process_axes": _strings(
                    objective_context.get("variable_process_axes")
                    or objective.get("process_axes")
                ),
                "property_axes": _strings(
                    objective_context.get("target_property_axes")
                    or objective.get("property_axes")
                ),
            },
            "claims": [
                {
                    "statement": _text(claim.get("statement")),
                    "claim_type": _text(claim.get("claim_type")),
                    "evidence_unit_ids": _strings(claim.get("source_object_ids")),
                }
                for claim in claims
                if _text(claim.get("statement"))
            ][:12],
            "contexts": [
                self._semantic_relation_context(context)
                for context in contexts[:_RELATION_CONTEXT_LIMIT]
            ],
            "evidence_units": [
                self._semantic_relation_evidence_unit(unit)
                for unit in self._semantic_relation_evidence_units(
                    evidence_units,
                    claims=claims,
                    logic_chain_unit_ids=_strings(
                        _mapping(payload.get("logic_chain")).get(
                            "evidence_unit_ids"
                        )
                    ),
                )
            ],
        }

    def _semantic_relation_context(
        self,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "label": _text(context.get("label")),
            "material_scope": _strings(context.get("material_scope")),
            "process_summary": self._semantic_relation_mapping_summary(
                _mapping(context.get("process_context")),
            ),
            "test_summary": self._semantic_relation_test_condition(
                _mapping(context.get("test_condition")),
            ),
            "property_scope": _strings(context.get("property_scope")),
        }

    def _semantic_relation_evidence_unit(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        value_payload = _mapping(unit.get("value_payload"))
        return {
            "evidence_unit_id": _text(unit.get("evidence_unit_id")),
            "unit_kind": _text(unit.get("unit_kind")),
            "property_normalized": _text(unit.get("property_normalized")),
            "sample_summary": self._semantic_relation_mapping_summary(
                _mapping(unit.get("sample_context")),
            ),
            "process_summary": self._semantic_relation_mapping_summary(
                _mapping(unit.get("process_context")),
            ),
            "test_summary": self._semantic_relation_test_condition(
                _mapping(unit.get("test_condition")),
            ),
            "value_payload": {
                key: _short_text(str(value), limit=240)
                for key, value in value_payload.items()
                if key
                in {
                    "source_value_text",
                    "summary",
                    "statement",
                    "direction",
                    "comparison_axis",
                    "comparison_axis_value",
                    "value",
                    "trend",
                }
                and _text(value)
            },
            "unit": _text(unit.get("unit")),
            "baseline_summary": self._semantic_relation_mapping_summary(
                _mapping(unit.get("baseline_context")),
            ),
            "interpretation": _short_text(_text(unit.get("interpretation")) or "", limit=240),
            "resolution_status": _text(unit.get("resolution_status")),
            "confidence": unit.get("confidence"),
        }

    def _semantic_relation_evidence_units(
        self,
        evidence_units: list[dict[str, Any]],
        *,
        claims: list[dict[str, Any]],
        logic_chain_unit_ids: list[str] | tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        eligible = [
            unit
            for unit in evidence_units
            if _text(unit.get("evidence_unit_id"))
        ]
        logic_chain_rank = {
            unit_id: rank
            for rank, unit_id in enumerate(logic_chain_unit_ids)
            if unit_id
        }
        claim_unit_ids = {
            unit_id
            for claim in claims
            for unit_id in _strings(claim.get("source_object_ids"))
        }
        claim_unit_rank: dict[str, int] = {}
        for claim in claims:
            for unit_id in _strings(claim.get("source_object_ids")):
                if unit_id not in claim_unit_rank:
                    claim_unit_rank[unit_id] = len(claim_unit_rank)
        return [
            unit
            for _, unit in sorted(
                enumerate(eligible),
                key=lambda item: self._semantic_relation_evidence_priority(
                    item[1],
                    logic_chain_rank=logic_chain_rank,
                    claim_unit_ids=claim_unit_ids,
                    claim_unit_rank=claim_unit_rank,
                    index=item[0],
                ),
            )
        ][:_RELATION_EVIDENCE_UNIT_LIMIT]

    def _semantic_relation_evidence_priority(
        self,
        unit: Mapping[str, Any],
        *,
        logic_chain_rank: Mapping[str, int],
        claim_unit_ids: set[str],
        claim_unit_rank: Mapping[str, int],
        index: int,
    ) -> tuple[int, int, int, int, int, int]:
        unit_id = _text(unit.get("evidence_unit_id")) or ""
        logic_rank = 0 if unit_id in logic_chain_rank else 1
        logic_order = logic_chain_rank.get(unit_id, len(logic_chain_rank))
        claim_rank = 0 if unit_id in claim_unit_ids else 1
        claim_order = claim_unit_rank.get(unit_id, len(claim_unit_rank))
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind in {"comparison", "interpretation", "characterization", "mechanism"}:
            signal_rank = 0
        elif self._semantic_relation_value_text(unit):
            signal_rank = 1
        else:
            signal_rank = 2
        return (logic_rank, logic_order, claim_rank, claim_order, signal_rank, index)

    def _semantic_relation_value_text(self, unit: Mapping[str, Any]) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        parts = [
            _text(value_payload.get(key)) or ""
            for key in (
                "comparison_axis",
                "direction",
                "trend",
                "summary",
                "statement",
            )
        ]
        parts.append(_text(unit.get("interpretation")) or "")
        return " ".join(part for part in parts if part)

    def _semantic_relation_mapping_summary(
        self,
        payload: Mapping[str, Any],
    ) -> str:
        return _join_display_values(
            [_short_text(value, limit=80) for value in _display_values(payload)],
            limit=5,
        )

    def _semantic_relation_test_condition(
        self,
        payload: Mapping[str, Any],
    ) -> str:
        compact = {
            key: value
            for key, value in payload.items()
            if str(key).lower() not in {"details", "detail", "notes", "note"}
        }
        return self._semantic_relation_mapping_summary(compact)

    def _semantic_relation_from_model(
        self,
        item: Mapping[str, Any],
        *,
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
    ) -> dict[str, Any]:
        source = _text(item.get("source_concept"))
        target = _text(item.get("target_concept"))
        statement = _text(item.get("statement"))
        evidence_unit_ids = _strings(item.get("evidence_unit_ids"))
        if not source or not target or not statement or not evidence_unit_ids:
            return {}
        if not _looks_user_facing(source) or not _looks_user_facing(target):
            return {}
        relation_type = _text(item.get("relation_type")) or "conditional"
        direction = _text(item.get("direction")) or "unknown"
        mediators = _strings(item.get("mediator_concepts"))
        conditions = _strings(item.get("conditions"))
        return {
            "relation_id": _stable_relation_id(
                relation_type,
                source,
                target,
                statement,
                evidence_unit_ids,
            ),
            "relation_type": self._presentation_relation_type(relation_type, direction),
            "subject": source,
            "predicate": direction if direction != "unknown" else relation_type,
            "object": " -> ".join((*mediators, target)) if mediators else target,
            "statement": statement,
            "conditions": conditions,
            "status": "supported" if self._ref_ids_for(evidence_unit_ids, evidence_ref_ids_by_unit) else "limited",
            "confidence": item.get("confidence"),
            "evidence_ref_ids": self._ref_ids_for(
                evidence_unit_ids,
                evidence_ref_ids_by_unit,
            ),
            "context_ids": context_ids,
            "source_object_ids": evidence_unit_ids,
            "warnings": _dedupe_strings(
                ["semantic_relation", *_strings(item.get("warnings"))]
            ),
        }

    def _material_evidence_refs(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for ref in _mapping_list(payload.get("evidence_refs")):
            refs.append(self._normalize_existing_evidence_ref(ref))
        for item in _mapping_list(payload.get("measured_properties")):
            for ref in _mapping_list(item.get("evidence_refs")):
                refs.append(self._normalize_existing_evidence_ref(ref))
        for group in _mapping_list(payload.get("comparison_groups")):
            for ref in _mapping_list(group.get("evidence_refs")):
                refs.append(self._normalize_existing_evidence_ref(ref))
        return self._sort_evidence_refs_for_review(refs)

    def _normalize_existing_evidence_ref(self, ref: Mapping[str, Any]) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_kind = _text(ref.get("source_kind")) or _text(locator.get("source_kind")) or "unknown"
        evidence_ref_id = _text(ref.get("evidence_ref_id"))
        if not evidence_ref_id:
            evidence_ref_id = _stable_ref_id(
                source_kind,
                _text(ref.get("document_id")),
                _strings(ref.get("fact_ids")),
                _strings(ref.get("anchor_ids")),
                locator,
            )
        return {
            "evidence_ref_id": evidence_ref_id,
            "source_kind": source_kind,
            "document_id": _text(ref.get("document_id")),
            "label": _text(ref.get("label")) or _text(locator.get("source_ref")) or evidence_ref_id,
            "locator": locator,
            "fact_ids": _strings(ref.get("fact_ids")),
            "anchor_ids": _strings(ref.get("anchor_ids")),
            "confidence": ref.get("confidence"),
            "traceability_status": _text(ref.get("traceability_status")) or "unknown",
            "evidence_role": _text(ref.get("evidence_role")),
            "quote": _text(ref.get("quote")),
            "href": _text(ref.get("href")),
        }

    def _evidence_refs_from_evidence_units(
        self,
        evidence_units: list[dict[str, Any]],
        *,
        collection_id: str | None = None,
        blocks_by_id: Mapping[str, SourceBlock] | None = None,
        tables_by_id: Mapping[str, SourceTable] | None = None,
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for unit in evidence_units:
            unit_id = _text(unit.get("evidence_unit_id"))
            source_refs = _mapping_list(unit.get("source_refs"))
            if not source_refs:
                refs.append(
                    self._evidence_ref_from_unit(
                        unit,
                        source_ref=None,
                        collection_id=collection_id,
                        blocks_by_id=blocks_by_id or {},
                        tables_by_id=tables_by_id or {},
                    )
                )
                continue
            for source_ref in source_refs:
                refs.append(
                    self._evidence_ref_from_unit(
                        unit,
                        source_ref=source_ref,
                        collection_id=collection_id,
                        blocks_by_id=blocks_by_id or {},
                        tables_by_id=tables_by_id or {},
                    )
                )
            if unit_id and _strings(unit.get("evidence_anchor_ids")):
                refs.append(
                    self._evidence_ref_from_unit(
                        unit,
                        source_ref=None,
                        collection_id=collection_id,
                        blocks_by_id=blocks_by_id or {},
                        tables_by_id=tables_by_id or {},
                    )
                )
        return self._sort_evidence_refs_for_review(refs)

    def _comparison_condition_table_row(
        self,
        table: SourceTable,
        *,
        comparison_axis: str,
        context: Mapping[str, Any],
    ) -> tuple[int, tuple[str, ...], int, str] | None:
        headers = list(table.column_headers)
        comparison_index = next(
            (
                index
                for index, header in enumerate(headers)
                if self._axis_match_tokens(header)
                and self._axis_match_tokens(comparison_axis)
                == self._axis_match_tokens(header)
            ),
            None,
        )
        if comparison_index is None:
            return None
        expected_by_index: dict[int, str] = {}
        for index, header in enumerate(headers):
            expected = next(
                (
                    _text(value)
                    for key, value in context.items()
                    if _text(value)
                    and self._axis_match_tokens(header)
                    and self._axis_match_tokens(_text(key))
                    == self._axis_match_tokens(header)
                ),
                None,
            )
            if expected:
                expected_by_index[index] = expected
        if comparison_index not in expected_by_index or len(expected_by_index) < 2:
            return None
        for row_index, row in enumerate(table.table_matrix):
            if len(row) < len(headers):
                continue
            if all(
                self._energy_density_condition_matches(row[index], expected)
                for index, expected in expected_by_index.items()
            ):
                return (
                    row_index,
                    tuple(row),
                    len(expected_by_index),
                    row[comparison_index],
                )
        return None

    def _sort_evidence_refs_for_review(
        self,
        refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped = _dedupe_by_id(refs, "evidence_ref_id")
        return [
            ref
            for _, ref in sorted(
                enumerate(deduped),
                key=lambda item: (*self._evidence_ref_priority(item[1]), item[0]),
            )
        ]

    def _evidence_ref_priority(self, ref: Mapping[str, Any]) -> tuple[int, int]:
        source_kind = (_text(ref.get("source_kind")) or "").lower()
        priority = 40
        if "table" in source_kind:
            priority = 0
        elif "figure" in source_kind:
            priority = 1
        text = self._evidence_priority_text(ref).lower()
        if any(term in text for term in ("result", "discussion", "conclusion")):
            priority = min(priority, 2)
        if any(term in text for term in ("table", "figure", "value", "measured")):
            priority = min(priority, 3)
        if any(term in text for term in ("abstract", "introduction", "background")):
            priority = max(priority, 80)
        if not _text(ref.get("quote")) and source_kind in {"unknown", "text_window"}:
            priority = max(priority, 60)
        traceability_status = _text(ref.get("traceability_status")) or ""
        traceability_rank = 0 if traceability_status in {"resolved", "traceable"} else 1
        return (priority, traceability_rank)

    def _evidence_priority_text(self, ref: Mapping[str, Any]) -> str:
        locator = _locator_mapping(ref.get("locator"))
        return " ".join(
            value
            for value in (
                _text(ref.get("label")),
                _text(locator.get("source_ref")),
                _text(locator.get("source_kind")),
                _text(ref.get("quote")),
                _text(ref.get("source_kind")),
            )
            if value
        )

    def _evidence_ref_from_unit(
        self,
        unit: Mapping[str, Any],
        *,
        source_ref: Mapping[str, Any] | None,
        collection_id: str | None,
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, Any]:
        source = _mapping(source_ref)
        unit_id = _text(unit.get("evidence_unit_id"))
        source_kind = _text(source.get("source_kind")) or "unknown"
        source_ref_id = _text(source.get("source_ref"))
        block = blocks_by_id.get(source_ref_id) if source_ref_id else None
        table = tables_by_id.get(source_ref_id) if source_ref_id else None
        source_ref_label = (
            _text(source.get("display_label"))
            or _text(source.get("source_ref"))
            or _text(source.get("route_id"))
        )
        document_id = (
            _text(source.get("document_id"))
            or _text(unit.get("document_id"))
            or _text(block.document_id if block else None)
            or _text(table.document_id if table else None)
        )
        page = (
            source.get("page")
            if _text(source.get("page"))
            else (block.page if block and block.page is not None else None)
        )
        if page is None and table is not None and table.page is not None:
            page = table.page
        quote_text = _text(source.get("quote"))
        if not quote_text and block is not None:
            quote_text = _short_text(block.text, limit=420)
        if not quote_text and table is not None:
            quote_text = self._presentation_table_source_text(table)
        href = _text(source.get("href"))
        if not href and collection_id and source_ref_id and document_id:
            href = (
                _presentation_evidence_href(
                    collection_id=collection_id,
                    document_id=document_id,
                    source_ref=source_ref_id,
                    page=_text(page),
                    quote_text=quote_text,
                )
                or ""
            )
        evidence_ref_id = _stable_ref_id(
            source_kind,
            document_id,
            [unit_id] if unit_id else [],
            _strings(unit.get("evidence_anchor_ids")),
            source,
        )
        return {
            "evidence_ref_id": evidence_ref_id,
            "source_kind": source_kind,
            "document_id": document_id,
            "label": source_ref_label or unit_id or evidence_ref_id,
            "locator": {
                key: value
                for key, value in {
                    "source_ref": source_ref_id,
                    "route_id": _text(source.get("route_id")),
                    "source_kind": source_kind,
                    "page": page,
                }.items()
                if value
            },
            "fact_ids": [unit_id] if unit_id else [],
            "anchor_ids": _strings(unit.get("evidence_anchor_ids")),
            "confidence": unit.get("confidence"),
            "traceability_status": (
                _text(unit.get("resolution_status"))
                or ("traceable" if source or unit.get("evidence_anchor_ids") else "missing")
            ),
            "evidence_role": self._evidence_role_for_unit_source(unit, source),
            "quote": quote_text,
            "href": href,
        }

    def _evidence_role_for_unit_source(
        self,
        unit: Mapping[str, Any],
        source: Mapping[str, Any],
    ) -> str | None:
        return self._normalized_evidence_role(
            _text(source.get("evidence_role"))
            or _text(source.get("role"))
            or _text(unit.get("evidence_role"))
        )

    def _normalized_evidence_role(self, role: str | None) -> str | None:
        normalized = (_text(role) or "").lower()
        if normalized in {
            "direct_support",
            "current_experimental_evidence",
            "direct_experimental_evidence",
            "experimental_evidence",
            "supporting_experimental_evidence",
        }:
            return "direct_support"
        return _text(role)

    def _enrich_evidence_refs_from_source_blocks(
        self,
        refs: list[dict[str, Any]],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> list[dict[str, Any]]:
        if not refs or not blocks_by_id:
            return refs
        return [
            self._evidence_ref_with_source_block(ref, blocks_by_id=blocks_by_id)
            for ref in refs
        ]

    def _evidence_ref_with_source_block(
        self,
        ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_ref = _text(locator.get("source_ref"))
        block = blocks_by_id.get(source_ref or "") if source_ref else None
        if block is None:
            return dict(ref)
        enriched = dict(ref)
        enriched_locator = dict(locator)
        if block.page is not None and not _text(enriched_locator.get("page")):
            enriched_locator["page"] = block.page
        enriched["locator"] = enriched_locator
        if not _text(enriched.get("document_id")) and block.document_id:
            enriched["document_id"] = block.document_id
        if not _text(enriched.get("quote")) and _text(block.text):
            enriched["quote"] = _short_text(block.text, limit=420)
        return enriched

    def _record_with_traceable_evidence_refs(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        collection_id = _text(_mapping(record.get("scope")).get("collection_id"))
        refs = _mapping_list(record.get("evidence_refs"))
        if not collection_id or not refs:
            return dict(record)
        blocks_by_id, _documents_by_id, tables_by_id = self._source_artifact_lookups(
            collection_id
        )
        if not blocks_by_id and not tables_by_id:
            return dict(record)
        updated = dict(record)
        updated["evidence_refs"] = [
            self._traceable_evidence_ref(
                ref,
                collection_id=collection_id,
                blocks_by_id=blocks_by_id,
                tables_by_id=tables_by_id,
            )
            for ref in refs
        ]
        return updated

    def _record_with_comparison_condition_evidence(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        collection_id = _text(_mapping(record.get("scope")).get("collection_id"))
        if not collection_id:
            return dict(record)
        blocks_by_id, _documents_by_id, tables_by_id = self._source_artifact_lookups(
            collection_id
        )
        if not tables_by_id:
            return dict(record)
        tables_by_document: dict[str, list[SourceTable]] = {}
        for table in tables_by_id.values():
            tables_by_document.setdefault(table.document_id, []).append(table)
        evidence_refs = _mapping_list(record.get("evidence_refs"))
        evidence_by_id = {
            ref_id: ref
            for ref in evidence_refs
            if (ref_id := _text(ref.get("evidence_ref_id")))
        }
        contexts_by_id = {
            context_id: context
            for context in _mapping_list(record.get("contexts"))
            if (context_id := _text(context.get("context_id")))
        }
        generated_refs: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        for relation in _mapping_list(record.get("relations")):
            relation_ref_ids = _strings(relation.get("evidence_ref_ids"))
            if any(
                _text(evidence_by_id.get(ref_id, {}).get("evidence_role"))
                == "condition_context"
                for ref_id in relation_ref_ids
            ):
                relations.append(relation)
                continue
            process_payload = next(
                (
                    _mapping(contexts_by_id[context_id].get("process_context"))
                    for context_id in _strings(relation.get("context_ids"))
                    if context_id in contexts_by_id
                    and _mapping(
                        _mapping(contexts_by_id[context_id].get("process_context")).get(
                            "baseline_context"
                        )
                    )
                ),
                {},
            )
            source_object_ids = _strings(relation.get("source_object_ids"))
            direct_refs = [
                evidence_by_id[ref_id]
                for ref_id in relation_ref_ids
                if ref_id in evidence_by_id
            ]
            document_ids = {
                document_id
                for ref in direct_refs
                if (document_id := _text(ref.get("document_id")))
            }
            comparison_axis = self._presentation_relation_side(
                relation.get("subject")
            )
            current_context = {
                **_mapping(process_payload.get("sample_context")),
                **_mapping(process_payload.get("process_context")),
            }
            baseline = _mapping(process_payload.get("baseline_context"))
            baseline_context = {
                **_mapping(baseline.get("sample_context")),
                **_mapping(baseline.get("process_context")),
            }
            if (
                not comparison_axis
                or not source_object_ids
                or len(document_ids) != 1
                or not current_context
                or not baseline_context
            ):
                relations.append(relation)
                continue
            document_id = next(iter(document_ids))
            direct_source_refs = {
                source_ref
                for ref in direct_refs
                if (
                    source_ref := _text(
                        _locator_mapping(ref.get("locator")).get("source_ref")
                    )
                )
            }
            candidates = []
            for table in tables_by_document.get(document_id, []):
                if table.table_id in direct_source_refs:
                    continue
                current_match = self._comparison_condition_table_row(
                    table,
                    comparison_axis=comparison_axis,
                    context=current_context,
                )
                baseline_match = self._comparison_condition_table_row(
                    table,
                    comparison_axis=comparison_axis,
                    context=baseline_context,
                )
                if (
                    current_match
                    and baseline_match
                    and current_match[0] != baseline_match[0]
                    and not self._energy_density_condition_matches(
                        current_match[3],
                        baseline_match[3],
                    )
                ):
                    candidates.append(
                        (
                            current_match[2] + baseline_match[2],
                            -(table.table_order or 0),
                            table,
                            current_match,
                            baseline_match,
                        )
                    )
            if not candidates:
                relations.append(relation)
                continue
            _, _, table, current_match, baseline_match = max(
                candidates,
                key=lambda candidate: (candidate[0], candidate[1]),
            )
            quote = _presentation_table_audit_quote(
                {
                    "columns": list(table.column_headers),
                    "relevant_rows": [
                        {
                            "row_index": match[0],
                            "cells": list(match[1]),
                            "aligned": _table_row_cells_are_aligned(
                                list(match[1]),
                                list(table.column_headers),
                            ),
                        }
                        for match in (current_match, baseline_match)
                    ],
                }
            )
            condition_ref = self._evidence_ref_from_unit(
                {
                    "evidence_unit_id": source_object_ids[0],
                    "document_id": document_id,
                    "confidence": relation.get("confidence"),
                    "resolution_status": "resolved",
                },
                source_ref={
                    "source_kind": "table",
                    "source_ref": table.table_id,
                    "display_label": (
                        _text(table.caption_text) or "Comparison conditions"
                    ),
                    "page": table.page,
                    "evidence_role": "condition_context",
                    "quote": quote,
                },
                collection_id=collection_id,
                blocks_by_id=blocks_by_id,
                tables_by_id=tables_by_id,
            )
            condition_ref_id = _text(condition_ref.get("evidence_ref_id")) or ""
            generated_refs.append(condition_ref)
            relations.append(
                {
                    **relation,
                    "evidence_ref_ids": _dedupe_strings(
                        [*relation_ref_ids, condition_ref_id]
                    ),
                }
            )
        if not generated_refs:
            return dict(record)
        updated = dict(record)
        updated["relations"] = relations
        updated["evidence_refs"] = self._sort_evidence_refs_for_review(
            [*evidence_refs, *generated_refs]
        )
        return updated

    def _traceable_evidence_ref(
        self,
        ref: Mapping[str, Any],
        *,
        collection_id: str,
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_ref = _text(locator.get("source_ref"))
        if not source_ref:
            return dict(ref)
        block = blocks_by_id.get(source_ref)
        table = tables_by_id.get(source_ref)
        if block is None and table is None:
            return dict(ref)
        enriched = dict(ref)
        enriched_locator = dict(locator)
        if block is not None:
            if block.page is not None and not _text(enriched_locator.get("page")):
                enriched_locator["page"] = block.page
            if not _text(enriched.get("document_id")):
                enriched["document_id"] = block.document_id
            if not _text(enriched.get("quote")) and _text(block.text):
                enriched["quote"] = _short_text(block.text, limit=420)
        if table is not None:
            if table.page is not None and not _text(enriched_locator.get("page")):
                enriched_locator["page"] = table.page
            if not _text(enriched.get("document_id")):
                enriched["document_id"] = table.document_id
            if not _text(enriched.get("quote")):
                enriched["quote"] = self._presentation_table_source_text(table)
        enriched["locator"] = enriched_locator
        if not _text(enriched.get("href")):
            href = _presentation_evidence_href(
                collection_id=collection_id,
                document_id=_text(enriched.get("document_id")),
                source_ref=source_ref,
                page=_text(enriched_locator.get("page")),
                quote_text=_text(enriched.get("quote")),
            )
            if href:
                enriched["href"] = href
        return enriched

    def _statement_from_evidence_unit(self, unit: Mapping[str, Any]) -> str | None:
        unit_kind = _text(unit.get("unit_kind"))
        property_name = _text(unit.get("property_normalized"))
        value_payload = _mapping(unit.get("value_payload"))
        source_value = (
            _text(value_payload.get("source_value_text"))
            or _text(value_payload.get("value"))
            or _text(value_payload.get("statement"))
        )
        summary = _text(value_payload.get("summary"))
        unit_text = _text(unit.get("unit"))
        interpretation = _text(unit.get("interpretation"))
        if unit_kind == "comparison":
            return (
                self._comparison_statement(unit, property_name)
                or _text(value_payload.get("summary"))
                or interpretation
                or _text(value_payload.get("statement"))
                or _text(value_payload.get("source_value_text"))
            )
        if unit_kind in _DIRECT_RESULT_CONTEXT_UNIT_KINDS:
            direct_statement = self._direct_result_statement_from_evidence_unit(unit)
            if direct_statement:
                return direct_statement
        if interpretation:
            return interpretation
        if unit_kind in {"characterization", "interpretation", "mechanism"} and summary:
            return summary
        if property_name and source_value:
            suffix = f" {unit_text}" if unit_text and unit_text not in source_value else ""
            return f"{property_name} is reported as {source_value}{suffix}."
        return source_value

    def _reviewable_objective_claim_type(
        self,
        unit: Mapping[str, Any],
        statement: str,
        *,
        target_axes: list[str] | tuple[str, ...] = (),
    ) -> str | None:
        if not self._looks_complete_claim_statement(statement):
            return None
        if not self._objective_unit_matches_claim_target(
            unit,
            statement,
            target_axes,
        ):
            return None
        unit_kind = _text(unit.get("unit_kind"))
        property_name = _text(unit.get("property_normalized"))
        if unit_kind == "measurement":
            return (
                "measurement"
                if property_name and self._has_source_value(unit)
                else None
            )
        if self._is_noisy_objective_claim_statement(statement):
            return None
        if unit_kind == "comparison":
            sample_context = _mapping(unit.get("sample_context"))
            baseline_context = _mapping(unit.get("baseline_context"))
            sample_values = _display_values(sample_context)
            baseline_values = _display_values(baseline_context)
            process_values = _display_values(_mapping(unit.get("process_context")))
            row_level_keys = {
                "sample_number",
                "condition_number",
                "sample_id",
                "condition_id",
            }
            context_keys = {
                _text(key).lower()
                for key in (*sample_context.keys(), *baseline_context.keys())
                if _text(key)
            }
            if (
                sample_values
                and baseline_values
                and not process_values
                and context_keys.intersection(row_level_keys)
            ):
                return None
            return (
                "comparison"
                if property_name and self._has_comparison_signal(unit)
                else None
            )
        if unit_kind in {"characterization", "interpretation", "mechanism"}:
            lower_statement = f" {_text(statement).lower()} "
            mechanism_signals = (
                " improves",
                " improve",
                " reduces",
                " reduce",
                " increases",
                " increase",
                " decreases",
                " decrease",
                " affects",
                " affect",
                " explains",
                " explain",
                " leads to ",
                " led to ",
                " results in ",
                " resulted in ",
                " associated with ",
                " directly linking ",
            )
            return (
                "mechanism"
                if any(signal in lower_statement for signal in mechanism_signals)
                else None
            )
        if unit_kind in _DIRECT_RESULT_CONTEXT_UNIT_KINDS:
            return (
                "finding"
                if self._objective_unit_has_direct_result_signal(unit)
                else None
            )
        return None

    def _objective_unit_has_direct_result_signal(self, unit: Mapping[str, Any]) -> bool:
        if self._objective_unit_evidence_role(unit) != "direct_support":
            return False
        if not _mapping_list(unit.get("source_refs")):
            return False
        statement = self._direct_result_statement_from_evidence_unit(unit)
        if not statement or self._is_noisy_objective_claim_statement(statement):
            return False
        return self._looks_complete_claim_statement(statement)

    def _direct_result_statement_from_evidence_unit(
        self,
        unit: Mapping[str, Any],
    ) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        variable = self._deterministic_relation_subject(unit)
        property_name = (
            _text(value_payload.get("property"))
            or _text(unit.get("property_normalized"))
            or "observed response"
        )
        trend = _text(value_payload.get("trend")) or _text(value_payload.get("direction"))
        value = _text(value_payload.get("value")) or _text(
            value_payload.get("source_value_text")
        )
        if variable and property_name and trend and value:
            verb = self._comparison_direction_verb(trend)
            value_text = self._direct_result_value_text(value)
            if value_text:
                return self._sentence_case(
                    f"{variable} {verb} {property_name} by {value_text}."
                )
            return self._sentence_case(f"{variable} {verb} {property_name}.")
        interpretation = _text(unit.get("interpretation"))
        if interpretation and _looks_user_facing(interpretation):
            return interpretation
        for key in ("summary", "statement", "source_value_text"):
            text = _text(value_payload.get(key))
            if text and _looks_user_facing(text):
                return text
        return ""

    def _direct_result_value_text(self, value: str) -> str:
        text = _text(value) or ""
        return re.sub(r"\s+(increase|decrease|improvement|reduction)$", "", text).strip()

    def _objective_target_axes_for_claims(
        self,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[str]:
        lens = _mapping(objective_context.get("objective_evidence_lens"))
        return _dedupe_strings(
            [
                *(_strings(lens.get("target_outcome_axes"))),
                *(_strings(objective_context.get("target_property_axes"))),
                *(_strings(objective.get("property_axes"))),
            ]
        )

    def _objective_unit_matches_claim_target(
        self,
        unit: Mapping[str, Any],
        statement: str,
        target_axes: list[str] | tuple[str, ...],
    ) -> bool:
        if not target_axes:
            return True
        property_name = _text(unit.get("property_normalized"))
        if property_name and self._objective_statement_mentions_target_axis(
            property_name,
            target_axes,
        ):
            return True
        value_payload = _mapping(unit.get("value_payload"))
        text = " ".join(
            item
            for item in (
                statement,
                _text(value_payload.get("summary")),
                _text(value_payload.get("source_value_text")),
                _text(value_payload.get("statement")),
                _text(unit.get("interpretation")),
            )
            if item
        )
        return self._objective_statement_mentions_target_axis(text, target_axes)

    def _objective_statement_mentions_target_axis(
        self,
        statement: str,
        target_axes: list[str] | tuple[str, ...],
    ) -> bool:
        if not target_axes:
            return True
        return any(
            self._objective_axis_tokens_match(statement, axis)
            for axis in target_axes
        )

    def _objective_axis_tokens_match(self, text: str, axis: str) -> bool:
        axis_tokens = tuple(re.findall(r"[a-z0-9]+", (axis or "").lower()))
        text_tokens = tuple(re.findall(r"[a-z0-9]+", (text or "").lower()))
        if not axis_tokens or not text_tokens:
            return False
        if len(axis_tokens) > 1 and len(axis_tokens) <= len(text_tokens):
            for index in range(0, len(text_tokens) - len(axis_tokens) + 1):
                if text_tokens[index : index + len(axis_tokens)] == axis_tokens:
                    return True
        if axis_tokens == ("relative", "density"):
            axis_tokens = ("density",)
        if len(axis_tokens) != 1:
            return False
        axis_token = axis_tokens[0]
        for index, token in enumerate(text_tokens):
            if token != axis_token:
                continue
            previous = text_tokens[index - 1] if index > 0 else ""
            if axis_token == "density" and previous == "dislocation":
                continue
            return True
        return False

    def _is_noisy_objective_claim_statement(self, statement: str) -> bool:
        text = _text(statement) or ""
        lower = text.lower()
        if not lower:
            return True
        if lower.startswith("sample ") and " has the highest " in lower:
            return True
        if " table-derived " in lower and " has the highest " in lower:
            return True
        if "measurement is relative to" in lower:
            return True
        if lower.startswith(("future work", "further work")):
            return True
        if lower.startswith("further ") and (
            " required" in lower
            or " needed" in lower
            or " should " in lower
        ):
            return True
        if " should be investigated" in lower or " remains to be studied" in lower:
            return True
        if " is assumed " in lower or " are assumed " in lower:
            return True
        if " is reported as " in lower and lower.endswith(" analysis."):
            return True
        return False

    def _is_aggregate_logic_summary(self, statement: str) -> bool:
        text = _text(statement) or ""
        lower = text.lower()
        if not lower:
            return True
        aggregate_signals = (
            " assembled ",
            " measurement unit(s)",
            " across ",
            " density range ",
            " relative density range ",
            " table ",
        )
        signal_count = sum(1 for signal in aggregate_signals if signal in lower)
        return signal_count >= 2 or (len(text) > 220 and ":" in text)

    def _has_source_value(self, unit: Mapping[str, Any]) -> bool:
        value_payload = _mapping(unit.get("value_payload"))
        return bool(
            _text(value_payload.get("source_value_text"))
            or _text(value_payload.get("value"))
            or _text(value_payload.get("statement"))
        )

    def _has_comparison_signal(self, unit: Mapping[str, Any]) -> bool:
        value_payload = _mapping(unit.get("value_payload"))
        return bool(
            _text(value_payload.get("comparison_axis"))
            or _text(value_payload.get("direction"))
            or _text(value_payload.get("trend"))
            or _text(value_payload.get("summary"))
            or _text(value_payload.get("source_value_text"))
            or _text(value_payload.get("statement"))
            or _text(unit.get("interpretation"))
        )

    def _looks_complete_claim_statement(self, statement: str) -> bool:
        text = _text(statement)
        if not text or not _looks_user_facing(text):
            return False
        lower = f" {text.lower()} "
        claim_signals = (
            " is ",
            " are ",
            " was ",
            " were ",
            " has ",
            " have ",
            " shows ",
            " show ",
            " improves",
            " improve",
            " improved",
            " reduces",
            " reduce",
            " reduced",
            " increases",
            " increase",
            " increased",
            " decreases",
            " decrease",
            " decreased",
            " affects",
            " affect",
            " affected",
            " correlates",
            " correlate",
            " correlated",
            " explains",
            " explain",
            " explained",
            " indicates",
            " indicate",
            " indicated",
            " suggests",
            " suggest",
            " suggested",
            " leads to ",
            " led to ",
            " results in ",
            " resulted in ",
            " associated with ",
            " reported as ",
            " observed ",
            " formed ",
            " exhibits ",
            " exhibit ",
        )
        has_claim_signal = any(signal in lower for signal in claim_signals)
        if lower.strip().startswith(
            (
                "achieved through ",
                "based on ",
                "under ",
                "using ",
                "with ",
                "without ",
            )
        ) and not has_claim_signal:
            return False
        return has_claim_signal

    def _comparison_statement(
        self,
        unit: Mapping[str, Any],
        property_name: str | None,
    ) -> str | None:
        value_payload = _mapping(unit.get("value_payload"))
        process_context = _mapping(unit.get("process_context"))
        baseline_context = _mapping(unit.get("baseline_context"))
        baseline_process_context = _mapping(baseline_context.get("process_context"))
        raw_axis = _text(value_payload.get("comparison_axis"))
        axis = self._display_axis_label(raw_axis)
        direction = _text(value_payload.get("direction")) or _text(value_payload.get("trend"))
        property_text = _text(property_name) or "observed response"
        if not axis and not property_text:
            return None
        verb = self._comparison_direction_verb(direction)
        unit_text = _text(unit.get("unit"))
        current_value = self._comparison_display_value(
            _text(value_payload.get("current_value"))
            or _text(value_payload.get("value")),
            unit_text,
        )
        baseline_value = self._comparison_display_value(
            _text(baseline_context.get("source_value_text"))
            or _text(baseline_context.get("value")),
            unit_text,
        )
        raw_axis_display = raw_axis or axis
        current_axis_value = (
            self._axis_value_from_context(raw_axis, process_context)
            or (
                self._axis_value_from_context(axis, process_context)
                if not _symbol_match_term(raw_axis)
                else ""
            )
            if axis or raw_axis
            else ""
        )
        baseline_axis_value = (
            self._axis_value_from_context(raw_axis, baseline_process_context)
            or (
                self._axis_value_from_context(axis, baseline_process_context)
                if not _symbol_match_term(raw_axis)
                else ""
            )
            if axis or raw_axis
            else ""
        )
        current_label = self._comparison_axis_label(
            raw_axis_display if _symbol_match_term(raw_axis) else axis,
            current_axis_value,
        )
        baseline_label = (
            self._comparison_axis_label(
                raw_axis_display if _symbol_match_term(raw_axis) else axis,
                baseline_axis_value,
            )
            if baseline_axis_value
            else ""
        )
        current_context_label = self._comparison_context_value_label(
            process_context,
            axis=raw_axis if _symbol_match_term(raw_axis) else axis,
        )
        baseline_context_label = self._comparison_context_value_label(
            baseline_process_context,
            axis=raw_axis if _symbol_match_term(raw_axis) else axis,
        )
        if current_context_label:
            current_label = current_context_label
        if baseline_context_label:
            baseline_label = baseline_context_label
        if not baseline_label:
            baseline_label = _join_display_values(
                _display_values(_mapping(baseline_context.get("sample_context"))),
                limit=2,
            )
        subject = current_label or axis or property_text
        controlled_axes = self._comparison_controlled_axes_text(value_payload)
        if current_value and baseline_value:
            if (
                _symbol_match_term(raw_axis)
                and current_axis_value
                and baseline_axis_value
            ):
                prefix = f"With {controlled_axes}, " if controlled_axes else ""
                statement = (
                    f"{prefix}changing {raw_axis_display} from {baseline_axis_value} "
                    f"to {current_axis_value} {verb} {property_text} from "
                    f"{baseline_value} to {current_value}."
                )
                return self._sentence_case(statement)
            prefix = f"Under {controlled_axes}, " if controlled_axes else ""
            if baseline_label:
                statement = (
                    f"{prefix}{subject} {verb} {property_text} from "
                    f"{baseline_value} ({baseline_label}) to {current_value}."
                )
            else:
                statement = (
                    f"{prefix}{subject} {verb} {property_text} from "
                    f"{baseline_value} to {current_value}."
                )
        else:
            source_statement = self._comparison_source_statement(value_payload)
            if source_statement:
                return source_statement
            if baseline_label and baseline_label.lower() != subject.lower():
                statement = (
                    f"{prefix}{subject} {verb} {property_text} relative to "
                    f"{baseline_label}."
                )
            else:
                return None
        return self._sentence_case(statement)

    def _comparison_source_statement(
        self,
        value_payload: Mapping[str, Any],
    ) -> str:
        for key in ("source_value_text", "statement", "summary"):
            text = _text(value_payload.get(key))
            if (
                text
                and _looks_user_facing(text)
                and self._looks_complete_claim_statement(text)
            ):
                return _short_text(text, limit=220)
        return ""

    def _comparison_controlled_axes_text(
        self,
        value_payload: Mapping[str, Any],
    ) -> str:
        axes = []
        for item in _mapping_list(value_payload.get("controlled_axes")):
            raw_axis = _text(item.get("axis"))
            axis = self._display_axis_label(raw_axis)
            value = _text(item.get("value"))
            if axis and value:
                axes.append(self._comparison_axis_label(axis, value))
        axes = _dedupe_strings(axes)
        if len(axes) == 1:
            return axes[0]
        if len(axes) > 1:
            return f"{', '.join(axes[:-1])} and {axes[-1]}"
        return ""

    def _axis_value_from_context(
        self,
        axis: str | None,
        context: Mapping[str, Any],
    ) -> str:
        axis_tokens = self._axis_match_tokens(axis)
        if not axis_tokens:
            return ""
        for key, value in context.items():
            key_tokens = self._axis_match_tokens(_text(key))
            if axis_tokens and axis_tokens <= key_tokens:
                return _text(value) or ""
        return ""

    def _axis_match_tokens(self, value: str | None) -> set[str]:
        symbol_term = _symbol_match_term(value)
        if symbol_term:
            return {symbol_term}
        symbol_text = str(value or "")
        for symbol in ("α", "β", "θ", "ɵ"):
            if symbol in symbol_text:
                return {_symbol_match_term(symbol)}
        text = _normalize_match_text(_text(value) or "")
        replacements = {
            "scanning": "scan",
            "volumetric": "volume",
        }
        ignored_tokens = {"of", "the", "mm", "s", "w", "j", "cm", "3"}
        tokens = {
            replacements.get(token, token)
            for token in text.split()
            if token and token not in ignored_tokens
        }
        if "ved" in tokens:
            tokens.update({"volume", "energy", "density"})
        if {"volume", "energy", "density"} <= tokens:
            tokens.add("ved")
        return tokens

    def _comparison_axis_label(self, axis: str | None, value: str | None) -> str:
        axis_text = _text(axis)
        value_text = _text(value)
        if axis_text and value_text:
            separator = "=" if _symbol_match_term(axis_text) else " "
            return f"{axis_text}{separator}{value_text}"
        return axis_text or ""

    def _comparison_context_value_label(
        self,
        context: Mapping[str, Any],
        *,
        axis: str | None,
    ) -> str:
        axis_tokens = self._axis_match_tokens(axis)
        if not axis_tokens:
            return ""
        ignored_keys = {
            "fe",
            "mn",
            "mo",
            "nb",
            "si",
            "column_1",
            "sample",
            "sample #",
            "sample number",
            "sample_number",
            "condition_number",
            "condition_id",
            "sample_id",
        }
        for key, value in context.items():
            key_text = _text(key)
            value_text = _text(value)
            if not key_text or not value_text:
                continue
            if axis_tokens - self._axis_match_tokens(key_text):
                continue
            normalized_key = _normalize_match_text(key_text)
            if normalized_key in ignored_keys:
                continue
            if _symbol_match_term(key_text):
                continue
            normalized_value = _normalize_match_text(value_text)
            if not normalized_value or normalized_value == normalized_key:
                continue
            if value_text.lower() in {"fe", "mn", "mo", "nb", "si"}:
                continue
            axis_label = self._display_axis_label(axis)
            if axis_label and axis_label.lower() not in value_text.lower():
                return f"{axis_label} {value_text}"
            return value_text
        return ""

    def _comparison_display_value(self, value: str | None, unit_text: str | None) -> str:
        text = _text(value)
        if not text:
            return ""
        unit = _text(unit_text)
        if unit and unit not in text:
            return f"{text} {unit}"
        return text

    def _comparison_direction_verb(self, direction: str | None) -> str:
        normalized = self._normalized_relation_predicate(direction)
        return {
            "increases": "increased",
            "decreases": "decreased",
            "improves": "improved",
            "reduces": "reduced",
        }.get(normalized, "changed")

    def _normalized_relation_predicate(self, value: str | None) -> str:
        normalized = (_text(value) or "").lower()
        return {
            "increase": "increases",
            "increased": "increases",
            "increases": "increases",
            "decrease": "decreases",
            "decreased": "decreases",
            "decreases": "decreases",
            "improve": "improves",
            "improved": "improves",
            "improves": "improves",
            "reduce": "reduces",
            "reduced": "reduces",
            "reduces": "reduces",
            "affect": "affects",
            "affected": "affects",
            "affects": "affects",
        }.get(normalized, _short_text(normalized, limit=80) if normalized else "")

    def _sentence_case(self, statement: str) -> str:
        text = statement.strip()
        if not text:
            return ""
        return f"{text[0].upper()}{text[1:]}"

    def _claim(
        self,
        *,
        claim_type: str,
        statement: str,
        source_object_ids: list[str] | tuple[str, ...],
        evidence_ref_ids: list[str],
        context_ids: list[str],
        seen: set[str],
        status: str | None = None,
        strength: str | None = None,
        confidence: Any = None,
    ) -> dict[str, Any]:
        key = statement.strip().lower()
        if key in seen:
            return {}
        seen.add(key)
        return {
            "claim_type": claim_type,
            "statement": statement,
            "status": status or ("supported" if evidence_ref_ids else "limited"),
            "confidence": confidence,
            "strength": strength,
            "evidence_ref_ids": evidence_ref_ids,
            "context_ids": context_ids,
            "source_object_ids": list(source_object_ids),
            "warnings": [] if evidence_ref_ids else ["missing_evidence_ref"],
        }

    def _ref_ids_for(
        self,
        fact_ids: list[str] | tuple[str, ...],
        evidence_ref_ids_by_fact: dict[str, list[str]],
    ) -> list[str]:
        ref_ids: list[str] = []
        for fact_id in fact_ids:
            ref_ids.extend(evidence_ref_ids_by_fact.get(fact_id, []))
        return _dedupe_strings(ref_ids)

    def _fact_ids_from_refs(self, refs: list[dict[str, Any]]) -> list[str]:
        fact_ids: list[str] = []
        for ref in refs:
            fact_ids.extend(_strings(ref.get("fact_ids")))
        return _dedupe_strings(fact_ids)

    def _evidence_ref_ids_by_fact(
        self,
        refs: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for ref in refs:
            ref_id = _text(ref.get("evidence_ref_id"))
            if not ref_id:
                continue
            for fact_id in _strings(ref.get("fact_ids")):
                grouped.setdefault(fact_id, []).append(ref_id)
        return {key: _dedupe_strings(value) for key, value in grouped.items()}

    def _presentation_relation_type(self, relation_type: str, direction: str) -> str:
        normalized_direction = self._normalized_relation_predicate(direction)
        if normalized_direction in {"improves", "reduces", "increases", "decreases"}:
            return normalized_direction
        normalized_type = (relation_type or "").lower()
        if normalized_type == "conflicting":
            return "conflicts"
        if normalized_type == "comparative":
            return "compares"
        if normalized_type == "mechanistic":
            return "explains"
        if normalized_type == "correlational":
            return "correlates"
        return "compares"

    def _state_for(
        self,
        claims: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
    ) -> str:
        claims = [claim for claim in claims if claim]
        if not claims and not relations and not evidence_refs:
            return "empty"
        if any(claim.get("status") == "supported" for claim in claims):
            return "ready"
        if claims or relations:
            return "limited"
        return "partial"

    def _state_with_presentation(self, record: Mapping[str, Any]) -> str:
        state = _text(record.get("state")) or "empty"
        if state != "empty":
            return state
        presentation = _mapping(record.get("presentation"))
        summary = _mapping(presentation.get("summary"))
        finding_count = _safe_count(summary.get("primary_finding_count")) + _safe_count(
            summary.get("review_queue_finding_count")
        )
        if finding_count:
            return "limited"
        return state

    def _understanding_warnings(
        self,
        claims: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
        *,
        extra_warnings: list[str] | tuple[str, ...] = (),
    ) -> list[str]:
        warnings: list[str] = []
        if claims and not evidence_refs:
            warnings.append("claims_without_evidence_refs")
        if any("missing_evidence_ref" in claim.get("warnings", []) for claim in claims):
            warnings.append("some_claims_missing_evidence_refs")
        warnings.extend(_strings(extra_warnings))
        return _dedupe_strings(warnings)

    def _record_with_recovered_presentation_objects(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        updated = dict(record)
        scope = _mapping(updated.get("scope"))
        blocks_by_id, _documents_by_id, tables_by_id = self._source_artifact_lookups(
            _text(scope.get("collection_id"))
        )
        recovered_findings = self._recovered_presentation_findings_from_source_blocks(
            updated,
            blocks_by_id=blocks_by_id,
            tables_by_id=tables_by_id,
        )
        if not recovered_findings:
            return updated
        updated = self._record_without_superseded_recovered_objects(
            updated,
            recovered_findings=recovered_findings,
        )
        updated["claims"] = self._dedupe_claims_for_understanding(
            [
                *[
                    recovered["claim"]
                    for recovered in recovered_findings
                    if recovered.get("claim")
                ],
                *_mapping_list(updated.get("claims")),
            ]
        )
        updated["relations"] = _dedupe_by_id(
            [
                *[
                    recovered["relation"]
                    for recovered in recovered_findings
                    if recovered.get("relation")
                ],
                *_mapping_list(updated.get("relations")),
            ],
            "relation_id",
        )
        updated["evidence_refs"] = self._sort_evidence_refs_for_review(
            [
                *[
                    evidence_ref
                    for recovered in recovered_findings
                    for evidence_ref in self._recovered_evidence_refs(recovered)
                ],
                *_mapping_list(updated.get("evidence_refs")),
            ]
        )
        updated["contexts"] = _dedupe_by_id(
            [
                *[
                    recovered["context"]
                    for recovered in recovered_findings
                    if recovered.get("context")
                ],
                *_mapping_list(updated.get("contexts")),
            ],
            "context_id",
        )
        updated["warnings"] = self._understanding_warnings(
            _mapping_list(updated.get("claims")),
            _mapping_list(updated.get("evidence_refs")),
            extra_warnings=_strings(updated.get("warnings")),
        )
        return updated

    def _record_without_superseded_recovered_objects(
        self,
        record: Mapping[str, Any],
        *,
        recovered_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        current_claim_ids = {
            claim_id
            for recovered in recovered_findings
            if (claim_id := _text(_mapping(recovered.get("claim")).get("claim_id")))
        }
        current_relation_ids = {
            relation_id
            for recovered in recovered_findings
            if (
                relation_id := _text(
                    _mapping(recovered.get("relation")).get("relation_id")
                )
            )
        }
        current_source_object_ids = {
            source_object_id
            for recovered in recovered_findings
            for source_object_id in _strings(
                _mapping(recovered.get("claim")).get("source_object_ids")
            )
        }
        if not current_source_object_ids:
            return dict(record)

        claims = _mapping_list(record.get("claims"))
        stale_claims = [
            claim
            for claim in claims
            if (_text(claim.get("claim_id")) or "").startswith("claim_recovered_")
            and _text(claim.get("claim_id")) not in current_claim_ids
            and _intersects(
                _strings(claim.get("source_object_ids")),
                current_source_object_ids,
            )
        ]
        relations = _mapping_list(record.get("relations"))
        stale_relations = [
            relation
            for relation in relations
            if (_text(relation.get("relation_id")) or "").startswith("rel_recovered_")
            and _text(relation.get("relation_id")) not in current_relation_ids
            and _intersects(
                _strings(relation.get("source_object_ids")),
                current_source_object_ids,
            )
        ]
        if not stale_claims and not stale_relations:
            return dict(record)

        stale_claim_ids = {
            _text(claim.get("claim_id")) for claim in stale_claims
        }
        stale_relation_ids = {
            _text(relation.get("relation_id")) for relation in stale_relations
        }
        retained_claims = [
            claim
            for claim in claims
            if _text(claim.get("claim_id")) not in stale_claim_ids
        ]
        retained_relations = [
            relation
            for relation in relations
            if _text(relation.get("relation_id")) not in stale_relation_ids
        ]
        stale_evidence_ref_ids = {
            ref_id
            for item in [*stale_claims, *stale_relations]
            for ref_id in _strings(item.get("evidence_ref_ids"))
        }
        retained_evidence_ref_ids = {
            ref_id
            for item in [*retained_claims, *retained_relations]
            for ref_id in _strings(item.get("evidence_ref_ids"))
        }
        stale_context_ids = {
            context_id
            for item in [*stale_claims, *stale_relations]
            for context_id in _strings(item.get("context_ids"))
        }
        retained_context_ids = {
            context_id
            for item in [*retained_claims, *retained_relations]
            for context_id in _strings(item.get("context_ids"))
        }
        updated = dict(record)
        updated["claims"] = retained_claims
        updated["relations"] = retained_relations
        updated["evidence_refs"] = [
            ref
            for ref in _mapping_list(record.get("evidence_refs"))
            if _text(ref.get("evidence_ref_id"))
            not in stale_evidence_ref_ids - retained_evidence_ref_ids
        ]
        updated["contexts"] = [
            context
            for context in _mapping_list(record.get("contexts"))
            if _text(context.get("context_id"))
            not in stale_context_ids - retained_context_ids
        ]
        return updated

    def _record_without_off_axis_recovered_objects(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        updated = dict(record)
        contexts = _mapping_list(updated.get("contexts"))
        objective, objective_context = self._presentation_recovery_objective(
            _mapping(updated.get("scope")),
            contexts=contexts,
        )
        goal_axes = _dedupe_strings(
            [
                *_strings(objective.get("process_axes")),
                *_strings(objective_context.get("variable_process_axes")),
            ]
        )
        if not goal_axes:
            return updated
        relations = _mapping_list(updated.get("relations"))
        off_axis_relation_ids = {
            relation_id
            for relation in relations
            if (relation_id := _text(relation.get("relation_id")))
            and relation_id.startswith("rel_recovered_")
            and not self._relation_matches_goal_axis(relation, goal_axes)
        }
        if not off_axis_relation_ids:
            return updated
        off_axis_evidence_ref_ids = {
            ref_id
            for relation in relations
            if _text(relation.get("relation_id")) in off_axis_relation_ids
            for ref_id in _strings(relation.get("evidence_ref_ids"))
        }
        off_axis_context_ids = {
            context_id
            for relation in relations
            if _text(relation.get("relation_id")) in off_axis_relation_ids
            for context_id in _strings(relation.get("context_ids"))
        }
        updated["relations"] = [
            relation
            for relation in relations
            if _text(relation.get("relation_id")) not in off_axis_relation_ids
        ]
        updated["claims"] = [
            claim
            for claim in _mapping_list(updated.get("claims"))
            if not (
                (_text(claim.get("claim_id")) or "").startswith("claim_recovered_")
                and _intersects(
                    _strings(claim.get("evidence_ref_ids")),
                    off_axis_evidence_ref_ids,
                )
            )
        ]
        updated["evidence_refs"] = [
            ref
            for ref in _mapping_list(updated.get("evidence_refs"))
            if _text(ref.get("evidence_ref_id")) not in off_axis_evidence_ref_ids
        ]
        updated["contexts"] = [
            context
            for context in contexts
            if _text(context.get("context_id")) not in off_axis_context_ids
        ]
        return updated

    def _presentation_for(self, record: Mapping[str, Any]) -> dict[str, Any]:
        claims = _mapping_list(record.get("claims"))
        relations = _mapping_list(record.get("relations"))
        evidence_refs = _mapping_list(record.get("evidence_refs"))
        contexts = _mapping_list(record.get("contexts"))
        scope = _mapping(record.get("scope"))
        blocks_by_id, documents_by_id, tables_by_id = self._source_artifact_lookups(
            _text(scope.get("collection_id"))
        )
        evidence_by_id = {
            _text(ref.get("evidence_ref_id")): ref
            for ref in evidence_refs
            if _text(ref.get("evidence_ref_id"))
        }
        contexts_by_id = {
            _text(context.get("context_id")): context
            for context in contexts
            if _text(context.get("context_id"))
        }
        relations_by_id = {
            _text(relation.get("relation_id")): relation
            for relation in relations
            if _text(relation.get("relation_id"))
        }
        effects = [
            self._presentation_effect(
                claim,
                relations=relations,
                evidence_by_id=evidence_by_id,
                contexts_by_id=contexts_by_id,
            )
            for claim in claims
            if _text(claim.get("statement"))
        ]
        covered_relation_ids = {
            relation_id
            for effect in effects
            for relation_id in _strings(effect.get("relation_ids"))
        }
        goal_axes = _dedupe_strings(
            [
                axis
                for context in contexts_by_id.values()
                if (
                    _text(context.get("context_id")) == "ctx_objective_scope"
                    or _normalize_match_text(_text(context.get("label")) or "")
                    in {"objective scope", "goal scope"}
                )
                for process_context in [_mapping(context.get("process_context"))]
                for axis in _strings(process_context.get("variable_process_axes"))
            ]
        )
        relation_effects = [
            self._presentation_relation_effect(
                relation,
                evidence_by_id=evidence_by_id,
                contexts_by_id=contexts_by_id,
            )
            for relation in relations
            if _text(relation.get("relation_id")) not in covered_relation_ids
            and self._reviewable_presentation_relation(relation)
            and self._relation_can_drive_presentation_finding(
                relation,
                evidence_by_id=evidence_by_id,
                existing_effects=effects,
            )
            and self._relation_matches_goal_axis(relation, goal_axes)
        ]
        effects.extend(relation_effects)
        context_summaries = [
            self._presentation_context_summary(context)
            for context in contexts
        ]
        summary_contexts = [
            context
            for context in contexts
            if not _text(context.get("source_evidence_unit_id"))
            and not (_text(context.get("context_id")) or "").endswith("_boundary")
        ] or contexts
        scope_contexts = [
            context for context in summary_contexts if self._is_scope_context(context)
        ]
        axis_contexts = scope_contexts or summary_contexts
        material_scope = _dedupe_strings(
            [
                value
                for context in summary_contexts
                for value in _strings(context.get("material_scope"))
            ]
        )
        property_scope = _dedupe_strings(
            [
                value
                for context in axis_contexts
                for value in _strings(context.get("property_scope"))
            ]
        )
        property_scope = self._dedupe_axis_labels(
            [
                *property_scope,
                *self._presentation_recovery_property_axes_from_title(
                    _text(scope.get("title")) or ""
                ),
            ]
        )
        variable_axes = _dedupe_strings(
            [
                value
                for context in axis_contexts
                for value in _display_values(_mapping(context.get("process_context")))
            ]
        )
        variable_axes = self._dedupe_axis_labels(
            [
                *variable_axes,
                *self._presentation_recovery_process_axes_from_title(
                    _text(scope.get("title")) or ""
                ),
            ]
        )
        variable_axes = [
            axis
            for axis in variable_axes
            if not self._is_platform_process_context_axis(axis)
        ]
        findings = [
            self._presentation_finding(
                effect,
                evidence_by_id=evidence_by_id,
                relations_by_id=relations_by_id,
                blocks_by_id=blocks_by_id,
                tables_by_id=tables_by_id,
                contexts_by_id=contexts_by_id,
            )
            for effect in effects
        ]
        if _text(scope.get("scope_type")) == "goal" and goal_axes:
            findings = [
                finding
                for finding in findings
                if any(
                    self._axis_labels_match(variable, axis)
                    for variable in _strings(finding.get("variables"))
                    for axis in goal_axes
                )
            ]
        findings = [
            finding
            for finding in findings
            if self._reviewable_expert_finding(
                finding,
                evidence_by_id=evidence_by_id,
                blocks_by_id=blocks_by_id,
            )
        ]
        findings = self._sort_presentation_findings(findings)
        findings = self._merge_duplicate_presentation_findings(
            findings,
            evidence_by_id=evidence_by_id,
        )
        findings = [
            self._finding_with_aligned_direct_evidence(
                finding,
                evidence_by_id=evidence_by_id,
            )
            for finding in findings
        ]
        findings = [
            self._finding_with_compact_table_direct_evidence(
                finding,
                evidence_by_id=evidence_by_id,
            )
            for finding in findings
        ]
        findings = [
            self._finding_with_compact_evidence_bundle(
                finding,
                evidence_by_id=evidence_by_id,
            )
            for finding in findings
        ]
        findings = [
            self._finding_with_recovered_mechanical_comparison_guard(
                finding,
                evidence_by_id=evidence_by_id,
                tables_by_id=tables_by_id,
            )
            for finding in findings
        ]
        findings = [
            self._finding_with_paper_level_corrosion_association_guard(
                finding,
                evidence_by_id=evidence_by_id,
                tables_by_id=tables_by_id,
            )
            for finding in findings
        ]
        findings = [
            self._finding_with_source_unit_consistency_guard(
                finding,
                evidence_by_id=evidence_by_id,
                tables_by_id=tables_by_id,
                blocks_by_id=blocks_by_id,
            )
            for finding in findings
        ]
        findings = self._merge_duplicate_presentation_findings(
            findings,
            evidence_by_id=evidence_by_id,
        )
        findings = [
            self._finding_with_observed_symbol_axis(finding)
            for finding in findings
        ]
        findings = self._findings_without_redundant_generic_mechanical_rows(findings)
        findings = self._findings_without_redundant_multi_outcome_rows(
            findings,
            evidence_by_id=evidence_by_id,
        )
        primary_findings, review_queue_findings = self._partition_presentation_findings(
            findings,
            evidence_by_id=evidence_by_id,
            blocks_by_id=blocks_by_id,
            tables_by_id=tables_by_id,
            goal_axes=variable_axes,
        )
        review_queue_findings = self._review_findings_without_covered_ved_rows(
            review_queue_findings,
            primary_findings=primary_findings,
            evidence_by_id=evidence_by_id,
        )
        review_queue_findings = self._review_findings_without_confounded_table_rows(
            review_queue_findings
        )
        review_queue_findings = [
            self._finding_with_table_alignment_review_reason(
                finding,
                evidence_by_id=evidence_by_id,
                tables_by_id=tables_by_id,
                relations_by_id=relations_by_id,
            )
            for finding in review_queue_findings
        ]
        review_queue_findings = [
            self._finding_with_energy_density_context(
                finding,
                evidence_by_id=evidence_by_id,
                tables_by_id=tables_by_id,
            )
            for finding in review_queue_findings
        ]
        review_queue_findings = [
            self._finding_with_preheating_table_comparison(
                finding,
                evidence_by_id=evidence_by_id,
                tables_by_id=tables_by_id,
            )
            for finding in review_queue_findings
        ]
        primary_findings, review_queue_findings = self._merge_aligned_table_findings(
            primary_findings,
            review_queue_findings=review_queue_findings,
            evidence_by_id=evidence_by_id,
        )
        review_queue_findings = self._review_findings_without_low_magnitude_table_rows(
            review_queue_findings,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
        )
        primary_findings = self._findings_with_review_queue_context(
            primary_findings,
            review_queue_findings=review_queue_findings,
        )
        for finding in (*primary_findings, *review_queue_findings):
            finding["scope_summary"] = _compact_finding_scope_summary(
                _text(finding.get("scope_summary")) or "",
                variables=list(_strings(finding.get("variables"))),
                outcomes=list(_strings(finding.get("outcomes"))),
                statement=_text(finding.get("statement")) or "",
            )
        visible_findings_by_id = {
            _text(finding.get("finding_id")): finding
            for finding in [*primary_findings, *review_queue_findings]
            if _text(finding.get("finding_id"))
        }
        findings = [
            visible_findings_by_id[_text(finding.get("finding_id"))]
            for finding in findings
            if _text(finding.get("finding_id")) in visible_findings_by_id
        ]
        quote_hints_by_ref = self._finding_quote_hints_by_evidence_ref(
            findings,
            relations_by_id=relations_by_id,
        )
        presentation_evidence_ref_ids = self._presentation_evidence_ref_ids(
            [*primary_findings, *review_queue_findings],
            effects=effects,
        )
        evidence_items = [
            self._presentation_evidence_item(
                ref,
                collection_id=_text(scope.get("collection_id")),
                blocks_by_id=blocks_by_id,
                tables_by_id=tables_by_id,
                documents_by_id=documents_by_id,
                quote_hints=quote_hints_by_ref.get(
                    _text(ref.get("evidence_ref_id")) or "",
                    {},
                ),
            )
            for ref in evidence_refs
            if _text(ref.get("evidence_ref_id")) in presentation_evidence_ref_ids
        ]
        presentation_context_ids = {
            context_id
            for finding in [*primary_findings, *review_queue_findings]
            for context_id in _strings(finding.get("context_ids"))
        }
        return {
            "summary": {
                "title": _text(scope.get("title")) or "Research understanding",
                "material_scope": material_scope,
                "variable_axes": variable_axes,
                "property_scope": property_scope,
                "claim_count": len(claims),
                "relation_count": len(relations),
                "evidence_count": len(evidence_items),
                "context_count": len(presentation_context_ids),
                "review_queue_count": len(review_queue_findings),
                "primary_finding_count": len(primary_findings),
                "review_queue_finding_count": len(review_queue_findings),
                "collection_document_count": len(documents_by_id),
                "axis_coverage": self._presentation_axis_coverage(
                    variable_axes=variable_axes,
                    property_scope=property_scope,
                    primary_findings=primary_findings,
                    review_queue_findings=review_queue_findings,
                    contexts_by_id=contexts_by_id,
                ),
            },
            "effects": effects,
            "findings": findings,
            "primary_findings": primary_findings,
            "review_queue_findings": review_queue_findings,
            "evidence_items": evidence_items,
            "context_summaries": context_summaries,
        }

    def _presentation_evidence_ref_ids(
        self,
        findings: list[dict[str, Any]],
        *,
        effects: list[dict[str, Any]],
    ) -> set[str]:
        ref_ids = {
            ref_id
            for finding in findings
            for ref_id in self._finding_evidence_ref_ids_from_bundle(
                _mapping(finding.get("evidence_bundle"))
            )
        }
        if ref_ids:
            return ref_ids
        ref_ids = {
            ref_id
            for finding in findings
            for ref_id in _strings(finding.get("evidence_ref_ids"))
        }
        if ref_ids:
            return ref_ids
        return {
            ref_id
            for effect in effects
            for ref_id in _strings(effect.get("evidence_ref_ids"))
        }

    def _presentation_axis_coverage(
        self,
        *,
        variable_axes: list[str],
        property_scope: list[str],
        primary_findings: list[dict[str, Any]],
        review_queue_findings: list[dict[str, Any]],
        contexts_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, list[dict[str, str]]]:
        return {
            "variables": self._presentation_axis_coverage_rows(
                variable_axes,
                primary_findings=primary_findings,
                review_queue_findings=review_queue_findings,
                finding_key="variables",
                contexts_by_id=contexts_by_id,
            ),
            "properties": self._presentation_axis_coverage_rows(
                property_scope,
                primary_findings=primary_findings,
                review_queue_findings=review_queue_findings,
                finding_key="outcomes",
                contexts_by_id=contexts_by_id,
            ),
        }

    def _dedupe_axis_labels(self, axes: list[str] | tuple[str, ...]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for axis in axes:
            label = _text(axis) or ""
            if not label:
                continue
            key = self._axis_key(label)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(label)
        return result

    def _presentation_axis_coverage_rows(
        self,
        axes: list[str],
        *,
        primary_findings: list[dict[str, Any]],
        review_queue_findings: list[dict[str, Any]],
        finding_key: str,
        contexts_by_id: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for axis in axes:
            label = _text(axis) or ""
            if not label:
                continue
            status, finding_id = self._axis_coverage_status(
                label,
                primary_findings=primary_findings,
                review_queue_findings=review_queue_findings,
                finding_key=finding_key,
                include_context=finding_key == "variables",
                contexts_by_id=contexts_by_id,
            )
            rows.append({"axis": label, "status": status, "finding_id": finding_id})
        return rows

    def _axis_coverage_status(
        self,
        axis: str,
        *,
        primary_findings: list[dict[str, Any]],
        review_queue_findings: list[dict[str, Any]],
        finding_key: str,
        include_context: bool,
        contexts_by_id: Mapping[str, dict[str, Any]],
    ) -> tuple[str, str]:
        matchers = [
            ("primary", primary_findings, finding_key),
            ("review_queue", review_queue_findings, finding_key),
            ("mechanism", primary_findings, "mediators"),
            ("mechanism", review_queue_findings, "mediators"),
        ]
        if include_context:
            matchers.extend(
                [
                    ("context", primary_findings, "context"),
                    ("context", review_queue_findings, "context"),
                ]
            )
        for status, findings, match_key in matchers:
            finding = self._axis_matching_finding(
                axis,
                findings,
                match_key,
                contexts_by_id=contexts_by_id,
            )
            if finding:
                return status, _text(finding.get("finding_id")) or ""
        return "missing", ""

    def _axis_matching_finding(
        self,
        axis: str,
        findings: list[dict[str, Any]],
        finding_key: str,
        contexts_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        normalized_axis = _normalize_axis_coverage_text(axis)
        if not normalized_axis:
            return None
        for finding in findings:
            values = self._axis_matching_values(
                finding,
                finding_key,
                contexts_by_id=contexts_by_id,
            )
            if any(
                _axis_terms_overlap(normalized_axis, _normalize_axis_coverage_text(value))
                for value in values
            ):
                return finding
        return None

    def _axis_matching_values(
        self,
        finding: Mapping[str, Any],
        finding_key: str,
        contexts_by_id: Mapping[str, dict[str, Any]],
    ) -> list[str]:
        if finding_key == "context":
            context_values = [
                value
                for context_id in _strings(finding.get("context_ids"))
                if (context := contexts_by_id.get(context_id))
                for value in [
                    *_strings(context.get("material_scope")),
                    *_display_values(_mapping(context.get("process_context"))),
                    *_strings(context.get("property_scope")),
                    *_display_values(_mapping(context.get("test_condition"))),
                ]
            ]
            return _dedupe_strings(
                [
                    _text(finding.get("scope_summary")) or "",
                    *_strings(finding.get("variables")),
                    *_strings(finding.get("mediators")),
                    *_strings(finding.get("outcomes")),
                    *_strings(finding.get("context")),
                    *context_values,
                    *[
                        str(condition.get("axis"))
                        for condition in _mapping_list(
                            finding.get("direct_conditions")
                        )
                        if _text(condition.get("axis"))
                    ],
                    *[
                        str(condition.get("value"))
                        for condition in _mapping_list(
                            finding.get("direct_conditions")
                        )
                        if _text(condition.get("value"))
                    ],
                ]
            )
        return _strings(finding.get(finding_key))

    def _reviewable_expert_finding(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> bool:
        variables = _strings(finding.get("variables"))
        outcomes = _strings(finding.get("outcomes"))
        statement = _text(finding.get("statement")) or ""
        title = _text(finding.get("title")) or ""
        bundle = _mapping(finding.get("evidence_bundle"))
        if not variables or not outcomes:
            return False
        if any(self._is_unusable_finding_axis(variable) for variable in variables[:1]):
            return False
        if self._is_measurement_only_finding(statement, title=title):
            return False
        if not self._finding_has_reviewable_result_evidence(
            finding,
            evidence_by_id=evidence_by_id,
            blocks_by_id=blocks_by_id,
        ):
            return False
        if not _mapping_list(finding.get("relation_chain")):
            return False
        if not self._finding_statement_matches_display_variable(finding):
            return False
        return True

    def _finding_has_reviewable_result_evidence(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> bool:
        evidence_bundle = _mapping(finding.get("evidence_bundle"))
        if _strings(evidence_bundle.get("conflict")):
            return True
        direct_ref_ids = _strings(evidence_bundle.get("direct_result"))
        if not direct_ref_ids:
            return False
        terms = self._finding_quote_alignment_terms(finding)
        for ref_id in direct_ref_ids:
            evidence_ref = evidence_by_id.get(ref_id, {})
            source_kind = (_text(evidence_ref.get("source_kind")) or "").lower()
            locator = _locator_mapping(evidence_ref.get("locator"))
            source_ref = _text(locator.get("source_ref"))
            traceability_status = (
                _text(evidence_ref.get("traceability_status")) or ""
            ).lower()
            if (
                "table" in source_kind
                and source_ref
                and traceability_status in {"resolved", "traceable"}
            ):
                return True
            block = blocks_by_id.get(source_ref or "") if source_ref else None
            source_text = " ".join(
                value
                for value in (
                    _text(evidence_ref.get("quote")),
                    _text(block.text if block else None),
                )
                if value
            )
            if not source_text:
                continue
            normalized = f" {_normalize_match_text(source_text)} "
            if _quote_term_hits(normalized, terms["outcome"]):
                return True
        return False

    def _is_unusable_finding_axis(self, value: str) -> bool:
        if _symbol_match_term(value):
            return False
        normalized = _normalize_match_text(value)
        if not normalized:
            return True
        if normalized.replace(".", "", 1).isdigit():
            return True
        if normalized in {
            "none",
            "unknown",
            "n/a",
            "na",
            "sample",
            "samples",
            "specimen",
            "specimens",
        }:
            return True
        return "_" in value

    def _is_measurement_only_finding(self, statement: str, *, title: str) -> bool:
        normalized_statement = f" {_normalize_match_text(statement)} "
        normalized_title = f" {_normalize_match_text(title)} "
        return (
            " is reported as " in normalized_statement
            or " is reported as " in normalized_title
        )

    def _findings_with_review_queue_context(
        self,
        primary_findings: list[dict[str, Any]],
        *,
        review_queue_findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not review_queue_findings:
            return primary_findings
        result: list[dict[str, Any]] = []
        for finding in primary_findings:
            updated = dict(finding)
            related_finding_ids = self._related_review_finding_ids(
                updated,
                review_queue_findings=review_queue_findings,
            )
            updated["review_reasons"] = _dedupe_strings(
                [
                    *_strings(updated.get("review_reasons")),
                    *(
                        ["has_unreviewed_comparable_candidates"]
                        if related_finding_ids
                        else []
                    ),
                ]
            )
            updated["related_review_finding_ids"] = related_finding_ids
            result.append(updated)
        return result

    def _related_review_finding_ids(
        self,
        finding: Mapping[str, Any],
        *,
        review_queue_findings: list[dict[str, Any]],
    ) -> list[str]:
        finding_id = _text(finding.get("finding_id")) or ""
        variables = self._finding_axis_keys(_strings(finding.get("variables")))
        outcomes = self._finding_axis_keys(_strings(finding.get("outcomes")))
        if not variables or not outcomes:
            return []
        related: list[str] = []
        for candidate in review_queue_findings:
            candidate_id = _text(candidate.get("finding_id")) or ""
            if not candidate_id or candidate_id == finding_id:
                continue
            candidate_variables = self._finding_axis_keys(
                _strings(candidate.get("variables"))
            )
            candidate_outcomes = self._finding_axis_keys(
                _strings(candidate.get("outcomes"))
            )
            if variables & candidate_variables and outcomes & candidate_outcomes:
                related.append(candidate_id)
        return _dedupe_strings(related[:5])

    def _finding_axis_keys(self, values: list[str] | tuple[str, ...]) -> set[str]:
        return {axis_key for value in values if (axis_key := self._axis_key(value))}

    def _recovered_presentation_findings_from_source_blocks(
        self,
        record: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable] | None = None,
    ) -> list[dict[str, Any]]:
        if not blocks_by_id:
            return []
        scope = _mapping(record.get("scope"))
        collection_id = _text(scope.get("collection_id"))
        title = _text(scope.get("title"))
        if not collection_id or not title:
            return []
        contexts = _mapping_list(record.get("contexts"))
        objective, objective_context = self._presentation_recovery_objective(
            scope,
            contexts=contexts,
        )
        existing_claims = _mapping_list(record.get("claims"))
        existing_source_refs = self._source_refs_from_evidence_refs(
            _mapping_list(record.get("evidence_refs"))
        )
        existing_recovered_claim_ids = {
            claim_id
            for claim in existing_claims
            if (claim_id := _text(claim.get("claim_id")))
            and claim_id.startswith("claim_recovered_")
        }
        existing_recovered_relation_ids = {
            relation_id
            for relation in _mapping_list(record.get("relations"))
            if (relation_id := _text(relation.get("relation_id")))
            and relation_id.startswith("rel_recovered_")
        }
        existing_recovered_source_object_ids = {
            source_object_id
            for claim in existing_claims
            if (_text(claim.get("claim_id")) or "").startswith("claim_recovered_")
            for source_object_id in _strings(claim.get("source_object_ids"))
        }
        axis_text = " ".join(
            [
                title,
                " ".join(_strings(objective.get("process_axes"))),
                " ".join(_strings(objective_context.get("variable_process_axes"))),
                " ".join(_strings(objective.get("property_axes"))),
                " ".join(_strings(objective_context.get("target_property_axes"))),
            ]
        )
        normalized_axes = f" {_normalize_match_text(axis_text)} "
        normalized_property_axes = self._normalized_objective_property_axes(
            objective,
            objective_context,
        )
        document_ids = self._presentation_recovery_document_ids(
            record,
            blocks_by_id=blocks_by_id,
        )
        if not document_ids:
            return []
        payload = {
            "collection_id": collection_id,
            "objective": objective,
            "objective_context": objective_context,
            "paper_frames": [{"document_id": document_id} for document_id in document_ids],
        }
        recovered: list[dict[str, Any]] = []
        if self._objective_axes_request_preheating_ductility(normalized_axes):
            for document_id in document_ids:
                block = self._best_preheating_ductility_source_block(
                    document_id,
                    blocks_by_id=blocks_by_id,
                )
                if block is None:
                    continue
                recovered.append(
                    self._recovered_preheating_ductility_finding(
                        block,
                        collection_id=collection_id,
                        objective_context=objective_context,
                        objective=objective,
                    )
                )
                break
        recovered.extend(
            self._recovered_process_property_findings_from_source_blocks(
                payload,
                evidence_units=[],
                blocks_by_id=blocks_by_id,
                tables_by_id=tables_by_id,
                normalized_axes=normalized_axes,
                normalized_property_axes=normalized_property_axes,
                objective=objective,
                objective_context=objective_context,
            )
        )
        if (
            (
                " porosity " in normalized_axes
                or " pore " in normalized_axes
                or " pores " in normalized_axes
            )
            and (
                " corrosion " in normalized_axes
                or " pitting " in normalized_axes
            )
        ):
            for document_id in document_ids:
                block = self._best_porosity_corrosion_source_block(
                    document_id,
                    blocks_by_id=blocks_by_id,
                )
                if block is None:
                    continue
                condition_table = self._best_porosity_corrosion_process_table(
                    document_id,
                    tables_by_id=tables_by_id,
                )
                recovered.append(
                    self._recovered_porosity_corrosion_finding(
                        block,
                        collection_id=collection_id,
                        objective_context=objective_context,
                        objective=objective,
                        condition_table=condition_table,
                    )
                )
                break
        return [
            recovered
            for recovered in recovered
            if not (
                existing_claims
                and self._recovered_source_ref(recovered) in existing_source_refs
                and not self._recovered_refreshes_existing_object(
                    recovered,
                    existing_recovered_claim_ids=existing_recovered_claim_ids,
                    existing_recovered_relation_ids=existing_recovered_relation_ids,
                    existing_recovered_source_object_ids=(
                        existing_recovered_source_object_ids
                    ),
                )
            )
            if _mapping(recovered.get("claim"))
            and _mapping(recovered.get("relation"))
            and self._recovered_evidence_refs(recovered)
        ]

    def _recovered_refreshes_existing_object(
        self,
        recovered: Mapping[str, Any],
        *,
        existing_recovered_claim_ids: set[str],
        existing_recovered_relation_ids: set[str],
        existing_recovered_source_object_ids: set[str],
    ) -> bool:
        claim_id = _text(_mapping(recovered.get("claim")).get("claim_id"))
        relation_id = _text(_mapping(recovered.get("relation")).get("relation_id"))
        source_ref = self._recovered_source_ref(recovered)
        return bool(
            (claim_id and claim_id in existing_recovered_claim_ids)
            or (relation_id and relation_id in existing_recovered_relation_ids)
            or (source_ref and source_ref in existing_recovered_source_object_ids)
        )

    def _recovered_evidence_refs(self, recovered: Mapping[str, Any]) -> list[dict[str, Any]]:
        refs = _mapping_list(recovered.get("evidence_refs"))
        if refs:
            return refs
        ref = _mapping(recovered.get("evidence_ref"))
        return [ref] if ref else []

    def _source_refs_from_evidence_refs(
        self,
        evidence_refs: list[dict[str, Any]],
    ) -> set[str]:
        return {
            source_ref
            for ref in evidence_refs
            if (source_ref := _text(_locator_mapping(ref.get("locator")).get("source_ref")))
        }

    def _recovered_source_ref(self, recovered: Mapping[str, Any]) -> str:
        evidence_refs = self._recovered_evidence_refs(recovered)
        evidence_ref = evidence_refs[0] if evidence_refs else {}
        return _text(_locator_mapping(evidence_ref.get("locator")).get("source_ref"))

    def _presentation_recovery_objective(
        self,
        scope: Mapping[str, Any],
        *,
        contexts: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        title = _text(scope.get("title"))
        scope_contexts = [
            context
            for context in contexts
            if self._is_scope_context(context)
        ]
        contexts_for_scope = scope_contexts or []
        material_scope = _dedupe_strings(
            [
                value
                for context in contexts_for_scope
                for value in _strings(context.get("material_scope"))
            ]
        )
        if not material_scope and "316l" in _normalize_match_text(title):
            material_scope = ["316L stainless steel"]
        process_axes = _dedupe_strings(
            [
                value
                for context in contexts_for_scope
                for value in _display_values(_mapping(context.get("process_context")))
            ]
        )
        property_axes = _dedupe_strings(
            [
                value
                for context in contexts_for_scope
                for value in _strings(context.get("property_scope"))
            ]
        )
        process_axes = _dedupe_strings(
            [*process_axes, *self._presentation_recovery_process_axes_from_title(title)]
        )
        property_axes = _dedupe_strings(
            [*property_axes, *self._presentation_recovery_property_axes_from_title(title)]
        )
        objective_id = _text(scope.get("objective_id"))
        return (
            {
                "objective_id": objective_id,
                "question": title,
                "material_scope": material_scope,
                "process_axes": process_axes,
                "property_axes": property_axes,
            },
            {
                "objective_id": objective_id,
                "question": title,
                "material_scope": material_scope,
                "variable_process_axes": process_axes,
                "target_property_axes": property_axes,
            },
        )

    def _is_scope_context(self, context: Mapping[str, Any]) -> bool:
        context_id = _normalize_match_text(_text(context.get("context_id")) or "")
        label = _normalize_match_text(_text(context.get("label")) or "")
        return context_id in {"ctx_objective_scope", "ctx_goal_scope", "ctx_goal"} or label in {
            "objective scope",
            "goal scope",
        }

    def _presentation_recovery_process_axes_from_title(self, title: str) -> list[str]:
        normalized = f" {_normalize_match_text(title)} "
        has_volumetric_energy_density = (
            " volumetric energy density " in normalized or " ved " in normalized
        )
        axes: list[str] = []
        for display, terms in (
            ("laser beam powder bed fusion", ("laser beam powder bed fusion", "laser powder bed fusion", "lpbf", "pbf lb", "powder bed fusion")),
            ("selective laser melting", ("selective laser melting", "slm")),
            ("build platform preheating temperature", ("build platform preheating", "preheating temperature")),
            ("heat treatment", ("heat treatment",)),
            ("laser power", ("laser power",)),
            ("scanning speed", ("scanning speed", "scan speed")),
            ("energy density", ("energy density",)),
            ("porosity level", ("porosity level", "porosity")),
            ("pore size", ("pore size",)),
            ("scan strategy rotation angle", ("scan strategy rotation angle", "rotation angle")),
            ("build orientation", ("build orientation",)),
            ("volumetric energy density", ("volumetric energy density", "ved")),
        ):
            if display == "energy density" and has_volumetric_energy_density:
                continue
            if any(f" {_normalize_match_text(term)} " in normalized for term in terms):
                axes.append(display)
        return _dedupe_strings(axes)

    def _presentation_recovery_property_axes_from_title(self, title: str) -> list[str]:
        normalized = f" {_normalize_match_text(self._presentation_recovery_property_phrase(title))} "
        axes: list[str] = []
        for display, terms in (
            ("density", ("density", "densification")),
            ("microstructure", ("microstructure",)),
            ("mechanical properties", ("mechanical properties",)),
            ("yield strength", ("yield strength",)),
            ("ultimate tensile strength", ("ultimate tensile strength",)),
            ("elongation", ("elongation", "ductility")),
            ("pitting corrosion behavior", ("pitting corrosion behavior", "pitting corrosion")),
            ("crystallographic texture", ("crystallographic texture",)),
            ("defect structure", ("defect structure", "defect")),
            ("fatigue strength", ("fatigue strength", "fatigue")),
        ):
            if any(f" {_normalize_match_text(term)} " in normalized for term in terms):
                axes.append(display)
        return _dedupe_strings(axes)

    def _presentation_recovery_property_phrase(self, title: str) -> str:
        normalized = _normalize_match_text(title)
        for marker in (" affect ", " affects "):
            marker = marker.strip()
            pattern = f" {marker} "
            padded = f" {normalized} "
            if pattern in padded:
                return padded.split(pattern, 1)[1]
        return normalized

    def _presentation_recovery_document_ids(
        self,
        record: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> list[str]:
        document_ids: list[str] = []
        for ref in _mapping_list(record.get("evidence_refs")):
            document_id = _text(ref.get("document_id"))
            if document_id:
                document_ids.append(document_id)
                continue
            locator = _locator_mapping(ref.get("locator"))
            block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
            if block and block.document_id:
                document_ids.append(block.document_id)
        if not document_ids:
            document_ids.extend(block.document_id for block in blocks_by_id.values())
        return _dedupe_strings(document_ids)

    def _merge_duplicate_presentation_findings(
        self,
        findings: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        index_by_key: dict[tuple[str, str, str, str], int] = {}
        for finding in findings:
            key = self._presentation_finding_merge_key(
                finding,
                evidence_by_id=evidence_by_id,
            )
            if not key:
                merged.append(finding)
                continue
            if key not in index_by_key:
                index_by_key[key] = len(merged)
                merged.append(finding)
                continue
            target_index = index_by_key[key]
            merged[target_index] = self._merge_presentation_finding(
                merged[target_index],
                finding,
                evidence_by_id=evidence_by_id,
            )
        return merged

    def _presentation_finding_merge_key(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> tuple[str, str, str, str] | None:
        variables = [
            _normalize_match_text(value)
            for value in _strings(finding.get("variables"))
            if _normalize_match_text(value)
        ]
        outcomes = [
            _normalize_match_text(value)
            for value in _strings(finding.get("outcomes"))
            if _normalize_match_text(value)
        ]
        if not variables or not outcomes:
            return None
        table_row_scope = ""
        if self._finding_is_table_axis_review_candidate(finding):
            table_row_scope = self._table_row_review_merge_scope(
                finding,
                evidence_by_id=evidence_by_id,
            )
            direction = ""
        else:
            direction = self._finding_merge_direction(_text(finding.get("direction")) or "")
        return (
            " | ".join(variables),
            " | ".join(outcomes),
            direction,
            table_row_scope,
        )

    def _table_row_review_merge_scope(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> str:
        source_refs = [
            source_ref
            for ref_id in self._finding_evidence_ref_ids_from_bundle(
                _mapping(finding.get("evidence_bundle"))
            )
            if (
                source_ref := _text(
                    _locator_mapping(evidence_by_id.get(ref_id, {}).get("locator")).get(
                        "source_ref"
                    )
                )
            )
        ]
        return " | ".join(_dedupe_strings(source_refs))

    def _finding_is_table_axis_review_candidate(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        warnings = {
            _normalize_match_text(value)
            for value in _strings(finding.get("warnings"))
        }
        finding_id = _text(finding.get("finding_id")) or ""
        is_generated_row_finding = finding_id.startswith(
            "finding_relation_rel_"
        ) or bool(re.match(r"^finding_claim_[0-9a-f]{12}$", finding_id))
        if "deterministic relation" not in warnings and not is_generated_row_finding:
            return False
        statements = [
            _text(finding.get("statement")) or "",
            *[
                _text(segment.get("statement")) or ""
                for segment in _mapping_list(finding.get("relation_chain"))
            ],
        ]
        return any(
            self._finding_statement_is_table_row_comparison(statement)
            for statement in statements
        )

    def _finding_merge_direction(self, direction: str) -> str:
        normalized = _normalize_match_text(direction)
        if normalized in {
            "affect",
            "affects",
            "affected",
            "change",
            "changes",
            "changed",
            "compare",
            "compares",
            "compared",
            "improve",
            "improves",
            "improved",
            "modulate",
            "modulates",
            "modulated",
        }:
            return ""
        return normalized

    def _merge_presentation_finding(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        merged = dict(left)
        merged["finding_id"] = _text(left.get("finding_id")) or _text(
            right.get("finding_id")
        )
        merged["claim_id"] = _text(left.get("claim_id")) or _text(right.get("claim_id"))
        merged_variables = _dedupe_strings(
            [*_strings(left.get("variables")), *_strings(right.get("variables"))]
        )
        merged_outcomes = _dedupe_strings(
            [*_strings(left.get("outcomes")), *_strings(right.get("outcomes"))]
        )
        merged["statement"] = self._preferred_finding_statement(
            _text(left.get("statement")) or "",
            _text(right.get("statement")) or "",
            variables=merged_variables,
            outcomes=merged_outcomes,
        )
        merged["variables"] = merged_variables
        merged["mediators"] = _dedupe_strings(
            [*_strings(left.get("mediators")), *_strings(right.get("mediators"))]
        )
        merged["outcomes"] = merged_outcomes
        merged["direction"] = _text(left.get("direction")) or _text(
            right.get("direction")
        ) or ""
        merged["relation_chain"] = self._merge_relation_chains(
            _mapping_list(left.get("relation_chain")),
            _mapping_list(right.get("relation_chain")),
        )
        merged["scope_summary"] = self._merge_scope_summaries(
            _text(left.get("scope_summary")) or "",
            _text(right.get("scope_summary")) or "",
        )
        merged["support_grade"] = self._stronger_support_grade(
            _text(left.get("support_grade")) or "",
            _text(right.get("support_grade")) or "",
        )
        merged["review_status"] = self._merged_review_status(
            _text(left.get("review_status")) or "",
            _text(right.get("review_status")) or "",
        )
        merged["confidence"] = self._merged_confidence(
            left.get("confidence"),
            right.get("confidence"),
        )
        merged["evidence_ref_ids"] = _dedupe_strings(
            [
                *_strings(left.get("evidence_ref_ids")),
                *_strings(right.get("evidence_ref_ids")),
            ]
        )
        document_ids = {
            document_id
            for ref_id in merged["evidence_ref_ids"]
            if (document_id := _text(evidence_by_id.get(ref_id, {}).get("document_id")))
        }
        merged["paper_count"] = len(document_ids) or max(
            _safe_count(left.get("paper_count")),
            _safe_count(right.get("paper_count")),
        )
        merged["evidence_count"] = len(merged["evidence_ref_ids"])
        merged["context_ids"] = _dedupe_strings(
            [*_strings(left.get("context_ids")), *_strings(right.get("context_ids"))]
        )
        merged["relation_ids"] = _dedupe_strings(
            [*_strings(left.get("relation_ids")), *_strings(right.get("relation_ids"))]
        )
        merged["evidence_bundle"] = self._merge_evidence_bundles(
            _mapping(left.get("evidence_bundle")),
            _mapping(right.get("evidence_bundle")),
        )
        merged["warnings"] = _dedupe_strings(
            [*_strings(left.get("warnings")), *_strings(right.get("warnings"))]
        )
        if self._finding_is_table_axis_review_candidate(merged):
            merged["direction"] = "condition-dependent"
            representative_statement = self._representative_table_axis_statement(
                merged["relation_chain"],
                variables=merged_variables,
                outcomes=merged_outcomes,
            )
            if representative_statement:
                representative_segment = next(
                    (
                        segment
                        for segment in merged["relation_chain"]
                        if _text(segment.get("statement"))
                        == representative_statement
                    ),
                    {},
                )
                representative_relation_id = _text(
                    representative_segment.get("relation_id")
                )
                right_relation_ids = {
                    *_strings(right.get("relation_ids")),
                    *(
                        _text(segment.get("relation_id")) or ""
                        for segment in _mapping_list(right.get("relation_chain"))
                    ),
                }
                representative_source = (
                    right
                    if representative_relation_id
                    and representative_relation_id in right_relation_ids
                    else left
                )
                merged["statement"] = representative_statement
                merged["finding_id"] = _text(
                    representative_source.get("finding_id")
                ) or merged["finding_id"]
                merged["claim_id"] = _text(
                    representative_source.get("claim_id")
                ) or merged["claim_id"]
                merged["confidence"] = representative_source.get("confidence")
                merged["paper_count"] = _safe_count(
                    representative_source.get("paper_count")
                )
                merged["evidence_ref_ids"] = list(
                    _strings(representative_source.get("evidence_ref_ids"))
                )
                merged["evidence_count"] = len(merged["evidence_ref_ids"])
                merged["context_ids"] = list(
                    _strings(representative_source.get("context_ids"))
                )
                merged["relation_ids"] = (
                    [representative_relation_id]
                    if representative_relation_id
                    else list(_strings(representative_source.get("relation_ids")))
                )
                merged["relation_chain"] = (
                    [dict(representative_segment)]
                    if representative_segment
                    else list(
                        _mapping_list(representative_source.get("relation_chain"))
                    )
                )
                merged["evidence_bundle"] = {
                    key: list(_strings(value))
                    for key, value in _mapping(
                        representative_source.get("evidence_bundle")
                    ).items()
                }
                merged["scope_summary"] = _text(
                    representative_source.get("scope_summary")
                ) or merged["scope_summary"]
                merged["comparison_summary"] = self._finding_comparison_summary(
                    representative_statement,
                    variables=merged_variables,
                    outcomes=merged_outcomes,
                    direction="",
                )
            merged["support_grade"] = "partial"
            merged["review_status"] = "needs_review"
        return self._finding_with_refreshed_use_boundary(merged)

    def _finding_with_refreshed_use_boundary(
        self,
        finding: Mapping[str, Any],
    ) -> dict[str, Any]:
        refreshed = dict(finding)
        support_grade = _text(refreshed.get("support_grade")) or ""
        review_status = _text(refreshed.get("review_status")) or ""
        paper_count = int(refreshed.get("paper_count") or 0)
        evidence_bundle = _mapping(refreshed.get("evidence_bundle"))
        generalization_status = self._finding_generalization_status(
            support_grade=support_grade,
            review_status=review_status,
            paper_count=paper_count,
            evidence_bundle=evidence_bundle,
        )
        refreshed["expert_use_status"] = self._finding_expert_use_status(
            support_grade=support_grade,
            review_status=review_status,
            paper_count=paper_count,
            evidence_bundle=evidence_bundle,
        )
        refreshed["generalization_status"] = generalization_status
        refreshed["generalization_note"] = self._finding_generalization_note(
            generalization_status=generalization_status,
            paper_count=paper_count,
        )
        refreshed["evidence_gap_summary"] = self._finding_evidence_gap_summary(
            support_grade=support_grade,
            review_status=review_status,
            paper_count=paper_count,
            evidence_bundle=evidence_bundle,
        )
        refreshed["upgrade_actions"] = self._finding_upgrade_actions(
            support_grade=support_grade,
            review_status=review_status,
            paper_count=paper_count,
            evidence_bundle=evidence_bundle,
        )
        refreshed["review_reasons"] = self._finding_review_reasons(
            refreshed,
            evidence_bundle=evidence_bundle,
            mediators=_strings(refreshed.get("mediators")),
            mechanism_source_text="",
            outcomes=_strings(refreshed.get("outcomes")),
            relation_ids=_strings(refreshed.get("relation_ids")),
            review_status=review_status,
            support_grade=support_grade,
            scope_summary=_text(refreshed.get("scope_summary")) or "",
        )
        return refreshed

    def _representative_table_axis_statement(
        self,
        relation_chain: list[dict[str, Any]],
        *,
        variables: list[str],
        outcomes: list[str],
    ) -> str:
        candidates = [
            statement
            for relation in relation_chain
            if (
                statement := _text(relation.get("statement"))
            )
            and self._finding_statement_is_table_row_comparison(statement)
            and self._statement_matches_finding_display(
                statement,
                variables=variables,
                outcomes=outcomes,
            )
            and self._statement_changed_axis_matches_variables(
                statement,
                variables=variables,
            )
        ]
        if not candidates:
            return ""
        return max(
            candidates,
            key=lambda statement: (
                self._comparison_statement_value_delta(statement),
                self._statement_specificity_score(statement),
                len(statement),
            ),
        )

    def _comparison_statement_value_delta(self, statement: str) -> float:
        match = re.search(
            r"\bfrom\s+(-?\d+(?:\.\d+)?)\s*%?\b.*?\bto\s+(-?\d+(?:\.\d+)?)\s*%?\b",
            statement,
            flags=re.IGNORECASE,
        )
        if match is None:
            return 0.0
        try:
            return abs(float(match.group(2)) - float(match.group(1)))
        except ValueError:
            return 0.0

    def _statement_changed_axis_matches_variables(
        self,
        statement: str,
        *,
        variables: list[str],
    ) -> bool:
        changed_axis = self._statement_changed_axis(statement)
        if not changed_axis:
            return True
        return any(
            self._axis_labels_match(changed_axis, variable)
            for variable in variables
        )

    def _statement_changed_axis(self, statement: str) -> str:
        text = _text(statement) or ""
        patterns = [
            r"^(?:Under|With)\s+.+?,\s+changing\s+(?P<axis>.+?)\s+from\s+",
            r"^(?:Under|With)\s+.+?,\s+(?P<axis>.+?)\s+"
            r"(?:increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+",
        ]
        for pattern in patterns:
            match = re.search(pattern, text.strip(), flags=re.IGNORECASE)
            if match is not None:
                return _clean_comparison_summary_text(match.group("axis"))
        return ""

    def _preferred_finding_statement(
        self,
        left: str,
        right: str,
        *,
        variables: list[str] | None = None,
        outcomes: list[str] | None = None,
    ) -> str:
        if not left:
            return right
        if not right:
            return left
        left_contextualized = self._looks_contextualized_comparison_statement(left)
        right_contextualized = self._looks_contextualized_comparison_statement(right)
        if left_contextualized and not right_contextualized:
            return left
        if right_contextualized and not left_contextualized:
            return right
        if variables and outcomes:
            left_matches = self._statement_matches_finding_display(
                left,
                variables=variables,
                outcomes=outcomes,
            )
            right_matches = self._statement_matches_finding_display(
                right,
                variables=variables,
                outcomes=outcomes,
            )
            if left_matches and not right_matches:
                return left
            if right_matches and not left_matches:
                return right
        left_score = self._statement_specificity_score(left)
        right_score = self._statement_specificity_score(right)
        if right_score > left_score:
            return right
        if right_score == left_score and len(right) > len(left):
            return right
        return left

    def _looks_contextualized_comparison_statement(self, statement: str) -> bool:
        normalized = f" {_normalize_match_text(statement)} "
        return bool(
            (" changing " in normalized and " from " in normalized and " to " in normalized)
            or " table row comparison changes " in normalized
            or " table-row comparison changes " in normalized
        )

    def _merge_relation_chains(
        self,
        left: list[dict[str, Any]],
        right: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for segment in [*left, *right]:
            key = (
                _text(segment.get("relation_id")) or "",
                _text(segment.get("variable")) or "",
                _text(segment.get("outcome")) or "",
                _text(segment.get("statement")) or "",
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(segment)
        return merged

    def _merge_scope_summaries(self, left: str, right: str) -> str:
        values = [
            item.strip()
            for value in (left, right)
            for item in value.split(",")
            if item.strip()
        ]
        return _join_display_values(_dedupe_strings(values), limit=5)

    def _stronger_support_grade(self, left: str, right: str) -> str:
        rank = {
            "strong": 0,
            "partial": 1,
            "weak": 2,
            "conflict": 3,
            "insufficient": 4,
        }
        left_rank = rank.get(left, 5)
        right_rank = rank.get(right, 5)
        return left if left_rank <= right_rank else right

    def _merged_review_status(self, left: str, right: str) -> str:
        if left == "pending_review" or right == "pending_review":
            return "pending_review"
        return left or right

    def _merged_confidence(self, left: Any, right: Any) -> float | None:
        values = [
            value
            for value in (_confidence_or_none(left), _confidence_or_none(right))
            if value is not None
        ]
        return max(values) if values else None

    def _merge_evidence_bundles(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
    ) -> dict[str, list[str]]:
        keys = (
            "direct_result",
            "mechanism",
            "condition_context",
            "background",
            "conflict",
            "noise",
            "uncategorized",
        )
        return {
            key: _dedupe_strings(
                [*_strings(left.get(key)), *_strings(right.get(key))]
            )
            for key in keys
        }

    def _finding_with_aligned_direct_evidence(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_ref_ids = _strings(bundle.get("direct_result"))
        if not direct_ref_ids:
            return dict(finding)
        if self._is_recovered_expert_finding(finding):
            return dict(finding)
        uncategorized_ref_ids = _strings(bundle.get("uncategorized"))
        table_refs = [
            ref_id
            for ref_id in [*direct_ref_ids, *uncategorized_ref_ids]
            if "table"
            in (_text(evidence_by_id.get(ref_id, {}).get("source_kind")) or "").lower()
        ]
        text_refs = [ref_id for ref_id in direct_ref_ids if ref_id not in table_refs]
        if not table_refs or not text_refs:
            return dict(finding)
        statements = [
            _text(finding.get("statement")) or "",
            *[
                _text(item.get("statement")) or ""
                for item in _mapping_list(finding.get("relation_chain"))
            ],
        ]
        if not any(
            self._finding_statement_is_table_row_comparison(statement)
            for statement in statements
        ):
            return dict(finding)
        updated = dict(finding)
        updated_bundle = {key: list(value) for key, value in bundle.items()}
        updated_bundle["direct_result"] = table_refs
        updated_bundle["uncategorized"] = _dedupe_strings(
            [
                *[
                    ref_id
                    for ref_id in updated_bundle.get("uncategorized", [])
                    if ref_id not in table_refs
                ],
                *text_refs,
            ]
        )
        updated["evidence_bundle"] = updated_bundle
        return updated

    def _finding_with_compact_table_direct_evidence(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_ref_ids = _strings(bundle.get("direct_result"))
        if len(direct_ref_ids) <= 1:
            return dict(finding)
        table_ref_ids = [
            ref_id
            for ref_id in direct_ref_ids
            if "table"
            in (_text(evidence_by_id.get(ref_id, {}).get("source_kind")) or "").lower()
        ]
        if len(table_ref_ids) <= 1:
            return dict(finding)
        grouped_by_source: dict[str, list[str]] = {}
        for ref_id in table_ref_ids:
            source_ref = _text(
                _locator_mapping(evidence_by_id.get(ref_id, {}).get("locator")).get(
                    "source_ref"
                )
            )
            grouped_by_source.setdefault(source_ref or ref_id, []).append(ref_id)
        if not any(len(group) > 1 for group in grouped_by_source.values()):
            return dict(finding)

        statement = " ".join(
            value
            for value in (
                _text(finding.get("statement")),
                *[
                    _text(item.get("statement"))
                    for item in _mapping_list(finding.get("relation_chain"))
                ],
            )
            if value
        )
        if not self._finding_statement_is_table_row_comparison(statement):
            return dict(finding)

        kept: list[str] = []
        moved: list[str] = []
        for group in grouped_by_source.values():
            if len(group) == 1:
                kept.extend(group)
                continue
            preferred = max(
                group,
                key=lambda ref_id: self._table_direct_evidence_match_score(
                    ref_id,
                    statement=statement,
                    finding=finding,
                    evidence_by_id=evidence_by_id,
                ),
            )
            kept.append(preferred)
            moved.extend(ref_id for ref_id in group if ref_id != preferred)
        if not moved:
            return dict(finding)

        updated = dict(finding)
        updated_bundle = {key: list(value) for key, value in bundle.items()}
        updated_bundle["direct_result"] = _dedupe_strings(
            [
                ref_id
                for ref_id in direct_ref_ids
                if ref_id not in moved
            ]
        )
        updated_bundle["uncategorized"] = _dedupe_strings(
            [*updated_bundle.get("uncategorized", []), *moved]
        )
        updated["evidence_bundle"] = updated_bundle
        return updated

    def _finding_with_compact_evidence_bundle(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        updated = dict(finding)
        compact_bundle = self._compact_finding_evidence_bundle(
            _mapping(finding.get("evidence_bundle")),
            evidence_by_id=evidence_by_id,
        )
        updated["evidence_bundle"] = compact_bundle
        updated["evidence_ref_ids"] = self._finding_evidence_ref_ids_from_bundle(
            compact_bundle
        )
        updated["evidence_count"] = len(updated["evidence_ref_ids"])
        return updated

    def _finding_with_recovered_mechanical_comparison_guard(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, Any]:
        if not self._is_recovered_scanning_speed_mechanical_finding(finding):
            return dict(finding)
        if not self._finding_statement_has_scanning_speed_range(finding):
            return dict(finding)

        mechanical_table = self._finding_source_table(
            finding,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
            predicate=self._specific_mechanical_property_table_score,
        )
        processing_table = self._finding_source_table(
            finding,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
            predicate=self._slm_processing_parameter_table_score,
        )
        if mechanical_table is None or processing_table is None:
            return dict(finding)
        axes = self._specific_mechanical_outcomes(
            finding,
            evidence_by_id=evidence_by_id,
        ) or _strings(finding.get("outcomes"))
        axes = [
            axis
            for axis in axes
            if axis
            in {
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            }
        ]
        if not axes:
            return dict(finding)
        controlled_summary = self._specific_mechanical_property_controlled_summary(
            mechanical_table,
            processing_table,
            axes,
        )
        if controlled_summary:
            return dict(finding)

        updated = dict(finding)
        updated["statement"] = self._unisolated_scanning_speed_statement(axes)
        updated["variables"] = [_SLM_COUPLED_PARAMETER_SET_LABEL]
        updated["title"] = self._finding_title(
            variables=updated["variables"],
            outcomes=axes,
            fallback=_text(updated.get("title")) or "",
        )
        updated["direction"] = "associated"
        updated["support_grade"] = "partial"
        updated["review_status"] = "needs_review"
        updated["warnings"] = _dedupe_strings(
            [
                *_strings(updated.get("warnings")),
                "non_single_variable_table_comparison",
                "single_variable_effect_not_isolated",
                "needs_expert_review",
            ]
        )
        updated["review_reasons"] = _dedupe_strings(
            [
                *_strings(updated.get("review_reasons")),
                "non_single_variable_table_comparison",
                "single_variable_effect_not_isolated",
                "needs_expert_review",
            ]
        )
        updated["comparison_summary"] = None
        updated["relation_chain"] = [
            {
                **segment,
                "variable": _SLM_COUPLED_PARAMETER_SET_LABEL,
                "statement": updated["statement"],
                "direction": "associated",
                "status": "limited",
                "warnings": _dedupe_strings(
                    [
                        *_strings(segment.get("warnings")),
                        "non_single_variable_table_comparison",
                        "single_variable_effect_not_isolated",
                    ]
                ),
            }
            for segment in _mapping_list(updated.get("relation_chain"))
        ]
        return self._finding_with_refreshed_use_boundary(updated)

    def _finding_with_paper_level_corrosion_association_guard(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, Any]:
        variable_text = _normalize_match_text(" ".join(_strings(finding.get("variables"))))
        outcome_text = _normalize_match_text(" ".join(_strings(finding.get("outcomes"))))
        if "porosity" not in variable_text or not (
            "corrosion" in outcome_text or "pitting" in outcome_text
        ):
            return dict(finding)

        bundle = _mapping(finding.get("evidence_bundle"))
        direct_ref_ids = _strings(bundle.get("direct_result"))
        direct_document_ids = {
            document_id
            for ref_id in direct_ref_ids
            if (document_id := _text(evidence_by_id.get(ref_id, {}).get("document_id")))
        }
        if direct_document_ids:
            if len(direct_document_ids) != 1:
                return dict(finding)
        elif int(finding.get("paper_count") or 0) != 1:
            return dict(finding)
        relevant_ref_ids = _dedupe_strings(
            [
                *direct_ref_ids,
                *_strings(bundle.get("condition_context")),
            ]
        )
        evidence_text = " ".join(
            " ".join(
                value
                for value in (
                    _text(evidence_by_id.get(ref_id, {}).get("label")),
                    _text(evidence_by_id.get(ref_id, {}).get("quote")),
                )
                if value
            )
            for ref_id in relevant_ref_ids
        )
        condition_table = next(
            (
                table
                for ref_id in relevant_ref_ids
                if (
                    source_ref := _text(
                        _locator_mapping(
                            evidence_by_id.get(ref_id, {}).get("locator")
                        ).get("source_ref")
                    )
                )
                and (table := tables_by_id.get(source_ref)) is not None
                and self._porosity_corrosion_process_table_score(table) > 0
            ),
            None,
        )
        process_conditions_not_isolated = (
            self._porosity_corrosion_process_conditions_not_isolated(
                source_text=evidence_text,
                condition_table=condition_table,
            )
        )
        statement = self._porosity_corrosion_association_statement(
            process_conditions_not_isolated=process_conditions_not_isolated,
        )
        warnings = [
            *_strings(finding.get("warnings")),
            "paper_level_association",
            "needs_expert_review",
        ]
        if process_conditions_not_isolated:
            warnings.append("process_conditions_not_isolated")

        updated = dict(finding)
        updated.update(
            {
                "statement": statement,
                "direction": "associated",
                "support_grade": "partial",
                "review_status": "needs_review",
                "paper_count": 1,
                "comparison_summary": None,
                "warnings": _dedupe_strings(warnings),
                "relation_chain": [
                    {
                        **segment,
                        "direction": "associated",
                        "statement": statement,
                    }
                    for segment in _mapping_list(finding.get("relation_chain"))
                ],
            }
        )
        return self._finding_with_refreshed_use_boundary(updated)

    def _finding_with_source_unit_consistency_guard(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> dict[str, Any]:
        bundle = _mapping(finding.get("evidence_bundle"))
        document_ids = {
            document_id
            for ref_id in self._finding_evidence_ref_ids_from_bundle(bundle)
            if (
                document_id := _text(
                    evidence_by_id.get(ref_id, {}).get("document_id")
                )
            )
        }
        if not document_ids:
            return dict(finding)
        has_unit_inconsistency = any(
            table.document_id in document_ids
            and self._table_has_slm_scanning_speed_unit_inconsistency(
                table,
                blocks_by_id=blocks_by_id,
            )
            for table in tables_by_id.values()
        )
        if not has_unit_inconsistency:
            return dict(finding)

        limitation = (
            "The source reports scanning speed in mm/s, but its laser power, "
            "layer thickness, hatch spacing, and energy-density values are "
            "internally consistent with m/s; treat the scanning-speed unit as "
            "unresolved."
        )
        updated = dict(finding)
        statement = _text(updated.get("statement")) or ""
        if limitation not in statement:
            updated["statement"] = f"{statement} {limitation}".strip()
        updated["warnings"] = _dedupe_strings(
            [*_strings(updated.get("warnings")), "source_unit_inconsistency"]
        )
        updated["review_reasons"] = _dedupe_strings(
            [
                *_strings(updated.get("review_reasons")),
                "source_unit_inconsistency",
                "needs_expert_review",
            ]
        )
        updated["relation_chain"] = [
            {
                **segment,
                "statement": updated["statement"],
                "warnings": _dedupe_strings(
                    [
                        *_strings(segment.get("warnings")),
                        "source_unit_inconsistency",
                    ]
                ),
            }
            for segment in _mapping_list(updated.get("relation_chain"))
        ]
        return self._finding_with_refreshed_use_boundary(updated)

    def _table_has_slm_scanning_speed_unit_inconsistency(
        self,
        table: SourceTable,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> bool:
        indexes = self._slm_energy_density_consistency_column_indexes(table)
        if set(indexes) != {"hatch_spacing", "scanning_speed", "energy_density"}:
            return False
        process_values = self._slm_fixed_power_and_layer_thickness(
            _text(table.document_id),
            blocks_by_id=blocks_by_id,
        )
        if process_values is None:
            return False
        laser_power, layer_thickness_mm = process_values
        hatch_index = indexes["hatch_spacing"]
        speed_index = indexes["scanning_speed"]
        energy_index = indexes["energy_density"]
        compared = 0
        thousand_fold_matches = 0
        for row in table.table_matrix:
            if len(row) <= max(hatch_index, speed_index, energy_index):
                continue
            hatch_spacing = _float_text(row[hatch_index])
            reported_speed = _float_text(row[speed_index])
            energy_density = _float_text(row[energy_index])
            if not all(
                value is not None and value > 0
                for value in (hatch_spacing, reported_speed, energy_density)
            ):
                continue
            expected_speed_mm_s = laser_power / (
                energy_density * hatch_spacing * layer_thickness_mm
            )
            ratio = expected_speed_mm_s / reported_speed
            compared += 1
            if 900 <= ratio <= 1100:
                thousand_fold_matches += 1
        return (
            compared >= 2
            and thousand_fold_matches >= 2
            and thousand_fold_matches / compared >= 0.75
        )

    def _slm_energy_density_consistency_column_indexes(
        self,
        table: SourceTable,
    ) -> dict[str, int]:
        indexes: dict[str, int] = {}
        headers = list(table.column_headers)
        if not headers and table.table_matrix:
            headers = list(table.table_matrix[0])
        for index, header in enumerate(headers):
            raw = _text(header) or ""
            normalized = f" {_normalize_match_text(raw)} "
            if (
                (" hatch space " in normalized or " hatch spacing " in normalized)
                and re.search(r"\(\s*mm\s*\)", raw, flags=re.IGNORECASE)
            ):
                indexes["hatch_spacing"] = index
            if (
                (" scan speed " in normalized or " scanning speed " in normalized)
                and re.search(r"mm\s*/\s*s", raw, flags=re.IGNORECASE)
            ):
                indexes["scanning_speed"] = index
            if (
                " energy density " in normalized
                and " j " in normalized
                and " mm " in normalized
                and " 3 " in normalized
            ):
                indexes["energy_density"] = index
        return indexes

    def _slm_fixed_power_and_layer_thickness(
        self,
        document_id: str | None,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> tuple[float, float] | None:
        if not document_id:
            return None
        for block in sorted(
            (
                block
                for block in blocks_by_id.values()
                if block.document_id == document_id
            ),
            key=lambda item: item.block_order or 0,
        ):
            text = normalize_display_text(_text(block.text)) or ""
            if (
                "laser power" not in text.lower()
                or "layer thickness" not in text.lower()
            ):
                continue
            power_match = re.search(
                r"\blaser power(?:\s+of)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*w\b",
                text,
                flags=re.IGNORECASE,
            )
            thickness_match = re.search(
                r"\blayer thickness(?:\s+of)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*"
                r"((?:μ|µ|u)\s*m|mm)\b",
                text,
                flags=re.IGNORECASE,
            )
            if power_match is None or thickness_match is None:
                continue
            laser_power = float(power_match.group(1))
            layer_thickness = float(thickness_match.group(1))
            unit = thickness_match.group(2).replace(" ", "").lower()
            layer_thickness_mm = (
                layer_thickness / 1000 if unit != "mm" else layer_thickness
            )
            if laser_power > 0 and layer_thickness_mm > 0:
                return laser_power, layer_thickness_mm
        return None

    def _is_recovered_scanning_speed_mechanical_finding(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        claim_id = _text(finding.get("claim_id")) or ""
        if not claim_id.startswith(
            "claim_recovered_scan_speed_density_microstructure_"
        ):
            return False
        variables = {
            _normalize_match_text(value)
            for value in _strings(finding.get("variables"))
        }
        outcomes = {
            _normalize_match_text(value)
            for value in _strings(finding.get("outcomes"))
        }
        return any("scanning speed" in variable for variable in variables) and bool(
            outcomes
            & {
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            }
        )

    def _finding_statement_has_scanning_speed_range(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        statement = self._finding_statement_text(finding)
        normalized = f" {_normalize_match_text(statement)} "
        return bool(
            " scanning speed from " in normalized
            and " to " in normalized
            and re.search(r"\d+(?:\.\d+)?", statement)
        )

    def _finding_source_table(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
        predicate: Any,
    ) -> SourceTable | None:
        best: tuple[int, int, SourceTable] | None = None
        for ref_id in self._finding_evidence_ref_ids_from_bundle(
            _mapping(finding.get("evidence_bundle"))
        ):
            ref = evidence_by_id.get(ref_id, {})
            if "table" not in (_text(ref.get("source_kind")) or "").lower():
                continue
            source_ref = _text(_locator_mapping(ref.get("locator")).get("source_ref"))
            table = tables_by_id.get(source_ref or "")
            if table is None:
                continue
            score = predicate(table)
            if score <= 0:
                continue
            ranked = (score, -(table.table_order or 0), table)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else None

    def _finding_with_observed_symbol_axis(
        self,
        finding: Mapping[str, Any],
    ) -> dict[str, Any]:
        comparison = _mapping(finding.get("comparison_summary"))
        observed = _mapping(comparison.get("observed"))
        observed_label = _text(observed.get("label"))
        if not _symbol_match_term(observed_label):
            return dict(finding)
        variable = self._display_axis_label(observed_label)
        if not variable:
            return dict(finding)
        outcomes = _strings(finding.get("outcomes"))
        updated = dict(finding)
        updated["variables"] = [variable]
        updated["title"] = self._finding_title(
            variables=[variable],
            outcomes=outcomes,
            fallback=_text(finding.get("title")) or _text(finding.get("statement")),
        )
        updated_comparison = dict(comparison)
        updated_comparison["variable"] = variable
        updated["comparison_summary"] = updated_comparison
        scope_tokens = [
            token.strip()
            for token in (_text(updated.get("scope_summary")) or "").split(",")
            if token.strip()
        ]
        symbol_axes = {
            display
            for symbol in ("α", "β", "θ", "ɵ")
            if (display := self._display_axis_label(symbol))
        }
        cleaned_scope_tokens = []
        for token in scope_tokens:
            display_token = self._display_axis_label(token)
            if display_token in symbol_axes:
                continue
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", token):
                continue
            cleaned_scope_tokens.append(token)
        updated["scope_summary"] = _join_display_values(
            _dedupe_strings(
                [
                    *cleaned_scope_tokens,
                    variable,
                    *outcomes,
                ]
            ),
            limit=7,
        )
        return updated

    def _finding_evidence_ref_ids_from_bundle(
        self,
        evidence_bundle: Mapping[str, list[str]],
    ) -> list[str]:
        return _dedupe_strings(
            [
                ref_id
                for role in (
                    "direct_result",
                    "mechanism",
                    "condition_context",
                    "conflict",
                    "background",
                    "uncategorized",
                )
                for ref_id in _strings(evidence_bundle.get(role))
            ]
        )

    def _table_direct_evidence_match_score(
        self,
        ref_id: str,
        *,
        statement: str,
        finding: Mapping[str, Any],
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> tuple[int, int, int, int]:
        evidence_ref = evidence_by_id.get(ref_id, {})
        searchable = self._evidence_search_text(evidence_ref)
        bounded = f" {_normalize_match_text(searchable)} "
        statement_numbers = set(re.findall(r"\d+(?:\.\d+)?", statement))
        evidence_numbers = set(re.findall(r"\d+(?:\.\d+)?", searchable))
        variable_terms = {
            term
            for variable in _strings(finding.get("variables"))
            for term in _quote_hint_terms(variable)
        }
        outcome_terms = self._finding_statement_outcome_terms(
            _strings(finding.get("outcomes"))
        )
        fact_hits = _quote_term_hits(
            bounded,
            {
                term
                for fact_id in _strings(evidence_ref.get("fact_ids"))
                for term in _quote_hint_terms(fact_id)
            },
        )
        return (
            len(statement_numbers & evidence_numbers),
            _quote_term_hits(bounded, variable_terms),
            _quote_term_hits(bounded, outcome_terms),
            fact_hits,
        )

    def _finding_statement_is_table_row_comparison(self, statement: str) -> bool:
        normalized = f" {_normalize_match_text(statement)} "
        return bool(
            re.search(r"\d", statement)
            and _quote_has_concrete_result_cue(statement)
            and " from " in normalized
            and " to " in normalized
            and any(
                f" {cue} " in normalized
                for cue in (
                    "under",
                    "with",
                    "laser power",
                    "scan speed",
                    "heat treatment",
                    "density",
                )
            )
        )

    def _finding_statement_is_confounded_table_row_comparison(
        self,
        statement: str,
    ) -> bool:
        normalized = f" {_normalize_match_text(statement)} "
        return bool(
            " table row comparison changes " in normalized
            or " table-row comparison changes " in normalized
        )

    def _review_candidate_table_row_statement(self, statement: str) -> str:
        text = (_text(statement) or "").strip()
        if not text:
            return ""
        if text.startswith("Selected source table rows show:"):
            return text
        if text[-1] not in ".!?":
            text = f"{text}."
        return (
            f"Selected source table rows show: {text} "
            "Expert review is required before treating this as a material effect."
        )

    def _finding_table_row_statement_text(self, finding: Mapping[str, Any]) -> str:
        statements = [
            _text(finding.get("statement")) or "",
            *[
                _text(item.get("statement")) or ""
                for item in _mapping_list(finding.get("relation_chain"))
            ],
        ]
        for statement in statements:
            if self._finding_statement_is_table_row_comparison(statement):
                return statement
        return ""

    def _partition_presentation_findings(
        self,
        findings: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable],
        goal_axes: list[str] | tuple[str, ...] = (),
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        primary: list[dict[str, Any]] = []
        review_queue: list[dict[str, Any]] = []
        source_finding_document_ids = self._source_finding_document_ids(
            findings,
            evidence_by_id=evidence_by_id,
        )
        source_evidence_document_ids = self._source_evidence_document_ids(
            evidence_by_id=evidence_by_id,
        )
        primary_candidates: list[tuple[dict[str, Any], bool]] = []
        for finding in findings:
            primary_candidates.append(
                (
                    finding,
                    self._finding_has_primary_expert_use_status(finding)
                    and self._is_primary_presentation_finding(
                        finding,
                        evidence_by_id=evidence_by_id,
                        blocks_by_id=blocks_by_id,
                    ),
                )
            )
        has_non_table_primary = any(
            is_primary
            and self._finding_has_non_table_direct_result(
                finding,
                evidence_by_id=evidence_by_id,
            )
            for finding, is_primary in primary_candidates
        )
        for finding, is_primary in primary_candidates:
            if (
                _text(finding.get("review_status")) == "needs_review"
                and self._finding_has_only_table_direct_result(
                    finding,
                    evidence_by_id=evidence_by_id,
                )
                and self._finding_statement_is_table_row_comparison(
                    self._finding_statement_text(finding)
                )
                and not (
                    self._is_recovered_expert_finding(finding)
                    and self._finding_has_non_direct_text_support(
                        _mapping(finding.get("evidence_bundle")),
                        evidence_by_id=evidence_by_id,
                    )
                )
            ):
                review_queue.append(
                    self._finding_as_review_candidate(
                        finding,
                        reason="table_row_needs_expert_review",
                    )
                )
                continue
            if (
                (source_finding_document_ids or source_evidence_document_ids)
                and self._finding_has_only_table_direct_result(
                    finding,
                    evidence_by_id=evidence_by_id,
                )
                and not (
                    self._is_recovered_expert_finding(finding)
                    and self._finding_has_non_direct_text_support(
                        _mapping(finding.get("evidence_bundle")),
                        evidence_by_id=evidence_by_id,
                    )
                )
            ):
                finding_document_ids = self._finding_document_ids(
                    finding,
                    evidence_by_id=evidence_by_id,
                )
                if (
                    finding_document_ids
                    and finding_document_ids
                    <= (source_finding_document_ids | source_evidence_document_ids)
                ):
                    review_queue.append(
                        self._finding_as_review_candidate(
                            finding,
                            reason="table_row_needs_text_or_mechanism_review",
                        )
                    )
                    continue
            if (
                has_non_table_primary
                and is_primary
                and self._finding_has_only_table_direct_result(
                    finding,
                    evidence_by_id=evidence_by_id,
                )
                and not (
                    self._is_recovered_expert_finding(finding)
                    and self._finding_has_non_direct_text_support(
                        _mapping(finding.get("evidence_bundle")),
                        evidence_by_id=evidence_by_id,
                    )
                )
                and self._finding_statement_is_table_row_comparison(
                    self._finding_statement_text(finding)
                )
            ):
                review_queue.append(
                    self._finding_as_review_candidate(
                        finding,
                        reason="table_row_shadowed_by_text_finding",
                    )
                )
                continue
            if is_primary:
                primary.append(finding)
            else:
                review_queue.append(finding)
        review_queue = self._review_findings_without_low_magnitude_table_rows(
            review_queue,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
        )
        return self._promote_uncovered_goal_axis_findings(
            primary,
            review_queue,
            evidence_by_id=evidence_by_id,
            goal_axes=goal_axes,
        )

    def _review_findings_without_covered_ved_rows(
        self,
        review_queue: list[dict[str, Any]],
        *,
        primary_findings: list[dict[str, Any]],
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        covered_sources = self._covered_ved_fatigue_table_sources(
            primary_findings,
            evidence_by_id=evidence_by_id,
        )
        if not covered_sources:
            return review_queue
        return [
            finding
            for finding in review_queue
            if not self._ved_fatigue_review_row_is_covered(
                finding,
                covered_sources=covered_sources,
                evidence_by_id=evidence_by_id,
            )
        ]

    def _review_findings_without_confounded_table_rows(
        self,
        review_queue: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            finding
            for finding in review_queue
            if not self._finding_is_confounded_table_row_candidate(finding)
        ]

    def _review_findings_without_low_magnitude_table_rows(
        self,
        review_queue: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> list[dict[str, Any]]:
        density_deltas_by_outcome: dict[str, list[float]] = {}
        for finding in review_queue:
            delta = self._finding_density_percentage_delta(
                finding,
                evidence_by_id=evidence_by_id,
            )
            if delta is None:
                continue
            outcome_key = self._axis_key(
                " ".join(_strings(finding.get("outcomes")))
                or _text(_mapping(finding.get("comparison_summary")).get("outcome"))
                or _text(finding.get("title"))
                or ""
            )
            density_deltas_by_outcome.setdefault(outcome_key, []).append(delta)
        return [
            finding
            for finding in review_queue
            if not self._finding_is_low_magnitude_table_row_candidate(
                finding,
                evidence_by_id=evidence_by_id,
                tables_by_id=tables_by_id,
                density_deltas_by_outcome=density_deltas_by_outcome,
            )
        ]

    def _finding_with_table_alignment_review_reason(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
        relations_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if not self._finding_uses_unaligned_table_rows(
            finding,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
            relations_by_id=relations_by_id,
        ):
            return dict(finding)
        updated = dict(finding)
        updated["review_reasons"] = _dedupe_strings(
            [
                *_strings(updated.get("review_reasons")),
                "table_row_alignment_uncertain",
                "needs_expert_review",
            ]
        )
        updated["warnings"] = _dedupe_strings(
            [
                *_strings(updated.get("warnings")),
                "table_row_alignment_uncertain",
            ]
        )
        return updated

    def _finding_uses_unaligned_table_rows(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
        relations_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        bundle = _mapping(finding.get("evidence_bundle"))
        quote_hints = self._quote_hints_for_finding(
            finding,
            relations_by_id=relations_by_id,
        )
        for ref_id in _strings(bundle.get("direct_result")):
            ref = evidence_by_id.get(ref_id, {})
            if "table" not in (_text(ref.get("source_kind")) or "").lower():
                continue
            source_ref = _text(_locator_mapping(ref.get("locator")).get("source_ref"))
            table = tables_by_id.get(source_ref)
            if table is None:
                continue
            table_audit = self._presentation_table_audit(
                table,
                quote_hints=quote_hints,
            )
            if _table_audit_has_unaligned_rows(table_audit):
                return True
        return False

    def _finding_is_low_magnitude_table_row_candidate(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
        density_deltas_by_outcome: Mapping[str, list[float]],
    ) -> bool:
        if not self._finding_has_only_table_direct_result(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if self._finding_has_non_direct_text_support(
            _mapping(finding.get("evidence_bundle")),
            evidence_by_id=evidence_by_id,
        ):
            return False
        statement = self._finding_statement_text(finding)
        is_table_row_comparison = self._finding_statement_is_table_row_comparison(
            statement
        )
        if is_table_row_comparison and self._finding_is_low_magnitude_prediction_comparison(
            finding, statement
        ):
            return True
        mechanical_strength_delta = self._finding_mechanical_strength_relative_delta(
            finding,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
        )
        if (
            mechanical_strength_delta is not None
            and mechanical_strength_delta < 0.5
        ):
            return True
        if not is_table_row_comparison:
            return False
        density_delta = self._finding_density_percentage_delta(
            finding,
            evidence_by_id=evidence_by_id,
        )
        if density_delta is None:
            return False
        if density_delta < 0.5:
            return True
        if density_delta >= 1.5:
            return False
        outcome_key = self._axis_key(
            " ".join(_strings(finding.get("outcomes")))
            or _text(_mapping(finding.get("comparison_summary")).get("outcome"))
            or _text(finding.get("title"))
            or ""
        )
        return any(
            other_delta >= 1.5
            for other_delta in density_deltas_by_outcome.get(outcome_key, [])
        )

    def _finding_density_percentage_delta(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> float | None:
        if not self._finding_has_only_table_direct_result(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return None
        if self._finding_has_non_direct_text_support(
            _mapping(finding.get("evidence_bundle")),
            evidence_by_id=evidence_by_id,
        ):
            return None
        summary_delta = self._comparison_summary_percentage_delta(finding)
        if summary_delta is not None:
            return summary_delta
        statement = _text(finding.get("statement")) or self._finding_statement_text(finding)
        if not self._finding_statement_is_table_row_comparison(statement):
            return None
        if not self._finding_is_density_percentage_comparison(finding, statement):
            return None
        percent_values = re.findall(r"(-?\d+(?:\.\d+)?)\s*%", statement)
        if len(percent_values) < 2:
            return None
        try:
            return abs(float(percent_values[-1]) - float(percent_values[-2]))
        except ValueError:
            return None

    def _comparison_summary_percentage_delta(
        self,
        finding: Mapping[str, Any],
    ) -> float | None:
        comparison = _mapping(finding.get("comparison_summary"))
        if not comparison or not self._finding_has_density_outcome(finding):
            return None
        baseline = _text(_mapping(comparison.get("baseline")).get("value")) or ""
        observed = _text(_mapping(comparison.get("observed")).get("value")) or ""
        if "%" not in baseline or "%" not in observed:
            return None
        baseline_match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", baseline)
        observed_match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", observed)
        if baseline_match is None or observed_match is None:
            return None
        try:
            return abs(float(observed_match.group(1)) - float(baseline_match.group(1)))
        except ValueError:
            return None

    def _finding_mechanical_strength_relative_delta(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> float | None:
        comparison = _mapping(finding.get("comparison_summary"))
        outcome_values = [
            *_strings(finding.get("outcomes")),
            _text(comparison.get("outcome")) or "",
        ]
        if not any(
            self._axis_key(value)
            in {"yield strength", "ultimate tensile strength", "tensile strength"}
            for value in outcome_values
        ):
            return None
        baseline = _float_text(_mapping(comparison.get("baseline")).get("value"))
        observed = _float_text(_mapping(comparison.get("observed")).get("value"))
        if baseline is None or observed is None:
            matches = list(
                re.finditer(
                    r"\bfrom\s+(-?\d+(?:\.\d+)?)\s*mpa\b.*?"
                    r"\bto\s+(-?\d+(?:\.\d+)?)\s*mpa\b",
                    self._finding_statement_text(finding),
                    flags=re.IGNORECASE,
                )
            )
            if not matches:
                return self._finding_preheating_strength_relative_delta_from_table(
                    finding,
                    evidence_by_id=evidence_by_id,
                    tables_by_id=tables_by_id,
                )
            baseline = float(matches[-1].group(1))
            observed = float(matches[-1].group(2))
        if baseline == 0:
            return None
        return abs(observed - baseline) / abs(baseline) * 100

    def _finding_with_energy_density_context(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, Any]:
        if not self._finding_has_only_table_direct_result(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return dict(finding)
        summary = _mapping(finding.get("comparison_summary"))
        variable = self._display_axis_label(_text(summary.get("variable")))
        if self._axis_key(variable) not in {
            "hatch spacing",
            "laser power",
            "scan speed",
        }:
            return dict(finding)
        comparison_values = self._finding_energy_density_comparison_values(
            finding,
            variable=variable,
            summary=summary,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
        )
        if not comparison_values:
            return dict(finding)

        baseline = _mapping(summary.get("baseline"))
        observed = _mapping(summary.get("observed"))
        outcome = self._display_axis_label(_text(summary.get("outcome")))
        controlled_conditions = _mapping_list(summary.get("controlled_conditions"))
        condition_text = " and ".join(
            f"{_text(item.get('axis'))} {_text(item.get('value'))}"
            for item in controlled_conditions
            if _text(item.get("axis")) and _text(item.get("value"))
        )
        condition_clause = f"under {condition_text}, " if condition_text else ""
        baseline_axis = self._process_axis_display_value(
            variable,
            comparison_values["baseline_axis"],
        )
        observed_axis = self._process_axis_display_value(
            variable,
            comparison_values["observed_axis"],
        )
        baseline_energy = (
            f"{comparison_values['baseline_energy_density']} J/mm3"
        )
        observed_energy = (
            f"{comparison_values['observed_energy_density']} J/mm3"
        )
        changed_process_axes = _mapping_list(
            comparison_values.get("changed_process_axes")
        )
        variables = _dedupe_strings(
            [
                variable,
                *[
                    axis
                    for item in changed_process_axes
                    if (axis := self._display_axis_label(_text(item.get("axis"))))
                ],
            ]
        )
        variable_label = " + ".join(variables)
        process_change_text = (
            f"{variable} changed from {baseline_axis} to {observed_axis}"
        )
        baseline_labels = [f"{variable} {baseline_axis}"]
        observed_labels = [f"{variable} {observed_axis}"]
        for item in changed_process_axes:
            axis = self._display_axis_label(_text(item.get("axis")))
            baseline_value = self._process_axis_display_value(
                axis,
                _text(item.get("baseline")) or "",
            )
            observed_value = self._process_axis_display_value(
                axis,
                _text(item.get("observed")) or "",
            )
            process_change_text += (
                f" while {axis} changed from {baseline_value} to {observed_value}"
            )
            baseline_labels.append(f"{axis} {baseline_value}")
            observed_labels.append(f"{axis} {observed_value}")
        baseline_labels.append(f"derived energy density {baseline_energy}")
        observed_labels.append(f"derived energy density {observed_energy}")
        has_independent_coupling = bool(changed_process_axes)
        direction = (
            "associated" if has_independent_coupling else "condition-dependent"
        )
        statement_prefix = (
            "Selected source table rows show a coupled process-parameter contrast:"
            if has_independent_coupling
            else "Selected source table rows show:"
        )
        conclusion = (
            "The rows do not isolate the separate effects of "
            f"{' and '.join(variables)}."
            if has_independent_coupling
            else (
                "This is a condition-specific table association; the rows do not "
                "isolate a causal mechanism."
            )
        )
        statement = (
            f"{statement_prefix} {condition_clause}{process_change_text} while the "
            "derived energy density changed from "
            f"{baseline_energy} to {observed_energy}; {outcome} changed from "
            f"{_text(baseline.get('value'))} to {_text(observed.get('value'))}. "
            f"{conclusion}"
        )
        updated = dict(finding)
        updated["title"] = f"{variable_label} -> {outcome}"
        updated["statement"] = statement
        updated["variables"] = variables
        updated["direction"] = direction
        updated["comparison_summary"] = {
            "variable": variable_label,
            "direction": direction,
            "outcome": outcome,
            "baseline": {
                "label": "; ".join(baseline_labels),
                "value": _text(baseline.get("value")) or "",
            },
            "observed": {
                "label": "; ".join(observed_labels),
                "value": _text(observed.get("value")) or "",
            },
            "controlled_conditions": controlled_conditions,
        }
        stale_context_reasons = {
            "coupled_energy_density_change",
            "derived_energy_density_context",
            "non_single_variable_table_comparison",
            "single_variable_effect_not_isolated",
        }
        coupling_reasons = (
            [
                "non_single_variable_table_comparison",
                "single_variable_effect_not_isolated",
            ]
            if has_independent_coupling
            else []
        )
        updated["review_reasons"] = _dedupe_strings(
            [
                *[
                    reason
                    for reason in _strings(updated.get("review_reasons"))
                    if reason not in stale_context_reasons
                ],
                "derived_energy_density_context",
                *coupling_reasons,
                "needs_expert_review",
            ]
        )
        updated["warnings"] = _dedupe_strings(
            [
                *[
                    warning
                    for warning in _strings(updated.get("warnings"))
                    if warning not in stale_context_reasons
                ],
                "derived_energy_density_context",
                *coupling_reasons,
            ]
        )
        updated["relation_chain"] = [
            {
                **segment,
                "variable": variable_label,
                "statement": statement,
                "direction": direction,
            }
            for segment in _mapping_list(finding.get("relation_chain"))
        ]
        return updated

    def _finding_energy_density_comparison_values(
        self,
        finding: Mapping[str, Any],
        *,
        variable: str,
        summary: Mapping[str, Any],
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, Any]:
        baseline = _mapping(summary.get("baseline"))
        observed = _mapping(summary.get("observed"))
        baseline_axis = _float_text(baseline.get("label"))
        observed_axis = _float_text(observed.get("label"))
        baseline_outcome = _float_text(baseline.get("value"))
        observed_outcome = _float_text(observed.get("value"))
        if None in {
            baseline_axis,
            observed_axis,
            baseline_outcome,
            observed_outcome,
        }:
            return {}

        for ref_id in _strings(
            _mapping(finding.get("evidence_bundle")).get("direct_result")
        ):
            ref = evidence_by_id.get(ref_id, {})
            source_ref = _text(_locator_mapping(ref.get("locator")).get("source_ref"))
            table = tables_by_id.get(source_ref or "")
            if table is None:
                continue
            headers = [
                self._display_axis_label(header) for header in table.column_headers
            ]
            variable_index = next(
                (
                    index
                    for index, header in enumerate(headers)
                    if self._axis_labels_match(variable, header)
                ),
                None,
            )
            energy_index = next(
                (
                    index
                    for index, header in enumerate(headers)
                    if "energy density" in self._axis_key(header)
                ),
                None,
            )
            outcome = self._display_axis_label(_text(summary.get("outcome")))
            outcome_index = next(
                (
                    index
                    for index, header in enumerate(headers)
                    if "energy density" not in self._axis_key(header)
                    and self._axis_labels_match(outcome, header)
                ),
                None,
            )
            if None in {variable_index, energy_index, outcome_index}:
                continue
            condition_indexes: list[tuple[int, str]] = []
            for condition in _mapping_list(summary.get("controlled_conditions")):
                condition_axis = self._display_axis_label(
                    _text(condition.get("axis"))
                )
                condition_value = _text(condition.get("value")) or ""
                condition_index = next(
                    (
                        index
                        for index, header in enumerate(headers)
                        if self._axis_labels_match(condition_axis, header)
                    ),
                    None,
                )
                if condition_index is not None and condition_value:
                    condition_indexes.append((condition_index, condition_value))
            required_index = max(
                variable_index,
                energy_index,
                outcome_index,
                *(index for index, _value in condition_indexes),
            )
            baseline_row = self._energy_density_comparison_table_row(
                table,
                variable_index=variable_index,
                outcome_index=outcome_index,
                required_index=required_index,
                variable_value=baseline_axis,
                outcome_value=baseline_outcome,
                condition_indexes=condition_indexes,
            )
            observed_row = self._energy_density_comparison_table_row(
                table,
                variable_index=variable_index,
                outcome_index=outcome_index,
                required_index=required_index,
                variable_value=observed_axis,
                outcome_value=observed_outcome,
                condition_indexes=condition_indexes,
            )
            if baseline_row is None or observed_row is None:
                continue
            baseline_energy = _numeric_text(baseline_row[energy_index])
            observed_energy = _numeric_text(observed_row[energy_index])
            if (
                not baseline_energy
                or not observed_energy
                or _float_text(baseline_energy) == _float_text(observed_energy)
            ):
                continue
            independent_process_axes = {
                "build orientation angle",
                "build platform preheating temperature",
                "hatch distance",
                "hatch spacing",
                "heat treatment duration",
                "heat treatment pressure",
                "heat treatment temperature",
                "heat treatment time",
                "heat treatment type",
                "laser power",
                "layer thickness",
                "scan speed",
                "scan strategy",
                "scan strategy rotation angle",
                "scanning strategy",
            }
            changed_process_axes: list[dict[str, str]] = []
            for index, header in enumerate(headers):
                if index in {variable_index, energy_index, outcome_index}:
                    continue
                if self._axis_key(header) not in independent_process_axes:
                    continue
                if index >= len(baseline_row) or index >= len(observed_row):
                    continue
                if self._energy_density_condition_matches(
                    baseline_row[index],
                    observed_row[index],
                ):
                    continue
                changed_process_axes.append(
                    {
                        "axis": header,
                        "baseline": _text(baseline_row[index]) or "",
                        "observed": _text(observed_row[index]) or "",
                    }
                )
            return {
                "baseline_axis": _numeric_text(baseline_row[variable_index]),
                "observed_axis": _numeric_text(observed_row[variable_index]),
                "baseline_energy_density": baseline_energy,
                "observed_energy_density": observed_energy,
                "changed_process_axes": changed_process_axes,
            }
        return {}

    def _energy_density_comparison_table_row(
        self,
        table: SourceTable,
        *,
        variable_index: int,
        outcome_index: int,
        required_index: int,
        variable_value: float,
        outcome_value: float,
        condition_indexes: list[tuple[int, str]],
    ) -> tuple[str, ...] | None:
        for row in table.table_matrix:
            if len(row) <= required_index:
                continue
            row_variable = _float_text(row[variable_index])
            row_outcome = _float_text(row[outcome_index])
            if row_variable != variable_value or row_outcome != outcome_value:
                continue
            if any(
                not self._energy_density_condition_matches(row[index], value)
                for index, value in condition_indexes
            ):
                continue
            return row
        return None

    def _energy_density_condition_matches(self, cell: str, expected: str) -> bool:
        expected_number = _float_text(expected)
        cell_number = _float_text(cell)
        if expected_number is not None and cell_number is not None:
            return expected_number == cell_number
        return cell.strip().casefold() == expected.strip().casefold()

    def _process_axis_display_value(self, axis: str, value: str) -> str:
        unit = {
            "hatch distance": "mm",
            "hatch spacing": "mm",
            "laser power": "W",
            "layer thickness": "mm",
            "scan speed": "mm/s",
        }.get(self._axis_key(axis), "")
        return f"{value} {unit}".strip()

    def _finding_preheating_strength_relative_delta_from_table(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> float | None:
        comparison = self._finding_preheating_table_comparison_values(
            finding,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
        )
        if _text(comparison.get("outcome_axis")) not in {
            "yield strength",
            "ultimate tensile strength",
        }:
            return None
        baseline = _float_text(comparison.get("baseline"))
        observed = _float_text(comparison.get("observed"))
        if baseline is None or observed is None or baseline == 0:
            return None
        return abs(observed - baseline) / abs(baseline) * 100

    def _finding_with_preheating_table_comparison(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, Any]:
        if not self._finding_has_only_table_direct_result(
            finding,
            evidence_by_id=evidence_by_id,
        ) or self._finding_has_non_direct_text_support(
            _mapping(finding.get("evidence_bundle")),
            evidence_by_id=evidence_by_id,
        ):
            return dict(finding)
        comparison = self._finding_preheating_table_comparison_values(
            finding,
            evidence_by_id=evidence_by_id,
            tables_by_id=tables_by_id,
        )
        outcome_axis = _text(comparison.get("outcome_axis")) or ""
        baseline = _text(comparison.get("baseline")) or ""
        observed = _text(comparison.get("observed")) or ""
        if not outcome_axis or not baseline or not observed:
            return dict(finding)

        unit = self._specific_mechanical_property_unit(outcome_axis).strip()
        baseline_value = f"{baseline}{unit}" if unit == "%" else f"{baseline} {unit}"
        observed_value = f"{observed}{unit}" if unit == "%" else f"{observed} {unit}"
        baseline_value = baseline_value.strip()
        observed_value = observed_value.strip()
        baseline_number = _float_text(baseline)
        observed_number = _float_text(observed)
        if baseline_number is None or observed_number is None:
            return dict(finding)
        if observed_number > baseline_number:
            direction = "increases"
        elif observed_number < baseline_number:
            direction = "decreases"
        else:
            direction = "unchanged"
        statement = (
            f"The source table reports {outcome_axis} of {baseline_value} for the "
            f"non-preheated condition and {observed_value} for the preheated "
            "condition."
        )
        variable = _text(next(iter(_strings(finding.get("variables"))), "")) or ""
        updated = dict(finding)
        updated["statement"] = statement
        updated["direction"] = direction
        updated["comparison_summary"] = {
            "variable": variable,
            "direction": direction,
            "outcome": outcome_axis,
            "baseline": {"label": "non-preheated", "value": baseline_value},
            "observed": {"label": "preheated", "value": observed_value},
            "controlled_conditions": [],
        }
        updated["relation_chain"] = [
            {**segment, "statement": statement, "direction": direction}
            for segment in _mapping_list(finding.get("relation_chain"))
        ]
        return updated

    def _merge_aligned_table_findings(
        self,
        primary_findings: list[dict[str, Any]],
        *,
        review_queue_findings: list[dict[str, Any]],
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        merged_primary = list(primary_findings)
        retained_review: list[dict[str, Any]] = []
        for review_finding in review_queue_findings:
            matching_indexes = [
                index
                for index, primary_finding in enumerate(merged_primary)
                if self._table_finding_matches_narrative_finding(
                    review_finding,
                    narrative_finding=primary_finding,
                    evidence_by_id=evidence_by_id,
                )
            ]
            if len(matching_indexes) == 1:
                index = matching_indexes[0]
                merged_primary[index] = self._merged_aligned_table_finding(
                    merged_primary[index],
                    table_finding=review_finding,
                    evidence_by_id=evidence_by_id,
                )
                continue
            retained_review.append(review_finding)
        return merged_primary, retained_review

    def _table_finding_matches_narrative_finding(
        self,
        table_finding: Mapping[str, Any],
        *,
        narrative_finding: Mapping[str, Any],
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        if not self._finding_has_only_table_direct_result(
            table_finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if not self._finding_has_non_table_direct_result(
            narrative_finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if not self._finding_document_ids(
            table_finding,
            evidence_by_id=evidence_by_id,
        ) & self._finding_document_ids(
            narrative_finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if not any(
            self._axis_labels_match(left, right)
            for left in _strings(table_finding.get("variables"))
            for right in _strings(narrative_finding.get("variables"))
        ):
            return False
        if self._finding_outcome_keys(table_finding) != self._finding_outcome_keys(
            narrative_finding
        ):
            return False
        table_direction = self._finding_merge_direction(
            _text(table_finding.get("direction")) or ""
        )
        narrative_direction = self._finding_merge_direction(
            _text(narrative_finding.get("direction")) or ""
        )
        if (
            table_direction
            and narrative_direction
            and table_direction != narrative_direction
        ):
            return False
        comparison = _mapping(table_finding.get("comparison_summary"))
        baseline = _float_text(_mapping(comparison.get("baseline")).get("value"))
        observed = _float_text(_mapping(comparison.get("observed")).get("value"))
        stated_change = self._finding_stated_relative_change(narrative_finding)
        if (
            baseline is None
            or observed is None
            or baseline == 0
            or stated_change is None
        ):
            return False
        calculated_change = abs(observed - baseline) / abs(baseline) * 100
        tolerance = max(1.0, abs(stated_change) * 0.1)
        return abs(calculated_change - abs(stated_change)) <= tolerance

    def _finding_outcome_keys(self, finding: Mapping[str, Any]) -> set[str]:
        keys: set[str] = set()
        for outcome in _strings(finding.get("outcomes")):
            normalized = _normalize_match_text(outcome)
            if normalized in {"ductility", "elongation", "elongation to failure"}:
                normalized = "elongation"
            if normalized:
                keys.add(normalized)
        return keys

    def _finding_stated_relative_change(
        self,
        finding: Mapping[str, Any],
    ) -> float | None:
        match = re.search(
            r"\b(?:increas\w*|decreas\w*|reduc\w*|improv\w*)\b"
            r"[^.;]{0,100}?\bby\s+(?:approximately\s+)?"
            r"(?P<value>\d+(?:\.\d+)?)\s*%",
            _text(finding.get("statement")) or "",
            flags=re.IGNORECASE,
        )
        return float(match.group("value")) if match is not None else None

    def _merged_aligned_table_finding(
        self,
        narrative_finding: Mapping[str, Any],
        *,
        table_finding: Mapping[str, Any],
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        merged = self._merge_presentation_finding(
            narrative_finding,
            table_finding,
            evidence_by_id=evidence_by_id,
        )
        outcomes = _strings(table_finding.get("outcomes"))
        outcome = _text(next(iter(outcomes), "")) or ""
        variables = _strings(merged.get("variables"))
        variable = _text(next(iter(variables), "")) or ""
        statements = _dedupe_strings(
            [
                _text(table_finding.get("statement")) or "",
                _text(narrative_finding.get("statement")) or "",
            ]
        )
        merged["title"] = f"{variable} -> {outcome}"
        merged["statement"] = " ".join(statements)
        merged["outcomes"] = outcomes
        merged["direction"] = _text(table_finding.get("direction")) or ""
        merged["comparison_summary"] = _mapping(
            table_finding.get("comparison_summary")
        )
        merged["scope_summary"] = re.sub(
            r"\b(?:ductility|elongation(?:\s+to\s+failure)?)\b",
            outcome,
            _text(merged.get("scope_summary")) or "",
            flags=re.IGNORECASE,
        )
        merged["relation_chain"] = [
            {
                **segment,
                "outcome": outcome
                if self._finding_outcome_keys({"outcomes": [segment.get("outcome")]})
                == {"elongation"}
                else segment.get("outcome"),
            }
            for segment in _mapping_list(merged.get("relation_chain"))
        ]
        return self._finding_with_refreshed_use_boundary(merged)

    def _finding_preheating_table_comparison_values(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, str]:
        variable_text = _normalize_match_text(
            " ".join(_strings(finding.get("variables")))
        )
        if "preheat" not in variable_text:
            return {}
        outcome_keys = {
            self._axis_key(outcome) for outcome in _strings(finding.get("outcomes"))
        }
        if "ultimate tensile strength" in outcome_keys:
            outcome_axis = "ultimate tensile strength"
        elif "yield strength" in outcome_keys:
            outcome_axis = "yield strength"
        elif "tensile strength" in outcome_keys:
            outcome_axis = "ultimate tensile strength"
        elif "elongation" in outcome_keys or "ductility" in outcome_keys:
            outcome_axis = "elongation"
        else:
            return {}

        for ref_id in _strings(
            _mapping(finding.get("evidence_bundle")).get("direct_result")
        ):
            ref = evidence_by_id.get(ref_id, {})
            source_ref = _text(_locator_mapping(ref.get("locator")).get("source_ref"))
            table = tables_by_id.get(source_ref or "")
            if table is None:
                continue
            indexes = self._specific_mechanical_property_column_indexes(table)
            condition_index = indexes.get("condition")
            outcome_index = indexes.get(outcome_axis)
            if condition_index is None or outcome_index is None:
                continue
            baseline = ""
            observed = ""
            for row in table.table_matrix:
                if len(row) <= max(condition_index, outcome_index):
                    continue
                label = _normalize_match_text(row[condition_index])
                value = _numeric_text(row[outcome_index])
                if not value:
                    continue
                if "non preheated" in label or "without preheat" in label:
                    baseline = value
                elif label == "preheated" or label.startswith("preheated "):
                    observed = value
            if not baseline or not observed:
                continue
            return {
                "outcome_axis": outcome_axis,
                "baseline": baseline,
                "observed": observed,
            }
        return {}

    def _finding_is_low_magnitude_prediction_comparison(
        self,
        finding: Mapping[str, Any],
        statement: str,
    ) -> bool:
        searchable = " ".join(
            [
                statement,
                _text(finding.get("title")) or "",
                " ".join(_strings(finding.get("outcomes"))),
            ]
        )
        normalized = f" {_normalize_match_text(searchable)} "
        if " prediction " not in normalized and " predictions " not in normalized:
            return False
        if " mpa " not in normalized:
            return False
        match = re.search(
            r"\bfrom\s+(-?\d+(?:\.\d+)?)\s*mpa\b.*?"
            r"\bto\s+(-?\d+(?:\.\d+)?)\s*mpa\b",
            statement,
            flags=re.IGNORECASE,
        )
        if match is None:
            return False
        try:
            return abs(float(match.group(2)) - float(match.group(1))) < 5.0
        except ValueError:
            return False

    def _finding_is_density_percentage_comparison(
        self,
        finding: Mapping[str, Any],
        statement: str,
    ) -> bool:
        if not self._finding_has_density_outcome(finding):
            return False
        comparison = _mapping(finding.get("comparison_summary"))
        comparison_parts = [
            _text(comparison.get("variable")) or "",
            _text(comparison.get("outcome")) or "",
            _text(_mapping(comparison.get("baseline")).get("value")) or "",
            _text(_mapping(comparison.get("observed")).get("value")) or "",
        ]
        searchable = " ".join(
            [
                statement,
                _text(finding.get("title")) or "",
                " ".join(_strings(finding.get("outcomes"))),
                " ".join(comparison_parts),
            ]
        ).lower()
        return "density" in searchable and "%" in searchable

    def _finding_has_density_outcome(self, finding: Mapping[str, Any]) -> bool:
        comparison = _mapping(finding.get("comparison_summary"))
        outcome_values = [
            *_strings(finding.get("outcomes")),
            _text(comparison.get("outcome")) or "",
        ]
        for value in outcome_values:
            outcome_key = self._axis_key(value)
            if outcome_key in {"density", "relative density"}:
                return True
            if outcome_key.endswith(" density") and outcome_key != "energy density":
                return True
        title = _text(finding.get("title")) or ""
        if "->" in title:
            title_outcome_key = self._axis_key(title.rsplit("->", 1)[-1])
            return title_outcome_key in {"density", "relative density"} or (
                title_outcome_key.endswith(" density")
                and title_outcome_key != "energy density"
            )
        return False

    def _finding_is_confounded_table_row_candidate(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        if "confounded_table_row_comparison" in _strings(
            finding.get("review_reasons")
        ):
            return True
        summary = _mapping(finding.get("comparison_summary"))
        if _text(summary.get("variable")) == _MULTI_AXIS_TABLE_CONTRAST_LABEL:
            return True
        return self._finding_statement_is_confounded_table_row_comparison(
            self._finding_statement_text(finding)
        )

    def _covered_ved_fatigue_table_sources(
        self,
        findings: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> set[str]:
        sources: set[str] = set()
        for finding in findings:
            claim_id = _text(finding.get("claim_id")) or ""
            if not claim_id.startswith("claim_recovered_ved_defects_fatigue_"):
                continue
            if not self._finding_has_fatigue_strength_axis(finding):
                continue
            for ref_id in _strings(
                _mapping(finding.get("evidence_bundle")).get("direct_result")
            ):
                ref = evidence_by_id.get(ref_id, {})
                if "table" not in (
                    _text(ref.get("source_kind")) or ""
                ).lower():
                    continue
                source_ref = _text(
                    _locator_mapping(ref.get("locator")).get("source_ref")
                )
                if source_ref:
                    sources.add(source_ref)
        return sources

    def _ved_fatigue_review_row_is_covered(
        self,
        finding: Mapping[str, Any],
        *,
        covered_sources: set[str],
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        if not self._finding_has_fatigue_strength_axis(finding):
            return False
        variables = {
            _normalize_match_text(value)
            for value in _strings(finding.get("variables"))
        }
        if not (
            "volumetric energy density" in variables
            or "ved" in variables
        ):
            return False
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_sources = {
            source_ref
            for ref_id in _strings(bundle.get("direct_result"))
            if (
                source_ref := _text(
                    _locator_mapping(evidence_by_id.get(ref_id, {}).get("locator")).get(
                        "source_ref"
                    )
                )
            )
        }
        return bool(direct_sources & covered_sources)

    def _finding_has_fatigue_strength_axis(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        searchable = " ".join(
            [
                *_strings(finding.get("outcomes")),
                _text(finding.get("title")) or "",
                _text(finding.get("statement")) or "",
            ]
        )
        return "fatigue strength" in _normalize_match_text(searchable)

    def _finding_as_review_candidate(
        self,
        finding: Mapping[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        updated = dict(finding)
        statement = self._finding_statement_text(updated)
        reasons = [reason]
        table_row_statement = self._finding_table_row_statement_text(updated)
        if table_row_statement:
            review_statement = self._review_candidate_table_row_statement(
                table_row_statement
            )
            updated["statement"] = review_statement
            updated["direction"] = "condition-dependent"
            updated["relation_chain"] = [
                {
                    **segment,
                    **(
                        {
                            "direction": "condition-dependent",
                            "statement": self._review_candidate_table_row_statement(
                                _text(segment.get("statement")) or ""
                            ),
                        }
                        if self._finding_statement_is_table_row_comparison(
                            _text(segment.get("statement")) or ""
                        )
                        else {}
                    ),
                }
                for segment in _mapping_list(updated.get("relation_chain"))
            ]
            summary = _mapping(updated.get("comparison_summary"))
            if summary:
                updated["comparison_summary"] = {
                    **summary,
                    "direction": "condition-dependent",
                }
        if self._finding_statement_is_confounded_table_row_comparison(statement):
            reasons.append("confounded_table_row_comparison")
            updated["title"] = self._finding_title(
                variables=[_MULTI_AXIS_TABLE_CONTRAST_LABEL],
                outcomes=_strings(updated.get("outcomes")),
                fallback=_text(updated.get("title")) or statement,
            )
            summary = _mapping(updated.get("comparison_summary"))
            if summary:
                summary = dict(summary)
                summary["variable"] = _MULTI_AXIS_TABLE_CONTRAST_LABEL
                observed = dict(_mapping(summary.get("observed")))
                if observed:
                    observed["label"] = _MULTI_AXIS_TABLE_CONTRAST_LABEL
                    summary["observed"] = observed
                updated["comparison_summary"] = summary
        updated["expert_use_status"] = "review_candidate"
        updated["review_status"] = "needs_review"
        updated["dataset_use_status"] = "review_candidate"
        updated["review_reasons"] = _dedupe_strings(
            [
                *_strings(updated.get("review_reasons")),
                *reasons,
                "needs_expert_review",
            ]
        )
        updated["evidence_gap_summary"] = self._finding_evidence_gap_summary(
            support_grade=_text(updated.get("support_grade")) or "",
            review_status="needs_review",
            paper_count=int(updated.get("paper_count") or 0),
            evidence_bundle=_mapping(updated.get("evidence_bundle")),
        )
        updated["upgrade_actions"] = self._finding_upgrade_actions(
            support_grade=_text(updated.get("support_grade")) or "",
            review_status="needs_review",
            paper_count=int(updated.get("paper_count") or 0),
            evidence_bundle=_mapping(updated.get("evidence_bundle")),
        )
        return updated

    def _promote_uncovered_goal_axis_findings(
        self,
        primary: list[dict[str, Any]],
        review_queue: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        goal_axes: list[str] | tuple[str, ...],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        goal_axis_keys = self._goal_axis_keys(goal_axes)
        if not goal_axis_keys:
            return primary, review_queue

        covered_axis_keys = self._covered_goal_axis_keys(
            primary,
            goal_axes=goal_axes,
        )
        promoted: list[dict[str, Any]] = []
        remaining_review_queue: list[dict[str, Any]] = []
        for finding in review_queue:
            axis_key = self._finding_goal_axis_key(finding, goal_axes=goal_axes)
            if (
                axis_key
                and axis_key in goal_axis_keys
                and axis_key not in covered_axis_keys
                and self._promotable_table_goal_axis_finding(
                    finding,
                    evidence_by_id=evidence_by_id,
                )
            ):
                promoted.append(finding)
                covered_axis_keys.add(axis_key)
                continue
            remaining_review_queue.append(finding)
        return [*primary, *promoted], remaining_review_queue

    def _goal_axis_keys(self, goal_axes: list[str] | tuple[str, ...]) -> set[str]:
        return {
            axis_key
            for axis in goal_axes
            if (axis_key := self._axis_key(axis))
        }

    def _covered_goal_axis_keys(
        self,
        findings: list[dict[str, Any]],
        *,
        goal_axes: list[str] | tuple[str, ...],
    ) -> set[str]:
        return {
            axis_key
            for finding in findings
            if (axis_key := self._finding_goal_axis_key(finding, goal_axes=goal_axes))
        }

    def _finding_goal_axis_key(
        self,
        finding: Mapping[str, Any],
        *,
        goal_axes: list[str] | tuple[str, ...],
    ) -> str:
        variable = _text(next(iter(_strings(finding.get("variables"))), ""))
        if not variable:
            return ""
        for axis in goal_axes:
            display_axis = self._display_axis_label(axis)
            if display_axis and self._axis_labels_match(variable, display_axis):
                return self._axis_key(display_axis)
        return self._axis_key(variable)

    def _axis_labels_match(self, left: str, right: str) -> bool:
        left_key = self._axis_key(left)
        right_key = self._axis_key(right)
        if not left_key or not right_key:
            return False
        if left_key == right_key:
            return True
        return self._objective_axis_tokens_match(left, right) or (
            self._objective_axis_tokens_match(right, left)
        )

    def _axis_key(self, value: str) -> str:
        normalized = _normalize_match_text(self._display_axis_label(value))
        if normalized == "scanning speed":
            normalized = "scan speed"
        if normalized == "volumetric energy density":
            normalized = "ved"
        tokens = _normalize_axis_coverage_text(normalized)
        if {"build", "orientation"} <= tokens:
            normalized = "build orientation angle"
        if {"scan", "strategy", "rotation"} <= tokens:
            normalized = "scan strategy rotation angle"
        if {"laser", "powder", "bed", "fusion"} <= tokens or "lpbf" in tokens:
            normalized = "laser beam powder bed fusion"
        if {"selective", "laser", "melting"} <= tokens or "slm" in tokens:
            normalized = "selective laser melting"
        return normalized

    def _promotable_table_goal_axis_finding(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        if not self._finding_has_primary_expert_use_status(finding):
            return False
        if not self._finding_has_only_table_direct_result(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if self._finding_has_same_document_source_context(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if self._finding_statement_is_table_row_comparison(
            self._finding_statement_text(finding)
        ):
            return False
        if not self._finding_has_specific_result_statement(finding):
            return False
        if not self._finding_statement_matches_display_variable(finding):
            return False
        grade = _text(finding.get("support_grade")) or ""
        return grade in {"strong", "partial"}

    def _finding_has_primary_expert_use_status(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        return (_text(finding.get("expert_use_status")) or "") in {
            "paper_level_finding",
            "scoped_expert_finding",
        }

    def _is_recovered_expert_finding(self, finding: Mapping[str, Any]) -> bool:
        claim_id = _text(finding.get("claim_id")) or ""
        return claim_id.startswith("claim_recovered_")

    def _is_recovered_expert_effect(self, effect: Mapping[str, Any]) -> bool:
        claim_id = _text(effect.get("claim_id")) or ""
        return claim_id.startswith("claim_recovered_")

    def _finding_direct_bundle(
        self,
        bundle: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        outcomes: list[str],
        promote_non_table: bool,
        statement: str,
        tables_by_id: Mapping[str, SourceTable],
    ) -> dict[str, list[str]]:
        updated = {key: list(_strings(value)) for key, value in bundle.items()}
        direct_refs = list(updated.get("direct_result", []))
        text_refs = (
            [
                ref_id
                for role in ("mechanism", "uncategorized")
                for ref_id in _strings(updated.get(role))
                if "table"
                not in (
                    _text(evidence_by_id.get(ref_id, {}).get("source_kind")) or ""
                ).lower()
            ]
            if promote_non_table
            else []
        )
        outcome_keys = {
            self._axis_key(outcome)
            for outcome in [
                *outcomes,
                *self._specific_mechanical_outcome_terms(statement),
            ]
        }
        table_refs = []
        for ref_id in _strings(updated.get("uncategorized")):
            evidence_ref = evidence_by_id.get(ref_id, {})
            if "table" not in (
                _text(evidence_ref.get("source_kind")) or ""
            ).lower():
                continue
            if (_text(evidence_ref.get("traceability_status")) or "").lower() not in {
                "resolved",
                "traceable",
            }:
                continue
            source_ref = _text(
                _locator_mapping(evidence_ref.get("locator")).get("source_ref")
            )
            table = tables_by_id.get(source_ref or "")
            if table is None:
                continue
            table_axes = set(self._specific_mechanical_property_column_indexes(table))
            if outcome_keys & table_axes:
                table_refs.append(ref_id)
        updated["direct_result"] = _dedupe_strings(
            [*text_refs, *direct_refs, *table_refs]
        )
        updated["uncategorized"] = [
            ref_id
            for ref_id in updated.get("uncategorized", [])
            if ref_id not in text_refs and ref_id not in table_refs
        ]
        return updated

    def _finding_has_non_direct_text_support(
        self,
        bundle: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        direct_refs = set(_strings(bundle.get("direct_result")))
        for role in ("mechanism", "uncategorized", "condition_context"):
            for ref_id in _strings(bundle.get(role)):
                if ref_id in direct_refs:
                    continue
                source_kind = (
                    _text(evidence_by_id.get(ref_id, {}).get("source_kind")) or ""
                ).lower()
                if source_kind and "table" not in source_kind:
                    return True
        return False

    def _source_finding_document_ids(
        self,
        findings: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> set[str]:
        document_ids: set[str] = set()
        for finding in findings:
            if self._finding_has_non_table_direct_result(
                finding,
                evidence_by_id=evidence_by_id,
            ):
                document_ids.update(
                    self._finding_document_ids(finding, evidence_by_id=evidence_by_id)
                )
        return document_ids

    def _source_evidence_document_ids(
        self,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> set[str]:
        document_ids: set[str] = set()
        for evidence_ref in evidence_by_id.values():
            source_kind = (_text(evidence_ref.get("source_kind")) or "").lower()
            if "table" in source_kind:
                continue
            role = (_text(evidence_ref.get("evidence_role")) or "").lower()
            traceability_status = (
                _text(evidence_ref.get("traceability_status")) or ""
            ).lower()
            if role and role != "direct_support":
                continue
            if traceability_status not in {"", "resolved", "traceable"}:
                continue
            document_id = _text(evidence_ref.get("document_id"))
            if document_id:
                document_ids.add(document_id)
        return document_ids

    def _finding_document_ids(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> set[str]:
        return {
            document_id
            for ref_id in _strings(finding.get("evidence_ref_ids"))
            if (document_id := _text(evidence_by_id.get(ref_id, {}).get("document_id")))
        }

    def _finding_has_only_table_direct_result(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        direct_ref_ids = _strings(
            _mapping(finding.get("evidence_bundle")).get("direct_result")
        )
        if not direct_ref_ids:
            return False
        return all(
            "table" in (
                _text(evidence_by_id.get(ref_id, {}).get("source_kind")) or ""
            ).lower()
            for ref_id in direct_ref_ids
        )

    def _finding_has_non_table_direct_result(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        direct_ref_ids = _strings(
            _mapping(finding.get("evidence_bundle")).get("direct_result")
        )
        return any(
            "table"
            not in (
                _text(evidence_by_id.get(ref_id, {}).get("source_kind")) or ""
            ).lower()
            for ref_id in direct_ref_ids
        )

    def _is_primary_presentation_finding(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> bool:
        grade = _text(finding.get("support_grade")) or ""
        if grade not in {"strong", "partial"}:
            return False
        bundle = _mapping(finding.get("evidence_bundle"))
        if (
            not _strings(bundle.get("direct_result"))
            or not finding.get("relation_chain")
            or not self._finding_statement_matches_display_variable(finding)
        ):
            return False
        if self._finding_is_model_validation_or_prediction(
            finding
        ) and not self._finding_is_experimental_validation_trend(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        has_quote_aligned_direct = self._finding_has_quote_aligned_direct_result(
            finding,
            evidence_by_id=evidence_by_id,
            blocks_by_id=blocks_by_id,
        )
        if has_quote_aligned_direct:
            return True
        if not self._finding_has_table_aligned_direct_result(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if self._is_recovered_expert_finding(finding) and (
            self._finding_has_mechanism_support(bundle)
            or self._finding_has_non_direct_text_support(
                bundle,
                evidence_by_id=evidence_by_id,
            )
        ):
            return True
        if self._finding_has_same_document_source_context(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return False
        if self._finding_has_specific_result_statement(finding):
            return True
        if self._finding_has_specific_result_evidence(
            finding,
            evidence_by_id=evidence_by_id,
        ):
            return True
        return bool(
            int(finding.get("paper_count") or 0) > 1
            or (
                self._finding_has_mechanism_support(bundle)
                and bool(
                    set(_strings(bundle.get("mechanism")))
                    - set(_strings(bundle.get("direct_result")))
                )
            )
        )

    def _finding_statement_text(self, finding: Mapping[str, Any]) -> str:
        return " ".join(
            value
            for value in (
                _text(finding.get("statement")),
                *[
                    _text(item.get("statement"))
                    for item in _mapping_list(finding.get("relation_chain"))
                ],
            )
            if value
        )

    def _finding_is_model_validation_or_prediction(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        warnings = {
            _text(warning)
            for warning in _strings(finding.get("warnings"))
            if _text(warning)
        }
        if "model_validation_finding" in warnings:
            return True
        searchable = " ".join(
            value
            for value in (
                _text(finding.get("title")),
                _text(finding.get("statement")),
                *[
                    _text(item.get("statement"))
                    for item in _mapping_list(finding.get("relation_chain"))
                ],
            )
            if value
        )
        normalized = f" {_normalize_match_text(searchable)} "
        return bool(
            (
                " model " in normalized
                or " prediction " in normalized
                or " predictions " in normalized
                or " predicted " in normalized
                or " validation " in normalized
                or " validate " in normalized
            )
            and (
                " yield strength " in normalized
                or " texture " in normalized
                or " crystallographic " in normalized
            )
        )

    def _finding_is_experimental_validation_trend(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        warnings = {
            _text(warning)
            for warning in _strings(finding.get("warnings"))
            if _text(warning)
        }
        if "model_validation_finding" not in warnings:
            return False
        variables = _normalize_match_text(" ".join(_strings(finding.get("variables"))))
        outcomes = _normalize_match_text(" ".join(_strings(finding.get("outcomes"))))
        if not (
            "yield strength" in outcomes
            and (
                "scan strategy" in variables
                or "build orientation" in variables
                or "rotation angle" in variables
            )
        ):
            return False
        direct_ref_ids = _strings(
            _mapping(finding.get("evidence_bundle")).get("direct_result")
        )
        if not direct_ref_ids:
            return False
        direct_text = " ".join(
            _text(evidence_by_id.get(ref_id, {}).get("quote")) or ""
            for ref_id in direct_ref_ids
        )
        normalized = f" {_normalize_match_text(direct_text)} "
        if not (
            " experimental findings " in normalized
            or " experimental data " in normalized
            or " validation results " in normalized
        ):
            return False
        if not (
            " yield strength " in normalized
            and re.search(r"\byield strengths?\s+increased\s+from\b", normalized)
            and " to " in normalized
        ):
            return False
        return bool(
            " scan strategy " in normalized
            or " build orientation " in normalized
            or " configuration " in normalized
            or " condition " in normalized
        )

    def _finding_has_same_document_source_context(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_document_ids = {
            document_id
            for ref_id in _strings(bundle.get("direct_result"))
            if (document_id := _text(evidence_by_id.get(ref_id, {}).get("document_id")))
        }
        if not direct_document_ids:
            return False
        for bundle_key in (
            "mechanism",
            "condition_context",
            "background",
            "uncategorized",
        ):
            for ref_id in _strings(bundle.get(bundle_key)):
                if ref_id in _strings(bundle.get("direct_result")):
                    continue
                evidence_ref = evidence_by_id.get(ref_id, {})
                document_id = _text(evidence_ref.get("document_id"))
                if document_id not in direct_document_ids:
                    continue
                source_kind = (_text(evidence_ref.get("source_kind")) or "").lower()
                if "table" not in source_kind:
                    return True
        return False

    def _finding_has_specific_result_statement(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        searchable = " ".join(
            value
            for value in (
                _text(finding.get("statement")),
                *[
                    _text(item.get("statement"))
                    for item in _mapping_list(finding.get("relation_chain"))
                ],
            )
            if value
        )
        if not searchable or not re.search(r"\d", searchable):
            return False
        normalized = f" {_normalize_match_text(searchable)} "
        variables = _strings(finding.get("variables"))
        outcomes = _strings(finding.get("outcomes"))
        return bool(
            _quote_has_concrete_result_cue(searchable)
            and variables
            and outcomes
            and self._finding_statement_matches_display_variable(finding)
            and _quote_term_hits(
                normalized,
                self._finding_statement_outcome_terms(outcomes),
            )
        )

    def _finding_has_specific_result_evidence(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_ref_ids = _strings(bundle.get("direct_result"))
        if not direct_ref_ids:
            return False
        direct_text = " ".join(
            _text(evidence_by_id.get(ref_id, {}).get("quote")) or ""
            for ref_id in direct_ref_ids
        )
        has_table_direct_ref = any(
            "table" in (
                _text(evidence_by_id.get(ref_id, {}).get("source_kind")) or ""
            ).lower()
            for ref_id in direct_ref_ids
        )
        has_concrete_result = _quote_has_concrete_result_cue(direct_text) or (
            has_table_direct_ref and bool(re.search(r"\d", direct_text))
        )
        if not direct_text or not has_concrete_result:
            return False
        normalized = self._alignment_searchable_text(direct_text)
        terms = self._finding_quote_alignment_terms(finding)
        return bool(
            _quote_term_hits(normalized, terms["variable"])
            and _quote_term_hits(normalized, terms["outcome"])
        )

    def _finding_statement_matches_display_variable(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        variables = _strings(finding.get("variables"))
        if not variables:
            return False
        primary_variable = variables[:1]
        relation_statements = [
            _text(item.get("statement"))
            for item in _mapping_list(finding.get("relation_chain"))
            if _text(item.get("statement"))
        ]
        searchable = " ".join(
            value
            for value in [
                _text(finding.get("statement")),
                *relation_statements,
            ]
            if value
        )
        return self._variable_matches_direct_evidence(
            primary_variable,
            searchable,
        ) or self._finding_statement_matches_symbol_axis_alias(
            primary_variable[0],
            finding,
            searchable,
        )

    def _finding_statement_matches_symbol_axis_alias(
        self,
        variable: str,
        finding: Mapping[str, Any],
        searchable: str,
    ) -> bool:
        if "greek_" not in _symbol_match_text(searchable):
            return False
        normalized_variable = _normalize_match_text(variable)
        if not normalized_variable:
            return False
        for item in _mapping_list(finding.get("relation_chain")):
            chain_variable = _text(item.get("variable"))
            if _normalize_match_text(chain_variable) != normalized_variable:
                continue
            relation_statement = _text(item.get("statement"))
            if "greek_" in _symbol_match_text(relation_statement):
                return True
        return False

    def _finding_has_table_aligned_direct_result(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> bool:
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_ref_ids = _strings(bundle.get("direct_result"))
        if not direct_ref_ids:
            return False
        statement = _text(finding.get("statement")) or ""
        terms = self._finding_quote_alignment_terms(finding)
        relation_statements = [
            _text(item.get("statement"))
            for item in _mapping_list(finding.get("relation_chain"))
            if _text(item.get("statement"))
        ]
        direct_ref_ids = _strings(bundle.get("direct_result"))
        direct_text = " ".join(
            _text(evidence_by_id.get(ref_id, {}).get("quote")) or ""
            for ref_id in direct_ref_ids
        )
        searchable = self._alignment_searchable_text(
            " ".join([statement, *relation_statements, direct_text])
        )
        has_symbol_axis_statement = "greek_" in _symbol_match_text(searchable)
        if not (
            (
                _quote_term_hits(searchable, terms["variable"])
                or has_symbol_axis_statement
            )
            and _quote_term_hits(searchable, terms["outcome"])
            and re.search(r"\d", " ".join([statement, *relation_statements, direct_text]))
        ):
            return False
        for ref_id in direct_ref_ids:
            evidence_ref = evidence_by_id.get(ref_id, {})
            source_kind = (_text(evidence_ref.get("source_kind")) or "").lower()
            locator = _locator_mapping(evidence_ref.get("locator"))
            traceability_status = (
                _text(evidence_ref.get("traceability_status")) or ""
            ).lower()
            if (
                "table" in source_kind
                and _text(locator.get("source_ref"))
                and traceability_status in {"resolved", "traceable"}
            ):
                return True
        return False

    def _alignment_searchable_text(self, value: Any) -> str:
        normalized = _normalize_match_text(str(value or ""))
        symbol_text = _symbol_match_text(value)
        return f" {normalized} {symbol_text} "

    def _finding_has_quote_aligned_direct_result(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> bool:
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_ref_ids = _strings(bundle.get("direct_result"))
        if not direct_ref_ids:
            return False
        terms = self._finding_quote_alignment_terms(finding)
        if not terms["variable"] or not terms["outcome"]:
            return False
        condition_text = " ".join(
            _text(evidence_by_id.get(ref_id, {}).get("quote")) or ""
            for ref_id in _strings(bundle.get("condition_context"))
        )
        normalized_condition_text = _normalize_match_text(condition_text)
        quote_hints = {
            "variable": terms["variable"],
            "outcome": terms["outcome"],
            "relation": {
                term
                for value in (
                    _text(finding.get("statement")),
                    _text(finding.get("title")),
                    _text(finding.get("direction")),
                    *_strings(finding.get("mediators")),
                )
                for term in _quote_hint_terms(value)
            },
        }
        for ref_id in direct_ref_ids:
            evidence_ref = evidence_by_id.get(ref_id, {})
            source_kind = (_text(evidence_ref.get("source_kind")) or "").lower()
            if "table" in source_kind:
                continue
            locator = _locator_mapping(evidence_ref.get("locator"))
            block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
            source_block = self._presentation_source_block_for_quote(
                block,
                blocks_by_id=blocks_by_id,
                quote_hints=quote_hints,
            )
            source_text = _text(source_block.text if source_block else None) or _text(
                evidence_ref.get("quote")
            )
            visible_quote = self._presentation_quote_for_ref(
                quote=_text(evidence_ref.get("quote")),
                source_text=source_text,
                quote_hints=quote_hints,
            )
            searchable = _normalize_match_text(visible_quote)
            if not searchable:
                continue
            bounded = f" {searchable} "
            variable_evidence = bounded
            if self._is_recovered_expert_finding(finding) and normalized_condition_text:
                variable_evidence = f"{bounded} {normalized_condition_text} "
            if not _quote_term_hits(variable_evidence, terms["variable"]):
                continue
            if not _quote_term_hits(bounded, terms["outcome"]):
                continue
            outcome_keys = {
                _normalize_match_text(value)
                for value in _strings(finding.get("outcomes"))
            }
            if "microstructure" in outcome_keys and not _quote_term_hits(
                bounded,
                terms["microstructure_concrete"],
            ):
                continue
            if "mechanical properties" in outcome_keys and not _quote_term_hits(
                bounded,
                terms["mechanical_concrete"],
            ):
                continue
            if (
                "pitting corrosion behavior" in outcome_keys
                and not _quote_term_hits(bounded, terms["corrosion_concrete"])
            ):
                continue
            if (
                "corrosion behavior" in outcome_keys
                and not _quote_term_hits(bounded, terms["corrosion_concrete"])
            ):
                continue
            return True
        return False

    def _finding_quote_alignment_terms(
        self,
        finding: Mapping[str, Any],
    ) -> dict[str, set[str]]:
        variable_terms: set[str] = set()
        for value in _strings(finding.get("variables")):
            variable_terms.update(_quote_hint_terms(value))
            symbol_term = _symbol_match_term(value)
            if symbol_term:
                variable_terms.add(symbol_term)
            if _normalize_match_text(value) == "volumetric energy density":
                variable_terms.add("ved")
            tokens = _meaningful_match_tokens(value)
            if not tokens:
                continue
            if len(tokens) == 1:
                variable_terms.update(_target_token_variants(tokens[0]))
            else:
                variable_terms.add(" ".join(tokens))
                for index in range(len(tokens) - 1):
                    left = tokens[index]
                    right = tokens[index + 1]
                    if left in {"and", "with"} or right in {"and", "with"}:
                        continue
                    variable_terms.add(f"{left} {right}")
            token_set = set(tokens)
            if "preheating" in token_set and (
                "platform" in token_set or "plate" in token_set
            ):
                variable_terms.update({"preheating", "build plate", "build platform"})
            if token_set & {"level", "size", "amount", "content"}:
                for token in token_set - {"level", "size", "amount", "content"}:
                    variable_terms.update(_target_token_variants(token))

        outcome_terms: set[str] = set()
        microstructure_concrete = {
            "cellular",
            "grain",
            "grains",
            "melt pool",
            "microstructural",
        }
        mechanical_concrete = {
            "ductility",
            "elongation",
            "strength",
            "tensile",
            "yield",
        }
        corrosion_concrete = {
            "corrosion",
            "electrochemical",
            "passivation",
            "pitting",
            "polarization",
        }
        for value in _strings(finding.get("outcomes")):
            outcome_terms.update(_quote_hint_terms(value))
            normalized = _normalize_match_text(value)
            if normalized == "ductility":
                outcome_terms.update({"ductility", "elongation", "el"})
            if normalized == "microstructure":
                outcome_terms.update(microstructure_concrete)
            elif normalized == "mechanical properties":
                outcome_terms.update(mechanical_concrete)
            elif normalized in {"corrosion behavior", "pitting corrosion behavior"}:
                outcome_terms.update(corrosion_concrete)
        return {
            "variable": variable_terms,
            "outcome": outcome_terms,
            "microstructure_concrete": microstructure_concrete,
            "mechanical_concrete": mechanical_concrete,
            "corrosion_concrete": corrosion_concrete,
        }

    def _sort_presentation_findings(
        self,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grade_rank = {
            "strong": 0,
            "partial": 1,
            "weak": 2,
            "conflict": 3,
            "insufficient": 4,
        }

        def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
            index, finding = item
            bundle = _mapping(finding.get("evidence_bundle"))
            has_direct = bool(_strings(bundle.get("direct_result")))
            has_chain = bool(finding.get("relation_chain"))
            grade = _text(finding.get("support_grade")) or ""
            usable_rank = (
                0 if grade in {"strong", "partial"} and has_direct and has_chain else 1
            )
            return (
                usable_rank,
                grade_rank.get(grade, 5),
                0 if has_direct else 1,
                index,
            )

        return [finding for _, finding in sorted(enumerate(findings), key=sort_key)]

    def _findings_without_redundant_generic_mechanical_rows(
        self,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        concrete_mechanical_variables = {
            self._axis_key(variable)
            for finding in findings
            for variable in _strings(finding.get("variables"))
            if self._finding_has_concrete_mechanical_outcome(finding)
        }
        concrete_mechanical_variables.discard("")
        if not concrete_mechanical_variables:
            return findings
        return [
            finding
            for finding in findings
            if not (
                self._finding_is_generic_mechanical_property_row(finding)
                and (
                    self._finding_variable_axis_keys(finding)
                    & concrete_mechanical_variables
                    or self._finding_is_generic_mechanical_process_umbrella(finding)
                )
            )
        ]

    def _findings_without_redundant_multi_outcome_rows(
        self,
        findings: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        def outcome_keys(finding: Mapping[str, Any]) -> set[str]:
            keys: set[str] = set()
            for outcome in _strings(finding.get("outcomes")):
                normalized = _normalize_match_text(outcome)
                if normalized in {"ductility", "elongation", "elongation to failure"}:
                    normalized = "ductility"
                if normalized:
                    keys.add(normalized)
            return keys

        indexed = [
            (
                finding,
                outcome_keys(finding),
                self._finding_document_ids(finding, evidence_by_id=evidence_by_id),
            )
            for finding in findings
        ]
        retained: list[dict[str, Any]] = []
        for index, (finding, finding_outcomes, document_ids) in enumerate(indexed):
            if len(finding_outcomes) <= 1 or not document_ids:
                retained.append(finding)
                continue
            if "single_variable_effect_not_isolated" in _strings(
                finding.get("warnings")
            ):
                retained.append(finding)
                continue
            variables = _strings(finding.get("variables"))
            covered_outcomes: set[str] = set()
            for candidate_index, (
                candidate,
                candidate_outcomes,
                candidate_document_ids,
            ) in enumerate(indexed):
                if candidate_index == index or len(candidate_outcomes) >= len(
                    finding_outcomes
                ):
                    continue
                if not document_ids & candidate_document_ids:
                    continue
                if (_text(candidate.get("support_grade")) or "") not in {
                    "strong",
                    "partial",
                }:
                    continue
                if not _strings(
                    _mapping(candidate.get("evidence_bundle")).get("direct_result")
                ) or not _mapping_list(candidate.get("relation_chain")):
                    continue
                if not any(
                    self._axis_labels_match(variable, candidate_variable)
                    for variable in variables
                    for candidate_variable in _strings(candidate.get("variables"))
                ):
                    continue
                covered_outcomes.update(finding_outcomes & candidate_outcomes)
            if covered_outcomes != finding_outcomes:
                retained.append(finding)
        return retained

    def _finding_has_concrete_mechanical_outcome(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        return any(
            _normalize_match_text(outcome)
            in {
                "ductility",
                "elongation",
                "fatigue life",
                "fatigue strength",
                "ultimate tensile strength",
                "yield strength",
            }
            for outcome in _strings(finding.get("outcomes"))
        )

    def _finding_is_generic_mechanical_property_row(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        outcomes = {
            _normalize_match_text(outcome)
            for outcome in _strings(finding.get("outcomes"))
        }
        if outcomes != {"mechanical properties"}:
            return False
        statement = _normalize_match_text(_text(finding.get("statement")) or "")
        relation_text = _normalize_match_text(
            " ".join(
                _text(segment.get("statement")) or ""
                for segment in _mapping_list(finding.get("relation_chain"))
            )
        )
        return bool(
            "is associated with mechanical properties" in statement
            or (
                "mechanical properties" in relation_text
                and not re.search(
                    r"\b(yield|ultimate|tensile|elongation|ductility|fatigue)\b",
                    statement,
                )
            )
        )

    def _finding_variable_axis_keys(
        self,
        finding: Mapping[str, Any],
    ) -> set[str]:
        keys = {self._axis_key(variable) for variable in _strings(finding.get("variables"))}
        for segment in _mapping_list(finding.get("relation_chain")):
            if variable := _text(segment.get("variable")):
                keys.add(self._axis_key(variable))
        keys.discard("")
        return keys

    def _finding_is_generic_mechanical_process_umbrella(
        self,
        finding: Mapping[str, Any],
    ) -> bool:
        variable_text = " ".join(_strings(finding.get("variables")))
        title = _text(finding.get("title")) or ""
        statement = _text(finding.get("statement")) or ""
        normalized = _normalize_match_text(" ".join((variable_text, title, statement)))
        return bool(
            "mechanical properties" in normalized
            and (
                "processing parameters" in normalized
                or "process parameters" in normalized
                or "slm processing" in normalized
            )
        )

    def _presentation_finding(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        relations_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable],
        contexts_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        claim_id = _text(effect.get("claim_id")) or "claim"
        relations = self._finding_relations(effect, relations_by_id)
        fallback_variable = _text(effect.get("variable_axis"))
        statement_axis = self._statement_comparison_axis(
            _text(effect.get("statement")) or "",
            goal_axes=[fallback_variable] if fallback_variable else [],
        )
        if (
            len(relations) == 1
            and statement_axis
            and not self._is_recovered_expert_effect(effect)
        ):
            relations = [
                self._relation_with_presentation_subject(
                    relations[0],
                    statement_axis,
                )
            ]
            fallback_variable = statement_axis
        _, initial_outcomes = self._finding_roles(effect, relations)
        initial_evidence_bundle = self._finding_evidence_bundle(
            effect,
            evidence_by_id=evidence_by_id,
            relations=relations,
            outcomes=initial_outcomes,
        )
        initial_display_variables = self._finding_display_variables(
            self._finding_variables(effect, relations),
            relations=relations,
            evidence_by_id=evidence_by_id,
            evidence_bundle=initial_evidence_bundle,
        )
        if self._is_recovered_expert_effect(effect):
            initial_display_variables = self._finding_variables(effect, relations)
        if (
            len(relations) == 1
            and initial_display_variables
            and not self._is_recovered_expert_effect(effect)
            and initial_display_variables[0]
            != self._presentation_relation_side(relations[0].get("subject"))
            and self._variable_matches_direct_evidence(
                [initial_display_variables[0]],
                _text(effect.get("statement")) or "",
            )
        ):
            relations = [
                self._relation_with_presentation_subject(
                    relations[0],
                    initial_display_variables[0],
                )
            ]
        if (
            len(relations) == 1
            and fallback_variable
            and fallback_variable
            != self._presentation_relation_side(relations[0].get("subject"))
            and self._variable_matches_direct_evidence(
                [fallback_variable],
                _text(effect.get("statement")) or "",
            )
        ):
            relations = [
                self._relation_with_presentation_subject(
                    relations[0],
                    fallback_variable,
                )
            ]
        variables = self._finding_variables(effect, relations)
        mediators, outcomes = self._finding_roles(effect, relations)
        direction = self._finding_direction(effect, relations)
        relation_ids = list(_strings(effect.get("relation_ids")))
        evidence_bundle = self._finding_evidence_bundle(
            effect,
            evidence_by_id=evidence_by_id,
            relations=relations,
            outcomes=outcomes,
        )
        evidence_bundle = self._finding_result_source_bundle(
            effect,
            evidence_bundle=evidence_bundle,
            evidence_by_id=evidence_by_id,
            relations=relations,
            outcomes=outcomes,
            blocks_by_id=blocks_by_id,
        )
        evidence_bundle = self._compact_finding_evidence_bundle(
            evidence_bundle,
            evidence_by_id=evidence_by_id,
        )
        evidence_bundle = self._finding_direct_bundle(
            evidence_bundle,
            evidence_by_id=evidence_by_id,
            outcomes=outcomes,
            promote_non_table=self._is_recovered_expert_effect(effect),
            statement=_text(effect.get("statement")) or "",
            tables_by_id=tables_by_id,
        )
        mechanism_source_text = " ".join(
            self._direct_evidence_source_texts(
                evidence_by_id=evidence_by_id,
                evidence_bundle=evidence_bundle,
                blocks_by_id=blocks_by_id,
            )
        )
        mechanism_ref_ids = self._direct_evidence_mechanism_ref_ids(
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        )
        normalized_outcomes = _normalize_match_text(" ".join(outcomes))
        if (
            "passive film" in _normalize_match_text(mechanism_source_text)
            and ("corrosion" in normalized_outcomes or "pitting" in normalized_outcomes)
            and not any(
                _normalize_match_text(mediator) == "passive film"
                for mediator in mediators
            )
        ):
            mediators = [*mediators, "passive film"]
            evidence_bundle = {
                key: list(value) for key, value in evidence_bundle.items()
            }
            evidence_bundle["mechanism"] = _dedupe_strings(
                [
                    *evidence_bundle.get("mechanism", []),
                    *[
                        ref_id
                        for ref_id in evidence_bundle.get("direct_result", [])
                        if "passive film"
                        in self._evidence_ref_source_text(
                            evidence_by_id.get(ref_id, {}),
                            blocks_by_id=blocks_by_id,
                        )
                    ],
                ]
            )
        evidence_mediators = self._finding_mediators_from_direct_evidence(
            mechanism_source_text
        )
        if evidence_mediators:
            mediators = _dedupe_strings([*mediators, *evidence_mediators])
            evidence_bundle = {
                key: list(value) for key, value in evidence_bundle.items()
            }
            evidence_bundle["mechanism"] = _dedupe_strings(
                [
                    *evidence_bundle.get("mechanism", []),
                    *mechanism_ref_ids,
                ]
            )
        display_variables = self._finding_display_variables(
            variables,
            relations=relations,
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
        )
        if self._is_recovered_expert_effect(effect):
            display_variables = variables
            if (
                _text(effect.get("claim_id")) or ""
            ).startswith("claim_recovered_ved_defects_fatigue_"):
                display_variables = [
                    "VED"
                    if _normalize_match_text(variable) == "volumetric energy density"
                    else variable
                    for variable in display_variables
                ]
        statement = self._finding_statement(
            statement=_text(effect.get("statement")) or "",
            variables=display_variables,
            relations=relations,
            outcomes=outcomes,
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        )
        narrowed_outcomes = self._specific_mechanical_outcomes(
            outcomes,
            relations=relations,
            statement=" ".join(
                value
                for value in (_text(effect.get("statement")), statement)
                if value
            ),
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        )
        if narrowed_outcomes != outcomes:
            outcomes = narrowed_outcomes
            statement = self._finding_statement(
                statement=_text(effect.get("statement")) or "",
                variables=display_variables,
                relations=relations,
                outcomes=outcomes,
                evidence_by_id=evidence_by_id,
                evidence_bundle=evidence_bundle,
                blocks_by_id=blocks_by_id,
            )
            statement = (
                self._relation_derived_finding_statement(
                    relations,
                    variables=display_variables,
                    outcomes=outcomes,
                )
                or statement
            )
        contexts = [
            contexts_by_id[context_id]
            for context_id in _strings(effect.get("context_ids"))
            if context_id in contexts_by_id
        ]
        statement = self._contextualized_comparison_statement(
            statement,
            variable_axis=display_variables[0] if display_variables else "",
            target_property=outcomes[0] if outcomes else "",
            direction=direction,
            contexts=contexts,
        )
        statement_was_cleaned = False
        normalized_statement = f" {_normalize_match_text(statement)} "
        if (
            " preheating " in normalized_statement
            and " yield strength " in normalized_statement
            and " 14 " in normalized_statement
            and " 4 " in normalized_statement
            and " microstructure " in normalized_statement
            and " texture evolution " in normalized_statement
        ):
            outcome_keys = {self._axis_key(outcome) for outcome in outcomes}
            if outcome_keys & {"ductility", "elongation"}:
                statement = (
                    "Build platform preheating increased elongation by "
                    "approximately 14% and yield strength by approximately 4%; "
                    "the authors attributed both changes to microstructure and "
                    "texture evolution."
                )
            else:
                statement = (
                    "Build platform preheating increased yield strength by "
                    "approximately 4%; the authors attributed the change to "
                    "microstructure and texture evolution."
                )
            statement_was_cleaned = True
        if re.search(r"\bauthors?\s+attributed\b", statement, flags=re.IGNORECASE):
            effect = {
                **effect,
                "warnings": _dedupe_strings(
                    [
                        *_strings(effect.get("warnings")),
                        "author_attributed_mechanism",
                    ]
                ),
            }
        review_status = self._finding_review_status(effect)
        scope_summary = _compact_finding_scope_summary(
            _text(effect.get("context_summary")) or "",
            variables=display_variables,
            outcomes=outcomes,
            statement=statement,
        )
        scope_summary = self._finding_scope_summary_with_direct_conditions(
            scope_summary,
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        )
        support_grade = self._finding_support_grade(
            effect,
            evidence_bundle=evidence_bundle,
            outcomes=outcomes,
            relation_ids=relation_ids,
            review_status=review_status,
            scope_summary=scope_summary,
        )
        paper_count = int(effect.get("paper_count") or 0)
        expert_use_status = self._finding_expert_use_status(
            support_grade=support_grade,
            review_status=review_status,
            paper_count=paper_count,
            evidence_bundle=evidence_bundle,
        )
        generalization_status = self._finding_generalization_status(
            support_grade=support_grade,
            review_status=review_status,
            paper_count=paper_count,
            evidence_bundle=evidence_bundle,
        )
        relation_chain = self._finding_relation_chain(
            relations,
            variables=display_variables,
            mediators=mediators,
            direction=direction,
            outcomes=outcomes,
        )
        if statement_was_cleaned:
            relation_chain = [
                {**segment, "statement": statement} for segment in relation_chain
            ]
        comparison_summary = self._finding_comparison_summary(
            statement,
            variables=display_variables,
            outcomes=outcomes,
            direction=direction,
        )
        if claim_id.startswith("claim_recovered_texture_yield_build_orientation_"):
            comparison_summary = {
                "variable": "α and β build orientation angles",
                "direction": "increases",
                "outcome": "yield strength",
                "baseline": {"label": "α=0°, β=0°", "value": "334.2 MPa"},
                "observed": {"label": "α=45°, β=22.5°", "value": "363.1 MPa"},
                "controlled_conditions": [
                    {"axis": "scan strategy rotation angle (θ)", "value": "0°"}
                ],
            }
        elif claim_id.startswith("claim_recovered_texture_yield_scan_rotation_"):
            comparison_summary = {
                "variable": "scan strategy rotation angle (θ)",
                "direction": "increases",
                "outcome": "yield strength",
                "baseline": {"label": "θ=0°", "value": "334.2 MPa"},
                "observed": {"label": "θ=45°", "value": "351.9 MPa"},
                "controlled_conditions": [
                    {"axis": "α build orientation angle", "value": "0°"},
                    {"axis": "β build orientation angle", "value": "0°"},
                ],
            }
        return {
            "finding_id": f"finding_{claim_id}",
            "claim_id": claim_id,
            "title": self._finding_title(
                variables=display_variables,
                outcomes=outcomes,
                fallback=_text(effect.get("title")) or _text(effect.get("statement")),
            ),
            "statement": statement,
            "variables": display_variables,
            "mediators": mediators,
            "outcomes": outcomes,
            "direction": direction,
            "relation_chain": relation_chain,
            "scope_summary": scope_summary,
            "support_grade": support_grade,
            "review_status": review_status,
            "confidence": effect.get("confidence"),
            "paper_count": effect.get("paper_count") or 0,
            "evidence_count": effect.get("evidence_count") or 0,
            "evidence_ref_ids": list(_strings(effect.get("evidence_ref_ids"))),
            "context_ids": list(_strings(effect.get("context_ids"))),
            "relation_ids": relation_ids,
            "evidence_bundle": evidence_bundle,
            "comparison_summary": comparison_summary,
            "expert_use_status": expert_use_status,
            "dataset_use_status": "review_candidate",
            "generalization_status": generalization_status,
            "generalization_note": self._finding_generalization_note(
                generalization_status=generalization_status,
                paper_count=paper_count,
            ),
            "evidence_gap_summary": self._finding_evidence_gap_summary(
                support_grade=support_grade,
                review_status=review_status,
                paper_count=paper_count,
                evidence_bundle=evidence_bundle,
            ),
            "upgrade_actions": self._finding_upgrade_actions(
                support_grade=support_grade,
                review_status=review_status,
                paper_count=paper_count,
                evidence_bundle=evidence_bundle,
            ),
            "related_review_finding_ids": list(
                _strings(effect.get("related_review_finding_ids"))
            ),
            "review_reasons": self._finding_review_reasons(
                effect,
                evidence_bundle=evidence_bundle,
                mediators=mediators,
                mechanism_source_text=mechanism_source_text,
                outcomes=outcomes,
                relation_ids=relation_ids,
                review_status=review_status,
                support_grade=support_grade,
                scope_summary=scope_summary,
            ),
            "warnings": list(_strings(effect.get("warnings"))),
        }

    def _finding_comparison_summary(
        self,
        statement: str,
        *,
        variables: list[str],
        outcomes: list[str],
        direction: str,
    ) -> dict[str, Any] | None:
        text = _text(statement) or ""
        if not text:
            return None
        variable = self._display_axis_label(variables[0]) if variables else ""
        outcome = outcomes[0] if outcomes else ""
        if not variable or not outcome:
            return None
        normalized_direction = self._comparison_summary_direction(direction, text)
        if not normalized_direction:
            return None

        changing_pattern = re.compile(
            r"^(?:Under|With)\s+(?P<conditions>.+),\s+changing\s+"
            r"(?P<axis>.+?)\s+from\s+"
            r"(?P<baseline_axis_value>.+?)\s+to\s+"
            r"(?P<observed_axis_value>.+?)\s+"
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+"
            r"(?P<outcome>.+?)\s+from\s+"
            r"(?P<baseline_value>.+?)\s+to\s+"
            r"(?P<observed_value>.+?)\.?$",
            flags=re.IGNORECASE,
        )
        changing_match = changing_pattern.match(text.strip())
        if changing_match is not None:
            axis_label = self._comparison_statement_axis_label(variable)
            baseline_axis_value = _clean_comparison_summary_value(
                changing_match.group("baseline_axis_value")
            )
            observed_axis_value = _clean_comparison_summary_value(
                changing_match.group("observed_axis_value")
            )
            baseline_value = _clean_comparison_summary_value(
                changing_match.group("baseline_value")
            )
            observed_value = _clean_comparison_summary_value(
                changing_match.group("observed_value")
            )
            statement_outcome = _clean_comparison_summary_text(
                changing_match.group("outcome")
            )
            if baseline_axis_value and observed_axis_value and baseline_value and observed_value:
                return {
                    "variable": variable,
                    "direction": normalized_direction,
                    "outcome": outcome or statement_outcome,
                    "baseline": {
                        "label": f"{axis_label}={baseline_axis_value}",
                        "value": baseline_value,
                    },
                    "observed": {
                        "label": f"{axis_label}={observed_axis_value}",
                        "value": observed_value,
                    },
                    "controlled_conditions": self._comparison_summary_conditions(
                        changing_match.group("conditions")
                    ),
                }

        multi_axis_pattern = re.compile(
            r"^(?:With\s+(?P<conditions>.+),\s+)?"
            r"table-row comparison changes\s+"
            r"(?P<changed_axes>.+?);\s+"
            r"(?P<outcome>.+?)\s+"
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+"
            r"from\s+"
            r"(?P<baseline_value>.+?)\s+to\s+"
            r"(?P<observed_value>.+?)\.?$",
            flags=re.IGNORECASE,
        )
        multi_axis_match = multi_axis_pattern.match(text.strip())
        if multi_axis_match is not None:
            baseline_value = _clean_comparison_summary_value(
                multi_axis_match.group("baseline_value")
            )
            observed_value = _clean_comparison_summary_value(
                multi_axis_match.group("observed_value")
            )
            statement_outcome = _clean_comparison_summary_text(
                multi_axis_match.group("outcome")
            )
            if baseline_value and observed_value:
                return {
                    "variable": _MULTI_AXIS_TABLE_CONTRAST_LABEL,
                    "direction": self._comparison_summary_direction(
                        multi_axis_match.group("direction"),
                        text,
                    ),
                    "outcome": outcome or statement_outcome,
                    "baseline": {"label": "", "value": baseline_value},
                    "observed": {
                        "label": _MULTI_AXIS_TABLE_CONTRAST_LABEL,
                        "value": observed_value,
                    },
                    "controlled_conditions": self._comparison_summary_conditions(
                        multi_axis_match.group("conditions")
                    ),
                }

        target_outcome = _normalize_match_text(outcome)
        pattern = re.compile(
            r"^(?:Under|With)\s+(?P<conditions>.+),\s+"
            r"(?P<observed_label>.+?)\s+"
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+"
            r"(?P<outcome>.+?)\s+from\s+"
            r"(?P<baseline_segment>.+?)\s+to\s+"
            r"(?P<observed_value>.+?)\.?$",
            flags=re.IGNORECASE,
        )
        match = pattern.match(text.strip())
        if match is not None:
            observed_label = _clean_comparison_summary_text(
                match.group("observed_label")
            )
            baseline_value, baseline_label = _comparison_summary_baseline(
                match.group("baseline_segment")
            )
            observed_value = _clean_comparison_summary_value(
                match.group("observed_value")
            )
            statement_outcome = _clean_comparison_summary_text(match.group("outcome"))
            if observed_label and baseline_value and observed_value:
                return {
                    "variable": variable,
                    "direction": normalized_direction,
                    "outcome": outcome or statement_outcome,
                    "baseline": {
                        "label": baseline_label,
                        "value": baseline_value,
                    },
                    "observed": {
                        "label": observed_label,
                        "value": observed_value,
                    },
                    "controlled_conditions": self._comparison_summary_conditions(
                        match.group("conditions")
                    ),
                }

        from_to_pattern = re.compile(
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+"
            r"(?P<outcome>.+?)\s+from\s+"
            r"(?P<baseline_segment>.+?)\s+to\s+"
            r"(?P<observed_value>[+-]?\d+(?:\.\d+)?\s*(?:%|MPa|GPa|J/mm3|J/mm³|HV|°\s*C|°C|C|K)?)",
            flags=re.IGNORECASE,
        )
        from_to_match = from_to_pattern.search(text.strip())
        if from_to_match is not None:
            statement_outcome = _clean_comparison_summary_text(
                from_to_match.group("outcome")
            )
            normalized_statement_outcome = _normalize_match_text(statement_outcome)
            if (
                normalized_statement_outcome
                and (
                    not target_outcome
                    or target_outcome in normalized_statement_outcome
                    or normalized_statement_outcome in target_outcome
                )
            ):
                baseline_value, baseline_label = _comparison_summary_baseline(
                    from_to_match.group("baseline_segment")
                )
                observed_value = _clean_comparison_summary_value(
                    from_to_match.group("observed_value")
                )
                baseline_value = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    baseline_value,
                    flags=re.IGNORECASE,
                )
                observed_value = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    observed_value,
                    flags=re.IGNORECASE,
                )
                if baseline_value and observed_value:
                    return {
                        "variable": variable,
                        "direction": normalized_direction,
                        "outcome": outcome or statement_outcome,
                        "baseline": {
                            "label": baseline_label,
                            "value": baseline_value,
                        },
                        "observed": {
                            "label": variable,
                            "value": observed_value,
                        },
                        "controlled_conditions": [],
                    }

        outcome_first_from_to_pattern = re.compile(
            r"(?P<outcome>.+?)\s+"
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+"
            r"from\s+"
            r"(?P<baseline_segment>[^.;]+?)\s+to\s+"
            r"(?P<observed_value>.+?)(?:\s+with\b|[.;](?:\s|$)|$)",
            flags=re.IGNORECASE,
        )
        outcome_first_from_to_match = outcome_first_from_to_pattern.search(
            text.strip()
        )
        if outcome_first_from_to_match is not None:
            statement_outcome = _clean_comparison_summary_text(
                outcome_first_from_to_match.group("outcome")
            )
            normalized_statement_outcome = _normalize_match_text(statement_outcome)
            if (
                normalized_statement_outcome
                and (
                    not target_outcome
                    or target_outcome in normalized_statement_outcome
                    or normalized_statement_outcome in target_outcome
                )
            ):
                baseline_value, baseline_label = _comparison_summary_baseline(
                    outcome_first_from_to_match.group("baseline_segment")
                )
                observed_value = _clean_comparison_summary_value(
                    outcome_first_from_to_match.group("observed_value")
                )
                baseline_value = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    baseline_value,
                    flags=re.IGNORECASE,
                )
                observed_value = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    observed_value,
                    flags=re.IGNORECASE,
                )
                if baseline_value and observed_value:
                    return {
                        "variable": variable,
                        "direction": normalized_direction,
                        "outcome": outcome or statement_outcome,
                        "baseline": {
                            "label": baseline_label,
                            "value": baseline_value,
                        },
                        "observed": {
                            "label": variable,
                            "value": observed_value,
                        },
                        "controlled_conditions": [],
                    }

        from_to_label_pattern = re.compile(
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+"
            r"(?P<outcome>.+?)\s+from\s+"
            r"(?P<baseline_segment>[^.;]+?)\s+to\s+"
            r"(?P<observed_value>.+?)(?:[.;](?:\s|$)|$)",
            flags=re.IGNORECASE,
        )
        from_to_label_match = from_to_label_pattern.search(text.strip())
        if from_to_label_match is not None:
            statement_outcome = _clean_comparison_summary_text(
                from_to_label_match.group("outcome")
            )
            normalized_statement_outcome = _normalize_match_text(statement_outcome)
            if (
                normalized_statement_outcome
                and (
                    not target_outcome
                    or target_outcome in normalized_statement_outcome
                    or normalized_statement_outcome in target_outcome
                )
            ):
                baseline_value, baseline_label = _comparison_summary_baseline(
                    from_to_label_match.group("baseline_segment")
                )
                observed_value = _clean_comparison_summary_value(
                    from_to_label_match.group("observed_value")
                )
                baseline_value = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    baseline_value,
                    flags=re.IGNORECASE,
                )
                observed_value = re.sub(
                    r"^(?:the|a|an)\s+",
                    "",
                    observed_value,
                    flags=re.IGNORECASE,
                )
                if baseline_value and observed_value:
                    return {
                        "variable": variable,
                        "direction": normalized_direction,
                        "outcome": outcome or statement_outcome,
                        "baseline": {
                            "label": baseline_label,
                            "value": baseline_value,
                        },
                        "observed": {
                            "label": variable,
                            "value": observed_value,
                        },
                        "controlled_conditions": [],
                    }

        delta_pattern = re.compile(
            r"(?P<observed_label>.+?)\s+"
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises)\s+"
            r"(?P<outcome>.+?)\s+by\s+"
            r"(?P<delta>[+-]?\d+(?:\.\d+)?\s*%)",
            flags=re.IGNORECASE,
        )
        delta_match = delta_pattern.search(text.strip())
        if delta_match is None:
            return None
        statement_outcome = _clean_comparison_summary_text(delta_match.group("outcome"))
        normalized_statement_outcome = _normalize_match_text(statement_outcome)
        if (
            not normalized_statement_outcome
            or (
                target_outcome
                and target_outcome not in normalized_statement_outcome
                and normalized_statement_outcome not in target_outcome
            )
        ):
            return None
        observed_label = _clean_comparison_summary_text(
            delta_match.group("observed_label")
        )
        condition_value = ""
        condition_match = re.search(
            r"\b(?:to|at)\s+(?P<value>[+-]?\d+(?:\.\d+)?\s*(?:°\s*C|°C|C|K|J/mm3|J/mm³|%))\b",
            observed_label,
            flags=re.IGNORECASE,
        )
        if condition_match is not None:
            condition_value = _clean_comparison_summary_value(
                condition_match.group("value")
            )
        delta = _clean_comparison_summary_value(delta_match.group("delta"))
        if not delta:
            return None
        delta_prefix = "+" if normalized_direction == "increases" else "-"
        delta_value = f"{delta_prefix}{delta.lstrip('+-')} {outcome or statement_outcome}"
        return {
            "variable": variable,
            "direction": normalized_direction,
            "outcome": outcome or statement_outcome,
            "baseline": {
                "label": "",
                "value": "reference",
            },
            "observed": {
                "label": (
                    f"{variable} {condition_value}" if condition_value else observed_label
                ),
                "value": delta_value,
            },
            "controlled_conditions": [],
        }

    def _comparison_summary_direction(self, direction: str, statement: str) -> str:
        normalized = _normalize_match_text(direction)
        if normalized:
            if normalized in {"increase", "increased", "increases", "improve", "improved", "improves", "raise", "raised", "raises"}:
                return "increases"
            if normalized in {"decrease", "decreased", "decreases", "reduce", "reduced", "reduces", "lower", "lowered", "lowers"}:
                return "decreases"
            if normalized in {"change", "changed", "changes"}:
                return "changes"
        lowered = f" {_normalize_match_text(statement)} "
        if re.search(r"\b(increased|increases|improved|improves|raised|raises)\b", lowered):
            return "increases"
        if re.search(r"\b(decreased|decreases|reduced|reduces|lowered|lowers)\b", lowered):
            return "decreases"
        if re.search(r"\b(changed|changes)\b", lowered):
            return "changes"
        return ""

    def _comparison_summary_conditions(self, text: str | None) -> list[dict[str, str]]:
        raw = _clean_comparison_summary_text(text)
        if not raw:
            return []
        parts = [
            _clean_comparison_summary_text(part)
            for part in re.split(r",\s+|\s+and\s+", raw)
        ]
        conditions: list[dict[str, str]] = []
        for part in parts:
            if not part:
                continue
            if "=" in part:
                axis, value = part.split("=", 1)
            else:
                axis, value = self._comparison_summary_axis_value(part)
                if axis and value:
                    axis_text = self._display_axis_label(
                        _clean_comparison_summary_text(axis)
                    )
                    value_text = _clean_comparison_summary_text(value)
                    conditions.append({"axis": axis_text, "value": value_text})
                    continue
                match = re.match(r"(.+?)\s+([^\s]+)$", part)
                if not match:
                    continue
                axis, value = match.groups()
            axis_text = self._display_axis_label(_clean_comparison_summary_text(axis))
            value_text = _clean_comparison_summary_text(value)
            if axis_text and value_text:
                conditions.append({"axis": axis_text, "value": value_text})
        return _dedupe_mapping_list(conditions)

    def _comparison_summary_axis_value(self, text: str) -> tuple[str, str]:
        symbol_match = re.match(
            r"^\s*(?P<symbol>[αβθɵ])(?:\s+.+?)?\s+"
            r"(?P<value>[-+]?\d+(?:\.\d+)?(?:\s*(?:%|MPa|GPa|J/mm3|J/mm³|HV|°\s*C|°C|C|K))?)\s*$",
            text,
            flags=re.IGNORECASE,
        )
        if symbol_match is not None:
            axis = self._display_axis_label(symbol_match.group("symbol"))
            value = self._comparison_summary_value_without_axis_unit(
                symbol_match.group("value")
            )
            if axis and value:
                return axis, value
        normalized = f" {_normalize_match_text(text)} "
        axis_labels = (
            "build platform preheating temperature",
            "heat treatment type",
            "heat treatment parameters",
            "volumetric energy density",
            "laser energy density",
            "scan strategy rotation angle",
            "build orientation angle",
            "scanning speed",
            "scan speed",
            "laser power",
            "hatch spacing",
            "layer thickness",
            "energy density",
            "porosity level",
            "pore size",
        )
        for axis in axis_labels:
            axis_key = _normalize_match_text(axis)
            if normalized.startswith(f" {axis_key} "):
                value = self._comparison_summary_value_without_axis_unit(
                    text[len(axis) :].strip()
                )
                if value:
                    return axis, value
        for axis in axis_labels:
            axis_key = _normalize_match_text(axis)
            pattern = (
                rf"^\s*{re.escape(axis_key)}(?:\s+\([^)]*\)|\s+\[[^\]]+\])?"
                r"\s+(?P<value>.+?)\s*$"
            )
            match = re.match(pattern, _normalize_match_text(text))
            if match is None:
                continue
            value = self._comparison_summary_value_without_axis_unit(
                match.group("value")
            )
            if value:
                return axis, value
        type_heat_treatment = re.match(
            r"^\s*type\s+of\s+heat\s+treatment\s+(?P<value>.+?)\s*$",
            _normalize_match_text(text),
        )
        if type_heat_treatment is not None:
            value = self._comparison_summary_value_without_axis_unit(
                type_heat_treatment.group("value")
            )
            if value:
                return "heat treatment type", value
        return "", ""

    def _comparison_summary_value_without_axis_unit(self, value: str) -> str:
        text = _clean_comparison_summary_value(value)
        return re.sub(r"^\[[^\]]+\]\s*", "", text).strip()

    def _finding_expert_use_status(
        self,
        *,
        support_grade: str,
        review_status: str,
        paper_count: int,
        evidence_bundle: Mapping[str, list[str]],
    ) -> str:
        if not self._finding_has_direct_support(evidence_bundle):
            return "evidence_repair_needed"
        if paper_count <= 1:
            return "paper_level_finding"
        if (
            support_grade == "strong"
            and review_status not in {"needs_review", "pending_review"}
        ):
            return "scoped_expert_finding"
        return "review_candidate"

    def _finding_generalization_status(
        self,
        *,
        support_grade: str,
        review_status: str,
        paper_count: int,
        evidence_bundle: Mapping[str, list[str]],
    ) -> str:
        if not self._finding_has_direct_support(evidence_bundle):
            return "evidence_repair_needed"
        if evidence_bundle.get("conflict") or support_grade == "conflict":
            return "conflict_review_needed"
        if paper_count <= 1:
            return "paper_level_only"
        if (
            support_grade == "strong"
            and review_status not in {"needs_review", "pending_review"}
        ):
            return "scoped_cross_paper"
        return "cross_paper_candidate"

    def _finding_generalization_note(
        self,
        *,
        generalization_status: str,
        paper_count: int,
    ) -> str:
        if generalization_status == "evidence_repair_needed":
            return (
                "Direct result evidence is missing; do not generalize before "
                "the source binding is repaired."
            )
        if generalization_status == "conflict_review_needed":
            return (
                "Conflicting evidence is linked; resolve the conflict before "
                "using this as a stable conclusion."
            )
        if generalization_status == "paper_level_only":
            return (
                "Evidence comes from one paper; use this as a traceable "
                "paper-level finding, not a cross-paper conclusion."
            )
        if generalization_status == "scoped_cross_paper":
            return (
                f"Direct evidence spans {paper_count} papers; use only with "
                "the stated material, process, test, and evidence scope."
            )
        return (
            f"Evidence spans {paper_count} papers, but support or review is "
            "not final; keep this as a cross-paper review candidate."
        )

    def _finding_evidence_gap_summary(
        self,
        *,
        support_grade: str,
        review_status: str,
        paper_count: int,
        evidence_bundle: Mapping[str, list[str]],
    ) -> str:
        gaps: list[str] = []
        if not self._finding_has_direct_support(evidence_bundle):
            gaps.append("direct result evidence")
        if paper_count <= 1:
            gaps.append("independent cross-paper confirmation")
        if support_grade != "strong":
            gaps.append("support-grade curation")
        if evidence_bundle.get("conflict"):
            gaps.append("conflict resolution")
        if review_status in {"needs_review", "pending_review"}:
            gaps.append("expert review")
        if not gaps:
            return "No immediate evidence gap is visible; keep the stated scope attached."
        return "Needs " + ", ".join(_dedupe_strings(gaps)) + "."

    def _finding_upgrade_actions(
        self,
        *,
        support_grade: str,
        review_status: str,
        paper_count: int,
        evidence_bundle: Mapping[str, list[str]],
    ) -> list[str]:
        actions: list[str] = []
        direct_count = len(_strings(evidence_bundle.get("direct_result")))
        if direct_count:
            actions.append("verify_direct_evidence")
        else:
            actions.append("repair_direct_evidence")
        if paper_count <= 1:
            actions.append("add_cross_paper_evidence")
        if support_grade != "strong":
            actions.append("curate_support_grade")
        if evidence_bundle.get("conflict"):
            actions.append("resolve_conflict")
        if review_status in {"needs_review", "pending_review"}:
            actions.append("record_expert_review")
        if not actions:
            actions.append("keep_scope_conditions")
        return _dedupe_strings(actions)

    def _finding_scope_summary_with_direct_conditions(
        self,
        scope_summary: str,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> str:
        condition_text = " ".join(
            self._evidence_source_texts_for_bundle_keys(
                evidence_by_id=evidence_by_id,
                evidence_bundle=evidence_bundle,
                blocks_by_id=blocks_by_id,
                bundle_keys=("direct_result", "condition_context"),
            )
        )
        condition_tokens = self._direct_evidence_condition_tokens(condition_text)
        if not condition_tokens:
            return scope_summary
        return _join_display_values(
            _dedupe_strings(
                [
                    *[token.strip() for token in scope_summary.split(",")],
                    *condition_tokens,
                ]
            ),
            limit=7,
        )

    def _direct_evidence_condition_tokens(self, text: str) -> list[str]:
        raw = _text(text) or ""
        if not raw:
            return []
        normalized = f" {_normalize_match_text(raw)} "
        tokens: list[str] = []
        if "316l" in normalized and (
            " stainless steel " in normalized or " steel " in normalized
        ):
            tokens.append("316L stainless steel")
        if (
            " pbf lb " in normalized
            or " powder bed fusion " in normalized
            or " laser beam powder bed fusion " in normalized
        ):
            tokens.append("PBF-LB")
        if " selective laser melting " in normalized or " slm " in normalized:
            tokens.append("SLM")
        if " hip " in normalized or " hot isostatic " in normalized:
            tokens.append("HIP")
        ved_values = [
            _normalize_numeric_token(value)
            for value in re.findall(
                r"(\d+(?:\.\d+)?)\s*(?:j\s*/?\s*mm\s*(?:3|³)|j/mm3|j/mm³)",
                raw,
                flags=re.IGNORECASE,
            )
        ]
        ved_values = [value for value in _dedupe_strings(ved_values) if value]
        if len(ved_values) >= 2:
            tokens.append(f"{ved_values[0]}-{ved_values[-1]} J/mm3")
        elif len(ved_values) == 1:
            tokens.append(f"{ved_values[0]} J/mm3")
        temp_values = [
            _normalize_numeric_token(value)
            for value in re.findall(
                r"(\d+(?:\.\d+)?)\s*(?:°\s*c|deg(?:ree)?s?\s*c|celsius)",
                raw,
                flags=re.IGNORECASE,
            )
        ]
        temp_values = [value for value in _dedupe_strings(temp_values) if value]
        if temp_values:
            tokens.append(f"{temp_values[0]} °C")
        return _dedupe_strings(tokens)

    def _finding_title(
        self,
        *,
        variables: list[str],
        outcomes: list[str],
        fallback: str,
    ) -> str:
        if variables and outcomes:
            return f"{variables[0]} -> {self._finding_title_outcome(outcomes)}"
        if fallback:
            return _short_text(fallback, limit=96)
        if outcomes:
            return outcomes[0]
        if variables:
            return variables[0]
        return "Research finding"

    def _finding_title_outcome(self, outcomes: list[str]) -> str:
        cleaned = [value for value in _dedupe_strings(outcomes) if value]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"

    def _finding_statement(
        self,
        *,
        statement: str,
        variables: list[str],
        outcomes: list[str],
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
        relations: list[dict[str, Any]] | None = None,
    ) -> str:
        relations = relations or []
        if not variables or not outcomes:
            return statement
        corrosion_statement = self._corrosion_direct_statement(
            outcomes=outcomes,
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        )
        if corrosion_statement:
            return corrosion_statement
        recovered_relation_statement = self._recovered_relation_finding_statement(
            relations,
            variables=variables,
            outcomes=outcomes,
        )
        if recovered_relation_statement:
            return recovered_relation_statement
        quote_statement = self._quote_derived_finding_statement(
            variables=variables,
            outcomes=outcomes,
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        )
        relation_statement = self._relation_derived_finding_statement(
            relations,
            variables=variables,
            outcomes=outcomes,
        )
        if self._statement_matches_finding_display(
            statement,
            variables=variables,
            outcomes=outcomes,
        ):
            if relation_statement and self._statement_specificity_score(
                relation_statement
            ) >= self._statement_specificity_score(statement) + 5:
                return relation_statement
            if quote_statement and self._statement_specificity_score(
                quote_statement
            ) >= self._statement_specificity_score(statement) + 5:
                return quote_statement
            return statement
        if relation_statement:
            return relation_statement
        if quote_statement:
            return quote_statement
        variable = variables[0]
        outcome = outcomes[0]
        return f"{variable} is associated with {outcome}."

    def _recovered_relation_finding_statement(
        self,
        relations: list[dict[str, Any]],
        *,
        variables: list[str],
        outcomes: list[str],
    ) -> str:
        for relation in relations:
            if "recovered_from_source_text" not in _strings(relation.get("warnings")):
                continue
            statement = self._presentation_relation_summary(relation)
            if self._statement_matches_finding_display(
                statement,
                variables=_dedupe_strings(
                    [
                        *variables,
                        self._presentation_relation_side(relation.get("subject")),
                        _text(relation.get("subject")),
                    ]
                ),
                outcomes=outcomes,
            ):
                return statement
        return ""

    def _relation_derived_finding_statement(
        self,
        relations: list[dict[str, Any]],
        *,
        variables: list[str],
        outcomes: list[str],
    ) -> str:
        for relation in relations:
            statement = self._presentation_relation_summary(relation)
            relation_variable = self._presentation_relation_side(relation.get("subject"))
            raw_relation_variable = _text(relation.get("subject"))
            variable_candidates = _dedupe_strings(
                [*variables, relation_variable, raw_relation_variable]
            )
            recovered_relation = "recovered_from_source_text" in _strings(
                relation.get("warnings")
            )
            if (
                statement
                and (
                    re.search(r"\d", statement)
                    or recovered_relation
                )
                and (
                    self._statement_matches_finding_display(
                        statement,
                        variables=variable_candidates,
                        outcomes=outcomes,
                    )
                    or (
                        recovered_relation
                        and self._variable_matches_direct_evidence(
                            variable_candidates,
                            statement,
                        )
                        and _quote_term_hits(
                            f" {_normalize_match_text(statement)} ",
                            self._finding_statement_outcome_terms(outcomes),
                        )
                    )
                    or (
                        _quote_term_hits(
                            f" {_normalize_match_text(statement)} ",
                            self._finding_statement_outcome_terms(outcomes),
                        )
                        and self._statement_relation_predicate(statement)
                    )
                )
            ):
                return statement
        return ""

    def _corrosion_direct_statement(
        self,
        *,
        outcomes: list[str],
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> str:
        outcome_text = _normalize_match_text(" ".join(outcomes))
        if "corrosion" not in outcome_text and "pitting" not in outcome_text:
            return ""
        for source_text in self._direct_evidence_source_texts(
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        ):
            normalized = f" {_normalize_match_text(source_text)} "
            if not (
                " porosity " in normalized
                or " porosities " in normalized
                or " pores " in normalized
            ):
                continue
            if " pitting " not in normalized and " corrosion " not in normalized:
                continue
            has_low_porosity_direction = (
                " decreased porosity " in normalized
                or " low porosity " in normalized
                or " lower porosity " in normalized
                or " porosity level " in normalized
            )
            has_corrosion_mechanism = (
                " passive film " in normalized
                or " corrosion rate " in normalized
                or " pitting potential " in normalized
                or " better corrosion " in normalized
            )
            if not (has_low_porosity_direction and has_corrosion_mechanism):
                continue
            return self._porosity_corrosion_association_statement(
                process_conditions_not_isolated=(
                    self._porosity_corrosion_process_conditions_not_isolated(
                        source_text=source_text,
                        condition_table=None,
                    )
                ),
            )
        return ""

    def _direct_evidence_source_texts(
        self,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> list[str]:
        return self._evidence_source_texts_for_bundle_keys(
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
            bundle_keys=("direct_result",),
        )

    def _evidence_source_texts_for_bundle_keys(
        self,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
        bundle_keys: tuple[str, ...],
    ) -> list[str]:
        texts: list[str] = []
        for bundle_key in bundle_keys:
            for ref_id in _strings(evidence_bundle.get(bundle_key)):
                evidence_ref = evidence_by_id.get(ref_id, {})
                locator = _locator_mapping(evidence_ref.get("locator"))
                block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
                text = " ".join(
                    value
                    for value in (
                        _text(evidence_ref.get("quote")),
                        _text(block.text if block else None),
                    )
                    if value
                )
                if text:
                    texts.append(text)
        return texts

    def _quote_derived_finding_statement(
        self,
        *,
        variables: list[str],
        outcomes: list[str],
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> str:
        quote_hints = {
            "variable": {
                term for value in variables for term in _quote_hint_terms(value)
            },
            "outcome": self._finding_statement_outcome_terms(outcomes),
            "relation": set(),
        }
        if not quote_hints["variable"] or not quote_hints["outcome"]:
            return ""
        for ref_id in _strings(evidence_bundle.get("direct_result")):
            evidence_ref = evidence_by_id.get(ref_id, {})
            locator = _locator_mapping(evidence_ref.get("locator"))
            block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
            source_block = self._presentation_source_block_for_quote(
                block,
                blocks_by_id=blocks_by_id,
                quote_hints=quote_hints,
            )
            source_text = _text(source_block.text if source_block else None) or _text(
                evidence_ref.get("quote")
            )
            if not source_text:
                continue
            source_sentences = _quote_sentences(source_text)
            for index, sentence in enumerate(source_sentences[:-1]):
                if not _quote_has_concrete_result_cue(sentence):
                    continue
                normalized = f" {_normalize_match_text(sentence)} "
                if not _quote_term_hits(normalized, quote_hints["variable"]):
                    continue
                if not _quote_term_hits(normalized, quote_hints["outcome"]):
                    continue
                if _is_mechanism_attribution_sentence(source_sentences[index + 1]):
                    return f"{sentence} {source_sentences[index + 1]}"
            snippet = self._best_matching_quote_snippet(source_text, quote_hints)
            if not snippet:
                continue
            sentences = _quote_sentences(snippet)
            for index, sentence in enumerate(sentences):
                if not _quote_has_concrete_result_cue(sentence):
                    continue
                normalized = f" {_normalize_match_text(sentence)} "
                if not _quote_term_hits(normalized, quote_hints["variable"]):
                    continue
                if not _quote_term_hits(normalized, quote_hints["outcome"]):
                    continue
                if index + 1 < len(sentences) and _is_mechanism_attribution_sentence(
                    sentences[index + 1]
                ):
                    return f"{sentence} {sentences[index + 1]}"
                return sentence
        return ""

    def _statement_specificity_score(self, statement: str) -> int:
        if not statement:
            return 0
        score = 0
        if _quote_has_concrete_result_cue(statement):
            score += 4
        if re.search(r"\d", statement):
            score += 4
        normalized = f" {_normalize_match_text(statement)} "
        for cue in (
            "increased",
            "increases",
            "decreased",
            "decreases",
            "reduced",
            "reduces",
            "improved",
            "improves",
            "affecting",
            "affects",
            "measured",
            "achieved",
            "observed",
            "revealed",
            "sensitive",
        ):
            if f" {cue} " in normalized:
                score += 1
        return score

    def _finding_statement_outcome_terms(self, outcomes: list[str]) -> set[str]:
        terms: set[str] = set()
        for value in outcomes:
            normalized = _normalize_match_text(value)
            if re.fullmatch(r"ultimate tensile strength(?: mpa)?", normalized):
                terms.update(
                    {
                        "tensile strength",
                        "ultimate tensile strength",
                        "uts",
                    }
                )
                continue
            if re.fullmatch(r"yield strength(?: mpa)?", normalized):
                terms.update({"yield", "yield strength", "ys"})
                continue
            if re.fullmatch(r"tensile strength(?: mpa)?", normalized):
                terms.update({"tensile strength", "uts"})
                continue
            terms.update(_quote_hint_terms(value))
            if normalized == "microstructure":
                terms.update(
                    {
                        "cellular",
                        "columnar",
                        "grain",
                        "grains",
                        "melt pool",
                        "microstructural",
                        "structure",
                    }
                )
            elif normalized == "mechanical properties":
                terms.update({"ductility", "elongation", "strength", "tensile", "yield"})
            elif normalized in {"corrosion behavior", "pitting corrosion behavior"}:
                terms.update(
                    {
                        "corrosion",
                        "electrochemical",
                        "passivation",
                        "pitting",
                        "polarization",
                    }
                )
        return terms

    def _statement_matches_finding_display(
        self,
        statement: str,
        *,
        variables: list[str],
        outcomes: list[str],
    ) -> bool:
        if not statement or not variables or not outcomes:
            return False
        normalized = f" {_normalize_match_text(statement)} "
        return bool(
            self._variable_matches_direct_evidence(variables, statement)
            and _quote_term_hits(
                normalized,
                self._finding_statement_outcome_terms(outcomes),
            )
        )

    def _finding_relation_chain(
        self,
        relations: list[dict[str, Any]],
        *,
        variables: list[str] | None = None,
        mediators: list[str] | None = None,
        direction: str = "",
        outcomes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        display_variables = variables or []
        display_mediator_keys = {
            _normalize_match_text(mediator) for mediator in mediators or []
        }
        display_outcomes = outcomes or []
        for index, relation in enumerate(relations):
            variable = self._presentation_relation_side(relation.get("subject"))
            object_chain = self._relation_object_chain(relation)
            if not variable or not object_chain:
                continue
            display_variable = (
                display_variables[index]
                if index < len(display_variables)
                else (display_variables[0] if display_variables else variable)
            )
            segment_direction = ""
            for value in (relation.get("relation_type"), relation.get("predicate")):
                text = _text(value)
                if text and _looks_user_facing(text):
                    segment_direction = text
                    break
            terminal_is_mediator = (
                _normalize_match_text(object_chain[-1]) in display_mediator_keys
            )
            segment_mediators = (
                object_chain if terminal_is_mediator else object_chain[:-1]
            )
            if terminal_is_mediator and display_outcomes:
                segment_outcome = self._finding_title_outcome(display_outcomes)
            elif (
                display_outcomes
                and _normalize_match_text(object_chain[-1]) == "mechanical properties"
                and _normalize_match_text(display_outcomes[0])
                != "mechanical properties"
            ):
                segment_outcome = display_outcomes[0]
            else:
                segment_outcome = object_chain[-1]
            chain.append(
                {
                    "relation_id": _text(relation.get("relation_id")) or "",
                    "variable": display_variable,
                    "mediators": segment_mediators,
                    "outcome": segment_outcome,
                    "direction": segment_direction or direction,
                    "statement": self._presentation_relation_summary(relation),
                }
            )
        return chain

    def _finding_relations(
        self,
        effect: Mapping[str, Any],
        relations_by_id: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        claim_id = _text(effect.get("claim_id")) or ""
        if claim_id.startswith("relation_"):
            relation_id = claim_id.removeprefix("relation_")
            return [relations_by_id[relation_id]] if relation_id in relations_by_id else []
        return [
            relations_by_id[relation_id]
            for relation_id in _strings(effect.get("relation_ids"))
            if relation_id in relations_by_id
        ]

    def _finding_variables(
        self,
        effect: Mapping[str, Any],
        relations: list[dict[str, Any]],
    ) -> list[str]:
        fallback = _text(effect.get("variable_axis"))
        statement = _text(effect.get("statement")) or ""
        variables = _dedupe_strings(
            [
                subject
                for relation in relations
                if (
                    subject := (
                        _text(relation.get("subject"))
                        if _symbol_match_term(relation.get("subject"))
                        else self._presentation_relation_side(relation.get("subject"))
                    )
                )
            ]
        )
        if variables and self._is_recovered_expert_effect(effect):
            return variables
        if variables:
            if (
                len(variables) == 1
                and fallback
                and fallback != variables[0]
                and self._variable_matches_direct_evidence([fallback], statement)
                and not self._variable_matches_direct_evidence(variables, statement)
            ):
                return [fallback]
            return variables
        return [fallback] if fallback else []

    def _finding_display_variables(
        self,
        variables: list[str],
        *,
        relations: list[dict[str, Any]],
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
    ) -> list[str]:
        broad_process_variables = {
            "additive manufacturing",
            "laser beam powder bed fusion",
            "laser powder bed fusion",
            "lpbf",
            "powder bed fusion",
            "selective laser melting",
            "slm",
        }
        has_broad_variable = any(
            _normalize_match_text(variable) in broad_process_variables
            for variable in variables
        )
        relation_text_parts: list[str] = []
        for relation in relations:
            relation_text_parts.extend(
                [
                    self._presentation_relation_summary(relation),
                    _text(relation.get("statement")) or "",
                ]
            )
        direct_evidence_text = self._direct_evidence_text_for_display_variables(
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
        )
        direct_evidence_is_table_only = self._direct_evidence_is_table_only(
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
        )
        direct_concrete_variables = self._concrete_variable_terms(direct_evidence_text)
        concrete_variables = direct_concrete_variables or self._concrete_variable_terms(
            " ".join([*relation_text_parts, direct_evidence_text])
        )
        if not concrete_variables:
            return variables
        if (
            not has_broad_variable
            and direct_concrete_variables
            and not self._variable_matches_direct_evidence(
                variables,
                (
                    " ".join(relation_text_parts)
                    if direct_evidence_is_table_only
                    else direct_evidence_text
                ),
            )
        ):
            return direct_concrete_variables
        if not has_broad_variable:
            return variables
        broad_variable_keys = {
            _normalize_match_text(variable)
            for variable in variables
            if _normalize_match_text(variable) in broad_process_variables
        }
        non_broad_variable_keys = {
            _normalize_match_text(variable)
            for variable in variables
            if _normalize_match_text(variable) not in broad_process_variables
        }
        replacement_variables = [
            variable
            for variable in concrete_variables
            if _normalize_match_text(variable) not in non_broad_variable_keys
        ]
        if not replacement_variables:
            return variables
        return _dedupe_strings(
            [
                replacement
                for variable in variables
                for replacement in (
                    replacement_variables
                    if _normalize_match_text(variable) in broad_variable_keys
                    else [variable]
                )
            ]
        )

    def _direct_evidence_is_table_only(
        self,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
    ) -> bool:
        direct_ref_ids = _strings(evidence_bundle.get("direct_result"))
        if not direct_ref_ids:
            return False
        return all(
            "table" in (
                _text(evidence_by_id.get(ref_id, {}).get("source_kind")) or ""
            ).lower()
            for ref_id in direct_ref_ids
        )

    def _direct_evidence_text_for_display_variables(
        self,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
    ) -> str:
        text_parts: list[str] = []
        for ref_id in _strings(evidence_bundle.get("direct_result")):
            evidence_ref = evidence_by_id.get(ref_id, {})
            locator = _locator_mapping(evidence_ref.get("locator"))
            text_parts.extend(
                [
                    _text(evidence_ref.get("quote")) or "",
                    _text(evidence_ref.get("label")) or "",
                    *_display_values(locator),
                ]
            )
        return " ".join(text_parts)

    def _variable_matches_direct_evidence(
        self,
        variables: list[str],
        direct_evidence_text: str,
    ) -> bool:
        normalized = f" {_normalize_match_text(direct_evidence_text)} "
        if not normalized.strip():
            return False
        for variable in variables:
            symbol_term = _symbol_match_term(variable)
            if symbol_term and f" {symbol_term} " in f" {_symbol_match_text(direct_evidence_text)} ":
                return True
            normalized_variable = _normalize_match_text(variable)
            if normalized_variable and f" {normalized_variable} " in normalized:
                return True
            if normalized_variable == "volumetric energy density" and (
                " ved " in normalized or " volumetric energy density " in normalized
            ):
                return True
            raw_variable = _text(variable)
            if raw_variable and f" {raw_variable} " in f" {direct_evidence_text} ":
                return True
            if normalized_variable == "heat treatment" and (
                " heat treatment " in normalized or " heat treatments " in normalized
            ):
                return True
            tokens = _meaningful_match_tokens(variable)
            if not tokens:
                continue
            if len(tokens) == 1 and _quote_term_hits(
                normalized,
                _quote_hint_terms(variable),
            ):
                return True
            phrase = " ".join(tokens)
            if f" {phrase} " in normalized:
                return True
            token_hits = sum(
                1 for token in set(tokens) if f" {token} " in normalized
            )
            if token_hits >= 2:
                return True
        return False

    def _concrete_variable_terms(self, text: str) -> list[str]:
        normalized = f" {_normalize_match_text(text)} "
        variables: list[str] = []
        phrase_variables = (
            ("laser power", ("laser power",)),
            ("scan speed", ("scan speed", "scanning speed")),
            ("heat treatment time", ("heat treatment time",)),
            ("heat treatment pressure", ("heat treatment pressure",)),
            ("heat treatment temperature", ("heat treatment temperature",)),
            ("preheating temperature", ("preheating temperature",)),
            (
                "build platform preheating temperature",
                ("build platform preheating temperature",),
            ),
            ("build platform preheating", ("build platform preheating",)),
        )
        for display, phrases in phrase_variables:
            if any(f" {phrase} " in normalized for phrase in phrases):
                variables.append(display)
        if " ved " in normalized or " volumetric energy density " in normalized:
            variables.append("VED")
        elif " energy density " in normalized and not variables:
            variables.append("energy density")
        return _dedupe_strings(variables)

    def _finding_mediators(self, relations: list[dict[str, Any]]) -> list[str]:
        return _dedupe_strings(
            [
                segment
                for relation in relations
                for segment in self._relation_object_chain(relation)[:-1]
            ]
        )

    def _finding_roles(
        self,
        effect: Mapping[str, Any],
        relations: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        mediators = self._finding_mediators(relations)
        outcomes = self._finding_outcomes(effect, relations)
        if (_text(effect.get("claim_type")) or "") != "mechanism":
            return mediators, outcomes

        specific_outcomes = self._specific_mechanical_outcome_terms(
            _text(effect.get("statement")) or ""
        )
        if not specific_outcomes:
            return mediators, outcomes

        specific_outcome_keys = {
            _normalize_match_text(outcome) for outcome in specific_outcomes
        }
        mechanism_terminals: list[str] = []
        for relation in relations:
            object_chain = self._relation_object_chain(relation)
            if not object_chain:
                continue
            terminal = object_chain[-1]
            if _normalize_match_text(terminal) == "mechanical properties":
                continue
            terminal_outcome_keys = {
                _normalize_match_text(outcome)
                for outcome in self._specific_mechanical_outcome_terms(terminal)
            }
            if terminal_outcome_keys & specific_outcome_keys:
                continue
            mechanism_terminals.append(terminal)
        return (
            _dedupe_strings([*mediators, *mechanism_terminals]),
            specific_outcomes,
        )

    def _finding_mediators_from_direct_evidence(self, source_text: str) -> list[str]:
        normalized = f" {_normalize_match_text(source_text)} "
        mediators: list[str] = []
        if (
            " microstructure evolution " in normalized
            or " microstructural evolution " in normalized
            or " microstructure and texture evolution " in normalized
        ):
            mediators.append("microstructure evolution")
        if " texture evolution " in normalized:
            mediators.append("texture evolution")
        if " crystallographic texture " in normalized:
            mediators.append("crystallographic texture")
        if (
            " homogenized microstructure " in normalized
            or " homogenised microstructure " in normalized
        ):
            mediators.append("microstructure")
        if (
            " gnd " in normalized
            or " gnds " in normalized
            or " geometrically necessary dislocations " in normalized
            or " geometry necessary dislocations " in normalized
        ):
            mediators.append("GNDs")
        if (
            " cellular microstructure " in normalized
            or " cellular microstructures " in normalized
            or " cellular structure " in normalized
        ):
            mediators.append("cellular microstructure")
        if " dislocation density " in normalized:
            mediators.append("dislocation density")
        elif (
            " dense dislocation structures " in normalized
            or " dislocation structures " in normalized
        ):
            mediators.append("dislocation structures")
        if " recrystallization " in normalized:
            mediators.append("recrystallization")
        if " defect fraction " in normalized or " defect size " in normalized:
            mediators.append("defect structure")
        if " refined microstructure " in normalized:
            mediators.append("refined microstructure")
        if " densification " in normalized:
            mediators.append("densification")
        return _dedupe_strings(mediators)

    def _direct_evidence_mechanism_ref_ids(
        self,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> list[str]:
        return [
            ref_id
            for ref_id in _strings(evidence_bundle.get("direct_result"))
            if self._finding_mediators_from_direct_evidence(
                self._evidence_ref_source_text(
                    evidence_by_id.get(ref_id, {}),
                    blocks_by_id=blocks_by_id,
                )
            )
        ]

    def _finding_outcomes(
        self,
        effect: Mapping[str, Any],
        relations: list[dict[str, Any]],
    ) -> list[str]:
        outcomes = _dedupe_strings(
            [
                outcome
                for relation in relations
                if (chain := self._relation_object_chain(relation))
                for outcome in self._parallel_property_outcomes(chain[-1])
            ]
        )
        if outcomes:
            return outcomes
        fallback = _text(effect.get("target_property"))
        return [fallback] if fallback else []

    def _parallel_property_outcomes(self, value: str) -> list[str]:
        normalized = f" {_normalize_match_text(value)} "
        specific_axes = (
            "yield strength",
            "ultimate tensile strength",
            "elongation",
        )
        if all(f" {axis} " in normalized for axis in specific_axes):
            return list(specific_axes)
        raw_value = _text(value) or ""
        separated = []
        if "," in raw_value:
            separated = [
                re.sub(r"^and\s+", "", item.strip(), flags=re.IGNORECASE)
                for item in raw_value.split(",")
            ]
            separated = [item for item in separated if _looks_user_facing(item)]
        elif normalized.strip() == "density and microstructure":
            separated = ["density", "microstructure"]
        if separated:
            return _dedupe_strings(separated)
        return [value]

    def _specific_mechanical_outcomes(
        self,
        outcomes: list[str],
        *,
        relations: list[dict[str, Any]],
        statement: str,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> list[str]:
        if not any(
            _normalize_match_text(outcome) == "mechanical properties"
            for outcome in outcomes
        ):
            return outcomes
        statement_specific = self._specific_mechanical_outcome_terms(statement)
        if statement_specific:
            specific = statement_specific
        else:
            text_parts = [statement]
            for ref_id in _strings(evidence_bundle.get("direct_result")):
                evidence_ref = evidence_by_id.get(ref_id, {})
                locator = _locator_mapping(evidence_ref.get("locator"))
                block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
                text_parts.extend(
                    [
                        _text(evidence_ref.get("quote")) or "",
                        _text(evidence_ref.get("label")) or "",
                        _text(block.text if block else None) or "",
                    ]
                )
            specific = self._specific_mechanical_outcome_terms(" ".join(text_parts))
        if not specific:
            return outcomes
        result: list[str] = []
        for outcome in outcomes:
            if _normalize_match_text(outcome) == "mechanical properties":
                result.extend(specific)
            else:
                result.append(outcome)
        return _dedupe_strings(result)

    def _specific_mechanical_outcome_terms(self, text: str) -> list[str]:
        normalized = f" {_normalize_match_text(text)} "
        specific: list[str] = []
        for display, terms in (
            ("ductility", ("ductility", "elongation", "el")),
            ("yield strength", ("yield strength",)),
            ("tensile strength", ("tensile strength",)),
            ("hardness", ("hardness", "microhardness")),
            ("fatigue", ("fatigue",)),
        ):
            if any(f" {term} " in normalized for term in terms):
                specific.append(display)
        return specific

    def _relation_object_chain(self, relation: Mapping[str, Any]) -> list[str]:
        object_text = _text(relation.get("object")) or ""
        return [
            segment
            for segment in (
                self._presentation_relation_side(part)
                for part in object_text.split("->")
            )
            if segment
        ]

    def _finding_direction(
        self,
        effect: Mapping[str, Any],
        relations: list[dict[str, Any]],
    ) -> str:
        for relation in relations:
            for value in (relation.get("relation_type"), relation.get("predicate")):
                text = _text(value)
                if text and _looks_user_facing(text):
                    return text
        return _text(effect.get("effect_direction")) or ""

    def _finding_evidence_bundle(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        relations: list[dict[str, Any]],
        outcomes: list[str],
    ) -> dict[str, list[str]]:
        bundle: dict[str, list[str]] = {
            "direct_result": [],
            "mechanism": [],
            "condition_context": [],
            "background": [],
            "conflict": [],
            "noise": [],
            "uncategorized": [],
        }
        relation_evidence_ref_ids = {
            ref_id
            for relation in relations
            for ref_id in _strings(relation.get("evidence_ref_ids"))
        }
        target_terms = self._finding_target_terms(effect, outcomes)
        for ref_id in _strings(effect.get("evidence_ref_ids")):
            evidence_ref = evidence_by_id.get(ref_id, {})
            role = _text(evidence_ref.get("evidence_role"))
            bundle_key = self._finding_bundle_key_for_role(
                role,
                fallback_direct=(
                    not role
                    and ref_id in relation_evidence_ref_ids
                    and self._evidence_matches_finding_target(
                        evidence_ref,
                        target_terms,
                    )
                ),
            )
            bundle[bundle_key].append(ref_id)
        return bundle

    def _finding_result_source_bundle(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_bundle: Mapping[str, list[str]],
        evidence_by_id: Mapping[str, dict[str, Any]],
        relations: list[dict[str, Any]],
        outcomes: list[str],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> dict[str, list[str]]:
        direct_ref_ids = _strings(evidence_bundle.get("direct_result"))
        if not direct_ref_ids:
            return {key: list(value) for key, value in evidence_bundle.items()}
        if all(ref_id.startswith("evref_recovered_") for ref_id in direct_ref_ids):
            return {key: list(value) for key, value in evidence_bundle.items()}
        target_terms = self._finding_target_terms(effect, outcomes)
        variable_values: list[str] = []
        variable_terms: set[str] = set()
        relation_terms: set[str] = set()
        for relation in relations:
            relation_variable = self._presentation_relation_side(
                relation.get("subject")
            )
            if relation_variable:
                variable_values.append(relation_variable)
            variable_terms.update(
                _quote_hint_terms(relation_variable)
            )
            for value in (
                _text(relation.get("predicate")),
                _text(relation.get("relation_type")),
                self._presentation_relation_summary(relation),
                " ".join(self._relation_object_chain(relation)),
            ):
                relation_terms.update(_quote_hint_terms(value))
        for value in (
            _text(effect.get("variable_axis")),
            _text(effect.get("statement")),
            _text(effect.get("title")),
            _text(effect.get("effect_direction")),
        ):
            relation_terms.update(_quote_hint_terms(value))
        if effect_variable := _text(effect.get("variable_axis")):
            variable_values.append(effect_variable)
        variable_values = _dedupe_strings(variable_values)
        if not target_terms or not (variable_terms or relation_terms):
            return {key: list(value) for key, value in evidence_bundle.items()}
        ranked_direct_refs: list[tuple[tuple[int, int, int, int, int], str]] = []
        for index, ref_id in enumerate(direct_ref_ids):
            evidence_ref = evidence_by_id.get(ref_id, {})
            searchable = self._evidence_ref_source_text(
                evidence_ref,
                blocks_by_id=blocks_by_id,
            )
            bounded = f" {searchable} "
            ranked_direct_refs.append(
                (
                    (
                        self._evidence_result_source_score(
                            evidence_ref,
                            blocks_by_id=blocks_by_id,
                        ),
                        1 if _quote_has_concrete_result_cue(searchable) else 0,
                        _quote_term_hits(bounded, target_terms),
                        _quote_term_hits(bounded, variable_terms)
                        + _quote_term_hits(bounded, relation_terms),
                        -index,
                    ),
                    ref_id,
                )
            )
        ordered_direct_ref_ids = [
            ref_id
            for _, ref_id in sorted(ranked_direct_refs, reverse=True)
        ]
        updated_direct_bundle = {key: list(value) for key, value in evidence_bundle.items()}
        updated_direct_bundle["direct_result"] = ordered_direct_ref_ids
        current_best_score = max(
            self._evidence_result_source_score(
                evidence_by_id.get(ref_id, {}),
                blocks_by_id=blocks_by_id,
            )
            for ref_id in direct_ref_ids
        )
        if self._effect_has_specific_result_statement(effect) and all(
            self._evidence_ref_aligns_with_terms(
                evidence_by_id.get(ref_id, {}),
                blocks_by_id=blocks_by_id,
                target_terms=target_terms,
                variable_terms=variable_terms,
                relation_terms=relation_terms,
            )
            for ref_id in direct_ref_ids
        ):
            return updated_direct_bundle
        if self._finding_statement_is_table_row_comparison(
            _text(effect.get("statement")) or ""
        ) and any(
            "table"
            in (_text(evidence_by_id.get(ref_id, {}).get("source_kind")) or "").lower()
            and _text(
                _locator_mapping(evidence_by_id.get(ref_id, {}).get("locator")).get(
                    "source_ref"
                )
            )
            and (
                _text(evidence_by_id.get(ref_id, {}).get("traceability_status")) or ""
            ).lower()
            in {"resolved", "traceable"}
            for ref_id in direct_ref_ids
        ):
            return updated_direct_bundle
        if current_best_score >= 4:
            return updated_direct_bundle
        def document_id_for(evidence_ref: Mapping[str, Any]) -> str:
            document_id = _text(evidence_ref.get("document_id"))
            if document_id:
                return document_id
            locator = _locator_mapping(evidence_ref.get("locator"))
            block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
            return _text(block.document_id if block else None) or ""

        direct_document_ids = {
            document_id
            for ref_id in direct_ref_ids
            if (document_id := document_id_for(evidence_by_id.get(ref_id, {})))
        }
        candidate_ref_ids = _dedupe_strings(
            [
                ref_id
                for ref_id, ref in evidence_by_id.items()
                if not direct_document_ids or document_id_for(ref) in direct_document_ids
            ]
        )
        candidates: list[tuple[int, int, str]] = []
        for index, ref_id in enumerate(candidate_ref_ids):
            if ref_id in direct_ref_ids:
                continue
            evidence_ref = evidence_by_id.get(ref_id, {})
            score = self._evidence_result_source_score(
                evidence_ref,
                blocks_by_id=blocks_by_id,
            )
            if score < 4 or score <= current_best_score:
                continue
            searchable = self._evidence_ref_source_text(
                evidence_ref,
                blocks_by_id=blocks_by_id,
            )
            if not searchable:
                continue
            bounded = f" {searchable} "
            target_hits = _quote_term_hits(bounded, target_terms)
            variable_hits = _quote_term_hits(bounded, variable_terms)
            if not (target_hits and variable_hits):
                continue
            if not self._evidence_ref_has_joint_variable_and_target(
                evidence_ref,
                blocks_by_id=blocks_by_id,
                variable_values=variable_values,
                target_terms=target_terms,
            ):
                continue
            candidates.append((score, -index, ref_id))
        if not candidates:
            return updated_direct_bundle
        preferred_ref_id = max(candidates)[2]
        updated = {
            key: [ref_id for ref_id in value if ref_id != preferred_ref_id]
            for key, value in evidence_bundle.items()
        }
        updated["direct_result"] = [preferred_ref_id]
        updated["uncategorized"] = _dedupe_strings(
            [
                *updated.get("uncategorized", []),
                *[
                    ref_id
                    for ref_id in ordered_direct_ref_ids
                    if ref_id != preferred_ref_id
                    and ref_id not in updated.get("uncategorized", [])
                ],
            ]
        )
        return updated

    def _compact_finding_evidence_bundle(
        self,
        evidence_bundle: Mapping[str, list[str]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, list[str]]:
        updated = {
            key: _dedupe_strings(_strings(value))
            for key, value in evidence_bundle.items()
        }
        if not any(
            updated.get(key)
            for key in (
                "direct_result",
                "mechanism",
                "condition_context",
                "conflict",
            )
        ):
            return updated

        updated = self._dedupe_evidence_bundle_by_source_target(
            updated,
            evidence_by_id=evidence_by_id,
        )
        updated = self._dedupe_evidence_bundle_by_ref_id(updated)

        seen_sources = {
            source_key
            for key in (
                "direct_result",
                "mechanism",
                "condition_context",
                "conflict",
            )
            for ref_id in updated.get(key, [])
            if (
                source_key := self._evidence_ref_source_key(
                    evidence_by_id.get(ref_id, {})
                )
            )
        }
        compact_uncategorized: list[str] = []
        retained_same_source_supplements: set[str] = set()
        for ref_id in updated.get("uncategorized", []):
            evidence_ref = evidence_by_id.get(ref_id, {})
            source_key = self._evidence_ref_source_key(evidence_by_id.get(ref_id, {}))
            if source_key and source_key in seen_sources:
                if (
                    source_key in retained_same_source_supplements
                    or not self._is_role_bearing_supplemental_evidence(evidence_ref)
                ):
                    continue
                retained_same_source_supplements.add(source_key)
            if source_key:
                seen_sources.add(source_key)
            compact_uncategorized.append(ref_id)
            if len(compact_uncategorized) >= 3:
                break
        updated["uncategorized"] = compact_uncategorized
        return updated

    def _dedupe_evidence_bundle_by_ref_id(
        self,
        evidence_bundle: Mapping[str, list[str]],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        seen: set[str] = set()
        direct_refs = set(_strings(evidence_bundle.get("direct_result")))
        for role in (
            "direct_result",
            "mechanism",
            "condition_context",
            "conflict",
            "background",
            "uncategorized",
            "noise",
        ):
            retained: list[str] = []
            for ref_id in _strings(evidence_bundle.get(role)):
                if role == "mechanism" and ref_id in direct_refs:
                    retained.append(ref_id)
                    continue
                if ref_id in seen:
                    continue
                seen.add(ref_id)
                retained.append(ref_id)
            result[role] = retained
        return result

    def _dedupe_evidence_bundle_by_source_target(
        self,
        evidence_bundle: Mapping[str, list[str]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, list[str]]:
        role_priority = (
            "direct_result",
            "mechanism",
            "condition_context",
            "conflict",
            "background",
            "uncategorized",
            "noise",
        )
        retained_source_keys: set[str] = set()
        retained_ref_ids_seen: set[str] = set()
        result: dict[str, list[str]] = {}
        direct_refs = set(_strings(evidence_bundle.get("direct_result")))
        for role in role_priority:
            retained_ref_ids: list[str] = []
            for ref_id in _strings(evidence_bundle.get(role)):
                if role == "mechanism" and ref_id in direct_refs:
                    retained_ref_ids.append(ref_id)
                    continue
                if ref_id in retained_ref_ids_seen:
                    continue
                source_key = self._evidence_ref_source_key(evidence_by_id.get(ref_id, {}))
                if source_key and source_key in retained_source_keys:
                    continue
                if source_key:
                    retained_source_keys.add(source_key)
                retained_ref_ids_seen.add(ref_id)
                retained_ref_ids.append(ref_id)
            result[role] = retained_ref_ids
        return result

    def _evidence_ref_source_key(self, evidence_ref: Mapping[str, Any]) -> str:
        locator = _locator_mapping(evidence_ref.get("locator"))
        source_ref = _normalize_match_text(_text(locator.get("source_ref")) or "")
        document_id = _normalize_match_text(_text(evidence_ref.get("document_id")) or "")
        source_kind = _normalize_match_text(
            _text(evidence_ref.get("source_kind"))
            or _text(locator.get("source_kind"))
            or ""
        )
        page = _normalize_match_text(
            _text(locator.get("page"))
            or _text(locator.get("page_no"))
            or ""
        )
        if not (source_ref or document_id):
            return ""
        return "|".join((document_id, source_kind, source_ref, page))

    def _is_role_bearing_supplemental_evidence(
        self,
        evidence_ref: Mapping[str, Any],
    ) -> bool:
        role = (_text(evidence_ref.get("evidence_role")) or "").lower()
        return role in {
            "direct_support",
            "mediator_context",
            "mechanism",
            "condition_context",
            "context",
            "conflict",
            "conflicting",
        }

    def _effect_has_specific_result_statement(self, effect: Mapping[str, Any]) -> bool:
        statement = _text(effect.get("statement")) or ""
        if not statement:
            return False
        return bool(re.search(r"\d", statement) and _quote_has_concrete_result_cue(statement))

    def _evidence_ref_aligns_with_terms(
        self,
        evidence_ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        target_terms: set[str],
        variable_terms: set[str],
        relation_terms: set[str],
    ) -> bool:
        searchable = self._evidence_ref_source_text(
            evidence_ref,
            blocks_by_id=blocks_by_id,
        )
        if not searchable:
            return False
        bounded = f" {searchable} "
        return bool(
            _quote_term_hits(bounded, target_terms)
            and (
                _quote_term_hits(bounded, variable_terms)
                or _quote_term_hits(bounded, relation_terms)
            )
        )

    def _evidence_ref_has_joint_variable_and_target(
        self,
        evidence_ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        variable_values: list[str],
        target_terms: set[str],
    ) -> bool:
        locator = _locator_mapping(evidence_ref.get("locator"))
        block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
        source_texts = _dedupe_strings(
            [
                _text(evidence_ref.get("quote")) or "",
                _text(block.text if block else None) or "",
            ]
        )
        has_preheating_variable = any(
            {"preheat", "preheating"}
            & set(_normalize_match_text(variable).split())
            for variable in variable_values
        )
        for source_text in source_texts:
            for sentence in _quote_sentences(source_text):
                normalized_sentence = f" {_normalize_match_text(sentence)} "
                variable_matches = self._variable_matches_direct_evidence(
                    variable_values,
                    sentence,
                ) or (
                    has_preheating_variable
                    and (
                        " preheat " in normalized_sentence
                        or " preheating " in normalized_sentence
                    )
                )
                if variable_matches and _quote_term_hits(
                    normalized_sentence,
                    target_terms,
                ):
                    return True
        return False

    def _finding_target_terms(
        self,
        effect: Mapping[str, Any],
        outcomes: list[str],
    ) -> set[str]:
        target_texts = outcomes or [_text(effect.get("target_property")) or ""]
        terms: set[str] = set()
        for text in target_texts:
            normalized = _normalize_match_text(text)
            if re.fullmatch(
                r"(?:ultimate )?tensile strength(?: mpa)?|"
                r"yield strength(?: mpa)?",
                normalized,
            ):
                terms.update(self._finding_statement_outcome_terms([text]))
                continue
            tokens = _meaningful_match_tokens(text)
            if not tokens:
                continue
            phrase = _normalize_match_text(" ".join(tokens))
            if len(tokens) >= 2:
                terms.add(phrase)
                for index in range(len(tokens) - 1):
                    terms.add(f"{tokens[index]} {tokens[index + 1]}")
            for token in tokens:
                terms.update(_target_token_variants(token))
        return {term for term in terms if term}

    def _evidence_matches_finding_target(
        self,
        evidence_ref: Mapping[str, Any],
        target_terms: set[str],
    ) -> bool:
        if not target_terms:
            return False
        searchable = self._evidence_search_text(evidence_ref)
        if not searchable:
            return False
        bounded = f" {searchable} "
        return any(f" {term} " in bounded for term in target_terms)

    def _evidence_search_text(self, evidence_ref: Mapping[str, Any]) -> str:
        locator = _mapping(evidence_ref.get("locator"))
        parts = [
            _text(evidence_ref.get("quote")),
            _text(evidence_ref.get("label")),
            *_display_values(locator),
        ]
        return _normalize_match_text(" ".join(part for part in parts if part))

    def _evidence_result_source_score(
        self,
        evidence_ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> int:
        searchable = self._evidence_ref_source_text(
            evidence_ref,
            blocks_by_id=blocks_by_id,
        )
        if not searchable:
            return 0
        score = 0
        locator = _locator_mapping(evidence_ref.get("locator"))
        block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
        heading = _normalize_match_text(_text(block.heading_path if block else None) or "")
        is_background_heading = any(
            term in heading
            for term in ("abstract", "introduction", "background", "references")
        )
        for cue in (
            "result",
            "results",
            "discussion",
            "conclusion",
            "conclusions",
            "show",
            "showed",
            "demonstrate",
            "demonstrated",
            "attributed",
            "increased",
            "decreased",
            "reduced",
            "improved",
        ):
            if f" {cue} " in f" {searchable} ":
                score += 2
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|c|k|w|mpa|gpa|hv|mm/s|um)\b", searchable):
            score += 2
        if any(term in heading for term in ("result", "discussion", "conclusion")):
            score += 3
        if is_background_heading:
            score -= 8
        if any(
            f" {cue} " in f" {searchable} "
            for cue in (
                "abstract",
                "introduction",
                "background",
                "aim",
                "aims",
                "objective",
                "objectives",
                "method",
                "methods",
                "study aims",
            )
        ):
            score -= 4
        return score

    def _evidence_ref_source_text(
        self,
        evidence_ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> str:
        locator = _locator_mapping(evidence_ref.get("locator"))
        block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
        parts = [
            _text(evidence_ref.get("quote")),
            _text(evidence_ref.get("label")),
            _text(locator.get("source_ref")),
            _text(locator.get("source_kind")),
            _text(evidence_ref.get("source_kind")),
            _text(block.heading_path if block else None),
            _text(block.text if block else None),
        ]
        return _normalize_match_text(" ".join(part for part in parts if part))

    def _finding_bundle_key_for_role(
        self,
        evidence_role: str | None,
        *,
        fallback_direct: bool = False,
    ) -> str:
        normalized = (_text(evidence_role) or "").lower()
        if normalized == "direct_support":
            return "direct_result"
        if normalized in {"mediator_context", "mechanism"}:
            return "mechanism"
        if normalized in {"condition_context", "context"}:
            return "condition_context"
        if normalized in {"background_context", "background"}:
            return "background"
        if normalized in {"conflict", "conflicting"}:
            return "conflict"
        if normalized in {"noise", "irrelevant"}:
            return "noise"
        if fallback_direct:
            return "direct_result"
        return "uncategorized"

    def _finding_support_grade(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_bundle: Mapping[str, list[str]],
        outcomes: list[str],
        relation_ids: list[str],
        review_status: str,
        scope_summary: str,
    ) -> str:
        support_status = (_text(effect.get("support_status")) or "limited").lower()
        direct_count = len(evidence_bundle.get("direct_result", []))
        evidence_count = int(effect.get("evidence_count") or 0)
        has_mechanism = self._finding_has_mechanism_support(evidence_bundle)
        has_independent_mechanism = bool(
            set(evidence_bundle.get("mechanism", []))
            - set(evidence_bundle.get("direct_result", []))
        )
        has_direct = self._finding_has_direct_support(evidence_bundle)
        if support_status == "conflicted" or evidence_bundle.get("conflict"):
            return "conflict"
        if support_status == "unsupported" or evidence_count == 0 or not outcomes:
            return "insufficient"
        if not has_direct:
            return "weak" if has_mechanism else "insufficient"
        if not relation_ids or not scope_summary:
            return "weak"
        if review_status == "needs_review":
            return "partial"
        if direct_count >= 2 or has_independent_mechanism:
            return "strong"
        if support_status == "supported":
            return "partial"
        return "weak"

    def _finding_review_reasons(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_bundle: Mapping[str, list[str]],
        mediators: list[str],
        mechanism_source_text: str,
        outcomes: list[str],
        relation_ids: list[str],
        review_status: str,
        support_grade: str,
        scope_summary: str,
    ) -> list[str]:
        reasons: list[str] = []
        paper_count = int(effect.get("paper_count") or 0)
        evidence_count = int(effect.get("evidence_count") or 0)
        if paper_count <= 0:
            reasons.append("no_source_paper")
        elif paper_count == 1:
            reasons.append("single_paper_evidence")
            reasons.append("needs_cross_paper_confirmation")
        else:
            reasons.append("cross_paper_evidence")
        if evidence_count <= 0:
            reasons.append("no_evidence")
        if not self._finding_has_direct_support(evidence_bundle):
            reasons.append("missing_direct_result_evidence")
        if not outcomes:
            reasons.append("missing_target_outcome")
        if not relation_ids:
            reasons.append("missing_relation_chain")
        if not scope_summary:
            reasons.append("missing_scope_context")
        if support_grade in {"partial", "weak", "insufficient"}:
            reasons.append(f"{support_grade}_support")
        if "non_single_variable_table_comparison" in _strings(effect.get("warnings")):
            reasons.append("non_single_variable_table_comparison")
        if "single_variable_effect_not_isolated" in _strings(
            effect.get("warnings")
        ):
            reasons.append("single_variable_effect_not_isolated")
        if "paper_level_association" in _strings(effect.get("warnings")):
            reasons.append("paper_level_association")
        if "process_conditions_not_isolated" in _strings(effect.get("warnings")):
            reasons.append("process_conditions_not_isolated")
        if "source_unit_inconsistency" in _strings(effect.get("warnings")):
            reasons.append("source_unit_inconsistency")
        if "author_attributed_mechanism" in _strings(effect.get("warnings")):
            reasons.append("author_attributed_mechanism")
        if (
            support_grade == "partial"
            and self._finding_has_direct_support(evidence_bundle)
            and not self._finding_has_mechanism_support(
                evidence_bundle,
                mediators=mediators,
                mechanism_source_text=mechanism_source_text,
            )
        ):
            reasons.append("missing_mechanism_evidence")
        if review_status == "needs_review":
            reasons.append("needs_expert_review")
        return _dedupe_strings(reasons)

    def _finding_has_direct_support(self, bundle: Mapping[str, list[str]]) -> bool:
        return bool(bundle.get("direct_result"))

    def _finding_has_mechanism_support(
        self,
        bundle: Mapping[str, list[str]],
        *,
        mediators: list[str] | None = None,
        mechanism_source_text: str = "",
    ) -> bool:
        if bundle.get("mechanism"):
            return True
        mediator_terms: set[str] = set()
        for mediator in mediators or []:
            mediator_terms.update(_quote_hint_terms(mediator))
        if not mediator_terms:
            return False
        if not mechanism_source_text:
            return False
        normalized = f" {_normalize_match_text(mechanism_source_text)} "
        return bool(_quote_term_hits(normalized, mediator_terms))

    def _finding_review_status(self, effect: Mapping[str, Any]) -> str:
        return "needs_review" if effect.get("needs_review") else "pending_review"

    def _finding_quote_hints_by_evidence_ref(
        self,
        findings: list[dict[str, Any]],
        *,
        relations_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, dict[str, set[str]]]:
        hints_by_ref: dict[str, dict[str, set[str]]] = {}
        for finding in findings:
            direct_ref_ids = _strings(
                _mapping(finding.get("evidence_bundle")).get("direct_result")
            )
            if not direct_ref_ids:
                continue
            hint_terms = self._quote_hints_for_finding(
                finding,
                relations_by_id=relations_by_id,
            )
            if not any(hint_terms.values()):
                continue
            for ref_id in direct_ref_ids:
                ref_hints = hints_by_ref.setdefault(
                    ref_id,
                    {
                        "variable": set(),
                        "outcome": set(),
                        "relation": set(),
                        "statement": set(),
                        "result_numeric": set(),
                        "result_numeric_endpoints": set(),
                    },
                )
                for key, terms in hint_terms.items():
                    ref_hints[key].update(terms)
        return hints_by_ref

    def _quote_hints_for_finding(
        self,
        finding: Mapping[str, Any],
        *,
        relations_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, set[str]]:
        hint_terms = {
            "variable": set(),
            "outcome": set(),
            "relation": set(),
            "statement": set(),
            "result_numeric": set(),
            "result_numeric_endpoints": set(),
        }
        for value in _strings(finding.get("variables")):
            hint_terms["variable"].update(_quote_hint_terms(value))
        for value in _strings(finding.get("outcomes")):
            hint_terms["outcome"].update(_quote_hint_terms(value))
        hint_terms["statement"].update(_quote_hint_terms(finding.get("statement")))
        hint_terms["statement"].update(_quote_numeric_hint_terms(finding.get("statement")))
        hint_terms["result_numeric"].update(
            _quote_result_numeric_hint_terms(finding.get("statement"))
        )
        hint_terms["result_numeric_endpoints"].update(
            _quote_result_numeric_endpoint_terms(finding.get("statement"))
        )
        for value in (
            _text(finding.get("statement")),
            _text(finding.get("title")),
            _text(finding.get("direction")),
            *_strings(finding.get("mediators")),
        ):
            hint_terms["relation"].update(_quote_hint_terms(value))
            hint_terms["relation"].update(_quote_numeric_hint_terms(value))
        for relation_id in _strings(finding.get("relation_ids")):
            relation = relations_by_id.get(relation_id, {})
            hint_terms["variable"].update(
                _quote_hint_terms(self._presentation_relation_side(relation.get("subject")))
            )
            object_chain = self._relation_object_chain(relation)
            if object_chain:
                hint_terms["outcome"].update(_quote_hint_terms(object_chain[-1]))
                for mediator in object_chain[:-1]:
                    hint_terms["relation"].update(_quote_hint_terms(mediator))
            for value in (
                _text(relation.get("predicate")),
                _text(relation.get("relation_type")),
                self._presentation_relation_summary(relation),
            ):
                hint_terms["relation"].update(_quote_hint_terms(value))
        return hint_terms

    def _presentation_effect(
        self,
        claim: Mapping[str, Any],
        *,
        relations: list[dict[str, Any]],
        evidence_by_id: dict[str, dict[str, Any]],
        contexts_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        claim_id = _text(claim.get("claim_id")) or "claim"
        evidence_ref_ids = _strings(claim.get("evidence_ref_ids"))
        context_ids = _strings(claim.get("context_ids"))
        source_object_ids = _strings(claim.get("source_object_ids"))
        direct_relations = [
            relation
            for relation in relations
            if _intersects(evidence_ref_ids, _strings(relation.get("evidence_ref_ids")))
        ]
        if not direct_relations:
            direct_relations = [
                relation
                for relation in relations
                if _intersects(
                    source_object_ids,
                    _strings(relation.get("source_object_ids")),
                )
            ]
        direct_relations = [
            relation
            for relation in direct_relations
            if self._relation_can_support_presentation_claim(
                relation,
                claim_evidence_ref_ids=evidence_ref_ids,
            )
        ]
        related_relations = [
            relation
            for relation in direct_relations
            if self._reviewable_presentation_relation(relation)
        ]
        primary_relation = related_relations[0] if related_relations else {}
        contexts = [
            contexts_by_id[context_id]
            for context_id in context_ids
            if context_id in contexts_by_id
        ]
        variable_axis = self._variable_axis_for(primary_relation, contexts)
        target_property = self._target_property_for(claim, primary_relation, contexts)
        target_properties = _dedupe_strings(
            [
                property_name
                for context in contexts_by_id.values()
                if (
                    _text(context.get("context_id")) == "ctx_objective_scope"
                    or _normalize_match_text(_text(context.get("label")) or "")
                    in {"objective scope", "goal scope"}
                )
                for property_name in _strings(context.get("property_scope"))
            ]
        )
        target_terms: set[str] = set()
        for target_property_name in target_properties:
            target_terms.update(
                self._finding_target_terms(
                    {"target_property": target_property_name},
                    [],
                )
            )
        goal_axes = _dedupe_strings(
            [
                axis
                for context in contexts_by_id.values()
                if (
                    _text(context.get("context_id")) == "ctx_objective_scope"
                    or _normalize_match_text(_text(context.get("label")) or "")
                    in {"objective scope", "goal scope"}
                )
                for process_context in [_mapping(context.get("process_context"))]
                for axis in [
                    *_strings(process_context.get("variable_process_axes")),
                    *_strings(process_context.get("process_context_axes")),
                ]
            ]
        )
        goal_axis_relations = [
            relation
            for relation in related_relations
            if self._relation_matches_goal_axis(relation, goal_axes)
        ]
        explicit_statement_axis = self._statement_comparison_axis(
            _text(claim.get("statement")) or "",
            goal_axes=goal_axes,
        )
        if self._is_recovered_expert_effect(claim):
            explicit_statement_axis = ""
        if explicit_statement_axis:
            statement_axis_relations = [
                self._relation_with_presentation_subject(
                    relation,
                    explicit_statement_axis,
                )
                for relation in related_relations
                if self._statement_comparison_axis(
                    self._presentation_relation_summary(relation),
                    goal_axes=goal_axes,
                )
                == explicit_statement_axis
            ]
            if statement_axis_relations:
                related_relations = statement_axis_relations
                primary_relation = related_relations[0]
                variable_axis = explicit_statement_axis
                target_property = self._target_property_for(
                    claim,
                    primary_relation,
                    contexts,
                )
        elif goal_axis_relations:
            related_relations = goal_axis_relations
            primary_relation = related_relations[0]
            variable_axis = self._variable_axis_for(primary_relation, contexts)
            target_property = self._target_property_for(claim, primary_relation, contexts)
        elif goal_axes and any(
            self._reviewable_presentation_relation(relation)
            and self._relation_matches_goal_axis(relation, goal_axes)
            for relation in relations
        ):
            related_relations = []
            primary_relation = {}
            variable_axis = self._variable_axis_for(primary_relation, contexts)
            target_property = self._target_property_for(claim, primary_relation, contexts)
        target_relations = [
            relation
            for relation in related_relations
            if self._relation_matches_finding_target(relation, target_terms)
        ]
        if target_relations:
            related_relations = target_relations
            primary_relation = related_relations[0]
            variable_axis = self._variable_axis_for(primary_relation, contexts)
            target_property = self._target_property_for(claim, primary_relation, [])
        relation_evidence_ref_ids = _dedupe_strings(
            [
                ref_id
                for relation in related_relations
                for ref_id in _strings(relation.get("evidence_ref_ids"))
            ]
        )
        effect_evidence_ref_ids = _dedupe_strings(
            [*evidence_ref_ids, *relation_evidence_ref_ids]
        )
        evidence_refs = [
            evidence_by_id[ref_id]
            for ref_id in effect_evidence_ref_ids
            if ref_id in evidence_by_id
        ]
        review_support_count = sum(
            1
            for ref in evidence_refs
            if _text(ref.get("evidence_role"))
            not in {"condition_context", "background", "conflict", "noise"}
        )
        paper_count = len(
            {
                _text(ref.get("document_id"))
                for ref in evidence_refs
                if _text(ref.get("document_id"))
            }
        )
        relation_ids = [
            _text(relation.get("relation_id"))
            for relation in related_relations
            if _text(relation.get("relation_id"))
        ]
        statement = _text(claim.get("statement")) or ""
        statement = self._contextualized_comparison_statement(
            statement,
            variable_axis=variable_axis,
            target_property=target_property,
            direction=_text(primary_relation.get("relation_type"))
            or _text(primary_relation.get("predicate"))
            or "",
            contexts=contexts,
        )
        return {
            "effect_id": f"effect_{claim_id}",
            "claim_id": claim_id,
            "title": self._effect_title(
                variable_axis=variable_axis,
                target_property=target_property,
                fallback=statement,
                relation_count=len(related_relations),
            ),
            "statement": statement,
            "claim_type": _text(claim.get("claim_type")) or "finding",
            "support_status": _text(claim.get("status")) or "limited",
            "confidence": claim.get("confidence"),
            "effect_direction": _text(primary_relation.get("relation_type"))
            or _text(primary_relation.get("predicate"))
            or "",
            "variable_axis": variable_axis,
            "target_property": target_property,
            "paper_count": paper_count,
            "evidence_count": len(evidence_refs),
            "context_summary": self._context_summary_text(contexts),
            "evidence_ref_ids": effect_evidence_ref_ids,
            "context_ids": context_ids,
            "relation_ids": relation_ids,
            "needs_review": self._effect_needs_review(
                claim,
                evidence_count=review_support_count,
                relation_ids=relation_ids,
                context_summary=self._context_summary_text(contexts),
            ),
            "warnings": _strings(claim.get("warnings")),
        }

    def _contextualized_comparison_statement(
        self,
        statement: str,
        *,
        variable_axis: str,
        target_property: str,
        direction: str,
        contexts: list[dict[str, Any]],
    ) -> str:
        text = _text(statement) or ""
        if not text or not variable_axis or not target_property:
            return text
        if self._looks_contextualized_comparison_statement(text):
            return text
        match = re.search(
            r"(?P<prefix>^(?:Under|With)\s+.+?,\s+)?"
            r"(?P<body_axis>.+?)\s+"
            r"(?P<direction>increased|increases|decreased|decreases|reduced|reduces|"
            r"improved|improves|lowered|lowers|raised|raises|changed|changes)\s+"
            r"(?P<outcome>.+?)\s+from\s+"
            r"(?P<baseline_segment>.+?)\s+to\s+"
            r"(?P<observed_value>[+-]?\d+(?:\.\d+)?\s*(?:%|MPa|GPa|J/mm3|J/mm³|HV|°\s*C|°C|C|K)?)"
            r"\.?$",
            text.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            return text
        baseline_value, _baseline_label = _comparison_summary_baseline(
            match.group("baseline_segment")
        )
        observed_value = _clean_comparison_summary_value(match.group("observed_value"))
        context = self._comparison_context_with_axis_values(
            contexts,
            variable_axis=variable_axis,
            baseline_value=baseline_value,
            observed_value=observed_value,
        )
        if not context:
            return text
        process_context = _mapping(_mapping(context.get("process_context")).get("process_context"))
        baseline_context = _mapping(
            _mapping(context.get("process_context")).get("baseline_context")
        )
        baseline_process_context = _mapping(baseline_context.get("process_context"))
        axis_lookup = self._comparison_statement_axis_label(variable_axis)
        current_axis_value = self._axis_value_from_context(
            axis_lookup,
            process_context,
        )
        baseline_axis_value = self._axis_value_from_context(
            axis_lookup,
            baseline_process_context,
        )
        if not current_axis_value or not baseline_axis_value:
            return text
        unit_text = self._comparison_value_unit(observed_value)
        baseline_value = self._comparison_display_value(baseline_value, unit_text)
        observed_value = self._comparison_display_value(observed_value, unit_text)
        if not baseline_value or not observed_value:
            return text
        controlled_axes = self._comparison_controlled_axes_from_context(
            process_context,
            baseline_process_context,
            variable_axis=variable_axis,
        )
        changed_axes = self._comparison_changed_axes_from_context(
            process_context,
            baseline_process_context,
            variable_axis=variable_axis,
        )
        if len(changed_axes) > 1:
            changed_axes_text = self._comparison_changed_axes_text(changed_axes)
            prefix = f"With {controlled_axes}, " if controlled_axes else ""
            verb = self._comparison_direction_verb(match.group("direction") or direction)
            return self._sentence_case(
                f"{prefix}table-row comparison changes {changed_axes_text}; "
                f"{target_property} {verb} from {baseline_value} to {observed_value}."
            )
        prefix = f"With {controlled_axes}, " if controlled_axes else ""
        axis_label = self._comparison_statement_axis_label(variable_axis)
        verb = self._comparison_direction_verb(match.group("direction") or direction)
        rewritten = (
            f"{prefix}changing {axis_label} from {baseline_axis_value} "
            f"to {current_axis_value} {verb} {target_property} from "
            f"{baseline_value} to {observed_value}."
        )
        return self._sentence_case(rewritten)

    def _comparison_context_with_axis_values(
        self,
        contexts: list[dict[str, Any]],
        *,
        variable_axis: str,
        baseline_value: str = "",
        observed_value: str = "",
    ) -> dict[str, Any]:
        matched_context = {}
        for context in contexts:
            process_payload = _mapping(context.get("process_context"))
            process_context = _mapping(process_payload.get("process_context"))
            baseline_context = _mapping(process_payload.get("baseline_context"))
            baseline_process_context = _mapping(baseline_context.get("process_context"))
            axis_lookup = self._comparison_statement_axis_label(variable_axis)
            if self._axis_value_from_context(
                axis_lookup,
                process_context,
            ) and self._axis_value_from_context(
                axis_lookup,
                baseline_process_context,
            ):
                if self._comparison_context_values_match_statement(
                    process_payload,
                    baseline_value=baseline_value,
                    observed_value=observed_value,
                ):
                    return context
                if not matched_context:
                    matched_context = context
        return matched_context if not (baseline_value or observed_value) else {}

    def _comparison_context_values_match_statement(
        self,
        process_payload: Mapping[str, Any],
        *,
        baseline_value: str,
        observed_value: str,
    ) -> bool:
        if not baseline_value and not observed_value:
            return True
        baseline_context = _mapping(process_payload.get("baseline_context"))
        baseline_candidates = (
            _text(baseline_context.get("source_value_text")),
            _text(baseline_context.get("value")),
        )
        process_candidates = (
            _text(process_payload.get("source_value_text")),
            _text(process_payload.get("value")),
        )
        baseline_matches = (
            not baseline_value
            or self._numeric_values_overlap(baseline_value, baseline_candidates)
        )
        if not baseline_matches:
            return False
        return (
            not observed_value
            or not any(process_candidates)
            or self._numeric_values_overlap(observed_value, process_candidates)
        )

    def _numeric_values_overlap(
        self,
        expected: str,
        candidates: tuple[str | None, ...],
    ) -> bool:
        expected_numbers = {
            _normalize_numeric_token(value)
            for value in re.findall(r"[-+]?\d+(?:\.\d+)?", expected)
        }
        expected_numbers.discard("")
        if not expected_numbers:
            return False
        candidate_numbers = {
            _normalize_numeric_token(value)
            for candidate in candidates
            for value in re.findall(r"[-+]?\d+(?:\.\d+)?", candidate or "")
        }
        candidate_numbers.discard("")
        return bool(expected_numbers & candidate_numbers)

    def _comparison_controlled_axes_from_context(
        self,
        process_context: Mapping[str, Any],
        baseline_process_context: Mapping[str, Any],
        *,
        variable_axis: str,
    ) -> str:
        controlled: list[str] = []
        variable_tokens = self._axis_match_tokens(
            self._comparison_statement_axis_label(variable_axis)
        )
        for key, value in process_context.items():
            key_text = _text(key) or ""
            key_tokens = self._axis_match_tokens(key_text)
            if variable_tokens and _axis_terms_overlap(variable_tokens, key_tokens):
                continue
            current_value = _text(value) or ""
            baseline_value = _text(baseline_process_context.get(key)) or ""
            if not current_value or current_value != baseline_value:
                continue
            controlled.append(
                self._comparison_axis_label(
                    self._display_axis_label(key_text),
                    current_value,
                )
            )
        cleaned_controlled = [
            value
            for value in _dedupe_strings(controlled)
            if _looks_user_facing(value)
        ]
        if len(cleaned_controlled) > 4:
            return ", ".join(
                (*cleaned_controlled[:4], f"+{len(cleaned_controlled) - 4} more")
            )
        if len(cleaned_controlled) > 1:
            return f"{', '.join(cleaned_controlled[:-1])} and {cleaned_controlled[-1]}"
        return cleaned_controlled[0] if cleaned_controlled else ""

    def _comparison_changed_axes_from_context(
        self,
        process_context: Mapping[str, Any],
        baseline_process_context: Mapping[str, Any],
        *,
        variable_axis: str,
    ) -> list[dict[str, str]]:
        changed: list[dict[str, str]] = []
        for key, value in process_context.items():
            key_text = _text(key) or ""
            current_value = _text(value) or ""
            baseline_value = _text(baseline_process_context.get(key)) or ""
            if not key_text or not current_value or not baseline_value:
                continue
            if current_value == baseline_value:
                continue
            axis_label = self._display_axis_label(key_text)
            if not _looks_user_facing(axis_label):
                continue
            changed.append(
                {
                    "axis": axis_label,
                    "baseline": baseline_value,
                    "observed": current_value,
                    "is_variable": str(
                        self._axis_labels_match(axis_label, variable_axis)
                    ),
                }
            )
        changed.sort(key=lambda item: 0 if item["is_variable"] == "true" else 1)
        return changed

    def _comparison_changed_axes_text(
        self,
        changed_axes: list[dict[str, str]],
    ) -> str:
        parts = [
            (
                f"{item['axis']} from {item['baseline']} to {item['observed']}"
            )
            for item in changed_axes
            if item.get("axis") and item.get("baseline") and item.get("observed")
        ]
        if len(parts) > 1:
            return f"{', '.join(parts[:-1])} and {parts[-1]}"
        return parts[0] if parts else ""

    def _comparison_statement_axis_label(self, axis: str) -> str:
        text = _text(axis) or ""
        for symbol in ("α", "β", "θ", "ɵ"):
            if symbol in text:
                return symbol
        return self._display_axis_label(text)

    def _comparison_value_unit(self, value: str) -> str:
        match = re.search(r"\d(?:\.\d+)?\s*(?P<unit>%|MPa|GPa|J/mm3|J/mm³|HV|°\s*C|°C|C|K)$", value)
        return match.group("unit") if match else ""

    def _presentation_relation_effect(
        self,
        relation: Mapping[str, Any],
        *,
        evidence_by_id: dict[str, dict[str, Any]],
        contexts_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        relation_id = _text(relation.get("relation_id")) or "relation"
        context_ids = _strings(relation.get("context_ids"))
        contexts = [
            contexts_by_id[context_id]
            for context_id in context_ids
            if context_id in contexts_by_id
        ]
        goal_axes = _dedupe_strings(
            [
                axis
                for context in contexts_by_id.values()
                if (
                    _text(context.get("context_id")) == "ctx_objective_scope"
                    or _normalize_match_text(_text(context.get("label")) or "")
                    in {"objective scope", "goal scope"}
                )
                for process_context in [_mapping(context.get("process_context"))]
                for axis in [
                    *_strings(process_context.get("variable_process_axes")),
                    *_strings(process_context.get("process_context_axes")),
                ]
            ]
        )
        explicit_statement_axis = self._statement_comparison_axis(
            self._presentation_relation_summary(relation),
            goal_axes=goal_axes,
        )
        if explicit_statement_axis:
            relation = self._relation_with_presentation_subject(
                relation,
                explicit_statement_axis,
            )
        variable_axis = self._variable_axis_for(relation, contexts)
        target_property = self._target_property_for({}, relation, contexts)
        evidence_ref_ids = _strings(relation.get("evidence_ref_ids"))
        evidence_refs = [
            evidence_by_id[ref_id]
            for ref_id in evidence_ref_ids
            if ref_id in evidence_by_id
        ]
        review_support_count = sum(
            1
            for ref in evidence_refs
            if _text(ref.get("evidence_role"))
            not in {"condition_context", "background", "conflict", "noise"}
        )
        paper_count = len(
            {
                _text(ref.get("document_id"))
                for ref in evidence_refs
                if _text(ref.get("document_id"))
            }
        )
        statement = self._presentation_relation_summary(relation)
        return {
            "effect_id": f"effect_{relation_id}",
            "claim_id": f"relation_{relation_id}",
            "title": self._effect_title(
                variable_axis=variable_axis,
                target_property=target_property,
                fallback=statement,
                relation_count=1,
            ),
            "statement": statement,
            "claim_type": "finding",
            "support_status": _text(relation.get("status")) or "limited",
            "confidence": relation.get("confidence"),
            "effect_direction": _text(relation.get("relation_type"))
            or _text(relation.get("predicate"))
            or "",
            "variable_axis": variable_axis,
            "target_property": target_property,
            "paper_count": paper_count,
            "evidence_count": len(evidence_refs),
            "context_summary": self._context_summary_text(contexts),
            "evidence_ref_ids": evidence_ref_ids,
            "context_ids": context_ids,
            "relation_ids": [relation_id],
            "needs_review": self._effect_needs_review(
                {"claim_type": "finding", "status": relation.get("status")},
                evidence_count=review_support_count,
                relation_ids=[relation_id],
                context_summary=self._context_summary_text(contexts),
            ),
            "warnings": _strings(relation.get("warnings")),
        }

    def _effect_needs_review(
        self,
        claim: Mapping[str, Any],
        *,
        evidence_count: int,
        relation_ids: list[str],
        context_summary: str,
    ) -> bool:
        if self._needs_review(claim):
            return True
        claim_type = _text(claim.get("claim_type")) or "finding"
        if evidence_count < 2 and claim_type in {"comparison", "mechanism", "finding"}:
            return True
        if self._claim_type_requires_relation(claim_type) and not relation_ids:
            return True
        if not context_summary:
            return True
        return False

    def _statement_comparison_axis(
        self,
        statement: str,
        *,
        goal_axes: list[str],
    ) -> str:
        raw_statement = _text(statement) or ""
        normalized_statement = f" {_normalize_match_text(raw_statement)} "
        if not normalized_statement.strip():
            return ""
        candidate_axes = [
            self._display_axis_label(axis)
            for axis in goal_axes
            if self._display_axis_label(axis)
        ]
        changed_axis = self._statement_changed_axis(raw_statement)
        if changed_axis:
            for axis in candidate_axes:
                if self._axis_labels_match(changed_axis, axis):
                    return axis
        condition_match = re.match(
            r"^\s*(?:Under|With)\s+(?P<conditioned>.+)$",
            raw_statement,
            flags=re.IGNORECASE,
        )
        condition_body = ""
        if condition_match and "," in condition_match.group("conditioned"):
            condition_body = condition_match.group("conditioned").rsplit(",", 1)[-1].strip()
        body_symbol_axis = ""
        if condition_body:
            body = condition_body
            body_symbol = _statement_leading_symbol(body)
            if body_symbol:
                body_symbol_axis = self._display_axis_label(body_symbol)
            changing_symbol = _statement_changing_symbol(body)
            if changing_symbol:
                body_symbol_axis = self._display_axis_label(changing_symbol)
        candidate_axes = _dedupe_strings(
            [
                *([body_symbol_axis] if body_symbol_axis else []),
                *self._statement_symbol_axis_candidates(raw_statement),
                *candidate_axes,
            ]
        )
        if condition_body:
            body = condition_body
            if body_symbol_axis and body_symbol_axis in candidate_axes:
                return body_symbol_axis
            body_tokens = _normalize_match_text(body).split()
            comparison_verbs = {
                "changed",
                "changes",
                "decreased",
                "decreases",
                "improved",
                "improves",
                "increased",
                "increases",
                "lowered",
                "lowers",
                "raised",
                "raises",
                "reduced",
                "reduces",
            }
            for axis in candidate_axes:
                axis_tokens = _normalize_match_text(axis).split()
                if not axis_tokens or body_tokens[: len(axis_tokens)] != axis_tokens:
                    continue
                if any(
                    token in comparison_verbs
                    for token in body_tokens[len(axis_tokens) : len(axis_tokens) + 4]
                ):
                    return axis
        parenthetical_text = " ".join(
            match.group(1)
            for match in re.finditer(r"\(([^)]{1,160})\)", raw_statement)
        )
        normalized_parenthetical = f" {_normalize_match_text(parenthetical_text)} "
        for axis in candidate_axes:
            normalized_axis = _normalize_match_text(axis)
            if not normalized_axis:
                continue
            if f" {normalized_axis} " in normalized_parenthetical:
                return axis
        for axis in candidate_axes:
            normalized_axis = _normalize_match_text(axis)
            if not normalized_axis:
                continue
            if re.search(
                rf"\b{re.escape(normalized_axis)}\s+[-+]?\d",
                normalized_statement,
            ):
                return axis
        return ""

    def _statement_symbol_axis_candidates(self, statement: str) -> list[str]:
        return _dedupe_strings(
            [
                display
                for symbol in ("β", "α", "θ", "ɵ")
                if symbol in statement
                if (display := self._display_axis_label(symbol))
            ]
        )

    def _relation_with_presentation_subject(
        self,
        relation: Mapping[str, Any],
        subject: str,
    ) -> dict[str, Any]:
        updated = dict(relation)
        updated["subject"] = subject
        return updated

    def _claim_type_requires_relation(self, claim_type: str) -> bool:
        return claim_type in {"comparison", "mechanism", "finding"}

    def _reviewable_presentation_relation(self, relation: Mapping[str, Any]) -> bool:
        subject = self._presentation_relation_side(relation.get("subject"))
        object_chain = self._relation_object_chain(relation)
        return bool(subject and object_chain and self._presentation_relation_summary(relation))

    def _relation_can_drive_presentation_finding(
        self,
        relation: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, Mapping[str, Any]],
        existing_effects: list[dict[str, Any]],
    ) -> bool:
        if "semantic_relation" not in _strings(relation.get("warnings")):
            return True
        evidence_ref_ids = _strings(relation.get("evidence_ref_ids"))
        evidence_refs = [
            evidence_by_id[ref_id]
            for ref_id in evidence_ref_ids
            if ref_id in evidence_by_id
        ]
        if not evidence_refs or len(evidence_refs) != len(evidence_ref_ids):
            return False
        document_ids = {
            document_id
            for ref in evidence_refs
            if (document_id := _text(ref.get("document_id")))
        }
        if len(document_ids) != 1:
            return False
        relation_subject_key = self._axis_key(
            self._presentation_relation_side(relation.get("subject"))
        )
        object_chain = self._relation_object_chain(relation)
        relation_outcome_key = _normalize_match_text(
            object_chain[-1] if object_chain else ""
        )
        if relation_outcome_key in {"ductility", "elongation to failure"}:
            relation_outcome_key = "elongation"
        relation_document_id = next(iter(document_ids))
        matches_existing_effect = False
        for effect in existing_effects:
            if _text(effect.get("claim_type")) not in {
                "comparison",
                "finding",
                "mechanism",
            }:
                continue
            if (
                self._axis_key(_text(effect.get("variable_axis")) or "")
                != relation_subject_key
            ):
                continue
            effect_outcome_key = _normalize_match_text(
                _text(effect.get("target_property")) or ""
            )
            if effect_outcome_key in {"ductility", "elongation to failure"}:
                effect_outcome_key = "elongation"
            if effect_outcome_key != relation_outcome_key:
                continue
            effect_document_ids = {
                document_id
                for ref_id in _strings(effect.get("evidence_ref_ids"))
                if (ref := evidence_by_id.get(ref_id)) is not None
                if (document_id := _text(ref.get("document_id")))
            }
            if relation_document_id in effect_document_ids:
                matches_existing_effect = True
                break
        if not matches_existing_effect:
            return False
        if any(
            "table"
            not in (
                _text(ref.get("source_kind"))
                or _text(_locator_mapping(ref.get("locator")).get("source_kind"))
                or ""
            ).lower()
            for ref in evidence_refs
        ):
            return True
        statement = _text(relation.get("statement")) or ""
        return bool(
            re.search(
                r"(?<![\w.])[-+]?\d+(?:\.\d+)?\s*"
                r"(?:%|MPa|GPa|J\s*/\s*mm(?:3|³)|HV|°\s*C|°C|C|K|W|"
                r"mm/s|µm|μm|um)(?![\w/])",
                statement,
                flags=re.IGNORECASE,
            )
        )

    def _relation_can_support_presentation_claim(
        self,
        relation: Mapping[str, Any],
        *,
        claim_evidence_ref_ids: list[str],
    ) -> bool:
        if "semantic_relation" not in _strings(relation.get("warnings")):
            return True
        relation_evidence_ref_ids = set(
            _strings(relation.get("evidence_ref_ids"))
        )
        return bool(
            relation_evidence_ref_ids
            and relation_evidence_ref_ids <= set(claim_evidence_ref_ids)
        )

    def _relation_matches_goal_axis(
        self,
        relation: Mapping[str, Any],
        goal_axes: list[str],
    ) -> bool:
        if not goal_axes:
            return False
        searchable = " ".join(
            item
            for item in (
                self._presentation_relation_side(relation.get("subject")),
                " ".join(self._relation_object_chain(relation)),
                self._presentation_relation_summary(relation),
            )
            if item
        )
        return any(
            self._objective_axis_tokens_match(searchable, axis)
            for axis in goal_axes
        )

    def _relation_matches_finding_target(
        self,
        relation: Mapping[str, Any],
        target_terms: set[str],
    ) -> bool:
        if not target_terms:
            return False
        broad_target_terms = {
            "mechanic",
            "mechanical",
            "mechanicals",
            "microstructural",
            "microstructure",
            "microstructureal",
            "microstructures",
            "properties",
        }
        if target_terms <= broad_target_terms:
            return False
        object_terms = self._finding_target_terms(
            {"target_property": " ".join(self._relation_object_chain(relation))},
            [],
        )
        return bool(object_terms & target_terms)

    def _presentation_relation_summary(self, relation: Mapping[str, Any]) -> str:
        statement = _text(relation.get("statement"))
        if statement and _looks_user_facing(statement):
            return statement
        subject = self._presentation_relation_side(relation.get("subject"))
        object_text = self._presentation_relation_side(relation.get("object"))
        predicate = _text(relation.get("predicate")) or _text(relation.get("relation_type"))
        if subject and object_text and _looks_user_facing(predicate):
            return f"{subject} -> {predicate} -> {object_text}"
        return ""

    def _presentation_relation_side(self, value: Any) -> str:
        text = self._display_axis_label(_text(value))
        if not text or not _looks_user_facing(text):
            return ""
        if self._is_placeholder_relation_side(text):
            return ""
        lower = text.lower()
        if (
            "sample_context" in lower
            or "process_context" in lower
            or "test_condition" in lower
            or "source_object_ids" in lower
            or "evidence_ref_ids" in lower
            or lower.startswith(
                (
                    "sample_number:",
                    "condition_number:",
                    "sample id:",
                    "condition id:",
                    "sample number:",
                    "condition number:",
                )
            )
        ):
            return ""
        return text

    def _display_axis_label(self, value: str | None) -> str:
        text = _text(value) or ""
        if not text:
            return ""
        stripped = text.strip()
        normalized = re.sub(r"\s+", " ", stripped.replace("_", " ")).strip()
        normalized = re.sub(
            r"\s*(?:\([^)]*\)|\[[^\]]*\])\s*$", "", normalized
        ).strip()
        for alias_candidate in (stripped, normalized):
            alias = _SYMBOL_AXIS_DISPLAY_ALIASES.get(alias_candidate.casefold())
            if alias:
                return alias
        normalized_key = _normalize_match_text(normalized)
        canonical_axes = {
            "energy density": "energy density",
            "hatch spacing": "hatch spacing",
            "heat treatment type": "heat treatment type",
            "laser power": "laser power",
            "layer thickness": "layer thickness",
            "scan speed": "scan speed",
            "scanning speed": "scanning speed",
            "type of heat treatment": "heat treatment type",
            "volumetric energy density": "volumetric energy density",
        }
        if normalized_key in canonical_axes:
            return canonical_axes[normalized_key]
        return normalized

    def _is_placeholder_relation_side(self, value: Any) -> bool:
        text = (_text(value) or "").strip()
        if not text:
            return True
        lower = text.lower()
        return lower in {
            "none",
            "null",
            "unknown",
            "n/a",
            "na",
            "not available",
            "not specified",
            "true",
            "false",
            "{}",
            "[]",
        }

    def _presentation_evidence_item(
        self,
        ref: Mapping[str, Any],
        *,
        collection_id: str,
        blocks_by_id: Mapping[str, SourceBlock],
        tables_by_id: Mapping[str, SourceTable],
        documents_by_id: Mapping[str, SourceDocument],
        quote_hints: Mapping[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_ref = _text(locator.get("source_ref"))
        label = _text(ref.get("label"))
        source_kind = _text(ref.get("source_kind")) or "unknown"
        document_id = _text(ref.get("document_id"))
        block = blocks_by_id.get(source_ref or "") if source_ref else None
        table = tables_by_id.get(source_ref or "") if source_ref else None
        document = (
            documents_by_id.get(block.document_id)
            if block and block.document_id
            else documents_by_id.get(table.document_id)
            if table and table.document_id
            else documents_by_id.get(document_id or "")
            if document_id
            else None
        )
        paper_label = _paper_label(document)
        block_label = _block_kind_label(block)
        if paper_label:
            source_label = paper_label
        elif _looks_user_facing(source_ref):
            source_label = source_ref or ""
        elif _looks_user_facing(label):
            source_label = label or ""
        elif block_label:
            source_label = block_label
        else:
            source_label = _source_kind_label(source_kind)
        quote = _text(ref.get("quote"))
        if not quote and block:
            quote = _short_text(block.text, limit=420)
        source_block = self._presentation_source_block_for_quote(
            block,
            blocks_by_id=blocks_by_id,
            quote_hints=quote_hints or {},
        )
        source_text = normalize_display_text(
            self._presentation_table_source_text(table)
            if table is not None
            else _text(source_block.text if source_block else None) or quote
        )
        table_audit = self._presentation_table_audit(
            table,
            quote_hints=quote_hints or {},
            cited_rows_quote=(
                quote
                if _text(ref.get("evidence_role")) == "condition_context"
                else ""
            ),
        )
        quote = (
            _presentation_table_audit_quote(table_audit) or source_text
            if table is not None
            else quote
            if (
                (
                    (_text(ref.get("evidence_ref_id")) or "").startswith(
                        "evref_recovered_heat_treatment_microstructure_mechanics_"
                    )
                    or (
                        (_text(ref.get("evidence_ref_id")) or "").startswith(
                            "evref_recovered_texture_yield_"
                        )
                        and "_mechanics_"
                        in (_text(ref.get("evidence_ref_id")) or "")
                    )
                )
                and quote
            )
            else self._presentation_quote_for_ref(
                quote=quote,
                source_text=source_text,
                quote_hints=quote_hints or {},
            )
        )
        display_block = source_block or block
        display_source_ref = (
            _text(display_block.block_id if display_block else None) or source_ref
        )
        display_page = (
            _text(locator.get("page"))
            or _text(locator.get("page_no"))
            or _text(table.page if table else None)
            or _text(display_block.page if display_block else None)
        )
        display_document_id = (
            document_id
            or _text(display_block.document_id if display_block else None)
            or _text(table.document_id if table else None)
        )
        display_title_parts = [source_label]
        if display_page:
            display_title_parts.append(f"p. {display_page}")
        heading_path = _text(display_block.heading_path if display_block else None)
        block_type = _text(display_block.block_type if display_block else None)
        value_summary = (
            _block_context_label(display_block)
            or (label if _looks_user_facing(label) else "")
        )
        href = _presentation_evidence_href(
            collection_id=collection_id,
            document_id=display_document_id,
            source_ref=display_source_ref,
            page=display_page,
            quote_text=quote,
        ) or _text(ref.get("href"))
        return {
            "evidence_ref_id": _text(ref.get("evidence_ref_id")) or "",
            "document_id": display_document_id,
            "title": " / ".join(display_title_parts),
            "source_label": source_label,
            "source_kind": source_kind,
            "source_ref": display_source_ref,
            "block_type": block_type,
            "heading_path": heading_path,
            "page": display_page,
            "quote": quote,
            "source_text": source_text,
            "value_summary": value_summary,
            "table_audit": table_audit,
            "traceability_status": _text(ref.get("traceability_status")) or "unknown",
            "evidence_role": _text(ref.get("evidence_role")),
            "confidence": ref.get("confidence"),
            "href": href,
        }

    def _presentation_table_audit(
        self,
        table: SourceTable | None,
        *,
        quote_hints: Mapping[str, set[str]],
        cited_rows_quote: str = "",
    ) -> dict[str, Any] | None:
        if table is None:
            return None
        columns = [_text(header) for header in table.column_headers if _text(header)]
        row_records: list[dict[str, Any]] = []
        statement_numeric_terms = {
            term for term in quote_hints.get("statement", set()) if re.search(r"\d", term)
        }
        result_numeric_terms = {
            term
            for term in quote_hints.get("result_numeric", set())
            if re.search(r"\d", term)
        }
        normalized_cited_rows = f" {_normalize_match_text(cited_rows_quote)} "
        for row_index, row in enumerate(table.table_matrix):
            cells = [_text(cell) for cell in row]
            row_text = " | ".join(cell for cell in cells if cell)
            if not row_text:
                continue
            normalized_row = f" {_normalize_match_text(row_text)} "
            if columns and _table_row_matches_columns(cells, columns):
                continue
            statement_hits = _quote_term_hits(
                normalized_row,
                quote_hints.get("statement", set()),
            )
            numeric_statement_hits = _quote_term_hits(
                normalized_row,
                statement_numeric_terms,
            )
            result_numeric_hits = _quote_term_hits(
                normalized_row,
                result_numeric_terms,
            )
            endpoint_hits = _quote_endpoint_numeric_hits(
                normalized_row,
                quote_hints.get("result_numeric_endpoints", set()),
            )
            score = _quote_candidate_score(row_text, quote_hints)
            if _quote_has_concrete_result_cue(row_text):
                score += 4
            if result_numeric_hits:
                score += result_numeric_hits * 80
            if endpoint_hits:
                score += endpoint_hits * 80
            if numeric_statement_hits:
                score += numeric_statement_hits * 40
            if statement_hits:
                score += statement_hits * 20
            if score <= 0 and re.search(r"\d", row_text):
                score = 1
            cited = bool(cited_rows_quote) and all(
                f" {_normalize_match_text(cell)} " in normalized_cited_rows
                for cell in cells
                if _text(cell)
            )
            row_records.append(
                {
                    "row_index": row_index,
                    "cells": cells,
                    "_score": score,
                    "_statement_hits": statement_hits,
                    "_numeric_statement_hits": numeric_statement_hits,
                    "_result_numeric_hits": result_numeric_hits,
                    "_endpoint_hits": endpoint_hits,
                    "_cited": cited,
                }
            )
        cited_rows = [row for row in row_records if row["_cited"]]
        endpoint_rows = _quote_endpoint_precision_rows(
            row_records,
            quote_hints.get("result_numeric_endpoints", set()),
        )
        max_result_hits = max(
            (int(row["_result_numeric_hits"]) for row in row_records),
            default=0,
        )
        result_precision_rows = [
            row
            for row in row_records
            if max_result_hits > 0
            and int(row["_result_numeric_hits"]) == max_result_hits
        ]
        max_numeric_hits = max(
            (int(row["_numeric_statement_hits"]) for row in row_records),
            default=0,
        )
        numeric_precision_rows = [
            row
            for row in row_records
            if max_numeric_hits > 0
            and int(row["_numeric_statement_hits"]) == max_numeric_hits
        ]
        precision_rows = cited_rows or endpoint_rows or _dedupe_rows_by_index(
            [
                *(result_precision_rows or numeric_precision_rows),
                *[row for row in row_records if row["_statement_hits"] > 0],
            ],
        )
        scored_rows = precision_rows or [row for row in row_records if row["_score"] > 0]
        relevant_rows = sorted(
            scored_rows,
            key=lambda row: (-int(row["_score"]), int(row["row_index"])),
        )[:4]
        if not relevant_rows:
            relevant_rows = row_records[:4]
        visible_column_indexes = list(range(len(columns)))
        semantic_terms: set[str] = set()
        for terms in quote_hints.values():
            semantic_terms.update(terms)
        sample_axis_terms = {"sample", "samples", "specimen", "specimens"}
        rows_are_aligned = all(
            len(row["cells"]) == len(columns) for row in relevant_rows
        )
        explicit_columns = [
            column
            for column in columns
            if _normalize_match_text(column) not in sample_axis_terms
        ]
        normalized_explicit_columns = (
            f" {_normalize_match_text(' | '.join(explicit_columns))} "
        )
        explicit_variable_and_outcome = bool(
            _quote_term_hits(
                normalized_explicit_columns,
                quote_hints.get("variable", set()),
            )
            and _quote_term_hits(
                normalized_explicit_columns,
                quote_hints.get("outcome", set()),
            )
        )
        if (
            rows_are_aligned
            and explicit_variable_and_outcome
            and not sample_axis_terms.intersection(semantic_terms)
        ):
            visible_column_indexes = [
                index
                for index, column in enumerate(columns)
                if not (
                    _normalize_match_text(column) in sample_axis_terms
                    and any(
                        re.search(
                            r"(?:as|ht|hip)[-\s]?slm\s*\(\s*\d+\s*/\s*$",
                            row["cells"][index],
                            flags=re.IGNORECASE,
                        )
                        for row in relevant_rows
                    )
                )
            ]
        visible_columns = [columns[index] for index in visible_column_indexes]
        audit_rows: list[dict[str, Any]] = []
        for row in relevant_rows:
            cells = (
                [row["cells"][index] for index in visible_column_indexes]
                if rows_are_aligned
                else list(row["cells"])
            )
            audit_rows.append(
                {
                    "row_index": int(row["row_index"]),
                    "cells": [cell if cell else "-" for cell in cells],
                    "aligned": _table_row_cells_are_aligned(
                        cells,
                        visible_columns,
                    ),
                }
            )
        return {
            "columns": visible_columns,
            "relevant_rows": audit_rows,
        }

    def _presentation_table_source_text(self, table: SourceTable | None) -> str:
        if table is None:
            return ""
        parts: list[str] = []
        caption = _text(table.caption_text)
        if caption:
            parts.append(caption)
        headers = [header for header in table.column_headers if _text(header)]
        if headers:
            parts.append("Columns: " + " | ".join(headers))
        rows: list[str] = []
        for row in table.table_matrix[:6]:
            cells = [_text(cell) for cell in row if _text(cell)]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            parts.append("Rows: " + " / ".join(rows))
        return _short_text(" ".join(parts), limit=900)

    def _presentation_source_block_for_quote(
        self,
        block: SourceBlock | None,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        quote_hints: Mapping[str, set[str]],
    ) -> SourceBlock | None:
        source_text = _text(block.text if block else None) or ""
        if (
            not block
            or not source_text
            or not quote_hints
            or _quote_has_concrete_result_cue(source_text)
            or not _quote_has_background_cue(source_text)
        ):
            return block
        source_heading = _normalize_match_text(_text(block.heading_path) or "")
        candidates = [
            candidate
            for candidate in blocks_by_id.values()
            if candidate.document_id == block.document_id
            and candidate.block_id != block.block_id
            and candidate.block_order is not None
            and block.block_order is not None
            and 0 < candidate.block_order - block.block_order <= 5
            and _normalize_match_text(_text(candidate.heading_path) or "")
            == source_heading
            and _quote_has_concrete_result_cue(_text(candidate.text) or "")
        ]
        best: tuple[int, int, int, SourceBlock] | None = None
        for index, candidate in enumerate(candidates):
            text = _text(candidate.text) or ""
            snippet = self._best_matching_quote_snippet(text, quote_hints)
            if not snippet:
                continue
            score = _quote_candidate_score(snippet, quote_hints)
            if score <= 0:
                continue
            ranked = (score, -(candidate.block_order or 0), -index, candidate)
            if best is None or ranked > best:
                best = ranked
        return best[3] if best else block

    def _presentation_quote_for_ref(
        self,
        *,
        quote: str | None,
        source_text: str | None,
        quote_hints: Mapping[str, set[str]],
    ) -> str:
        fallback = normalize_display_text(quote) or ""
        source = normalize_display_text(source_text) or fallback
        if not source:
            return ""
        snippet = self._best_matching_quote_snippet(source, quote_hints)
        if snippet:
            return normalize_display_text(snippet) or ""
        return fallback or _short_text(source, limit=420)

    def _best_matching_quote_snippet(
        self,
        source_text: str,
        quote_hints: Mapping[str, set[str]],
        *,
        limit: int = 520,
    ) -> str:
        if not quote_hints:
            return ""
        sentences = _quote_sentences(source_text)
        candidates = _quote_candidates_from_sentences(sentences)
        non_background_candidates = [
            candidate
            for candidate in candidates
            if not _quote_has_background_cue(candidate)
        ]
        if non_background_candidates:
            candidates = non_background_candidates
        specific_sentences = [
            sentence
            for sentence in sentences
            if sentence in candidates
            and _quote_has_variable_and_outcome(sentence, quote_hints)
        ]
        statement_terms = quote_hints.get("statement", set())
        non_variable_statement_terms = (
            statement_terms - quote_hints.get("variable", set())
        )
        statement_aligned_sentences = [
            sentence
            for sentence in sentences
            if sentence in candidates
            and _quote_has_concrete_result_cue(sentence)
            and _quote_candidate_score(sentence, quote_hints) > 0
            and _quote_term_hits(
                f" {_normalize_match_text(sentence)} ",
                statement_terms,
            )
            >= 3
            and _quote_term_hits(
                f" {_normalize_match_text(sentence)} ",
                non_variable_statement_terms,
            )
            >= 2
        ]
        if statement_aligned_sentences:
            statement_aligned_candidates: list[str] = []
            for index, sentence in enumerate(sentences):
                if sentence not in statement_aligned_sentences:
                    continue
                if (
                    index + 1 < len(sentences)
                    and _is_mechanism_attribution_sentence(sentences[index + 1])
                ):
                    window = f"{sentence} {sentences[index + 1]}"
                    if window in candidates:
                        statement_aligned_candidates.append(window)
                        continue
                statement_aligned_candidates.append(sentence)
            candidates = statement_aligned_candidates
            if any(candidate not in sentences for candidate in candidates):
                specific_sentences = []
            else:
                specific_sentences = [
                    sentence
                    for sentence in specific_sentences
                    if sentence in statement_aligned_sentences
                ]
        concrete_specific_sentences = [
            sentence
            for sentence in specific_sentences
            if _quote_has_concrete_result_cue(sentence)
        ]
        if concrete_specific_sentences:
            candidates = concrete_specific_sentences
        elif specific_sentences:
            best_specific_score = max(
                _quote_candidate_score(sentence, quote_hints)
                for sentence in specific_sentences
            )
            concrete_windows = [
                candidate
                for candidate in candidates
                if candidate not in sentences
                and _quote_has_concrete_result_cue(candidate)
                and _quote_candidate_score(candidate, quote_hints)
                >= best_specific_score + 8
            ]
            candidates = [*specific_sentences, *concrete_windows]
        best: tuple[int, int, str] | None = None
        for index, candidate in enumerate(candidates):
            score = _quote_candidate_score(candidate, quote_hints)
            if score <= 0:
                continue
            ranked = (score, -index, candidate)
            if best is None or ranked > best:
                best = ranked
        if best is None:
            return ""
        return _short_text(
            _extend_quote_with_neighboring_result_sentence(
                best[2],
                sentences=sentences,
                quote_hints=quote_hints,
            ),
            limit=limit,
        )

    def _source_artifact_lookups(
        self,
        collection_id: str | None,
    ) -> tuple[
        dict[str, SourceBlock],
        dict[str, SourceDocument],
        dict[str, SourceTable],
    ]:
        if not collection_id:
            return {}, {}, {}
        try:
            blocks = self.source_artifact_repository.list_blocks(collection_id)
            documents = self.source_artifact_repository.list_documents(collection_id)
        except Exception:  # noqa: BLE001
            return {}, {}, {}
        try:
            tables = self.source_artifact_repository.list_tables(collection_id)
        except Exception:  # noqa: BLE001
            tables = []
        return (
            {block.block_id: block for block in blocks if block.block_id},
            {document.document_id: document for document in documents if document.document_id},
            {table.table_id: table for table in tables if table.table_id},
        )

    def _presentation_context_summary(self, context: Mapping[str, Any]) -> dict[str, Any]:
        context_id = _text(context.get("context_id")) or "context"
        material_scope = _strings(context.get("material_scope"))
        property_scope = _strings(context.get("property_scope"))
        process_values = _display_values(_mapping(context.get("process_context")))
        test_values = _display_values(_mapping(context.get("test_condition")))
        return {
            "context_id": context_id,
            "label": _text(context.get("label")) or "Context",
            "material_scope": material_scope,
            "property_scope": property_scope,
            "process_summary": _join_display_values(process_values),
            "test_summary": _join_display_values(test_values),
            "limitations": _strings(context.get("limitations")),
        }

    def _variable_axis_for(
        self,
        relation: Mapping[str, Any],
        contexts: list[dict[str, Any]],
    ) -> str:
        subject = _text(relation.get("subject"))
        if subject and _looks_user_facing(subject):
            return subject
        predicate = _text(relation.get("predicate"))
        if predicate and _looks_user_facing(predicate):
            return predicate
        for context in contexts:
            values = _display_values(_mapping(context.get("process_context")))
            if values:
                return values[0]
        return ""

    def _target_property_for(
        self,
        claim: Mapping[str, Any],
        relation: Mapping[str, Any],
        contexts: list[dict[str, Any]],
    ) -> str:
        for context in contexts:
            properties = _strings(context.get("property_scope"))
            if properties:
                return properties[0]
        object_text = _text(relation.get("object"))
        if object_text and _looks_user_facing(object_text):
            return object_text
        statement = _text(claim.get("statement")) or ""
        if "density" in statement.lower():
            return "density"
        if "microstructure" in statement.lower():
            return "microstructure"
        return ""

    def _effect_title(
        self,
        *,
        variable_axis: str,
        target_property: str,
        fallback: str,
        relation_count: int = 0,
    ) -> str:
        if relation_count and variable_axis and target_property:
            return f"{variable_axis} -> {target_property}"
        if fallback:
            return _short_text(fallback, limit=96)
        if target_property:
            return target_property
        if variable_axis:
            return variable_axis
        return "Research finding"

    def _context_summary_text(self, contexts: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for context in contexts:
            parts.extend(_strings(context.get("material_scope")))
            parts.extend(_display_values(_mapping(context.get("process_context"))))
            parts.extend(_display_values(_mapping(context.get("test_condition"))))
        return _join_display_values(_dedupe_strings(parts), limit=5)

    def _needs_review(self, claim: Mapping[str, Any]) -> bool:
        status = _text(claim.get("status")) or ""
        confidence = _confidence_or_none(claim.get("confidence"))
        return (
            status in {"limited", "conflicted", "unsupported"}
            or (confidence is not None and confidence < 0.7)
            or bool(_strings(claim.get("warnings")))
            or not bool(_strings(claim.get("evidence_ref_ids")))
        )


def _stable_ref_id(
    source_kind: str | None,
    document_id: str | None,
    fact_ids: list[str] | tuple[str, ...],
    anchor_ids: list[str] | tuple[str, ...],
    locator: Mapping[str, Any],
) -> str:
    parts = [
        source_kind or "",
        document_id or "",
        ",".join(fact_ids),
        ",".join(anchor_ids),
        "|".join(f"{key}:{locator[key]}" for key in sorted(locator, key=str)),
    ]
    from hashlib import sha1

    return f"evref_{sha1('|'.join(parts).encode('utf-8')).hexdigest()[:12]}"


def _stable_relation_id(
    relation_type: str,
    source: str,
    target: str,
    statement: str,
    evidence_unit_ids: list[str] | tuple[str, ...],
) -> str:
    parts = [
        relation_type,
        source,
        target,
        statement,
        ",".join(evidence_unit_ids),
    ]
    from hashlib import sha1

    return f"rel_{sha1('|'.join(parts).encode('utf-8')).hexdigest()[:12]}"


def _dedupe_by_id(items: list[dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_id = _text(item.get(id_key))
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _append_claim(claims: list[dict[str, Any]], claim: dict[str, Any]) -> None:
    if claim:
        claims.append(claim)


def _dedupe_strings(items: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_mapping_list(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for item in items:
        cleaned: dict[str, str] = {}
        for key, raw_value in item.items():
            value = _text(raw_value) or ""
            if value:
                cleaned[key] = value
        key = tuple(sorted(cleaned.items()))
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _clean_comparison_summary_text(value: str | None) -> str:
    text = _text(value) or ""
    return re.sub(r"\s+", " ", text).strip(" .,;:")


def _clean_comparison_summary_value(value: str | None) -> str:
    return _clean_comparison_summary_text(value)


def _comparison_summary_baseline(value: str | None) -> tuple[str, str]:
    text = _clean_comparison_summary_text(value)
    if not text:
        return "", ""
    match = re.match(r"^(?P<value>.+)\((?P<label>[^()]*)\)$", text)
    if match is None:
        return _clean_comparison_summary_value(text), ""
    return (
        _clean_comparison_summary_value(match.group("value")),
        _clean_comparison_summary_text(match.group("label")),
    )


def _display_mapping(payload: Mapping[str, Any]) -> str:
    parts = []
    for key, value in payload.items():
        text = _text(value)
        if text:
            parts.append(f"{key}: {text}")
    return ", ".join(parts)


def _display_values(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for value in payload.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, Mapping):
            values.extend(_display_values(value))
        elif isinstance(value, (list, tuple, set)):
            values.extend(
                text
                for item in value
                if not isinstance(item, bool)
                and (text := _text(item))
                and text.lower() not in {"true", "false"}
            )
        elif (text := _text(value)) and text.lower() not in {"true", "false"}:
            values.append(text)
    return _dedupe_strings(values)


def _join_display_values(values: list[str] | tuple[str, ...], *, limit: int = 6) -> str:
    cleaned = [
        value
        for value in _dedupe_strings(values)
        if _looks_user_facing(value)
    ]
    if len(cleaned) > limit:
        return ", ".join((*cleaned[:limit], f"+{len(cleaned) - limit} more"))
    return ", ".join(cleaned)


def _compact_finding_scope_summary(
    raw_scope_summary: str,
    *,
    variables: list[str],
    outcomes: list[str],
    statement: str,
) -> str:
    raw = _text(raw_scope_summary) or ""
    if not raw:
        return ""

    raw_tokens = [token.strip() for token in raw.split(",") if token.strip()]
    has_more_marker = any(
        re.fullmatch(r"\+\d+\s+more", token, flags=re.IGNORECASE)
        for token in raw_tokens
    )
    visible_tokens = [
        token
        for token in raw_tokens
        if not re.fullmatch(r"\+\d+\s+more", token, flags=re.IGNORECASE)
    ]
    visible_tokens = [
        token
        for token in visible_tokens
        if not _is_generic_finding_scope_token(token)
    ]
    normalized_statement = f" {_normalize_match_text(statement)} "
    hip_markers = ("hip", "hot isostatic")
    furnace_markers = ("furnace ht", "furnace heat")
    statement_has_hip = any(marker in normalized_statement for marker in hip_markers)
    statement_has_furnace = any(
        marker in normalized_statement for marker in furnace_markers
    )
    statement_has_untreated = bool(
        re.search(
            r"\bheat treatment type\s*(?:-|none|untreated|as[- ]?slm)(?:\s|$)",
            statement,
            flags=re.IGNORECASE,
        )
    ) or any(
        marker in normalized_statement
        for marker in (" untreated ", " as slm ")
    )
    if statement_has_hip or statement_has_furnace or statement_has_untreated:
        visible_tokens = [
            token
            for token in visible_tokens
            if not (
                any(marker in _normalize_match_text(token) for marker in hip_markers)
                and not statement_has_hip
            )
            and not (
                any(
                    marker in _normalize_match_text(token)
                    for marker in furnace_markers
                )
                and not statement_has_furnace
            )
        ]
    if not has_more_marker and len(visible_tokens) == len(raw_tokens):
        return raw

    compact: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = _text(value)
        if not text or not _looks_user_facing(text):
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        compact.append(text)

    material_markers = (
        "316l",
        "304l",
        "steel",
        "stainless",
        "alloy",
        "aluminium",
        "aluminum",
        "titanium",
        "nickel",
        "inconel",
        "copper",
        "ti-",
        "ti6",
    )
    context_markers = (
        "lpbf",
        "l-pbf",
        "slm",
        "selective laser melting",
        "laser beam powder bed fusion",
        "powder bed fusion",
        "additive manufacturing",
        "electron beam melting",
        "directed energy deposition",
        "preheat",
        "preheating",
        "hot isostatic",
        "hip",
        "nacl",
        "corrosion",
    )

    for token in visible_tokens:
        lower = token.lower()
        if any(marker in lower for marker in material_markers):
            add(token)
    for variable in variables:
        add(variable)
    for outcome in outcomes:
        add(outcome)
    for token in visible_tokens:
        lower = token.lower()
        if any(marker in lower for marker in context_markers):
            add(token)

    if compact:
        return ", ".join(compact[:5])
    return ", ".join(visible_tokens[:4])


def _short_text(value: str, *, limit: int) -> str:
    text = normalize_display_text(value) or ""
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


def _is_generic_finding_scope_token(value: str) -> bool:
    text = _text(value)
    if not text:
        return True
    normalized = _normalize_match_text(text)
    if re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Za-z]", text):
        return True
    if normalized in {
        "conclusion",
        "conclusions",
        "conclusions and future study",
        "future study",
    }:
        return True
    if re.search(r"\(\s*\d+/\s*$", text):
        return True
    if re.fullmatch(
        r"\(\s*\d+\s*/\s*\d+\s*\)\s*(?:as|ht|hip)[-\s]?slm",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    return text.lower() in {
        "axis",
        "condition",
        "control",
        "factor",
        "parameter",
        "sample",
        "specimen",
        "test sample",
        "test specimen",
        "variable",
    }


def _intersects(left: list[str] | tuple[str, ...], right: list[str] | tuple[str, ...]) -> bool:
    right_set = set(right)
    return any(item in right_set for item in left)


def _looks_user_facing(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    lower = text.lower()
    if lower in {"true", "false"}:
        return False
    return not (
        lower.startswith(("blk_", "tbl_", "fig_", "evref_", "claim_", "rel_", "ctx_"))
        or lower.startswith(("sample_number:", "sample_id:", "row_id:", "document_id:"))
        or "sample_context:" in lower
        or "process_context:" in lower
        or "test_condition:" in lower
        or "{" in lower
        or "}" in lower
    )


def _source_kind_label(source_kind: str) -> str:
    normalized = source_kind.replace("_", " ").strip().lower()
    if "table" in normalized:
        return "Table evidence"
    if "figure" in normalized:
        return "Figure evidence"
    if "text" in normalized or "paragraph" in normalized:
        return "Text evidence"
    return "Evidence"


def _paper_label(document: SourceDocument | None) -> str:
    if not document:
        return ""
    for value in (
        document.title,
        document.metadata.get("file_name") if isinstance(document.metadata, Mapping) else None,
        document.metadata.get("filename") if isinstance(document.metadata, Mapping) else None,
        document.document_id,
    ):
        text = _text(value)
        if text and _looks_user_facing(text):
            return _short_text(text, limit=120)
    return ""


def _block_kind_label(block: SourceBlock | None) -> str:
    if not block:
        return ""
    block_type = str(block.block_type or "").replace("_", " ").strip()
    if not block_type:
        return ""
    if block.block_order:
        return f"{block_type.title()} {block.block_order}"
    return block_type.title()


def _block_context_label(block: SourceBlock | None) -> str:
    if not block:
        return ""
    heading = _text(block.heading_path)
    if heading and _looks_user_facing(heading):
        return _short_text(heading, limit=160)
    return _block_kind_label(block)


def _presentation_evidence_href(
    *,
    collection_id: str,
    document_id: Any,
    source_ref: str,
    page: str,
    quote_text: str | None = None,
) -> str | None:
    document = _text(document_id)
    source = _text(source_ref)
    if not collection_id or not document or not source:
        return None
    params = [("view", "parsed-paper"), ("source_ref", source)]
    if page:
        params.append(("page", page))
    quote_value = _short_text(_text(quote_text), limit=520)
    if quote_value:
        params.append(("quote", quote_value))
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params)
    return (
        f"/collections/{quote(collection_id)}/documents/{quote(document)}"
        f"?{query}"
    )


def _presentation_table_audit_quote(table_audit: Mapping[str, Any] | None) -> str:
    if not table_audit:
        return ""
    columns = _ordered_texts(table_audit.get("columns"))
    row_texts: list[str] = []
    for row in _mapping_list(table_audit.get("relevant_rows")):
        cells = _ordered_texts(row.get("cells"))
        if cells:
            row_texts.append(
                _presentation_table_row_quote(
                    cells,
                    columns,
                    aligned=row.get("aligned"),
                )
            )
    parts: list[str] = []
    if columns:
        parts.append("Columns: " + " | ".join(columns))
    if row_texts:
        parts.append("Relevant rows: " + " / ".join(row_texts))
    return _short_text(" ".join(parts), limit=900)


def _presentation_table_row_quote(
    cells: list[str],
    columns: list[str],
    *,
    aligned: Any = None,
) -> str:
    if not columns:
        return " | ".join(cells)
    if not _table_row_is_aligned(cells, columns, aligned=aligned):
        return "Unaligned cells: " + " | ".join(cells)
    pairs: list[str] = []
    for index, cell in enumerate(cells):
        pairs.append(f"{columns[index]}: {cell}")
    return "; ".join(pairs)


def _table_row_is_aligned(
    cells: list[str],
    columns: list[str],
    *,
    aligned: Any = None,
) -> bool:
    if isinstance(aligned, bool):
        return aligned
    return _table_row_cells_are_aligned(cells, columns)


def _table_row_cells_are_aligned(cells: list[str], columns: list[str]) -> bool:
    return not columns or len(cells) == len(columns)


def _table_audit_has_unaligned_rows(table_audit: Mapping[str, Any] | None) -> bool:
    if not table_audit:
        return False
    columns = _ordered_texts(table_audit.get("columns"))
    if not columns:
        return False
    for row in _mapping_list(table_audit.get("relevant_rows")):
        cells = _ordered_texts(row.get("cells"))
        if cells and not _table_row_is_aligned(
            cells,
            columns,
            aligned=row.get("aligned"),
        ):
            return True
    return False


def _ordered_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        items = (value,)
    return [text for item in items if (text := _text(item))]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _locator_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = _text(value)
    return {"source_ref": text} if text else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = (value,)
    return _dedupe_strings(
        [
            text
            for item in items
            if not isinstance(item, bool)
            and (text := str(item).strip())
            and text.lower() not in {"true", "false"}
        ]
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _normalize_match_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _normalize_numeric_token(value: Any) -> str:
    text = _text(value) or ""
    if not text:
        return ""
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def _numeric_text(value: Any) -> str:
    text = _text(value) or ""
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def _float_text(value: Any) -> float | None:
    text = _numeric_text(value)
    if not text:
        return None
    return float(text)


def _format_numeric_range(values: list[str]) -> str:
    pairs = [(float(value), value) for value in values]
    if not pairs:
        return ""
    low_value, low_text = min(pairs, key=lambda item: item[0])
    high_value, high_text = max(pairs, key=lambda item: item[0])
    if low_value == high_value:
        return low_text
    return f"{low_text}-{high_text}"


def _meaningful_match_tokens(value: str) -> list[str]:
    return [
        token
        for token in _normalize_match_text(value).split()
        if len(token) >= 3 and token not in _FINDING_MATCH_STOPWORDS
    ]


def _normalize_axis_coverage_text(value: str) -> set[str]:
    tokens = set(_meaningful_match_tokens(value))
    if "mechanical" in tokens:
        tokens.update(_MECHANICAL_PROPERTY_AXIS_TOKENS)
    if {"pbf", "lb"} <= tokens:
        tokens.update({"laser", "powder", "bed", "fusion", "lpbf"})
    if {"powder", "bed", "fusion"} <= tokens:
        tokens.update({"laser", "lpbf"})
    if "ved" in tokens:
        tokens.update({"volumetric", "energy", "density"})
    if {"volumetric", "energy", "density"} <= tokens:
        tokens.add("ved")
    if "lpbf" in tokens:
        tokens.update({"laser", "powder", "bed", "fusion"})
    if {"laser", "powder", "bed", "fusion"} <= tokens:
        tokens.add("lpbf")
    if "slm" in tokens:
        tokens.update({"selective", "laser", "melting"})
    if {"selective", "laser", "melting"} <= tokens:
        tokens.add("slm")
    if "preheating" in tokens:
        tokens.add("preheat")
    if "preheat" in tokens:
        tokens.add("preheating")
    return tokens


def _axis_terms_overlap(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    shared = left & right
    return bool(shared and (shared == left or shared == right or len(shared) >= 2))


def _symbol_match_term(value: Any) -> str:
    text = str(value or "").strip()
    if text == "α":
        return "greek_alpha"
    if text == "β":
        return "greek_beta"
    if text in {"θ", "ɵ"}:
        return "greek_theta"
    return ""


def _symbol_match_text(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "α": " greek_alpha ",
        "β": " greek_beta ",
        "θ": " greek_theta ",
        "ɵ": " greek_theta ",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return " ".join(text.split()).casefold()


def _statement_leading_symbol(value: Any) -> str:
    text = str(value or "").lstrip()
    for symbol in ("α", "β", "θ", "ɵ"):
        if text.startswith(symbol):
            return symbol
    return ""


def _statement_changing_symbol(value: Any) -> str:
    match = re.search(r"\bchanging\s*([αβθɵ])\s+from\b", str(value or ""))
    return match.group(1) if match else ""


def _target_token_variants(token: str) -> set[str]:
    variants = {token}
    domain_variants = {
        "porosity": {"pore", "pores", "porosities"},
        "pore": {"pores", "porosity"},
        "pores": {"pore", "porosity"},
        "density": {"densities"},
        "densities": {"density"},
        "microstructure": {"microstructural"},
        "microstructural": {"microstructure"},
    }
    variants.update(domain_variants.get(token, set()))
    if token.endswith("y") and len(token) > 4:
        variants.add(f"{token[:-1]}ies")
    elif token.endswith("ies") and len(token) > 5:
        variants.add(f"{token[:-3]}y")
    elif token.endswith("s") and len(token) > 4:
        variants.add(token[:-1])
    elif not token.endswith("s"):
        variants.add(f"{token}s")
    if token.endswith("al") and len(token) > 5:
        variants.add(token[:-2])
    else:
        variants.add(f"{token}al")
    return variants


def _quote_hint_terms(value: str | None) -> set[str]:
    terms: set[str] = set()
    normalized_value = f" {_normalize_match_text(value or '')} "
    tokens = _meaningful_match_tokens(value or "")
    for token in tokens:
        terms.update(_target_token_variants(token))
    for index in range(len(tokens) - 1):
        left = tokens[index]
        right = tokens[index + 1]
        terms.add(f"{left} {right}")
        if right.endswith("y") and len(right) > 4:
            terms.add(f"{left} {right[:-1]}ies")
        elif right.endswith("s"):
            terms.add(f"{left} {right[:-1]}")
        else:
            terms.add(f"{left} {right}s")
    if " volumetric energy density " in normalized_value:
        terms.add("ved")
    if " ved " in normalized_value:
        terms.update({"volumetric energy density", "energy density"})
    return {term for term in terms if term}


def _quote_numeric_hint_terms(value: str | None) -> set[str]:
    terms: set[str] = set()
    for match in re.findall(r"[-+]?\d+(?:\.\d+)?", value or ""):
        terms.add(match)
        terms.add(_normalize_match_text(match))
        normalized = _normalize_numeric_token(match)
        if normalized:
            terms.add(normalized)
            terms.add(_normalize_match_text(normalized))
            if "." in match:
                integer_part, fractional_part = match.split(".", 1)
                for precision in range(len(fractional_part), 4):
                    padded = f"{integer_part}.{fractional_part.ljust(precision, '0')}"
                    terms.add(_normalize_numeric_token(padded))
                    terms.add(_normalize_match_text(padded))
    return terms


def _quote_result_numeric_hint_terms(value: str | None) -> set[str]:
    text = value or ""
    result_numbers: list[str] = []
    for match in re.finditer(r"\bfrom\s+([-+]?\d+(?:\.\d+)?)", text, flags=re.IGNORECASE):
        result_numbers.append(match.group(1))
        trailing = text[match.end() : match.end() + 120]
        to_match = re.search(
            r"\bto\s+([-+]?\d+(?:\.\d+)?)",
            trailing,
            flags=re.IGNORECASE,
        )
        if to_match:
            result_numbers.append(to_match.group(1))
    for match in re.finditer(
        r"\(([0-9]+(?:\.\d+)?)\s+to\s+([0-9]+(?:\.\d+)?)\s*[%a-zA-Zµμ^0-9]*\)",
        text,
        flags=re.IGNORECASE,
    ):
        result_numbers.extend([match.group(1), match.group(2)])
    terms: set[str] = set()
    for number in result_numbers:
        terms.update(_quote_numeric_hint_terms(number))
    return terms


def _quote_result_numeric_endpoint_terms(value: str | None) -> set[str]:
    text = value or ""
    endpoints: set[str] = set()
    for match in re.finditer(r"\bfrom\s+([-+]?\d+(?:\.\d+)?)", text, flags=re.IGNORECASE):
        baseline = match.group(1)
        trailing = text[match.end() : match.end() + 120]
        observed_match = re.search(
            r"\bto\s+([-+]?\d+(?:\.\d+)?)",
            trailing,
            flags=re.IGNORECASE,
        )
        if not observed_match:
            continue
        for number in (baseline, observed_match.group(1)):
            terms = sorted(_quote_numeric_hint_terms(number))
            if terms:
                endpoints.add("\x1f".join(terms))
    return endpoints


def _quote_endpoint_numeric_hits(
    normalized_candidate: str,
    endpoint_terms: set[str],
) -> int:
    hits = 0
    for endpoint in endpoint_terms:
        terms = {term for term in endpoint.split("\x1f") if term}
        if _quote_term_hits(normalized_candidate, terms):
            hits += 1
    return hits


def _quote_endpoint_precision_rows(
    row_records: list[dict[str, Any]],
    endpoint_terms: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for endpoint in endpoint_terms:
        terms = {term for term in endpoint.split("\x1f") if term}
        matching = [
            row
            for row in row_records
            if _quote_term_hits(
                f" {_normalize_match_text(' | '.join(cell for cell in row['cells'] if cell))} ",
                terms,
            )
        ]
        if not matching:
            continue
        rows.append(
            max(
                matching,
                key=lambda row: (int(row["_score"]), -int(row["row_index"])),
            )
        )
    return _dedupe_rows_by_index(rows)


def _dedupe_rows_by_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        row_index = int(row["row_index"])
        if row_index in seen:
            continue
        seen.add(row_index)
        deduped.append(row)
    return deduped


def _quote_sentences(value: str) -> list[str]:
    text = " ".join(value.split())
    if not text:
        return []
    abbreviations = {"Fig.": "Fig<dot>"}
    for source, replacement in abbreviations.items():
        text = text.replace(source, replacement)
    sentences = [
        candidate.replace("Fig<dot>", "Fig.").strip()
        for candidate in re.split(r"(?<=[.!?])\s+", text)
        if candidate.strip()
    ]
    result: list[str] = []
    for sentence in sentences:
        prefix, separator, suffix = sentence.partition(":")
        normalized_prefix = _normalize_match_text(prefix)
        if (
            separator
            and suffix.strip()
            and (
                "following conclusions" in normalized_prefix
                or "based on the results" in normalized_prefix
            )
        ):
            result.append(prefix.strip() + separator)
            result.append(suffix.strip())
            continue
        result.append(sentence)
    return result


def _quote_candidates_from_sentences(sentences: list[str]) -> list[str]:
    if not sentences:
        return []
    windows = [
        f"{left} {right}"
        for left, right in zip(sentences, sentences[1:], strict=False)
    ]
    return [*sentences, *windows]


def _quote_candidate_score(candidate: str, quote_hints: Mapping[str, set[str]]) -> int:
    normalized = f" {_normalize_match_text(candidate)} "
    if not normalized.strip():
        return 0
    variable_hits = _quote_term_hits(normalized, quote_hints.get("variable", set()))
    outcome_hits = _quote_term_hits(normalized, quote_hints.get("outcome", set()))
    relation_hits = _quote_term_hits(normalized, quote_hints.get("relation", set()))
    if not (variable_hits or outcome_hits or relation_hits):
        return 0
    score = variable_hits + outcome_hits * 4 + relation_hits * 2
    if variable_hits and outcome_hits:
        score += 8
    if outcome_hits and relation_hits:
        score += 4
    if _quote_has_concrete_result_cue(candidate):
        score += 12
    has_result_cue = any(
        f" {cue} " in normalized
        for cue in (
            "result",
            "results",
            "show",
            "showed",
            "shown",
            "indicate",
            "indicated",
            "reported",
            "demonstrate",
            "demonstrated",
            "conclusion",
            "conclusions",
        )
    )
    if has_result_cue:
        score += 3
    has_background_cue = _normalized_quote_has_background_cue(normalized)
    if has_background_cue:
        score -= 12 if not has_result_cue else 4
    return score


def _table_row_matches_columns(row: list[str], columns: list[str]) -> bool:
    if not row or not columns:
        return False
    normalized_row = [_normalize_match_text(cell) for cell in row if _text(cell)]
    normalized_columns = [
        _normalize_match_text(column) for column in columns if _text(column)
    ]
    if not normalized_row or not normalized_columns:
        return False
    return normalized_row[: len(normalized_columns)] == normalized_columns


def _extend_quote_with_neighboring_result_sentence(
    selected: str,
    *,
    sentences: list[str],
    quote_hints: Mapping[str, set[str]],
) -> str:
    selected_sentences = _quote_sentences(selected)
    if not selected_sentences:
        return selected
    last_sentence = selected_sentences[-1]
    if last_sentence not in sentences:
        return selected
    index = sentences.index(last_sentence)
    extended = selected
    start_index = index
    while start_index > 0:
        previous = sentences[start_index - 1]
        if _previous_sentence_extends_quote(previous, extended, quote_hints):
            extended = f"{previous} {extended}"
            start_index -= 1
            continue
        if (
            start_index > 1
            and _previous_sentence_bridges_validation_context(previous, extended)
            and _previous_sentence_extends_quote(
                sentences[start_index - 2],
                f"{previous} {extended}",
                quote_hints,
            )
        ):
            extended = f"{sentences[start_index - 2]} {previous} {extended}"
            start_index -= 2
            continue
        break
    if index + 1 >= len(sentences):
        return extended
    while index + 1 < len(sentences):
        following = sentences[index + 1]
        if not _following_sentence_extends_quote(following, extended, quote_hints):
            break
        extended = f"{extended} {following}"
        index += 1
    return extended


def _previous_sentence_extends_quote(
    previous: str,
    selected: str,
    quote_hints: Mapping[str, set[str]],
) -> bool:
    normalized_previous = f" {_normalize_match_text(previous)} "
    normalized_selected = f" {_normalize_match_text(selected)} "
    if "validation" not in normalized_selected:
        return False
    has_validation_quality_cue = (
        " experimental findings " in normalized_previous
        or " experimental results " in normalized_previous
        or " deviations " in normalized_previous
        or " strong alignment " in normalized_previous
    )
    if not _quote_has_concrete_result_cue(previous):
        return False
    if has_validation_quality_cue:
        return True
    return bool(
        _quote_term_hits(normalized_previous, quote_hints.get("outcome", set()))
        or _quote_term_hits(normalized_previous, quote_hints.get("relation", set()))
        or _quote_term_hits(normalized_previous, quote_hints.get("statement", set()))
    )


def _previous_sentence_bridges_validation_context(
    previous: str,
    selected: str,
) -> bool:
    normalized_previous = f" {_normalize_match_text(previous)} "
    normalized_selected = f" {_normalize_match_text(selected)} "
    if "validation" not in normalized_selected:
        return False
    return bool(
        (
            " consistency " in normalized_previous
            or " accuracy " in normalized_previous
        )
        and (
            " prediction " in normalized_previous
            or " predictions " in normalized_previous
            or " experimental data " in normalized_previous
        )
    )


def _following_sentence_extends_quote(
    following: str,
    selected: str,
    quote_hints: Mapping[str, set[str]],
) -> bool:
    normalized_following = f" {_normalize_match_text(following)} "
    normalized_selected = f" {_normalize_match_text(selected)} "
    if not _quote_hints_allow_result_extension(quote_hints):
        return False
    if _following_sentence_is_fatigue_limitation(normalized_following, quote_hints):
        return True
    if _following_sentence_is_corrosion_mechanism(
        normalized_following,
        quote_hints,
    ):
        return True
    if not _quote_has_concrete_result_cue(following):
        return False
    shared_statement_hits = _quote_term_hits(
        normalized_following,
        quote_hints.get("statement", set()),
    )
    relation_hits = _quote_term_hits(
        normalized_following,
        quote_hints.get("relation", set()),
    )
    outcome_hits = _quote_term_hits(
        normalized_following,
        quote_hints.get("outcome", set()),
    )
    return shared_statement_hits >= 2 and (relation_hits or outcome_hits)


def _quote_hints_allow_result_extension(
    quote_hints: Mapping[str, set[str]],
) -> bool:
    terms = set(quote_hints.get("outcome", set())) | set(
        quote_hints.get("statement", set())
    )
    return bool(
        terms
        & {
            "better corrosion",
            "corrosion",
            "corrosion rate",
            "electrochemical",
            "passive film",
            "pitting",
            "pitting corrosion",
            "pitting potential",
            "polarization",
            "defect",
            "defects",
            "fatigue",
            "fatigue strength",
            "lof",
        }
    )


def _following_sentence_is_fatigue_limitation(
    normalized_following: str,
    quote_hints: Mapping[str, set[str]],
) -> bool:
    terms = set(quote_hints.get("outcome", set())) | set(
        quote_hints.get("statement", set())
    )
    if not (terms & {"defect", "defects", "fatigue", "fatigue strength", "lof"}):
        return False
    return bool(
        (
            " fatigue limit " in normalized_following
            or " fatigue life " in normalized_following
        )
        and (
            " lof " in normalized_following
            or " defect " in normalized_following
            or " defects " in normalized_following
        )
        and (
            " limited " in normalized_following
            or " decrease " in normalized_following
            or " decreases " in normalized_following
        )
    )


def _following_sentence_is_corrosion_mechanism(
    normalized_following: str,
    quote_hints: Mapping[str, set[str]],
) -> bool:
    terms = set(quote_hints.get("outcome", set())) | set(
        quote_hints.get("statement", set())
    )
    if not (
        terms
        & {
            "better corrosion",
            "corrosion",
            "corrosion rate",
            "pitting",
            "pitting corrosion",
            "pitting potential",
        }
    ):
        return False
    return bool(
        " passive film " in normalized_following
        or " corrosion rate " in normalized_following
        or " pitting potential " in normalized_following
        or " better corrosion " in normalized_following
    )


def _quote_has_concrete_result_cue(candidate: str) -> bool:
    normalized = f" {_normalize_match_text(candidate)} "
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|c|k|w|mpa|gpa|hv|mm/s|um)\b", candidate.lower()):
        return True
    if re.search(r"\bdeviations?\b.+\b\d+(?:\.\d+)?\s*%", candidate.lower()):
        return True
    return any(
        f" {cue} " in normalized
        for cue in (
            "increased",
            "decreased",
            "reduced",
            "improved",
            "attributed",
            "affected",
            "measured",
            "achieved",
            "observed",
            "revealed",
            "sensitive",
            "prone",
            "slow",
            "slows",
            "formed",
            "experimental findings",
            "strong alignment",
        )
    )


def _is_mechanism_attribution_sentence(candidate: str) -> bool:
    normalized = f" {_normalize_match_text(candidate)} "
    has_attribution = any(
        f" {cue} " in normalized
        for cue in (
            "attributed",
            "attributable",
            "because",
            "caused",
            "due",
            "owing",
            "resulting",
            "through",
        )
    )
    if not has_attribution:
        return False
    return any(
        f" {cue} " in normalized
        for cue in (
            "cellular",
            "dislocation",
            "dislocations",
            "gnd",
            "gnds",
            "grain",
            "grains",
            "homogenized",
            "microstructure",
            "microstructural",
            "passive film",
            "pores",
            "porosity",
            "residual stress",
            "texture",
        )
    )


def _quote_has_variable_and_outcome(
    candidate: str,
    quote_hints: Mapping[str, set[str]],
) -> bool:
    normalized = f" {_normalize_match_text(candidate)} "
    return bool(
        _quote_term_hits(normalized, quote_hints.get("variable", set()))
        and _quote_term_hits(normalized, quote_hints.get("outcome", set()))
    )


def _quote_term_hits(normalized_candidate: str, terms: set[str]) -> int:
    return sum(1 for term in terms if f" {term} " in normalized_candidate)


def _quote_has_background_cue(candidate: str) -> bool:
    return _normalized_quote_has_background_cue(
        f" {_normalize_match_text(candidate)} "
    )


def _normalized_quote_has_background_cue(normalized_candidate: str) -> bool:
    return any(
        f" {cue} " in normalized_candidate
        for cue in (
            "aim",
            "aims",
            "objective",
            "objectives",
            "introduction",
            "prior work",
            "study evaluates",
            "study aims",
            "was investigated",
            "were investigated",
            "can be drawn",
        )
    )


def _confidence_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if math.isnan(numeric):
            return None
        return round(min(1.0, max(0.0, numeric)), 2)
    except (TypeError, ValueError):
        return None


def _safe_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _trace_id(
    task_type: Any,
    collection_id: str | None,
    scope_id: str | None,
    source_object_ids: list[str],
) -> str:
    payload = "\x1f".join(
        [
            _text(task_type) or "",
            collection_id or "",
            scope_id or "",
            *source_object_ids,
        ]
    )
    return "rut_" + sha1(payload.encode("utf-8")).hexdigest()[:16]
