from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    """Serialize a route-compatible graph payload into GraphML bytes."""
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
        node_el = SubElement(graph, "node", id=node["id"])
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
            add_data(node_el, key, node.get(key))

    for edge in edges:
        edge_el = SubElement(
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
            add_data(edge_el, key, edge.get(key))

    return tostring(gml, encoding="utf-8", xml_declaration=True)


__all__ = ["to_graphml"]
