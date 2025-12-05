import json
from typing import Dict, List, Tuple

from graphrag.prompts import build_extraction_prompt
from graphrag.schema import Source
from graphrag.store import GraphStore
from services.llm_client import LLMClient


def _safe_parse_json(text: str) -> List[Dict]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        return []
    return []


class GraphBuilder:
    """Chunk-level extractor that builds the graph from documents."""

    def __init__(self, store: GraphStore, llm: LLMClient):
        self.store = store
        self.llm = llm

    # 创建关系
    def extract_triples(self, text: str, meta: Dict) -> List[Dict]:
        prompt = build_extraction_prompt(text=text)
        raw = self.llm.chat(system="You are an information extraction assistant.", user=prompt, temperature=0.2)
        triples = _safe_parse_json(raw)
        if not triples:
            # minimal fallback triple to keep graph connected
            # 如果模型没有返回三元组，就人工插入保证图不会断裂
            triples = [
                {
                    "head": "Paragraph",
                    "head_type": "Context",
                    "relation": "mentions",
                    "tail": meta.get("source", "document"),
                    "tail_type": "Source",
                    "confidence": 0.1,
                }
            ]
        return triples

    def ingest_chunks(self, chunked: List[Tuple[str, Dict]], doc_id: str, source: str) -> None:
        for chunk_text, meta in chunked:
            meta = dict(meta)
            meta["doc_id"] = doc_id
            meta["source"] = source
            triples = self.extract_triples(chunk_text, meta)
            self._merge_triples(triples, chunk_text, meta)
        self.store.save()

    def _merge_triples(self, triples: List[Dict], chunk_text: str, meta: Dict) -> None:
        if not triples:
            # fallback: add a pseudo node for the chunk to keep traceability
            node_id = self.store.upsert_node(name="Chunk", type_="Context", attrs={"doc_ids": [meta["doc_id"]]})
            self.store.upsert_edge(
                head_id=node_id,
                tail_id=node_id,
                relation="mentions",
                sources=[Source(doc_id=meta["doc_id"], source=meta.get("source", ""), page=meta.get("page"), chunk_id=meta.get("chunk_id"), snippet=chunk_text)],
            )
            return

        for triple in triples:
            head = triple.get("head") or triple.get("subject")
            tail = triple.get("tail") or triple.get("object")
            relation = triple.get("relation") or triple.get("predicate") or triple.get("rel") or "related_to"
            head_type = triple.get("head_type") or triple.get("subject_type") or "Entity"
            tail_type = triple.get("tail_type") or triple.get("object_type") or "Entity"
            if not head or not tail:
                continue

            head_attrs = triple.get("head_attrs") or {}
            tail_attrs = triple.get("tail_attrs") or {}
            self.store.upsert_node(name=str(head), type_=str(head_type), attrs={"doc_ids": [meta["doc_id"]], **head_attrs})
            self.store.upsert_node(name=str(tail), type_=str(tail_type), attrs={"doc_ids": [meta["doc_id"]], **tail_attrs})

            edge_attrs = triple.get("attrs") or {}
            source = Source(
                doc_id=meta["doc_id"],
                source=meta.get("source", ""),
                page=meta.get("page"),
                chunk_id=meta.get("chunk_id"),
                snippet=chunk_text,
                score=triple.get("confidence"),
            )
            self.store.upsert_edge(
                head_id=self.store._node_key(str(head), str(head_type)),
                tail_id=self.store._node_key(str(tail), str(tail_type)),
                relation=str(relation),
                attrs=edge_attrs,
                sources=[source],
            )
