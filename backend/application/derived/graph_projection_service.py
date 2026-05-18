from __future__ import annotations

import math
from hashlib import sha1
from typing import Any, Mapping


_NODE_TYPE_PRIORITY = {
    "objective": 0,
    "material_system": 1,
    "material_scope": 2,
    "process_sample_context": 3,
    "test_conditions": 4,
    "characterization": 5,
    "measurement_results": 6,
    "controlled_comparisons": 7,
    "mechanism_interpretation": 8,
    "limitations": 9,
}
_STEP_SEQUENCE = (
    ("material_scope", "Material scope"),
    ("process_sample_context", "Process / sample context"),
    ("test_conditions", "Test conditions"),
    ("characterization", "Characterization"),
    ("measurement_results", "Measurement results"),
    ("controlled_comparisons", "Controlled comparisons"),
    ("mechanism_interpretation", "Mechanism / interpretation"),
    ("limitations", "Limitations / uncertainty"),
)
_STEP_ROLE_PRIORITY = {role: index for index, (role, _label) in enumerate(_STEP_SEQUENCE)}
_PLACEHOLDER_VALUES = frozenset({"", "--", "unknown", "none", "null", "n/a"})
_PAPER_LOCAL_CONTEXT_KEYS = frozenset(
    {
        "case",
        "case number",
        "case no",
        "case no.",
        "condition",
        "condition number",
        "condition no",
        "condition no.",
        "id",
        "index",
        "no",
        "no.",
        "number",
        "row",
        "row id",
        "sample",
        "sample id",
        "sample number",
        "sample no",
        "sample no.",
        "specimen",
        "specimen id",
    }
)


