#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from collections import Counter
from typing import Any


RAW_CANVAS_NODE_TYPES = {
    "document",
    "measurement",
    "comparison",
    "controlled_comparison",
    "sample",
    "test_condition",
}
MATERIAL_EDGE_TYPES = {
    "objective_to_material_system",
    "material_system_to_material_scope",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the semantic graph contract for a collection.")
    parser.add_argument("collection_id")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--max-nodes", type=int, default=200)
    args = parser.parse_args()

    payload = _load_graph(args.base_url, args.collection_id, args.max_nodes)
    nodes = list(payload.get("nodes") or [])
    edges = list(payload.get("edges") or [])
    errors: list[str] = []

    material_nodes = [node for node in nodes if node.get("type") == "material_system"]
    material_labels = Counter(str(node.get("label") or "") for node in material_nodes)
    duplicate_materials = sorted(label for label, count in material_labels.items() if label and count > 1)
    raw_node_types = sorted({str(node.get("type")) for node in nodes} & RAW_CANVAS_NODE_TYPES)

    material_edges_missing_chain = [
        edge.get("id")
        for edge in edges
        if edge.get("edge_description") in MATERIAL_EDGE_TYPES and not edge.get("logic_chain_id")
    ]
    semantic_edges_missing_roles = [
        edge.get("id")
        for edge in edges
        if edge.get("edge_description") == "semantic_chain_step_to_step"
        and (not edge.get("source_role") or not edge.get("target_role") or not edge.get("logic_chain_id"))
    ]

    if not material_nodes:
        errors.append("expected at least one material_system node")
    if duplicate_materials:
        errors.append(f"duplicate material_system labels: {', '.join(duplicate_materials)}")
    if raw_node_types:
        errors.append(f"raw canvas node types leaked into graph: {', '.join(raw_node_types)}")
    if material_edges_missing_chain:
        errors.append(f"material edges missing logic_chain_id: {material_edges_missing_chain[:5]}")
    if semantic_edges_missing_roles:
        errors.append(f"semantic chain edges missing role metadata: {semantic_edges_missing_roles[:5]}")

    print(
        json.dumps(
            {
                "collection_id": args.collection_id,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "material_system_count": len(material_nodes),
                "material_labels": dict(material_labels),
                "edge_types": sorted({edge.get("edge_description") for edge in edges}),
                "truncated": bool(payload.get("truncated")),
                "passed": not errors,
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors else 0


def _load_graph(base_url: str, collection_id: str, max_nodes: int) -> dict[str, Any]:
    base = base_url.rstrip("/")
    url = f"{base}/api/v1/collections/{collection_id}/graph?max_nodes={max_nodes}&min_weight=0"
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
