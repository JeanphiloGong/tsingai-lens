from __future__ import annotations

import math
from hashlib import sha1
from pathlib import Path
from typing import Any

import pandas as pd

from infra.persistence.backbone_codec import restore_frame_from_storage


_CORE_GRAPH_BACKBONE_ARTIFACTS = (
    "document_profiles.parquet",
    "evidence_cards.parquet",
)
_DOCUMENT_PROFILE_JSON_COLUMNS = (
    "protocol_extractability_signals",
    "parsing_warnings",
)
_EVIDENCE_CARD_JSON_COLUMNS = (
    "evidence_anchors",
    "material_system",
    "condition_context",
)
_NODE_TYPE_PRIORITY = {
    "comparison": 0,
    "evidence": 1,
    "document": 2,
    "material": 3,
    "property": 4,
    "test_condition": 5,
    "baseline": 6,
}
_BACKBONE_NODE_TYPES = frozenset({"document", "evidence", "comparison"})
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
_BACKBONE_TRUNCATION_SHARE = 0.6


def missing_core_graph_artifacts(base_dir: Path) -> list[str]:
    return [
        filename
        for filename in _CORE_GRAPH_BACKBONE_ARTIFACTS
        if not (base_dir / filename).is_file()
    ]


def load_core_graph_payload(
    base_dir: Path,
    comparison_rows: pd.DataFrame,
    max_nodes: int,
    min_weight: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    profiles = _read_profiles(base_dir)
    evidence_cards = _read_evidence_cards(base_dir)

    doc_records: dict[str, dict[str, Any]] = {}
    evidence_records: dict[str, dict[str, Any]] = {}

    node_index: dict[str, dict[str, Any]] = {}
    edge_index: dict[str, dict[str, Any]] = {}

    for _, row in profiles.iterrows():
        document_id = _as_text(row.get("document_id"))
        if not document_id:
            continue
        record = _build_document_record(row)
        doc_records[document_id] = record
        _put_node(node_index, record["node"])

    for _, row in evidence_cards.iterrows():
        evidence_id = _as_text(row.get("evidence_id"))
        if not evidence_id:
            continue
        record = _build_evidence_record(row, doc_records)
        evidence_records[evidence_id] = record
        _put_node(node_index, record["node"])
        if record["document_edge"] is not None:
            _put_edge(edge_index, record["document_edge"])

    for _, row in comparison_rows.iterrows():
        comparison_id = _as_text(row.get("row_id"))
        if not comparison_id:
            continue
        comparison_node, semantic_nodes, comparison_edges = _build_comparison_projection(
            row,
            evidence_records=evidence_records,
        )
        _put_node(node_index, comparison_node)
        for semantic_node in semantic_nodes:
            _put_node(node_index, semantic_node)
        for edge in comparison_edges:
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


def _read_profiles(base_dir: Path) -> pd.DataFrame:
    return restore_frame_from_storage(
        pd.read_parquet(base_dir / "document_profiles.parquet"),
        _DOCUMENT_PROFILE_JSON_COLUMNS,
    )


def _read_evidence_cards(base_dir: Path) -> pd.DataFrame:
    return restore_frame_from_storage(
        pd.read_parquet(base_dir / "evidence_cards.parquet"),
        _EVIDENCE_CARD_JSON_COLUMNS,
    )


def _build_document_record(row: pd.Series) -> dict[str, Any]:
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


def _build_evidence_record(
    row: pd.Series,
    doc_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    evidence_id = _as_text(row.get("evidence_id")) or ""
    document_id = _as_text(row.get("document_id"))
    claim_text = _as_text(row.get("claim_text")) or evidence_id
    node = {
        "id": f"evi:{evidence_id}",
        "label": _shorten_text(claim_text, 96),
        "type": "evidence",
        "degree": 0,
    }
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
        "node": node,
        "document_edge": document_edge,
    }


def _build_comparison_projection(
    row: pd.Series,
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
    row: pd.Series,
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
    if isinstance(value, float) and pd.isna(value):
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
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "load_core_graph_payload",
    "missing_core_graph_artifacts",
]
