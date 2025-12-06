from typing import Dict, Iterable, List, Set

import networkx as nx
from networkx.algorithms.community import label_propagation_communities

from graphrag.prompts import build_community_summary_prompt
from services.llm_client import LLMClient
from graphrag.store import GraphStore


class CommunityManager:
    def __init__(self, store: GraphStore, llm: LLMClient):
        self.store = store
        self.llm = llm

    def rebuild(self, max_communities: int = 20) -> None:
        communities = self._detect(self.store.graph)
        # Clear existing community nodes
        self.store.remove_nodes_by_type("Community")
        for idx, members in enumerate(communities):
            if idx >= max_communities:
                break
            community_id = f"community::{idx}"
            summary = self._summarize(community_id, members)
            self._materialize(community_id, members, summary)
        self.store.save()

    def _detect(self, graph: nx.MultiDiGraph) -> List[Set[str]]:
        if graph.number_of_nodes() == 0:
            return []
        undirected = nx.Graph()
        undirected.add_nodes_from(graph.nodes())
        for u, v in graph.edges():
            undirected.add_edge(u, v)
        communities_iter = label_propagation_communities(undirected)
        return [set(c) for c in communities_iter]

    def _summarize(self, community_id: str, members: Iterable[str]) -> str:
        nodes = [self.store.graph.nodes[m] for m in members if m in self.store.graph.nodes]
        labels = [f"{n.get('name')}[{n.get('type')}]" for n in nodes]
        prompt = build_community_summary_prompt(community_id=community_id, members=labels[:50])
        try:
            return self.llm.chat(system="你是图谱摘要助手。", user=prompt, temperature=0.2)
        except Exception:
            return ", ".join(labels[:20])

    def _materialize(self, community_id: str, members: Iterable[str], summary: str) -> None:
        node_id = self.store.upsert_node(name=community_id, type_="Community", attrs={"summary": summary})
        for member in members:
            if member not in self.store.graph.nodes:
                continue
            self.store.upsert_edge(
                head_id=node_id,
                tail_id=member,
                relation="includes",
                attrs={"weight": 1.0},
                sources=[],
            )
