from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    """Serialize a route-compatible graph payload into GraphML bytes."""
    gml = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")

    key_defs = [
        ("label", "node", "string"),
        ("type", "node", "string"),
        ("degree", "node", "int"),
        ("edge_description", "edge", "string"),
        ("weight", "edge", "double"),
    ]
    for name, domain, attr_type in key_defs:
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
        for key in ["label", "type", "degree"]:
            add_data(node_el, key, node.get(key))

    for edge in edges:
        edge_el = SubElement(
            graph,
            "edge",
            id=edge["id"],
            source=edge["source"],
            target=edge["target"],
        )
        for key in ["weight", "edge_description"]:
            add_data(edge_el, key, edge.get(key))

    return tostring(gml, encoding="utf-8", xml_declaration=True)


__all__ = ["to_graphml"]
