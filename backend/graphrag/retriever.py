from typing import Dict, List, Tuple

import networkx as nx

from graphrag.prompts import SYSTEM_PROMPT, build_answer_prompt
from graphrag.store import GraphStore
from services.llm_client import LLMClient


class GraphRetriever:
    def __init__(self, store: GraphStore, llm: LLMClient):
        self.store = store
        self.llm = llm

    def parse_query(self, query: str) -> List[str]:
        # naive token split; can be replaced by LLM parsing
        return [q for q in query.replace(",", " ").split() if q.strip()]

    def find_seed_nodes(self, query: str, limit: int = 5) -> List[str]:
        tokens = self.parse_query(query)
        matched: List[str] = []
        for tok in tokens:
            for node in self.store.find_nodes_by_keyword(tok, limit=limit):
                matched.append(node["id"])
        # add community nodes whose summary hits query
        for comm in self.store.find_nodes_by_type("Community"):
            summary = (comm.get("attrs") or {}).get("summary", "") or ""
            if any(tok.lower() in summary.lower() for tok in tokens):
                matched.append(comm["id"])
        # dedupe preserving order
        seen = set()
        deduped = []
        for m in matched:
            if m in seen:
                continue
            seen.add(m)
            deduped.append(m)
        if deduped:
            return deduped[:limit]
        # fallback: top degree nodes
        degrees = sorted(self.store.graph.degree, key=lambda kv: kv[1], reverse=True)
        return [n for n, _ in degrees[:limit]]

    def _community_cards(self, seeds: List[str], top_k_cards: int, max_edges: int) -> Tuple[List[Dict], List[Dict]]:
        communities = [n for n, d in self.store.graph.nodes(data=True) if d.get("type") == "Community"]
        if not communities:
            return [], []

        # rank communities: seeds inside community get higher weight
        community_scores = []
        for cid in communities:
            members = [v for _, v, data in self.store.graph.out_edges(cid, data=True) if data.get("relation") == "includes"]
            score = len(set(members) & set(seeds))
            community_scores.append((cid, score, members))
        community_scores.sort(key=lambda t: t[1], reverse=True)

        cards = []
        sources: List[Dict] = []
        for cid, _, members in community_scores[:top_k_cards]:
            node_data = self.store.graph.nodes[cid]
            summary = (node_data.get("attrs") or {}).get("summary", "")
            edges = self._edges_for_members(members, max_edges=max_edges // max(top_k_cards, 1))
            edge_lines = []
            for edge_data in edges:
                head = self._node_label(self.store.graph.nodes[edge_data["head"]])
                tail = self._node_label(self.store.graph.nodes[edge_data["tail"]])
                rel = edge_data.get("relation", "related_to")
                srcs = edge_data.get("attrs", {}).get("sources", [])
                edge_lines.append(f"{head} --{rel}--> {tail}")
                for src in srcs:
                    sources.append(
                        {
                            "doc_id": src.get("doc_id"),
                            "source": src.get("source"),
                            "page": src.get("page"),
                            "chunk_id": src.get("chunk_id"),
                            "snippet": src.get("snippet"),
                            "edge_id": edge_data.get("id"),
                            "community_id": cid,
                            "head": head,
                            "tail": tail,
                            "relation": rel,
                            "score": src.get("score"),
                        }
                    )
            card_text = f"[{cid}] 摘要: {summary}\n关系:\n" + "\n".join(edge_lines[:10])
            cards.append(card_text)
        return cards, sources

    def _edges_for_members(self, members: List[str], max_edges: int) -> List[Dict]:
        collected: List[Dict] = []
        for u, v, _, data in self.store.graph.edges(keys=True, data=True):
            if u in members or v in members:
                collected.append(data)
            if len(collected) >= max_edges:
                break
        return collected

    def answer(self, query: str, mode: str = "optimize", top_k_cards: int = 5, max_edges: int = 80) -> Dict:
        seeds = self.find_seed_nodes(query, limit=5)
        cards, sources = self._community_cards(seeds, top_k_cards=top_k_cards, max_edges=max_edges)
        if not cards:
            return {"answer": "未找到与问题相关的图谱证据。请尝试上传更多文档或使用更具体的关键词。", "sources": []}
        context = "\n\n".join(cards)
        prompt = build_answer_prompt(query=query, context=context, mode=mode)
        answer = self.llm.chat(system=SYSTEM_PROMPT, user=prompt)
        return {"answer": answer, "sources": sources}

    def _node_label(self, node_data: Dict) -> str:
        return f"{node_data.get('name')}[{node_data.get('type')}]"
