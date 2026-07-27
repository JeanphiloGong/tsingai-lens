from __future__ import annotations

import math
from hashlib import sha1
from typing import Any, Mapping


_NODE_TYPE_PRIORITY = {
    "objective": 0,
    "comparison": 1,
    "evidence": 2,
    "document": 3,
    "material": 4,
    "property": 5,
    "test_condition": 6,
    "baseline": 7,
}
_SEMANTIC_NODE_SPECS = (
    {
        "field": "material_system_normalized",
        "type": "material",
        "prefix": "mat",
        "edge_description": "comparison_to_material",
        "placeholders": {
            "",
            "--",
            "unknown",
            "unspecified material system",
        },
    },
    {
        "field": "property_normalized",
        "type": "property",
        "prefix": "prop",
        "edge_description": "comparison_to_property",
        "placeholders": {
            "",
            "--",
            "unknown",
        },
    },
    {
        "field": "test_condition_normalized",
        "type": "test_condition",
        "prefix": "tc",
        "edge_description": "comparison_to_test_condition",
        "placeholders": {
            "",
            "--",
            "unknown",
            "unspecified test condition",
        },
    },
    {
        "field": "baseline_normalized",
        "type": "baseline",
        "prefix": "base",
        "edge_description": "comparison_to_baseline",
        "placeholders": {
            "",
            "--",
            "unknown",
            "unspecified baseline",
        },
    },
)
def load_core_graph_payload(
    profiles: tuple[dict[str, Any], ...],
    research_objectives: tuple[dict[str, Any], ...],
    max_nodes: int,
    min_weight: float,
    evidence_cards: tuple[dict[str, Any], ...] = (),
    comparison_rows: tuple[dict[str, Any], ...] = (),
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
    node_index: dict[str, dict[str, Any]] = {}
    edge_index: dict[str, dict[str, Any]] = {}

    if evidence_cards or comparison_rows:
        for record in doc_records.values():
            _put_node(node_index, record["node"])
        evidence_records = _build_evidence_card_projection(
            evidence_cards=evidence_cards,
            doc_records=doc_records,
            node_index=node_index,
            edge_index=edge_index,
        )
        _build_comparison_projection(
            comparison_rows=comparison_rows,
            evidence_records=evidence_records,
            node_index=node_index,
            edge_index=edge_index,
        )

    for record in objective_records.values():
        _put_node(node_index, record["node"])

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
        "node": {
            "id": f"doc:{document_id}",
            "label": title or source_filename or document_id,
            "type": "document",
            "degree": 0,
        },
    }


