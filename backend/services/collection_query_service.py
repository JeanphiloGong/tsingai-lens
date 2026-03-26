from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

import pandas as pd
from fastapi import HTTPException

from services.artifact_registry_service import ArtifactRegistryService
from services.collection_service import CollectionService


artifact_registry_service = ArtifactRegistryService()
collection_service = CollectionService()


def resolve_collection_output_dir(collection_id: str) -> Path:
    try:
        payload = artifact_registry_service.get(collection_id)
        output_path = payload.get("output_path")
        if output_path:
            base_dir = Path(str(output_path)).expanduser().resolve()
            if base_dir.exists():
                return base_dir
    except FileNotFoundError:
        pass

    paths = collection_service.get_paths(collection_id)
    if not paths.output_dir.exists():
        raise HTTPException(status_code=404, detail=f"集合输出目录不存在: {paths.output_dir}")
    return paths.output_dir.resolve()


def _read_parquet_or_error(path: Path, label: str) -> pd.DataFrame:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{label} 不存在: {path}")
    try:
        return pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{label} 读取失败: {exc}") from exc


def _safe_int(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def load_graph_payload(
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None]:
    entities = _read_parquet_or_error(base_dir / "entities.parquet", "实体数据")
    relationships = _read_parquet_or_error(base_dir / "relationships.parquet", "关系数据")

    community_label = None
    if community_id:
        communities = _read_parquet_or_error(base_dir / "communities.parquet", "社区数据")
        matched = communities[
            (communities["id"].astype(str) == community_id)
            | (communities["human_readable_id"].astype(str) == community_id)
            | (communities["community"].astype(str) == community_id)
        ]
        if matched.empty:
            raise HTTPException(status_code=404, detail="未找到指定社区")
        community_row = matched.iloc[0]
        entity_allowlist = set(str(e) for e in (community_row.get("entity_ids") or []))
        entities = entities[entities["id"].astype(str).isin(entity_allowlist)]
        community_label = (
            str(community_row.get("title"))
            if community_row.get("title") is not None
            else str(community_id)
        )

    if min_weight > 0:
        relationships = relationships[
            relationships["weight"].fillna(0) >= float(min_weight)
        ]

    truncated = False
    if len(entities) > max_nodes:
        entities = (
            entities.sort_values(by=["degree", "frequency"], ascending=False)
            .head(max_nodes)
            .copy()
        )
        truncated = True

    selected_ids = set(entities["id"].astype(str))
    title_to_id = {
        str(row.title): str(row.id)
        for _, row in entities[["title", "id"]].dropna().iterrows()
    }

    def map_entity(value: Any) -> str:
        text = str(value)
        return title_to_id.get(text, text)

    def edge_in_subset(row: pd.Series) -> bool:
        source_id = map_entity(row["source"])
        target_id = map_entity(row["target"])
        return source_id in selected_ids and target_id in selected_ids

    relationships = relationships[relationships.apply(edge_in_subset, axis=1)]

    nodes_payload = [
        {
            "id": str(row.id),
            "label": str(row.title),
            "type": row.type if not pd.isna(row.type) else None,
            "description": row.description if not pd.isna(row.description) else None,
            "degree": _safe_int(row.degree),
            "frequency": _safe_int(row.frequency),
            "x": _safe_float(row.x),
            "y": _safe_float(row.y),
        }
        for _, row in entities.iterrows()
    ]

    edges_payload = []
    for _, row in relationships.iterrows():
        source_id = map_entity(row["source"])
        target_id = map_entity(row["target"])
        edges_payload.append(
            {
                "id": str(row.id) if not pd.isna(row.id) else f"{source_id}->{target_id}",
                "source": source_id,
                "target": target_id,
                "weight": _safe_float(row.weight),
                "description": row.description if not pd.isna(row.description) else None,
                "rank": _safe_int(row.rank),
            }
        )

    return nodes_payload, edges_payload, truncated, community_label


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    gml = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    graph = SubElement(gml, "graph", edgedefault="directed")

    for node in nodes:
        node_el = SubElement(graph, "node", id=str(node["id"]))
        for key in ("label", "type", "description", "degree", "frequency", "x", "y"):
            value = node.get(key)
            if value is None:
                continue
            data_el = SubElement(node_el, "data", key=key)
            data_el.text = str(value)

    for edge in edges:
        edge_el = SubElement(
            graph,
            "edge",
            id=str(edge.get("id") or f'{edge["source"]}->{edge["target"]}'),
            source=str(edge["source"]),
            target=str(edge["target"]),
        )
        for key in ("weight", "description", "rank"):
            value = edge.get(key)
            if value is None:
                continue
            data_el = SubElement(edge_el, "data", key=key)
            data_el.text = str(value)

    return tostring(gml, encoding="utf-8", xml_declaration=True)
