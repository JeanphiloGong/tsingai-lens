from collections import defaultdict
from typing import Dict, List


def graph_to_mindmap(graph_data: Dict) -> Dict:
    """Convert graph data to a simple tree rooted at the most connected node."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    if not nodes:
        return {}

    degree_map = defaultdict(int)
    for edge in edges:
        degree_map[edge["source"]] += 1
        degree_map[edge["target"]] += 1

    root_id = max(degree_map, key=degree_map.get, default=nodes[0]["id"])
    children_map: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        children_map[edge["source"]].append(edge["target"])

    def build_node(node_id: str) -> Dict:
        return {
            "topic": node_id,
            "children": [build_node(child) for child in children_map.get(node_id, [])],
        }

    return {"topic": root_id, "children": [build_node(c) for c in children_map.get(root_id, [])]}
