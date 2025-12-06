import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx

from graphrag.schema import Edge, Node, Source


class GraphStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.graph = nx.MultiDiGraph()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            nodes = payload.get("nodes", [])
            edges = payload.get("edges", [])
            for n in nodes:
                self.graph.add_node(n["id"], **n)
            for e in edges:
                self.graph.add_edge(e["head"], e["tail"], key=e["id"], **e)
        except json.JSONDecodeError:
            self.graph = nx.MultiDiGraph()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        nodes = [self.graph.nodes[n] for n in self.graph.nodes]
        edges = []
        for u, v, k, data in self.graph.edges(keys=True, data=True):
            edges.append(data)
        payload = {"nodes": nodes, "edges": edges}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _node_key(name: str, type_: str) -> str:
        return f"{type_.lower()}::{name.strip().lower()}"

    def remove_nodes_by_type(self, type_name: str) -> None:
        to_remove = [n for n, d in self.graph.nodes(data=True) if d.get("type") == type_name]
        self.graph.remove_nodes_from(to_remove)

    def upsert_node(self, name: str, type_: str, attrs: Optional[Dict] = None) -> str:
        node_id = self._node_key(name, type_)
        attrs = attrs or {}
        existing = self.graph.nodes.get(node_id)
        if existing:
            merged_attrs = {**existing.get("attrs", {}), **attrs}
            existing["attrs"] = self._merge_attrs(existing.get("attrs", {}), attrs)
            return node_id
        node = Node(id=node_id, name=name.strip(), type=type_.strip(), attrs=attrs or {})
        self.graph.add_node(node_id, **node.__dict__)
        return node_id

    def _merge_attrs(self, base: Dict, new: Dict) -> Dict:
        merged = dict(base)
        for k, v in (new or {}).items():
            if k not in merged:
                merged[k] = v
                continue
            if isinstance(merged[k], list) and isinstance(v, list):
                merged[k] = list({*merged[k], *v})
            elif isinstance(merged[k], set) and isinstance(v, set):
                merged[k] = set(merged[k]).union(v)
            else:
                merged[k] = v
        return merged

    def upsert_edge(
        self,
        head_id: str,
        tail_id: str,
        relation: str,
        attrs: Optional[Dict] = None,
        sources: Optional[List[Source]] = None,
    ) -> str:
        attrs = attrs or {}
        relation_key = relation.strip().lower()
        # try merge with existing same relation/ endpoints
        for _, _, key, data in self.graph.edges(keys=True, data=True):
            if data.get("head") == head_id and data.get("tail") == tail_id and data.get("relation") == relation:
                merged_sources = list(data.get("attrs", {}).get("sources", []))
                merged_sources.extend([s.__dict__ for s in sources or []])
                data_attrs = {**data.get("attrs", {}), **attrs, "sources": merged_sources}
                data["attrs"] = data_attrs
                return key

        edge_id = str(uuid.uuid4())
        edge = Edge(
            id=edge_id,
            head=head_id,
            tail=tail_id,
            relation=relation_key,
            attrs={**attrs, "sources": [s.__dict__ for s in sources or []]},
        )
        self.graph.add_edge(head_id, tail_id, key=edge_id, **edge.__dict__)
        return edge_id

    def list_nodes(self) -> List[Dict]:
        return [self.graph.nodes[n] for n in self.graph.nodes]

    def list_edges(self) -> List[Dict]:
        edges: List[Dict] = []
        for _, _, _, data in self.graph.edges(keys=True, data=True):
            edges.append(data)
        return edges

    def find_nodes_by_type(self, type_name: str) -> List[Dict]:
        return [data for _, data in self.graph.nodes(data=True) if data.get("type") == type_name]

    def find_nodes_by_keyword(self, keyword: str, limit: int = 10) -> List[Dict]:
        key = keyword.lower()
        matched = []
        for n in self.graph.nodes:
            data = self.graph.nodes[n]
            if key in data.get("name", "").lower():
                matched.append(data)
            elif key in data.get("type", "").lower():
                matched.append(data)
        return matched[:limit]

    def neighbors(self, node_id: str) -> List[Tuple[str, Dict]]:
        neigh = []
        for _, v, data in self.graph.out_edges(node_id, data=True):
            neigh.append((v, data))
        for v, _, data in self.graph.in_edges(node_id, data=True):
            neigh.append((v, data))
        return neigh
