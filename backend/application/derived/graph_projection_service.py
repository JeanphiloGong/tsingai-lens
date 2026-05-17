from __future__ import annotations

import math
from hashlib import sha1
from typing import Any, Mapping


_NODE_TYPE_PRIORITY = {
    "objective": 0,
    "logic_chain": 1,
    "document": 2,
    "evidence": 3,
    "controlled_comparison": 4,
    "measurement": 5,
    "material": 6,
    "property": 7,
    "process": 8,
    "sample": 9,
    "test_condition": 10,
    "baseline": 11,
    "mechanism": 12,
    "characterization": 13,
}
_BACKBONE_NODE_TYPES = frozenset(
    {"objective", "logic_chain", "document", "evidence", "measurement", "controlled_comparison"}
)
_BACKBONE_TRUNCATION_SHARE = 0.6
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
_TEST_CONDITION_SIGNALS = (
    "test",
    "method",
    "standard",
    "environment",
    "medium",
    "solution",
    "electrolyte",
    "strain",
    "load",
    "stress ratio",
    "frequency",
    "cycle",
    "ph",
)


def load_core_graph_payload(
    profiles: tuple[dict[str, Any], ...],
    research_objectives: tuple[dict[str, Any], ...],
    objective_evidence_units: tuple[dict[str, Any], ...],
    objective_logic_chains: tuple[dict[str, Any], ...],
    max_nodes: int,
    min_weight: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    doc_records: dict[str, dict[str, Any]] = {}
    objective_records: dict[str, dict[str, Any]] = {}
    evidence_unit_records: dict[str, dict[str, Any]] = {}

    node_index: dict[str, dict[str, Any]] = {}
    edge_index: dict[str, dict[str, Any]] = {}

    for row in profiles:
        document_id = _as_text(row.get("document_id"))
        if not document_id:
            continue
        record = _build_document_record(row)
        doc_records[document_id] = record
        _put_node(node_index, record["node"])

    for row in research_objectives:
        objective_id = _as_text(row.get("objective_id"))
        if not objective_id:
            continue
        record = _build_objective_record(row)
        objective_records[objective_id] = record
        _put_node(node_index, record["node"])

    for row in objective_evidence_units:
        evidence_unit_id = _as_text(row.get("evidence_unit_id"))
        if not evidence_unit_id:
            continue
        record = _build_evidence_unit_projection(
            row=row,
            doc_records=doc_records,
            objective_records=objective_records,
        )
        evidence_unit_records[evidence_unit_id] = record
        _put_node(node_index, record["node"])
        for semantic_node in record["semantic_nodes"]:
            _put_node(node_index, semantic_node)
        for edge in record["edges"]:
            _put_edge(edge_index, edge)

    for row in objective_logic_chains:
        projection = _build_logic_chain_projection(
            row=row,
            objective_records=objective_records,
            evidence_unit_records=evidence_unit_records,
            doc_records=doc_records,
        )
        if projection is None:
            continue
        _put_node(node_index, projection["node"])
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
    label = title or source_filename or document_id
    return {
        "document_id": document_id,
        "node": {
            "id": f"doc:{document_id}",
            "label": label,
            "type": "document",
            "degree": 0,
        },
    }


def _build_objective_record(row: Mapping[str, Any]) -> dict[str, Any]:
    objective_id = _as_text(row.get("objective_id")) or ""
    question = _as_text(row.get("question")) or objective_id
    return {
        "objective_id": objective_id,
        "node": {
            "id": f"obj:{objective_id}",
            "label": _shorten_text(question, 120),
            "type": "objective",
            "degree": 0,
        },
    }


def _build_evidence_unit_projection(
    *,
    row: Mapping[str, Any],
    doc_records: dict[str, dict[str, Any]],
    objective_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    evidence_id = _as_text(row.get("evidence_unit_id")) or ""
    document_id = _as_text(row.get("document_id"))
    objective_id = _as_text(row.get("objective_id"))
    node_type = _evidence_unit_node_type(row)
    node = {
        "id": f"evi:{evidence_id}",
        "label": _shorten_text(_evidence_unit_label(row), 96),
        "type": node_type,
        "degree": 0,
    }
    edges: list[dict[str, Any]] = []
    if document_id and document_id in doc_records:
        edges.append(
            {
                "id": f"edge:doc:{document_id}:evi:{evidence_id}",
                "source": f"doc:{document_id}",
                "target": f"evi:{evidence_id}",
                "weight": 1.0,
                "edge_description": "document_to_evidence",
            }
        )
    if objective_id and objective_id in objective_records:
        edges.append(
            {
                "id": f"edge:obj:{objective_id}:evi:{evidence_id}",
                "source": f"obj:{objective_id}",
                "target": f"evi:{evidence_id}",
                "weight": 1.0,
                "edge_description": "objective_to_evidence",
            }
        )

    semantic_nodes: list[dict[str, Any]] = []
    semantic_edges: list[dict[str, Any]] = []
    for semantic_node, edge_description in _semantic_projections_for_evidence_unit(row):
        semantic_nodes.append(semantic_node)
        semantic_edges.append(
            {
                "id": f"edge:evi:{evidence_id}:{semantic_node['id']}",
                "source": f"evi:{evidence_id}",
                "target": semantic_node["id"],
                "weight": 1.0,
                "edge_description": edge_description,
            }
        )
    edges.extend(semantic_edges)
    return {
        "node": node,
        "semantic_nodes": semantic_nodes,
        "edges": edges,
    }


def _build_logic_chain_projection(
    *,
    row: Mapping[str, Any],
    objective_records: dict[str, dict[str, Any]],
    evidence_unit_records: dict[str, dict[str, Any]],
    doc_records: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    logic_chain_id = _as_text(row.get("logic_chain_id"))
    if not logic_chain_id:
        return None
    objective_id = _as_text(row.get("objective_id"))
    document_id = _as_text(row.get("document_id"))
    label = _as_text(row.get("summary")) or _as_text(row.get("question")) or logic_chain_id
    node = {
        "id": f"chain:{logic_chain_id}",
        "label": _shorten_text(label, 120),
        "type": "logic_chain",
        "degree": 0,
    }
    edges: list[dict[str, Any]] = []
    if objective_id and objective_id in objective_records:
        edges.append(
            {
                "id": f"edge:obj:{objective_id}:chain:{logic_chain_id}",
                "source": f"obj:{objective_id}",
                "target": f"chain:{logic_chain_id}",
                "weight": 1.0,
                "edge_description": "objective_to_logic_chain",
            }
        )
    if document_id and document_id in doc_records:
        edges.append(
            {
                "id": f"edge:doc:{document_id}:chain:{logic_chain_id}",
                "source": f"doc:{document_id}",
                "target": f"chain:{logic_chain_id}",
                "weight": 1.0,
                "edge_description": "document_to_logic_chain",
            }
        )
    for evidence_id in _string_list(row.get("evidence_unit_ids")):
        if evidence_id not in evidence_unit_records:
            continue
        edges.append(
            {
                "id": f"edge:chain:{logic_chain_id}:evi:{evidence_id}",
                "source": f"chain:{logic_chain_id}",
                "target": f"evi:{evidence_id}",
                "weight": 1.0,
                "edge_description": "logic_chain_to_evidence",
            }
        )
    return {"node": node, "edges": edges}


def _semantic_projections_for_evidence_unit(
    row: Mapping[str, Any],
) -> list[tuple[dict[str, Any], str]]:
    projections: list[tuple[dict[str, Any], str]] = []
    material = _material_label(row.get("material_system"))
    if material:
        projections.append(
            (_semantic_node("mat", "material", material), "evidence_to_material")
        )
    property_name = _clean_graph_text(row.get("property_normalized"))
    if property_name:
        projections.append(
            (_semantic_node("prop", "property", property_name), "evidence_to_property")
        )
    sample_label = _context_label(
        _merge_context(row.get("sample_context"), row.get("join_keys")),
        allow_paper_local_keys=True,
    )
    if sample_label:
        projections.append(
            (_semantic_node("sample", "sample", sample_label), "evidence_to_sample")
        )
    process_label = _context_label(
        _merge_context(row.get("process_context"), row.get("resolved_condition")),
        allow_paper_local_keys=False,
    )
    if process_label:
        projections.append(
            (_semantic_node("proc", "process", process_label), "evidence_to_process")
        )
    test_condition_label = _test_condition_label(row)
    if test_condition_label:
        projections.append(
            (
                _semantic_node("tc", "test_condition", test_condition_label),
                "evidence_to_test_condition",
            )
        )
    baseline_label = _context_label(row.get("baseline_context"), allow_paper_local_keys=True)
    if baseline_label:
        projections.append(
            (_semantic_node("base", "baseline", baseline_label), "evidence_to_baseline")
        )
    return projections


def _truncate_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    max_nodes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    degrees = _compute_degrees(edges)
    for node in nodes:
        node["degree"] = degrees.get(str(node.get("id")), 0)

    truncated = len(nodes) > max_nodes
    if truncated:
        selected_nodes = _select_truncated_nodes(nodes, edges, max_nodes)
    else:
        selected_nodes = list(nodes)

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
    edges: list[dict[str, Any]],
    max_nodes: int,
) -> list[dict[str, Any]]:
    node_lookup = {str(node["id"]): node for node in nodes}
    ordered_backbone = _ordered_nodes(
        node for node in nodes if str(node.get("type")) in _BACKBONE_NODE_TYPES
    )
    ordered_semantic = _ordered_nodes(
        node for node in nodes if str(node.get("type")) not in _BACKBONE_NODE_TYPES
    )
    if len(ordered_backbone) <= max_nodes:
        return _fill_truncation_budget(
            selected_nodes=ordered_backbone,
            fallback_nodes=ordered_semantic,
            max_nodes=max_nodes,
        )

    backbone_budget = min(
        len(ordered_backbone),
        max(math.ceil(max_nodes * _BACKBONE_TRUNCATION_SHARE), 1),
    )
    selected_backbone = ordered_backbone[:backbone_budget]
    selected_comparison_ids = {
        str(node["id"])
        for node in selected_backbone
        if str(node.get("type")) == "comparison"
    }
    ordered_adjacent_semantic = _ordered_nodes(
        node_lookup[node_id]
        for node_id in _semantic_neighbors_of_comparisons(edges, selected_comparison_ids)
        if node_id in node_lookup
    )
    selected_nodes = _fill_truncation_budget(
        selected_nodes=selected_backbone,
        fallback_nodes=ordered_adjacent_semantic,
        max_nodes=max_nodes,
    )
    if len(selected_nodes) < max_nodes:
        remaining_backbone = ordered_backbone[backbone_budget:]
        selected_nodes = _fill_truncation_budget(
            selected_nodes=selected_nodes,
            fallback_nodes=remaining_backbone,
            max_nodes=max_nodes,
        )
    if len(selected_nodes) < max_nodes:
        selected_nodes = _fill_truncation_budget(
            selected_nodes=selected_nodes,
            fallback_nodes=ordered_semantic,
            max_nodes=max_nodes,
        )
    return selected_nodes


def _fill_truncation_budget(
    *,
    selected_nodes: list[dict[str, Any]],
    fallback_nodes: list[dict[str, Any]],
    max_nodes: int,
) -> list[dict[str, Any]]:
    selected = list(selected_nodes)
    selected_ids = {str(node["id"]) for node in selected}
    for node in fallback_nodes:
        node_id = str(node["id"])
        if node_id in selected_ids:
            continue
        selected.append(node)
        selected_ids.add(node_id)
        if len(selected) >= max_nodes:
            break
    return selected


def _semantic_neighbors_of_comparisons(
    edges: list[dict[str, Any]],
    comparison_ids: set[str],
) -> list[str]:
    neighbor_ids: set[str] = set()
    for edge in edges:
        source = _as_text(edge.get("source"))
        target = _as_text(edge.get("target"))
        if source in comparison_ids and target and not target.startswith("evi:"):
            neighbor_ids.add(target)
    return list(neighbor_ids)


def _evidence_unit_node_type(row: Mapping[str, Any]) -> str:
    unit_kind = (_as_text(row.get("unit_kind")) or "evidence").casefold()
    if unit_kind == "measurement":
        return "measurement"
    if unit_kind == "comparison":
        return "controlled_comparison"
    if unit_kind == "interpretation":
        return "mechanism"
    if unit_kind == "characterization":
        return "characterization"
    return "evidence"


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


def _test_condition_label(row: Mapping[str, Any]) -> str | None:
    test_condition = _as_mapping(row.get("test_condition"))
    filtered = _filter_context(test_condition, allow_paper_local_keys=False)
    if not filtered:
        return None
    has_test_signal = any(
        _has_test_condition_signal(key) or _has_test_condition_signal(value)
        for key, value in filtered.items()
    )
    if not has_test_signal:
        return None
    return _context_label(filtered, allow_paper_local_keys=False)


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


def _is_paper_local_context_key(value: str) -> bool:
    normalized = value.casefold().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    return normalized in _PAPER_LOCAL_CONTEXT_KEYS


def _has_test_condition_signal(value: str) -> bool:
    normalized = value.casefold().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    return any(signal in normalized for signal in _TEST_CONDITION_SIGNALS)


def _semantic_node(prefix: str, node_type: str, label: str) -> dict[str, Any]:
    display_value, normalized_key = _normalize_semantic_value(label)
    node_id = f"{prefix}:{sha1((normalized_key or '').encode('utf-8')).hexdigest()}"
    return {
        "id": node_id,
        "label": display_value or label,
        "type": node_type,
        "degree": 0,
    }


def _ordered_nodes(nodes: Any) -> list[dict[str, Any]]:
    return sorted(
        list(nodes),
        key=lambda node: (
            -int(node.get("degree") or 0),
            _NODE_TYPE_PRIORITY.get(str(node.get("type") or ""), 99),
            str(node.get("label") or node.get("id") or ""),
        ),
    )


def _put_node(index: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    index[str(node["id"])] = node


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


def _shorten_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _normalize_semantic_value(value: Any) -> tuple[str | None, str | None]:
    display_value = _clean_graph_text(value)
    if not display_value:
        return None, None
    return display_value, display_value.lower()


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
