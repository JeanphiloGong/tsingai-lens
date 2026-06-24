from __future__ import annotations

from typing import Any, Mapping

from domain.core import ResearchUnderstanding


class ResearchUnderstandingService:
    """Project existing Core research views into claim/relation/evidence form."""

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
        return ResearchUnderstanding.from_mapping(
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
        ).to_record()

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
        return ResearchUnderstanding.from_mapping(
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
        ).to_record()

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
