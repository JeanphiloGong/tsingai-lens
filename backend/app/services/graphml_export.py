"""GraphML export helpers with evidence fields."""

from __future__ import annotations

import json
import logging
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

import pandas as pd
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def read_parquet_or_error(path: Any, label: str) -> pd.DataFrame:
    """Read a parquet file and raise a friendly HTTP error if missing or broken."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{label} 不存在: {path}")
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.exception("Failed to read %s from %s", label, path)
        raise HTTPException(status_code=500, detail=f"{label} 读取失败: {exc}") from exc


def read_parquet_optional(path: Any, label: str) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        logger.warning("Failed to read %s from %s", label, path)
        return None


def safe_int(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, float) and pd.isna(item):
                continue
            items.append(str(item))
        return items
    if isinstance(value, float) and pd.isna(value):
        return []
    return [str(value)]


def serialize_list(values: list[str]) -> str | None:
    if not values:
        return None
    return json.dumps(values, ensure_ascii=False)


def build_source_fields(
    text_unit_ids_value: Any,
    text_unit_to_docs: dict[str, list[str]],
    doc_id_to_title: dict[str, str],
    prefix: str,
) -> dict[str, Any]:
    text_unit_ids = sorted(set(listify(text_unit_ids_value)))
    doc_ids: list[str] = []
    if text_unit_ids:
        doc_ids = sorted(
            {
                doc_id
                for text_unit_id in text_unit_ids
                for doc_id in text_unit_to_docs.get(text_unit_id, [])
            }
        )
    doc_titles = [
        title for doc_id in doc_ids if (title := doc_id_to_title.get(doc_id))
    ]
    return {
        f"{prefix}_text_unit_ids": serialize_list(text_unit_ids),
        f"{prefix}_text_unit_count": len(text_unit_ids) if text_unit_ids else None,
        f"{prefix}_document_ids": serialize_list(doc_ids),
        f"{prefix}_document_titles": serialize_list(doc_titles),
        f"{prefix}_document_count": len(doc_ids) if doc_ids else None,
    }


def load_graph_payload(
    base_dir: Any,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
    include_community: bool,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], bool, str | None, int | None
]:
    """Load and filter graph data, returning nodes and edges payloads."""
    entities = read_parquet_or_error(base_dir / "entities.parquet", "实体数据")
    relationships = read_parquet_or_error(
        base_dir / "relationships.parquet", "关系数据"
    )

    communities = None
    community_level = None
    communities_path = base_dir / "communities.parquet"
    if community_id or include_community:
        if communities_path.is_file():
            communities = read_parquet_or_error(communities_path, "社区数据")
        elif community_id:
            raise HTTPException(status_code=404, detail="社区数据不存在，无法筛选")
        elif include_community:
            logger.warning("社区数据不存在，跳过 community 字段输出")

    text_units = read_parquet_optional(base_dir / "text_units.parquet", "文本单元")
    documents = read_parquet_optional(base_dir / "documents.parquet", "文档")
    text_unit_to_docs: dict[str, list[str]] = {}
    if text_units is not None and {"id", "document_ids"}.issubset(text_units.columns):
        for _, row in text_units.iterrows():
            text_unit_id = row.get("id")
            if text_unit_id is None or (
                isinstance(text_unit_id, float) and pd.isna(text_unit_id)
            ):
                continue
            doc_ids = listify(row.get("document_ids"))
            if doc_ids:
                text_unit_to_docs[str(text_unit_id)] = doc_ids

    doc_id_to_title: dict[str, str] = {}
    if documents is not None and {"id", "title"}.issubset(documents.columns):
        for _, row in documents.iterrows():
            doc_id = row.get("id")
            title = row.get("title")
            if doc_id is None or (isinstance(doc_id, float) and pd.isna(doc_id)):
                continue
            if title is None or (isinstance(title, float) and pd.isna(title)):
                continue
            doc_id_to_title[str(doc_id)] = str(title)

    community_label = None
    community_row = None
    if community_id:
        if communities is None:
            raise HTTPException(status_code=404, detail="社区数据不存在，无法筛选")
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
    community_map: dict[str, int | None] = {}
    if include_community and selected_ids:
        if community_row is not None:
            community_value = safe_int(community_row.get("community"))
            community_level = safe_int(community_row.get("level"))
            for entity_id in selected_ids:
                community_map[entity_id] = community_value
        elif communities is not None:
            if "level" in communities.columns:
                level_series = communities["level"].dropna()
                if not level_series.empty:
                    community_level = safe_int(level_series.max())
            if community_level is not None and "level" in communities.columns:
                communities = communities[communities["level"] == community_level]
            community_join = communities.explode("entity_ids").loc[
                :, ["community", "entity_ids"]
            ]
            for _, row in community_join.iterrows():
                entity_id = row.get("entity_ids")
                if pd.isna(entity_id):
                    continue
                entity_id_str = str(entity_id)
                if entity_id_str in selected_ids and entity_id_str not in community_map:
                    community_map[entity_id_str] = safe_int(row.get("community"))

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
            "degree": safe_int(row.degree),
            "frequency": safe_int(row.frequency),
            "x": safe_float(row.x),
            "y": safe_float(row.y),
            "community": community_map.get(str(row.id)),
            **build_source_fields(
                row.text_unit_ids, text_unit_to_docs, doc_id_to_title, "node"
            ),
        }
        for _, row in entities.iterrows()
    ]

    edges_payload = [
        {
            "id": str(row.id),
            "source": map_entity(row.source),
            "target": map_entity(row.target),
            "weight": safe_float(row.weight),
            "edge_description": row.description
            if not pd.isna(row.description)
            else None,
            **build_source_fields(
                row.text_unit_ids, text_unit_to_docs, doc_id_to_title, "edge"
            ),
        }
        for _, row in relationships.iterrows()
    ]

    return nodes_payload, edges_payload, truncated, community_label, community_level


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    """Serialize nodes/edges into GraphML format."""
    gml = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")

    key_defs = [
        ("label", "node", "string"),
        ("type", "node", "string"),
        ("description", "node", "string"),
        ("edge_description", "edge", "string"),
        ("degree", "node", "int"),
        ("frequency", "node", "int"),
        ("x", "node", "double"),
        ("y", "node", "double"),
        ("community", "node", "int"),
        ("node_text_unit_ids", "node", "string"),
        ("node_text_unit_count", "node", "int"),
        ("node_document_ids", "node", "string"),
        ("node_document_titles", "node", "string"),
        ("node_document_count", "node", "int"),
        ("edge_text_unit_ids", "edge", "string"),
        ("edge_text_unit_count", "edge", "int"),
        ("edge_document_ids", "edge", "string"),
        ("edge_document_titles", "edge", "string"),
        ("edge_document_count", "edge", "int"),
        ("weight", "edge", "double"),
    ]
    has_community = any(node.get("community") is not None for node in nodes)
    for name, domain, attr_type in key_defs:
        if name == "community" and not has_community:
            continue
        SubElement(
            gml,
            "key",
            id=name,
            attr_name=name,
            attr_type=attr_type,
            **{"for": domain},
        )

    graph = SubElement(gml, "graph", id="G", edgedefault="undirected")

    def add_data(el: Element, key: str, value: Any) -> None:
        if value is None:
            return
        SubElement(el, "data", key=key).text = str(value)

    for node in nodes:
        n = SubElement(graph, "node", id=node["id"])
        for key in [
            "label",
            "type",
            "description",
            "degree",
            "frequency",
            "x",
            "y",
            "community",
            "node_text_unit_ids",
            "node_text_unit_count",
            "node_document_ids",
            "node_document_titles",
            "node_document_count",
        ]:
            add_data(n, key, node.get(key))

    for edge in edges:
        e = SubElement(
            graph,
            "edge",
            id=edge["id"],
            source=edge["source"],
            target=edge["target"],
        )
        for key in [
            "weight",
            "edge_description",
            "edge_text_unit_ids",
            "edge_text_unit_count",
            "edge_document_ids",
            "edge_document_titles",
            "edge_document_count",
        ]:
            add_data(e, key, edge.get(key))

    return tostring(gml, encoding="utf-8", xml_declaration=True)