def load_core_graph_payload(
    profiles: tuple[dict[str, Any], ...],
    research_objectives: tuple[dict[str, Any], ...],
    objective_evidence_units: tuple[dict[str, Any], ...],
    objective_logic_chains: tuple[dict[str, Any], ...],
    max_nodes: int,
    min_weight: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    doc_records = {
        document_id: _build_document_record(row)
        for row in profiles
        if (document_id := _as_text(row.get("document_id")))
    }
    objective_records = {
        objective_id: _build_objective_record(row)
        for row in research_objectives
        if (objective_id := _as_text(row.get("objective_id")))
    }
    units_by_id = {
        evidence_unit_id: row
        for row in objective_evidence_units
        if (evidence_unit_id := _as_text(row.get("evidence_unit_id")))
    }

    node_index: dict[str, dict[str, Any]] = {}
    edge_index: dict[str, dict[str, Any]] = {}

    for record in objective_records.values():
        _put_node(node_index, record["node"])

    for chain in _iter_logic_chain_rows(
        research_objectives=research_objectives,
        objective_evidence_units=objective_evidence_units,
        objective_logic_chains=objective_logic_chains,
    ):
        projection = _build_logic_chain_step_projection(
            chain=chain,
            objective_records=objective_records,
            units_by_id=units_by_id,
            doc_records=doc_records,
        )
        for node in projection["nodes"]:
            _put_node(node_index, node)
        for edge in projection["edges"]:
            _put_edge(edge_index, edge)

    nodes = list(node_index.values())
    edges = list(edge_index.values())
    if min_weight > 0:
        edges = [
            edge
            for edge in edges
            if edge.get("weight") is not None and float(edge["weight"]) >= float(min_weight)
        ]

    nodes, edges, truncated = _truncate_graph(nodes, edges, max_nodes)
    return nodes, edges, truncated


def _build_document_record(row: Mapping[str, Any]) -> dict[str, Any]:
    document_id = _as_text(row.get("document_id")) or ""
    title = _as_text(row.get("title"))
    source_filename = _as_text(row.get("source_filename"))
    return {
        "document_id": document_id,
        "label": title or source_filename or document_id,
    }


def _build_objective_record(row: Mapping[str, Any]) -> dict[str, Any]:
    objective_id = _as_text(row.get("objective_id")) or ""
    question = _as_text(row.get("question")) or objective_id
    material_scope = _string_list(row.get("material_scope"))
    process_axes = _string_list(row.get("process_axes"))
    property_axes = _string_list(row.get("property_axes"))
    detail_rows = [
        _drop_empty_values(
            {
                "label": "Research objective",
                "objective_id": objective_id,
                "material": _join_terms(material_scope),
                "process": _join_terms(process_axes),
                "property": _join_terms(property_axes),
                "interpretation": _as_text(row.get("comparison_intent")),
                "confidence": row.get("confidence"),
            }
        )
    ]
    return {
        "objective_id": objective_id,
        "question": question,
        "material_scope": material_scope,
        "process_axes": process_axes,
        "property_axes": property_axes,
        "node": {
            "id": f"obj:{objective_id}",
            "label": _shorten_text(question, 120),
            "type": "objective",
            "role": "research_objective",
            "summary": question,
            "metrics": {
                "material_scope_count": len(material_scope),
                "process_axis_count": len(process_axes),
                "property_axis_count": len(property_axes),
            },
            "detail_rows": detail_rows,
            "objective_id": objective_id,
            "degree": 0,
        },
    }


def _iter_logic_chain_rows(
    *,
    research_objectives: tuple[dict[str, Any], ...],
    objective_evidence_units: tuple[dict[str, Any], ...],
    objective_logic_chains: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    if objective_logic_chains:
        return list(objective_logic_chains)

    units_by_objective: dict[str, list[str]] = {}
    for unit in objective_evidence_units:
        objective_id = _as_text(unit.get("objective_id"))
        evidence_unit_id = _as_text(unit.get("evidence_unit_id"))
        if objective_id and evidence_unit_id:
            units_by_objective.setdefault(objective_id, []).append(evidence_unit_id)

    chains: list[dict[str, Any]] = []
    for objective in research_objectives:
        objective_id = _as_text(objective.get("objective_id"))
        if not objective_id:
            continue
        evidence_unit_ids = units_by_objective.get(objective_id, [])
        if not evidence_unit_ids:
            continue
        chains.append(
            {
                "logic_chain_id": f"fallback_{sha1(objective_id.encode('utf-8')).hexdigest()[:12]}",
                "objective_id": objective_id,
                "chain_scope": "objective",
                "document_id": None,
                "question": objective.get("question"),
                "evidence_unit_ids": evidence_unit_ids,
                "chain_payload": {},
                "summary": objective.get("question"),
                "confidence": objective.get("confidence"),
            }
        )
    return chains


def _build_logic_chain_step_projection(
    *,
    chain: Mapping[str, Any],
    objective_records: dict[str, dict[str, Any]],
    units_by_id: dict[str, dict[str, Any]],
    doc_records: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    logic_chain_id = _as_text(chain.get("logic_chain_id"))
    objective_id = _as_text(chain.get("objective_id"))
    if not logic_chain_id or not objective_id or objective_id not in objective_records:
        return {"nodes": [], "edges": []}

    units = [
        units_by_id[evidence_unit_id]
        for evidence_unit_id in _string_list(chain.get("evidence_unit_ids"))
        if evidence_unit_id in units_by_id
    ]
    chain_payload = _as_mapping(chain.get("chain_payload"))
    objective_record = objective_records[objective_id]
    material_nodes = _build_material_system_nodes(
        logic_chain_id=logic_chain_id,
        objective_id=objective_id,
        objective_record=objective_record,
        chain_payload=chain_payload,
        units=units,
        doc_records=doc_records,
    )
    step_nodes = [
        _build_step_node(
            logic_chain_id=logic_chain_id,
            objective_id=objective_id,
            chain=chain,
            objective_record=objective_record,
            role=role,
            label=label,
            units=units,
            doc_records=doc_records,
            chain_payload=chain_payload,
        )
        for role, label in _STEP_SEQUENCE
    ]
    nodes = [*material_nodes, *step_nodes]
    edges: list[dict[str, Any]] = []
    first_step_id = _step_node_id(logic_chain_id, _STEP_SEQUENCE[0][0])
    if material_nodes:
        for material_node in material_nodes:
            material_node_id = str(material_node["id"])
            edges.append(
                {
                    "id": f"edge:obj:{objective_id}:{material_node_id}",
                    "source": f"obj:{objective_id}",
                    "target": material_node_id,
                    "weight": 1.0,
                    "edge_description": "objective_to_material_system",
                    "source_role": "research_objective",
                    "target_role": "material_system",
                }
            )
            edges.append(
                {
                    "id": f"edge:{material_node_id}:step:{logic_chain_id}:{_STEP_SEQUENCE[0][0]}",
                    "source": material_node_id,
                    "target": first_step_id,
                    "weight": 1.0,
                    "edge_description": "material_system_to_material_scope",
                    "source_role": "material_system",
                    "target_role": _STEP_SEQUENCE[0][0],
                }
            )
    else:
        edges.append(
            {
                "id": f"edge:obj:{objective_id}:step:{logic_chain_id}:{_STEP_SEQUENCE[0][0]}",
                "source": f"obj:{objective_id}",
                "target": first_step_id,
                "weight": 1.0,
                "edge_description": "objective_to_material_scope",
                "source_role": "research_objective",
                "target_role": _STEP_SEQUENCE[0][0],
            }
        )
    for (source_role, _source_label), (target_role, _target_label) in zip(
        _STEP_SEQUENCE,
        _STEP_SEQUENCE[1:],
        strict=False,
    ):
        edges.append(
            {
                "id": f"edge:step:{logic_chain_id}:{source_role}:{target_role}",
                "source": _step_node_id(logic_chain_id, source_role),
                "target": _step_node_id(logic_chain_id, target_role),
                "weight": 1.0,
                "edge_description": "semantic_chain_step_to_step",
                "source_role": source_role,
                "target_role": target_role,
            }
        )
    return {"nodes": nodes, "edges": edges}


def _build_material_system_nodes(
    *,
    logic_chain_id: str,
    objective_id: str,
    objective_record: Mapping[str, Any],
    chain_payload: Mapping[str, Any],
    units: list[dict[str, Any]],
    doc_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    material_labels = _collect_material_labels(
        objective_record=objective_record,
        chain_payload=chain_payload,
        units=units,
    )
    return [
        _build_material_system_node(
            objective_id=objective_id,
            logic_chain_id=logic_chain_id,
            material_label=material_label,
            units=units,
            doc_records=doc_records,
        )
        for material_label in material_labels
    ]


def _build_material_system_node(
    *,
    objective_id: str,
    logic_chain_id: str,
    material_label: str,
    units: list[dict[str, Any]],
    doc_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    matching_units = [
        unit
        for unit in units
        if (_material_label(unit.get("material_system")) or "").casefold()
        == material_label.casefold()
    ]
    evidence_rows = [
        _evidence_unit_detail_row(unit, doc_records)
        for unit in matching_units
    ]
    paper_ids = {
        document_id
        for row in evidence_rows
        if (document_id := _as_text(row.get("document_id")))
    }
    detail_rows = [
        _drop_empty_values(
            {
                "label": material_label,
                "material": material_label,
                "objective_id": objective_id,
                "logic_chain_id": logic_chain_id,
                "paper_count": len(paper_ids),
                "evidence_count": len(matching_units),
            }
        )
    ]
    detail_rows.extend(evidence_rows)
    return {
        "id": _material_system_node_id(material_label),
        "label": _shorten_text(material_label, 96),
        "type": "material_system",
        "role": "material_system",
        "summary": f"{material_label} material system across this collection.",
        "metrics": {
            "row_count": len(detail_rows),
            "paper_count": len(paper_ids),
            "evidence_count": len(matching_units),
            "objective_count": 1,
            "logic_chain_count": 1,
        },
        "detail_rows": detail_rows,
        "objective_id": None,
        "logic_chain_id": None,
        "degree": 0,
    }


def _collect_material_labels(
    *,
    objective_record: Mapping[str, Any],
    chain_payload: Mapping[str, Any],
    units: list[dict[str, Any]],
) -> list[str]:
    objective_payload = _as_mapping(chain_payload.get("objective"))
    candidates = [
        *_string_list(objective_record.get("material_scope")),
        *_string_list(objective_payload.get("material_scope")),
    ]
    candidates.extend(
        material_label
        for unit in units
        if (material_label := _material_label(unit.get("material_system")))
    )

    labels: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        label = _clean_graph_text(candidate)
        if not label:
            continue
        key = label.casefold()
        if key in _PLACEHOLDER_VALUES or key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return labels


def _build_step_node(
    *,
    logic_chain_id: str,
    objective_id: str,
    chain: Mapping[str, Any],
    objective_record: Mapping[str, Any],
    role: str,
    label: str,
    units: list[dict[str, Any]],
    doc_records: dict[str, dict[str, Any]],
    chain_payload: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _step_detail_rows(
        role=role,
        chain=chain,
        objective_record=objective_record,
        units=units,
        doc_records=doc_records,
        chain_payload=chain_payload,
    )
    paper_ids = {
        document_id
        for row in rows
        if (document_id := _as_text(row.get("document_id")))
    }
    summary = _step_summary(role=role, rows=rows, chain=chain, chain_payload=chain_payload)
    return {
        "id": _step_node_id(logic_chain_id, role),
        "label": label,
        "type": role,
        "role": role,
        "summary": summary,
        "metrics": {
            "row_count": len(rows),
            "paper_count": len(paper_ids),
            "evidence_count": sum(1 for row in rows if row.get("evidence_unit_id")),
        },
        "detail_rows": rows,
        "objective_id": objective_id,
        "logic_chain_id": logic_chain_id,
        "degree": 0,
    }


def _step_detail_rows(
    *,
    role: str,
    chain: Mapping[str, Any],
    objective_record: Mapping[str, Any],
    units: list[dict[str, Any]],
    doc_records: dict[str, dict[str, Any]],
    chain_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if role == "material_scope":
        objective = _as_mapping(chain_payload.get("objective"))
        material_scope = _string_list(objective.get("material_scope")) or _string_list(
            objective_record.get("material_scope")
        )
        process_axes = _string_list(objective.get("process_axes")) or _string_list(
            objective_record.get("process_axes")
        )
        property_axes = _string_list(objective.get("property_axes")) or _string_list(
            objective_record.get("property_axes")
        )
        return [
            _drop_empty_values(
                {
                    "label": "Objective scope",
                    "material": _join_terms(material_scope),
                    "process": _join_terms(process_axes),
                    "property": _join_terms(property_axes),
                    "interpretation": _as_text(chain.get("question"))
                    or _as_text(objective_record.get("question")),
                    "confidence": chain.get("confidence"),
                }
            )
        ]

    if role == "process_sample_context":
        return [
            _evidence_unit_detail_row(unit, doc_records)
            for unit in units
            if unit.get("sample_context")
            or unit.get("process_context")
            or unit.get("resolved_condition")
            or unit.get("join_keys")
        ]

    if role == "test_conditions":
        return [
            _evidence_unit_detail_row(unit, doc_records)
            for unit in units
            if _as_text(unit.get("unit_kind")) == "test_condition"
            or _context_label(unit.get("test_condition"), allow_paper_local_keys=False)
        ]

    if role == "characterization":
        return [
            _evidence_unit_detail_row(unit, doc_records)
            for unit in units
            if _as_text(unit.get("unit_kind")) == "characterization"
        ]

    if role == "measurement_results":
        return [
            _evidence_unit_detail_row(unit, doc_records)
            for unit in units
            if _as_text(unit.get("unit_kind")) == "measurement"
        ]

    if role == "controlled_comparisons":
        return [
            _evidence_unit_detail_row(unit, doc_records)
            for unit in units
            if _as_text(unit.get("unit_kind")) == "comparison"
        ]

    if role == "mechanism_interpretation":
        return [
            _evidence_unit_detail_row(unit, doc_records)
            for unit in units
            if _as_text(unit.get("unit_kind")) == "interpretation"
            or _clean_graph_text(unit.get("interpretation"))
        ]

    if role == "limitations":
        rows = [
            _drop_empty_values(
                {
                    "label": "Unresolved evidence",
                    "document_id": unit.get("document_id"),
                    "paper": _document_label(unit, doc_records),
                    "evidence_unit_id": unit.get("evidence_unit_id"),
                    "source": _source_refs_label(unit.get("source_refs")),
                    "interpretation": unit.get("resolution_status"),
                    "confidence": unit.get("confidence"),
                }
            )
            for unit in units
            if _as_text(unit.get("resolution_status")) not in {None, "resolved"}
        ]
        rows.extend(_gap_detail_rows(chain_payload))
        return rows

    return []


def _evidence_unit_detail_row(
    unit: Mapping[str, Any],
    doc_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return _drop_empty_values(
        {
            "label": _evidence_unit_label(unit),
            "row_type": unit.get("unit_kind"),
            "paper": _document_label(unit, doc_records),
            "document_id": unit.get("document_id"),
            "evidence_unit_id": unit.get("evidence_unit_id"),
            "property": unit.get("property_normalized"),
            "value": _value_payload_label(unit.get("value_payload"), unit.get("unit")),
            "unit": unit.get("unit"),
            "material": _material_label(unit.get("material_system")),
            "sample": _context_label(
                _merge_context(unit.get("sample_context"), unit.get("join_keys")),
                allow_paper_local_keys=True,
            ),
            "process": _context_label(
                _merge_context(unit.get("process_context"), unit.get("resolved_condition")),
                allow_paper_local_keys=False,
            ),
            "test_condition": _context_label(
                unit.get("test_condition"),
                allow_paper_local_keys=False,
            ),
            "baseline": _context_label(
                unit.get("baseline_context"),
                allow_paper_local_keys=True,
            ),
            "interpretation": unit.get("interpretation"),
            "source": _source_refs_label(unit.get("source_refs")),
            "resolution_status": unit.get("resolution_status"),
            "confidence": unit.get("confidence"),
        }
    )


def _gap_detail_rows(chain_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    cross_paper = _as_mapping(chain_payload.get("cross_paper"))
    rows: list[dict[str, Any]] = []
    for gap in _as_list(cross_paper.get("gaps")):
        gap_text = _clean_graph_text(gap)
        if gap_text:
            rows.append({"label": "Cross-paper gap", "interpretation": gap_text})
    for paper_chain in _as_list(chain_payload.get("paper_chains")):
        paper_chain_mapping = _as_mapping(paper_chain)
        document_id = _as_text(paper_chain_mapping.get("document_id"))
        resolution = _as_mapping(paper_chain_mapping.get("resolution"))
        for gap in _as_list(resolution.get("gaps")):
            gap_text = _clean_graph_text(gap)
            if gap_text:
                rows.append(
                    _drop_empty_values(
                        {
                            "label": "Paper gap",
                            "document_id": document_id,
                            "interpretation": gap_text,
                        }
                    )
                )
    return rows


def _step_summary(
    *,
    role: str,
    rows: list[dict[str, Any]],
    chain: Mapping[str, Any],
    chain_payload: Mapping[str, Any],
) -> str:
    if role == "material_scope":
        return (
            _as_text(chain.get("summary"))
            or _as_text(chain.get("question"))
            or "Research objective scope."
        )
    if role == "measurement_results":
        ranges = _as_list(_as_mapping(chain_payload.get("cross_paper")).get("measurement_value_ranges"))
        if ranges:
            return f"{len(rows)} measurement rows across {len(ranges)} value ranges."
    if not rows:
        return "No extracted evidence rows for this chain step."
    return f"{len(rows)} evidence rows support this chain step."


def _step_node_id(logic_chain_id: str, role: str) -> str:
    return f"step:{logic_chain_id}:{role}"


def _material_system_node_id(material_label: str) -> str:
    suffix = sha1(material_label.casefold().encode("utf-8")).hexdigest()[:12]
    return f"material_system:{suffix}"


def _truncate_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    max_nodes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    degrees = _compute_degrees(edges)
    for node in nodes:
        node["degree"] = degrees.get(str(node.get("id")), 0)

    truncated = len(nodes) > max_nodes
    selected_nodes = _select_truncated_nodes(nodes, max_nodes) if truncated else list(nodes)
    allowed_ids = {str(node["id"]) for node in selected_nodes}
    selected_edges = [
        edge
        for edge in edges
        if str(edge.get("source")) in allowed_ids and str(edge.get("target")) in allowed_ids
    ]
    degrees = _compute_degrees(selected_edges)
    for node in selected_nodes:
        node["degree"] = degrees.get(str(node.get("id")), 0)
    return selected_nodes, selected_edges, truncated


def _compute_degrees(edges: list[dict[str, Any]]) -> dict[str, int]:
    degrees: dict[str, int] = {}
    for edge in edges:
        source = _as_text(edge.get("source"))
        target = _as_text(edge.get("target"))
        if source:
            degrees[source] = degrees.get(source, 0) + 1
        if target:
            degrees[target] = degrees.get(target, 0) + 1
    return degrees


def _select_truncated_nodes(
    nodes: list[dict[str, Any]],
    max_nodes: int,
) -> list[dict[str, Any]]:
    return _ordered_nodes(nodes)[:max_nodes]


def _evidence_unit_label(row: Mapping[str, Any]) -> str:
    unit_kind = _as_text(row.get("unit_kind")) or "evidence"
    property_name = _clean_graph_text(row.get("property_normalized"))
    value_text = _value_payload_label(row.get("value_payload"), row.get("unit"))
    interpretation = _clean_graph_text(row.get("interpretation"))
    parts = [part for part in (property_name, value_text, interpretation) if part]
    if parts:
        return " | ".join(parts)
    return _as_text(row.get("evidence_unit_id")) or unit_kind


def _value_payload_label(value_payload: Any, unit: Any) -> str | None:
    payload = _as_mapping(value_payload)
    value = _clean_graph_text(
        payload.get("source_value_text")
        or payload.get("value")
        or payload.get("text")
        or payload.get("trend")
    )
    unit_text = _clean_graph_text(unit)
    if value and unit_text and unit_text.lower() not in value.lower():
        return f"{value} {unit_text}"
    return value


def _material_label(value: Any) -> str | None:
    material = _as_mapping(value)
    for key in ("family", "name", "material", "material_system", "alloy"):
        text = _clean_graph_text(material.get(key))
        if text and text.casefold() not in _PLACEHOLDER_VALUES:
            return text
    return _context_label(material, allow_paper_local_keys=False)


def _document_label(
    row: Mapping[str, Any],
    doc_records: dict[str, dict[str, Any]],
) -> str | None:
    document_id = _as_text(row.get("document_id"))
    if not document_id:
        return None
    return _as_text(doc_records.get(document_id, {}).get("label")) or document_id


def _source_refs_label(value: Any) -> str | None:
    parts: list[str] = []
    for ref in _as_list(value):
        ref_mapping = _as_mapping(ref)
        source_kind = _as_text(ref_mapping.get("source_kind"))
        source_ref = _as_text(ref_mapping.get("source_ref"))
        page = _as_text(ref_mapping.get("page"))
        label = ":".join(part for part in (source_kind, source_ref) if part)
        if page:
            label = f"{label} p.{page}" if label else f"p.{page}"
        if label:
            parts.append(label)
    return "; ".join(parts) if parts else None


def _context_label(value: Any, *, allow_paper_local_keys: bool) -> str | None:
    items = _filter_context(value, allow_paper_local_keys=allow_paper_local_keys)
    if not items:
        return None
    parts = [f"{key}: {val}" for key, val in sorted(items.items())]
    return "; ".join(parts)


def _filter_context(value: Any, *, allow_paper_local_keys: bool) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, raw_value in _as_mapping(value).items():
        key_text = _clean_graph_text(key)
        value_text = _context_value_text(raw_value)
        if not key_text or not value_text:
            continue
        if key_text.casefold() in _PLACEHOLDER_VALUES:
            continue
        if value_text.casefold() in _PLACEHOLDER_VALUES:
            continue
        if not allow_paper_local_keys and _is_paper_local_context_key(key_text):
            continue
        result[key_text] = value_text
    return result


def _context_value_text(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _context_label(value, allow_paper_local_keys=True)
    if isinstance(value, (list, tuple, set)):
        parts = [
            part
            for item in value
            if (part := _context_value_text(item))
        ]
        return ", ".join(parts) if parts else None
    return _clean_graph_text(value)


def _merge_context(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        merged.update(_as_mapping(value))
    return merged


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _is_paper_local_context_key(value: str) -> bool:
    normalized = value.casefold().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    return normalized in _PAPER_LOCAL_CONTEXT_KEYS


def _ordered_nodes(nodes: Any) -> list[dict[str, Any]]:
    return sorted(
        list(nodes),
        key=lambda node: (
            _NODE_TYPE_PRIORITY.get(str(node.get("type") or ""), 99),
            _STEP_ROLE_PRIORITY.get(str(node.get("role") or ""), 99),
            str(node.get("label") or node.get("id") or ""),
        ),
    )


def _put_node(index: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    node_id = str(node["id"])
    existing = index.get(node_id)
    if existing and existing.get("type") == "material_system" and node.get("type") == "material_system":
        _merge_material_system_node(existing, node)
        return
    index[node_id] = node


def _merge_material_system_node(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    rows = [
        *[row for row in _as_list(existing.get("detail_rows")) if isinstance(row, Mapping)],
        *[row for row in _as_list(incoming.get("detail_rows")) if isinstance(row, Mapping)],
    ]
    deduped_rows: list[dict[str, Any]] = []
    seen_rows: set[tuple[tuple[str, str], ...]] = set()
    for row in rows:
        row_dict = dict(row)
        key = tuple(sorted((str(item_key), str(item_value)) for item_key, item_value in row_dict.items()))
        if key in seen_rows:
            continue
        seen_rows.add(key)
        deduped_rows.append(row_dict)

    objective_ids = {
        objective_id
        for row in deduped_rows
        if (objective_id := _as_text(row.get("objective_id")))
    }
    logic_chain_ids = {
        logic_chain_id
        for row in deduped_rows
        if (logic_chain_id := _as_text(row.get("logic_chain_id")))
    }
    paper_ids = {
        document_id
        for row in deduped_rows
        if (document_id := _as_text(row.get("document_id")))
    }
    evidence_ids = {
        evidence_unit_id
        for row in deduped_rows
        if (evidence_unit_id := _as_text(row.get("evidence_unit_id")))
    }

    existing["detail_rows"] = deduped_rows
    existing["metrics"] = {
        **_as_mapping(existing.get("metrics")),
        "row_count": len(deduped_rows),
        "paper_count": len(paper_ids),
        "evidence_count": len(evidence_ids),
        "objective_count": len(objective_ids),
        "logic_chain_count": len(logic_chain_ids),
    }
    existing["summary"] = (
        f"{existing.get('label')} material system across "
        f"{len(objective_ids) or 1} research objective(s)."
    )


def _put_edge(index: dict[str, dict[str, Any]], edge: dict[str, Any]) -> None:
    index[str(edge["id"])] = edge


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            text = _as_text(item)
            if text:
                items.append(text)
        return items
    text = _as_text(value)
    return [text] if text else []


def _join_terms(values: list[str]) -> str | None:
    return ", ".join(values) if values else None


def _drop_empty_values(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if value is not None and value != "" and value != [] and value != {}
    }


def _shorten_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _clean_graph_text(value: Any) -> str | None:
    text = _as_text(value)
    if not text:
        return None
    return " ".join(text.split())


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "load_core_graph_payload",
]
