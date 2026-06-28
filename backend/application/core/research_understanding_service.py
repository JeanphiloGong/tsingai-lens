from __future__ import annotations

import math
from typing import Any, Mapping

from domain.core import ResearchUnderstanding


class ResearchUnderstandingService:
    """Project existing Core research views into claim/relation/evidence form."""

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
        record["presentation"] = self._presentation_for(record)
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
        evidence_refs = self._evidence_refs_from_evidence_units(evidence_units)
        evidence_ref_ids_by_unit = self._evidence_ref_ids_by_fact(evidence_refs)
        contexts = self._objective_contexts(context, objective)
        context_ids = [item["context_id"] for item in contexts]
        claims = self._objective_claims(
            payload,
            evidence_units=evidence_units,
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
        )
        relations = self._objective_relations(
            evidence_units,
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
        )
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
                    "warnings": self._understanding_warnings(claims, evidence_refs),
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
                }
            )
        ) or {}

    def _objective_contexts(
        self,
        context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if not context and not objective:
            return []
        return [
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
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        seen: set[str] = set()
        for unit in evidence_units[:12]:
            statement = self._statement_from_evidence_unit(unit)
            if not statement:
                continue
            unit_id = _text(unit.get("evidence_unit_id"))
            evidence_unit_ids = [unit_id] if unit_id else []
            _append_claim(
                claims,
                self._claim(
                    claim_type=self._claim_type_from_unit(unit),
                    statement=statement,
                    source_object_ids=evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(evidence_unit_ids, evidence_ref_ids_by_unit),
                    context_ids=context_ids,
                    confidence=unit.get("confidence"),
                    seen=seen,
                ),
            )
        logic_chain = _mapping(payload.get("logic_chain"))
        summary = _text(logic_chain.get("summary"))
        if summary:
            evidence_unit_ids = _strings(logic_chain.get("evidence_unit_ids"))
            _append_claim(
                claims,
                self._claim(
                    claim_type="finding",
                    statement=summary,
                    source_object_ids=evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        evidence_unit_ids,
                        evidence_ref_ids_by_unit,
                    ),
                    context_ids=context_ids,
                    seen=seen,
                ),
            )
        return claims

    def _objective_relations(
        self,
        evidence_units: list[dict[str, Any]],
        *,
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
    ) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []
        for unit in evidence_units:
            if _text(unit.get("unit_kind")) != "comparison":
                continue
            evidence_unit_id = _text(unit.get("evidence_unit_id"))
            property_name = _text(unit.get("property_normalized"))
            value_payload = _mapping(unit.get("value_payload"))
            direction = _text(value_payload.get("direction"))
            axis = _text(value_payload.get("comparison_axis"))
            sample_context = _display_mapping(_mapping(unit.get("sample_context")))
            baseline_context = _display_mapping(_mapping(unit.get("baseline_context")))
            subject = sample_context or "Observed condition"
            object_text = baseline_context or property_name or "baseline"
            relations.append(
                {
                    "relation_type": self._relation_type_from_direction(direction),
                    "subject": subject,
                    "predicate": direction or axis or "compares with",
                    "object": object_text,
                    "status": "supported",
                    "confidence": unit.get("confidence"),
                    "evidence_ref_ids": self._ref_ids_for(
                        [evidence_unit_id] if evidence_unit_id else [],
                        evidence_ref_ids_by_unit,
                    ),
                    "context_ids": context_ids,
                    "source_object_ids": [evidence_unit_id] if evidence_unit_id else [],
                    "warnings": [],
                }
            )
        return relations

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
        return _dedupe_by_id(refs, "evidence_ref_id")

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
            "quote": _text(ref.get("quote")),
            "href": _text(ref.get("href")),
        }

    def _evidence_refs_from_evidence_units(
        self,
        evidence_units: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for unit in evidence_units:
            unit_id = _text(unit.get("evidence_unit_id"))
            source_refs = _mapping_list(unit.get("source_refs"))
            if not source_refs:
                refs.append(self._evidence_ref_from_unit(unit, source_ref=None))
                continue
            for source_ref in source_refs:
                refs.append(self._evidence_ref_from_unit(unit, source_ref=source_ref))
            if unit_id and _strings(unit.get("evidence_anchor_ids")):
                refs.append(self._evidence_ref_from_unit(unit, source_ref=None))
        return _dedupe_by_id(refs, "evidence_ref_id")

    def _evidence_ref_from_unit(
        self,
        unit: Mapping[str, Any],
        *,
        source_ref: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        source = _mapping(source_ref)
        unit_id = _text(unit.get("evidence_unit_id"))
        source_kind = _text(source.get("source_kind")) or "unknown"
        source_ref_label = (
            _text(source.get("display_label"))
            or _text(source.get("source_ref"))
            or _text(source.get("route_id"))
        )
        evidence_ref_id = _stable_ref_id(
            source_kind,
            _text(unit.get("document_id")),
            [unit_id] if unit_id else [],
            _strings(unit.get("evidence_anchor_ids")),
            source,
        )
        return {
            "evidence_ref_id": evidence_ref_id,
            "source_kind": source_kind,
            "document_id": _text(source.get("document_id")) or _text(unit.get("document_id")),
            "label": source_ref_label or unit_id or evidence_ref_id,
            "locator": {
                key: value
                for key, value in {
                    "source_ref": _text(source.get("source_ref")),
                    "route_id": _text(source.get("route_id")),
                    "source_kind": source_kind,
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
            "quote": _text(source.get("quote")),
            "href": _text(source.get("href")),
        }

    def _statement_from_evidence_unit(self, unit: Mapping[str, Any]) -> str | None:
        unit_kind = _text(unit.get("unit_kind"))
        property_name = _text(unit.get("property_normalized"))
        value_payload = _mapping(unit.get("value_payload"))
        source_value = (
            _text(value_payload.get("source_value_text"))
            or _text(value_payload.get("value"))
            or _text(value_payload.get("statement"))
        )
        unit_text = _text(unit.get("unit"))
        interpretation = _text(unit.get("interpretation"))
        if unit_kind == "comparison":
            return (
                _text(value_payload.get("summary"))
                or _text(value_payload.get("source_value_text"))
                or interpretation
            )
        if interpretation:
            return interpretation
        if property_name and source_value:
            suffix = f" {unit_text}" if unit_text and unit_text not in source_value else ""
            return f"{property_name} is reported as {source_value}{suffix}."
        return source_value

    def _claim_type_from_unit(self, unit: Mapping[str, Any]) -> str:
        unit_kind = _text(unit.get("unit_kind"))
        if unit_kind == "comparison":
            return "comparison"
        if unit_kind in {"characterization", "interpretation"}:
            return "mechanism"
        if unit_kind == "measurement":
            return "measurement"
        return "context"

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

    def _relation_type_from_direction(self, direction: str | None) -> str:
        normalized = (direction or "").lower().replace("-", " ").replace("_", " ")
        if "improv" in normalized:
            return "improves"
        if "reduc" in normalized or "lower" in normalized:
            return "reduces"
        if "increas" in normalized:
            return "increases"
        if "decreas" in normalized:
            return "decreases"
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

    def _understanding_warnings(
        self,
        claims: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
    ) -> list[str]:
        warnings: list[str] = []
        if claims and not evidence_refs:
            warnings.append("claims_without_evidence_refs")
        if any("missing_evidence_ref" in claim.get("warnings", []) for claim in claims):
            warnings.append("some_claims_missing_evidence_refs")
        return warnings

    def _presentation_for(self, record: Mapping[str, Any]) -> dict[str, Any]:
        claims = _mapping_list(record.get("claims"))
        relations = _mapping_list(record.get("relations"))
        evidence_refs = _mapping_list(record.get("evidence_refs"))
        contexts = _mapping_list(record.get("contexts"))
        scope = _mapping(record.get("scope"))
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
        evidence_items = [
            self._presentation_evidence_item(ref)
            for ref in evidence_refs
        ]
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
        context_summaries = [
            self._presentation_context_summary(context)
            for context in contexts
        ]
        material_scope = _dedupe_strings(
            [
                value
                for context in contexts
                for value in _strings(context.get("material_scope"))
            ]
        )
        property_scope = _dedupe_strings(
            [
                value
                for context in contexts
                for value in _strings(context.get("property_scope"))
            ]
        )
        variable_axes = _dedupe_strings(
            [
                value
                for context in contexts
                for value in _display_values(_mapping(context.get("process_context")))
            ]
        )
        review_queue_count = sum(
            1
            for claim in claims
            if self._needs_review(claim)
        )
        return {
            "summary": {
                "title": _text(scope.get("title")) or "Research understanding",
                "material_scope": material_scope,
                "variable_axes": variable_axes,
                "property_scope": property_scope,
                "claim_count": len(claims),
                "relation_count": len(relations),
                "evidence_count": len(evidence_refs),
                "context_count": len(contexts),
                "review_queue_count": review_queue_count,
            },
            "effects": effects,
            "evidence_items": evidence_items,
            "context_summaries": context_summaries,
        }

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
            or _intersects(source_object_ids, _strings(relation.get("source_object_ids")))
        ]
        related_relations = [
            relation
            for relation in relations
            if relation in direct_relations
            or _intersects(context_ids, _strings(relation.get("context_ids")))
        ]
        primary_relation = direct_relations[0] if direct_relations else {}
        contexts = [
            contexts_by_id[context_id]
            for context_id in context_ids
            if context_id in contexts_by_id
        ]
        variable_axis = self._variable_axis_for(primary_relation, contexts)
        target_property = self._target_property_for(claim, primary_relation, contexts)
        evidence_refs = [
            evidence_by_id[ref_id]
            for ref_id in evidence_ref_ids
            if ref_id in evidence_by_id
        ]
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
        return {
            "effect_id": f"effect_{claim_id}",
            "claim_id": claim_id,
            "title": self._effect_title(
                variable_axis=variable_axis,
                target_property=target_property,
                fallback=statement,
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
            "evidence_ref_ids": evidence_ref_ids,
            "context_ids": context_ids,
            "relation_ids": relation_ids,
            "needs_review": self._needs_review(claim),
            "warnings": _strings(claim.get("warnings")),
        }

    def _presentation_evidence_item(self, ref: Mapping[str, Any]) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_ref = _text(locator.get("source_ref"))
        label = _text(ref.get("label"))
        source_kind = _text(ref.get("source_kind")) or "unknown"
        source_label = (
            source_ref
            if _looks_user_facing(source_ref)
            else label
            if _looks_user_facing(label)
            else _source_kind_label(source_kind)
        )
        page = _text(locator.get("page")) or _text(locator.get("page_no"))
        title_parts = [source_label]
        if page:
            title_parts.append(f"p. {page}")
        title = " / ".join(title_parts)
        return {
            "evidence_ref_id": _text(ref.get("evidence_ref_id")) or "",
            "document_id": _text(ref.get("document_id")),
            "title": title,
            "source_label": source_label,
            "source_kind": source_kind,
            "page": page,
            "quote": _text(ref.get("quote")),
            "value_summary": label if _looks_user_facing(label) else "",
            "traceability_status": _text(ref.get("traceability_status")) or "unknown",
            "confidence": ref.get("confidence"),
            "href": _text(ref.get("href")),
        }

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
    ) -> str:
        if variable_axis and target_property:
            return f"{variable_axis} -> {target_property}"
        if target_property:
            return target_property
        if variable_axis:
            return variable_axis
        return _short_text(fallback, limit=96) or "Research finding"

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
        if isinstance(value, Mapping):
            values.extend(_display_values(value))
        elif isinstance(value, (list, tuple, set)):
            values.extend(
                text for item in value if (text := _text(item))
            )
        elif text := _text(value):
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


def _short_text(value: str, *, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


def _intersects(left: list[str] | tuple[str, ...], right: list[str] | tuple[str, ...]) -> bool:
    right_set = set(right)
    return any(item in right_set for item in left)


def _looks_user_facing(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    lower = text.lower()
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
    return _dedupe_strings([str(item).strip() for item in items if str(item).strip()])


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
