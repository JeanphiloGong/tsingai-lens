import logging

from domain.query import QueryResult, SourceItem
from graphrag.retriever import GraphRetriever

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, graph_retriever: GraphRetriever):
        self.graph_retriever = graph_retriever

    def query(self, query: str, mode: str, top_k_cards: int, max_edges: int) -> QueryResult:
        logger.info(
            "开始图谱问答，query=%s，mode=%s，top_k_cards=%s，max_edges=%s",
            query,
            mode,
            top_k_cards,
            max_edges,
        )
        raw = self.graph_retriever.answer(query=query, mode=mode, top_k_cards=top_k_cards, max_edges=max_edges)
        result = QueryResult(
            answer=raw["answer"],
            sources=[SourceItem(**s) for s in raw.get("sources", [])],
        )
        logger.info("图谱问答完成，answer_len=%s，sources_count=%s", len(result.answer), len(result.sources))
        return result
