from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from infra.persistence.backbone_codec import restore_frame_from_storage


_CORE_GRAPH_ARTIFACTS = (
    "document_profiles.parquet",
    "evidence_cards.parquet",
    "comparison_rows.parquet",
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
_COMPARISON_ROW_JSON_COLUMNS = (
    "supporting_evidence_ids",
    "comparability_warnings",
)
_NODE_TYPE_PRIORITY = {
    "comparison": 0,
    "evidence": 1,
    "document": 2,
}


def missing_core_graph_artifacts(base_dir: Path) -> list[str]:
    return [
        filename for filename in _CORE_GRAPH_ARTIFACTS if not (base_dir / filename).is_file()
    ]


def load_core_graph_payload(
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    profiles = _read_profiles(base_dir)
    evidence_cards = _read_evidence_cards(base_dir)
    comparison_rows = _read_comparison_rows(base_dir)

    doc_records: dict[str, dict[str, Any]] = {}
    evidence_records: dict[str, dict[str, Any]] = {}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for _, row in profiles.iterrows():
        document_id = _as_text(row.get("document_id"))
        if not document_id:
            continue
        record = _build_document_record(row)
        doc_records[document_id] = record
        nodes.append(record["node"])

    for _, row in evidence_cards.iterrows():
        evidence_id = _as_text(row.get("evidence_id"))
        if not evidence_id:
            continue
        record = _build_evidence_record(row, doc_records)
        evidence_records[evidence_id] = record
        nodes.append(record["node"])
        if record["document_edge"] is not None:
            edges.append(record["document_edge"])

    for _, row in comparison_rows.iterrows():
        comparison_id = _as_text(row.get("row_id"))
        if not comparison_id:
            continue
        comparison_node, comparison_edges = _build_comparison_projection(
            row,
            evidence_records=evidence_records,
        )
        nodes.append(comparison_node)
        edges.extend(comparison_edges)

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


def _read_comparison_rows(base_dir: Path) -> pd.DataFrame:
    return restore_frame_from_storage(
        pd.read_parquet(base_dir / "comparison_rows.parquet"),
        _COMPARISON_ROW_JSON_COLUMNS,
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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    comparison_id = _as_text(row.get("row_id")) or ""
    supporting_evidence_ids = _string_list(row.get("supporting_evidence_ids"))
    property_name = _as_text(row.get("property_normalized"))
    material_name = _as_text(row.get("material_system_normalized"))

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
    return node, edges


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
        ordered_nodes = sorted(
            nodes,
            key=lambda node: (
                -int(node.get("degree") or 0),
                _NODE_TYPE_PRIORITY.get(str(node.get("type") or ""), 99),
                str(node.get("label") or node.get("id") or ""),
            ),
        )
        selected_nodes = ordered_nodes[:max_nodes]
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