def _build_evidence_card_projection(
    *,
    evidence_cards: tuple[dict[str, Any], ...],
    doc_records: dict[str, dict[str, Any]],
    node_index: dict[str, dict[str, Any]],
    edge_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    evidence_records: dict[str, dict[str, Any]] = {}
    for row in evidence_cards:
        evidence_id = _as_text(row.get("evidence_id"))
        if not evidence_id:
            continue
        record = _build_evidence_card_record(row, doc_records)
        evidence_records[evidence_id] = record
        _put_node(node_index, record["node"])
        if record["document_edge"] is not None:
            _put_edge(edge_index, record["document_edge"])
    return evidence_records


def _build_evidence_card_record(
    row: Mapping[str, Any],
    doc_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    evidence_id = _as_text(row.get("evidence_id")) or ""
    document_id = _as_text(row.get("document_id"))
    claim_text = _as_text(row.get("claim_text")) or evidence_id
    document_edge = None
    if document_id and document_id in doc_records:
        document_edge = {
            "id": f"edge:doc:{document_id}:evi:{evidence_id}",
            "source": f"doc:{document_id}",
            "target": f"evi:{evidence_id}",
            "weight": 1.0,
            "edge_description": "document_to_evidence",
        }
    return {
        "node": {
            "id": f"evi:{evidence_id}",
            "label": _shorten_text(claim_text, 96),
            "type": "evidence",
            "degree": 0,
        },
        "document_edge": document_edge,
    }


def _build_comparison_projection(
    *,
    comparison_rows: tuple[dict[str, Any], ...],
    evidence_records: dict[str, dict[str, Any]],
    node_index: dict[str, dict[str, Any]],
    edge_index: dict[str, dict[str, Any]],
) -> None:
    for row in comparison_rows:
        comparison_id = _as_text(row.get("row_id"))
        if not comparison_id:
            continue
        comparison_node, semantic_nodes, comparison_edges = _build_comparison_record(
            row,
            evidence_records=evidence_records,
        )
        _put_node(node_index, comparison_node)
        for semantic_node in semantic_nodes:
            _put_node(node_index, semantic_node)
        for edge in comparison_edges:
            _put_edge(edge_index, edge)


def _build_comparison_record(
    row: Mapping[str, Any],
    *,
    evidence_records: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    comparison_id = _as_text(row.get("row_id")) or ""
    supporting_evidence_ids = _string_list(row.get("supporting_evidence_ids"))
    property_name = _clean_graph_text(row.get("property_normalized"))
    material_name = _clean_graph_text(row.get("material_system_normalized"))
    node = {
        "id": f"cmp:{comparison_id}",
        "label": _build_comparison_label(material_name, property_name, comparison_id),
        "type": "comparison",
        "degree": 0,
    }

    edges: list[dict[str, Any]] = []
    for evidence_id in supporting_evidence_ids:
        if evidence_records.get(evidence_id) is None:
            continue
        edges.append(
            {
                "id": f"edge:evi:{evidence_id}:cmp:{comparison_id}",
                "source": f"evi:{evidence_id}",
                "target": f"cmp:{comparison_id}",
                "weight": 1.0,
                "edge_description": "evidence_to_comparison",
            }
        )

    semantic_nodes: list[dict[str, Any]] = []
    for spec in _SEMANTIC_NODE_SPECS:
        semantic_projection = _build_semantic_projection(
            row=row,
            comparison_id=comparison_id,
            field=str(spec["field"]),
            node_type=str(spec["type"]),
            node_prefix=str(spec["prefix"]),
            edge_description=str(spec["edge_description"]),
            placeholders={str(item) for item in spec["placeholders"]},
        )
        if semantic_projection is None:
            continue
        semantic_node, semantic_edge = semantic_projection
        semantic_nodes.append(semantic_node)
        edges.append(semantic_edge)
    return node, semantic_nodes, edges


def _build_semantic_projection(
    *,
    row: Mapping[str, Any],
    comparison_id: str,
    field: str,
    node_type: str,
    node_prefix: str,
    edge_description: str,
    placeholders: set[str],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    display_value, normalized_key = _normalize_semantic_value(row.get(field))
    if not display_value or not normalized_key or normalized_key in placeholders:
        return None
    node_id = f"{node_prefix}:{sha1(normalized_key.encode('utf-8')).hexdigest()}"
    return (
        {
            "id": node_id,
            "label": display_value,
            "type": node_type,
            "degree": 0,
        },
        {
            "id": f"edge:cmp:{comparison_id}:{node_id}",
            "source": f"cmp:{comparison_id}",
            "target": node_id,
            "weight": 1.0,
            "edge_description": edge_description,
        },
    )


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


def _ordered_nodes(nodes: Any) -> list[dict[str, Any]]:
    return sorted(
        list(nodes),
        key=lambda node: (
            _NODE_TYPE_PRIORITY.get(str(node.get("type") or ""), 99),
            str(node.get("label") or node.get("id") or ""),
        ),
    )


def _put_node(index: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    index[str(node["id"])] = node


def _put_edge(index: dict[str, dict[str, Any]], edge: dict[str, Any]) -> None:
    index[str(edge["id"])] = edge


def _build_comparison_label(
    material_name: str | None,
    property_name: str | None,
    comparison_id: str,
) -> str:
    parts = [part for part in (material_name, property_name) if part]
    if parts:
        return " | ".join(parts)
    return comparison_id


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
